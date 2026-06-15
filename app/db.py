import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import get_settings


def _db_path() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise ValueError("Only sqlite:/// DATABASE_URL is supported in this app.")
    path = Path(url.replace("sqlite:///", "", 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                genre TEXT NOT NULL DEFAULT '',
                premise TEXT NOT NULL,
                target_chapters INTEGER NOT NULL DEFAULT 500,
                chapter_words INTEGER NOT NULL DEFAULT 3000,
                bible TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                number INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                outline TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'outline',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, number),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            """
        )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1], strict=False)
        raise
