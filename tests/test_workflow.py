import pytest

from scriptor.context import build_context
from scriptor.errors import Conflict, ModelError, ReviewRejected, ScriptorError
from scriptor.evidence import render_sources, sources_for
from scriptor.models import Criterion, PlanBatch, PlanRequest, StageInput
from scriptor.repository import Repository

from .conftest import bible, plan, prepare, review


def test_workflow_and_export(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    content = "林海确认了姐姐的笔迹。"
    model.outputs += [content, review(content)]
    result = svc.write(book_id, 1)
    book = svc.inspect(book_id)
    assert book["total_words"] == len(content)
    assert book["progress"]["achieved"]
    assert book["memory"][0]["chapter"] == 1
    assert content in svc.export(book_id)
    assert result["version"] == 1
    assert all(r["status"] == "succeeded" for r in svc.repo.runs(book_id))
    assert Repository(svc.settings.database).get(book_id)["chapters"][0]["content"] == content


def test_rewrite_replaces_memory_counts_and_retains_history(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    old, new = "林海确认了姐姐的笔迹。", "他尚未认出笔迹。"
    model.outputs += [old, review(old), new, review(new, achieved=False, key="unconfirmed")]
    svc.write(book_id, 1)
    svc.write(book_id, 1, rewrite=True)
    book = svc.inspect(book_id)
    assert book["total_words"] == len(new)
    assert book["total_chapters"] == 1
    assert not book["progress"]["achieved"]
    assert [f["key"] for f in book["memory"]] == ["unconfirmed"]
    assert [r["content"] for r in svc.repo.history(book_id, 1)] == [old, new]


@pytest.mark.parametrize(
    "fault", ["quote", "contradiction", "criterion", "duplicate", "empty_evidence"]
)
def test_review_rejection_preserves_candidate_not_canon(setup, fault):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    content = "林海确认了姐姐的笔迹。"
    assessment = review(content)
    if fault == "quote":
        assessment.facts[0].evidence = "正文中没有这句话"
    elif fault == "contradiction":
        assessment.contradictions = ["人物无解释地复活"]
    elif fault == "criterion":
        assessment.criteria[0].criterion = "错误条件"
    elif fault == "duplicate":
        assessment.facts *= 2
    else:
        assessment.criteria[0].evidence = []
    model.outputs += [content, assessment, assessment, assessment]
    with pytest.raises(ReviewRejected):
        svc.write(book_id, 1)
    assert svc.repo.get(book_id)["total_chapters"] == 0
    failed = svc.repo.runs(book_id)[0]
    assert failed["status"] == "failed"
    assert failed["artifacts"]["candidate"] == content
    assert svc.repo.history(book_id, 1) == []


def test_model_failure_does_not_partially_save(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += ["候选正文", ModelError("审核接口暂时不可用")]
    revision = svc.repo.get(book_id)["revision"]
    with pytest.raises(ModelError):
        svc.write(book_id, 1)
    assert svc.repo.get(book_id)["revision"] == revision
    assert svc.repo.runs(book_id)[0]["artifacts"]["candidate"] == "候选正文"


def test_submit_candidate_skips_writer_but_still_reviews(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    content = "林海确认了姐姐的笔迹。"
    model.outputs += [review(content)]
    svc.write(book_id, 1, content=content)
    assert svc.inspect(book_id)["progress"]["achieved"]
    assert render_sources(sources_for(content)) in model.prompts[-1]


def test_replan_replaces_future_suffix(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id, count=3)
    model.outputs += [PlanBatch(chapters=[plan(2)])]
    svc.plan(book_id, PlanRequest(start=2, count=1))
    assert [p["number"] for p in svc.repo.get(book_id)["plans"]] == [1, 2]


@pytest.mark.parametrize("chapters", [[plan(2)], [plan(1), plan(1)], [plan(1, stage=2)]])
def test_invalid_model_plan_preserves_existing(setup, chapters):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += [PlanBatch(chapters=chapters)]
    with pytest.raises(Conflict):
        svc.plan(book_id, PlanRequest(start=1, count=1))
    assert len(svc.repo.get(book_id)["plans"]) == 1


def test_no_gaps_or_implicit_rewrite(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id, count=2)
    for number in (0, -1, 2, 100):
        with pytest.raises(Conflict):
            svc.write(book_id, number)
    model.outputs += ["林海确认了姐姐的笔迹。", review()]
    svc.write(book_id, 1)
    with pytest.raises(Conflict):
        svc.write(book_id, 1)
    with pytest.raises(Conflict):
        svc.plan(book_id, PlanRequest(start=1, count=1))
    with pytest.raises(Conflict):
        svc.bible(book_id)


def test_stage_transition_requires_evidence_confirmation_and_clears_future(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id, count=2)
    stage = StageInput(goal="抵达灯塔", setting="海上", acceptance=["登上灯塔"])
    with pytest.raises(Conflict):
        svc.advance(book_id, stage, True)
    model.outputs += ["林海确认了姐姐的笔迹。", review()]
    svc.write(book_id, 1)
    with pytest.raises(Conflict):
        svc.advance(book_id, stage, False)
    svc.advance(book_id, stage, True)
    book = svc.inspect(book_id)
    assert book["stage"] == 2
    assert book["stages"][0]["closed_at_chapter"] == 1
    assert [p["number"] for p in book["plans"]] == [1]
    assert not book["progress"]["achieved"]
    with pytest.raises(Conflict):
        svc.write(book_id, 1, rewrite=True)


def test_low_confidence_is_not_completion(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    assessment = review()
    assessment.confidence = 0.79
    model.outputs += ["林海确认了姐姐的笔迹。", assessment]
    svc.write(book_id, 1)
    assert not svc.inspect(book_id)["progress"]["achieved"]


def test_concurrent_change_rejects_stale_result(setup):
    svc, model, book_id = setup
    model.outputs += [bible()]

    def concurrent_edit():
        with svc.repo.connect() as conn:
            conn.execute("UPDATE books SET revision=revision+1 WHERE id=?", (book_id,))

    model.hook = concurrent_edit
    with pytest.raises(Conflict):
        svc.bible(book_id)
    assert svc.repo.get(book_id)["bible"] is None
    assert svc.repo.runs(book_id)[0]["artifacts"]["bible"]["world"] == "近未来港口"


def test_stale_editor_revision_is_rejected_before_model_call(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    with pytest.raises(Conflict, match="页面基于旧版本"):
        svc.write(book_id, 1, content="浏览器草稿", expected_revision=0)
    assert model.outputs == []
    assert svc.repo.get(book_id)["total_chapters"] == 0


def test_db_mutation_failure_rolls_back_all_changes(setup):
    svc, model, book_id = setup
    run_id, snapshot = svc.repo.start(book_id, "test")

    def mutate(conn):
        conn.execute("UPDATE books SET stage=5 WHERE id=?", (book_id,))
        raise RuntimeError("disk simulation")

    with pytest.raises(RuntimeError):
        svc.repo.commit(snapshot, run_id, mutate, {}, [])
    book = svc.repo.get(book_id)
    assert book["stage"] == 1
    assert book["revision"] == 0


def test_full_chapter_tail_reaches_reviewer(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    content = "前情。" * 1800 + "最后一行揭示笔迹。"
    assessment = review("最后一行揭示笔迹。")
    model.outputs += [content, assessment]
    svc.write(book_id, 1)
    assert render_sources(sources_for(content)) in model.prompts[-1]


def test_context_excludes_future_and_respects_budget(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id, count=2)
    model.outputs += ["林海确认了姐姐的笔迹。", review()]
    svc.write(book_id, 1)
    book = svc.repo.get(book_id)
    context, trace = build_context(book, before=1, budget=6000, focus={"task": "rewrite"})
    assert "林海确认了姐姐的笔迹。" not in context
    assert trace["characters_used"] <= 6000
    with pytest.raises(ScriptorError):
        build_context(book, before=1, budget=10)


def test_large_candidate_preserved_when_review_cannot_fit(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += ["文" * 30000]
    with pytest.raises(ReviewRejected):
        svc.write(book_id, 1)
    assert svc.repo.runs(book_id)[0]["artifacts"]["candidate"] == "文" * 30000


def test_rewrite_invalidates_future_plans(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id, count=3)
    content = "林海确认了姐姐的笔迹。"
    model.outputs += [content, review(content), review(content)]
    svc.write(book_id, 1)
    svc.write(book_id, 1, rewrite=True, content=content)
    assert [p["number"] for p in svc.repo.get(book_id)["plans"]] == [1]


def test_acceptance_accumulates_evidence_across_chapters(setup):
    svc, model, book_id = setup
    # Change the initial stage before writing, to exercise a two-criterion milestone.
    with svc.repo.connect() as conn:
        conn.execute(
            "UPDATE stages SET spec=? WHERE book_id=?",
            (
                StageInput(
                    goal="准备出海", setting="旧港", acceptance=["确认笔迹", "获得路线"]
                ).model_dump_json(),
                book_id,
            ),
        )
    prepare(svc, model, book_id, count=2)
    first = review()
    first.criteria.append(Criterion(criterion="获得路线", achieved=False, evidence=[]))
    model.outputs += ["林海确认了姐姐的笔迹。", first]
    svc.write(book_id, 1)
    assert not svc.inspect(book_id)["progress"]["achieved"]
    content = "林海找到了航行路线。"
    second = review(content)
    second.criteria = [
        Criterion(criterion="确认笔迹", achieved=False, evidence=[]),
        Criterion(criterion="获得路线", achieved=True, evidence=[content]),
    ]
    model.outputs += [content, second]
    svc.write(book_id, 2)
    progress = svc.inspect(book_id)["progress"]
    assert progress["achieved"]
    assert [c["evidence"][0]["chapter"] for c in progress["criteria"]] == [1, 2]


def test_arbitrary_stages_use_the_correct_current_goal(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    for stage_number in range(1, 5):
        criterion = "确认笔迹" if stage_number == 1 else f"完成第{stage_number}阶段"
        if stage_number > 1:
            model.outputs += [PlanBatch(chapters=[plan(stage_number, stage_number)])]
            svc.plan(book_id, PlanRequest(start=stage_number, count=1))
            assert f"目标{stage_number}" in model.prompts[-1]
        content = f"行动{stage_number}已经完成。"
        assessment = review(content)
        assessment.criteria[0].criterion = criterion
        model.outputs += [content, assessment]
        svc.write(book_id, stage_number)
        svc.advance(
            book_id,
            StageInput(
                goal=f"目标{stage_number + 1}",
                setting="海上",
                acceptance=[f"完成第{stage_number + 1}阶段"],
            ),
            True,
        )
    assert svc.inspect(book_id)["stage"] == 5
