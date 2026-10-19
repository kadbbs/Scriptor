import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .errors import Conflict, NotFound, ScriptorError
from .models import CreateBook


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Repository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
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
                PRAGMA user_version=1;
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

    def create(self, request: CreateBook):
        book_id = uuid4().hex
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

    def start(self, book_id, operation):
        run_id = uuid4().hex
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            snapshot = self._snapshot(conn, book_id)
            conn.execute(
                "INSERT INTO runs(id,book_id,operation,base_revision) VALUES (?,?,?,?)",
                (run_id, book_id, operation, snapshot["revision"]),
            )
        return run_id, snapshot

    def commit(self, snapshot, run_id, mutate, artifacts, calls):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
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
