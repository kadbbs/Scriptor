"""Story direction, prose composition, independent critique and manuscript revision."""

from . import prompts
from .errors import EvidenceError, LiteraryError, ReviewRejected, StructuredOutputError
from .evidence import render_sources, sources_for
from .models import LiteraryReview, NarrativeBrief
from .repository import dump

PIPELINE_VERSION = "narrative-2"


class NarrativeEngine:
    def __init__(self, model, budget, context, phase, artifacts):
        self.model, self.budget = model, budget
        self.context, self.phase, self.artifacts = context, phase, artifacts

    def _prompt(self, instructions, focus, suffix="", label="narrative_context"):
        reserve = len(instructions) + len(suffix) + 200
        if reserve >= self.budget:
            raise LiteraryError(
                "全文与文学审稿材料超出预算；候选已保留，请增加 SCRIPTOR_CONTEXT_CHARS"
            )
        return self.context(focus, self.budget - reserve, label) + suffix

    @staticmethod
    def needs_revision(report):
        return (
            report.verdict == "revise"
            or any(i.severity == "major" or i.category == "continuity" for i in report.issues)
            or min(report.causality, report.character, report.scene, report.voice) < 3
        )

    def _critique(self, focus, candidate, revision):
        sources = sources_for(candidate)
        ids = {s.id for s in sources}
        base = "\n【本章全文】\n" + render_sources(sources)
        feedback = ""
        for attempt in range(3):
            self.phase(
                "独立文学审稿：因果、人物、场景与行文" if not attempt else "校正文学审稿的问题定位"
            )
            record = {"revision": revision, "attempt": attempt + 1}
            self.artifacts.setdefault("literary_passes", []).append(record)
            try:
                prompt = self._prompt(
                    prompts.LITERARY_REVIEW, focus, base + feedback, "literary_context"
                )
                report = self.model.structured(
                    prompts.EDITOR, prompts.LITERARY_REVIEW + "\n" + prompt, LiteraryReview
                )
                record["report"] = report.model_dump()
                for issue in report.issues:
                    if (
                        issue.severity == "major" or issue.category == "continuity"
                    ) and not issue.source_ids:
                        raise EvidenceError("文学审稿要求修订的问题必须指向实际正文片段")
                    if any(i not in ids for i in issue.source_ids):
                        raise EvidenceError("文学审稿引用了不存在的正文片段")
                if self.needs_revision(report) and not report.issues and not report.revision_plan:
                    raise EvidenceError("文学审稿要求改稿，但未提供具体问题或修改方案")
                record["status"] = "revise" if self.needs_revision(report) else "accepted"
                self.artifacts["literary_review"] = report.model_dump()
                return report, sources
            except (EvidenceError, StructuredOutputError) as exc:
                record.update(status="invalid_review", error=str(exc))
                if attempt == 2:
                    raise EvidenceError(f"文学审稿结构修复仍未通过：{exc}") from exc
                feedback = "\n【修复审稿结构，不要改正文】\n" + str(exc)[:600]

    def run(self, plan, candidate=None, allow_rewrite=True, prior_brief=None, repair_notes=None):
        brief = NarrativeBrief.model_validate(prior_brief) if prior_brief else None
        if candidate is None and brief is None:
            self.phase("叙事导演：承接前因、人物选择与本章回报")
            focus = {"coarse_plan_not_binding": plan, "factual_revision_notes": repair_notes}
            prompt = self._prompt(prompts.CHAPTER_DIRECTOR, focus, label="director_context")
            brief = self.model.structured(
                prompts.EDITOR, prompts.CHAPTER_DIRECTOR + "\n" + prompt, NarrativeBrief
            )
        if brief:
            self.artifacts["narrative_brief"] = brief.model_dump()
        focus = {
            "chapter_brief": brief.model_dump() if brief else plan,
            "factual_revision_notes": repair_notes,
        }
        if candidate is None:
            self.phase("主笔：写成完整场景与人物行动")
            prompt = self._prompt(prompts.WRITE, focus, label="author_context")
            candidate = self.model.text(prompts.WRITE, prompt)
        for revision in range(3):
            self.artifacts["candidate"] = candidate
            if not candidate.strip() or len(candidate) > 60000:
                raise ReviewRejected("正文为空或超过 60000 字符，候选未采纳")
            self.artifacts.setdefault("manuscripts", []).append(
                {"revision": revision, "content": candidate}
            )
            report, sources = self._critique(focus, candidate, revision)
            if not self.needs_revision(report):
                return candidate, brief, report
            if not allow_rewrite or revision == 2:
                issues = "；".join(i.diagnosis for i in report.issues if i.severity == "major")
                raise LiteraryError(
                    "文学审稿未通过，正文未采纳："
                    + (issues or "；".join(report.revision_plan))[:700]
                )
            self.phase(f"主笔修订（{revision + 1}/2）：补因果与动机，保留有效段落")
            used = {i for issue in report.issues for i in issue.source_ids}
            notes = {
                "editor": report.model_dump(),
                "located_excerpts": [{"id": s.id, "text": s.text} for s in sources if s.id in used],
            }
            suffix = "\n【独立责编意见】\n" + dump(notes) + "\n【待修订完整原稿】\n" + candidate
            prompt = self._prompt(prompts.REVISE_PROSE, focus, suffix, "revision_context")
            candidate = self.model.text(prompts.REVISE_PROSE, prompt)
