"""Resolve model-selected source IDs to immutable spans of the actual manuscript."""

import re
from dataclasses import dataclass

from .errors import EvidenceError
from .models import Criterion, Fact, Review, SourceReview


@dataclass(frozen=True)
class Source:
    id: int
    start: int
    end: int
    text: str


def sources_for(content: str, limit: int = 360) -> list[Source]:
    sources = []
    for line in re.finditer(r"[^\r\n]+", content):
        start, end = line.span()
        if not line.group().strip():
            continue
        while start < end:
            stop = min(start + limit, end)
            if stop < end:
                boundaries = list(re.finditer(r"[。！？!?；;]", content[start:stop]))
                if boundaries and boundaries[-1].end() >= limit // 2:
                    stop = start + boundaries[-1].end()
            text = content[start:stop]
            if text.strip():
                sources.append(Source(len(sources) + 1, start, stop, text))
            start = stop
    return sources


def render_sources(sources: list[Source]) -> str:
    return "\n".join(f"[P{s.id}] {s.text}" for s in sources)


def resolve_review(result: SourceReview, sources: list[Source], acceptance: list[str]) -> Review:
    by_id = {s.id: s for s in sources}

    def quote(source_id):
        if source_id not in by_id:
            raise EvidenceError(
                f"审核选择了不存在的正文片段 P{source_id}；有效编号为 1–{len(sources)}"
            )
        return by_id[source_id].text

    ids = [c.criterion_id for c in result.criteria]
    if sorted(ids) != list(range(1, len(acceptance) + 1)):
        raise EvidenceError("审核必须且只能覆盖每个验收编号一次，不得遗漏、重复或自行添加")
    facts = [
        Fact(**f.model_dump(exclude={"source_id"}), evidence=quote(f.source_id))
        for f in result.facts
    ]
    criteria = []
    for criterion in sorted(result.criteria, key=lambda c: c.criterion_id):
        if criterion.achieved and not criterion.source_ids:
            raise EvidenceError(f"验收项 {criterion.criterion_id} 声称达成但没有选择证据片段")
        if not criterion.achieved and criterion.source_ids:
            raise EvidenceError(f"未达成的验收项 {criterion.criterion_id} 必须使用空 source_ids")
        criteria.append(
            Criterion(
                criterion=acceptance[criterion.criterion_id - 1],
                achieved=criterion.achieved,
                evidence=[quote(i) for i in dict.fromkeys(criterion.source_ids)],
            )
        )
    return Review(
        summary=result.summary,
        facts=facts,
        contradictions=result.contradictions,
        criteria=criteria,
        confidence=result.confidence,
    )
