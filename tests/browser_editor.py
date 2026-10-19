"""Optional real-browser smoke test; runs only against a temporary DB and fake model.

uv run --extra dev --with playwright python -m playwright install chromium
uv run --extra dev --with playwright python -m tests.browser_editor
"""

import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

from scriptor.api import create_app
from scriptor.config import Settings
from scriptor.models import Direction, PlanBatch

from .conftest import FakeModel, blueprint, plan, review, stage_design


def main():
    with tempfile.TemporaryDirectory(prefix="scriptor-browser-") as tmp:
        model = FakeModel()
        original = "林海确认了姐姐的笔迹。"
        replacement = "林海找到了姐姐留下的笔迹。"
        rejected = review(replacement)
        rejected.contradictions = ["笔迹前后不一致"]
        model.outputs = [
            blueprint(),
            PlanBatch(chapters=[plan()]),
            original,
            review(original),
            rejected,
            review(replacement),
            Direction(
                finished=False, rationale="进入下一阶段", next_stage=stage_design("抵达灯塔")
            ),
            PlanBatch(chapters=[plan(2, 2)]),
            original,
            review(original),
        ]
        model.hook = lambda: model.calls.append(
            {
                "provider": "anthropic",
                "model": "test-claude-diagnostics",
                "status": "end_turn",
                "usage": {"total_tokens": 30},
                "request": {
                    "schema": "CreativeBlueprint",
                    "native_schema": True,
                    "max_output_tokens": 12000,
                    "input_chars": 5000,
                    "system_chars": 159,
                },
            }
        )
        app = create_app(Settings(database=Path(tmp) / "test.db"), lambda: model)
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError("Preview failed to start")
                time.sleep(0.05)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("dialog", lambda dialog: dialog.accept())
                page.goto(f"http://127.0.0.1:{port}")
                expect(page.locator("#activity")).to_have_text("准备就绪")
                page.screenshot(path="/tmp/scriptor-home.png", full_page=True)
                page.locator("#welcome-create").click()
                form = page.locator("#book-form")
                for name, value in {
                    "ideas": "失踪姐姐的灯塔检修单",
                    "points": "升级必须付出代价",
                    "style": "克制悬疑",
                }.items():
                    form.locator(f"[name={name}]").fill(value)
                form.get_by_role("button", name="创建作品").click()
                expect(page.locator("#stage-label")).to_have_text("待构思")
                page.locator("#step").click()
                expect(page.locator("#content")).to_have_value(original)
                expect(page.locator("#book-title")).to_have_text("失约的灯塔")
                expect(page.locator("#review-panel")).to_contain_text("文学审稿")
                expect(page.locator("#review-panel")).to_contain_text("叙事接力")
                page.get_by_role("button", name="作品设定", exact=True).click()
                expect(page.locator("#bible-content")).to_contain_text("维修与信息")
                expect(page.locator("#bible-content")).to_contain_text("主角")
                page.get_by_role("button", name="写作", exact=True).click()
                expect(page.locator("#save-state")).to_have_text("已审核保存")
                page.locator("#content").fill(replacement)
                page.locator("#content").dispatch_event("input")
                page.reload()
                page.locator(".book-item").click()
                expect(page.locator("#content")).to_have_value(replacement)
                page.locator("#save").click()
                page.locator("#confirm-yes").click()
                expect(page.locator("#notice")).to_contain_text("审核发现实质矛盾")
                expect(page.locator("#content")).to_have_value(replacement)
                page.get_by_role("button", name="运行记录", exact=True).click()
                page.locator("[data-recover='0']").click()
                page.locator("#confirm-yes").click()
                expect(page.locator("#content")).to_have_value(replacement)
                page.locator("#save").click()
                page.locator("#confirm-yes").click()
                expect(page.locator("#save-state")).to_have_text("已审核保存")
                page.locator("#history").click()
                expect(page.locator("#history-content article")).to_have_count(2)
                page.locator("#history-dialog [data-close]").click()
                page.get_by_role("button", name="剧情记忆", exact=True).click()
                expect(page.locator("#memory-content")).to_contain_text(replacement)
                page.get_by_role("button", name="运行记录", exact=True).click()
                expect(page.locator("#runs-content article")).to_have_count(5)
                expect(page.locator("#runs-content")).to_contain_text("模型调用诊断")
                expect(page.locator("#runs-content")).to_contain_text("test-claude-diagnostics")
                expect(page.locator("#runs-content")).to_contain_text("本章因果与回报")
                page.locator("#advance").click()
                expect(page.locator("#stage-progress")).to_contain_text("确认笔迹")
                page.locator("#stage-submit").click()
                expect(page.locator("#stage-label")).to_have_text("阶段 2")
                page.locator("#auto-open").click()
                page.locator("#auto-form [name=chapters]").fill("1")
                page.locator("#auto-form").get_by_role("button", name="开始自动运行").click()
                expect(page.locator("#auto-label")).to_have_text("本次自动运行完成", timeout=15000)
                expect(page.locator("#auto-info")).to_contain_text("1 / 1")
                with page.expect_download() as downloaded:
                    page.locator("#export").click()
                assert downloaded.value.suggested_filename.endswith(".md")
                page.get_by_role("button", name="写作", exact=True).click()
                page.locator("[data-chapter='2']").click()
                page.screenshot(path="/tmp/scriptor-editor-desktop.png", full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path="/tmp/scriptor-editor-mobile.png", full_page=True)
                assert not errors, errors
                browser.close()
                print(
                    "Browser smoke passed: ideas-only creation, manual stepping, full LLM design, draft recovery, edit, failed candidate recovery, history, memory, autonomous stages, background auto execution, export, mobile layout"
                )
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()


if __name__ == "__main__":
    main()
