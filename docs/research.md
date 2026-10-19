# 长篇写作方案调研与取舍

调研日期：2026-10-19。以下是基于原项目说明、论文摘要及官方文档的设计比较，不是对各工具进行统一实测后的排名，也不将数千词论文实验外推为百万字小说质量保证。

## 现有方案

| 方案与原始来源 | 可借鉴机制 | 本项目落地 | 尚未引入的部分 |
| --- | --- | --- | --- |
| [Long-Novel-GPT](https://github.com/MaoXiaoYuZ/Long-Novel-GPT) | 大纲→章节→正文，自上而下扩写；检索相关文本与剧情纲要，修改后同步纲要 | 分卷→章节→场景；按相关性检索已发生事实；编辑后重算记忆 | 导入拆书、向量检索、任意历史章节的依赖传播重写 |
| [DOC 论文](https://arxiv.org/abs/2212.10077) / [官方 v2 实现](https://github.com/facebookresearch/doc-storygen-v2) | 详细层级大纲与正文控制，将创意规划前置 | 场景目标、冲突、状态变化，正文生成与连续性审核分开 | 论文中的控制器、候选重排和原实验模型未复现；v2 说明定位于数千词故事 |
| [RecurrentGPT](https://github.com/aiwaves-cn/RecurrentGPT) | 最近文本与短期记忆，加可检索的长期记忆；人工参与调整 | 上一章摘要和结尾、可回放的事实记忆、历史摘要；显式阶段切换 | 暂用确定性词项检索，尚无语义向量检索；也未复现其全部循环算法 |
| [StoryWriter 论文](https://arxiv.org/abs/2506.16445) | 区分事件大纲、章节安排和正文写作；根据事件处理故事历史 | 规划、写作、审核各自独立的协议；上下文按当前任务选择 | 不引入多智能体运行框架、模型训练或其数据集；本次仅参考论文所述机制 |

这些资料共同支持将规划、正文和记忆分开处理。是否适合本仓库仍需工程判断：本实现选择小型、可测试的顺序工作流，减少框架依赖和隐式模型调用。

## 从旧分支保留的思想

- `main`：多书管理、显式设定、持久化、摘要与正文独立理解。
- `fix_chapter`：写后抽取人物、事件和剧情线；新实现增加原文证据，并将增量绑定到正文版本。
- `add_target`：阶段目标和地图；当前实现改为任意阶段表和正文逐项验收，目标、地图与升级策略由 LLM 制定，用户选择手动推进或后台自动运行。
- `novel-agent-mvp`：SQLite 和可复用服务入口；新实现让 CLI 与 HTTP API 调用同一领域服务，避免复制业务流程。

没有复制或合并旧业务代码，也没有复制外部项目源码。旧历史与分支保留，新分支使用全新的 `scriptor/` 包和数据库。原有 `LICENSE` 保留。

## Responses API 的准确边界

以下描述 OpenAI 模式；0.6 起新增 Anthropic Messages 模式，见 [架构说明](architecture.md)。

依据 [OpenAI Responses API Reference](https://developers.openai.com/api/reference/python/resources/responses) 和 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)：

- 所有生成走 `client.responses.create`，使用 `instructions`、`input` 和 `max_output_tokens`。
- 结构化结果使用 `text.format` 的 `json_schema`，然后通过 Pydantic 在本地再次验证。
- 正文读取 `output_text`；拒绝、空结果、未完成响应都作为失败处理。
- 使用 `store=False`；书籍状态由本地 SQLite 管理，不依赖远端会话链。
- 显式兼容开关仅关闭服务端 Schema 约束，仍调用 Responses，并验证返回 JSON；不会改用 Chat Completions。

兼容 Chat Completions 的服务不一定兼容 Responses。未选择特定模型或承诺所有第三方端点可用，必须按实际提供商验证。接口格式通过真实 OpenAI Python SDK 加 HTTP MockTransport 验证；没有用真实密钥测试模型质量。

## 为什么本轮先实现这些

优先保证可追踪的写作闭环：设定→规划→正文→审核→记忆→阶段验收。事务和版本管理防止生成异常破坏已有内容，证据引用防止把规划直接当成事实。字符预算、词项检索和调用记录提供可检查的基础。

后续最有价值的扩展是：语义检索与召回评测、人工审核界面、场景级续写、历史章节依赖重算、持久任务队列。引入它们前，应先用固定题材与盲评样本测量设定遵循、重复事件、伏笔回收、字数偏差和人工修改量。自动测试保证工程性质，不能证明文学质量。
