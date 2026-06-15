import json
from typing import Any

from openai import AsyncOpenAI

from .config import get_settings
from .db import parse_json_object


SYSTEM_PROMPT = """你是一名资深中文商业网文主笔兼责编。
目标是把零散点子发展成长篇连载方案，并保持设定一致、节奏清晰、冲突递进。
输出必须具体、可执行，避免空泛形容。正文使用中文网络小说风格，重视钩子、情绪推进和章末悬念。"""


def client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured. Create .env from .env.example first.")
    return AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)


async def chat_text(
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: dict[str, str] | None = None,
) -> str:
    settings = get_settings()
    kwargs: dict[str, Any] = {}
    if response_format:
        kwargs["response_format"] = response_format
    response = await client().chat.completions.create(
        model=settings.model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return response.choices[0].message.content or ""


async def expand_bible(project: dict[str, Any]) -> str:
    prompt = f"""
请基于下面的网文点子，扩展成完整作品设定圣经。

书名：{project["title"]}
类型：{project["genre"]}
目标章节：{project["target_chapters"]}
单章字数：约 {project["chapter_words"]} 字
核心点子：
{project["premise"]}

请按以下结构输出：
1. 一句话卖点
2. 世界观与时代背景
3. 力量体系/职业体系/规则限制
4. 主角设定：欲望、缺陷、底牌、成长线
5. 主要配角与反派
6. 核心矛盾与长期主线
7. 阶段性卷纲，覆盖全书
8. 爽点、虐点、反转、悬念模板
9. 必须遵守的设定禁区
"""
    return await chat_text([{"role": "user", "content": prompt}], temperature=0.75, max_tokens=6000)


async def generate_outline_batch(
    project: dict[str, Any],
    previous_chapters: list[dict[str, Any]],
    start: int,
    count: int,
) -> dict[str, Any]:
    previous = "\n".join(
        f"第{item['number']}章《{item['title']}》：{item['outline']}" for item in previous_chapters[-20:]
    )
    prompt = f"""
请为长篇网文生成章节大纲，返回严格 JSON，不要 Markdown。

作品信息：
书名：{project["title"]}
类型：{project["genre"]}
目标章节：{project["target_chapters"]}
单章字数：约 {project["chapter_words"]} 字

作品设定圣经：
{project["bible"]}

最近章节：
{previous or "暂无，这是第一批。"}

任务：
生成第 {start} 章到第 {start + count - 1} 章的大纲。
每章需要 title 和 outline。outline 需要包含本章目标、冲突、转折、信息增量、章末钩子。

返回严格 JSON 对象，所有换行必须转义为 \\n，不要在字符串内部直接换行。
JSON 格式：
{{
  "chapters": [
    {{"number": {start}, "title": "章节标题", "outline": "章节大纲"}}
  ]
}}
"""
    text = await chat_text(
        [{"role": "user", "content": prompt}],
        temperature=0.65,
        max_tokens=7000,
        response_format={"type": "json_object"},
    )
    return parse_json_object(text)


async def generate_chapter(
    project: dict[str, Any],
    chapter: dict[str, Any],
    recent_chapters: list[dict[str, Any]],
) -> str:
    recent = "\n".join(
        f"第{item['number']}章《{item['title']}》摘要：{item['outline']}\n正文片段：{(item['content'] or '')[-500:]}"
        for item in recent_chapters[-3:]
    )
    prompt = f"""
请根据设定和大纲撰写网文正文。

书名：{project["title"]}
类型：{project["genre"]}
目标单章字数：约 {project["chapter_words"]} 中文字

作品设定圣经：
{project["bible"]}

前文参考：
{recent or "暂无前文。"}

本章：
第{chapter["number"]}章《{chapter["title"]}》
大纲：{chapter["outline"]}

写作要求：
- 直接输出正文，不要解释。
- 保持人物动机一致，场景清楚，冲突具体。
- 本章必须完成一个小闭环，同时在结尾留下下一章钩子。
- 避免流水账，避免重复设定说明。
"""
    return await chat_text([{"role": "user", "content": prompt}], temperature=0.78, max_tokens=8000)


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
