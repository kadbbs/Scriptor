import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from .config import Settings
from .errors import ScriptorError
from .llm import create_model
from .models import CreateBook, IdeaInput, PlanRequest, StageInput
from .repository import Repository
from .runner import AutoRunner
from .service import StoryService


def parser():
    root = argparse.ArgumentParser(prog="scriptor", description="OpenAI / Anthropic 长篇小说工作流")
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="从点子、要点和风格 JSON 创建作品")
    create.add_argument("--input", type=Path, required=True)
    commands.add_parser("list", help="列出书籍")
    for name in ("show", "bible", "runs", "step", "conceive", "direct"):
        commands.add_parser(name).add_argument("book_id")
    auto = commands.add_parser("auto", help="自动构思、规划、写作及推进阶段，可用 Ctrl+C 请求暂停")
    auto.add_argument("book_id")
    auto.add_argument("--chapters", type=int, default=10, choices=range(1, 501), metavar="1..500")
    plan = commands.add_parser("plan", help="生成或替换未写章节的大纲后缀")
    plan.add_argument("book_id")
    plan.add_argument("--start", type=int, required=True)
    plan.add_argument("--count", type=int, default=5)
    for name in ("write", "edit", "history"):
        command = commands.add_parser(name)
        command.add_argument("book_id")
        command.add_argument("number", type=int)
        if name == "write":
            command.add_argument("--rewrite", action="store_true")
            command.add_argument(
                "--file", type=Path, help="提交手写正文或 runs 中保留的候选，仍需全文审核"
            )
        elif name == "edit":
            command.add_argument("--file", type=Path, required=True)
    advance = commands.add_parser("advance", help="验收完成后切换到任意下一阶段")
    advance.add_argument("book_id")
    advance.add_argument("--input", type=Path, required=True)
    advance.add_argument("--confirm", action="store_true")
    export = commands.add_parser("export")
    export.add_argument("book_id")
    export.add_argument("--output", type=Path)
    serve = commands.add_parser("serve", help="启动本地 HTTP API，交互文档 /docs")
    serve.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    serve.add_argument("--port", type=int, default=8000)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    model = None
    try:
        settings = Settings.from_env()
        if args.command == "serve":
            import uvicorn

            from .api import create_app

            uvicorn.run(create_app(settings), host=args.host, port=args.port)
            return 0
        repo = Repository(settings.database)
        model = create_model(settings)
        svc = StoryService(repo, model, settings)
        if args.command == "create":
            raw = json.loads(args.input.read_text(encoding="utf-8"))
            result = repo.create(
                IdeaInput.model_validate(raw) if "ideas" in raw else CreateBook.model_validate(raw)
            )
        elif args.command == "list":
            result = repo.list()
        elif args.command == "show":
            result = svc.inspect(args.book_id)
        elif args.command == "bible":
            result = svc.bible(args.book_id)
        elif args.command == "conceive":
            result = svc.conceive(args.book_id)
        elif args.command == "step":
            result = svc.step(args.book_id)
        elif args.command == "direct":
            result = svc.direct(args.book_id)
        elif args.command == "auto":
            runner = AutoRunner(repo, lambda: create_model(settings), settings)
            job = runner.start(args.book_id, args.chapters)
            try:
                try:
                    while repo.job(args.book_id, job["id"])["status"] in ("running", "stopping"):
                        time.sleep(0.5)
                except KeyboardInterrupt:
                    repo.pause_job(args.book_id, job["id"])
                    print("已请求暂停，等待当前步骤完成…", file=sys.stderr)
                    while repo.job(args.book_id, job["id"])["status"] in ("running", "stopping"):
                        time.sleep(0.5)
                result = repo.job(args.book_id, job["id"])
            finally:
                runner.close()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["status"] in ("failed", "interrupted") else 0
        elif args.command == "plan":
            result = svc.plan(args.book_id, PlanRequest(start=args.start, count=args.count))
        elif args.command == "write":
            result = svc.write(
                args.book_id,
                args.number,
                rewrite=args.rewrite,
                content=args.file.read_text(encoding="utf-8") if args.file else None,
            )
        elif args.command == "edit":
            result = svc.write(
                args.book_id,
                args.number,
                rewrite=True,
                content=args.file.read_text(encoding="utf-8"),
            )
        elif args.command == "advance":
            result = svc.advance(
                args.book_id,
                StageInput.model_validate_json(args.input.read_text(encoding="utf-8")),
                args.confirm,
            )
        elif args.command == "runs":
            repo.get(args.book_id)
            result = repo.runs(args.book_id)
        elif args.command == "history":
            repo.get(args.book_id)
            result = repo.history(args.book_id, args.number)
        elif args.command == "export":
            content = svc.export(args.book_id)
            if args.output:
                args.output.write_text(content, encoding="utf-8")
            else:
                print(content, end="")
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ScriptorError, ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        if model is not None:
            model.close()


if __name__ == "__main__":
    raise SystemExit(main())
