# 研究完成判断与失败恢复审计（2026-11-28）

范围：普通语义研究、RQCE、自主研究三条路径；重点是“为什么提前结束”，
以及工具失败后是否尽力恢复。基线 `main@b2736bfc`，本轮无付费模型调用。

## 1. 结论

之前最根本的缺陷不是“没有资料”，而是**把模型停止调用工具当成研究完成**。
`src/llm_client.py` 的 `run_tool_loop` 在 `raw_calls` 为空时直接
`mark_stop("completed")`，不再检查是否读过正文、搜索是否为空、读取是否失败、
或模型自己是否说“资料不足”。

本轮把它改成“候选完成 + 有界缺口检查”：

- 仍然允许模型在证据足够时结束；没有固定最低来源数。
- 只有在出现**可观察的未完成动作**时才继续：零工具调用、零结果搜索、
  全部读取失败、找到候选但零正文、模型声称资料不足但候选未读、
  读取成功但只是 JS 壳/反爬页/短导航文本。
- 每次续跑都有具体下一步，不允许无指令的“继续”。
- 最多 2 次续跑，且始终为最终回答保留 1 次模型调用；超过就接受当前结果。
- 续跑消息会列出具体未读来源或失败域名，避免重复同一个无效调用。

## 2. 三条路径的审查

| 路径 | 完成判断 | 本轮结论 |
| --- | --- | --- |
| 自主研究 | 原为 `if not raw_calls: completed`（`llm_client.py` L876–889） | **缺陷，已修**：新增 `completion_check`，自主路径传入 `research_completion_gap` |
| 普通语义研究 | `research_recovery.recover_public_research` 按计划阶段执行，检测到缺口时插入 `gap_fill`（L779、L1200），不是模型不调用工具就结束 | 已是缺口驱动；未改 |
| RQCE | `active_research_runtime` 用 `_ordered_gaps`（L2436）规划查询，`completed_wave_stop_signal`（`research_runtime_wave_settlement.py` L89）按 `has_actionable_gaps` / saturation / gate 决定是否停 | 已是缺口/饱和驱动；`coverage_stop_assessment` 仍是 advisory，未接入停点 |

因此，“模型只读两份就停”主要是自主路径的问题；RQCE 和普通语义路径的停点
本来就不依赖模型是否继续调用工具。

## 3. 失败恢复矩阵

| 情况 | 现有能力 | 本轮动作 |
| --- | --- | --- |
| 搜索无结果 | 模型可改写；state block 显示 `searched -> 0` | 续跑消息明确要求换关键词/语言/平台 site_key；不把空结果当不存在 |
| 結果质量差 | 提示词要求优先官方/一手来源；RQCE 有候选排序 | 未新增排序；自主续跑只指出“读最权威候选” |
| HTTP 读取失败 | `tool_gateway.read` 自动尝试 paired browser（L1471） | 保持；续跑消息给出 `mode="browse"` |
| 正文提取成 JS 壳/反爬页 | `read_adequacy` 已能分类，但短读升级默认要开关 | **自动升级**：`js_shell` / `anti_bot_or_error` 即使未开 `WEB_BROWSE_READ_ENABLED` 也尝试一次浏览器；普通短页仍不自动开浏览器 |
| 视频无字幕 | `video_read` 自动走 SenseVoice ASR | 保持 |
| 视频关键信息在画面 | `include_ocr=true` 时本地 OCR | 保持显式调用；未自动 OCR（代价高，需单独授权/验证） |
| 资料过时 | 提示词要求记录版本/分支/commit 并检查新版本 | 保持 |
| 资料矛盾 | RQCE 有 conflict gap / authority 规则；自主路径只靠提示词 | P1，未新增机制 |
| 模型提前停止 | 原为直接完成 | **有界续跑**，见上 |
| 引用有问题 | #704/#705 已做局部删除/降级 | 保持 |

## 4. 源码对照（固定 commit）

- **Codex** `065e18b0` `codex-rs/core/src/session/turn.rs` L865–908：
  Stop hook 只有带具体 continuation prompt 时才继续；没有 prompt 时
  warning 并忽略 block。对应：续跑必须带可执行指令。
- **Claude Code** 官方 Hooks 文档（公开仓库 `102fafb0` 不含核心 loop）：
  `stop_hook_active`、连续续跑 8 次上限、`StopFailure` 单独表示 API 错误。
  对应：续跑有界，且失败类型分开。
- **OpenCode** `eeeeaa0d` `runner/max-steps.ts` L1、`runner/llm.ts` L263–282：
  达到步数上限注入“只输出文本”的收尾提示并 `toolChoice:"none"`；输出上限
  连续 3 次才失败。对应：预算耗尽要收尾，不是丢结果。
- **DSH** `4b399c39` `agent-loop/src/agent.ts` L359–386、L490–529：
  步骤失败时回收 tool results；流中断时持久化已产生内容；`max-tokens` sticky。
  对应：工具失败/中断不抹掉已完成工作。

## 5. 验证

- 新增/更新测试：
  - `tests/test_research_completion.py`：零工具、空/截断、零结果、只搜不读、
    全读取失败、声称缺失但有未读候选、短壳页、单篇充分读取接受回答、
    视频读取不按短页处理。
  - `tests/test_llm_tool_loop_continuation.py`：续跑一次且保留证据、保留最终
    回答调用、续跑上限、检查函数异常不终止循环。
  - `tests/test_browse_read.py`：JS 壳无开关也升级浏览器；普通短页不启动浏览器。
  - `tests/test_persistent_web_agent.py`：自主路径确实传入完成检查和 2 次上限。
- 影响集 **203 passed**；Ruff 干净。
- 免费回放：
  - Round 1 A 组真实 trace（14 次调用、10 次成功读取）经过新检查返回
    `None`，不会强制增加读取；说明“读得够”时不会为凑数继续。
  - 同一条 trace 若只有搜索没有读取，则返回“找到候选但未读正文”；
    全部读取失败时返回 `mode="browse"` 建议。均由单元测试固定。
- 未产生付费调用；账本未变化。

## 6. 已知限制

1. 完成检查只识别**可观察**的缺口，不判断答案是否覆盖了所有语义子问题。
   模型读了 2 篇充分资料并自信结束，仍会被接受；这避免把固定阅读数当质量。
2. 资料矛盾、过时版本、第三方反例仍主要靠提示词和 RQCE 的 conflict gap，
   自主路径没有新增 claim 级规划。
3. `coverage_stop_assessment` 仍是 advisory；没有把它接成硬门禁。
4. 自动浏览器升级只覆盖 JS 壳/反爬页；普通短页仍受开关控制，避免每次短读
   都启动浏览器。
5. 视频 OCR 仍为显式 `include_ocr`；没有在“无语音”时自动下载视频轨跑 OCR。
6. 本机存在 `browse` 可执行文件时，`test_deepseek_web_tools` 的一个搜索回退
   断言会因浏览器先返回结果而失败；这是环境差异，不是本轮代码改动。
