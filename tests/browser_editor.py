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
from scriptor.models import PlanBatch

from .conftest import FakeModel, bible, plan, review


def main():
    with tempfile.TemporaryDirectory(prefix="scriptor-browser-") as tmp:
        model = FakeModel()
        original = "林海确认了姐姐的笔迹。"
        replacement = "林海找到了姐姐留下的笔迹。"
        rejected = review(replacement)
        rejected.contradictions = ["笔迹前后不一致"]
        model.outputs = [
            bible(),
            PlanBatch(chapters=[plan()]),
            original,
            review(original),
            rejected,
            review(replacement),
        ]
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
                page.locator("#welcome-create").click()
                form = page.locator("#book-form")
                for name, value in {
                    "title": "失约的灯塔",
                    "genre": "悬疑",
                    "premise": "失踪姐姐的来信",
                    "goal": "确认来信",
                    "setting": "旧港",
                    "acceptance": "确认笔迹",
                }.items():
                    form.locator(f"[name={name}]").fill(value)
                form.get_by_role("button", name="创建作品").click()
                expect(page.locator("#book-title")).to_have_text("失约的灯塔")
                page.locator("#bible-generate").click()
                expect(page.locator("#bible-content")).to_contain_text("近未来港口")
                page.get_by_role("button", name="写作", exact=True).click()
                page.locator("#plan-open").click()
                page.locator("#plan-form [name=count]").fill("1")
                page.locator("#plan-form").get_by_role("button", name="生成规划").click()
                expect(page.locator("#chapter-title")).to_have_text("旧港口")
                page.locator("#generate").click()
                expect(page.locator("#content")).to_have_value(original)
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
                page.locator("#advance").click()
                expect(page.locator("#stage-progress")).to_contain_text("确认笔迹")
                stage = page.locator("#stage-form")
                stage.locator("[name=goal]").fill("抵达灯塔")
                stage.locator("[name=setting]").fill("海上")
                stage.locator("[name=acceptance]").fill("登上灯塔")
                stage.locator("[name=confirm]").check()
                page.locator("#stage-submit").click()
                expect(page.locator("#stage-label")).to_have_text("阶段 2")
                with page.expect_download() as downloaded:
                    page.locator("#export").click()
                assert downloaded.value.suggested_filename.endswith(".md")
                page.get_by_role("button", name="写作", exact=True).click()
                page.screenshot(path="/tmp/scriptor-editor-desktop.png", full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path="/tmp/scriptor-editor-mobile.png", full_page=True)
                assert not errors, errors
                browser.close()
                print(
                    "Browser smoke passed: create, bible, plan, generate, draft recovery, edit, history, memory, runs, stage, export, mobile layout"
                )
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()


if __name__ == "__main__":
    main()
