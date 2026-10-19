import pytest

from scriptor.config import Settings
from scriptor.models import Bible, ChapterPlan, CreateBook, PlanBatch, Review
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
