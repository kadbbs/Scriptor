import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .errors import Conflict, NotFound, ScriptorError
from .models import CreateBook, IdeaInput


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Repository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ScriptorError(f"不支持的数据库版本：{version}")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS books (
                    id TEXT PRIMARY KEY, spec TEXT NOT NULL, bible TEXT,
                    stage INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS stages (
                    book_id TEXT NOT NULL REFERENCES books(id), number INTEGER NOT NULL,
                    spec TEXT NOT NULL, closed_at_chapter INTEGER,
                    PRIMARY KEY(book_id, number)
                );
                CREATE TABLE IF NOT EXISTS plans (
                    book_id TEXT NOT NULL REFERENCES books(id), number INTEGER NOT NULL,
                    stage INTEGER NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(book_id, number)
                );
                CREATE TABLE IF NOT EXISTS chapters (
                    book_id TEXT NOT NULL REFERENCES books(id), number INTEGER NOT NULL,
                    stage INTEGER NOT NULL, version INTEGER NOT NULL,
                    title TEXT NOT NULL, content TEXT NOT NULL, review TEXT NOT NULL,
                    PRIMARY KEY(book_id, number)
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    book_id TEXT NOT NULL REFERENCES books(id), number INTEGER NOT NULL,
                    version INTEGER NOT NULL, stage INTEGER NOT NULL,
                    title TEXT NOT NULL, content TEXT NOT NULL, review TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(book_id, number, version)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id),
                    operation TEXT NOT NULL, base_revision INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running', error TEXT,
                    artifacts TEXT NOT NULL DEFAULT '{}', calls TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id),
                    status TEXT NOT NULL, target INTEGER NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
                    phase TEXT NOT NULL DEFAULT '准备运行', error TEXT, lease_until REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs(book_id)
                    WHERE status IN ('running','stopping');
                PRAGMA user_version=2;
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create(self, request: CreateBook | IdeaInput):
        book_id = uuid4().hex
        if isinstance(request, IdeaInput):
            spec = {
                "title": "新作品 · 待构思",
                "genre": "由 LLM 决定",
                "premise": request.ideas,
                "ideas": request.ideas,
                "points": request.points,
                "style": request.style,
                "chapter_words": 3000,
                "status": "idea",
                "autonomous": True,
            }
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO books(id,spec,stage) VALUES (?,?,0)", (book_id, dump(spec))
                )
            return self.get(book_id)
        if len(set(request.stage.acceptance)) != len(request.stage.acceptance):
            raise Conflict("阶段验收标准不能重复")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO books(id,spec) VALUES (?,?)", (book_id, request.book.model_dump_json())
            )
            conn.execute(
                "INSERT INTO stages(book_id,number,spec) VALUES (?,1,?)",
                (book_id, request.stage.model_dump_json()),
            )
        return self.get(book_id)

    def _snapshot(self, conn, book_id):
        row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if row is None:
            raise NotFound("书籍不存在")
        book = dict(row)
        book["spec"] = json.loads(book["spec"])
        book["bible"] = json.loads(book["bible"]) if book["bible"] else None
        for table in ("stages", "plans", "chapters"):
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE book_id=? ORDER BY number", (book_id,)
            ).fetchall()
            book[table] = [dict(row) for row in rows]
            for item in book[table]:
                for key in ("spec", "data", "review"):
                    if key in item:
                        item[key] = json.loads(item[key])
        book["total_chapters"] = len(book["chapters"])
        book["total_words"] = sum(len(ch["content"]) for ch in book["chapters"])
        return book

    def get(self, book_id):
        with self.connect() as conn:
            conn.execute("BEGIN")
            return self._snapshot(conn, book_id)

    def list(self):
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT b.id,b.spec,b.stage,b.revision,COUNT(c.number) AS total_chapters,
                       COALESCE(SUM(LENGTH(c.content)),0) AS total_words
                FROM books b LEFT JOIN chapters c ON b.id=c.book_id
                GROUP BY b.id ORDER BY b.created_at DESC,b.id
            """).fetchall()
            return [{**dict(r), "spec": json.loads(r["spec"])} for r in rows]

    def start(self, book_id, operation, job_id=None):
        run_id = uuid4().hex
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_jobs(conn)
            active = conn.execute(
                "SELECT id FROM jobs WHERE book_id=? AND status IN ('running','stopping')",
                (book_id,),
            ).fetchone()
            if active and active["id"] != job_id:
                raise Conflict("作品正在自动运行，请先暂停并等待当前步骤完成")
            snapshot = self._snapshot(conn, book_id)
            conn.execute(
                "INSERT INTO runs(id,book_id,operation,base_revision) VALUES (?,?,?,?)",
                (run_id, book_id, operation, snapshot["revision"]),
            )
        return run_id, snapshot

    def commit(self, snapshot, run_id, mutate, artifacts, calls, job_id=None):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if job_id:
                owned = conn.execute(
                    "SELECT 1 FROM jobs WHERE id=? AND book_id=? AND status IN ('running','stopping') AND lease_until>?",
                    (job_id, snapshot["id"], time.time()),
                ).fetchone()
                if not owned:
                    raise Conflict("自动任务已失去运行租约，候选保留但不能提交")
            changed = conn.execute(
                "UPDATE books SET revision=revision+1 WHERE id=? AND revision=?",
                (snapshot["id"], snapshot["revision"]),
            ).rowcount
            if changed != 1:
                raise Conflict("生成期间书籍已被修改；本次候选保留在 runs 中，请刷新后重试")
            mutate(conn)
            conn.execute(
                "UPDATE runs SET status='succeeded',artifacts=?,calls=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (dump(artifacts), dump(calls), run_id),
            )

    def fail(self, run_id, error, artifacts, calls):
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET status='failed',error=?,artifacts=?,calls=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (error, dump(artifacts), dump(calls), run_id),
            )

    def runs(self, book_id):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE book_id=? ORDER BY created_at DESC,rowid DESC", (book_id,)
            ).fetchall()
        return [
            {**dict(r), "artifacts": json.loads(r["artifacts"]), "calls": json.loads(r["calls"])}
            for r in rows
        ]

    def history(self, book_id, number):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM revisions WHERE book_id=? AND number=? ORDER BY version",
                (book_id, number),
            ).fetchall()
        return [{**dict(r), "review": json.loads(r["review"])} for r in rows]

    def recoverable_candidate(self, book_id, fingerprint):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,artifacts FROM runs WHERE book_id=? AND status='failed' ORDER BY rowid DESC LIMIT 12",
                (book_id,),
            ).fetchall()
        for row in rows:
            artifacts = json.loads(row["artifacts"])
            if (
                artifacts.get("draft_fingerprint") == fingerprint
                and artifacts.get("failure_kind") in ("review_structure", "model", "paused")
                and artifacts.get("candidate", "").strip()
            ):
                return {"run_id": row["id"], "content": artifacts["candidate"]}
        return None

    @staticmethod
    def _expire_jobs(conn):
        conn.execute(
            "UPDATE jobs SET status='interrupted',phase='运行中断，可重新启动',finished_at=CURRENT_TIMESTAMP WHERE status IN ('running','stopping') AND lease_until<?",
            (time.time(),),
        )

    def create_job(self, book_id, chapters):
        if not 1 <= chapters <= 500:
            raise Conflict("本次运行章数必须在 1–500 之间")
        job_id = uuid4().hex
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._snapshot(conn, book_id)
            self._expire_jobs(conn)
            if conn.execute(
                "SELECT 1 FROM jobs WHERE book_id=? AND status IN ('running','stopping')",
                (book_id,),
            ).fetchone():
                raise Conflict("该作品已经在自动运行")
            conn.execute(
                "INSERT INTO jobs(id,book_id,status,target,lease_until) VALUES (?,?,'running',?,?)",
                (job_id, book_id, chapters, time.time() + 30),
            )
            conn.execute("UPDATE books SET revision=revision+1 WHERE id=?", (book_id,))
        return self.job(book_id, job_id)

    def job(self, book_id, job_id):
        with self.connect() as conn:
            self._expire_jobs(conn)
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=? AND book_id=?", (job_id, book_id)
            ).fetchone()
            if not row:
                raise NotFound("自动任务不存在")
            return dict(row)

    def jobs(self, book_id):
        with self.connect() as conn:
            self._expire_jobs(conn)
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM jobs WHERE book_id=? ORDER BY created_at DESC,rowid DESC",
                    (book_id,),
                )
            ]

    def pause_job(self, book_id, job_id):
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='stopping',phase='暂停请求已收到，等待当前步骤完成' WHERE id=? AND book_id=? AND status='running'",
                (job_id, book_id),
            )
        return self.job(book_id, job_id)

    def heartbeat(self, job_id):
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET lease_until=? WHERE id=? AND status IN ('running','stopping')",
                (time.time() + 30, job_id),
            )

    def job_phase(self, job_id, phase):
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET phase=? WHERE id=? AND status='running'", (phase, job_id))

    def finish_job(self, job_id, status, completed, error=None):
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status=?,completed=?,error=?,phase=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    status,
                    completed,
                    error,
                    {"completed": "本次运行完成", "paused": "已暂停", "failed": "运行失败"}.get(
                        status, status
                    ),
                    job_id,
                ),
            )

    def job_completed(self, job_id, count):
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET completed=? WHERE id=?", (count, job_id))
