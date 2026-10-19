import pytest

from scriptor.config import Settings
from scriptor.models import (
    Bible,
    ChapterPlan,
    CreateBook,
    CreativeBlueprint,
    PlanBatch,
    Review,
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


class FakeModel:
    def __init__(self):
        self.outputs = []
        self.prompts = []
        self.calls = []
        self.hook = None

    def structured(self, instructions, prompt, schema):
        self.prompts.append(prompt)
        if self.hook:
            hook, self.hook = self.hook, None
            hook()
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
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
