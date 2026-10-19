from collections.abc import Callable

from . import prompts
from .config import Settings
from .context import build_context, memory
from .errors import Conflict, ReviewRejected, ScriptorError
from .llm import Model
from .models import Bible, PlanBatch, PlanRequest, Review, StageInput
from .repository import Repository


def stage_progress(book):
    stage = next(s for s in book["stages"] if s["number"] == book["stage"])
    criteria = [
        {"criterion": text, "achieved": False, "evidence": []}
        for text in stage["spec"]["acceptance"]
    ]
    for chapter in book["chapters"]:
        if chapter["stage"] != stage["number"] or chapter["review"]["confidence"] < 0.8:
            continue
        for criterion, assessment in zip(criteria, chapter["review"]["criteria"]):
            if assessment["achieved"]:
                criterion["achieved"] = True
                criterion["evidence"].append(
                    {"chapter": chapter["number"], "quotes": assessment["evidence"]}
                )
    return {
        "stage": stage["number"],
        "goal": stage["spec"]["goal"],
        "criteria": criteria,
        "achieved": all(c["achieved"] for c in criteria),
    }


class StoryService:
    def __init__(self, repo: Repository, model: Model, settings: Settings):
        self.repo, self.model, self.settings = repo, model, settings

    def _execute(self, book_id: str, operation: str, action: Callable):
        run_id, snapshot = self.repo.start(book_id, operation)
        artifacts = {}
        calls = getattr(self.model, "calls", [])
        offset = len(calls)
        try:
            mutate, result = action(snapshot, artifacts)
            self.repo.commit(snapshot, run_id, mutate, artifacts, calls[offset:])
        except BaseException as exc:
            # Interrupted processes retain running status; caught interrupts retain candidates too.
            message = (
                str(exc)
                if isinstance(exc, ScriptorError)
                else f"{type(exc).__name__}：操作失败，故事状态未提交"
            )
            self.repo.fail(run_id, message, artifacts, calls[offset:])
            if isinstance(exc, (ScriptorError, KeyboardInterrupt, SystemExit)):
                raise
            raise ScriptorError(message) from exc
        return {"run_id": run_id, **result}

    def _context(self, book, before, focus, artifacts, budget=None, label="context"):
        context, trace = build_context(book, before, budget or self.settings.context_chars, focus)
        artifacts[label] = trace
        return context

    def bible(self, book_id):
        def action(book, artifacts):
            if book["chapters"]:
                raise Conflict("已有正文，不能直接替换世界设定；请创建新书进行分叉创作")
            context = self._context(book, 1, {"task": "生成作品设定"}, artifacts)
            bible = self.model.structured(prompts.EDITOR, prompts.BIBLE + "\n" + context, Bible)
            artifacts["bible"] = bible.model_dump()

            def mutate(conn):
                conn.execute(
                    "UPDATE books SET bible=? WHERE id=?", (bible.model_dump_json(), book_id)
                )
                conn.execute("DELETE FROM plans WHERE book_id=?", (book_id,))

            return mutate, {"bible": bible.model_dump()}

        return self._execute(book_id, "bible", action)

    def plan(self, book_id, request: PlanRequest):
        def action(book, artifacts):
            if not book["bible"]:
                raise Conflict("请先生成作品设定")
            next_chapter = len(book["chapters"]) + 1
            last_plan = max((p["number"] for p in book["plans"]), default=next_chapter - 1)
            if not next_chapter <= request.start <= last_plan + 1:
                raise Conflict("只能从未写章节开始规划，且不能产生章节编号缺口")
            preceding = [p["data"] for p in book["plans"] if p["number"] < request.start][-5:]
            focus = {
                "start": request.start,
                "count": request.count,
                "stage": book["stage"],
                "preceding_plans_not_facts": preceding,
            }
            context = self._context(book, next_chapter, focus, artifacts)
            batch = self.model.structured(prompts.EDITOR, prompts.PLAN + "\n" + context, PlanBatch)
            artifacts["plan"] = batch.model_dump()
            expected = list(range(request.start, request.start + request.count))
            if [ch.number for ch in batch.chapters] != expected or any(
                ch.stage != book["stage"] for ch in batch.chapters
            ):
                raise Conflict("模型返回的章节数量、编号或阶段不匹配；原大纲未改变")

            def mutate(conn):
                # Replace the dependent future suffix, never append duplicate chapter numbers.
                conn.execute(
                    "DELETE FROM plans WHERE book_id=? AND number>=?", (book_id, request.start)
                )
                conn.executemany(
                    "INSERT INTO plans(book_id,number,stage,data) VALUES (?,?,?,?)",
                    [(book_id, ch.number, ch.stage, ch.model_dump_json()) for ch in batch.chapters],
                )

            return mutate, {"plan": batch.model_dump()}

        return self._execute(book_id, "plan", action)

    def write(self, book_id, number: int, rewrite=False, content: str | None = None):
        def action(book, artifacts):
            if not book["bible"]:
                raise Conflict("请先生成作品设定")
            total = len(book["chapters"])
            if number < 1 or (rewrite and number != total) or (not rewrite and number != total + 1):
                raise Conflict("新章必须按顺序撰写；仅允许显式重写/编辑最新一章，避免污染后文")
            plan = next((p for p in book["plans"] if p["number"] == number), None)
            if plan is None or plan["stage"] != book["stage"]:
                raise Conflict("本章缺少当前阶段的大纲，请先规划；已结束阶段的正文不能直接重写")
            context = self._context(book, number, plan["data"], artifacts)
            candidate = content if content is not None else self.model.text(prompts.WRITE, context)
            artifacts["candidate"] = candidate
            if not candidate.strip() or len(candidate) > 60000:
                raise ReviewRejected("正文为空或超过 60000 字符；未截断或写入正文")
            # Include the entire candidate, never just its opening.
            review_budget = self.settings.context_chars - len(candidate) - len(prompts.REVIEW) - 100
            if review_budget <= 0:
                raise ReviewRejected(
                    "完整正文超出审核预算；候选已保留，请增加 SCRIPTOR_CONTEXT_CHARS"
                )
            review_context = self._context(
                book, number, plan["data"], artifacts, budget=review_budget, label="review_context"
            )
            review_prompt = review_context + "\n【本章完整正文】\n" + candidate
            review = self.model.structured(
                prompts.EDITOR, prompts.REVIEW + "\n" + review_prompt, Review
            )
            artifacts["review"] = review.model_dump()
            stage = next(s for s in book["stages"] if s["number"] == book["stage"])
            self._validate_review(candidate, review, stage["spec"]["acceptance"])
            current = next((ch for ch in book["chapters"] if ch["number"] == number), None)
            version = current["version"] + 1 if current else 1
            title = plan["data"]["title"]

            def mutate(conn):
                values = (
                    book_id,
                    number,
                    version,
                    book["stage"],
                    title,
                    candidate,
                    review.model_dump_json(),
                )
                conn.execute(
                    "INSERT INTO revisions(book_id,number,version,stage,title,content,review) VALUES (?,?,?,?,?,?,?)",
                    values,
                )
                conn.execute(
                    """
                    INSERT INTO chapters(book_id,number,version,stage,title,content,review) VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(book_id,number) DO UPDATE SET
                    version=excluded.version,content=excluded.content,review=excluded.review,title=excluded.title
                """,
                    values,
                )
                if rewrite:
                    conn.execute(
                        "DELETE FROM plans WHERE book_id=? AND number>?", (book_id, number)
                    )

            return mutate, {
                "number": number,
                "version": version,
                "title": title,
                "content": candidate,
                "review": review.model_dump(),
                "word_count": len(candidate),
            }

        return self._execute(book_id, "edit" if content is not None else "write", action)

    @staticmethod
    def _validate_review(content, review, acceptance):
        if review.contradictions:
            raise ReviewRejected("审核发现实质矛盾；候选和审核结果已保留在 runs，未替换正文")
        if [c.criterion for c in review.criteria] != acceptance:
            raise ReviewRejected("审核未按顺序覆盖全部阶段验收标准")
        keys = [(f.kind, f.key) for f in review.facts]
        if len(keys) != len(set(keys)):
            raise ReviewRejected("审核包含重复事实标识")
        quotes = [fact.evidence for fact in review.facts]
        for criterion in review.criteria:
            if criterion.achieved and not criterion.evidence:
                raise ReviewRejected("目标达成判定缺少正文证据")
            if not criterion.achieved and criterion.evidence:
                raise ReviewRejected("未达成条件不能附带达成证据")
            quotes.extend(criterion.evidence)
        if any(quote not in content for quote in quotes):
            raise ReviewRejected("审核引用并非本章原文，不能写入事实记忆")

    def advance(self, book_id, stage: StageInput, confirm: bool):
        if confirm is not True:
            raise Conflict("切换阶段需要显式确认 confirm=true / --confirm")

        def action(book, artifacts):
            if not stage_progress(book)["achieved"]:
                raise Conflict("当前阶段尚未逐项获得置信度 >= 0.8 的正文证据")
            if len(set(stage.acceptance)) != len(stage.acceptance):
                raise Conflict("阶段验收标准不能重复")
            next_stage = book["stage"] + 1
            artifacts["new_stage"] = stage.model_dump()

            def mutate(conn):
                conn.execute(
                    "UPDATE stages SET closed_at_chapter=? WHERE book_id=? AND number=?",
                    (len(book["chapters"]), book_id, book["stage"]),
                )
                conn.execute(
                    "INSERT INTO stages(book_id,number,spec) VALUES (?,?,?)",
                    (book_id, next_stage, stage.model_dump_json()),
                )
                conn.execute("UPDATE books SET stage=? WHERE id=?", (next_stage, book_id))
                conn.execute(
                    "DELETE FROM plans WHERE book_id=? AND number>?",
                    (book_id, len(book["chapters"])),
                )

            return mutate, {"stage": next_stage}

        return self._execute(book_id, "advance", action)

    def inspect(self, book_id):
        book = self.repo.get(book_id)
        return {**book, "progress": stage_progress(book), "memory": memory(book["chapters"])}

    def export(self, book_id):
        book = self.repo.get(book_id)
        parts = ["# " + book["spec"]["title"]]
        for chapter in book["chapters"]:
            parts.append(f"## 第{chapter['number']}章 {chapter['title']}\n\n{chapter['content']}")
        return "\n\n".join(parts) + "\n"
