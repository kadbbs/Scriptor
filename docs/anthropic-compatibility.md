# Anthropic 兼容性排查与修复（0.6.2）

2026-10-19 对实际配置的 Anthropic 中转进行对照测试，发现两类独立问题。不能仅凭模型列表可访问或一次简短问答，就断言自动写作可用。

## 实测结果

| 请求 | 模型 | 结果 |
| --- | --- | --- |
| 用户提供的最小 Messages 示例，SDK 默认重试 | `claude-fable-5-1` | HTTP 503 |
| 项目完整构思请求，原生 Schema 或 JSON 提示 | `claude-fable-5-1` | HTTP 503 |
| 指定工具提交完整构思 | `claude-fable-5-1` | HTTP 504 |
| 简短普通文本 | `claude-haiku-4-5-20251001`、`claude-sonnet-4-6` | HTTP 200 |
| 项目完整构思，原生 `output_config` | `claude-sonnet-4-6` | HTTP 200，但返回 `# CreativeBlueprint` 开头的 Markdown，校验失败 |
| 原生 Schema 加完整 JSON 协议提示 | `claude-sonnet-4-6` | HTTP 200，但返回围栏中的无效 JSON，校验失败 |
| `tools` 加指定 `tool_choice` | `claude-sonnet-4-6` | 返回完整工具参数，通过 CreativeBlueprint 全部本地校验 |

以上是测试时的结果，不代表型号长期可用性。503/504 同样出现在独立请求中，不能归因于项目；而把中转返回的普通 Markdown 当作可解析的结构化输出，是项目需要处理的兼容性问题。

## 实现调整

Anthropic 的结构化步骤默认发送 `submit_result` 工具定义及完整 `input_schema`，指定该工具作为响应方式。只接收一个名称正确、参数为对象且完整结束的工具调用，再经过原始 Pydantic 校验。工具仅承载数据，不执行外部操作；正文继续普通文本生成。

支持三种显式模式：

```dotenv
ANTHROPIC_STRUCTURED_MODE=tool
SCRIPTOR_STRUCTURED_OUTPUT=true
```

`tool` 是默认值；`json_schema` 使用原生 `output_config`；`json` 使用完整 JSON 合约提示。`SCRIPTOR_STRUCTURED_OUTPUT=false` 强制 JSON 文本模式。不会自动切换模型、端点或提供商。

JSON 文本可去掉单个完整外层代码围栏，但不会截取散文中的 JSON、补齐字段或接纳截断输出。所有模式保留完整本地校验。失败运行保留原始结构化候选供检查，不将其写入正式故事设定。网页运行记录展示模型、请求模式、输出上限、输入字符数、请求编号和校验错误路径。

## 完整自动运行验证

在原数据库的隔离副本中，以 `claude-sonnet-4-6`、`tool` 模式执行自动运行，目标 1 章：

- 构思采用上一步真实请求保存的完整工具响应，未再次付费请求，也不是手写假数据。
- 后续章节规划、叙事导演、正文、独立文学审稿、全文事实抽取均为新的真实请求。
- 自动任务最终 `status=completed`、`completed=1`、`error=null`，耗时约 306 秒，章节 Markdown 4164 字符。
- 原小说数据库及用户 `.env` 未被修改。私有测试产物位于被 Git 忽略的 `data/evaluations`，不随代码发布。

该验证覆盖了一章的完整流程，不等于已经验证连续十章。回归测试覆盖实际 SDK 请求序列化、工具响应协议、异常停止、本地约束、结构化失败不入库，以及完整写章流程。

如使用本次验证通过的型号，可保留现有地址和密钥，仅设置：

```dotenv
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_STRUCTURED_MODE=tool
SCRIPTOR_STRUCTURED_OUTPUT=true
```

重启服务后生效。继续使用 Fable 时，仍需要该模型的生成线路恢复；本次代码调整不能修复中转的 503/504。

实现依据：[Anthropic 工具定义与调用](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)、[结构化输出](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)。
