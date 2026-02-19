"""
小说 Agent 主入口
"""

import os
import sys
import json
from dotenv import load_dotenv
from core.initializer import BookInitializer
from core.state import StoryStateManager
from core.generator import ChapterGenerator

load_dotenv()


def check_env():
    """检查环境变量"""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 错误：未找到 DASHSCOPE_API_KEY 环境变量")
        print("   请编辑 .env 文件，填入你的 API 密钥")
        return False
    return True


def init_new_book():
    """初始化新书"""
    if not check_env():
        return None
    
    api_key = os.getenv("DASHSCOPE_API_KEY")
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    print("\n📝 新书配置")
    print("=" * 50)
    
    genre = input("类型 (都市重生/修仙重生/科技重生): ").strip() or "都市重生"
    protagonist = input("主角核心设定：").strip() or "重生回 2010 年，掌握未来十年互联网风口"
    cheat = input("金手指：").strip() or "精准记忆未来重大商业事件"
    goal = input("初始目标：").strip() or "3 年内资产过亿"
    setting = input("第一阶段地图：").strip() or "三线城市创业起步"
    
    book_input = {
        "genre": genre,
        "protagonist_core": protagonist,
        "cheat_ability": cheat,
        "initial_goal": goal,
        "first_stage_setting": setting
    }
    
    print("\n" + "=" * 50)
    print("确认配置：")
    print(json.dumps(book_input, ensure_ascii=False, indent=2))
    print("=" * 50)
    
    confirm = input("\n确认创建？(y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ 已取消")
        return None
    
    initializer = BookInitializer(api_key, base_url)
    story_state = initializer.init_new_book(book_input)
    
    print(f"\n✅ 书籍已创建：{story_state['book_id']}")
    print(f"📁 存储位置：books/{story_state['book_id']}/")
    
    return story_state["book_id"]


def write_chapter(book_id: str, chapter_num: int):
    """撰写指定章节"""
    if not check_env():
        return
    
    api_key = os.getenv("DASHSCOPE_API_KEY")
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    if not os.path.exists(f"books/{book_id}"):
        print(f"❌ 错误：书籍 {book_id} 不存在")
        return
    
    state_manager = StoryStateManager(book_id)
    generator = ChapterGenerator(api_key, base_url, book_id)
    
    if generator.chapter_exists(chapter_num):
        print(f"⚠️  第{chapter_num}章已存在")
        overwrite = input("是否覆盖？(y/n): ").strip().lower()
        if overwrite != 'y':
            print("❌ 已取消")
            return
    
    world = state_manager.load_world()
    outlines = state_manager.load_outlines()
    state = state_manager.get_state()
    
    if chapter_num > len(outlines):
        print(f"❌ 错误：只有{len(outlines)}章大纲")
        return
    
    outline = outlines[chapter_num - 1]
    
    if chapter_num > 1:
        summary = state_manager.load_recent_summaries(count=3)
    else:
        summary = ""
    
    print(f"\n📝 开始撰写第{chapter_num}章：{outline['title']}")
    print("=" * 50)
    
    content = ""
    for chunk in generator.generate_chapter_stream(chapter_num, outline, world, summary):
        print(chunk, end="", flush=True)
        content += chunk
    
    print("\n" + "=" * 50)
    
    chapter_dir = generator.save_chapter(chapter_num, content, outline['title'])
    
    print("\n📋 生成章节摘要...")
    summary = generator.generate_summary(chapter_num, content)
    print(f"摘要：{summary[:100]}...")
    
    state_manager.save_summary(chapter_num, summary)
    
    state_manager.update_chapter_index(
        chapter_num, 
        outline['title'], 
        len(content), 
        f"{chapter_dir}/chapter.txt",
        summary
    )
    
    state_manager.update_chapter(chapter_num, len(content), summary)
    
    print(f"\n✅ 第{chapter_num}章完成！")
    print(f"   字数：{len(content)}")
    print(f"   位置：{chapter_dir}/")
    
    return content


def list_books():
    """列出所有书籍"""
    if not os.path.exists("books"):
        print("📭 暂无书籍")
        return
    
    print("\n📚 书籍列表")
    print("=" * 60)
    
    for book_id in sorted(os.listdir("books")):
        state_file = f"books/{book_id}/story_state.json"
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            print(f"\n📖 {book_id}")
            print(f"   类型：{state.get('genre', '未知')}")
            print(f"   章节：{state.get('total_chapters', 0)}")
            print(f"   字数：{state.get('total_words', 0):,}")
            print(f"   状态：{state.get('status', '未知')}")
    
    print("\n" + "=" * 60)


def list_chapters(book_id: str):
    """列出某书的所有章节"""
    index_file = f"books/{book_id}/chapters/chapter_index.json"
    
    if not os.path.exists(index_file):
        print(f"❌ 书籍 {book_id} 不存在或无章节")
        return
    
    with open(index_file, 'r', encoding='utf-8') as f:
        index = json.load(f)
    
    print(f"\n📖 {book_id} - 章节列表")
    print("=" * 60)
    
    for ch in index.get("chapters", []):
        print(f"   第{ch['chapter_number']:03d}章：{ch['title']}")
        print(f"      字数：{ch['word_count']:,} | 创建：{ch['created_at'][:10]}")
    
    print("=" * 60)
    print(f"总章节数：{index.get('total_chapters', 0)}")


def read_chapter(book_id: str, chapter_num: int):
    """阅读指定章节"""
    filepath = f"books/{book_id}/chapters/chapter_{chapter_num:03d}/chapter.txt"
    
    if not os.path.exists(filepath):
        print(f"❌ 第{chapter_num}章不存在")
        return
    
    print(f"\n📖 第{chapter_num}章")
    print("=" * 60)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print(content)
    print("=" * 60)


def show_menu():
    """显示主菜单"""
    print("\n" + "=" * 60)
    print("📖 小说 Agent 系统 v2.0 (持久化版)")
    print("=" * 60)
    print()
    print("  1. 创建新书")
    print("  2. 撰写章节")
    print("  3. 列出书籍")
    print("  4. 查看章节列表")
    print("  5. 阅读章节")
    print("  6. 退出")
    print()


def main():
    """主函数"""
    while True:
        show_menu()
        choice = input("请选择操作 (1-6): ").strip()
        
        if choice == "1":
            init_new_book()
        elif choice == "2":
            book_id = input("输入书籍 ID: ").strip()
            chapter_num = input("输入章节号：").strip()
            if book_id and chapter_num.isdigit():
                write_chapter(book_id, int(chapter_num))
            else:
                print("❌ 输入无效")
        elif choice == "3":
            list_books()
        elif choice == "4":
            book_id = input("输入书籍 ID: ").strip()
            if book_id:
                list_chapters(book_id)
        elif choice == "5":
            book_id = input("输入书籍 ID: ").strip()
            chapter_num = input("输入章节号：").strip()
            if book_id and chapter_num.isdigit():
                read_chapter(book_id, int(chapter_num))
        elif choice == "6":
            print("\n👋 再见！")
            break
        else:
            print("❌ 无效选项")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "init":
            init_new_book()
        elif sys.argv[1] == "write" and len(sys.argv) >= 4:
            write_chapter(sys.argv[2], int(sys.argv[3]))
        elif sys.argv[1] == "list":
            list_books()
        elif sys.argv[1] == "chapters" and len(sys.argv) >= 3:
            list_chapters(sys.argv[2])
        elif sys.argv[1] == "read" and len(sys.argv) >= 4:
            read_chapter(sys.argv[2], int(sys.argv[3]))
        else:
            main()
    else:
        main()