"""Typed contracts. Model-output fields are required for strict JSON Schema."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BookInput(Contract):
    title: Text = Field(max_length=120)
    genre: Text = Field(max_length=80)
    premise: Text = Field(max_length=12000)
    style: Text = Field(default="中文网文，场景具体，人物动机清楚", max_length=4000)
    chapter_words: int = Field(default=3000, ge=300, le=10000)


class StageInput(Contract):
    goal: Text = Field(max_length=4000)
    setting: Text = Field(max_length=2000)
    acceptance: list[Text] = Field(min_length=1, max_length=20)


class StageDesign(StageInput):
    development: Text
    exit_hook: Text


class CreateBook(Contract):
    book: BookInput
    stage: StageInput


class IdeaInput(Contract):
    ideas: Text = Field(max_length=12000)
    points: list[Text] = Field(default_factory=list, max_length=30)
    style: Text = Field(default="中文网文，场景具体，人物动机清楚", max_length=4000)


class Character(Contract):
    name: Text
    motivation: Text
    constraints: Text


class Arc(Contract):
    title: Text
    conflict: Text
    payoff: Text


class Bible(Contract):
    world: Text
    rules: list[Text] = Field(min_length=1)
    characters: list[Character] = Field(min_length=1)
    arcs: list[Arc] = Field(min_length=1)
    ending_direction: Text


class CastMember(Character):
    role: Literal["protagonist", "supporting", "antagonist"]
    growth: Text
    relationships: Text


class StoryMap(Contract):
    name: Text
    identity: Text
    conflict: Text
    unlock_condition: Text


class GrowthSystem(Contract):
    name: Text
    rules: Text
    levels: list[Text] = Field(min_length=1)
    advancement: Text
    costs: Text
    limits: Text


class WorldDesign(Bible):
    characters: list[CastMember] = Field(min_length=3)
    maps: list[StoryMap] = Field(min_length=1)
    systems: list[GrowthSystem] = Field(min_length=1)
    central_conflict: Text
    growth_strategy: Text
    narrative_strategy: Text


class CreativeBlueprint(Contract):
    title: Text = Field(max_length=120)
    genre: Text = Field(max_length=80)
    chapter_words: int = Field(ge=300, le=10000)
    bible: WorldDesign
    first_stage: StageDesign


class Direction(Contract):
    finished: bool = Field(strict=True)
    rationale: Text
    next_stage: StageDesign | None


class AutoRequest(Contract):
    chapters: int = Field(default=10, ge=1, le=500)


class Scene(Contract):
    viewpoint: Text
    location: Text
    objective: Text
    conflict: Text
    change: Text


class ChapterPlan(Contract):
    number: int = Field(ge=1)
    stage: int = Field(ge=1)
    title: Text
    objective: Text
    characters: list[Text] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1, max_length=12)
    hook: Text


class PlanBatch(Contract):
    chapters: list[ChapterPlan] = Field(min_length=1, max_length=20)


class Fact(Contract):
    key: Text
    kind: Literal["character", "event", "thread"]
    subject: Text
    detail: Text
    status: Literal["active", "resolved"]
    evidence: Text


class Criterion(Contract):
    criterion: Text
    achieved: bool = Field(strict=True)
    evidence: list[Text]


class Review(Contract):
    summary: Text
    facts: list[Fact]
    contradictions: list[Text]
    criteria: list[Criterion]
    confidence: float = Field(ge=0, le=1)


class SourceFact(Contract):
    key: Text
    kind: Literal["character", "event", "thread"]
    subject: Text
    detail: Text
    status: Literal["active", "resolved"]
    source_id: int = Field(ge=1)


class SourceCriterion(Contract):
    criterion_id: int = Field(ge=1)
    achieved: bool = Field(strict=True)
    source_ids: list[int]


class SourceReview(Contract):
    summary: Text
    facts: list[SourceFact]
    contradictions: list[Text]
    criteria: list[SourceCriterion]
    confidence: float = Field(ge=0, le=1)


class PlanRequest(Contract):
    start: int = Field(ge=1)
    count: int = Field(default=5, ge=1, le=20)


class WriteRequest(Contract):
    rewrite: bool = False
    content: Text | None = Field(default=None, max_length=60000)
    expected_revision: int | None = Field(default=None, ge=0)


class EditRequest(Contract):
    content: Text = Field(max_length=60000)
    expected_revision: int | None = Field(default=None, ge=0)


class StageRequest(Contract):
    stage: StageInput
    confirm: Literal[True]
