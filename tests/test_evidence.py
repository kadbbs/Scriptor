import pytest

from scriptor.errors import EvidenceError, ModelError, StructuredOutputError
from scriptor.evidence import render_sources, resolve_review, sources_for
from scriptor.models import PlanBatch, PlanRequest, SourceReview
from scriptor.runner import AutoRunner

from .conftest import plan, prepare
from .test_autonomy import wait_job


def source_review(source_id=1, criterion_id=1, achieved=True):
    return SourceReview.model_validate(
        {
            "summary": "主角确认来信",
            "confidence": 0.95,
            "contradictions": [],
            "facts": [
                {
                    "key": "letter",
                    "kind": "event",
                    "subject": "林海",
                    "detail": "确认来信",
                    "status": "resolved",
                    "source_id": source_id,
                }
            ],
            "criteria": [
                {
                    "criterion_id": criterion_id,
                    "achieved": achieved,
                    "source_ids": [source_id] if achieved else [],
                }
            ],
        }
    )


def test_sources_have_exact_offsets_and_cover_long_unicode_text():
    text = "  “灯亮了。”\r\n\r\n" + "甲。" * 1000 + "\n “信是真的。”"
    sources = sources_for(text)
    assert len(sources) > 5
    assert [s.id for s in sources] == list(range(1, len(sources) + 1))
    assert all(text[s.start : s.end] == s.text for s in sources)
    assert "".join("".join(s.text for s in sources).split()) == "".join(text.split())
    assert all(len(s.text) <= 360 for s in sources)


def test_references_become_real_manuscript_not_model_generated_quotes():
    text = "“是她的笔迹。”林海放下信纸。\n\n他抹去海图上的灰尘。"
    result = resolve_review(source_review(), sources_for(text), ["确认笔迹"])
    assert result.facts[0].evidence == "“是她的笔迹。”林海放下信纸。"
    assert result.criteria[0].criterion == "确认笔迹"
    assert all(q in text for c in result.criteria for q in c.evidence)


@pytest.mark.parametrize("source,criterion", [(999, 1), (1, 999)])
def test_out_of_range_reference_never_enters_canon(source, criterion):
    with pytest.raises(EvidenceError):
        resolve_review(source_review(source, criterion), sources_for("原文。"), ["确认笔迹"])


def test_review_repair_keeps_the_same_manuscript(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    text = "“是她的笔迹。”林海放下信纸。"
    model.outputs += [text, source_review(999), source_review()]
    result = svc.step(book_id)
    assert result["content"] == text
    assert len(model.prompts) == 7  # setup, director, author, literary editor, two evidence audits
    assert render_sources(sources_for(text)) in model.prompts[-1]
    assert "上次审核结构问题" in model.prompts[-1]
    run = svc.repo.runs(book_id)[0]
    assert [a["status"] for a in run["artifacts"]["review_attempts"]] == [
        "repair_required",
        "accepted",
    ]
    assert len(svc.repo.history(book_id, 1)) == 1


def test_exhausted_evidence_repairs_do_not_trigger_author_rewrites(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += ["正文。", source_review(999), source_review(999), source_review(999)]
    with pytest.raises(EvidenceError):
        svc.step(book_id)
    assert not model.outputs
    assert len(svc.repo.runs(book_id)) == 3  # two setup operations and ONE author attempt
    assert svc.repo.get(book_id)["total_chapters"] == 0
    assert svc.repo.runs(book_id)[0]["artifacts"]["candidate"] == "正文。"


def test_invalid_structured_review_is_repaired_without_rewriting(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += ["正文。", StructuredOutputError("SourceReview 格式错误"), source_review()]
    assert svc.step(book_id)["content"] == "正文。"


def test_criteria_are_ordered_by_program_not_model_wording():
    result = source_review()
    first = result.criteria[0].model_copy(update={"criterion_id": 2})
    result.criteria = [first, result.criteria[0]]
    resolved = resolve_review(result, sources_for("原文。"), ["条件一", "条件二"])
    assert [c.criterion for c in resolved.criteria] == ["条件一", "条件二"]


def test_resuming_auto_reuses_failed_audit_candidate_across_job_revisions(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += ["已生成的正文。", ModelError("审核接口失败")]
    runner = AutoRunner(svc.repo, lambda: model, svc.settings)
    try:
        first = runner.start(book_id, 1)
        assert wait_job(svc.repo, book_id, first["id"])["status"] == "failed"
        previous = svc.repo.runs(book_id)[0]
        model.outputs += [source_review()]
        second = runner.start(book_id, 1)
        assert wait_job(svc.repo, book_id, second["id"])["completed"] == 1
        assert svc.repo.get(book_id)["chapters"][0]["content"] == "已生成的正文。"
        assert svc.repo.runs(book_id)[0]["artifacts"]["recovered_from"] == previous["id"]
        assert not model.outputs
    finally:
        runner.close()


def test_replanned_chapter_does_not_reuse_a_stale_candidate(setup):
    svc, model, book_id = setup
    prepare(svc, model, book_id)
    model.outputs += ["旧大纲的正文。", ModelError("审核接口失败")]
    with pytest.raises(ModelError):
        svc.step(book_id)
    new_plan = plan()
    new_plan.title = "全新场景"
    model.outputs += [PlanBatch(chapters=[new_plan])]
    svc.plan(book_id, PlanRequest(start=1, count=1))
    model.outputs += ["新大纲的正文。", source_review()]
    assert svc.step(book_id)["content"] == "新大纲的正文。"
    assert "recovered_from" not in svc.repo.runs(book_id)[0]["artifacts"]
