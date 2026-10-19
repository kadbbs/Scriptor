import json

from fastapi.testclient import TestClient

from scriptor.api import create_app
from scriptor.cli import main
from scriptor.config import Settings
from scriptor.models import PlanBatch

from .conftest import FakeModel, bible, plan, review


def test_api_create_generate_edit_export(tmp_path):
    model = FakeModel()
    app = create_app(Settings(database=tmp_path / "api.db"), lambda: model)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "长篇写作工作台" in page.text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/styles.css").status_code == 200
        assert client.get("/health").json()["api_format"] == "responses"
        created = client.post(
            "/api/books",
            json={
                "book": {"title": "灯塔", "genre": "悬疑", "premise": "姐姐来信"},
                "stage": {"goal": "确认来信", "setting": "旧港", "acceptance": ["确认笔迹"]},
            },
        )
        assert created.status_code == 201
        base = "/api/books/" + created.json()["id"]
        model.outputs += [bible(), PlanBatch(chapters=[plan()]), "林海确认了姐姐的笔迹。", review()]
        assert client.post(base + "/bible").status_code == 200
        assert client.post(base + "/plans", json={"start": 1, "count": 1}).status_code == 200
        assert client.post(base + "/chapters/1/generate", json={}).status_code == 200
        replacement = "笔迹尚未认出。"
        model.outputs += [review(replacement, achieved=False)]
        assert client.put(base + "/chapters/1", json={"content": replacement}).status_code == 200
        assert client.get(base).json()["total_words"] == len(replacement)
        assert len(client.get(base + "/chapters/1/history").json()) == 2
        assert replacement in client.get(base + "/export").text
        assert client.get(base + "/runs").json()[0]["status"] == "succeeded"
        assert client.post(base + "/plans", json={"start": 0}).status_code == 422
        assert client.post(base + "/chapters/1/generate", json={}).status_code == 409
        assert client.get("/api/books/missing").status_code == 404


def test_readonly_cli_and_create_need_no_api_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SCRIPTOR_DB", str(tmp_path / "cli.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_MODEL", "")
    payload = {
        "book": {"title": "灯塔", "genre": "悬疑", "premise": "来信"},
        "stage": {"goal": "确认来信", "setting": "旧港", "acceptance": ["确认笔迹"]},
    }
    path = tmp_path / "book.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["create", "--input", str(path)]) == 0
    book_id = json.loads(capsys.readouterr().out)["id"]
    assert main(["show", book_id]) == 0
    assert not json.loads(capsys.readouterr().out)["progress"]["achieved"]
    assert main(["bible", book_id]) == 1
    assert "OPENAI_MODEL" in capsys.readouterr().err
    assert main(["list"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
