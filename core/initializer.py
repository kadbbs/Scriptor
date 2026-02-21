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
    
    def __init__(self, api_key: str, base_url: str, model_name: str = "qwen3.5-plus"):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model_name
    
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
        # 清理并解析模型返回的 JSON
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            return json.loads(content)
        except Exception:
            return {}

    def _generate_timeline(self, book_input: Dict, world: Dict) -> Dict:
        """生成时间线：模型返回一个 JSON 对象，包含 timeline 列表，
        并可选包含 goal_achieved_at 字段指示在哪个事件上达成初始目标。
        """
        prompt = f"""请基于下列信息生成一组以实现初始目标为导向的时间线事件列表。

【书籍信息】
- 类型：{book_input.get('genre')}
- 主角核心：{book_input.get('protagonist_core')}
- 金手指：{book_input.get('cheat_ability')}
- 初始目标：{book_input.get('initial_goal')}

【世界设定】
{json.dumps(world, ensure_ascii=False, indent=2)}

要求：
- 返回 JSON 格式，包含字段 `timeline`（事件数组），每个事件至少包含 `event`、`time`（可选）、`type`、`importance`（1-5）。
- 如果模型判断可以在某一事件上实现初始目标，请在最外层返回字段 `goal_achieved_at`，其值为该事件在 `timeline` 中的索引（从0开始）或相应描述。
- 不要返回额外说明或非 JSON 内容。

                示例格式：
{{
    "timeline": [
        {{"event": "事件描述", "time": "第1年", "type": "冲突", "importance": 4, "related_characters": ["角色A"]}}
    ],
    "goal_achieved_at": 5
}}

只返回 JSON。"""

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

        try:
            return json.loads(content)
        except Exception:
            return {}
    
    def _generate_outlines(self, book_input: Dict, world: Dict, timeline: Dict) -> List[Dict]:
        """生成前 20 章大纲"""
        prompt = f"""根据以下信息生成前 20 章的详细大纲：

【书籍信息】

【世界设定】

【时间线】

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
        prompt = f"""根据以下信息，生成一组以实现初始目标为导向的章节大纲序列。

说明：请基于 `initial_goal`、时间线与世界设定，设计一套章节大纲，覆盖从当前故事起点直到目标明确达成为止。请在返回数据中至少包含每章的：`chapter_number`（从 start 或 1 开始），`title`，`main_plot`，`sub_plot`，`key_characters`，`climax`，`hook`，`word_count_target`。

在某一章明确达成初始目标时，请在该章的 `notes` 字段中标注“目标达成”。大纲数量由模型自行判断以自然实现目标，不必固定为 20 章。

返回格式示例：
{{
  "outlines": [ {{"chapter_number":1, "title":"...", "main_plot":"...", "notes":"可选"}}, ... ],
  "note": "可选：说明共生成多少章及在哪章达成目标"
}}

只返回 JSON，不要其他说明。

【书籍信息】
- 类型：{book_input["genre"]}
- 主角核心：{book_input["protagonist_core"]}
- 初始目标：{book_input["initial_goal"]}

【世界设定】
{json.dumps(world, ensure_ascii=False, indent=2)}

【时间线】
{json.dumps(timeline, ensure_ascii=False, indent=2)}
"""
        
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
    


    def generate_more_outlines(self, book_id: str, start_chapter: int, count: int = 20) -> List[Dict]:
        """动态生成更多章节大纲"""
        base_dir = f"books/{book_id}"
        
        # 加载现有数据
        with open(f"{base_dir}/configs/world.json", 'r', encoding='utf-8') as f:
            world = json.load(f)
        with open(f"{base_dir}/configs/book_input.json", 'r', encoding='utf-8') as f:
            book_input = json.load(f)
        with open(f"{base_dir}/configs/outlines.json", 'r', encoding='utf-8') as f:
            existing = json.load(f)
        
        # 加载故事状态以获取当前阶段
        story_state_file = f"{base_dir}/story_state.json"
        current_stage = 1
        if os.path.exists(story_state_file):
            with open(story_state_file, 'r', encoding='utf-8') as f:
                story_state = json.load(f)
                current_stage = story_state.get('stage', 1)
        
        # 根据当前阶段确定目标
        current_goal = book_input.get('initial_goal', '')
        if current_stage >= 2 and 'second_stage_goal' in book_input and book_input['second_stage_goal']:
            current_goal = book_input['second_stage_goal']
        elif current_stage >= 3 and 'third_stage_goal' in book_input and book_input['third_stage_goal']:
            current_goal = book_input['third_stage_goal']
        
        # 获取已写章节摘要（用于上下文）
        summaries = []
        for i in range(max(1, start_chapter-5), start_chapter):
            summary_file = f"{base_dir}/summaries/chapter_{i:03d}_summary.json"
            if os.path.exists(summary_file):
                with open(summary_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    summaries.append(f"第{i}章：{data.get('summary', '')}")
        
        # 如果 count <= 0，允许模型自行判断需要多少章以实现当前阶段目标
        if count and count > 0:
            range_desc = f"第{start_chapter}章到第{start_chapter+count-1}章（共{count}章）"
        else:
            range_desc = f"从第{start_chapter}章开始，生成直到达成当前阶段目标所需的章节序列（模型自行判断章数）"

        prompt = f"""根据以下信息生成{range_desc}的详细大纲：

    【书籍信息】
    - 类型：{book_input["genre"]}
    - 主角核心：{book_input["protagonist_core"]}
    - 当前阶段目标：{current_goal}
    - 当前阶段：{current_stage}

    【世界设定】
    {json.dumps(world, ensure_ascii=False, indent=2)}

    【前情摘要】
    {chr(10).join(summaries)}

    请生成 JSON 格式的章节大纲列表：
    {{
        "outlines": [
            {{
                "chapter_number": {start_chapter},
                "title": "章节标题",
                "main_plot": "主要情节",
                "sub_plot": "次要情节",
                "key_characters": ["角色名"],
                "climax": "本章高潮",
                "hook": "悬念钩子",
                "word_count_target": 3000,
                "notes": "可选：若在此章达成当前阶段目标可标注 '目标达成'"
            }}
        ]
    }}

    请在返回的 JSON 最外层包含一条说明，表明共生成多少章以及在哪章达成目标（若适用）。

    只返回 JSON，不要其他内容。"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            timeout=300
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        data = json.loads(content)
        new_outlines = data.get("outlines", []) if isinstance(data, dict) else data
        
        # 合并到现有大纲
        existing.extend(new_outlines)
        
        # 保存
        with open(f"{base_dir}/configs/outlines.json", 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        
        # 改进的打印逻辑，处理 count <= 0 的情况
        if count and count > 0:
            print(f"✅ 已生成 {len(new_outlines)} 章新大纲（第{start_chapter}-{start_chapter+count-1}章）")
        else:
            print(f"✅ 已生成 {len(new_outlines)} 章新大纲（从第{start_chapter}章开始，由模型判断实现目标所需）")
        
        return new_outlines


    def generate_more_timeline(self, book_id: str, count: int = 30) -> List[Dict]:
        """动态生成更多时间线事件"""
        base_dir = f"books/{book_id}"
        
        if not os.path.exists(base_dir):
            print(f"❌ 书籍目录不存在：{base_dir}")
            return []
        
        print(f"\n📅 正在生成 {count} 个新时间线事件...")
        
        # 加载现有数据
        with open(f"{base_dir}/configs/world.json", 'r', encoding='utf-8') as f:
            world = json.load(f)
        with open(f"{base_dir}/configs/book_input.json", 'r', encoding='utf-8') as f:
            book_input = json.load(f)
        with open(f"{base_dir}/configs/timeline.json", 'r', encoding='utf-8') as f:
            existing = json.load(f)
        with open(f"{base_dir}/configs/outlines.json", 'r', encoding='utf-8') as f:
            outlines = json.load(f)
        
        # 加载故事状态以获取当前阶段
        story_state_file = f"{base_dir}/story_state.json"
        current_stage = 1
        if os.path.exists(story_state_file):
            with open(story_state_file, 'r', encoding='utf-8') as f:
                story_state = json.load(f)
                current_stage = story_state.get('stage', 1)
        
        # 根据当前阶段确定目标
        current_goal = book_input.get('initial_goal', '')
        if current_stage >= 2 and 'second_stage_goal' in book_input and book_input['second_stage_goal']:
            current_goal = book_input['second_stage_goal']
        elif current_stage >= 3 and 'third_stage_goal' in book_input and book_input['third_stage_goal']:
            current_goal = book_input['third_stage_goal']
        
        # 获取时间线列表
        existing_timeline = existing.get("timeline", [])
        
        # 获取已写章节摘要（用于上下文）
        summaries = []
        for i in range(max(1, len(outlines)-10), len(outlines)):
            summary_file = f"{base_dir}/summaries/chapter_{i:03d}_summary.json"
            if os.path.exists(summary_file):
                with open(summary_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    summaries.append(f"第{i}章：{data.get('summary', '')}")
        
        # 获取现有时间线
        last_event_time = existing_timeline[-1].get('time', '未知') if existing_timeline else '故事开始'
        last_event = existing_timeline[-1].get('event', '未知') if existing_timeline else '无'
        
        # 如果 count <= 0，允许模型自行判断需要多少事件以实现初始目标
        if count and count > 0:
            count_desc = f"{count} 个"
        else:
            count_desc = "若干个（请模型判断实现目标所需的事件数量）"

        prompt = f"""根据以下信息生成 {count_desc} 新的重大事件时间线：

    【书籍信息】
    - 类型：{book_input["genre"]}
    - 主角核心：{book_input["protagonist_core"]}
    - 金手指：{book_input["cheat_ability"]}
    - 当前阶段目标：{current_goal}
    - 当前阶段：{current_stage}

    【世界设定】
    {json.dumps(world, ensure_ascii=False, indent=2)}

    【现有时间线最后一个事件】
    {last_event_time} - {last_event}

    【当前剧情进度】
    {chr(10).join(summaries) if summaries else '暂无'}

    请生成 JSON 格式的时间线事件列表，要求事件能自然承接并引导至当前阶段目标的达成。请在返回的 JSON 中指明在哪一项事件目标达成（字段名示例：`goal_achieved_at`）。

    返回示例结构：
    {{
        "timeline": [ {{"time":"2011 年 6 月", "event":"事件描述", "type":"冲突", "importance":3}} ],
        "goal_achieved_at": "第N项或时间描述"
    }}

    只返回 JSON，不要其他内容。"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            timeout=300
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        data = json.loads(content)
        new_events = data.get('timeline', []) if isinstance(data, dict) else data
        
        # 合并到现有时间线
        existing_timeline.extend(new_events)
        existing["timeline"] = existing_timeline
        
        # 保存
        with open(f"{base_dir}/configs/timeline.json", 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 已生成 {len(new_events)} 个新时间线事件")
        print(f"   总事件数：{len(existing_timeline)}个")
        
        return new_events