# 自主研究路径：Codex / OpenCode 源码对照（2026-11-27）

目的：不再逐项设计 `read_next`、固定候选评分或专项调度规则，而是把成熟的 Agent 执行方式
接到 Study Agent 已有组件上。本文只记录读到的源码事实、许可和对本仓库的适配决定；
不复制对方代码，只复现机制。

## 1. 读到的源码

### Codex（`openai/codex`，Apache-2.0）

| 文件 | 机制 |
| --- | --- |
| `codex-rs/core/src/tasks/regular.rs` | `run_turns` 是 turn 级循环：一次 turn 内反复 `run_turn`，直到没有后续输入、预算耗尽或中断；错误、预算耗尽、中断都保留待处理输入，不重开 turn。 |
| `codex-rs/core/src/tasks/mod.rs` | 任务生命周期与 `abort` 是一等契约；compact 是独立 `CompactTask`，不是工具调用里的临时分支。 |
| `codex-rs/core/src/compact.rs` | 内联自动压缩：生成摘要后用替换历史继续，而不是把整段历史一直塞进上下文；摘要与后续上下文分开组装。 |
| `codex-rs/core/src/compact_retained_tool_outputs.rs` | 压缩时对工具输出有单独的保留/截断策略，避免摘要把可复用证据全部抹掉。 |

结论：Codex 的核心不是“更多固定步骤”，而是**turn 循环 + 明确的终止/中断 + 压缩作为独立阶段**。

### OpenCode（`anomalyco/opencode`，MIT）

| 文件 | 机制 |
| --- | --- |
| `packages/core/src/session/runner/step.ts` | 一个 step 内模型返回的所有工具调用**并发启动**（`toolRuns` 光纤），停止时先让可协作的工具自行收尾，再中断其余工具，最后统一读取每个工具的退出；工具失败被分类，不会静默变成成功。 |
| `packages/core/src/session/runner/max-steps.ts` | 达到最大 step 后注入 `MAX_STEPS_PROMPT`：禁止再调工具，只允许文本总结“已完成 / 未完成 / 下一步”。 |
| `packages/core/src/session/compaction.ts` | 自动压缩预留窗口（默认 15%，至少 16k token）；摘要之外保留一段最近对话原文；支持后台预生成摘要；摘要模板要求结构化 checkpoint。 |
| `packages/core/src/session/runner/llm.ts` | step 与 retry 分离：每次尝试有自己的流、工具与持久结算；输出触顶有单独的“拆小继续”提示。 |

结论：OpenCode 的核心是**一步内并行工具 + 明确的停止/收尾提示 + 阈值触发的结构化压缩**。

## 2. 与 Study Agent 的对应

| 机制 | 现有组件 | 本批决定 |
| --- | --- | --- |
| Agent Loop | `run_tool_loop`（已有轮次、工具调用、取消、状态块） | 直接复用，不新建循环 |
| 并行工具 | `max_parallel_tools` + `parallel_safe`（已完成网页读取） | 自主路径默认并行读取；搜索并行用独立开关，避免共享 provider 限额被打满 |
| 动态计划 | 模型在每轮自行选择下一工具；`build_research_state` 提供已读/未读/失败/剩余 | 提示词要求模型维护“已回答 / 未回答”，不新增计划数据库 |
| 预算耗尽 | `should_cancel` + 工具包装器 | 包装器按 search/read/wall 三类拒绝超限调用；提示模型用已有证据收尾 |
| 上下文压缩 | 尚无 | 后续独立片；先记录 Codex/OpenCode 的阈值与保留策略，不在本批硬塞 |
| 子代理 | 尚无 | 后续按实测决定；本批不做 |
| 证据/安全 | 现有网关、SSRF、平台范围、Evidence Gate、账本 | 全部保留；自主路径只编排已有工具 |

## 3. 本批边界

- 新增 `WEB_AUTONOMOUS_RESEARCH=1` 才启用普通研究的自主路径；默认关闭。
- `WEB_AUTONOMOUS_DEEP=1` 才把 Deep 请求交给同一路径；默认关闭，RQCE 仍是 Deep 的默认实现。
- 不新增读取器、搜索 provider、证据库或第二套状态机。
- 不复制 Codex/OpenCode 代码；只实现机制。许可证分别为 Apache-2.0 与 MIT。
- 付费额度、图片传输权限不变；本批无付费调用。

## 4. 后续切片（按实测，不预先扩张）

1. 自主普通研究 + 预算收尾（本批）。
2. 自主 Deep 路由 + 与 RQCE 的同题对照（需授权）。
3. 上下文压缩：优先保留原始 URL、已确认事实、失败原因、未解决问题。
4. 探索子代理：只有单 Agent 的上下文或轮次成为实测瓶颈时才做。
