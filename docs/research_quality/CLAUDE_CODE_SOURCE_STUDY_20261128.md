# Claude Code 恢复源码研究：机制、差距与取舍（2026-11-28）

本轮只做只读调研，不产生付费模型调用，也不复制专有代码。

## 0. 资料来源与可信度

| 来源 | 固定版本 | 类型 | 许可/使用边界 |
| --- | --- | --- | --- |
| [`PM-Shawn/claude-code-source`](https://github.com/PM-Shawn/claude-code-source) | `ae56bff1abdb503b2673122e23060c08bafd7bbb` | 2026-03-31 npm `@anthropic-ai/claude-code@2.1.88` 意外携带 `cli.js.map` 后恢复的 TypeScript 源码；仓库 README 明确说不是反编译 | 仓库无许可证；源码属于 Anthropic，**只用于阅读机制，不复制代码、常量或文案** |
| [`ComeOnOliver/claude-code-analysis`](https://github.com/ComeOnOliver/claude-code-analysis) | `c45730b02591b6992dfc8aaa3483fd01b213815e` | 第三方架构分析（MIT） | 用于交叉核对模块边界，不作为运行时事实的唯一来源 |
| [`cablate/claude-code-research`](https://github.com/cablate/claude-code-research) | `2c5df191f5667ac1188766a18264e54ce2f028b5` | 独立研究（缓存、上下文生命周期、工具序列化） | 用于对照缓存/上下文结论；不当作官方契约 |
| [`VILA-Lab/Dive-into-Claude-Code`](https://github.com/VILA-Lab/Dive-into-Claude-Code) | `ae32837c546a24a29e42d936b2af1875ab7bd5c7` | 系统性架构论文/文档（NOASSERTION） | 用于确认整体分层与“核心循环很薄、周边系统很厚”的判断 |
| [`JohnPitter/the-harness`](https://github.com/JohnPitter/the-harness) | `1e04157ad99cdac5b7d74b6f1fb0d72fabdf40b9` | 第三方完整技术参考（MIT） | 用于 Query Loop 流程与工具生命周期的交叉核对 |
| [`Yuyz0112/claude-code-reverse`](https://github.com/Yuyz0112/claude-code-reverse) | `c0d99ea1ab7168c12ba74838cfea355ce10f6c56` | 交互可视化/逆向观察工具 | 只能证明交互形态，不当作内部实现证据 |

恢复源码的完整性我没有逐文件对照 npm source map 验证；但读到的文件包含完整 TS 类型、import 图和实现逻辑，足以做机制级对照，不足以声称“每个细节都与官方二进制一致”。

## 1. 核心结论

Claude Code 的核心不是一个会“自动变聪明”的循环，而是：

> **一个很薄的 while 循环 + 很厚的上下文/工具/任务/恢复系统。**

`query.ts` 的循环本身只做“准备上下文 → 调模型 → 执行工具 → 收集结果 → 决定是否继续”。真正让几十轮任务不崩的是循环外面的五层：

1. 工具结果预算与磁盘持久化；
2. 多级上下文压缩（snip / microcompact / collapse / autocompact / reactive）；
3. 模型可写的 Todo 与 Plan/Explore 子代理；
4. 中断恢复与 sidechain transcript；
5. prompt cache 稳定性观测。

Study Agent 目前有第 1 层的简化版（上下文压缩 + 本轮读取缓存）和第 3 层的提示词版（研究状态块），但没有持久化工具结果、Todo/Task、子代理、sidechain 恢复。

## 2. 逐模块源码事实

### 2.1 Query Loop：循环很薄，退出条件不止“模型停手”

`src/query.ts`：

- L307 `while (true)`：真正的 agent loop。
- L365–467：每次模型调用前依次执行
  - `applyToolResultBudget`（L379，工具结果预算/替换）
  - `snipCompactIfNeeded`（L403，历史剪裁）
  - `microcompact`（L414，缓存感知的工具结果清理）
  - `contextCollapse`（L441，折叠视图）
  - `autocompact`（L454，整段摘要压缩）
- L530–537：压缩成功后把 `buildPostCompactMessages` 放回上下文并 `continue`，不是结束任务。
- L1015–1051：流式 abort 时生成缺失的 tool_result，返回 `aborted_streaming`，不把半截状态伪装成完成。
- L123–142：`yieldMissingToolResultBlocks` 为每个没有结果的 tool_use 补一条中断结果，保证 API 消息合法。

对照：Study Agent 的 `run_tool_loop` 已有 `completion_check`（L741）和 `compress_working_context`（L848），但没有“压缩后继续”的多级管线；压缩是单层的，且不会在压缩后重新评估是否应继续。

### 2.2 Token Budget：按“预算使用率 + 收益递减”继续

`src/query/tokenBudget.ts`：

- L4 `COMPLETION_THRESHOLD = 0.9`，L5 `DIMINISHING_THRESHOLD = 500`。
- L45–90 `checkTokenBudget`：
  - 未到 90% 且没有收益递减 → `action: 'continue'`，附 `nudgeMessage`；
  - 连续 3 次续跑后，若两次增量都 <500 tokens → 判定收益递减，停止；
  - 已有续跑但不再满足继续条件 → 停止并记录 `completionEvent`。

这不是“固定轮数”，而是“预算没用完且还在产生增量就继续”。Study Agent 的 `completion_check` 目前只看可观察缺口，没有“证据增量/收益递减”信号；这是 P2 可借鉴点，不应直接照搬 token 阈值。

### 2.3 工具结果：大结果落盘，上下文只留预览，可重新读取

`src/utils/toolResultStorage.ts`：

- L2 文件头：**persisting large tool results to disk instead of truncating them**。
- L137 `persistToolResult`：超过阈值的结果写入 `tool-results/`，返回 `filepath + preview`。
- L175–183：`generatePreview(content, 2000)`，预览最多 2,000 字节，并标记 `hasMore`。
- L189 `buildLargeToolResultMessage`：用 `<persisted-output>` 标签包住预览，正文不进入上下文。
- L376–392：`ContentReplacementState` 保存 `seenIds` 和 `replacements`；**一个结果一旦被替换，它的命运在会话内冻结**。
- L447 `provisionContentReplacementState`：冷启动新建；恢复时从记录重建，保证同样的结果得到同样的替换（prompt cache 稳定）。
- L643–661：把结果分成 `mustReapply` / `frozen` / `fresh`；已替换的复用原替换字符串，已见过的未替换结果不再改，只有新结果可被替换。
- L769 `enforceToolResultBudget`：按“单条消息聚合预算”选择最大的新结果替换，冻结前缀不动。

`src/services/compact/microCompact.ts`：

- L253 `microcompactMessages`；L305 `cachedMicrocompactPath`。
- L296–338：缓存感知的 microcompact 通过 cache editing 删除旧 tool result，而不重写本地消息；删除数量由 GrowthBook 配置的触发/保留阈值决定。

对照：Study Agent 的 `src/llm_context.py` L102 `compress_working_context` 把旧工具结果变成摘要（url/status/size/excerpt），但没有把完整正文持久化，也没有“按 call id 重新取回”的工具。我们本轮新增的读取缓存只在同一个 `AutonomousToolBudget` 生命周期内有效，进程重启/上下文压缩后仍可能拿不到全文。

### 2.4 Todo / Task：模型自己维护，程序只做结构提醒

`src/tools/TodoWriteTool/TodoWriteTool.ts`：

- L65–70：每次写入读取旧列表；全部 completed 时清空列表。
- L72–86：主线程关闭 3+ 项且没有任何 verification 项时，设置 `verificationNudgeNeeded`。
- L104–113：工具结果追加提醒——关闭 3+ 任务却没有验证步骤时，要求先跑 verification agent，不能自己在总结里写 caveat 代替验证。

`src/tools/TodoWriteTool/prompt.ts`：

- L9–23：何时用/不用 Todo（3+ 步骤、复杂任务、用户明确要求；单一琐事不用）。
- L148–166：状态只允许 `pending` / `in_progress` / `completed`；**任意时刻只能有一个 in_progress**；完成任务立即标记；遇到错误/阻塞保持 in_progress 并新建任务；不能把未完成说成 completed。

对照：Study Agent 没有模型可写的 Todo/Task；`build_research_state` 只显示搜索/读取/未读候选，不记录“子问题状态”。这不是必须马上加的硬门禁，但可以作为 P1 的“研究任务账本”。

### 2.5 Explore / Plan 子代理：只读、并行、独立上下文

`src/tools/AgentTool/built-in/exploreAgent.ts`：

- L24–56：文件搜索专家，只读；按调用方给的 thoroughness 调整搜索；鼓励并行 grep/read。
- L59 `EXPLORE_AGENT_MIN_QUERIES = 3`。
- L64–79：`agentType: 'Explore'`；外部用户默认 haiku；工具集只读。

`src/tools/AgentTool/built-in/planAgent.ts`：

- L21–70：软件架构/规划专家，只读；输出 3–5 个关键文件、步骤、权衡；禁止写文件。
- L73–88：`agentType: 'Plan'`；复用 Explore 的只读工具集；模型 inherit。

`src/tools/AgentTool/runAgent.ts`：

- L248 `runAgent`；L368–373：fork 上下文时先过滤不完整 tool call，再拼 prompt。
- L716–760：为子代理创建独立 `ToolUseContext`；L733–754 记录 sidechain transcript；L754 传 `maxTurns`。
- L866 `filterIncompleteToolCalls`：恢复/ fork 时丢掉没有 tool_result 的 assistant tool call，避免 API 错误。

对照：Study Agent 没有子代理。用户已明确暂缓子代理/多 Agent，所以本轮**不建议**为此改架构；可借鉴的是“只读探索”和“独立上下文”这两个边界，而不是马上引入 Explore/Plan。

### 2.6 会话恢复：中断的 turn 会补一句“继续”

`src/utils/conversationRecovery.ts`：

- L164 `deserializeMessagesWithInterruptDetection`。
- L187–202：恢复时过滤未完成的 tool use、孤立的 thinking-only assistant、空白 assistant。
- L204–224：检测到 `interrupted_turn` 时，追加 `Continue from where you left off.` 的 meta user message，并标记 `interrupted_prompt`。
- L226–245：如果最后一条是 user，补一个 synthetic assistant sentinel，保证会话对 API 合法。

对照：Study Agent 的 `chat_service` 有 turn 失败/重试/取消和 durable `rag_snapshot`，但没有“中断后自动续跑”的消息级恢复；研究轮失败后通常要用户重新发问。可借鉴“检测中断 → 明确续跑指令”，但不必引入完整 sidechain。

### 2.7 Prompt Cache：稳定性是观测出来的，不是猜的

`src/services/api/promptCacheBreakDetection.ts`：

- L247 `recordPromptState`：记录 system/tools 的 hash、字符数、逐工具 schema hash。
- L437 `checkResponseForCacheBreak`：比较 cache read tokens 的下降，判断 system prompt 改动、tools 改动、TTL 过期或服务端原因。
- L502–587：把原因归类为 system/tools 变化、1h/5min TTL、服务端或未知。

对照：Study Agent 使用 DeepSeek/OpenAI-compatible 接口，缓存行为与 Anthropic 不同；在没有实测 cache read 数据前，不应照搬 cache_edits 或 TTL 常量。可借鉴的是“记录 system/tools hash 与 cache 命中变化”，作为诊断字段。

## 3. 与 Study Agent 的逐项差距

| 模块 | Claude Code | Study Agent 当前 | 差距/判断 |
| --- | --- | --- | --- |
| Agent loop | `query.ts` while + 多级压缩 + abort 补齐 tool_result | `llm_client.run_tool_loop` + `completion_check` | 循环已有；缺压缩后继续、缺失工具结果补齐的系统化处理 |
| Token budget | 90% + 收益递减续跑 | 可观察缺口续跑，最多 2 次 | 可加“证据增量/收益递减”，不要照搬 token 阈值 |
| 工具结果 | 大结果落盘，预览 + 冻结替换 + 恢复重建 | 摘要压缩，完整正文只在 trace；本轮读取缓存仅进程内 | **最值得补**：持久化结果 + 按 id 重新取回 |
| Todo/Task | 模型维护，状态约束，验证提醒 | 无 | P1 可做轻量研究任务账本；不做硬门禁 |
| Plan/Explore | 只读子代理，独立上下文，并行搜索 | 单循环，提示词内规划 | 用户暂缓子代理；不采用完整子代理 |
| 会话恢复 | 中断检测 + “Continue from where you left off” | turn 失败/重试，无消息级续跑 | P1 可做中断续跑提示 |
| Prompt cache | 前缀 hash/缓存断点观测 | 无显式观测 | P2 先测 DeepSeek 缓存，再加诊断 |
| Verification | 3+ 任务关闭时提醒验证 agent | 发布门禁 + binder | 不新增模型调用；暂不引入 verifier 子代理 |

## 4. 值得采用 / 不值得采用

### 值得采用（按优先级）

1. **持久化工具结果 + 重新取回（P1）**
   - 复用现有 `rag_snapshot`/run trace，不新增外部平台。
   - 大结果写本地有界存储，上下文只留 `url/status/size/digest/预览` 和 call id；模型可通过已有研究工具按 id 取回正文。
   - 冻结已替换结果，保证恢复后前缀稳定；设置总容量/TTL，避免磁盘膨胀。
   - 直接解决“压缩后模型需要重新访问同一资料”的问题，比禁止重复读取更合理。

2. **轻量研究任务账本（P1）**
   - 复用 `build_research_state`，增加“子问题 / 状态 / 已用来源”，由模型更新；不设固定最少来源数，不把 Todo 当发布门禁。
   - 关闭 3+ 子问题时提示“还有未验证项”，但只作为提醒，不强制额外付费调用。

3. **中断续跑（P1）**
   - 研究轮在 `finish_reason=length`/流中断/进程重启后，如果已有证据，注入“从上次中断处继续”的明确指令；不要重新从头搜索。
   - 需要保留现有 `stop_reason`/`completion_gap`/partial evidence，不新增状态机。

4. **证据增量/收益递减（P2）**
   - 在 `completion_check` 中记录“新增了哪些来源/解决了哪些缺口”；连续多轮没有新增有效证据时停止续跑。
   - 不使用固定阅读数，不因单次搜索为空就判定不存在。

5. **缓存诊断字段（P2）**
   - 记录 system/tools hash、cache read/write、cache 命中变化；先测量 DeepSeek 的真实缓存行为，再决定是否优化。

### 不值得采用（本轮/近期）

- **完整 Explore/Plan 子代理**：用户已暂缓子代理；会引入新的上下文、权限、结果汇总和成本边界。
- **TodoWrite 的 3+ 任务验证强制**：需要 verifier 子代理/额外模型调用；当前发布门禁已承担部分职责。
- **Anthropic 的 cache_edits / TTL 常量**：绑定其 API 与缓存实现；Study Agent 使用不同 provider，先测量。
- **固定 `EXPLORE_AGENT_MIN_QUERIES=3`**：这是 Claude 搜索代理的启发式，不是研究质量规则；Study Agent 不设固定阅读数。
- **复制恢复源码**：无许可证、专有代码；只读机制，不复制实现、常量或提示词。

## 5. 对当前 Study Agent 的具体建议

- 先做 P1 的“工具结果持久化 + 重新取回”，因为它同时解决上下文压缩、重复读取和恢复三个问题，且不需要新模型调用。
- 再做 P1 的“轻量研究任务账本”和“中断续跑”，都用现有 `rag_snapshot` 与 `stop_reason`，不新建框架。
- P2 的 token/收益递减与缓存诊断，先用真实运行数据验证；没有数据前不调参数。
- 继续禁止把“固定阅读数”当质量，也不把 Todo 完成当发布许可。

## 6. 本轮验证与限制

- 只读源码/文档；无付费模型调用，账本未变化。
- 恢复源码版本固定为 `ae56bff1`；第三方分析固定到各自 commit。
- 未逐文件核对 npm source map 的完整性；未运行 Claude Code 本身；未验证第三方仓库与恢复源码的逐行一致性。
- 结论用于设计借鉴，不作为“官方实现就是这样”的绝对断言；官方文档与恢复源码在文中已分开标注。
