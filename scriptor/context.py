"""Deterministic, budgeted lexical retrieval without an embedding dependency."""

import re

from .errors import ScriptorError
from .repository import dump


def memory(chapters):
    facts = {}
    for chapter in sorted(chapters, key=lambda ch: ch["number"]):
        for fact in chapter["review"]["facts"]:
            facts[(fact["kind"], fact["key"])] = {**fact, "chapter": chapter["number"]}
    return list(facts.values())


def terms(text):
    result = set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))
    for word in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(word[i : i + 2] for i in range(len(word) - 1))
    return result


def build_context(book, before: int, budget: int, focus=None):
    stage = next((s for s in book["stages"] if s["number"] == book["stage"]), None)
    required = {
        "book": book["spec"],
        "bible": book["bible"],
        "stage": {"number": stage["number"], **stage["spec"]} if stage else None,
        "task": focus,
    }
    result = dump(required)
    if len(result) > budget:
        raise ScriptorError("世界设定、当前阶段和任务超出上下文预算；请增加 SCRIPTOR_CONTEXT_CHARS")
    chapters = [c for c in book["chapters"] if c["number"] < before]
    selected = []

    def add(label, value):
        nonlocal result
        block = "\n" + label + "：" + dump(value)
        if len(result) + len(block) <= budget:
            result += block
            return True
        return False

    # Give the author actual prose and unfinished consequences, not just a factual digest.
    if chapters:
        last = chapters[-1]
        previous = last["content"] if len(last["content"]) <= 12000 else last["content"][-8000:]
        if not add(
            "上一章正文与叙事接力",
            {
                "number": last["number"],
                "summary": last["review"]["summary"],
                "prose": previous,
                "prose_is_complete": len(previous) == len(last["content"]),
                "narrative_state": last["review"].get("narrative_state"),
            },
        ):
            raise ScriptorError(
                "上下文预算不足以容纳上一章正文与衔接，请增加 SCRIPTOR_CONTEXT_CHARS"
            )
    for chapter in chapters[-3:-1]:
        if chapter["review"].get("narrative_state"):
            add(
                "近期因果与人物变化",
                {"number": chapter["number"], **chapter["review"]["narrative_state"]},
            )
    query = terms(dump(focus) + (stage["spec"]["goal"] if stage else book["spec"]["premise"]))
    facts = memory(chapters)
    facts.sort(
        key=lambda f: (
            len(query & terms(f["subject"] + f["detail"])),
            f["kind"] == "thread" and f["status"] == "active",
            f["chapter"],
        ),
        reverse=True,
    )
    for fact in facts:
        if add("已发生事实", fact):
            selected.append((fact["kind"], fact["key"]))
    for chapter in reversed(chapters[:-1]):
        add("历史摘要", {"number": chapter["number"], "summary": chapter["review"]["summary"]})
    return result, {
        "characters_used": len(result),
        "budget": budget,
        "selected_facts": selected,
        "omitted_facts": len(facts) - len(selected),
        "before_chapter": before,
    }
