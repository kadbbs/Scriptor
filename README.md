# 网文 Agent 管理器

一个本地网页工具，用 OpenAI API 兼容格式接入 DeepSeek，辅助从点子扩展设定、生成全文大纲，并按章生成正文。

## 启动

```bash
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000

## 工作流

1. 新建项目，填写核心点子、类型、目标章节数、单章字数。
2. 生成完整设定：世界观、主线、人物、冲突、爽点节奏。
3. 生成全文大纲：按批次写入章节标题和剧情摘要。
4. 按章生成正文，自动参考项目设定、前文摘要和章节大纲。

