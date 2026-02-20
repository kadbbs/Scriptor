"""
章节生成器 - 带持久化存储
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from openai import OpenAI


class ChapterGenerator:
    """章节生成器"""
    
    def __init__(self, api_key: str, base_url: str, book_id: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = "qwen3.5-plus"
        self.book_id = book_id
        self.base_dir = f"books/{book_id}"
    
    def generate_chapter(self, chapter_num: int, outline: Dict, 
                         world: Dict, summary: str = "") -> str:
        """生成单个章节"""
        prompt = f"""你是一位专业小说作家。请根据以下信息撰写第{chapter_num}章：

【世界设定】
{json.dumps(world, ensure_ascii=False, indent=2)}

【本章大纲】
{json.dumps(outline, ensure_ascii=False, indent=2)}

【前情摘要】
{summary if summary else "这是第一章，无需前情摘要"}

【要求】
- 字数：约{outline.get('word_count_target', 3000)}字
- 风格：符合{world.get('genre', '都市')}小说风格
- 节奏：有起承转合，结尾留有悬念
- 对话：自然流畅，符合人物性格

请直接输出章节内容，不要其他说明。"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        
        return response.choices[0].message.content
    
    def generate_chapter_stream(self, chapter_num: int, outline: Dict,
                                 world: Dict, summary: str = ""):
        """流式生成章节"""
        prompt = f"""你是一位专业小说作家。请根据以下信息撰写第{chapter_num}章：

【世界设定】
{json.dumps(world, ensure_ascii=False, indent=2)}

【本章大纲】
{json.dumps(outline, ensure_ascii=False, indent=2)}

【前情摘要】
{summary if summary else "这是第一章，无需前情摘要"}

【要求】
- 字数：约{outline.get('word_count_target', 3000)}字
- 风格：符合{world.get('genre', '都市')}小说风格
- 节奏：有起承转合，结尾留有悬念

请流式输出章节内容。"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    def save_chapter(self, chapter_num: int, content: str, title: str = "") -> str:
        """保存章节到独立文件夹"""
        chapter_dir = f"{self.base_dir}/chapters/chapter_{chapter_num:03d}"
        os.makedirs(chapter_dir, exist_ok=True)
        
        content_file = f"{chapter_dir}/chapter.txt"
        with open(content_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        metadata = {
            "book_id": self.book_id,
            "chapter_number": chapter_num,
            "title": title,
            "word_count": len(content),
            "filepath": content_file,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        metadata_file = f"{chapter_dir}/metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        print(f"\n📁 章节文件夹：{chapter_dir}/")
        print(f"   - chapter.txt ({len(content)} 字)")
        print(f"   - metadata.json")
        
        return chapter_dir
    
    def load_chapter(self, chapter_num: int) -> Optional[str]:
        """加载已保存的章节"""
        filepath = f"{self.base_dir}/chapters/chapter_{chapter_num:03d}/chapter.txt"
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        return None
    
    def chapter_exists(self, chapter_num: int) -> bool:
        """检查章节是否已存在"""
        chapter_dir = f"{self.base_dir}/chapters/chapter_{chapter_num:03d}"
        return os.path.exists(chapter_dir) and os.path.exists(f"{chapter_dir}/chapter.txt")
    
    def generate_summary(self, chapter_num: int, content: str) -> str:
        """生成章节摘要"""
        prompt = f"""请为以下小说章节生成 200 字以内的摘要：

{content[:3000]}

摘要要求：
- 包含主要情节
- 包含关键人物
- 包含重要转折
- 简洁明了

只返回摘要内容，不要其他说明。"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=False
        )
        
        return response.choices[0].message.content.strip()

    def generate_state_delta(self, chapter_num: int, content: str) -> Dict:
        """从章节文本中抽取结构化的状态增量（JSON）。

        返回格式示例：
        {
            "characters": [{"name":"苏哲","level":3,"role":"主角","last_seen_chapter":11,"notes":"……"}],
            "events_done": ["苏哲揭露深蓝科技"],
            "current_timeline_index": 5,
            "active_plotlines": ["深蓝与雷霆的博弈"]
        }
        """
        prompt = f"""请你作为剧情梳理助手，把下面的章节内容解析为结构化的 JSON 增量，包含：

1) characters: 角色列表（每项包含 name, role, level(可选数字), last_seen_chapter(可选), notes(可选)）
2) events_done: 本章完成的重要事件（简短描述字符串数组）
3) current_timeline_index: 若章节推动了时间线，返回新的时间线索引（否则可不返回）
4) active_plotlines: 本章影响或激活的剧情线标签数组

只返回纯 JSON，不要任何额外说明。章节内容如下：

{content[:4000]}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False
            )

            content = response.choices[0].message.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            return json.loads(content)
        except Exception:
            # 若解析失败，返回空增量
            return {}