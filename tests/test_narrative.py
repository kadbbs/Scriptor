import pytest

from scriptor.context import build_context
from scriptor.errors import EvidenceError, LiteraryError

from .conftest import literary_review, narrative_brief, prepare, review


def criticism(source_id=1):
    report = literary_review()
    return type(report).model_validate(
        {
            **report.model_dump(),
            "verdict": "revise",
            "causality": 2,
            "issues": [
                {
                    "category": "causality",
                    "severity": "major",
                    "source_ids": [source_id],
                    "diagnosis": "人物尚在旧港，却突然出现在灯塔，没有出海的原因和过程",
                    "revision": "让来信导致出海决定，补上换船的行动与代价",
                }
            ],
            "revision_plan": ["保留有效对白，补齐从旧港到灯塔的行动链"],
        }
    )


@pytest.mark.parametrize("minor_continuity", [False, True])
def test_editor_revises_existing_manuscript_instead_of_generating_unrelated_text(
    setup, minor_continuity
):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    original = "林海在旧港等船。下一刻，他已站上灯塔。"
    revised = "林海用修好的水泵换了船票。半天后，他沿码头的梯子登上灯塔。"
    model.outputs += [original, revised, review(revised, achieved=False)]
    report = criticism()
    if minor_continuity:
        report.verdict, report.causality = "accept", 4
        report.issues[0].severity, report.issues[0].category = "minor", "continuity"
    model.literary_outputs = [report, literary_review()]
    result = svc.step(book_id)
    assert result["content"] == revised
    revision_prompt = next(p for p in model.prompts if "【待修订完整原稿】" in p)
    assert original in revision_prompt
    assert "补上换船的行动与代价" in revision_prompt
    artifacts = svc.repo.runs(book_id)[0]["artifacts"]
    assert [d["content"] for d in artifacts["manuscripts"]] == [original, revised]
    assert len(svc.repo.history(book_id, 1)) == 1


def test_manual_edits_are_not_silently_rewritten_by_agent(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    content = "他在旧港。下一刻，他已经抵达灯塔。"
    model.literary_outputs = [criticism()]
    with pytest.raises(LiteraryError, match="文学审稿未通过"):
        svc.write(book_id, 1, content=content)
    assert model.outputs == []
    assert svc.repo.runs(book_id)[0]["artifacts"]["candidate"] == content
    assert svc.repo.get(book_id)["total_chapters"] == 0


def test_exhausted_literary_revision_does_not_restart_the_outer_writer_loop(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += ["他瞬间到了灯塔。"] * 3
    model.literary_outputs = [criticism()] * 3
    with pytest.raises(LiteraryError):
        svc.step(book_id)
    assert model.outputs == []
    assert len(svc.repo.runs(book_id)) == 3  # setup + one bounded creative process
    assert len(svc.repo.runs(book_id)[0]["artifacts"]["manuscripts"]) == 3
    assert svc.repo.get(book_id)["total_chapters"] == 0


def test_invalid_editor_locations_are_repaired_without_changing_prose(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += ["林海决定动身。", review("林海决定动身。", achieved=False)]
    model.literary_outputs = [criticism(99999), literary_review()]
    assert svc.step(book_id)["content"] == "林海决定动身。"
    artifacts = svc.repo.runs(book_id)[0]["artifacts"]
    assert len(artifacts["manuscripts"]) == 1
    assert artifacts["literary_passes"][0]["status"] == "invalid_review"


def test_unlocatable_criticism_never_becomes_an_author_rewrite(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += ["原文。"]
    model.literary_outputs = [criticism(99999)] * 3
    with pytest.raises(EvidenceError):
        svc.step(book_id)
    assert not model.outputs
    assert len(svc.repo.runs(book_id)[0]["artifacts"]["manuscripts"]) == 1


def test_refined_scene_plan_and_narrative_memory_are_saved_only_on_acceptance(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    brief = narrative_brief().model_copy(update={"title": "一张有代价的船票"})
    model.director_outputs = [brief]
    model.outputs += [
        "他修好水泵，换到了船票。",
        review("他修好水泵，换到了船票。", achieved=False),
    ]
    svc.step(book_id)
    book = svc.repo.get(book_id)
    assert book["plans"][0]["data"]["title"] == "一张有代价的船票"
    assert book["chapters"][0]["title"] == "一张有代价的船票"
    assert book["chapters"][0]["review"]["narrative_state"]["next_hook"] == "寻找船"
    context, _ = build_context(book, 2, 28000)
    assert "他修好水泵，换到了船票。" in context
    assert "寻找船" in context


def test_next_chapter_keeps_the_beginning_and_ending_of_previous_prose(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    content = "姐姐在开头留下的独特暗号。" + "远处船笛响了。" * 250 + "船票到了手里。"
    model.outputs += [content, review("船票到了手里。", achieved=False)]
    svc.write(book_id, 1)
    context, trace = build_context(svc.repo.get(book_id), 2, 28000)
    assert "姐姐在开头留下的独特暗号。" in context
    assert "船票到了手里。" in context
    assert '"prose_is_complete":true' in context
    assert trace["characters_used"] <= 28000


def test_contradictory_editor_acceptance_cannot_bypass_major_or_low_score():
    from scriptor.narrative import NarrativeEngine

    major = criticism().model_copy(update={"verdict": "accept", "causality": 4})
    low_score = literary_review().model_copy(update={"voice": 2})
    assert NarrativeEngine.needs_revision(major)
    assert NarrativeEngine.needs_revision(low_score)
    continuity = criticism().model_dump()
    continuity.update(verdict="accept", causality=4)
    continuity["issues"][0].update(category="continuity", severity="minor")
    assert NarrativeEngine.needs_revision(type(major).model_validate(continuity))
    assert not NarrativeEngine.needs_revision(literary_review())
