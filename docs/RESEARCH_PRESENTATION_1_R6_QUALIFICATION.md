# RP-1 R6：真实运行与预算联合诊断（2026-10-08）

**裁定：本批次已完成，R6 NO-GO，RP-1 NOT CLOSED。** 没有真实 Standard
continuation / 后台 Deep child / Deep terminal / Deep-4A audited 链，不能进入 RP PR 门。
S5 恢复前置条件未出现；不以旧版同步 Deep、模拟 child 或未触发事件补齐。

## 冻结与复现入口

- branch `codex/reading-notebook-ui`，干净实现候选
  `4c36b93507abacaff83b34a1a0195ad180a4bf47`；运行期间生产文件摘要保持不变。
- 注册时新 main / #201 merge：`5f4e81e22ab85c0a27c3ad82214c0f1dc62b79eb`。
  未向候选同步旧/新 UI；后续只有 R6 封板后才比较并转移 `ec02590f..4c36b935` 的 RP 增量。
- 2026-10-08T13:02:20Z 预登记，manifest SHA256
  `e02a0c3b3d4df5ca7d1d377ef5fe8f7ce72482deb550ec1ef0a8b69338bf9cd8`。
- 五个样本各只提交一次真实 `/chat/stream`，真实 React/Vite → FastAPI → SQLite，
  浏览器默认自动角色/模型/意图，不注入升级、gap、child 或 API 响应。
  会话创建的等待和离开确认仅修正观察脚本；首次提交前的两个定位失败没有创建 turn。
- 真实 provider 配置来自现有 `.env`；隔离 DB/export/临时本地 API token。
  三例实际调用官方 `official_resolve/web_read`；S2/S4 在搜索派发前失败。
  **不是“五个真实搜索提供商成功样本”**，不把未执行的搜索计为 provider 验收。
- 预算、研究模型调用配额、研究资格、证据/发布权限均未修改。没有新增 UI 功能。
  本批次不重做既有 466 前端 / L2 258 / 浏览器 79 / real-stack 14 回归。

证据根目录 `D:/study-agent-validation/reading-notebook-ui-evidence/r6-batch-1/`：
`registry.json/.sha256`、`result.json`、`runtime.db`、`durable-trace.jsonl`、
`S1..S5-browser.json`（真实请求/完整 SSE/恢复 GET/DOM）、
`S1..S5-durable.json`（同 turn/run 原始记录与最终快照）、`S1..S5.png`、服务日志。
观察脚本在该目录的父目录：`r6-supervisor.py`、`r6-browser-template.js`、
`r6-generate-browser.py`、`r6-analyze.py`。只读分析可重跑，provider 批次不可无理由重跑。
所属后端/Vite 与浏览器已关闭；未触动原 main/A 线 dirty。

## 五个预登记样本

| 样本 | 域 / 原始问题 | requested fields | 实际结果 / 首次阻断 |
| --- | --- | --- | --- |
| S1 | 支持域；SQLite 3.45.3 发布日期和变化 | changes, release_date | VERIFIED / requested_claims_bound；无需升级 |
| S2 | 通用；比较 Claude Opus 5.5 与 Gemini 2.5 Pro 的 API 价格、上下文窗口和适用边界，核验官方来源，保留冲突和未知项。 | 无 | run failed；SemanticRecovery blocked: ValueError: question_identity；最终 SAFE_ABSTAIN / requested_claim_plan_unavailable |
| S3 | 支持域；Opus 5.5 发布日期、版本号和定位 | official_positioning, release_date, version | SAFE_ABSTAIN / no_verified_relevant_source；release_date 未绑定 |
| S4 | 通用；比较原始 Transformer 与检索增强生成在课程资料问答中的可靠性、成本和失效边界，核验论文与复现实验，保留未解决的关键问题。 | 无 | run failed；SemanticRecovery blocked: ValueError: invalid_rows；最终 SAFE_ABSTAIN / requested_claim_plan_unavailable |
| S5 | 支持域；FastAPI 0.136.0 发布日期和版本号 | release_date, version | SAFE_ABSTAIN / no_verified_relevant_source；release_date 未绑定；NOT_EXECUTED_NO_LIVE_DEEP |

S1/S3/S5 自动 task_intent 为 quick_answer，但正式 Lookup 门仍执行；S2/S4 自动为
research。意图、字段计划与实际运行层级分别记录，不互相冒充。Standard/deep 均
NOT_ADMITTED；其 stop_reason、unresolved gap、模型/时间/读取消耗没有观测值，不能补 0。

每例真实 thread_id / turn_id / run_id / parent_run_id / root_run_id / version /
stop_reason / 完成时间保存在 `result.json` 的 lineage 中。五个 root run 最终 version=3，
没有 parent child。已留出一次 20 秒观察窗口覆盖后台 runner 的 15 秒扫描，不手动唤醒。

## 首次阻断与权限

1. **支持域资格适配不匹配，非预算耗尽。** S3/S5 的 trusted web_read 各为 1，
   content 非空且 SHA256 有效、target_coverage=1/1，但 exact_named_version_match=false。
   实际正文分别为 `project: Claude Opus\nversion: 5.5\n...` 与
   `project: FastAPI\nversion: 0.136.0\n...`；`_exact_target_pattern` /
   `target_identity_pattern` 要求相邻名称和版本，不能跨越 `version:` 标签。
   `_verified_relevance_sources` 因此返回 0。不存在已经合格而漏执行 trigger 的证据。
   FastAPI 的 distribution_uploaded_at 不等于 release_date，未人为闭合该缺口。
2. **通用研究存在更早的执行失败。** S2/S4 的 run.stop_reason=chat_tool_loop_failed，
   provider_status=provider_failed，但原始 error 是语义 schema 校验错误，不足以归因
   网络 provider outage。`questions()` 的 question_identity 表示空/重复问题身份；
   `_rows()` 的 invalid_rows 有多个拒绝条件。缺少原始模型回复/调用计量，不能继续
   猜测具体分支或消耗；需独立保留原始结构化输出观测后诊断。最终无合法字段计划也是
   handoff 的阻断，但不是这些 run 的第一个执行错误。不能由此宣布整套 Deep 失效。
3. **Deep-4B 权威没有放宽。** 五例投影 publication_authority=false；无 audited
   candidate。S1 的 official-field publication 与 requested fields 机械绑定通过；
   S3/S5 只发布已有官方字段，不把未绑定字段或模型候选当作正式支持。

## 预算与延迟：单次观测，没有 SLO 资格

| 样本 | Lookup recovery elapsed | recovery searches / reads / chars | 首个研究状态可见 | 持久 turn 终态观察延迟 | TTUV |
| --- | --- | --- | --- | --- | --- |
| S1 | 4.687s | 1 / 1 / 1981 | 1.022s | 5.699s | NOT_OBSERVED |
| S2 | NOT_OBSERVED | NOT_OBSERVED | 0.144s | 3.451s | NOT_OBSERVED |
| S3 | 7.703s | 1 / 1 / 106 | 0.135s | 8.015s | NOT_OBSERVED |
| S4 | NOT_OBSERVED | NOT_OBSERVED | 0.161s | 3.313s | NOT_OBSERVED |
| S5 | 2.953s | 1 / 1 / 87 | 0.134s | 3.141s | NOT_OBSERVED |

首个研究状态可见由实际 DOM 可见区域观测，代表持久研究生命周期进度，不代表已搜索
或已有有用证据；S2/S4 没有搜索成功。持久终态延迟使用每 0.2 秒只读 SQLite 观察，
有采样/调度误差，不是精密耗时。浏览器另保留 first_answer_visible_at，但它只检查
正文容器，未记录合格字段片段在该时点的可见性；**不回填 TTUV**。Deep 审计也不具有
TTUV 资格。没有零秒占位或首次提示冒充有用内容。

recovery.searches 是既有逻辑计数，official_resolve 可以计入，不等于物理搜索请求。
model_calls 未有完整生产计量，标 NOT_OBSERVED；answer_generation_calls=0 仅证明
该回答阶段，不能解释为全链模型调用为 0。记录的三例 Lookup 未触及 30s/3 reads/
16000 chars；没有 Standard/Deep 可用于 60→90s 或 Deep 六模型调用配额的比较。
没有 wall_time/read/model/character/saturation 停止证据时保留未观测，不反向构造 stop。

## 同版本 UI 与服务端核对

来源 URL 与 run 版本五例均一致；缺口未知显示“—”，冲突未知未补“0”，审计未造就绪。
**读取数不一致：S1/S3/S5 的最终 turn 快照 version=3、read_count=1，而页面同版本
显示 0；手动刷新仍为 0。** SSE run 快照缺少 turn recovery，只读出 read_summary=0。
`mergeResearchPresentation` 仅在 incoming revision 更大时替换 block，忽略了同版本
turn 快照提供的更完整观测。三个真实样本复现，S1 截图已视觉核对。这个新增真实
finding 不能被之前的 R1–R5 mock/回归 PASS 覆盖，也没有修改候选掩盖它。

## 下一执行切片

停止本批次，不追加 S6，不调预算、不伪造 upgrade，不推送 RP PR。交付三项可复核
阻断：支持域身份匹配、通用语义校验失败、同版本投影合并。建议先独立修复
**同版本 turn 补全的只读前端合并**，用本批次真实持久记录重放验证；升级身份适配与
通用语义执行需另立 bounded 引擎修复合同，保留资格/发布权限。修复并取得授权后再
另开预登记 qualification 批次；真实后台恢复、完整 lineage 和 TTUV 仍是封 R6 的门。
本轮只有文档提交，未执行新 L3、push、RP PR 或 exact-head CI。
