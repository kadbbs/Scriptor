import json
import re

import pytest

from scriptor.config import Settings
from scriptor.models import (
    Bible,
    ChapterPlan,
    CreateBook,
    CreativeBlueprint,
    LiteraryReview,
    NarrativeBrief,
    PlanBatch,
    Review,
    SourceReview,
    StageDesign,
)
from scriptor.repository import Repository
from scriptor.service import StoryService


def bible():
    return Bible.model_validate(
        {
            "world": "近未来港口",
            "rules": ["灯塔只能乘船抵达"],
            "characters": [{"name": "林海", "motivation": "寻找姐姐", "constraints": "不能游泳"}],
            "arcs": [{"title": "检修单", "conflict": "真假难辨", "payoff": "路线出现"}],
            "ending_direction": "找到姐姐失踪的原因",
        }
    )


def plan(number=1, stage=1):
    return ChapterPlan.model_validate(
        {
            "number": number,
            "stage": stage,
            "title": "旧港口",
            "objective": "验证检修单",
            "characters": ["林海"],
            "hook": "海上出现灯光",
            "scenes": [
                {
                    "viewpoint": "林海",
                    "location": "旧港",
                    "objective": "找到船",
                    "conflict": "港口封锁",
                    "change": "发现线索",
                }
            ],
        }
    )


def stage_design(goal="确认来信", criterion="确认笔迹"):
    return StageDesign(
        goal=goal,
        setting="旧港",
        acceptance=[criterion],
        development="以维修技能换取信息，冒险暴露身份而非直接获得力量",
        exit_hook="航线将指向灯塔",
    )


def blueprint():
    world = bible().model_dump()
    world.update(
        {
            "characters": [
                {
                    "name": "林海",
                    "role": "protagonist",
                    "motivation": "寻找姐姐",
                    "constraints": "不能游泳",
                    "growth": "从独行到信任伙伴",
                    "relationships": "姐姐的弟弟",
                },
                {
                    "name": "阿舟",
                    "role": "supporting",
                    "motivation": "保住船",
                    "constraints": "负债",
                    "growth": "承担责任",
                    "relationships": "林海的向导",
                },
                {
                    "name": "站长",
                    "role": "antagonist",
                    "motivation": "控制航线",
                    "constraints": "怕失去权力",
                    "growth": "逐渐暴露弱点",
                    "relationships": "阻止林海",
                },
            ],
            "maps": [
                {
                    "name": "旧港",
                    "identity": "维修与走私共存",
                    "conflict": "封锁航线",
                    "unlock_condition": "解开检修单",
                }
            ],
            "systems": [
                {
                    "name": "维修与信息",
                    "rules": "技能换取资源",
                    "levels": ["学徒", "独立维修员"],
                    "advancement": "实际修好装置",
                    "costs": "暴露身份",
                    "limits": "不能凭空制造材料",
                }
            ],
            "central_conflict": "真相与航线垄断",
            "growth_strategy": "技能、信任与资源相互制约",
            "narrative_strategy": "用行动揭露信息，保持克制悬疑",
        }
    )
    return CreativeBlueprint(
        title="失约的灯塔",
        genre="近未来悬疑",
        chapter_words=3000,
        bible=world,
        first_stage=stage_design(),
    )


def review(content="林海确认了姐姐的笔迹。", achieved=True, key="handwriting"):
    return Review.model_validate(
        {
            "summary": content,
            "facts": [
                {
                    "key": key,
                    "kind": "event",
                    "subject": "林海",
                    "detail": content,
                    "status": "resolved",
                    "evidence": content,
                }
            ],
            "contradictions": [],
            "criteria": [
                {
                    "criterion": "确认笔迹",
                    "achieved": achieved,
                    "evidence": [content] if achieved else [],
                }
            ],
            "confidence": 0.95,
        }
    )


def narrative_brief():
    return NarrativeBrief.model_validate(
        {
            "title": "旧港口",
            "viewpoint": "林海",
            "cast": ["林海"],
            "opening_anchor": "林海拿着姐姐的来信站在旧港",
            "carry_in": "需要确认笔迹以决定是否出海",
            "reader_promise": "通过行动辨认真伪",
            "immediate_pressure": "最后一班船即将离港",
            "opponent_move": "船主为了自己的货物拒绝载客",
            "irreversible_change": "修泵换船票后，林海失去返乡的钱",
            "tangible_payoff": "确认线索但付出代价",
            "ending_consequence": "航线出现新障碍",
            "voice_notes": "克制悬疑",
            "avoid_repeating": ["重复问来信真假"],
            "scenes": [
                {
                    "location": "旧港",
                    "trigger": "收到信",
                    "desire": "确认笔迹",
                    "opposition": "封锁",
                    "choice": "寻找旧物核对",
                    "consequence": "发现线索",
                    "emotional_turn": "怀疑到动摇",
                },
                {
                    "location": "船坞",
                    "trigger": "线索指向船坞",
                    "desire": "找到航线",
                    "opposition": "船被锁",
                    "choice": "用维修换通行",
                    "consequence": "获得有限帮助",
                    "emotional_turn": "希望伴随代价",
                },
            ],
        }
    )


def literary_review():
    return LiteraryReview.model_validate(
        {
            "verdict": "accept",
            "causality": 4,
            "character": 4,
            "scene": 4,
            "voice": 4,
            "strengths": ["人物采取了行动"],
            "issues": [],
            "revision_plan": [],
            "narrative_state": {
                "time_place": "旧港",
                "causal_summary": "因为来信而核对，确认线索后准备寻找航线",
                "character_drives": [
                    {
                        "name": "林海",
                        "wants_now": "找到航线",
                        "knows": "来信线索",
                        "relationship_change": "开始寻找帮助",
                    }
                ],
                "pending_consequences": ["出海受阻"],
                "paid_promises": ["核对来信"],
                "next_hook": "寻找船",
            },
        }
    )


class FakeModel:
    def __init__(self):
        self.outputs = []
        self.prompts = []
        self.calls = []
        self.hook = None
        self.director_outputs = []
        self.literary_outputs = []

    def structured(self, instructions, prompt, schema):
        self.prompts.append(prompt)
        if self.hook:
            hook, self.hook = self.hook, None
            hook()
        if schema is NarrativeBrief:
            result = self.director_outputs.pop(0) if self.director_outputs else narrative_brief()
        elif schema is LiteraryReview:
            result = self.literary_outputs.pop(0) if self.literary_outputs else literary_review()
        else:
            result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        if schema is SourceReview and isinstance(result, Review):
            sources = [
                (int(i), text) for i, text in re.findall(r"^\[P(\d+)\] (.*)$", prompt, re.MULTILINE)
            ]
            checklist = json.loads(
                prompt.split("【验收项目】\n", 1)[1].split("\n【本章完整正文", 1)[0]
            )

            def source_id(quote):
                return next((i for i, text in sources if quote in text), 999999)

            result = SourceReview(
                summary=result.summary,
                confidence=result.confidence,
                contradictions=result.contradictions,
                facts=[
                    {**f.model_dump(exclude={"evidence"}), "source_id": source_id(f.evidence)}
                    for f in result.facts
                ],
                criteria=[
                    {
                        "criterion_id": next(
                            (c["id"] for c in checklist if c["criterion"] == cr.criterion), 999999
                        ),
                        "achieved": cr.achieved,
                        "source_ids": [source_id(q) for q in cr.evidence],
                    }
                    for cr in result.criteria
                ],
            )
        assert isinstance(result, schema)
        return result

    def text(self, instructions, prompt):
        self.prompts.append(prompt)
        return self.outputs.pop(0)


@pytest.fixture
def setup(tmp_path):
    settings = Settings(database=tmp_path / "story.db")
    repo = Repository(settings.database)
    model = FakeModel()
    svc = StoryService(repo, model, settings)
    request = CreateBook.model_validate(
        {
            "book": {"title": "灯塔", "genre": "悬疑", "premise": "失踪姐姐的来信"},
            "stage": {"goal": "确认来信", "setting": "旧港", "acceptance": ["确认笔迹"]},
        }
    )
    book_id = repo.create(request)["id"]
    return svc, model, book_id


def prepare(svc, model, book_id, count=1):
    from scriptor.models import PlanRequest

    model.outputs += [bible(), PlanBatch(chapters=[plan(i) for i in range(1, count + 1)])]
    svc.bible(book_id)
    svc.plan(book_id, PlanRequest(start=1, count=count))
