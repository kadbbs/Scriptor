# Scriptor

从头实现的中文长篇小说工作流：**作品设定 → 章节与场景规划 → 正文 → 全文审核 → 剧情记忆 → 阶段验收**。

所有模型请求使用 **Responses API**。提供网页写作工作台、CLI 和 HTTP API，共用同一业务核心；SQLite 保存正文版本、原文证据和运行记录。

本分支只从旧分支提取设计思想，未复用旧业务代码。外部方案比较见 [调研与取舍](docs/research.md)，一致性规则及边界见 [架构说明](docs/architecture.md)。

## 安装与配置

Python 3.10+：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

在 `.env` 中填写：

```dotenv
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=你有权限使用且支持Responses的模型
```

仓库附有 `uv.lock`。如使用 uv，可用 `uv sync --locked --extra dev` 安装锁定依赖；CI 使用同一锁文件。

`OPENAI_BASE_URL` 是 API 根路径，不要追加 `/responses`。第三方服务必须支持 `POST /responses`；仅有 OpenAI Chat Completions 兼容接口不足以运行本项目。不会静默改用其他 API。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 空 | 生成时必填；本地新建、查询、导出不需要 |
| `OPENAI_MODEL` | 空 | 显式选择模型，不绑定厂商 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Responses 服务根地址 |
| `SCRIPTOR_DB` | `data/scriptor.db` | 新版数据库，与旧文件布局分开 |
| `SCRIPTOR_TIMEOUT` | `180` | 单次请求超时秒数，SDK 最多重试两次 |
| `SCRIPTOR_MAX_OUTPUT_TOKENS` | `12000` | 单次模型输出 token 上限 |
| `SCRIPTOR_STRUCTURED_OUTPUT` | `true` | 服务端严格 JSON Schema；显式设为 `false` 时仍用 Responses，但只本地校验 JSON |
| `SCRIPTOR_CONTEXT_CHARS` | `28000` | 上下文字符预算，审核为完整正文预留空间；不是 token 数 |

环境变量优先于 `.env`。示例不含有效密钥，数据库、虚拟环境和 `.env` 不进入 Git。

## 命令行工作流

```bash
# 编辑示例，填写点子、题材、风格和阶段验收标准
scriptor create --input examples/book.json
scriptor list

# 将 BOOK_ID 替换成 create 返回的 id
scriptor bible BOOK_ID
scriptor plan BOOK_ID --start 1 --count 5
scriptor write BOOK_ID 1
scriptor show BOOK_ID
scriptor write BOOK_ID 2

# 最新一章可以显式重写，旧版本保留
scriptor write BOOK_ID 2 --rewrite
scriptor history BOOK_ID 2

# 或提交手写/修订正文，仍经过全文审核
scriptor edit BOOK_ID 2 --file chapter-2.txt

# 当前阶段验收全部达成后，由作者确认下一阶段
scriptor advance BOOK_ID --input examples/next-stage.json --confirm
scriptor plan BOOK_ID --start 3 --count 5

# 查看调用、失败候选和审核信息，导出采纳后的正文
scriptor runs BOOK_ID
scriptor export BOOK_ID --output novel.md
```

也可使用 `python -m scriptor`。命令输出 UTF-8 JSON；失败返回非零退出码。批量写作可通过脚本循环，但每章失败应停止并检查原因。

生成大纲每批 1–20 章，可从任一未写章节开始替换后续规划；不会重复追加同编号章节。正文按顺序写，仅支持编辑当前阶段最新一章，避免历史改动污染后文。重写后字数和记忆按当前版本计算，并清除依赖旧正文的后续规划，需要重新运行 `plan`。

阶段验收依据正文实际发生的事，而非大纲中的预告。每条事实与达成判定需要本章原文引用；阶段达成需要各验收项都有置信度至少 0.8 的证据，切换阶段还需显式确认。阶段数量不设固定上限。

如果审核失败、模型输出中断或并发期间书籍发生变化，原正文不变。`runs` 保存普通失败时已生成的候选与审核结果。取出候选并修改后，可用 `scriptor write BOOK_ID N --file candidate.txt` 提交新章，或增加 `--rewrite` 提交最新一章的替代版本。强制杀进程不保证保存尚在内存中的候选。

## 网页写作工作台与 HTTP API

```bash
scriptor serve --port 8000
```

默认监听 `0.0.0.0`，也可用 `--host` 指定监听地址。本机打开 **`http://127.0.0.1:8000/`** 使用网页编辑器，其他设备使用 `http://服务器IP:8000/`。`/docs` 仍提供交互式 API 文档。页面所需资源随 Python 包安装，不需要 Node.js、前端构建或第三方 CDN。

网页中可以完成：

1. 新建作品，填写创意、风格和阶段验收条件。
2. 在「作品设定」生成世界、人物、规则和分卷方向。
3. 在「写作」中规划章节，查看场景安排，生成正文或手动编辑，点击「保存并审核」采纳。
4. 在阶段面板查看逐项验收证据，完成后填写下一阶段并确认切换。
5. 在「剧情记忆」查看已发生事实；在「运行记录」查看审核失败原因、下载或恢复候选。
6. 查看章节历史，载入旧版本重新审核，或导出已采纳的全文。

未保存的编辑会暂存当前浏览器，切换章节或离开页面有提醒。「本地草稿」可载入基于旧版本的草稿。浏览器草稿不是服务器备份，清理浏览器数据后会丢失；正式正文以审核保存成功为准。生成请求完成前界面会锁定操作，避免重复提交或混用作品上下文。

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/books` | 创建书籍；请求结构同 `examples/book.json` |
| `GET /api/books` / `GET /api/books/{id}` | 列表 / 完整状态、记忆、阶段证据 |
| `POST /api/books/{id}/bible` | 生成作品设定 |
| `POST /api/books/{id}/plans` | `{"start":1,"count":5}` |
| `POST /api/books/{id}/chapters/{n}/generate` | `{"rewrite":false}`；可传 `content` 提交手写正文 |
| `PUT /api/books/{id}/chapters/{n}` | `{"content":"修订正文"}`，只允许最新一章 |
| `GET /api/books/{id}/chapters/{n}/history` | 已采纳历史版本 |
| `POST /api/books/{id}/stages` | `{"stage":{...},"confirm":true}`，stage 结构同 `next-stage.json` |
| `GET /api/books/{id}/runs` | 调用记录、候选和审核 |
| `GET /api/books/{id}/export` | Markdown 正文 |

生成请求同步等待，CLI 与 API 都有明确的完成/失败结果。并发提交由书籍版本检查保护，失败候选可查看。数据库保存创作内容，按本地单用户工具使用。

## 开发与验证

```bash
ruff check .
ruff format --check .
pytest -q
```

所有测试离线运行，不需要密钥。包括使用真实 OpenAI Python SDK 的 Responses HTTP 协议测试，以及重写、证据校验、事务回滚、并发冲突、HTTP API 与 CLI 测试。尚未用真实端点验证模型质量。

可选的真实浏览器烟测使用临时数据库和假模型，不会读取或修改实际书籍，不调用付费接口：

```bash
uv run --extra dev --with playwright python -m playwright install chromium --only-shell
uv run --extra dev --with playwright python -m tests.browser_editor
```

```text
scriptor/
  models.py       输入及模型输出契约
  llm.py          唯一的 Responses 传输适配器
  prompts.py      设定、规划、正文、审核任务
  context.py      版本记忆回放、词项检索、字符预算
  repository.py   SQLite、事务、运行记录和历史
  service.py      写作流程与阶段状态机
  cli.py / api.py 两个共用业务核心的入口
  static/         无构建依赖的网页编辑器
tests/            离线验证
docs/             调研与架构取舍
examples/         新书及后续阶段配置
```

当前不自动导入旧书，不支持任意历史章修改、流式续写或向量检索。原文引用存在不代表模型的语义判断一定正确，审核和置信度不能代替作者判断；小说质量仍需实际作品评测。

MIT License，见 [LICENSE](LICENSE)。
