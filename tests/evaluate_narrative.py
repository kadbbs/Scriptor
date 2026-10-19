"""Opt-in paid model evaluation on an isolated copy of an existing book.

uv run python -m tests.evaluate_narrative --book-id ID --output data/evaluations/run-1
This module is never collected by pytest. Outputs contain private manuscript material.
"""

import argparse
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from scriptor.config import Settings
from scriptor.errors import ScriptorError
from scriptor.llm import create_model
from scriptor.repository import Repository
from scriptor.service import StoryService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--chapters", type=int, default=2, choices=range(1, 11))
    args = parser.parse_args()
    settings = Settings.from_env()
    folder = args.output.resolve()
    if folder.exists() and any(folder.iterdir()):
        parser.error("输出目录必须为空，避免覆盖已有验证结果")
    folder.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(folder / "evaluation.db") as target:
            source.backup(target)
    settings = replace(settings, database=folder / "evaluation.db")
    repo = Repository(settings.database)
    before = repo.get(args.book_id)["total_chapters"]
    model = create_model(settings)
    service = StoryService(repo, model, settings)
    checkpoint = service._checkpoint

    def phase(book_id, message):
        print(message, flush=True)
        checkpoint(book_id, message)

    service._checkpoint = phase
    failed = False
    try:
        for _ in range(args.chapters):
            result = service.step(args.book_id)
            if result.get("finished"):
                print("作品已完结", flush=True)
                break
            number = result["number"]
            (folder / f"chapter-{number:03d}.md").write_text(
                f"# {result['title']}\n\n{result['content']}\n", encoding="utf-8"
            )
            (folder / f"chapter-{number:03d}-process.json").write_text(
                json.dumps(repo.runs(args.book_id)[0], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"第 {number} 章已通过文学与事实审核：{len(result['content'])} 字符", flush=True)
    except ScriptorError as exc:
        failed = True
        (folder / "failure-process.json").write_text(
            json.dumps(repo.runs(args.book_id)[0], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"验证停止：{exc}", flush=True)
    finally:
        model.close()
    after = repo.get(args.book_id)["total_chapters"]
    print(f"隔离副本新增 {after - before} 章；结果：{folder}", flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
