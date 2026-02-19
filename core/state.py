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
    
    def _load_state(self) -> Dict:
        """加载状态"""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def save_state(self):
        """保存状态"""
        self.state["updated_at"] = datetime.now().isoformat()
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
    
    def update_chapter(self, chapter_num: int, word_count: int, summary: str):
        """更新章节信息"""
        self.state["current_chapter"] = chapter_num
        self.state["total_chapters"] = chapter_num
        self.state["total_words"] += word_count
        self.state["last_summary"] = summary
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