"""
故事状态管理器 - 持久化存储
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional


class StoryStateManager:
    """故事状态管理器"""
    
    def __init__(self, book_id: str):
        self.book_id = book_id
        self.base_dir = f"books/{book_id}"
        self.state_file = f"{self.base_dir}/story_state.json"
        self.state = self._load_state()
        self._ensure_defaults()
    
    def _load_state(self) -> Dict:
        """加载状态"""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _ensure_defaults(self):
        """确保 state 包含必要的默认键，避免 KeyError 和不一致"""
        defaults = {
            "book_id": self.book_id,
            "current_chapter": 0,
            "total_chapters": 0,
            "total_words": 0,
            "current_timeline_index": 0,
            "active_characters": [],
            "characters": [],
            "events_done": [],
            "active_plotlines": [],
            "last_summary": "",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "initialized"
        }

        for k, v in defaults.items():
            if k not in self.state:
                self.state[k] = v
    
    def save_state(self):
        """保存状态"""
        self.state["updated_at"] = datetime.now().isoformat()
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
    
    def update_chapter(self, chapter_num: int, word_count: int, summary: str):
        """更新章节信息"""
        self.state["current_chapter"] = chapter_num
        self.state["total_chapters"] = chapter_num
        # 安全地累加字数
        self.state.setdefault("total_words", 0)
        try:
            self.state["total_words"] += int(word_count)
        except Exception:
            # 若 word_count 是字符串或异常，尝试用长度作为备用
            self.state["total_words"] += len(str(word_count))
        self.state["last_summary"] = summary
        self.save_state()

    def get_character(self, name: str) -> Optional[Dict]:
        """按名字查找角色信息"""
        for c in self.state.get("characters", []):
            if c.get("name") == name:
                return c
        return None

    def update_character(self, char: Dict):
        """更新或添加一个角色（根据 name 合并）"""
        if "name" not in char:
            return
        chars = self.state.setdefault("characters", [])
        for i, c in enumerate(chars):
            if c.get("name") == char.get("name"):
                # 合并字段（覆盖已有字段）
                c.update(char)
                chars[i] = c
                self.save_state()
                return

        chars.append(char)
        self.save_state()

    def mark_events_done(self, events: List[str]):
        """将事件标记为已完成（去重）"""
        done = set(self.state.setdefault("events_done", []))
        for e in events:
            if e:
                done.add(e)
        self.state["events_done"] = list(done)
        self.save_state()

    def apply_state_delta(self, delta: Dict):
        """应用从章节中抽取的状态增量。

        delta 可能包含：characters (list of dict), events_done (list of str),
        current_timeline_index (int), active_plotlines (list)
        """
        if not isinstance(delta, dict):
            return

        # 合并角色信息
        for c in delta.get("characters", []):
            try:
                self.update_character(c)
            except Exception:
                continue

        # 合并已完成事件
        events = delta.get("events_done", [])
        if events:
            self.mark_events_done(events)

        # 更新时间线索引
        if isinstance(delta.get("current_timeline_index"), int):
            self.state["current_timeline_index"] = max(
                self.state.get("current_timeline_index", 0), delta.get("current_timeline_index")
            )

        # 合并活动剧情线
        ap = delta.get("active_plotlines", [])
        if ap:
            exist = set(self.state.setdefault("active_plotlines", []))
            for a in ap:
                exist.add(a)
            self.state["active_plotlines"] = list(exist)

        # 更新最后更新时间
        self.state["updated_at"] = datetime.now().isoformat()
        self.save_state()
    
    def get_state(self) -> Dict:
        """获取当前状态"""
        return self.state
    
    def load_world(self) -> Dict:
        """加载世界设定"""
        with open(f"{self.base_dir}/configs/world.json", 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_timeline(self) -> Dict:
        """加载时间线"""
        with open(f"{self.base_dir}/configs/timeline.json", 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_outlines(self) -> List:
        """加载大纲"""
        with open(f"{self.base_dir}/configs/outlines.json", 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_outline(self, chapter_num: int) -> Optional[Dict]:
        """获取指定章节大纲"""
        outlines = self.load_outlines()
        if chapter_num <= len(outlines):
            return outlines[chapter_num - 1]
        return None
    
    def load_chapter_index(self) -> Dict:
        """加载章节索引"""
        index_file = f"{self.base_dir}/chapters/chapter_index.json"
        if os.path.exists(index_file):
            with open(index_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"book_id": self.book_id, "total_chapters": 0, "chapters": []}
    
    def update_chapter_index(self, chapter_num: int, title: str, word_count: int, 
                             filepath: str, summary: str):
        """更新章节索引"""
        index = self.load_chapter_index()
        
        chapter_exists = False
        for ch in index["chapters"]:
            if ch["chapter_number"] == chapter_num:
                ch["title"] = title
                ch["word_count"] = word_count
                ch["filepath"] = filepath
                ch["summary"] = summary
                ch["updated_at"] = datetime.now().isoformat()
                chapter_exists = True
                break
        
        if not chapter_exists:
            index["chapters"].append({
                "chapter_number": chapter_num,
                "title": title,
                "word_count": word_count,
                "filepath": filepath,
                "summary": summary,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            })
            index["chapters"].sort(key=lambda x: x["chapter_number"])
        
        index["total_chapters"] = len(index["chapters"])
        
        with open(f"{self.base_dir}/chapters/chapter_index.json", 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
    
    def save_summary(self, chapter_num: int, summary: str):
        """保存章节摘要"""
        os.makedirs(f"{self.base_dir}/summaries", exist_ok=True)
        filepath = f"{self.base_dir}/summaries/chapter_{chapter_num:03d}_summary.json"
        
        data = {
            "chapter_number": chapter_num,
            "summary": summary,
            "created_at": datetime.now().isoformat()
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def load_summary(self, chapter_num: int) -> Optional[str]:
        """加载章节摘要"""
        filepath = f"{self.base_dir}/summaries/chapter_{chapter_num:03d}_summary.json"
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("summary", "")
        return None
    
    def load_recent_summaries(self, count: int = 5) -> str:
        """加载最近 N 章摘要"""
        summaries = []
        for i in range(count):
            ch_num = self.state.get("current_chapter", 0) - i
            if ch_num > 0:
                summary = self.load_summary(ch_num)
                if summary:
                    summaries.append(f"第{ch_num}章摘要：{summary}")
        
        return "\n".join(reversed(summaries)) if summaries else ""