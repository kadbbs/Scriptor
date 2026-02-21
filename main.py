import os
import sys
import json
from typing import Optional

from core.initializer import BookInitializer
from core.generator import ChapterGenerator
from core.state import StoryStateManager

# API 配置 - 可通过环境变量覆盖
API_KEY = os.getenv("DEEPSEEK_API_KEY")
BASE_URL = "https://api.deepseek.com/v1"
MODEL_NAME = os.getenv("NOVEL_MODEL", "deepseek-reasoner")


def check_env() -> bool:
    if not API_KEY:
        print("❌ 环境变量 API_KEY 未设置")
        return False
    return True


def init_new_book():
    if not check_env():
        return

    print("请输入新书信息（回车使用默认或留空）：")
    genre = input("类型（如：奇幻/都市/科幻）: ").strip() or "都市"
    protagonist = input("主角核心设定: ").strip() or "主角是个普通人"
    cheat = input("金手指设定（如有）: ").strip() or "无"
    initial_goal = input("初始目标（如：吞噬3个物体）: ").strip() or "完成第一阶段目标"
    first_stage_setting = input("第一阶段地图（如：出租屋）: ").strip() or "出租屋"

    book_input = {
        "genre": genre,
        "protagonist_core": protagonist,
        "cheat_ability": cheat,
        "initial_goal": initial_goal,
        "first_stage_setting": first_stage_setting
    }

    initializer = BookInitializer(API_KEY, BASE_URL, MODEL_NAME)
    story_state = initializer.init_new_book(book_input)
    print(f"新书已创建：{story_state.get('book_id')}")


def write_chapter(book_id: str, chapter_num: int):
    if not check_env():
        return

    state_manager = StoryStateManager(book_id)
    # 加载所需内容
    try:
        world = state_manager.load_world()
    except Exception:
        print("❌ 无法加载 world.json，请确认书籍已初始化")
        return

    outline = state_manager.get_outline(chapter_num)
    if not outline:
        print(f"❌ 第{chapter_num}章没有大纲，自动生成直到达成当前阶段目标的大纲...")
        # 自动生成从当前章节开始的大纲，由模型决定需要多少章达成目标
        start_chapter = chapter_num
        
        initializer = BookInitializer(API_KEY, BASE_URL, MODEL_NAME)
        try:
            # 使用 count=0 让模型自行判断需要多少章以实现当前阶段目标
            initializer.generate_more_outlines(book_id, start_chapter, 0)
            print(f"✅ 已生成新大纲（从第{start_chapter}章开始，由模型决定章节数量以达成目标）")
            
            # 重新获取大纲
            outline = state_manager.get_outline(chapter_num)
            if not outline:
                print(f"⚠️ 大纲生成后仍未找到第{chapter_num}章大纲")
                return
            
            # 同时生成对应的时间线事件
            print("📅 正在生成对应的时间线事件...")
            initializer.generate_more_timeline(book_id, 0)
            
        except Exception as e:
            print(f"⚠️ 自动生成大纲失败：{e}")
            return
    
    generator = ChapterGenerator(API_KEY, BASE_URL, book_id, MODEL_NAME)

    print(f"开始生成第{chapter_num}章：{outline.get('title')}")
    
    # 获取故事状态作为上下文
    story_state = state_manager.get_state()
    # 准备故事上下文
    story_context = {
        'characters': story_state.get('characters', []),
        'events_done': story_state.get('events_done', []),
        'active_plotlines': story_state.get('active_plotlines', [])
    }
    
    content = generator.generate_chapter(chapter_num, outline, world, 
                                        state_manager.load_summary(chapter_num - 1) or "",
                                        story_context)

    chapter_dir = generator.save_chapter(chapter_num, content, outline.get('title', ''))
    summary = generator.generate_summary(chapter_num, content)
    state_manager.save_summary(chapter_num, summary)

    # 从章节中抽取状态增量并合并
    try:
        delta = generator.generate_state_delta(chapter_num, content) or {}
        state_manager.apply_state_delta(delta)
    except Exception as e:
        print(f"⚠️ 抽取/合并状态增量失败：{e}")
        delta = {}

            # 使用 AI 判断是否完成当前阶段目标，将判定放在此处
    try:
        # 读取 book_input
        bi_path = f"books/{book_id}/configs/book_input.json"
        try:
            with open(bi_path, 'r', encoding='utf-8') as f:
                book_input = json.load(f)
        except Exception:
            book_input = {}

        recent_summaries = state_manager.load_recent_summaries(count=5)
        
        # 获取当前阶段（需要在较早位置获取）
        current_stage = state_manager.get_state().get('stage', 1)
        
        # 根据当前阶段获取目标和设置
        stage_goal = book_input.get('initial_goal', '')
        stage_setting = book_input.get('first_stage_setting', '')
        if current_stage == 2:
            stage_goal = book_input.get('second_stage_goal', '')
            stage_setting = book_input.get('second_stage_setting', '')
        elif current_stage == 3:
            stage_goal = book_input.get('third_stage_goal', '')
            stage_setting = book_input.get('third_stage_setting', '')
        
        prompt = f"""你是剧情分析助手。给定以下信息，请判断书籍的第{current_stage}阶段目标是否已被完成。

要求：只返回纯 JSON，格式：
{{"achieved": true/false, "confidence": 0.0-1.0, "evidence": "简短说明为何完成或未完成"}}

上下文：
- 第{current_stage}阶段目标: {stage_goal}
- 第{current_stage}阶段地图: {stage_setting}
- 故事状态 events_done: {state_manager.get_state().get('events_done', [])}
- 最近摘要：{recent_summaries}
- 本章抽取的增量 delta: {json.dumps(delta, ensure_ascii=False)}
- 本章片段：{content[:2000]}

请用中文判断并只输出 JSON。"""

        try:
            response = generator.client.chat.completions.create(
                model=generator.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False
            )
            ai_out = response.choices[0].message.content.strip()
            if ai_out.startswith('```'):
                ai_out = ai_out.split('\n', 1)[-1]
                if ai_out.endswith('```'):
                    ai_out = ai_out[:-3].strip()

            result = json.loads(ai_out)
        except Exception:
            result = {"achieved": False, "confidence": 0.0, "evidence": "AI 判定失败或返回不可解析内容"}

        achieved = bool(result.get('achieved'))

        if achieved:
            next_stage = current_stage + 1
            print(f"\n🎯 AI 判定第{current_stage}阶段目标已完成：")
            print(f"目标：{stage_goal}")
            print("证据：", result.get('evidence', '无'))
            
            confirm = input(f"要更新并设置第{next_stage}阶段目标/地图吗？(y/n): ").strip().lower()
            if confirm == 'y':
                print("留空将保留原值。")
                
                # 根据下一阶段设置输入项
                if next_stage == 2:
                    new_protagonist = input("主角核心设定（可选，留空则不变）：").strip()
                    new_goal = input("第二阶段目标：").strip()
                    new_setting = input("第二阶段地图：").strip()
                elif next_stage == 3:
                    new_goal = input("第三阶段目标：").strip()
                    new_setting = input("第三阶段地图：").strip()
                else:
                    new_goal = input(f"第{next_stage}阶段目标：").strip()
                    new_setting = input(f"第{next_stage}阶段地图：").strip()

                if next_stage == 2 and new_protagonist:
                    book_input['protagonist_core'] = new_protagonist
                    state_manager.state['protagonist_core'] = new_protagonist
                
                # 保存下一阶段目标
                if new_goal:
                    if next_stage == 2:
                        book_input['second_stage_goal'] = new_goal
                        state_manager.state['second_stage_goal'] = new_goal
                    elif next_stage == 3:
                        book_input['third_stage_goal'] = new_goal
                    else:
                        book_input[f'stage_{next_stage}_goal'] = new_goal
                
                # 保存下一阶段地图
                if new_setting:
                    if next_stage == 2:
                        book_input['second_stage_setting'] = new_setting
                    elif next_stage == 3:
                        book_input['third_stage_setting'] = new_setting
                    else:
                        book_input[f'stage_{next_stage}_setting'] = new_setting

                try:
                    state_manager.state['stage'] = next_stage
                    os.makedirs(f"books/{book_id}/configs", exist_ok=True)
                    with open(f"books/{book_id}/configs/book_input.json", 'w', encoding='utf-8') as f:
                        json.dump(book_input, f, ensure_ascii=False, indent=2)
                    state_manager.save_state()
                    print(f"✅ 已保存第{next_stage}阶段设定并将故事阶段标记为 {next_stage}")

                    # 基于新设定重新规划后续大纲与时间线
                    try:
                        initializer = BookInitializer(API_KEY, BASE_URL, MODEL_NAME)
                        start_ch = chapter_num + 1
                        print(f"🔁 从第{start_ch}章开始重新生成后续大纲并由模型决定所需章节数量，随后生成时间线...")
                        initializer.generate_more_outlines(book_id, start_ch, 0)
                        initializer.generate_more_timeline(book_id, 0)
                        print("✅ 大纲/时间线已根据新设定生成并保存")
                    except Exception as e:
                        print(f"⚠️ 重新生成大纲/时间线失败：{e}")

                except Exception as e:
                    print(f"⚠️ 保存第{next_stage}阶段设定失败：{e}")
            else:
                print("ℹ️ 已选择不更新下一阶段设定")
    except Exception as e:
        print(f"⚠️ AI 阶段检测发生异常：{e}")

    # 更新章节索引与状态
    state_manager.update_chapter_index(
        chapter_num,
        outline.get('title', f"第{chapter_num}章"),
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
        print(f"      字数：{ch['word_count']:,} | 创建：{ch.get('created_at','')[:10]}")

    print("=" * 60)
    print(f"总章节数：{index.get('total_chapters', 0)}")


def read_chapter(book_id: str, chapter_num: int):
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


def generate_outlines(book_id: str, start: int, count: int):
    if not check_env():
        return

    if not os.path.exists(f"books/{book_id}"):
        print(f"❌ 错误：书籍 {book_id} 不存在")
        return

    initializer = BookInitializer(API_KEY, BASE_URL, MODEL_NAME)
    initializer.generate_more_outlines(book_id, start, count)


def generate_timeline(book_id: str, count: int):
    if not check_env():
        return

    if not os.path.exists(f"books/{book_id}"):
        print(f"❌ 错误：书籍 {book_id} 不存在")
        return

    initializer = BookInitializer(API_KEY, BASE_URL, MODEL_NAME)
    initializer.generate_more_timeline(book_id, count)


def update_stage_settings(book_id: str):
    """交互式更新并保存书籍的阶段设定（可在任意时刻调用）"""
    if not check_env():
        return

    state_manager = StoryStateManager(book_id)
    bi_path = f"books/{book_id}/configs/book_input.json"
    try:
        with open(bi_path, 'r', encoding='utf-8') as f:
            book_input = json.load(f)
    except Exception:
        book_input = {}

    print("当前设定（留空则不修改）：")
    print(f"  主角核心：{book_input.get('protagonist_core')}")
    print(f"  初始目标：{book_input.get('initial_goal')}")
    print(f"  第一阶段地图：{book_input.get('first_stage_setting')}")
    print(f"  第二阶段目标（当前）：{book_input.get('second_stage_goal', '')}")

    new_protagonist = input("主角核心设定（可选，留空则不变）：").strip()
    new_goal = input("第二阶段目标（留空则不变）：").strip()
    new_setting = input("第二阶段地图/场景（留空则不变）：").strip()
    new_stage = input("设置阶段数（如 2，留空不变）：").strip()

    if new_protagonist:
        book_input['protagonist_core'] = new_protagonist
        state_manager.state['protagonist_core'] = new_protagonist
    if new_goal:
        book_input['second_stage_goal'] = new_goal
        state_manager.state['second_stage_goal'] = new_goal
    if new_setting:
        book_input['second_stage_setting'] = new_setting
    if new_stage.isdigit():
        state_manager.state['stage'] = int(new_stage)

    try:
        os.makedirs(f"books/{book_id}/configs", exist_ok=True)
        with open(f"books/{book_id}/configs/book_input.json", 'w', encoding='utf-8') as f:
            json.dump(book_input, f, ensure_ascii=False, indent=2)
        state_manager.save_state()
        print("✅ 已保存设定")
    except Exception as e:
        print(f"⚠️ 保存设定失败：{e}")

    regen = input("是否基于新设定重新生成后续大纲/时间线？(y/n): ").strip().lower()
    if regen == 'y':
        try:
            initializer = BookInitializer(API_KEY, BASE_URL, MODEL_NAME)
            start_ch = state_manager.get_state().get('current_chapter', 0) + 1

            max_retries = 5
            attempt = 0
            while True:
                attempt += 1
                print(f"🔁 第 {attempt} 次尝试生成大纲（模型决定数量）...")
                initializer.generate_more_outlines(book_id, start_ch, 0)

                # 检查大纲中是否有目标达成标注
                outlines_path = f"books/{book_id}/configs/outlines.json"
                try:
                    with open(outlines_path, 'r', encoding='utf-8') as f:
                        outlines = json.load(f)
                except Exception:
                    outlines = []

                found = False
                for o in outlines:
                    notes = o.get('notes') if isinstance(o, dict) else None
                    if isinstance(notes, str) and '目标达成' in notes:
                        found = True
                        break

                if found:
                    print("✅ 模型已在大纲中标注“目标达成”。")
                    try:
                        initializer.generate_more_timeline(book_id, 0)
                    except Exception:
                        pass
                    break

                if attempt >= max_retries:
                    print(f"⚠️ 已达最大重试次数 ({max_retries})，仍未在大纲标注目标达成。")
                    break

                cont = input("模型生成的大纲未标注目标达成，是否重试一次？(y/n): ").strip().lower()
                if cont != 'y':
                    print("ℹ️ 停止重试。可稍后手动再次生成或编辑大纲以标注目标")
                    break

            print("✅ 大纲/时间线重生成流程结束")
        except Exception as e:
            print(f"⚠️ 重新生成失败：{e}")


def show_menu():
    print("\n" + "=" * 60)
    print("📖 小说 Agent 系统 v2.0 (持久化版)")
    print("=" * 60)
    print()
    print("  1. 创建新书")
    print("  2. 撰写章节")
    print("  3. 生成更多大纲")
    print("  4. 生成更多时间线")
    print("  5. 查看书籍状态")
    print("  6. 列出书籍")
    print("  7. 查看章节列表")
    print("  8. 阅读章节")
    print("  9. 退出")
    print(" 10. 更新阶段设定（随时修改目标/地图）")
    print()


def main():
    while True:
        show_menu()
        choice = input("请选择操作 (1-9): ").strip()

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
            book_id = input("输入书籍 ID: ").strip()
            start = input("起始章节：").strip()
            count = input("生成数量：").strip()
            if book_id and start.isdigit() and count.isdigit():
                generate_outlines(book_id, int(start), int(count))
            else:
                print("❌ 输入无效")
        elif choice == "4":
            book_id = input("输入书籍 ID: ").strip()
            count = input("生成数量：").strip()
            if book_id and count.isdigit():
                generate_timeline(book_id, int(count))
            else:
                print("❌ 输入无效")
        elif choice == "5":
            book_id = input("输入书籍 ID: ").strip()
            if book_id:
                # 简单展示 story_state.json
                sf = f"books/{book_id}/story_state.json"
                if os.path.exists(sf):
                    with open(sf, 'r', encoding='utf-8') as f:
                        print(json.dumps(json.load(f), ensure_ascii=False, indent=2))
                else:
                    print("❌ 未找到 story_state.json")

                # 允许随时更新阶段设定
                try:
                    ans = input("是否更新阶段设定/目标/地图？(y/n): ").strip().lower()
                    if ans == 'y':
                        update_stage_settings(book_id)
                except Exception:
                    pass
        elif choice == "6":
            list_books()
        elif choice == "7":
            book_id = input("输入书籍 ID: ").strip()
            if book_id:
                list_chapters(book_id)
        elif choice == "8":
            book_id = input("输入书籍 ID: ").strip()
            chapter_num = input("输入章节号：").strip()
            if book_id and chapter_num.isdigit():
                read_chapter(book_id, int(chapter_num))
        elif choice == "9":
            print("\n👋 再见！")
            break
        elif choice == "10":
            book_id = input("输入书籍 ID: ").strip()
            if book_id:
                update_stage_settings(book_id)
        else:
            print("❌ 无效选项")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "init":
            init_new_book()
        elif sys.argv[1] == "write" and len(sys.argv) >= 4:
            write_chapter(sys.argv[2], int(sys.argv[3]))
        elif sys.argv[1] == "outlines" and len(sys.argv) >= 5:
            generate_outlines(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
        elif sys.argv[1] == "timeline" and len(sys.argv) >= 4:
            generate_timeline(sys.argv[2], int(sys.argv[3]))
        elif sys.argv[1] == "list":
            list_books()
        elif sys.argv[1] == "status" and len(sys.argv) >= 3:
            sf = f"books/{sys.argv[2]}/story_state.json"
            if os.path.exists(sf):
                with open(sf, 'r', encoding='utf-8') as f:
                    print(json.dumps(json.load(f), ensure_ascii=False, indent=2))
            else:
                print("❌ 未找到 story_state.json")
        elif sys.argv[1] == "chapters" and len(sys.argv) >= 3:
            list_chapters(sys.argv[2])
        elif sys.argv[1] == "read" and len(sys.argv) >= 4:
            read_chapter(sys.argv[2], int(sys.argv[3]))
        elif sys.argv[1] == "setstage" and len(sys.argv) >= 3:
            update_stage_settings(sys.argv[2])
        else:
            print("用法:")
            print("  python main.py init              - 创建新书")
            print("  python main.py write <id> <章>   - 写单章")
            print("  python main.py outlines <id> <起> <数> - 生成大纲")
            print("  python main.py timeline <id> <数>    - 生成时间线")
            print("  python main.py status <id>     - 查状态")
            print("  python main.py list              - 列书籍")
            print("  python main.py chapters <id>     - 查章节")
            print("  python main.py read <id> <章>    - 读章节")
            print("  python main.py                   - 交互模式")
    else:
        main()
