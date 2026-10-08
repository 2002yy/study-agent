# RP-1 真实 Deep 进程重启恢复

2026-10-09；恢复验收 LOCAL PASS / CLOSED，RP-1 / R6c 仍 NO-GO。
branch `codex/reading-notebook-ui`，基线 `1740237602e25d9bf30d7195d70f670d4c0a21e0`，
生产恢复点仍 `6c539d2b`。本切片无生产代码、预算、schema、资格门、UI 或学习写入变更。

## 原样任务与中断

仅重放一次既有 S5 原始 API 请求“FastAPI 0.136.0 发布日期和版本号”，
去掉原 session/thread/turn/operation ID；请求在执行前登记，使用真实提供商。
新证据 DB 独立于前批，未注入 handoff、ESCALATE_DEEP 或 unresolved gaps。
后台使用原生产 app / startup worker；backend wrapper 只记录本窗口 PID，未 hook 执行函数。

| 身份 / 状态 | 实际值 |
| --- | --- |
| thread | `chat_55f1b9a602b146f390205c6393e18150` |
| turn | `turn_3b3e74429c914b6480303156ae8d8728` |
| Standard parent | `standard-15021302b0f38ae8a557f6bc` |
| 原始及恢复 Deep child | `deep-9b599f61ccdb87cab6f3f089` |
| 原 / 新 backend PID | 25168 / 13280 |
| 中断状态 | running / searching / wave 1 / version 12 |
| 已完成操作 | research_claim_planning attempt 1，原审计已持久化 |
| 未完成操作 | discovery search attempt 1，原 inflight marker 已持久化 |
| 恢复持久终态 | partial / evidence_saturated / version 83 |

真实硬终止本窗口 backend，保存完整中断前 row 及停机后 SQLite backup，
随后正常启动 app；未写 DB、未强行释放执行占用、未直接调用 consume 或补造第二个 child。
操作时间记录为 UTC（2026-10-08T17:19–17:21），对应用户时区 2026-10-09 凌晨。

## 验收证据与恢复限制

证据目录 `D:/study-agent-validation/reading-notebook-ui-evidence/r6c-process-restart/`：
`registry.json`、`before-kill-row.json`、`before-kill-summary.json`、`after-kill.db`、
`result.json`、最终 `runtime.db`、三代 server / PID 记录、`audit.json` 与 `terminal-probe.json`。
`run.py` 驱动真实请求/kill/restart；`audit.py` 只读调用原 validator；
`terminal-probe.py` 正常再次启动，经过一个 15 秒扫描周期（观察 17 秒）后检查终态。

17 项恢复检查 PASS：真实 PID 更换、持久非终态中断、同一且唯一 child、父子/thread/turn 绑定、
revision 不下降、恢复后持久终态、原 terminal/publication validators、审计绑定 child hash、
seed hash/projection、原 deadline/seed 未变、已完成规划调用恰一次、
中断 attempt 明确 unknown、terminal inflight 清空、原 cursor validator、
发布权仍 false、GET 终态不重新 running。

另 4 项终态再启动检查 PASS：所有研究 run rows 完全相同、快照不 running、
仍仅原 Deep child、两个快照完全相同；没有重跑已结束研究或重新生成审计记录。
审计 SQLite 前后字节 hash 一致。原 completed planner call ID / 内容完整保留，未出现第二次规划。

**Exactly-once 的实际证明范围：** 持久 child / lineage / 已完成规划操作 / 持久终态没有重复。
杀进程时外部搜索没有确认完成，恢复明确记 search_failed / interrupted_unknown，
允许原合同下重试；无法证明远端提供商只收到一次请求，不宣称网络副作用 exactly-once。

重启后先等待原执行占用过期：`WebLookupRepository.operation_is_stale` 默认 120 秒，
worker 每 15 秒重新发现；过期前同 child 仍在 version 12，随后自动接管。
没有按 PID 立即回收，也没有重置 Deep 的绝对窗口。
原 admitted_at / deadline_at 完全相同，最终预算 elapsed 142.243 秒、180 秒硬截止、
120 秒软截止、12 reads / 40 candidates 冻结；等待时间消耗了原研究窗口。
这次恢复在原截止内完成，但不证明更晚中断也有相同剩余研究能力；
120 秒占用窗口是明确的可用性限制，后续单独评估，当前不调整或绕过。

最初外部审计驱动误读不存在的 publication_approved，导致发布权限检查为 false；
核对原生产 schema 后改查 publication_authority 与 approval_status，21 项全部通过。
该错误只影响观测脚本，无生产缺陷/权限变化，无再次发起真实任务。
全部本窗口服务关闭，端口 5323 已释放；原 main / A 线 / 另一窗口 UI 未改。

## RP-1 判定与唯一下一刀

本例研究候选 assembled，但审计 critical_question_unanswered / fail，
audited-but-not-approved，publication_authority=false；自然运行与恢复不代表结论合格。
本例合格 TTUV 仍 NOT_OBSERVED（API reply 不等于可见时间）；
此前严格 S1 5.166 秒单次观测保留，不扩展为 Deep TTUV 或 p95。

本次闭合的是进程重启恢复，不是 R6 总门。S5/N3 官方候选传递缺口、字段级覆盖不足及
Deep-4B 无 qualified semantic judge 仍在；预算扩容、流萤/围棋/UI 均不插入当前 RP 切片。
生产不变，延用已有 131 L1 / 373 L2 / mypy NEW0；本轮原 validator + 21 检查、Ruff、
diff-check、docs-only scope / cleanliness PASS，不重跑全套或八样本，不 push / PR / CI。
最终 head / clean 由 Git 与证据目录 closeout-state.json 恢复。

**唯一下一 slice：可信 official_resolve 未读候选的 Standard 交接窄合同与修复。**
明确区分 resolver 候选与已读证据，仅传递已有公共、项目/版本受约束的地址，
保留 private / fabricated / wrong-project / adjacent-version 等负控；不扩大读取/查询额度，
不赋予证据或发布权。修复后再原样验证 S5/N3 是否取得日期，未取得仍保持不足。
字段语义单元与 qualified judge 另保留为未关闭门，不混入候选交接修复。
