from pathlib import Path
from json import JSONDecodeError

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError
from pydantic import BaseModel, Field

from . import llm
from .db import connect, init_db, row_to_dict


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Novel Agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    genre: str = Field(default="", max_length=80)
    premise: str = Field(min_length=1)
    target_chapters: int = Field(default=500, ge=1, le=2000)
    chapter_words: int = Field(default=3000, ge=500, le=10000)


class OutlineRequest(BaseModel):
    start: int = Field(default=1, ge=1)
    count: int = Field(default=20, ge=1, le=80)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/projects")
def list_projects():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [row_to_dict(row) for row in rows]


@app.post("/api/projects")
def create_project(payload: ProjectCreate):
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects (title, genre, premise, target_chapters, chapter_words)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payload.title, payload.genre, payload.premise, payload.target_chapters, payload.chapter_words),
        )
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


def get_project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    project = row_to_dict(row)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/api/projects/{project_id}")
def read_project(project_id: int):
    project = get_project(project_id)
    with connect() as conn:
        chapters = conn.execute(
            "SELECT * FROM chapters WHERE project_id = ? ORDER BY number ASC", (project_id,)
        ).fetchall()
    project["chapters"] = [row_to_dict(row) for row in chapters]
    return project


@app.post("/api/projects/{project_id}/bible")
async def generate_bible(project_id: int):
    project = get_project(project_id)
    try:
        bible = await llm.expand_bible(project)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(status_code=502, detail=f"模型接口调用失败：{exc}") from exc
    with connect() as conn:
        conn.execute(
            "UPDATE projects SET bible = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (bible, project_id),
        )
    return {"bible": bible}


@app.post("/api/projects/{project_id}/outline")
async def generate_outline(project_id: int, payload: OutlineRequest):
    project = get_project(project_id)
    if not project["bible"]:
        raise HTTPException(status_code=400, detail="请先生成作品设定。")

    with connect() as conn:
        previous = conn.execute(
            """
            SELECT * FROM chapters
            WHERE project_id = ? AND number < ?
            ORDER BY number ASC
            """,
            (project_id, payload.start),
        ).fetchall()

    try:
        data = await llm.generate_outline_batch(
            project,
            [row_to_dict(row) for row in previous],
            payload.start,
            payload.count,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(status_code=502, detail=f"模型接口调用失败：{exc}") from exc
    except JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"模型返回的大纲不是可解析 JSON：{exc}") from exc
    chapters = data.get("chapters", [])
    if not chapters:
        raise HTTPException(status_code=502, detail="模型没有返回可用章节大纲。")

    with connect() as conn:
        for item in chapters:
            conn.execute(
                """
                INSERT INTO chapters (project_id, number, title, outline, status)
                VALUES (?, ?, ?, ?, 'outline')
                ON CONFLICT(project_id, number) DO UPDATE SET
                    title = excluded.title,
                    outline = excluded.outline,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (project_id, int(item["number"]), item.get("title", ""), item.get("outline", "")),
            )
        conn.execute("UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))

    return {"chapters": chapters}


@app.post("/api/projects/{project_id}/chapters/{number}/content")
async def generate_chapter_content(project_id: int, number: int):
    project = get_project(project_id)
    with connect() as conn:
        chapter = conn.execute(
            "SELECT * FROM chapters WHERE project_id = ? AND number = ?", (project_id, number)
        ).fetchone()
        recent = conn.execute(
            """
            SELECT * FROM chapters
            WHERE project_id = ? AND number < ? AND content != ''
            ORDER BY number DESC LIMIT 3
            """,
            (project_id, number),
        ).fetchall()

    chapter_data = row_to_dict(chapter)
    if not chapter_data:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if not chapter_data["outline"]:
        raise HTTPException(status_code=400, detail="请先生成本章大纲。")

    try:
        content = await llm.generate_chapter(
            project,
            chapter_data,
            list(reversed([row_to_dict(row) for row in recent])),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(status_code=502, detail=f"模型接口调用失败：{exc}") from exc
    with connect() as conn:
        conn.execute(
            """
            UPDATE chapters
            SET content = ?, status = 'drafted', updated_at = CURRENT_TIMESTAMP
            WHERE project_id = ? AND number = ?
            """,
            (content, project_id, number),
        )
    return {"content": content}


@app.get("/api/projects/{project_id}/chapters/{number}")
def read_chapter(project_id: int, number: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM chapters WHERE project_id = ? AND number = ?", (project_id, number)
        ).fetchone()
    chapter = row_to_dict(row)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter
