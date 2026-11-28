# 研究交付失败审计与容错交付（2026-11-28）

范围：`main@c29b67ef` 的 inline research publication gate，以及四个成熟 Agent
（Codex、Claude Code、OpenCode、DeepSeek Harness）的**实际源码/官方文档**对照。

本轮不产生付费模型调用。所有源码对照均固定到具体 commit；Claude Code 的官方
仓库是插件/配置仓库，核心运行时代码未官方公开。2026-03-31 npm v2.1.88 意外
暴露 source map 后的恢复源码已另做专项研究（见 CLAUDE_CODE_SOURCE_STUDY_20261128.md）；
本文该部分仍只引用官方 Hooks 文档，不把文档描述冒充成源码事实。

## 1. 结论

之前的门禁把「质量/预算/运行时失败」和「安全拦截」混为一谈：任何一项检查没通过，
整份候选答案就被替换成 32 字固定拒绝文案。研究已经花掉的读取、证据和生成结果
全部消失。

本轮把发布结果拆成四类：

| 类别 | 处理 |
| --- | --- |
| 安全 | 仍然严格拦截；本轮没有放宽任何 SSRF/私网/凭证/授权边界 |
| 质量 | 能定位就删除/扣留问题片段；不能定位就发布带标签的草稿 |
| 预算 | 用已有候选生成降级交付，不因核验预算耗尽而清空答案 |
| 运行时/截断 | 保留候选与已读来源，明确标注失败步骤或截断状态 |

新的固定标签：

- `【部分结论尚未核实】`：只发布了一部分，或删除了问题引用/表述。
- `【未完整核实的研究草稿】`：整份候选是未核验草稿。
- `【研究未完成，已保留已读来源】`：没有可用正文，只交付实际读取的公开来源。

结构化记录 `rag_snapshot["research_delivery"]` 始终带
`verified: false`、`reason_code`、`reason_class`（`quality` / `budget` /
`runtime` / `truncation`）和来源列表。`answer_claim_snapshot.status` 仍是
`rejected`，所以程序化消费者不会把草稿当成已验证答案。

## 2. 改动前的整轮丢失路径

行号基于 `c29b67ef` 的 `src/application/chat_service.py`。

| 触发条件 | 原行为 | 失败分类 | 本轮行为 |
| --- | --- | --- | --- |
| 核验调用预算耗尽（`allowed_attempts < 1`，L1539） | 固定拒绝文案 | 预算 | 发布草稿 + 已读来源；记录 `budget_exhausted` |
| 没有证据简报（L1576） | 固定拒绝文案 | 程序整理失败 | 发布草稿；记录 `missing_evidence_brief` |
| 模型没有正文（L1585） | 固定拒绝文案 | 运行时/截断 | 交付已读来源 + 失败原因；`candidate_unavailable` 或 `output_limit` |
| 未读引用无法安全删除（L1638） | 固定拒绝文案 | 质量/链接卫生 | 按块扣留含问题链接的内容；不能定位时只交付来源 |
| 逐条核验全部扣留（L1765） | 固定拒绝文案 | 质量 | 不发布被扣留的正文，但交付已读来源 |
| 事实一致性检查失败（L1796） | 固定拒绝文案 | 质量 | 能按 claim 文本定位就删对应块，否则整份标为草稿 |
| binder 拒绝/不可用（L1820–1848） | 固定拒绝文案 | 质量/运行时 | 有已核验子集就发布子集；否则发布草稿 |
| 门禁抛异常 | 整轮 turn 失败 | 程序异常 | 捕获后发布带标签草稿，记录 `research_gate_error` |
| 输出被截断（`finish_reason=length`） | 当作正常答案发布 | 截断 | 保留正文，追加“达到输出上限”说明，记录 `partial` |

未改动：`publish_official_fields` 的 known-source 契约。用户显式要求“只给已核实”
时仍 abstain；这不是模型核验失败，而是用户选择的发布口径。

## 3. 候选与证据的保留

- 门禁返回降级结果时，把**门禁前的完整候选**写入
  `rag_snapshot["answer_gate_candidate"]`（上限 120,000 字符），含 `sha256`、
  `chars`、`truncated`、`delivery_outcome`。
- 已读来源从 evidence rows、`web_tools.used_sources` 和成功的 tool calls 三处
  合并，全部经过 `_public_url`：只接受公开 `http(s)`，拒绝私网、loopback、
  带用户名/密码的 URL。
- 已知限制：这是**同一 turn 提交时**的保留，不是门禁执行前的独立事务写入。
  进程在门禁中途硬崩溃仍会丢失该次候选；A2 的候选原文因此无法逐字回放。

## 4. 四个项目的源码对照

### Codex（`openai/codex@065e18b04021008e2e7d504db8dc50275f589f73`）

源码：`codex-rs/core/src/session/turn.rs`

- L537：`stop_hook_active` 是 turn 内状态。
- L865–908：模型准备结束时运行 Stop hooks。`should_block` 且提供了
  `continuation_fragments` 时，把具体反馈写回会话并 `continue`；**没有提供
  prompt 时只发 warning 并忽略这次 block**（L908）。
- L1094–1105：`run_stop` 统一执行 hook，记录 `stop_ran`。

采用：门禁要么给出**可执行的修正动作**（删除链接、扣留块、发布草稿），要么
不得阻止交付。没有可执行指令的“继续”是无效拦截。

未采用：没有再开一次模型调用让模型“修正”。Study Agent 的修正可以是确定性的，
不增加付费调用。

### Claude Code（公开仓库 `anthropics/claude-code@102fafb0953d90cff472b438e443485e7d131d36`）

该仓库只有插件/配置/文档/脚本，没有核心 agent loop 源码，所以这里只引用官方
Hooks 文档（https://code.claude.com/docs/en/hooks ，2026-11-28 抓取）：

- `Stop` 输入包含 `stop_hook_active`：已经因 Stop hook 继续时为 true，文档要求
  检查它，避免对永远不会满足的条件反复 block。
- 连续续跑上限 8 次；达到上限后下一次 block 被覆盖，turn 结束。计数在模型调用
  工具时重置；可用 `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` 调整。
- `StopFailure` 是独立事件，定义为“turn 因 API 错误结束”，不把 API 错误和
  质量检查失败混在一起。

采用：修正必须有界（沿用已有 `allowed_attempts`，最多 2 次）；质量失败、API
失败、截断分开记录；不引入 Hooks 框架。

### OpenCode（`anomalyco/opencode@eeeeaa0db3c18567bccbd2fca68b9cc6fe6227ee`）

源码：`packages/core/src/session/runner/max-steps.ts`、`.../llm.ts`

- `max-steps.ts` L1：达到最大步数时注入 `MAX_STEPS_PROMPT`，要求**只输出文本**，
  总结已完成、未完成和下一步。
- `llm.ts` L263–282：`stepLimitReached` 时追加该提示，并设置
  `toolChoice: "none"`。
- `llm.ts` L357–389：输出上限有独立处理；连续 3 条 `finish: "length"` 才判失败，
  否则注入 synthetic 继续提示，而不是直接丢结果。
- `llm.ts` L433–450：进程重启后把未完成的 assistant/tool 调用结算为 aborted，
  保留已发生的状态。

采用：预算耗尽对应“强制收尾交付”，不是“任务失败”；截断要披露且不能无限续跑。
没有新增“再调用一次模型做总结”的成本。

### DeepSeek Harness（`deepseek-ai/deepseek-harness@4b399c39a6d1479cd84ca591b4d7c88e24d38a96`，MIT）

源码：`packages/core/agent-loop/src/agent.ts`
文档：`docs/subsystems/session.zh.md`

- L364–369：`max-tokens` 是 sticky 的；后续步骤正常完成也不能把 turn 结果降级
  成 completed。
- L490–529：流在中途 abort/error 时，把 `live.interruptedBlocks()` 作为
  `assistant/message` 持久化并标记 `interrupted: true`；没有内容才写
  `assistant/attempt`。
- L359–386：步骤失败时 `ToolCallRecovery` 把已产生的 tool results 重新写入
  session，避免工具结果随异常丢失。
- L341–413：turn 结束原因是结构化的 `completed` / `blocked` / `max-tokens` /
  `aborted` / `error`。

采用：截断状态“粘住”并披露；已读证据与候选在门禁失败后继续保留；失败原因分类
写入结构化记录。未迁移整个 session 框架。

### 4.5 第二批：DSH 的 DeepSeek 适配（源码）

同一 commit `4b399c39`，`packages/llm/llm-deepseek/src/translate.ts`、`serialize.ts`。

| 主题 | DSH 的实际做法 | Study Agent 现状 | 本轮决定 |
| --- | --- | --- | --- |
| thinking | `serialize.ts` L147–155：`thinking` 只有 `disabled` / `enabled` 两态，`max_tokens` 逐请求下发；`translate.ts` L52–54 把 `thinking` 块映射为 `reasoning`，签名单独保留用于 replay | 规划轮用 `{"thinking":{"type":"disabled"}}`，答案轮保持默认；B 的真实运行已验证该配置能完成工具循环 | 线格式一致，不再改 |
| 工具参数 | `translate.ts` L84–86 累积 `input_json_delta`；L148 在块结束时替换为完整 JSON；L166–171 在非 `max-tokens` 时校验 JSON，**max-tokens 时保留截断的工具 JSON，交给共享 assembler 修剪** | `llm_client.py` L894–902：JSON 解析失败不抛异常，记录 `invalid_tool_arguments` 并让循环继续 | 已有等价容错；不引入 assembler |
| finish_reason | `translate.ts` L101 `max_tokens` → `max-tokens`；L166 只有非 max-tokens 才校验工具 JSON；空内容且 stop 抛 `EMPTY_RESPONSE`；`refusal` 先上报已计费 usage 再抛 `CONTENT_REFUSED` | `generation_outcome.py` 把 `length` 映射为 `output_limit`；本轮新增“保留正文 + 截断说明”；空正文仍按失败处理 | 已采用截断语义 |
| 流式输出 | L490–529：中断时把 `interruptedBlocks()` 持久化为 `assistant/message` 并标记 `interrupted`；没有内容才写 `assistant/attempt` | 研究轮在门禁前缓冲候选；本轮把候选写入 `answer_gate_candidate`，门禁失败不再丢 | 已采用“部分输出保留” |
| 异常恢复 | L359–386：步骤失败时 `ToolCallRecovery` 重放已产生的 tool results；L533 起 `agent/request-error` 可重试一次 | 工具结果已在 `web_tools.calls` / evidence rows 中；门禁异常被捕获并降级 | 不迁移 session 框架 |
| 上下文 | `docs/subsystems/session.zh.md`：从会话事件重建上下文，事件带 turn/step 序号 | `llm_context.py` 已有工作上下文压缩；本轮未改 | 暂缓，等真实长任务样本 |

结论：第二批只有“截断状态要保留并披露”是可落地的差异，已在 #705 完成；其余差异要么 Study Agent 已有等价容错，要么属于会话框架迁移，不在本轮范围。

## 5. 免费验证

- 影响集：`test_answer_publication_gate.py`、`test_research_delivery.py`、
  `test_research_answer_streaming.py`、`test_chat_research_publication.py`、
  `test_answer_links.py`、`test_chat_service.py`、`test_performance_budget.py`、
  `test_chat_stream_cancellation.py`，共 **151 passed**；Ruff 干净。
- B2 的 16k 实际答案（`docs/research_quality/evidence/rab-20261127/round2/answer-b-16k.md`，
  11,341 字符）静态回放：26 个链接、3 个唯一 URL，全部属于本轮读取的 3 个来源；
  outside = 0，删除 = 0。链接门禁不会拦截它。
- A2 的失败模式用原始两个未读 URL 做等价合成回放：
  `MutableCompoundShape.cpp#2` 与 `https://opendeer.net/` 均被识别并删除，
  删除后 outside = 0，输出以 `【部分结论尚未核实】` 开头并保留已读来源。
  A2 候选原文没有持久化，因此这不是逐字回放。
- 没有新的付费模型调用；账本未变化。

## 6. 已知限制与风险

1. 只识别 URL 形式的引用；纯文本提到未读来源仍不会被识别。
2. `strict` 模式的行为已改变：不再整轮拒发，而是发布带标签草稿；但
   `answer_claim_snapshot.status` 仍为 `rejected`，结构化契约没有被伪装成通过。
3. `answer_gate_candidate` 是 turn 提交时保留，不是崩溃前独立落盘。
4. 一致性检查默认关闭；开启时按 claim 文本/拒绝短语做块级删除，无法定位时整份
   降级，不做语义猜测。
5. 官方来源字段发布（`publish_official_fields`）仍可能 abstain；这是用户显式
   “只要已核实”口径，不属于本轮修复范围。

## 7. 下一步

- 用三类真实任务（技术研究、社区攻略、开源项目分析）做端到端对照，验证草稿
  交付在真实运行中的比例和可用性；需要新预算授权。
- 若真实运行仍出现“整轮无输出”，优先检查是否有新的非安全拒绝分支绕过了
  `research_delivery` 记录。
