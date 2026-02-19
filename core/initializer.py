"""
开书初始化模块
"""

import json
import os
from datetime import datetime
from typing import Dict, List
from openai import OpenAI


class BookInitializer:
    """新书初始化模块"""
    
    def __init__(self, api_key: str, base_url: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = "qwen3.5-plus"
    
    def init_new_book(self, book_input: Dict) -> Dict:
        """开书初始化主流程"""
        print("\n🚀 开始初始化新书...")
        
        print("📖 生成世界设定...")
        world = self._generate_world_setting(book_input)
        print(f"   ✅ 世界设定完成：{world.get('world_name', '未知')}")
        
        print("📅 生成时间线...")
        timeline = self._generate_timeline(book_input, world)
        timeline_count = len(timeline.get("timeline", []))
        print(f"   ✅ 时间线完成：共{timeline_count}个事件")
        
        print("📋 生成章节大纲...")
        outlines = self._generate_outlines(book_input, world, timeline)
        print(f"   ✅ 大纲完成：共{len(outlines)}章")
        
        print("📊 初始化故事状态...")
        story_state = self._init_story_state(book_input, world, timeline)
        
        print("💾 保存配置...")
        self._save_files(world, timeline, outlines, story_state, book_input)
        
        print("\n✅ 新书初始化完成！")
        return story_state
    
    def _generate_world_setting(self, book_input: Dict) -> Dict:
        """生成世界设定"""
        prompt = f"""你是一位专业小说策划师。根据以下信息生成完整的世界设定：

【书籍信息】
- 类型：{book_input["genre"]}
- 主角核心：{book_input["protagonist_core"]}
- 金手指：{book_input["cheat_ability"]}
- 初始目标：{book_input["initial_goal"]}
- 第一阶段地图：{book_input["first_stage_setting"]}

请生成 JSON 格式的世界设定，包含：
{{
    "world_name": "世界名称",
    "time_period": "时代背景",
    "location": "主要地点",
    "power_system": "力量体系（如有）",
    "social_structure": "社会结构",
    "key_factions": ["主要势力 1", "主要势力 2"],
    "technology_level": "科技水平",
    "main_conflicts": ["主要矛盾 1", "主要矛盾 2"]
}}

只返回 JSON，不要任何其他内容。"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            timeout=60
        )
        
        content = response.choices[0].message.content.strip()
        # 清理可能的 markdown 标记
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        return json.loads(content)
    
    def _generate_timeline(self, book_input: Dict, world: Dict) -> Dict:
        """生成时间线"""
        prompt = f"""根据以下信息生成未来 3 年的重大事件时间线：

【书籍信息】
- 类型：{book_input["genre"]}
- 主角核心：{book_input["protagonist_core"]}
- 金手指：{book_input["cheat_ability"]}
- 初始目标：{book_input["initial_goal"]}

【世界设定】
{json.dumps(world, ensure_ascii=False, indent=2)}

请生成 JSON 格式的时间线，包含 20 个关键事件：
{{
    "timeline": [
        {{
            "time": "2010 年 3 月",
            "event": "事件描述",
            "type": "商业/情感/冲突/机遇",
            "importance": 1-5,
            "related_characters": ["角色名"]
        }}
    ]
}}

只返回 JSON，不要任何其他内容。"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            timeout=120
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        return json.loads(content)
    
    def _generate_outlines(self, book_input: Dict, world: Dict, timeline: Dict) -> List[Dict]:
        """生成前 20 章大纲"""
        prompt = f"""根据以下信息生成前 20 章的详细大纲：

【书籍信息】
- 类型：{book_input["genre"]}
- 主角核心：{book_input["protagonist_core"]}
- 初始目标：{book_input["initial_goal"]}

【世界设定】
{json.dumps(world, ensure_ascii=False, indent=2)}

【时间线】
{json.dumps(timeline, ensure_ascii=False, indent=2)}

请生成 JSON 格式的章节大纲列表：
{{
    "outlines": [
        {{
            "chapter_number": 1,
            "title": "章节标题",
            "main_plot": "主要情节",
            "sub_plot": "次要情节",
            "key_characters": ["角色名"],
            "climax": "本章高潮",
            "hook": "悬念钩子",
            "word_count_target": 3000
        }}
    ]
}}

只返回 JSON，不要任何其他内容。"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            timeout=180
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        data = json.loads(content)
        return data.get("outlines", []) if isinstance(data, dict) else data
    
    def _init_story_state(self, book_input: Dict, world: Dict, timeline: Dict) -> Dict:
        """初始化故事状态"""
        return {
            "book_id": f"book_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "genre": book_input["genre"],
            "protagonist_core": book_input["protagonist_core"],
            "cheat_ability": book_input["cheat_ability"],
            "initial_goal": book_input["initial_goal"],
            "current_chapter": 0,
            "total_chapters": 0,
            "total_words": 0,
            "current_timeline_index": 0,
            "active_characters": [],
            "active_plotlines": [],
            "last_summary": "",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "initialized"
        }
    
    def _save_files(self, world: Dict, timeline: Dict, outlines: List, 
                    story_state: Dict, book_input: Dict):
        """保存所有配置文件"""
        base_dir = f"books/{story_state['book_id']}"
        
        os.makedirs(base_dir, exist_ok=True)
        os.makedirs(f"{base_dir}/chapters", exist_ok=True)
        os.makedirs(f"{base_dir}/configs", exist_ok=True)
        os.makedirs(f"{base_dir}/summaries", exist_ok=True)
        
        with open(f"{base_dir}/configs/world.json", 'w', encoding='utf-8') as f:
            json.dump(world, f, ensure_ascii=False, indent=2)
        
        with open(f"{base_dir}/configs/timeline.json", 'w', encoding='utf-8') as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        
        with open(f"{base_dir}/configs/outlines.json", 'w', encoding='utf-8') as f:
            json.dump(outlines, f, ensure_ascii=False, indent=2)
        
        with open(f"{base_dir}/story_state.json", 'w', encoding='utf-8') as f:
            json.dump(story_state, f, ensure_ascii=False, indent=2)
        
        with open(f"{base_dir}/configs/book_input.json", 'w', encoding='utf-8') as f:
            json.dump(book_input, f, ensure_ascii=False, indent=2)
        
        chapter_index = {"book_id": story_state["book_id"], "total_chapters": 0, "chapters": []}
        with open(f"{base_dir}/chapters/chapter_index.json", 'w', encoding='utf-8') as f:
            json.dump(chapter_index, f, ensure_ascii=False, indent=2)