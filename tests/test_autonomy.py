import threading
import time

import pytest
from fastapi.testclient import TestClient

from scriptor.api import create_app
from scriptor.config import Settings
from scriptor.errors import Conflict, ModelError, ReviewRejected
from scriptor.models import Direction, IdeaInput, PlanBatch
from scriptor.repository import Repository
from scriptor.runner import AutoRunner
from scriptor.service import StoryService

from .conftest import FakeModel, blueprint, plan, review, stage_design


@pytest.fixture
def autonomous(tmp_path):
    settings = Settings(database=tmp_path / "auto.db")
    repo = Repository(settings.database)
    model = FakeModel()
    book_id = repo.create(
        IdeaInput(
            ideas="姐姐发来消失灯塔的检修单", points=["力量提升必须付出代价"], style="克制悬疑"
        )
    )["id"]
    return StoryService(repo, model, settings), model, book_id


def chapter_outputs(number=1, stage=1, achieved=True):
    content = "林海确认了姐姐的笔迹。"
    return [PlanBatch(chapters=[plan(number, stage)]), content, review(content, achieved)]


def wait_job(repo, book_id, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = repo.job(book_id, job_id)
        if job["status"] not in ("running", "stopping"):
            return job
        time.sleep(0.02)
    raise AssertionError("Job did not finish")


def test_only_ideas_points_style_are_required(autonomous):
    svc, model, book_id = autonomous
    before = svc.inspect(book_id)
    assert before["stage"] == 0 and before["stages"] == []
    assert not before["progress"]["achieved"]
    assert model.outputs == []
    model.outputs = [blueprint()]
    svc.conceive(book_id)
    book = svc.inspect(book_id)
    assert book["spec"]["title"] == "失约的灯塔"
    assert book["bible"]["systems"][0]["costs"] == "暴露身份"
    assert "必须付出代价" in model.prompts[0] and "克制悬疑" in model.prompts[0]
    assert book["stages"][0]["spec"]["development"]


def test_step_conceives_plans_and_writes_without_user_planning(autonomous):
    svc, model, book_id = autonomous
    model.outputs = [blueprint(), *chapter_outputs()]
    assert svc.step(book_id)["number"] == 1
    assert svc.inspect(book_id)["progress"]["achieved"]
    assert (
        len(model.prompts) == 6
    )  # conceive, plan, director, author, literary editor, fact auditor


def test_llm_directs_next_stage_then_decides_when_to_finish(autonomous):
    svc, model, book_id = autonomous
    model.outputs = [blueprint(), *chapter_outputs()]
    svc.step(book_id)
    model.outputs = [
        Direction(
            finished=False,
            rationale="主线未结束，进入下一地图",
            next_stage=stage_design("抵达灯塔"),
        ),
        *chapter_outputs(2, 2),
    ]
    assert svc.step(book_id)["number"] == 2
    assert svc.inspect(book_id)["stage"] == 2
    model.outputs = [Direction(finished=True, rationale="主线已收束", next_stage=None)]
    assert svc.step(book_id)["finished"]
    assert svc.inspect(book_id)["spec"]["status"] == "completed"
    assert svc.step(book_id)["finished"]
    assert not model.outputs
    with pytest.raises(Conflict):
        svc.write(book_id, 2, rewrite=True)


def test_invalid_cast_does_not_save_partial_design(autonomous):
    svc, model, book_id = autonomous
    invalid = blueprint()
    invalid.bible.characters[1].role = "protagonist"
    model.outputs = [invalid]
    with pytest.raises(Conflict, match="一名主角"):
        svc.conceive(book_id)
    assert svc.inspect(book_id)["bible"] is None
    assert svc.inspect(book_id)["stages"] == []


def test_step_repairs_review_failure_with_bounded_feedback(autonomous):
    svc, model, book_id = autonomous
    bad = review()
    bad.contradictions = ["人物无解释地复活"]
    model.outputs = [
        blueprint(),
        PlanBatch(chapters=[plan()]),
        "林海确认了姐姐的笔迹。",
        bad,
        "林海确认了姐姐的笔迹。",
        review(),
    ]
    svc.step(book_id)
    assert svc.inspect(book_id)["total_chapters"] == 1
    assert "人物无解释地复活" in model.prompts[-2]
    assert len([r for r in svc.repo.runs(book_id) if r["status"] == "failed"]) == 1


def test_auto_pause_after_current_operation_and_resume(autonomous):
    svc, model, book_id = autonomous
    entered, release = threading.Event(), threading.Event()
    model.outputs = [blueprint()]
    model.hook = lambda: (entered.set(), release.wait(4))
    runner = AutoRunner(svc.repo, lambda: model, svc.settings)
    try:
        job = runner.start(book_id, 3)
        assert entered.wait(2)
        with pytest.raises(Conflict):
            runner.start(book_id, 1)
        with pytest.raises(Conflict):
            svc.conceive(book_id)
        svc.repo.pause_job(book_id, job["id"])
        release.set()
        paused = wait_job(svc.repo, book_id, job["id"])
        assert paused["status"] == "paused" and paused["completed"] == 0
        assert svc.repo.get(book_id)["bible"] is not None
        model.outputs = chapter_outputs()
        resumed = runner.start(book_id, 1)
        completed = wait_job(svc.repo, book_id, resumed["id"])
        assert completed["status"] == "completed" and completed["completed"] == 1
    finally:
        release.set()
        runner.close()


def test_auto_failure_preserves_previous_state_and_candidate(autonomous):
    svc, model, book_id = autonomous
    model.outputs = [blueprint(), PlanBatch(chapters=[plan()]), "候选正文", ModelError("接口失败")]
    runner = AutoRunner(svc.repo, lambda: model, svc.settings)
    try:
        job = runner.start(book_id, 10)
        failed = wait_job(svc.repo, book_id, job["id"])
        assert failed["status"] == "failed" and failed["completed"] == 0
        assert svc.repo.get(book_id)["total_chapters"] == 0
        assert svc.repo.runs(book_id)[0]["artifacts"]["candidate"] == "候选正文"
    finally:
        runner.close()


def test_automatic_run_reuses_plans_and_keeps_writing_same_stage(autonomous):
    svc, model, book_id = autonomous
    content = "林海确认了姐姐的笔迹。"
    model.outputs = [
        blueprint(),
        PlanBatch(chapters=[plan(1), plan(2)]),
        content,
        review(content, achieved=False),
        content,
        review(content, achieved=False),
    ]
    runner = AutoRunner(svc.repo, lambda: model, svc.settings)
    try:
        job = runner.start(book_id, 2)
        result = wait_job(svc.repo, book_id, job["id"])
        assert result["status"] == "completed" and result["completed"] == 2
        assert svc.inspect(book_id)["stage"] == 1
        assert model.outputs == []
    finally:
        runner.close()


def test_automatic_repair_stops_after_two_rewrites(autonomous):
    svc, model, book_id = autonomous
    bad = review()
    bad.contradictions = ["人物无解释地复活"]
    model.outputs = [blueprint(), PlanBatch(chapters=[plan()])]
    for _ in range(3):
        model.outputs += ["林海确认了姐姐的笔迹。", bad]
    with pytest.raises(ReviewRejected):
        svc.step(book_id)
    assert svc.repo.get(book_id)["total_chapters"] == 0
    assert len([r for r in svc.repo.runs(book_id) if r["status"] == "failed"]) == 3


def test_worker_that_loses_lease_cannot_commit(autonomous):
    svc, model, book_id = autonomous
    job = svc.repo.create_job(book_id, 1)

    def lose_lease():
        with svc.repo.connect() as conn:
            conn.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job["id"],))

    model.hook = lose_lease
    model.outputs = [blueprint()]
    worker = StoryService(svc.repo, model, svc.settings, job_id=job["id"])
    with pytest.raises(Conflict, match="租约"):
        worker.conceive(book_id)
    assert svc.repo.get(book_id)["bible"] is None
    assert "blueprint" in svc.repo.runs(book_id)[0]["artifacts"]


def test_expired_job_is_unlocked_and_database_upgrade_preserves_books(autonomous):
    svc, model, book_id = autonomous
    job = svc.repo.create_job(book_id, 5)
    with svc.repo.connect() as conn:
        conn.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job["id"],))
        conn.execute("PRAGMA user_version=1")
    repo = Repository(svc.settings.database)
    assert repo.job(book_id, job["id"])["status"] == "interrupted"
    assert repo.get(book_id)["spec"]["ideas"] == "姐姐发来消失灯塔的检修单"
    model.outputs = [blueprint()]
    svc.conceive(book_id)


def test_idea_api_and_background_execution(tmp_path):
    model = FakeModel()
    model.outputs = [blueprint(), *chapter_outputs()]
    app = create_app(Settings(database=tmp_path / "api.db"), lambda: model)
    with TestClient(app) as client:
        created = client.post(
            "/api/books", json={"ideas": "灯塔来信", "points": ["成长有代价"], "style": "悬疑"}
        )
        assert created.status_code == 201
        base = "/api/books/" + created.json()["id"]
        assert client.get(base).json()["stage"] == 0
        started = client.post(base + "/auto", json={"chapters": 1})
        assert started.status_code == 202
        job = wait_job(app.state.repo, created.json()["id"], started.json()["id"])
        assert job["status"] == "completed"
        assert client.get(base + "/auto").json()[0]["completed"] == 1
        assert client.get(base).json()["total_chapters"] == 1
        assert client.post(base + "/auto", json={"chapters": 0}).status_code == 422


def test_auto_recovers_from_temporary_provider_failure(autonomous):
    from dataclasses import replace

    from scriptor.errors import TransientModelError

    svc, model, book_id = autonomous
    model.outputs = [TransientModelError("HTTP 503"), blueprint(), *chapter_outputs()]
    runner = AutoRunner(svc.repo, lambda: model, replace(svc.settings, retry_delay=0))
    try:
        job = runner.start(book_id, 1)
        done = wait_job(svc.repo, book_id, job["id"])
        assert done["status"] == "completed" and done["completed"] == 1
        assert svc.repo.get(book_id)["total_chapters"] == 1
        assert len([r for r in svc.repo.runs(book_id) if r["status"] == "failed"]) == 1
    finally:
        runner.close()


def test_temporary_retries_reuse_manuscript_after_review_failure(autonomous):
    from dataclasses import replace

    from scriptor.errors import TransientModelError

    svc, model, book_id = autonomous
    content = "林海确认了姐姐的笔迹。"
    model.outputs = [
        blueprint(),
        PlanBatch(chapters=[plan()]),
        content,
        TransientModelError("HTTP 503"),
        review(content),
    ]
    runner = AutoRunner(svc.repo, lambda: model, replace(svc.settings, retry_delay=0))
    try:
        job = runner.start(book_id, 1)
        done = wait_job(svc.repo, book_id, job["id"])
        assert done["status"] == "completed" and done["completed"] == 1
        runs = [r for r in svc.repo.runs(book_id) if r["operation"] in ("write", "edit")]
        assert runs[0]["artifacts"]["recovered_from"] == runs[1]["id"]
        assert len(svc.repo.history(book_id, 1)) == 1
        assert not model.outputs
    finally:
        runner.close()


def test_persistent_503_exhausts_bounded_retries(autonomous):
    from dataclasses import replace

    from scriptor.errors import TransientModelError

    svc, model, book_id = autonomous
    model.outputs = [TransientModelError("HTTP 503")] * 3
    runner = AutoRunner(svc.repo, lambda: model, replace(svc.settings, retry_delay=0))
    try:
        job = runner.start(book_id, 20)
        failed = wait_job(svc.repo, book_id, job["id"])
        assert failed["status"] == "failed" and failed["completed"] == 0
        assert len(svc.repo.runs(book_id)) == 3
        assert not model.outputs
        assert svc.repo.get(book_id)["bible"] is None
    finally:
        runner.close()


def test_pause_during_retry_wait_is_prompt_and_does_not_start_another_call(autonomous):
    from dataclasses import replace

    from scriptor.errors import TransientModelError

    svc, model, book_id = autonomous
    model.outputs = [TransientModelError("HTTP 503", retry_after=60), blueprint()]
    runner = AutoRunner(svc.repo, lambda: model, replace(svc.settings, retry_delay=60))
    try:
        job = runner.start(book_id, 20)
        deadline = time.monotonic() + 3
        while "秒后重试" not in svc.repo.job(book_id, job["id"])["phase"]:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        started = time.monotonic()
        svc.repo.pause_job(book_id, job["id"])
        paused = wait_job(svc.repo, book_id, job["id"])
        assert paused["status"] == "paused" and paused["completed"] == 0
        assert time.monotonic() - started < 1
        assert len(model.outputs) == 1
    finally:
        runner.close()


def test_invalid_structured_proposal_is_preserved_without_changing_book(autonomous):
    from scriptor.errors import StructuredOutputError

    svc, model, book_id = autonomous
    raw = "# CreativeBlueprint\n普通 Markdown 大纲"
    model.outputs = [
        StructuredOutputError("json_invalid", raw_output=raw, schema_name="CreativeBlueprint")
    ]
    with pytest.raises(StructuredOutputError):
        svc.conceive(book_id)
    run = svc.repo.runs(book_id)[0]
    assert run["artifacts"]["structured_candidate"] == {
        "schema": "CreativeBlueprint",
        "content": raw,
    }
    assert raw not in run["error"]
    assert svc.repo.get(book_id)["bible"] is None
