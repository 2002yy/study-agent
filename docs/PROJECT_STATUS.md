# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-09-05
> 产品定义：**Study Agent 是长期保持“正在学什么、已经确认什么、还不会什么、下一步是什么”的个人学习工作台。**

本文件只维护当前事实、可复核证据、缺口和执行顺序。不得新增并列长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT 文档。

## 0. Current Handoff

> 新窗口 / 新 Agent 冷启动时先读本节，再按链接读取本轮所需合同；历史章节保留证据与决策时间语义，不拥有比本节更新的“当前下一步”。

- **Delivery lineage：**B5（PR #132）→ `main@5d620fe0`；B5-Hardening（PR #133）→ `main@fe308718`；P1-C 子批 1（PR #134）→ `main@c2cc60e`；P1-C 子批 2（PR #135）→ `main@533b60c`；P1-C 子批 3 + steering（PR #136）→ `main@da0c6ea`；failure-state Batch A（PR #137）→ `main@2c1e15c`；failure-state Batch B（PR #139）→ `main@53ac140`；v1 recovery hotfix（PR #140，head `5ab9c9b`）→ `main@1051f0a`；failure-state Batch C consumer contracts（PR #141，head `10b6316`）→ `main@10b6316`；answer/claim binding production batch（PR #143，final head `ab4924b1a66e15ad3a9bcdefd47af227e15f3bda`）→ `main@f3f17824c132e2a88caf4dac4a9d6eae78e35910`。
- **Remote CI / PR #142 infrastructure code gate：**RQ1-C bounded qualification infrastructure 的 code-audited exact head 为 `bbe6f0c903c1f2d80598c9833c2f0086a5193993`；exact-head push CI **#2903**（run `33957227532`）与 PR CI **#2904**（run `33957229680`）均 `completed / success`，实际通过 full pytest **1669/1669（168.64s）**、RAG K1、Ruff、package helper、detect-secrets、expanded mypy baseline `122≤128 / resolved=6`、frontend tests/build、browser Golden Journeys 与 real-stack browser gates。相对 `main@f3f17824` 为 `ahead 36 / behind 0`；代码审计 head 的 17 个 changed files 全部位于 `tests/` 或 `tools/`，无 `src/` production 漂移。
- **Current initiative：**Draft PR #142（分支 `codex/rq1c-bounded-qualification`）的 **RQ1-C bounded qualification infrastructure closure**。累计 5 个 P1 review thread 已逐条补最终 exact-head 证据并 **5/5 resolved / 0 unresolved**：direct qualification impl/core bypass、direct protocol stale-SHA bypass、qualification core/impl import→call bypass、protocol core/impl import→call bypass、tracked-dirty checkout exact-head 伪证据。Codex 在 `69dc455d…` 的最后一次自动 review 找到第 5 条 tracked-dirty P1；随后额度耗尽，按仓库既有 precedent 由 exact-head 手工审计替代再次 Codex review。手工覆盖 direct script、core/impl import→call、import order、shared pre-dispatch model-call/deadline guard、physical-vs-audit accounting、runtime/protocol SHA binding、evaluator fail-closed、stale SHA、dirty tracked checkout 与等价旁路，结论 **NO NEW BLOCKER**。
- **Runtime status：**Qualification runner 继续 fail-closed：每个 case 必须有 `answer.status == "available"`、`source == "production_chat"`、completed ChatTurn、非空最终答案、与答案正文精确匹配的 SHA-256 和可审计 answer-stage accounting，否则只能 NO-GO；runner 不自行生成或补造 qualification-side answer。exact identity 现在绑定 **40-char checkout HEAD + matching `GITHUB_SHA`（如存在）+ clean tracked checkout**，`git status` 失败同样 fail-closed；普通 untracked runtime/protocol artifact 不触发 clean guard。qualification/protocol 的 direct script 与 core/impl imported callable 均不能绕过该门。protocol probes 六项仍锁定：`provider_timeout_retry`、`user_cancellation`、`provider_http_429`、`provider_http_503`、`unreadable_page`、`duplicate_republication`。
- **GO / NO-GO：**RQCE-P0、P1-A0、A1–A4/B1–B5 + Hardening + P1-C 子批 1/2/3 + active steering + failure-state Batch A/B/C + PR #143 answer/claim binding = **REMOTE GO / DELIVERED**。PR #142 的 **qualification infrastructure code gate = GO / CLOSED at `bbe6f0c9…`**；但 RQ1-C 本身仍为 **NOT GO / LIVE 12 NOT RUN**（truthfulness 12/12 与 quality ≥10/12 尚未取得），default activation = **FROZEN**；RQCE-P2 = **NOT STARTED**。
- **唯一下一步：**本次只提交 `docs/PROJECT_STATUS.md` 的 handoff 更新；提交后必须先证明 `bbe6f0c9… → handoff head` 只有本文件顶部 handoff/date 的 docs-only delta，再对新的 final head 跑 **push + PR 双 exact-head CI**。只有 final docs head 双绿且 docs delta 手工复核无误后，才可宣布 **RQ1-C qualification infrastructure closure**。**不得因此自动运行 live 12，也不得开启 default activation。**
- **Known limitation：**answer-stage audit 的权威真值仍在成功持久化的 ChatTurn 域；若最终 repository 事务失败，物理模型调用可能已发生而 turn audit 随事务 rollback。未来 live qualification 接 production answer surface 时，final ChatTurn persistence 失败必须直接 NO-GO/error，不得因为缺少 turn audit 而按 0 answer calls 计算。binder v2 的模型语义分类仍是可信边界：server 无法自行判断模型把 factual 句误分类为 instructional/uncertainty；已堵漏的是漏段/重复段/未知段、factual 无正向支持、unknown evidence id 等结构化路径。
- **Delivered foundation：**Pre-RQCE RQ1-A truth stabilization；docs 路线统一；RQCE-P0 A0–C5-C（contracts/state/trace/policy/gates/20-case harness/live semantic audit）；P1-A0 Truth Fix（四层 retrieval truth、50 候选独立人工审计、taxonomy 修正、V2 report aggregate 修正）。
- **P0-C5 当前事实：**已切断 Gold→Shadow 决策输入，Gold 只用于事后评分；freshness 已进入 EvidenceRequirement/Evidence/Gate；primary denominator、Useful Read 与 evidence-linked critical coverage 口径已修正。frozen 10 的新诊断为 false closure 7、gold-blind shadow caught 6、missed 1、overblocked 0；该结果仍是预记录 projection 的组件证据，不是 runtime observer 证据。
- **Live 10 / 50-candidate Truth Fix：**Provider returned=50；production `worth_reading=true`=50；benchmark surface match=10；manual `ANSWER_RELEVANT`=5、`TOPIC_ONLY`=10、`OFF_TARGET`=35。新 taxonomy：`NO_ANSWER_RELEVANT_CANDIDATE=7`、`BENCHMARK_MATCH_FALSE_NEGATIVE=0`、`CLAIM_PROJECTION_UNAVAILABLE=2`、`COMPLETED_WITH_EVIDENCE=1`；旧 `RELEVANCE_FALSE_NEGATIVE=7` 结论已撤销。
- **Dominant observed bottleneck：**pre-read retrieval quality。证据链指向自然语言 query 缺 focused intent、degraded-provider fallback、first-nonempty acceptance，以及 production assessor 对单词重合的 false positive；reader/Evidence Gate 不是本轮主瓶颈。P1 顺序固定为 SearchIntent + CandidatePool → role-aware/semantic rerank → Read Scheduler，而不是先调 relevance 阈值。
- **权威设计合同：**[`RESEARCH_QUALITY_CODEX_TASKBOOK.md`](RESEARCH_QUALITY_CODEX_TASKBOOK.md)。
- **OpenCode 小批施工协议：**[`RESEARCH_QUALITY_OPENCODE_EXECUTION_PLAN.md`](RESEARCH_QUALITY_OPENCODE_EXECUTION_PLAN.md)。
- **状态读取规则：**若本文件历史段落中的旧 HEAD、旧“下一步”或旧 LOCAL/REMOTE 状态与本节冲突，以本节 + Git/GitHub 当前事实为准；实现者应修正文档，不得自行重开已冻结架构选择。

### 0.1 RQCE-P1 B5 frozen execution contract（2026-08-27）

1. **单轮纵向切片：**只接通 `Gap → query batch → CandidatePool → semantic assessment → role-aware rank → cluster-diverse read → strict extraction → Evidence Gate → durable continuation`；不做多轮饱和或独立 synthesis。
2. **失败真值：**active 外部调用开始后禁止静默回退 legacy。失败必须持久化阶段、已有证据和 `partial / unavailable` 语义；零合格证据且不可继续时才为 failed。
3. **cooperative cancellation：**同一 owning operation 的 cancellation check 穿透 provider、模型、阅读、提取与 Gate；每次外部调用前后和每个 checkpoint 检查，不强杀线程。
4. **单一 runtime owner：**`WebLookupRun.research_context["claim_engine_runtime"]` 是唯一 resume/audit cursor；通过现有 repository checkpoint 持久化，不新增第二套运行真值。
5. **外部数据边界：**每次外部模型调用重新通过现有 external-data policy，只发送公开问题/claim、候选 metadata 和有界阅读片段；逐调用审计，未授权 fail closed，不做隐藏 heuristic fallback。
6. **激活所有权：**只认该 run 已持久化且校验通过的 `claim_engine.mode=active`；off/shadow/缺失/损坏保持 legacy，deep 不自动等于 active。
7. **Gate 映射：**pass=`completed/found/evidence_gate_pass`；block=`partial/insufficient/evidence_gap_open`（可恢复）；hard-exhausted partial=`partial/insufficient/evidence_budget_exhausted`；Gate/policy/runtime 不可用时，有合格证据为 partial，零合格证据为 failed。
8. **共享预算：**默认最多 20 candidates、8 次成功阅读、16K 正文、soft 45 秒、hard 60 秒；所有阶段共享持久化计数和 elapsed，不允许 gateway/claim 各自重置。
9. **幂等恢复：**durable exactly-once truth + bounded at-least-once read-only execution。外部调用前写 deterministic step/call ID 与 inflight marker，完成后写结果/审计；completed 跳过；遗留 inflight 永久记 `interrupted_unknown`，仅在显式剩余 retry budget 内用新 attempt ID 重试，evidence ID 去重。
10. **明确 UI：**显示 planning/searching/assessing/reading/gating；pass 显示“证据核验已通过”；block 显示“研究尚未完成：仍缺关键证据，可继续”；partial 显示“已达到本轮预算，当前结论仅基于部分证据”；unavailable 显示“研究不可用，未生成无依据结论”；并显示候选、实际阅读、独立 cluster 和 open critical gap 数。
11. **timeout/取消门：**UI 200 ms 内确认停止请求；provider≤8s、reader≤10s、active model=`min(config,20s,hard remaining)`；慢 provider/model/reader 分阶段记录实测 settle 最大值，要求不超过当前调用 timeout+1s，不承诺不可证明的固定服务端毫秒终止。
12. **B5 验收：**synthetic 全链、policy deny、模型畸形、provider partial、崩溃恢复、各阶段取消；另跑一次真实 SearXNG active smoke，记录 query/provider/candidate/read/cluster/Gate/UI。live 10 不作为本批 CI 硬门。
13. **多 claim 公平：**critical-first round-robin；每个 critical claim 先争取一个独立 cluster，再补 primary/freshness/独立来源/conflict；保留三分之一冲突预算；critical 基础覆盖后才处理 major，context 不主动阅读，未覆盖 claim 保留 open gap。
14. **读取不等于证据：**read success 只产生读取事实；strict extractor 输出并经 server 校验 relation/strength/locator/source role/cluster/published_at 后才可 `extraction_status=eligible`。extract 失败持久化 `read_success + extraction_unavailable`，candidate/snippet 不得升级为证据；cursor 不存完整网页。
15. **Evidence Brief：**下游只接收 eligible evidence 的有界摘录、claim supports/contradicts、cluster/primary/freshness、unresolved conflicts、open gaps、Gate 与预算终止原因；排除未读/rejected/extraction-unavailable。partial/block 必须要求条件化措辞，不输出无保留强结论。
16. **Coverage：**上述范围已覆盖；B5 开始施工。明确 deferred：多轮饱和、独立 synthesis 模型、live 10 blocking CI。

**B5 Exit Gate：**聚焦测试和全量现有门禁通过；exact active synthetic journey 证明 server-owned IDs、逐调用审计、checkpoint/recovery、strict evidence eligibility、Gate 终态和 Evidence Brief；慢调用记录实测上限；真实 SearXNG smoke 有证据；off/shadow/legacy 回归零行为变化；UI 三 viewport 明确显示阶段与非完整结论。未满足任一项均为 **NO-GO**。

### 0.2 RQCE-P1 B5 implementation status（2026-08-27，已合并 PR #132 / main@5d620fe0，CI GREEN）

- **B5 施工状态：IMPLEMENTATION COMPLETE（本地全绿）/ 未提交。** active executor 全链（claim plan → gap query batch → CandidatePool → semantic assessment → role-aware rank → cluster-diverse read → strict extraction → Evidence Gate → durable continuation）已落地并通过全部本地门禁；仍遵守冻结边界：无多轮饱和、无独立 synthesis、live 10 不作为 CI 硬门。
- **真实 SearXNG active smoke（合同 item 12）：PASS（negative-path）。** 工具 `tools/run_research_active_smoke.py`；产物 `docs/research_quality/B5_ACTIVE_SEARXNG_SMOKE.json`。实测：1 次 claim planning（真实 DeepSeek）→ 2 条 gap-directed query（真实 SearXNG fixed digest @127.0.0.1:8080，provider audit 完整）→ 8 个候选 → hard budget 于 64.8s > 60s 耗尽 → assessment/read 未开始 → 终态 `partial / insufficient / evidence_budget_exhausted`（合同 item 7 映射正确）、UI progress 全字段（active_phase=assessing、candidate_count=8、open_critical_gap_count=1）。**判定：真实 hard-budget negative-path PASS；0 reads/0 cluster 是"阶段未执行"的自然结果，不登记为 clustering 缺陷；60s hard 在真实多-provider 搜索下的余量不足记为 bounded 性能风险观察，本批不改冻结预算。** `conditional_wording_required=null` 的 terminal-partial 语义单独列为后续检查项。
- **Claim Planner completion-budget 修复（900 → 4000）。** 根因实验锁定：`deepseek-v4-flash` JSON-mode 下合法 claim plan 需要 `output_tokens=1056`；`max_tokens=900` 时 `finish_reason=length`、JSON 截断不可解析（900 恰为 output_tokens 上限，A/B 对照：同一 prompt/parse/provider 仅改 4000 即 `finish_reason=stop` + parse 成功）。`RuntimeClaimPlanner.max_tokens=900 → 4000`，新增回归 `test_claim_planner_requests_full_completion_budget`；截断/非 object 仍 fail-closed（planner 既有 attempt_failed → unavailable 路径覆盖）。
- **B5 类型债务清零。** 修复两处真实类型污染：1）runtime cursor 初始化显式非 Optional owner（`RuntimeCursorLoadResult.available` 的跨属性收窄限制）；2）`planned`（ClaimBootstrapResult）遮蔽同名循环变量 → 重命名 `bootstrap`。`active_research_runtime.py` 现 0 mypy diagnostics；全仓 current=122 ≤ baseline=128（与 B5 前一致，B5 零新增债务）。
- **本地门禁（本批全绿）。** 后端全量 pytest 1370/1370（含 B5 聚焦 33：synthetic 全链、policy deny、畸形抽取+resume、四阶段取消、三慢调用 settle 实测 model 0.164s/provider 0.187s/reader 0.166s ≤ timeout+1s）；Ruff 全仓通过；expanded mypy baseline 122/128；前端 Vitest 349/349 + production build 通过；C1–C100 守恒 100；`git diff --check` 通过。detect-secrets/package helper/browser gates 由远程 CI 终审。

### 0.3 RQCE-P1 B5 post-merge review debt（2026-08-28 Codex Review 审计 + B5-Hardening 执行结果）

**正式状态：** RQCE-P1 B5 = MERGED（PR #132）+ CI GREEN + single-wave runtime delivered（main@5d620fe0）。不推翻 B5。**命名澄清：本节 P1/P2 为缺陷优先级（Codex Review 分级），与项目阶段 RQCE-P1/RQCE-P2 无关。** 本批 **RQCE-P1 B5-Hardening**（H1–H4 + H5）已全部执行完成（见文末执行记录），修完再进入 P1 后续；**不直接开始多轮 Saturation**，避免把恢复/预算/多 Claim 缺陷带进多轮研究放大。四条 debt 均已对照 main@5d620fe0 实际代码核实，非空穴来风。

**Hardening 执行结果（2026-08-28，本地全绿）：**
- **H1 ✅ checkpoint 边界调整。** `on_model_finished` 只更新内存 cursor（completed audit 不单独落盘）；caller 的 semantic-result checkpoint（planning 成功后新增显式 `checkpoint()`；assessment/extraction 原有成功路径 checkpoint）与 audit 同一 checkpoint 持久化。取消路径 `finish_cancel` 前补 checkpoint（终态审计完整且 inflight 已清）。新增回归 `test_model_crash_after_success_before_semantic_persist_recovers_via_new_attempt`：模型成功 + audit 回调完成 → 模拟 crash（wrapper fail 短路兜底，durable 停在最后 checkpoint）→ durable cursor 仍 inflight 且无 completed audit → resume → `interrupted_unknown` → 新 attempt 成功 → planning 恰 1 个 completed audit、call_id 无重复。
- **H2 ✅ candidate 满额停止外部搜索。** 搜索循环在外部调用前增加 `len(cursor.candidates) >= max_candidates → break`。新增回归 `test_full_candidate_pool_stops_pending_external_searches`（flood 20 候选/首条 query → 第 2 条 planned query 跳过：`search.calls == 1`、`completed_query_ids == 1`、candidates == 20；flood 单 cluster 数据 gate 合法 partial，不作为主要断言）。
- **H3 ✅ 拆 physical read / claim-evidence binding。** `_fair_read_plan` 返回 `(physical_reads, extraction_targets)`：① 跨 Claim 的 global candidate exclusion 删除，改为 **(candidate_id, claim_id) pair 去重**（同 claim 内不重复绑定，跨 claim 允许）；② **read budget 只限制新 physical candidate**——已计划候选对其他 claim 的 extraction-only 绑定不受 budget 门控（调度：每 claim/wave 先按排名+cluster-diverse 绑 reusable（零 read 成本），剩余 slots 给 `plan_read_wave` 调度 new candidates）；③ `source_record["extractions"]`（per-claim 复数）承载多 claim 提取，单数 `extraction` 保留为首个 eligible 摘要（UI/items/brief 回退兼容）；④ read plan 持久化 v2 dict（`physical_reads` + `extraction_targets`），`_load_read_plan` 兼容 v1 list（in-flight run 可 resume）；⑤ `_evidence_brief` record 查找优先 `extractions[claim_id]`。新增回归 `test_one_physical_read_serves_multiple_claims`：A/B 双 claim query 各发现 shared+a-only / shared+b-only → **provenance merge**（shared 候选 query_ids 含两 claim 的 query id）→ shared 恰 1 次 physical read → `(shared,A)`/`(shared,B)` 各绑定一次 → 同一 server-owned evidence_id 链到两个 claim。
- **H4 ✅ smoke 读真实 provenance 字段。** `attempt.get("providers")` → `attempt.get("providers_attempted")`；新增 `searxng_attempted` 断言并纳入 exit 条件（SearXNG 未被调用时 smoke 必须失败）；smoke schema 升 **v2**；artifact 重新生成（真实 SearXNG fixed digest @127.0.0.1:8080）。
- **H5 ✅ conditional_wording_required 成为 production contract field。** 根因确认：字段从未被 `_evidence_brief()` 生成，smoke `brief.get()` 得 null 只是 key 缺失。修复：brief 增加 `"conditional_wording_required": (gate is None or gate.status != "pass")`；`_format_evidence_brief()` 真正消费（conditional 时追加"结论约束：研究尚未通过完整证据核验；只能使用条件化措辞，不得输出无保留强结论。"）——不是 dead metadata。断言：gate pass → False；malformed/block 路径 → True 且 `source_block` 含该约束文本。smoke v2 一致性断言（`conditional_ok == (gate != "pass")`）纳入 exit 条件。
- **真实 SearXNG smoke v2（重新生成）：PASS。** `docs/research_quality/B5_ACTIVE_SEARXNG_SMOKE.json`（schema v2）：2 条 gap-directed query、`providers_attempted = ['searxng','bing_rss','duckduckgo_html']`（逐 query 真实记录）、`searxng_attempted = true`、5 candidates、hard budget 75.0s > 60s 耗尽 → `partial / insufficient / evidence_budget_exhausted`、`conditional_wording_required = true`（与 partial gate 一致）。negative-path PASS 形态与 B5 一致（frozen 60s 预算不改）。
- **门禁（本批全绿）。** 全量后端 pytest **1373/1373**（+3 hardening 回归）；B5 聚焦 + dispatch **36/36**；Ruff 全仓通过；expanded mypy baseline **122/128**（hardening 零新增债务）；`git diff --check` 通过。前端无本批改动（B5 已验 Vitest 349/349 + build）。

**Codex Review round 2（2026-08-28，同一 PR #133 分支补修）：**
- **H6 ✅ searxng_success 证明成功而非仅尝试。** `providers_attempted` 列出全部 enabled provider（无论成败，`provider_search.py` 中 `providers_attempted=enabled`）——attempted ≠ success。smoke 新增 `_searxng_success()`：从持久化 `provider_audit.provider_outcomes` 断言 `provider=="searxng" AND status=="ok" AND result_count>0`，并纳入 exit 条件（searxng 失败 + Bing 给结果 + partial 不再能通过 smoke）。回归覆盖三种形态：ok+有结果 / failed+attempted / ok+零结果。真实 smoke v2 复跑 `searxng_success=true`。
- **H7 ✅ 共享 evidence 的 per-claim anchor 保留。** 根因：`_add_extracted_evidence` 每次以当前 extraction 重建同 evidence_id 的 `ResearchEvidence`（source-level identity），多 claim 时 locator/anchored_spans 被最后写入者覆盖 → brief 行混配（Claim A locator + Claim B spans）。修复：`_evidence_brief()` 构造 claim row 时 locator/anchored_spans/caveats 优先取 `record["extractions"][link.claim_id]`（claim-specific anchor 层），`ResearchEvidence` 保持 source-level identity 不动。回归：multiclaim 测试改用 **claim_text 确定性且真实存在于 excerpt** 的双 anchor（"release date" / "2026-08-01"，适配 `_parse_extraction` 的 anti-hallucination 严格校验——stub 输出必须由输入决定且锚点在正文中），断言两条 brief 行各自保留自己的 locator/spans 且互不相同。
- **H8 ✅ cluster diversity 跨 reusable+fresh。** 根因：reusable 先占 cluster 后，`plan_read_wave(fresh)` 只保证 fresh 内部 cluster-diverse，fresh 接受循环无已占 cluster 检查 → 同 claim 浪费 slot 读取同 cluster 候选。修复：per-claim 跨波累计 `claim_clusters`（`_bind` 时登记），reusable 与 fresh 接受循环均检查已占 cluster，fresh 被跳过**不消耗 slot**（继续扫描后续候选）。回归：直接单测 `_fair_read_plan`（claim_B rankings = [P(X) 已绑, Q(X) fresh, R(Y) fresh]，wave2 必须跳 Q 取 R，physical 不含 Q）。
- **Round 2 门禁（全绿）。** 全量后端 pytest **1375/1375**（+2：H8/H6 回归）；focused **38/38**；Ruff 通过；mypy **122/128**；`git diff --check` 通过；真实 SearXNG smoke v2 复跑 exit 0（7 candidates、`searxng_attempted=true`、`searxng_success=true`、conditional 一致）。

**Codex Review round 3（2026-08-28，同分支补修）：**
- **H9 ✅ reusable 遵循与 fresh 相同的调度资格谓词。** 根因：H3/H8 后 reusable 候选只检查 `eligibility == "rejected"`，而 fresh 走 `plan_read_wave()` 还有 `lead_only` 无 provenance 级 gain signal 不可调度的更严规则（`scheduler.py`）→ 已物理读过的 lead_only 无信号候选会被错误绑定到新 claim（占 wave slot + 触发多余 extraction 调用）。修复：抽共享谓词 `is_schedulable_candidate()`（rejected 不可调度；lead_only 需 new_primary/new_provenance_lead/new_contradiction 之一），`plan_read_wave()` 与 `_fair_read_plan()` reusable 路径统一使用，两条路径不再漂移。回归：claim_B rankings = [X(lead_only 无信号, 已物理读), Y(eligible fresh), Z(lead_only 有 new_primary)] → X 不被绑定、Y 正常占位、Z 仍可调度（证明不是整波被清空）。
- **Round 3 门禁（全绿）。** 全量后端 pytest **1376/1376**（+1 H9 回归）；focused **39/39**；Ruff 通过；mypy **122/128**；`git diff --check` 通过。

**B5-Hardening 正式收口（2026-08-28）：** H1–H9 全部修复（PR #133，merge commit `fe30871`，round 3 head `c4745dc`）。四轮 Codex exact-head review 收敛轨迹：round 1 → H6/H7/H8（3×P2）；round 2 → H9（1×P2）；round 3+4 → 零 findings（exact-head review clean）。本地门禁 pytest 1376/1376、Ruff、mypy 122≤128、smoke v2 `searxng_success=true`；PR CI 与 **main exact-head CI（`fe30871`）均 completed success**。**正式判定：B5 + B5-Hardening = REMOTE GO / DELIVERED。** 下一批冻结目标（路线已定）：**P1-C 子批 1 = Evidence Gain + Saturation contracts**（确定性 gain evaluator，per-gap/per-claim saturation 计数，不做 runtime loop），随后子批 2 = multi-wave durable runtime loop、子批 3 = Stop Gate + bounded validation，之后才是 bounded 12-case qualification 与 P2。

### 0.4 RQCE-P1-C 子批 1：Evidence Gain + Saturation contracts（2026-08-29，DELIVERED）

**交付：** PR #134（head `a246219`，merge commit `c2cc60e`）——`src/web/research/evidence_gain.py` 纯合同批（不动 executor、不做 runtime loop）：`EvidenceGainResult`（含 `gain_reasons_by_claim` 审计归因）/ `SaturationState` / `GapBatchDelta` / `evaluate_evidence_gain(before, after, *, target_gap_ids, gain_provenance_by_gap)` / `update_saturation` / `saturated_claim_ids` / `saturated_gap_ids`。
- **冻结语义：** 6 类 gain（new_eligible_evidence 0→1、new_independent_cluster、better_source_role、new_contradiction、new_provenance_lead、claim_status_improvement 显式 edge 集）；同 cluster 重复/纯 result_count/新 URL 单独不算 gain；eligibility 一律复用 Gate 公共谓词（`evidence_gate.py` 抽出 `evidence_link_structurally_eligible` / `evidence_link_meets_freshness` / `evidence_link_eligibility`）；saturation 为 per-Gap/per-Claim 计数（非全局），连续 2 批无 gain → SATURATED，critical/conflict 第三批资格由调用方传入；`claim_status_improvement` 无 evidence identity、不经 delta 广播；weak-but-eligible（strength<0.7）算 gain 已作为合同冻结进测试。
- **Gap attribution（R3/R6/R9）：** `target_gap_ids` 显式 + per-claim reason 归因 + 多 target 时强制 `GapBatchDelta` provenance 与 per-claim per-cause evidence identity 求交；无 provenance 且多 target → fail-closed 不 credit；desired_source_role gap 按 role absent→present 实际判定；provenance key/target fail-closed 校验。
- **Review 轨迹（人工替代 Codex）：** round 1 R1-R3+P2 → round 2 R4+R5 → round 3 R6+R7 → round 4 R8-R10 → round 5 R11 → round 6 零 findings。R1–R11 全部 CLOSED：R1 pending→searching 非 gain；R2 Gate/Gain 共享 eligibility；R3/R6/R9 gap attribution 不广播、provenance per-claim per-cause、旧证据/重复证据/cross-claim 不可 credit；R4 reasons 不跨 claim 串味；R5 role gap 按实际 role 覆盖；R7/R10/R11 序列化 fail-closed（含 wrong-type 空字段、no-gain 不得携带 affected ids、by-claim 一致性）。
- **门禁：** evidence_gain 35/35；全量 pytest 1411/1411；Ruff；mypy 122≤128（零新增债务）；diff-check；PR CI（`a246219`）与 **main exact-head CI（`c2cc60e`，run #33245466010）均 completed success**。**P1-C 子批 1 = REMOTE GO / DELIVERED。下一批 = 子批 2 multi-wave durable runtime loop。**

| Debt | 判定 | 影响 | 执行时机 |
| --- | --- | --- | --- |
| H1 P1 model semantic-result crash consistency | 成立，严重 | 崩溃恢复可能从"可恢复"变成 runtime failure | 下一批第 1 个修 |
| H2 P1 candidate cap does not stop external searches | 成立 | 白烧 60s budget，可能没时间 assessment/read | 第 2 个修 |
| H3 P2 physical-read dedupe suppresses cross-claim binding | 成立 | 多 Claim 场景可能错误留下 open gap | P1 hardening 后修（多 Claim/saturation 前 mandatory） |
| H4 P2 SearXNG smoke reads wrong provenance field | 成立，验收缺陷 | smoke 并没有真正证明使用了 SearXNG | 很小，与 H1/H2 同批 + 重新生成 smoke artifact |

**H1 / P1：model semantic-result crash consistency（model result/audit 非 crash-consistent）。**
- 根因：`on_model_finished(audit)` 内 `finish_model_attempt` → `checkpoint()` 已把"模型调用完成"持久化；但 semantic result（claim plan / assessment / extraction，如 `state = bootstrap.state`）要等 `claim_planner.plan()` 整体返回后才写进运行状态。
- 崩溃窗口：模型成功 → audit 已 checkpoint →【进程崩溃】→ semantic result 尚未持久化。恢复后 durable cursor 认为 attempt:1 = completed，业务状态认为 claim plan 不存在 → 重调同一逻辑调用 → cursor 禁止"已 completed 的 call_id 再次成为 inflight"，`_validate_cursor_links()` 报 `completed model call cannot remain inflight` → 本应 `interrupted_unknown → retry/resume` 的窗口升级为 terminal runtime failure。
- 与 B5 冻结的 "durable exactly-once truth + bounded at-least-once read-only execution" 直接冲突。
- 修法（不做复杂事务，调整 checkpoint 边界）：`on_model_started` → 持久化 inflight marker（保持现状）；模型结束 → `on_model_finished` 只更新内存 cursor，**暂不 checkpoint**；caller 接收到 semantic result → semantic result + audit 在**同一个 checkpoint** 持久化。效果：死在模型返回后 → durable truth 仍只有 inflight → 恢复自然走 `interrupted_unknown → 新 attempt ID → bounded retry`，完全符合原设计。
- 新增针对性回归：model remote success → audit callback 完成 → 模拟 crash before semantic persist → reload → interrupted_unknown → 新 attempt → 成功恢复。

**H2 / P1：candidate budget must bound external search work。**
- 现状：搜索循环只检查 `elapsed() >= hard_timeout_seconds: break`；CandidatePool 全局上限 `max_candidates=20`；满额后新搜索候选仍被 `_merge_runtime_candidates(..., max_candidates=20)` 截断，但外部搜索已真实发生（白烧预算）→ 可能把 hard deadline 花在注定不进 CandidatePool 的搜索上，assessment/read 没剩时间。
- 修复（很小，放在外部调用之前）：`for planned in cursor.planned_queries: if len(cursor.candidates) >= state.budget.max_candidates: break`。
- **重要修正（不得篡改历史结论）：这不是 B5 64.8s/0 reads smoke 的根因**——那次 candidates=8 < 20（未满额），64.8s 是 DeepSeek planning + 两批真实搜索本身吃满 60s。H2 是另一个未来可能造成类似症状的问题。

**H3 / P2：deduplicate reads, not claim-evidence bindings。**
- 现状：`_fair_read_plan()` 全局 `selected_ids: set[str]`，每个 Claim 排名时过滤已选 candidate → 一个来源只能服务一个 Claim。现实里一个 primary source 很可能同时证明多个 Claim（例：FastAPI 官方 LICENSE 页面 → Claim A "FastAPI 使用 MIT License" + Claim B "MIT license text 存在于官方 repository"）。
- 后果：物理页面已读，但第二个 Claim 永远不会从该正文提取 Evidence → Claim B 仍 unresolved → 继续搜或 Gate block。深层原因：read-plan entry 绑定 `(candidate_id, claim_id, cluster_id, source_role)`，extractor 只按 `item["claim_id"]` 取单个 claim —— 一次 entry = 只对一个 claim extraction。
- 正确设计（不是临时删 `selected_ids`）：拆两个概念——Physical Read `(candidate_id)` 只读一次；Extraction / Claim Binding `(candidate_id, claim_id)` 可多个（source-X ├─ extract for Claim A ├─ Claim B └─ Claim C）。
- 改动比 H2 大：`RuntimeReadOutcome` 以 candidate_id 唯一，`source_record["extraction"]` 目前是单个 extraction 不是多 Claim collection → 需正规拆 `physical_read_plan` + `claim_extraction_targets`。

**H4 / P2：real-SearXNG smoke must assert persisted provider provenance。**
- 根因：生产代码真实保存 `"providers_attempted": list(outcome.providers_attempted)`；smoke 工具读取 `attempt.get("providers")` → 产物变成 `"providers": []`、`"provider_audits": [{"providers": null}]`（main 中已提交的 smoke artifact 即如此）。
- **表述修正：runtime execution 大概率正确（真实用了 SearXNG），但 smoke evidence extraction 错误，当前 artifact 没有证明该事实。** 两者分开记录：runtime execution 可能正确 / smoke evidence extraction 错误。
- 修复：① smoke 读 `attempt.get("providers_attempted")`；② smoke 成功条件不能只是"partial 合法 terminal state"，必须明确要求 `expected provider == "searxng"` 存在于 providers_attempted（否则 SearXNG 根本没被调用 + 其他 provider 返回 candidates + partial 也能错误通过 smoke）；③ 重新生成 smoke artifact。

**H5（独立项，不与 H1–H4 混为一谈）：** `conditional_wording_required=null` 语义确认——当前 artifact 仍为 null，独立检查项照旧。


### 0.5 RQCE-P1-C 子批 2/3 与 P0–P2 剩余路线（2026-08-31）

- **子批 2 已交付。** PR #135 经多轮 review 修复 multi-wave query identity、gain exactly-once、跨波/跨 claim cluster 覆盖、conflict reserve、major backfill、assessment/extraction attempt exhaustion、deferred context saturation 与 hard-budget precedence；最终 head `acbd330`，merge `533b60c`，exact-main CI #33327174616 success。
- **子批 3 当前改动。** 新增 `src/application/research_stop_gate.py` 与 characterization table；`active_research_runtime.py` 的正常 settlement、hard-budget、planning/policy unavailable、generic runtime unavailable 均从 gate 取得 canonical reason/mapping。新增 durable-state 重建验收，证明持久化 state + cursor 重算得到的 reason 与 run 上的 `evidence_saturated` 一致。
- **子批 3 明确边界。** 本批是 stop truth centralization，不宣称已经完成 active steering、全部结构化 `ResearchFailureReason`、bounded 12-case qualification 或 production activation；现有 legacy deep steering 不自动等于 Claim Engine active steering。
- **PR #136 round-2 小增量（LOCAL PASS）：**late steering 不再依赖当前调用栈的临时 `late_ids` 返回值，而由 `ResearchStopSignal.unapplied_steering_blocks_completion` 从 merged durable context 重算；因此 checkpoint 后 process death/resume 仍会抑制旧 graph 的 gate pass，并保留 canonical hard-budget/wave-limit terminal reason。focused 138/138、单次全仓 1475/1475、Ruff、mypy `122≤128 / NEW=0`、diff-check 均通过；远程状态必须以该增量 push 后的 exact-head CI 为准。

**Active structured steering Grill 1A–5A（2026-08-31，FROZEN）：**

1. **停止优先级：**owner-scoped cancel 与既有 hard/wave bounded ceiling 优先；只要仍有可执行预算，`pending` steering 必须阻止旧状态直接完成，并在下一波生效。已无可执行预算时标记 `late`/未应用，保持 partial/unavailable 真值，不隐式延长运行。
2. **结构化映射：**自由文本由服务端映射为 `created_by=user` 的 critical claim 与专属 open critical evidence gap；不删除、不静默改写既有 claim graph，也不让模型重写全图。
3. **单一真值：**只在同一 `WebLookupRun.research_context` 增加 append-only `claim_engine_steering`；每条由服务端分配 ID，持久化 `pending/applied/late`、`applied_wave` 及结构化 claim/gap 绑定。checkpoint 必须按 ID 合并并发到达的 steering，禁止新增第二张表或复用 legacy `deep.steering` 作为 active 真值。
4. **预算：**steering 只消耗当前剩余 candidates/reads/time/waves；不根据文本推断扩容。显式扩预算留给未来独立、授权 API，本批不做。
5. **验收顺序：**先完成 steering、failure mapping 与确定性 gate，再一次性运行 frozen + small-live 12-case qualification；不提前反复消耗 live CI/联网预算，也不以缺少 steering 的 qualification 代替闭环。
6. **apply 原子性/幂等性（FROZEN，6A）：**state mutation 与 `status=applied` 必须在**同一个 CAS checkpoint** 中持久化；claim/gap identity 从 steering ID 确定性派生（`claim_steering_<sha256(entry_id)[:24]>` / `gap_steering_<...>`）。CAS 冲突的 retry 对象是"语义操作"而非旧 JSON blob：reload 最新 WebLookupRun → 按 steering ID merge（executor 本地优先、durable-only 保留）→ 重放确定性 mutation → 重新 CAS。合法 crash 状态只有两个：checkpoint 前崩溃（durable 仍 pending，resume 以确定性 ID 幂等重放）与 checkpoint 后崩溃（claim/gap 与 applied 已共存，resume 跳过）；不存在"claim 已 durable 而 steering 仍 pending"或反序。

**本批验收：**同一 steering 在 crash/resume 后只生成一组 claim/gap（apply checkpoint 前/后崩溃各一条回归）；运行中并发注入不被旧 checkpoint 覆盖（checkpoint race 回归：reload/merge/retry 后 mutation 与 steering 都不丢）；已完成一波但尚有预算时 steering 强制进入下一波（pending vs gate pass 回归：StopGate 必须 continue）；hard/cancel/wave ceiling 下保留 `late` 未应用状态且 terminal 保持 canonical `evidence_budget_exhausted`；受 steering 影响的真实 search audit 仅记录 server-owned steering ID 与布尔标记，不复制第二套运行真值。

| 阶段 | 当前事实 | 尚余工作 |
| --- | --- | --- |
| **RQCE-P0** | contracts/state/trace/policy/gates、20-case Shadow/live semantic audit、retrieval taxonomy 已交付 | 无新施工批；继续作为 P1/P2 回归与诊断资产，不能替代 release benchmark |
| **RQCE-P1** | Gap/CandidatePool、semantic rank/cluster、Scheduler/Extractor、active adapter、multi-wave、Stop Gate + active structured steering 均已 REMOTE GO | failure-state 枚举/映射收口；bounded 12-case frozen+small-live qualification；人工 activation GO/NO-GO |
| **RQCE-P2** | 尚未开始完整产品质量层；现有 reader/brief 只是 P1 最小能力 | Progressive Reader（section/PDF/JS/login/403）+ cache/circuit breaker；完整 ResearchBrief+synthesis；Final Answer Auditor（最多一次 repair）；50–60 frozen/live benchmark 与 release report |

### 0.6 RQCE-P1 failure-state 枚举/映射审计（2026-08-31，IN PROGRESS）

**已验证事实：**

1. **两条语义轴尚未类型化。** `ResearchRuntimeCursor.failures[].code` 表示一次过程失败；`WebLookupRun.stop_reason` 表示整个 run 为什么终止。两者当前均为自由字符串，不能合并为同一个字段或互相覆盖。
2. **RuntimeFailure 当前生产者不闭合。** 固定 code 至少包括 `blocked_by_policy`、`candidate_assessment_blocked_by_policy`、`candidate_assessment_unavailable`、`extraction_blocked_by_policy`、`extractor_unavailable`、`hard_budget_reached`、`interrupted_unknown`；模型路径还透传 `model_call_attempts_exhausted`，generic exception 直接持久化 `type(exc).__name__`，因此 cursor schema 不能证明 code 有界。
3. **search/read 失败未进入统一 failure truth。** search 的 `search_exception` 或 provider payload reason 只进入 `RuntimeQueryOutcome.error_code`；read 的原始 reader error 只进入 `RuntimeReadOutcome.error_code`。最终 run 可能以 `evidence_saturated` / `evidence_gap_open` 停止，无法只凭 stop reason 区分 provider、访问或读取失败。
4. **policy 可能双计数。** `model_allowed()` 已追加通用 `blocked_by_policy`，candidate assessment / extraction 调用点随后又追加阶段专用 code；一次拒绝可能形成两条 failure，影响统计与恢复审计。
5. **StopGate 边界仍允许任意 reason。** 正常 stop reasons 已收敛为 `evidence_gate_pass`、`evidence_budget_exhausted`、`evidence_gap_open`、`evidence_saturated`、`wave_limit_exhausted`；但 `unavailable_reason` 仍原样成为 terminal reason，planning/model/generic 路径未经过有界映射。
6. **UI 映射不完整且 unknown 不安全。** `ChatResearchRecovery.stopReasonLabels` 已覆盖 gate pass、gap、budget、active unavailable、planning policy block、cancel；缺 saturation、wave ceiling、model attempts exhausted 等。SSE partial 的 unknown fallback 会直接显示 raw `stop_reason`，而 run detail 的 unknown partial 又只显示通用重试文案，两条入口不一致。
7. **任务书的完整枚举跨越 P1/P2。** `READ_LOGIN_REQUIRED`、`READ_JS_REQUIRED`、`READ_UNSUPPORTED_FORMAT`、`SYNTHESIS_FAILED`、`AUDIT_FAILED` 等需要 P2 Progressive Reader/Synthesis/Auditor 才能可靠观测。本批可预留枚举，但不得把当前不可区分的 reader error 猜成精确原因。

**审计建议：**保留 failure/stop 两轴；P1 先建立 canonical `ResearchFailureReason` + `ResearchStopReason` 及单向映射，generic 异常收口为 `INTERNAL_ERROR`，模型 per-call `error_type` 继续留在审计而不成为 cursor code；legacy v1 cursor 通过显式 migrator 将未知 code 归入 `LEGACY_UNKNOWN`；P2 原因先声明为 reserved/unreachable；UI 只显示稳定中文标签，unknown 显示安全通用文案并保留后台诊断，不直接展示 raw code。

**1A–12A FROZEN（2026-08-31）：**两条 durable 轴（failure=过程中发生了什么 / stop_reason=为何停止）永久分离（1A）；版本化 canonical string catalog 而非 closed Enum 作为持久化真值（2A）；code 恒 canonical、动态内容进 detail/provider_code/exception_type（3A）；outcome 保留局部事实、跨阶段失败投影 canonical RuntimeFailure（4A）；StopGate unavailable_reason 收敛为合法 stop reason（5A）；P1 不伪造 Reader 精度、P2 append-only 增加 READ_* 原因（6A）；正式升 research-runtime-v2、dual reader（v1 原样读 + 标记 legacy，不猜不改写）、新 writer 只写 v2（7A）；failure_id 按语义操作确定性生成、append by ID exactly-once、legacy 不 dedupe（8A）；P1 一级 code 只取稳定语义层级（9A）；outcome error_code 改 bounded local status + provider detail（10A）；API 暴露 canonical truth、UI 走 display mapping + unknown 安全 fallback（11A）；Batch 完成 Gate = 完整 writer→code→stop→consumer 矩阵 + 四类测试 + 静态审计（12A）。

**Failure-State Batch A（REMOTE GO / DELIVERED）：**PR #137 head `6f0ad47` 已合并为 `main@2c1e15c`，exact-main CI #33417206981 success。v2 合同 + dual reader + v2 codec、`src/web/research/failure_contracts.py`（failure-catalog-v1 8 个一级 code + stop-reason-catalog-v1 登记全部 production literal）、`RuntimeFailure` v2 内存结构 + `build_runtime_failure` factory + 确定性 `runtime_failure_id` + `append_runtime_failure` exactly-once 均已交付。

**Failure-State Batch B（MERGED WITH P2 REGRESSION / HOTFIX REQUIRED）：**PR #139 head `1c9e2cf` 的 PR CI #33421092842 success，后合并为 `main@53ac140`；merge-main CI #33421135104 failure（pytest/Ruff/mypy/frontend/browser 均通过，real-stack enforce 失败），不得标记 REMOTE GO。合并后 review 指出：v1 cursor recovery 被写成 canonical stage code + `detail/attempt_id`，但 v1 wire 只保留 `code/phase/item_id`；recovery checkpoint 后再崩溃会丢 `interrupted_unknown` 计数 marker，使 retry 退回 attempt 1。结论：主体方向保留，不回滚；合并时机错误，Batch C 冻结。

**Failure-State Batch B v1 recovery hotfix（LOCAL CANDIDATE）：**分支 `codex/rqce-p1-failure-state-v1-recovery-hotfix`，base `main@53ac140`。v1 model/search/read recovery 显式保留三字段 `interrupted_unknown`；v2 继续 stage-specific canonical code + `detail/attempt_id`。external second interruption 达到 ceiling 后投影 canonical `search_failed/read_failed + external_attempts_exhausted`，不再重复 attempt 2。crash/recovery focused 50/50、active runtime owner 44/44、Ruff 全仓通过、mypy `122≤128 / resolved=6`、diff-check 通过。本地 full pytest 1515/1516；唯一失败 `test_news_query_change_invalidates_downstream_stages` 已最小复现为既有非隔离测试（patch 旧 `src.api.run_search_stage`，实际 route 使用 `NewsService.dependencies.search` 并在本机走真实 gateway 502），不在 hotfix diff；#139 干净 PR CI 的同一 pytest 已通过。最终判断以 hotfix exact-head 干净 CI 为准。

**部署边界：**默认桌面产品坚持 Zero-Docker；SearXNG 是 optional provider，不是普通用户启动依赖。P2 引入 PDF、rendered browser 或其他重依赖前，必须先说明其桌面打包/降级方式；D1/D2（Zero-Docker runtime + packaged backend）应在 P1 收口后、P2 大规模 Reader/Synthesis 前完成。


## 1. 当前结论

- **P1：完成。**
- **P2-A：完成。**
- **P2-B：完成。**
- **P2-C：完成。**
- **P2-D-1：完成。** commit-pinned source symbol + exact-SHA CI association 已进入 main。
- **P2-D-2A：完成。** normalized durable learning truth schema + repository 已进入 main。
- **P2-D-2B：完成。** deterministic SourceEvidence convergence 已进入 main。
- **P2-D-2C：完成。** atomic Claim / Hypothesis commit boundary 已进入 main。
- **D-2 mini Golden Journey：完成。** PR #122 已合并进入 main。
- **P2-D-3A：完成。** Semantic Closure + durable Goal navigation 已进入 main。
- **P2-D-3B：完成。** bounded durable ResumeContext + read-only resume API 已进入 main。
- **P2-D GrillMe 决策 1–49：已冻结。**
- **P2-D-3C：完成。** durable learning truth surface（closure truth bridge、ResumeContext UI、LearningPanel/Strip/EvidenceTrail、goal-isolated confirmation）已进入 main。
- **P2-D-4C：完成。** backend 全链路 golden journey（真实源码 + 双 commit）已进入 main（35336cc）；前端学习侧栏缺陷修复（缺行/补给、摘要刷新、stale 角度刷新、server-only 断言）+ revalidation e2e journey 已进入 main（8fc1746）。
- **P2-D-4D：完成（自动验收部分）；实体手机验收延期。** firefox/webkit sample + 5 项目 51/51 通过；因 Android 导出/部署配置尚未就绪，用户于 2026-08-11 明确将实体手机验收延期，记录表仍为空且不得标记完成。
- **P2-E：自动化批次完成；实体手机人工验收延期。** 范围（2026-08-11 经现状调研确认，跳过 G 系列产品能力评审）：E-5 仓库清理 → E-1 自动化验收与文档收口 → E-2 backend 辅助模块直测补缺 → E-3 前端 surface 测试补缺；Android 导出/部署配置就绪后再恢复人工验收。

历史基础验证基线：`dd93fdabaa6f5f2637ef4f03604f43f91a1725c4`（[CI #32761262084 attempt 2](https://github.com/2002yy/study-agent/actions/runs/32761262084) 全门禁通过）。当前 RQCE checkpoint 与远程门禁以顶部 **Current Handoff** 为准。

## 2. P2-D 已进入 main 的基础

### 2.1 P2-D-1 — commit-pinned source evidence

PR #115 squash merge：`9581b4acea6132e9e0ee8902a1cac9a61bbd6939`。

已具备：

- wide search chunk → deterministic lexical match line；
- match line → innermost parsed symbol；
- 无 symbol 时 path+line fallback；
- SourceEvidence identity 固定到 repository / commit / tree / file / symbol / lines；
- CI payload 必须 exact-SHA association；
- CI failure/unavailable 不使 SourceEvidence 失效；
- custom snapshotter 不隐式触发 live CI；
- 不创建第二套 parser / CI provider。

### 2.2 P2-D-2A — durable learning truth

PR #119 squash merge：`1c2c3456b9f403a17d86712e98741ea8f2bcfb34`。

Global SQLite schema 已升级到 v17，正式落地：

- LearningTopic；
- LearningGoal + prerequisite relation；
- LearningClaim；
- immutable ClaimRevision；
- immutable SourceEvidence；
- ClaimRevision ↔ Evidence role relation；
- UnderstandingEvidence ↔ ClaimRevision result relation；
- lightweight LearningHypothesis；
- lightweight NextStep。

`LearningTruthRepository` 是单一 transaction owner。已验证 fresh DB、v16→v17、migration rollback/recovery、FK/unique/check、restart readback、revision/source immutability、prerequisite cycle guard、legacy learning state 零自动迁移。

### 2.3 P2-D-2B — SourceEvidence convergence

PR #120 squash merge：`458de772fd589c9e56947d21f59e208baa826e75`。

已具备：

- turn/search candidate → durable SourceEvidence identity whitelist；
- query/rank/score/confidence/provider/CI/selection diagnostics 不进入 durable truth；
- deterministic Primary priority；
- exact identity dedupe；
- 同一 EvidenceSet 保持 same repository + commit + tree；
- exactly 1 Primary + 0–4 Supporting；
- supporting proof-dimension diversity；
- learning graph expansion 显式 `depth=1`；
- normal source learning 显式 `include_ci=False`。

Mini Journey 额外发现并修正一个跨层语义缺口：snapshot provider unavailable 不再被压扁成 `missing_source`，而是保留为 `provider_unavailable`。

### 2.4 P2-D-2C — Claim / Hypothesis commit

PR #121 squash merge：`c66d3cd2d24d63b3464465a7bdc4d4b37128bee4`。

已具备：

- `Claim + rev1 + SourceEvidence links` 单事务提交；
- 中途 SourceEvidence 冲突时 Claim shell / Revision / Evidence 全部 rollback；
- 无 qualified Primary → LearningHypothesis only；
- 有 Primary → source-backed Claim + immutable initial Revision；
- existing lineage reuse 只能显式指定 `existing_claim_id`；
- existing lineage 要求 topic/scope/kind 一致和显式 revision reason；
- 不做 embedding / LLM 自动同义合并；
- D-2 不决定用户 mastery。

## 3. D-2 mini Golden Journey — COMPLETE

PR #122 merge：`a5112c4bec81ce9993edeeb88bf2a8779c826138`。

成功路径使用**当前 checkout 中真实的 Study Agent `src/application/github_source_evidence.py` 源码文本**，只把 provider 元数据固定为 deterministic fake snapshot，避免 CI 依赖公网：

```text
LearningTopic + LearningGoal
→ real Study Agent source text
→ GitHubSnapshotService deterministic line/symbol mapping
→ LearningSourceEvidenceService convergence
→ LearningOutcomeCommitService
→ Claim rev1 + SourceEvidence atomic commit
→ recreate LearningTruthRepository
→ same Topic / Goal / Claim / Revision / exact Evidence restored
```

同时验证：

```text
provider unavailable
→ convergence.provider_unavailable
→ LearningHypothesis only
→ 0 Claim / 0 Revision / 0 SourceEvidence
```

该 Journey 还确认 D-2 不会凭空创建 UnderstandingEvidence；理解确认由 P2-D-3 semantic closure 负责。

## 4. 仍然有效的迁移禁令

- `AnswerClaimV1` **不是** `LearningClaim`；
- `EvidenceRefV1 / EvidenceSnapshotV1` **不是** `SourceEvidence`；
- legacy `learning_state.confirmed_points` **不是** formal confirmed mastery；
- 旧 Markdown memory / session summary 不得批量晋升为 confirmed Claim；
- retrieval score / LLM confidence / provider status / selection reason 不得进入 durable SourceEvidence；
- CI ValidationObservation 不得并入 SourceEvidence identity。

## 5. 稳定合同 owner

- [`../domain_models.md`](../domain_models.md)：P2-D 领域对象与 1–49 决策；
- [`../state_invariants.md`](../state_invariants.md)：硬约束；
- [`ARCHITECTURE.md`](ARCHITECTURE.md)：runtime owner 与 evidence pipeline；
- [`STATE_MODEL.md`](STATE_MODEL.md)：durable / ephemeral / cache / context boundary；
- [`TESTING.md`](TESTING.md)：D-2/D-3/D-4 与 Golden Learning Journey 验收。

**合同冻结 ≠ 功能已上线。** 以下实现顺序仍是唯一当前执行顺序。

## 6. P2-D-3 — COMPLETE

目标：让 D-2 已存在的 durable truth 真正进入学习闭环，而不是继续依赖 legacy `learning_state` JSON 恢复。

### 6.1 P2-D-3A — Semantic Closure + Understanding — COMPLETE

PR #123 merge：`0c481c2e32079d0cd371a43663598b32e2aae712`。

已具备：

- schema v18：`learning_goal_contexts` 与 `learning_goal_claim_revisions`；
- Goal navigation context 与 LearningGoal truth 分离；
- pinned focus 优先于最近 active/blocked Goal；terminal Goal 自动失去 pinned focus；
- D2C Claim/revision commit 原子写入 Goal ↔ ClaimRevision relation；
- 仅显式 semantic closure 才写 UnderstandingEvidence，不做 per-turn durable auto commit；
- durable UnderstandingEvidence 保存 method / validation prompt / raw user response；
- 一次验证覆盖 1–3 个 ClaimRevision，并分别得到 pass / partial / fail；
- evaluator unavailable / needs semantic review → partial，不能伪造 fail；
- explicit misconception reject → fail；
- partial / fail 不得静默完成 Goal；
- explicit user skip 可以完成 Goal，但不得制造 UnderstandingEvidence；
- semantic closure transaction 原子提交 UnderstandingEvidence/results + Goal status + optional NextStep；
- 不保存 evaluator chain-of-thought / confidence 作为 mastery truth。

### 6.2 P2-D-3B — Durable Resume — COMPLETE

PR #124 merge：`c7a3fa0d87ec8646c6063b853f4f370d23aa019a`。

`LearningResumeService` 从 durable Topic / focused Goal / latest ClaimRevision / SourceEvidence / latest Understanding / unresolved Hypothesis / active NextStep 派生 bounded ResumeContext：

- Claims ≤ 3；
- unresolved Hypotheses ≤ 3；
- 1 Primary NextStep + optional ≤ 2；
- Claim recency 由**最新 Revision activity**决定，旧 Revision 不重复进入 resume；
- Understanding 投影轴固定为 `proposed / attempted / partial / confirmed`；
- 默认不把 raw user validation response 放进 ResumeContext；
- Primary / Supporting Evidence 保留 exact source identity；
- `GET /sessions/{session_id}/learning-resume` 已提供 read-only API；
- durable path **不会调用 `SessionService.get_session()`**，恢复不需要重放完整 turns；
- 只有从未获得 durable Goal context 的真正 legacy thread 才走旧 navigation fallback；
- 已有 durable context 但没有 active Goal → `durable/no_active_goal`，绝不 resurrect legacy state；
- legacy `confirmed_points` 只作为 `legacy_confirmed_points` 展示，`claims` 始终为空，不升级为 formal Claim/mastery。

### 6.3 P2-D-3C - Minimal Durable Learning UI - COMPLETE

PR #125 merge：`e413072`。

目标不是增加管理后台，而是把 D3B ResumeContext 接到当前学习 surface，让用户直接看到“正在学什么、哪些 Claim 有 durable 依据、哪里还没解决、理解验证到哪一步、下一步是什么”。

复用现有：

- `LearningStrip`；
- `LearningPanel`；
- `EvidenceTrail`。

第一版只展示：

- 当前 Goal；
- 1–3 个 durable Claim；
- 每个 Claim 的 Understanding 状态；
- Primary Evidence + 可展开 Supporting Evidence（symbol → path/line）；
- unresolved Hypothesis，与 Claim 有明确视觉区别；
- Primary NextStep；
- backend 明确返回 `legacy_fallback` 时才显示 legacy compatibility 信息。

硬边界：

- `LearningPanel/Strip` 不自行读取或推断完整 chat history；
- durable ResumeContext 优先于 `lastChat.route.learning_state`；
- durable/no_active_goal 不得回退到旧 confirmed_points/objective；
- legacy confirmed_points 不得以 Claim/已掌握知识点样式呈现；
- 不引入知识图谱、Claim dashboard、Route editor、Retention dashboard；
- D3C 不实现 freshness/revalidation。

## 7. P2-D-4 — COMPLETE (automation; manual mobile acceptance deferred)

- Primary unchanged → current；
- Primary materially changed → stale_candidate；
- removed / unmappable → source_changed / historical；
- corroborating support drift 不自动 stale；
- prerequisite support materially changed 可触发 stale_candidate；
- explicit revalidation → same Claim lineage + immutable next Revision；
- 完成 full Golden Learning Journey；
- Chromium + Firefox sample + WebKit sample 已完成；实体手机验收因 Android 导出/部署配置未就绪而延期。

### D-4A — Freshness evaluation service - COMPLETE

- 新服务 LearningFreshnessService.evaluate(claim, head_snapshot)：
  - freshness 是 on-demand derived 状态，不新增持久化表/migration；
  - Primary 在 HEAD 重定位（match_line_range + structure index重映射）；
  - path 不存在/无法重映射 → source_changed；
  - HEAD file_sha == 记录 file_sha → current（零内容比较）；
  - file_sha 不同 → symbol body 归一化比较（strip 尾空白、忽略空行）→ 相同 current / 不同 stale_candidate；
  - corroborating drift 只记录；prerequisite 实质变化可触发 stale_candidate；
  - provider 找不到→ unavailable，不推导 Claim false；
  - 归一化单元测试覆盖 TESTING.md L109–119 判定规则。

### D-4B — Resume freshness + UI + revalidation entry - COMPLETE

- GET /learning-resume 成列输出 freshness status + drift detail（案例化；
- LearningPanel 情境化提示：stale_candidate/source_changed 徽章 + 渐进披露（F1/F2）；
- 显式 revalidation 入口：新 closure run 带 claim 上下文，commit 复用 lineage；
- Playwright fixture + e2e 测试。

Backend completed (items deferred at that time):
- resume projection 已带 freshness detail（status/head_commit/reason/primary/supporting_drift），
  evaluator 故障降级为 unavailable 不中断；
- POST /sessions/{session_id}/claims/{claim_id}/revalidate 已实现：
  同 lineage 新 Revision（reason=revalidated），missing claim / no active goal /
  no primary source 均显式拒绝并返回对应 404/409；
- revalidation 后立即回写 freshness status；
- 当时延期项：LearningPanel UI 徽章 + 渐进披露、Playwright fixture + e2e；
  以上项目随后已由 D-4C 完成，不是当前缺口。

### D-4C — Full Golden Journey (AFTER D-4B) - COMPLETE

- 拓展 mini journey 到 step 1–17，用真实源码 + 双 commit 对；
- step 14–17：Primary 实质修改 → rev1/confirmed 保留、freshness → stale_candidate → 显式 revalidation → rev2 同 lineage；
- e2e golden journey 同步扩展。

Completed（35336cc + 8fc1746）:
- backend 侧 suspension 保留 rev1/confirmed → freshness stale_candidate → revalidate → rev2 同 lineage 已全链路验证；
- 前端缺陷修复：LearningStrip 缺行与来源补充、摘要刷新、stale/current 角度刷新、badge 标题 tooltip、server-only 断言（网络环境不可取时逐层降级而不报错）；
- LearningPanel「重新验证」按钮条件渲染守卫（仅 stale/source_changed 显示），单测锁定；
- e2e `stale_revalidation` journey：stale 条可见 → 重新验证 → 全部 current，desktop + mobile 双项目通过；golden-journeys manifest 期望 29 项已完成。

### D-4D — Cross-browser acceptance (AFTER D-4C) - COMPLETE (automation) / MANUAL MOBILE DEFERRED

- playwright config 新增 desktop-firefox / desktop-webkit sample（仅 golden-journeys，避免双倍全量成本）；
- `channel: chrome` 限定到 chromium 项目（原先顶层 use 会让 firefox 报 Unsupported channel）；
- 核心 journey 在 firefox / webkit 上通过：golden-journeys 4 条 × firefox/webkit 8/8；
- teardown manifest 扩展为 53 项（4 golden journeys × 4 桌面/移动项目 + complex_content_narrow），全量 5 项目 51/51 通过；
- 实体手机验收步骤保留在 `docs/MOBILE_ACCEPTANCE_D4D.md`；当前因 Android 导出/部署配置未就绪而延期，恢复后由执行人填写并归档。

Known environment notes:
- 本机 `npx playwright install chromium` 默认 CDN 不可达，使用 `PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright` 完成安装；
- 系统 Chrome（channel: chrome）下 complex-content linkRectCount 断言失败（渲染差异），headless shell 下通过；CI 保持默认 headless。

## 7.5 P2-E — Post-P2-D acceptance + test hardening (AFTER D-4D) - AUTOMATION COMPLETE / MANUAL MOBILE DEFERRED

范围（2026-08-11 现状调研确认；G 系列产品能力评审已排除）：

### E-5 — Repo cleanup - COMPLETE

- 删除 15 个已合并/过时的本地残留分支（codex/*、claude/*、P2-D-4A-freshness 等），保留 main + release-v0.8.0；
- 远程分支不动；不改变 main 内容。

### E-1 — Acceptance + docs/memory sync - AUTOMATION COMPLETE / MANUAL MOBILE DEFERRED

- 实体手机验收（人工）：因 Android 导出/部署配置未就绪而延期；恢复时按 docs/MOBILE_ACCEPTANCE_D4D.md 10 步执行并填写记录表（执行人/日期/浏览器/设备），完成后回写本 owner；
- docs 收口：TECH_STACK.md “后续 LearningClosureRun”已更新（G1 已实现）；memory/ 六个版本文件已同步到 P2-E 时代；
- 基线收口：8dcaf11。

### E-2 — Backend direct tests for helper modules - COMPLETE

- 覆盖审计结果：之前“17 个模块无测试”过保守；其中 6 个被 test_web_primitives / test_module_identity 直测覆盖、其余 9 个已有命名测试；
- 真正零测试只有 2 个：module_aliases.py + evidence_pinning.py，已补 16 个直测（tests/test_module_aliases.py 9 + tests/test_evidence_pinning.py 7）；
- 不改变产品行为，纯测试补缺。

### E-3 — Frontend surface tests - COMPLETE

- MarkdownMessage/StatusDot/RoadmapPanel/RoutePanel/roleCatalog/useRoleController 建立直测（6 个测试文件，24 个测试）；
- 不改变 UI 行为。
## 8. 当前执行顺序

```text
P2-D-1                         ✅ complete
P2-D-2A                        ✅ complete
P2-D-2B                        ✅ complete
P2-D-2C                        ✅ complete
D-2 mini Golden Journey        ✅ complete
P2-D-3A semantic closure       ✅ complete
P2-D-3B durable resume         ✅ complete

P2-D-3C minimal durable UI     ✅ complete

P2-D-4A freshness service      ✅ complete (PR #126)
P2-D-4B resume freshness + UI  ✅ complete (PR #126)
P2-D-4C full Golden Journey    ✅ complete (35336cc + 8fc1746)
P2-D-4D cross-browser          ✅ complete (automation 51/51; manual mobile deferred until Android export/deploy readiness)

P2-E-5 repo cleanup            ← 已完成（删 15 个已合并本地残留分支）
P2-E-1 acceptance + docs sync  ← 自动化/文档收口完成；实体手机人工验收延期
P2-E-2 backend direct tests    ← 已完成（src/web + src/application 17 模块直测）
P2-E-3 frontend surface tests  ← 已完成（MarkdownMessage/StatusDot/RoadmapPanel/RoutePanel/roles）

P2-E
post-P2-D acceptance + test hardening（不含 G 系列产品能力评审）
```

任何后续实现若改变该顺序或扩大 scope，必须先更新本唯一状态 owner，再执行。

## 9. 后续核心路线审计（2026-08-13）

当前代码核验确认，历史计划中的以下项目已经实现，不得重复建设：

- PedagogyEvalRun 已接入真实 turn completion、SQLite repository 和 semantic evaluation；
- pedagogy golden dialogues 与质量门禁已存在；
- after-session preview/commit 与 durable learning closure 已存在；
- 前端已升级 React 19 并迁移到 Testing Library，`react-test-renderer` 已移除；
- Streamlit `app.py`、`src/ui` 和依赖已移除。

**LearnerModelSnapshot 只读派生第一切片已完成。** owner 边界保持如下：

- LearningTruth 继续唯一拥有 Claim、SourceEvidence 与 UnderstandingEvidence；
- PedagogyEvalRun 继续只是逐轮评估记录，不直接成为长期画像；
- learner-profile memory 只保存用户确认的偏好，推断候选默认 pending；
- Learner Model 不创建 mastery 百分比，不推断敏感属性，不形成第二套学习真值；
- 第一实现切片不得夹带 GraphRAG、临时附件、统计面板或新的角色专属画像。

已落地范围：

- `LearnerModelSnapshot` 在读取时从当前 focus Goal、其最新 ClaimRevision / Understanding 结果、未解决 Hypothesis 数量、同目标 PedagogyEvalRun 汇总和已确认 learner-profile allowlist 派生；
- 快照有界、不可变且无独立 ID / 时间戳，不持久化 mastery，不暴露原始学习者回答；
- runtime factory 与 `GET /sessions/{session_id}/learner-model` 只读 API 已接线；没有新增 UI、表或写回路径；
- 真实 SQLite 集成测试逐表验证构建前后数据完全一致。

联网研究真实性与可用性已于 2026-08-12 完成自动验收收口：本机 Docker Desktop 数据盘已迁到 `D:\DockerDesktopData`，本地 `study-agent-searxng` 仅绑定 `127.0.0.1:8080`，SearXNG 为首选搜索源，Bing RSS 与 DuckDuckGo HTML 仅作顺序降级；DuckDuckGo challenge、HTTP/连接/超时以及总搜索预算耗尽均结构化记录，失败/空结果不会标记 `found`，也不会进入模型证据。普通联网问答绕过慢速 LLM 工具规划器，GitHub/PR 专用研究仍保留工具规划；provider 顺序降级共用 8 秒搜索预算，研究总预算维持 12 秒，按请求隔离执行器，连续 5 次超时后第 6 次仍可按预算终止。ResearchRun 只有至少一个带标题和公开 URL 的搜索结果，或搜索已发现 URL 的成功正文读取，才可进入 `found`；失败时首个可见答复明确写明“联网搜索失败，本回答未使用联网来源”，成功时先流出最多 3 个可点击来源，再等待模型综合正文。自动证据：3 个普通查询各返回 5 条来源，分别 3.95 / 1.30 / 2.06 秒；真实 `/chat/stream` 请求在 4.33 秒到达 `completed/found`、持久化 5 个来源，并在 4.34 秒输出首个可见来源结果。全量 pytest 1036/1036、ruff、detect-secrets 0 findings、相关 mypy、前端 Vitest 319/319 与 production build 已通过；提交 `2fac9d4` 的完整远程 CI #31618437026 已实际运行并全绿。

> **2026-08-26 解释修订：**上面的历史证据只证明 provider、预算和基础 `found` 行为，不证明普通 `chat_tool_loop` 已读取正文或具备研究级结论质量。真实“请联网研究：opus5”运行只执行 1 次查询、取得 5 个候选（约 3 个独立内容家族）、正文读取 0 次、无官方一手来源，却把候选标为 `validated_tool_evidence` 并生成确定性价格/能力结论；UI 又只展示前 3 条。因此 G9/G13 的研究级真值门已重开为 RQ1，完整冻结合同与路线见第 15 节。

### 9.1 全项目文档治理 — COMPLETE

- 扫描 130 份受版本控制的 Markdown / text 文档；区分当前 owner、稳定合同、专项运行文档、历史 archive、changelog、运行内容与测试夹具；
- 删除 14 个无仓库内消费者、只有 5–10 行的历史兼容指针；完整历史正文仍保存在 `docs/archive/` / `docs/archive/root/` 与 Git 历史；
- 将 `WEB_SEARCH_IMPLEMENTATION_NOTES.md` 的有效实现说明并入 `NEWS_PIPELINE.md`，`WEB_SEARCH_SETUP.md` 成为普通联网研究与 NewsRun 的唯一 provider 配置入口；
- 修正根 README 中“PR #115 CI 尚未绿色”和 USER_GUIDE 中“生产 Claim UI 冻结”等已与当前 owner 冲突的旧表述；
- 当前文档相对链接扫描通过：38 份现行文档无缺失本地目标；archive、changelog 与测试夹具保留原始时间语义，不参与当前链接验收。

### 9.2 联网 provider 只读健康诊断 — COMPLETE (local validation)

- 新增受 API token 保护的 `GET /health/providers`；核心 `/health` 保持无网络、快速 readiness 语义；
- 诊断区分 `enabled`、`configured`、服务 `reachable` 与实际 `search_capable`，endpoint 只返回脱敏 scheme/host/port；Bing RSS 与 DuckDuckGo 仅报告 fallback 开关，不把“已启用”冒充“已可达”；
- SearXNG 探针先检查 `/healthz`，再用 5 秒上限验证普通搜索；服务在线但引擎超时/无有效结果时明确标记 `degraded`；
- 本机 Docker `study-agent-searxng` 恢复后，真实 provider health 为 `ready`（4.26 秒）；普通查询 `Python 3.12 documentation`、`OpenAI API documentation`、`Godot Engine documentation` 各返回 5 条带标题/URL 的来源，分别 3.47 / 4.07 / 1.87 秒；
- 本地门禁：ruff 全仓通过；后端收集 1043 个测试，1037 个 tracked 测试按 12 个受控分片全部通过，新增 provider-health 6/6 通过；detect-secrets 0 findings；expanded mypy baseline 122 ≤ 128（本批新增文件 0 error）；前端 Vitest 82 文件、319/319 与 production build 通过。
- 远程收口：核心提交 `326d0ff` 首次 CI #31684026410 的 pytest/RAG/ruff/package 均通过，但 detect-secrets 正确拦截安全负例中的 Basic Auth 形态测试字符串；最小 allowlist 修复 `d85789a` 后，[CI #31684795857](https://github.com/2002yy/study-agent/actions/runs/31684795857) 完整全绿，pytest、RAG baseline、ruff、package helper、detect-secrets、expanded mypy baseline、前端 test/build、三浏览器 Golden Journeys 与 real-stack browser gates 均实际运行并通过。

### 9.3 设置页按需联网检测 — COMPLETE

- 设置页新增“检测联网搜索”，只在用户点击时请求 `GET /health/providers?probe=true`；不进入启动快照、不自动轮询、不写配置，探测按钮也不复用聊天发送锁；
- 页面区分首选 SearXNG 可用、服务在线但搜索引擎异常、首选源不可达且仅降级源开启、所有来源不可用；请求失败会保留明确错误，不把“已启用”写成“已可用”；
- 前端 API / 组件测试覆盖首次渲染零探测、ready、degraded、unavailable、请求失败和聊天期间独立检测；Vitest 83 文件、323/323 通过，production build 通过；
- Playwright 新旅程在 desktop + mobile Chromium 均通过，完整本地矩阵前 49 项（desktop/mobile/narrow Chromium 与 Firefox）通过；本机 Playwright WebKit 2336 进程启动即以 `3236495362` 退出，4 项未运行到产品断言，必须以远程 CI 的 WebKit 门禁作为最终结论，当前不得写成完整矩阵全绿；
- 真实 provider 复验为 `ready`；`Python 3.12 documentation`、`OpenAI API documentation`、`Godot Engine documentation` 各返回 5 条有效标题/URL，用时 1.95 / 1.31 / 1.69 秒，全部命中首选 SearXNG；相关后端 pytest 55/55 与 ruff 通过。
- 远程收口：提交 `34cbc66` 的 [CI #31688399223](https://github.com/2002yy/study-agent/actions/runs/31688399223) 完整全绿；远程三浏览器 Golden Journeys（含 WebKit）与 real-stack browser gates 均实际运行通过。

### 9.4 G1-G18 现状差距审计 — AUDIT COMPLETE

2026-08-13 差距审计后已实现 G15/G16/G17 的首批核心切片；G 表按当前代码与自动化证据更新。视觉、对比度、真实屏幕阅读器和实体手机仍保持 **未人工复核**，不得以自动化替代人工记录。本批本地证据：外发策略 pytest 10/10、ruff 通过；前端全量 88 文件 334/334、生产构建通过；关键 real-stack 移动端研究恢复、归档确认和资料证据旅程均定向通过；本机完整 real-stack 因约 64 秒终端上限未完成，最终结论以远程为准。远程 CI 依次真实暴露并修复：首次说明遮挡核心交互（#31697827369）、空 live region 造成复制反馈重复（#31699705213）、首次说明遮挡 real-stack 操作（#31700484139）、移动端粘性输入区遮挡证据按钮（#31702106709）。最终提交 `f69a305` 的 [CI #31703041709](https://github.com/2002yy/study-agent/actions/runs/31703041709) 完整全绿，53 条三浏览器 Golden Journeys 与 14 条真实栈门禁均实际运行并通过。

| G | 当前结论 | 已有事实与仍存真实缺口 |
|---|---|---|
| G1 LearningClosureRun | COMPLETE | server-owned durable run、正式状态机、幂等 preview、retry/cancel 与可恢复 UI 已存在。 |
| G2 结构化总结输入 | COMPLETE | closure 读取 committed learning truth、受预算约束的对话、PedagogyEvalRun 与证据引用；未提交/失败回合不冒充已确认理解。 |
| G3 summary status | COMPLETE | commit 后 summary status、同版本防重复、继续/归档并新建均已分离，且不自动归档。 |
| G4 会话导航 | COMPLETE | 标题、任务/阶段/缺口/状态、重命名、搜索和分组已实现；G4 收口（`4866880`，CI #32717990269）：`/sessions` 支持 q/limit/offset 服务端搜索（id + 手动标题 + learning_state）与分页总数，导航器防抖服务端搜索替换最新窗口集合并提供“加载更多”，较早会话可从 UI 直达。 |
| G5 去伪精化 | COMPLETE | 主 UI 使用目标、阶段、缺口、下一步和验证状态，不生成 heuristic mastery 百分比。 |
| G6 恢复卡 | COMPLETE | 新用户入口、durable Resume、研究 partial/interrupted 的继续/重试/放弃均已有正式状态来源。 |
| G7 UI 聚焦 | COMPLETE | 一级入口已收敛，诊断/来源/设置等进入次级 surface，普通状态不暴露低层 record/provider 参数。 |
| G8 窄屏可用 | COMPLETE (automation) / MANUAL DEFERRED | 自动化窄屏、三浏览器与 real-stack 门禁已通过；Android 导出/部署未就绪，实体手机记录表仍未填写。 |
| G9 时效检索 | PARTIAL / RQ1 REOPENED | SearXNG provider 可用性、结构化失败和快速查询预算已有证据；但明确研究意图仍可落入单查询、零正文读取的 `chat_tool_loop`，不能以候选摘要支撑研究级强结论。 |
| G10 ResearchRun | COMPLETE | follow-up child lineage、服务端安全 seed、本地候选、active Run steering、重新读取门、root aggregate、幂等与四态 EvidenceTrail 已实现；`dd93fda` 的 CI #32761262084 attempt 2 全门禁通过。 |
| G11 TaskContract | COMPLETE | task/source/closure 合同在角色、RAG、联网和记忆前确定，并持久化到 route snapshot。 |
| G12 预回答与取消 | COMPLETE | ChatTurn reservation + operation CAS、ResearchRun/本地 RAG/模型生成 cooperative checkpoints、durable cancelled/interrupted、server single writer、归档队列和三 viewport 真实栈时序证据均已交付。RagWriteRun 是独立写入生命周期，不属于本次只读 turn retrieval 取消合同。 |
| G13 证据/消息完整性 | PARTIAL / RQ1 REOPENED | adopted/candidate/read/rejected 模型已存在，但真实运行发现零读取候选被标为 `validated_tool_evidence`，UI“本次使用的来源”与实际 candidate-only 证据不一致；历史记录必须显示 unknown/candidate，不得伪造已读。 |
| G14 导入与来源范围 | COMPLETE | 长期资料库之外，当前会话临时附件已具备每文件状态/重试、thread 隔离、ready-only 召回、即时删除、归档成功后清理、幂等转正、文本 embedding fail-closed 和默认关闭的 vision 授权；实现至 `c761052`，交付记录 `1a471d4`。 |
| G15 会话转换 | COMPLETE (automation) / MANUAL VISUAL PENDING | 新建、切换、归档共用一个只读派生 transition guard；覆盖 chat generation、Memory preview/closure、partial ResearchRun 与 RagWrite，逐项说明停止、保留、继续或放弃的真实效果。归档只确认一次；从抽屉触发时先关闭来源抽屉，避免双 `aria-modal`。RagWrite 仍没有服务端取消能力，守卫明确说明其继续到真实终态而不冒充已取消。完整远程浏览器与 real-stack 矩阵已通过。 |
| G16 外发数据与隐私 | COMPLETE (automation) | evaluator 语义复核与外部 embedding 均 fail-closed，ChatTurn 逐调用记录真实 purpose/provider/categories/count/result，legacy 显示 unknown；G14 vision 使用独立默认关闭授权；跨会话记忆具备 off/ask/auto、会话级 CAS 同意/撤销和三态审计。止血、附件授权与 memory ask 均已交付 main。 |
| G17 首次使用/可访问性 | PARTIAL (P1, Enter 已收口 `f297dc9`) | 全局 API/操作错误已有 `alert`，部分故障用 polite `status`；API/部分故障提供重试、设置、详情，不能安全重放的操作错误直接显示完整错误并提供设置、关闭。转换确认复用 focus trap/Escape/焦点返回，首次外发说明不阻塞聊天；移动端真实栈已验证输入区不再遮挡证据操作。Enter/Shift+Enter 已可通过设置切换为 Ctrl+Enter 发送（`enter_to_send`，`f297dc9`，CI #32648090478）；视觉、对比度、真实屏幕阅读器和实体手机未人工复核。 |
| G18 React/Streamlit 迁移 | COMPLETE | React 19 + Testing Library 已完成，Streamlit 入口、`src/ui` 与依赖已移除。 |

当前未发现传统远程利用或数据破坏型 P0。G12、DR1、G14、G16 自动化切片、G17 Enter 配置、G4 与 G10 一般 follow-up 继承均已交付。2026-08-26 新增两个已授权窄门：SX1 固定 SearXNG 运行基线，以及 RQ1 修复明确研究意图下的候选/已读语义、证据覆盖和分析质量。G17 真实屏幕阅读器、视觉对比度和实体手机仍只能由真实设备/辅助技术证据关闭，不得由自动化冒充；其正式 LAN 验收排在 RQ1 GO 之后。

### 9.5 Learner Model UI 产品决策 — STANDALONE NO-GO

独立 Learner Model 页面或仪表盘 **不启动**。现有 LearningPanel / ResumeContext 已经展示目标、Claim、理解验证、未解决缺口、证据与下一步；再建顶层面板会复制同一学习真值并诱发第二套状态解释。当前 `LearnerModelSnapshot.evaluation` 还通过 `PedagogyEvalRun.objective == LearningGoal.objective` 文本相等聚合，而不是 `goal_id` 关联；目标改名或同名目标会使计数错配，因此这些计数不得作为“当前目标表现”直接展示。

后续若确有用户价值，只允许在现有学习面板中按需加载一个可失败隔离的只读补充区，并同时满足：

1. Claim、验证状态、缺口与下一步复用现有 ResumeContext 展示，不复制或重算；
2. 只显示用户已确认的学习偏好及其来源说明，不显示 inferred/pending profile；
3. 不出现 mastery、掌握度百分比、分数、等级、排名或人格/敏感属性推断；
4. evaluation 在完成 `goal_id` provenance 前不展示；`accepted/rejected` 只能解释为教学评估运行结果，不能解释为学习者能力；
5. 面板打开时才读取，API 失败不影响主学习闭环；不得新增写回、独立 ID、独立时间线或长期画像 owner。

因此 Learner Model UI 不是下一批。它的条件式只读补充区只有在 G15/G16 核心缺口收口、且评估 provenance 可解释后才重新评审。

### 9.6 GraphRAG 与长期画像写回边界 — DEFERRED

- **GraphRAG** 是把概念、Claim、来源、前置关系、支持/反驳关系组成图，再沿图扩展检索和拼装证据。当前系统已有关系型 LearningTruth 与有界 `depth=1` 学习关系扩展，但没有新的通用图索引、图检索器或 GraphRAG evidence owner；启动它会增加索引一致性、证据 provenance、删除同步与第二检索真值风险。现有核心缺口不需要它，保持未启动。
- **长期画像写回** 是从对话与行为推断“偏好、习惯、薄弱点或能力特征”，再写入跨会话持久存储。当前只允许用户确认的 learner-profile allowlist；推断候选默认 pending，不自动写回，不把教学评估或答题结果升级为掌握度。未来若评审，必须先冻结用户同意、来源说明、查看/修改/删除、过期、冲突、范围隔离和敏感属性禁写合同，并且不得成为第二套 LearningTruth。

### 9.7 后续执行顺序

1. ~~G12 ChatTurn cooperative cancellation~~ — 已交付并全门闭合（第 10 节）。
2. ~~DR1 Deep Research（历史提交标签 `G18 DeepResearch`）~~ — 已交付；扩展 WebLookupRun，不新增第二 run owner（第 11 节）。
3. ~~G14 临时附件、G17 Enter 配置、G16 会话记忆 ask、G4 历史分页/搜索~~ — 均已交付 main 并取得完整 CI。
4. ~~G10 follow-up inheritance Grill + 实施~~ — 15 项决策、schema v23、服务端 lineage/重新验证和 UI 真值已交付；`dd93fda` 的 CI #32761262084 attempt 2 全绿（第 14 节）。
5. ~~**SX1 最小 SearXNG 可复现基线。**~~ 已按固定 image digest、最小 Compose/config、本机 secret/proxy layering、`18080` candidate、真实搜索与可回滚切换完成，并由远程 CI #32877392793 关闭交付门；未开放 LAN。
6. **RQ1 有界研究真值与质量修复。** 先止血 candidate-only 语义和 UI，再实现明确研究意图的规划、正文读取、证据家族、主张绑定与双门验收；RQ1 未 GO 时不得把 LAN 结果写成正式 G17 GO。
7. **G17 人工可访问性与显式 LAN 验收。** 只在 SX1/RQ1 GO 后进入；对比度、真实屏幕阅读器与实体手机仍由人工证据关闭。当前 WLAN 为 Public 且 LAN controller 尚未实现，保持 `BLOCKED / AUDIT REQUIRED / Decision: NO-GO`。
8. **继续延期 Android 产品化、Learner Model 独立 UI、GraphRAG 与长期画像写回。** 它们不得抢占当前研究真实性缺口，也不得创建第二套真值。

当前阶段：**RQ1-A / Pre-RQCE 已由 `7edfda4` 和 CI #32945352584 交付；Research Quality 路线已统一为共享引擎的 quick/bounded/deep presets。RQCE-P0-A0 至 B3 已由 `2afea76f7a37abc1a48e4f25c4974439383907fb` 交付 `main`，匹配的 CI #32955918199 为 `success`；当前唯一允许的下一逻辑 batch 是 RQCE-P0-C1 eval schema；RQ1 整体与 G17-LAN 仍为 NO-GO。**

## 10. 2026-08-21 同步、仓库整理与下一切片门禁

### 10.1 同步与整理审计

- 本地 `main` 与 `origin/main` 均为 `589169b0852c23300b01cf51bd6fa98a080e445c`，`main...origin/main = 0/0`；本轮无需合并或改写历史。
- 该 SHA 对应的远程 [CI #31704003134](https://github.com/2002yy/study-agent/actions/runs/31704003134) 已于 2026-08-13 完成且结论为 `success`。
- 工作区没有已跟踪文件的既有改动；本地虚拟环境、Playwright 报告与门禁输出保留在磁盘，只通过 `.gitignore` 排除，不把用户产物当作仓库内容删除。
- 失效 worktree 的实际路径已不存在，可只清理 Git 管理记录；远程历史分支不在本轮授权范围内，不删除。
- 文档继续保持三层：`PROJECT_STATUS.md` 拥有当前事实和执行门；稳定合同文档拥有语义；`archive/` 和 `superpowers/` 只保留历史时间语义。
- `INTERVIEW_NOTES.md` 已从陈旧的 Streamlit/旧测试数量介绍改为当前项目表达与 Grill 决策索引，但不成为第二个状态 owner。

### 10.2 G12 已确认的实现事实

- chat 流与 provider 生成阶段已有 browser abort / `should_cancel` 链路；ResearchRun 另有服务端 owner、取消请求和 durable `cancelled` 终态。
- chat pre-answer preparation 仍会同步取得本地 RAG context；当前 local RAG retrieval 没有接收 cancel signal，也没有独立 durable run 可表达取消终态。
- RagWriteRun 是资料写入/索引生命周期，不等于本次 chat 的只读 local RAG retrieval；它没有 cancel endpoint，必须另立事务和回滚合同。
- 因此仅在前端丢弃响应，不能证明本地检索已停止，也不能标记服务端工作为 `cancelled`。

### 10.3 已锁定边界

本切片只讨论 **chat pre-answer 的只读本地 RAG 检索取消**。明确非目标：

- 不顺带实现 RagWriteRun 取消或索引事务回滚；
- 不实现 G14 临时附件、每文件重试或附件外发策略；
- 不实现 G16 按会话记忆 ask、G10 follow-up run 继承、GraphRAG 或长期画像写回；
- 不因客户端断开而删除已存在的长期资料、SourceEvidence、LearningTruth 或历史 ChatTurn；
- 不用“前端不再显示结果”冒充服务端检索已停止。

### 10.4 G12 / G16 最终 Grill 决策（1–24）

Grill coverage 于 2026-08-21 经多轮代码路径反证后闭合。以下决定已经锁定：

1. **停止范围：**停止当前 ChatTurn 拥有的全部未完成工作，包括 ResearchRun、本地 RAG 和模型生成；不删除长期资料，不回滚与该 turn 无关且已完成的操作。
2. **单一状态 owner：**在耗时准备前持久化 ChatTurn；`cancel_requested → cancelled/interrupted` 写入 ChatTurn，不新增 LocalRagRun 作为第二真值。检索函数只接收该 turn/operation 的 cooperative cancellation check。
3. **未采用检索：**只保留取消阶段、query-plan 摘要、计时和结果数量；未采用 local chunks 不进入模型、LearningTruth、引用或自动重试复用。
4. **响应时间：**UI 必须在点击后 200 ms 内同步显示“停止请求正在提交/已登记”；这不是服务端物理终止 SLA。每个检索阶段设置检查点，注入慢检索并记录从登记到真实终态的实测上限。
5. **终态区分：**没有任何可见输出为 `cancelled`；已有回答 token 或联网来源预览为 `interrupted`，保留可见部分与本轮已采用资料。
6. **单调 fence：**已接受取消的 operation 永远不能再提交 `completed`、调用后续模型或写学习真值；若 completed 已先原子提交，取消返回 `already_completed`。
7. **统一接口：**`/chat` 与 `/chat/stream` 使用同一 turn cancellation semantics。前端不并行拼装 ResearchRun、浏览器 abort 和 ChatTurn 三份终态。
8. **恢复语义：**cancelled 重发创建新 operation 并全新检索；interrupted continue 使用同一 turn 的已持久化 RAG snapshot、不得重跑检索；regenerate/retry 创建新 operation/child turn 并全新检索。新 operation 不继承旧取消标记。
9. **协作式取消：**不承诺强杀线程/进程。当前同步 provider 调用可自然返回后丢弃，但 fence 必须阻止任何后续副作用。
10. **会话转换：**取消登记后可立即切换、新建或关闭；归档与同会话新问题必须等待该 operation 终态。
11. **最小持久化：**ChatTurn 记录 operation-scoped cancel timestamps、stage、reason 和 operation identity；延迟可派生，不保存未采用正文。任何“已接受取消仍可 completed/调用模型/写真值”均为 kill criterion。
12. **明确 UI：**状态放在 turn bubble，不只用 toast；使用 `status`/`alert`、文本而非颜色，覆盖窄屏。浏览器 abort 本身不能显示“已停止”。固定文案区分提交中、停止中、慢收尾、cancelled、interrupted、already completed、请求失败、等待归档和归档失败。
13. **覆盖复审修正：**服务端是 partial reply 唯一 writer；前端在已接受取消后不得再 `commitTurn`。生产 `ExternalDataPolicyChatService` 与基础 ChatService 必须共享 reservation/checkpoint/settlement shell，真实栈测试必须走生产 policy service。`cancelled` 加入 session detail、export、恢复与 consumer regression matrix；closure 仍只消费 completed。
14. **兼容边界：**官方客户端必须预分配 handle 并可取消；未提供 handle 的 legacy 同步 `/chat` 请求中途不可取消，不伪装兼容。
15. **持久归档队列：**`archive_after_cancel` 绑定 operation 并由服务端持久化；刷新、关闭、重启后仍执行。支持取消待归档；停止成功但归档失败要保留会话并显示独立错误。
16. **优先级改写：**先完成窄 G16 隐私真值止血，再开始 G12。
17. **限制策略下的教学评估：**`question_only` / `recent_chat` 不允许外部语义评估接收长期学习状态；先用本地 deterministic evaluation，明确记为受策略限制而未语义复核，不能伪装 pass/fail。
18. **逐调用外发真值：**不新增外发 run；在 owner snapshot 中记录小型 `external_calls` 清单，包含 purpose、provider、实际数据类别/数量和结果，不存正文。UI 分开显示回答生成、教学评估、embedding 等用途。
19. **历史记录：**增加执行记录版本；旧 turn 缺少语义评估调用证据时显示“历史记录粒度不足，学习评估外发状态未知”，不反向改写为 false。
20. **身份与终态观测：**官方客户端预分配 cryptographically random `turn_id + operation_id`；取消用 `(turn_id, expected_operation_id)` CAS。Cancel POST 只确认请求登记，客户端通过 turn-status endpoint/poll 等待 durable 终态；迟到旧请求不能误杀同 turn 的 continuation。
21. **文档 embedding 授权：**在建立文档级云处理授权前，任何可能离机的 embedding provider 都不得处理用户文档正文；operator 环境变量不等于用户同意。
22. **外部 query 最小化：**未来即使明确允许外部 embedding，`question_only` / `recent_chat` 下也只可发送当前原始问题；包含学习目标/缺口的 `private_query` 只允许本地使用。
23. **fail-closed 体验：**隐私策略阻止远程 embedding 时，本地解析、关键词索引和本地向量阶段仍可完成；远程阶段记录 `blocked_by_policy`。UI 不静默降级后继续显示“增强语义”。
24. **复用现有 owner：**聊天回答/教学评估/query embedding 的外发事实归 ChatTurn；文档正文 embedding 归现有 RagWriteRun stage，不创建新审计实体。

### 10.5 明确拒绝的替代方案

- 拒绝把浏览器 `AbortController`、连接断开或 UI 不再显示结果当作服务端 cancelled。
- 拒绝只用 turn ID 取消；同一 turn 可 continuation，迟到请求会误杀新 operation。
- 拒绝让前端和服务端同时提交 partial reply，或由前端猜测 durable 终态。
- 拒绝新增 LocalRagRun、外发审计 run 或另一套取消状态机。
- 拒绝在 cancelled retry 中自动复用未采用 chunks；拒绝 continuation 重新执行 route/RAG/web preparation。
- 拒绝把 `allow_local_evidence` 扩张解释为“允许把整个资料库上传给 embedding provider”。
- 拒绝把 operator 配置、API key 或 provider 可用性解释成用户隐私授权。
- 拒绝对旧审计记录进行无法证明的 backfill；未知必须显示为未知。
- 拒绝承诺无法由 cooperative checkpoint 保证的固定服务端终止毫秒数。

### 10.6 完成门与验收矩阵

**G16 止血门：**

- 主动学习状态 + `question_only` / `recent_chat` 的真实 production policy path 中，semantic evaluator 不收到 objective、protocol、expected concepts、历史 evidence 或长期记忆；执行记录与捕获调用参数一致。
- 回答模型、教学评估、query embedding、document embedding 分用途记录 actual data categories；旧记录显示 unknown，不显示假 false。
- `Chroma + external embedding` 配置下，未授权文档正文不离机；RagWriteRun 记录 `blocked_by_policy`，本地可完成阶段不被伪装成失败或增强语义成功。
- 任一限制策略仍能把禁止数据送入任何模型/provider，或 EvidenceTrail 与实际调用不一致：**NO-GO**。

**G12 自动门：**

- 覆盖 cancel before reservation、reservation race、每个检索/facet/backend checkpoint、检索后模型前、首 token 前、首 token 后、completion race、continuation/retry、disconnect、restart recovery、archive queue/failure/cancel。
- 同步 `/chat` 与异步 `/chat/stream` 共享状态语义；基础服务和 production policy service 都通过，real-stack 必须走后者。
- 证明 accepted cancel 的旧 operation 无法 complete、无法调用后续模型、无法写 LearningTruth/引用；前端不调用 partial commit fallback。
- `cancelled` consumer regression 覆盖 session detail、历史恢复、export、closure、LearningState 和窄屏 UI。

**G12 人工与时序门：**

- 点击后 200 ms 内 turn bubble 明确确认 UI 已接收操作；慢检索场景记录 cancel 登记到每个 checkpoint/最终终态的实际最大值。
- desktop、narrow landscape、mobile viewport 验证状态文本、aria live semantics、离开会话、等待归档、取消归档和归档失败。
- 不以 mock sleep 的固定断言或浏览器请求被 abort 代替真实服务端终态记录。

### 10.7 GO / NO-GO 与唯一下一步

- **Grill coverage：COMPLETE。** 目标、边界、非目标、恢复、兼容、隐私、失败语义和验收门已冻结，无剩余产品选择要求实现者自行决定。
- **G16 local implementation/stop gate：GO。** 窄修复和本地全量证据完整；没有发现禁止数据到达测试 provider、legacy 假 false 或本地索引回归。
- **G16 delivery：GO / COMPLETE。** 实现 `2662cd3` 与 legacy Golden Journey 验收修正 `a3f00de` 已快进进入 `main`；完整 CI #32499954659 全绿。
- **G12 implementation：GO / COMPLETE。** reservation、operation CAS、retrieval checkpoints、durable terminal truth、200 ms UI 自动观测和慢检索真实栈证据已交付。
- **本节历史下一步：CLOSED。** G10 follow-up inheritance 已完成合同与本地实施；2026-08-26 的当前路线以 15.5 为准。

### 10.8 G16 窄修复实测证据

- production policy 路径使用 active LearningState + explicit learn task 覆盖 `question_only`、`recent_chat`、`allow_local_evidence`：前两者 evaluator 调用数为 0，结果为 `needs_semantic_review / blocked_by_policy`；允许策略仍实际调用并记录 provider/categories/count/result。
- Chroma 外部 provider 的 document/query 测试在取 collection/client 与调用 embed/embed_many 前抛出 policy error；捕获的 provider 输入与 collection 调用均为空。Chroma + local embedding 的 upsert/query 正常控制仍通过。
- RagWriteRun 在外部 document embedding 被阻止时仍 `completed + activated=true`，vector stage 为 `blocked_by_policy`，本地索引可读取；真实 vector failure 仍保持 partial success 且不激活。
- ChatTurn `external_data_audit_version=2` 逐调用记录 answer generation、semantic evaluation、query embedding；旧 audit version 的 web/history/local evidence/learning state/memory 均显示“历史记录粒度不足，实际状态未知”。记录只含类别与数量，不含正文/query。
- `.venv\Scripts\python.exe -m pytest -q`：**1051 passed**。
- `npm test`：**88 files / 336 tests passed**；`npm run build`：通过，仅保留既有的 >500 kB bundle warning。
- `ruff check .`：通过；mypy baseline：current 122 / baseline 128 / new 0；detect-secrets：0 个 finding 文件；`git diff --check`：通过。
- 实现提交 `2662cd3a57b4b12f4115e3cddaec4b5f59604e1e` 与 legacy Golden Journey 验收修正 `a3f00de4ae700d8661c05718cafa0d7a29781927` 已快进交付到 `main`；[CI #32499954659](https://github.com/2002yy/study-agent/actions/runs/32499954659) 完整全绿，G16 止血证据闭合。

### 10.9 G12 交付证据 — ChatTurn cooperative cancellation（2026-08-22）

按已冻结合同（10.4 决策 1–24、10.6 验收矩阵）交付窄切片：chat pre-answer 本地 RAG 检索与生成的协作式取消。实现提交 `db0404b`（后端核心）、`cb613d5`（检索层贯穿）、`be199cb`（前端 UX），分支 `codex/g16-privacy-truth-hotfix`。

**合同落实对照：**

- **决策 2（耗时准备前持久化）**：`start_turn` 在 `acquire_chat_operation` 之后立即落 pending 裸行（含客户端 turn_id + operation_id 与 retry 父链）；route/pedagogy/RAG/web 全部准备在 reservation 之后进行。
- **决策 2/5/6（单一 owner + 终态区分 + 单调 fence）**：schema v20 为 `chat_turns` 增加 `cancel_requested_at / cancel_stage / cancel_reason`；`finish_turn_cancel` 以 `(turn_id, operation_id)` CAS 落 `cancelled`（无可见输出）或 `interrupted`（保留 partial），同事务释放 thread operation；accepted cancel 后所有 worker 写路径（streaming 推进、audit 回写、complete、前端 commit fallback）被 `cancel_requested_at IS NULL` fence 拒绝；completed 先原子提交时取消返回 `already_completed`。
- **决策 4/9（checkpoint + 协作式）**：preparation 设 route → pedagogy_evaluate → retrieval → web_tools 四个 checkpoint；generate 前后各设 fence（模型调用自然返回后输出丢弃，不承诺强杀）；检索层新增 `RetrievalCancelled`，在 retrieval entry / before index load / before search / before rewrite / coverage entry / coverage facet / search entry / post-search 八处检查并穿透 broad except。
- **决策 7/20（统一接口 + 身份 CAS）**：`/chat` 与 `/chat/stream` 共享同一取消语义；官方客户端预分配 cryptographically random `operation_id`；`POST /chat/turns/{id}/cancel` 只确认登记（pre-reservation 有界等待 2s，沿用 WebLookup 先例）；`GET /chat/turns/{id}/status` 提供 durable 终态轮询。
- **决策 8（恢复语义）**：continuation 经 `reassign_chat_turn_operation` 转移 operation 并清除旧取消标记（不继承）；cancelled turn 不可 continuation，retry 创建新 child turn + 新 operation + 全新检索；supersede CAS 接受 cancelled。
- **决策 11（最小持久化）**：只存 cancel timestamps/stage/reason；延迟可由 requested_at 与 updated_at 派生；未采用正文不入库。
- **决策 12（明确 UI）**：状态行置于 turn bubble 内（非仅 toast），`role=status`、文本区分 提交中/停止中/慢收尾/cancelled/interrupted/already completed/请求失败，窄屏样式降级可读；浏览器 abort 不再显示"已停止"。
- **决策 13（服务端唯一 writer）**：前端 `commitTurn` 调用整体移除并由 packaging guard + boundary test 双重禁止；基础 ChatService 与 ExternalDataPolicyChatService 共享 reservation/checkpoint/settlement shell（helper 复用，policy 仅覆写 policy 门与 audit）。
- **决策 14（兼容边界）**：未提供 handle 的 legacy 同步请求不可中途取消，前端退回 abort-only，服务端断连 settlement 兜底，不伪装兼容。
- **崩溃恢复**：`recover_stale_chat_operations` 对已登记取消的 stale turn 落 `cancelled`/`interrupted`（按是否有 partial），stage=`recovery`。

**自动化证据：**

- `.venv\Scripts\python.exe -m pytest -q`：**1078 passed**（基线 1051 + 新增 27 个 G12 测试：repository 取消原语 6、fence/race 3、start_turn checkpoint 2、reservation 2、continuation 清标记 1、stale recovery 2、双 service 共享语义 2、并发慢检索 1、检索层贯穿 3、consumer regression 3、API/路由经既有 stream cancellation 测试回归）。
- `npm test`（frontend）：**88 files / 337 tests passed**（新增 cancelled SSE settle 测试；stop 行为测试改写为 cancel+poll 语义；boundary/packaging guard 更新为"commitTurn 全面禁止 + cancelChatTurn 必须在 controller"）。
- `npm run build`：通过（仅保留既有 >500 kB bundle warning）；`tsc -b` 通过。
- `ruff check .`：通过；mypy baseline：current 122 / new 0。

**遗留边界（后续切片，不在本门内）：**

- `archive_after_cancel` 持久归档队列（决策 10/15 的会话切换等待与归档失败 UI）尚未实现——当前取消后 thread operation 已释放，会话切换/新建不被阻塞，但"归档失败独立错误"文案依赖该队列落地。
- 慢检索实测上限的人工时序记录（desktop/narrow/mobile viewport 验证）属人工门，待真实设备验收批次执行。

### 10.10 G12 交付收口与归档队列（2026-08-22）

- **修复迭代**：turn 状态行初版按 `message.turnStatus` 渲染，导致历史 completed 消息永久显示取消文案（Playwright strict-mode 冲突 + 违反决策 12"浏览器 abort 不显示已停止"）。改为独立 `ChatMessage.cancelNotice` 字段，仅协作取消流程写入；恢复历史与普通断线永不渲染。
- **恢复卡保持**：onCancelled 不再清空 streamRecovery——取消 settle 后的 retry 正是决策 8 的新 operation 全新检索路径。
- **归档队列落地（决策 10/15）**：schema v21 增加 `chat_threads.archive_after_cancel_operation_id`（绑定 operation，stale marker 无法误触发）；POST archive 在已接受取消时持久化排队而非失败；DELETE `/sessions/{id}/archive-queue` 支持取消待归档；exactly-once 消费（pop CAS + readiness 检查）；启动扫描（get_session_service 首次构造）+ stream finally + turn-status 轮询三处触发执行；前端 queued 响应允许立即切换/新建会话，归档失败保留会话并显示独立错误。
- **交付基线**：`main` = `8a2f91ae6b1fb048b5415702ec71ca2393679479`，本地与远程一致；[CI #32573043290](https://github.com/2002yy/study-agent/actions/runs/32573043290) 全绿（pytest、RAG K1、ruff、detect-secrets、mypy baseline、前端测试/构建、Golden Journeys 与 real-stack browser gates）。
- **门状态：G12 自动门 CLOSED。剩余人工与时序门**（10.6）：点击后 200 ms 实测记录、慢检索登记→终态实测上限、desktop/narrow/mobile viewport 人工验证——待真实设备验收批次执行。

### 10.11 G12 人工与时序门闭合（2026-08-22，浏览器自动化真实栈证据）

执行方式：Playwright 真实 Chrome 对本地真实栈（专用测试 server + 真实 SQLite），全程读取服务端 durable 终态，无 mock sleep、无以浏览器 abort 冒充服务端终态。完整数据与方法见 [`G12_ACCEPTANCE.md`](G12_ACCEPTANCE.md)。

- **200ms UI 确认（决策 4）**：desktop 113ms / narrow landscape 127ms / mobile 130ms，全部 <200ms；多轮稳态复核无离群。
- **慢检索登记→终态实测（决策 4/9）**：注入 3s 慢检索后，登记→durable cancelled 实测 2963–2994ms（checkpoint=web_tools）——协作开销 ≈0，终态无可见输出、operation 锁同事务释放。
- **三 viewport 文案与 aria（决策 12）**：bubble 内状态行 `role=status` + `aria-live=polite`，固定文案集命中，截图/视频存证于 `frontend/test-results/g12-artifacts/`。
- **离开会话 / 等待归档 / 取消归档（决策 10/15）**：取消 pending 时 composer 即时可用、新会话可建；archive 排队持久化并在 settle 后自动执行（三 viewport）；DELETE archive-queue 清 marker 后 settle 不再归档。
- **资产**：`playwright.g12-acceptance.config.ts` + `e2e/g12-acceptance.spec.ts`（六旅程 A–F）+ 测试 server 注入端点；复现入口 `npm run test:e2e:g12`。
- **仍属人工批次**：真实屏幕阅读器体验、实体手机、视觉对比度评审——沿用既有边界，归 G17 人工验收。

## 11. DR1 深度调研（DeepResearch）冻结合同（2026-08-22 Grill，决策 1–16）

> 历史实现提交使用 `G18 DeepResearch` 标签；为避免与既有 G18 React/Streamlit 迁移编号冲突，当前 owner 统一称为 **DR1**，不改写历史提交信息。

背景：现有联网调研的三条实证痛点——太浅就断、读得太少、不会追问。目标对标 ChatGPT Deep Research 的中度深研形态。Grill 已闭合，16 条决策冻结如下；实施排期插队 G14 前。

### 11.1 冻结决策

1. **场景范围：**学习调研、时事研究、决策支持、技术溯源四类全覆盖。
2. **痛点基线：**太浅就断、读得太少、不会追问（用户实证确认，非架构推断）。
3. **量级：**中度深研——子问题分解 + 3–5 轮迭代 + 10–20 页阅读，单次 3–8 分钟。
4. **触发：**自动升级（LLM 复杂度预判）+ 用户可调灵敏度开关（设置项，默认保守）。
5. **预算：**质量优先——单次数万 token、3–10 分钟可接受。
6. **Durable 承载：**扩展 WebLookupRun，不新建实体；新增阶段 `planning → [searching→reading→noting]×N → synthesizing`；笔记总量上限 64KB 防 checkpoint 膨胀；G12 取消语义直接适用。
7. **上下文经济：**双层结构——逐页结构化笔记（事实+出处）+ 全局滚动研究备忘录。
8. **进度可视化：**步骤日志流（每轮搜了什么/读了哪页/发现了什么），扩展 G12 决策 12 状态体系。
9. **分解策略：**初始计划 + 允许中途插入新子问题（发现新线索时）。
10. **真值边界：**仅证据链，不写 LearningTruth（SourceEvidence 合同风险归零）。
11. **交付形态：**增强版回答——引用内嵌，不强制分节。
12. **运行中转向：**输入框即入口（深研期间发送的消息自动成为研究方向注入）；轮边界生效；steering 是绑定活动 run 的元数据注入（`research_context.steering[]`），不创建 turn、不排队——**修订 G12 决策 10** 为："同会话新问题（创建新 ChatTurn 的请求）仍须等待 operation 终态；转向消息是元数据注入例外"。合成阶段到达的 steering 标记 late 留档不生效。
13. **外发审计：**受 steering 影响的 web_search 条目加 `influenced_by_steering: true` 标记（steering 文本本身不直接外发，不伪造新 purpose）。
14. **部分产出：**中断/取消保留已收集笔记，可查证据链。
15. **轮次失败：**换查询变体重试一次，仍败则跳过该子问题续跑，报告如实标注缺口。
16. **新闻管线：**远期统一到底层研究引擎，本轮不动。

### 11.2 明确拒绝的替代方案

- 拒绝新建 DeepResearchRun 第二实体（operation/CAS/checkpoint/取消链路重复实现，违反单一 owner）。
- 拒绝 steering 创建轻量 turn（触碰 add_chat_turn 校验、recovery、supersede、export 过滤等多处消费者）。
- 拒绝伪造 `purpose=research_steering` 审计条目（steering 文本不直接外发，真实越界的是 web_search 调用）。
- 拒绝即时中断式 steering（浪费已发起调用；轮边界语义简单且足够响应）。
- 拒绝强制分节报告模板（交付形态由问题类型自然决定）。

### 11.3 验收门草案

- 自动升级判定有灵敏度开关且默认保守；简单问题的回归路径不受影响（不进深研管线）。
- 深研全程可取消（G12 语义直接复用）；steering 在下一轮计划修订中生效并有步骤日志记录。
- 中断/取消后笔记保留且证据链可查；部分产出不伪装为完整结论。
- 步骤日志流三 viewport（desktop/narrow/mobile）验收；外发审计含 influenced_by_steering 标记且无正文落库。
- 单次深研轮数 ≤5、阅读 ≤20 页、时长 ≤10 分钟硬上限；超限按预算截断并如实标注。

### 11.4 GO / NO-GO

- **DR1 合同冻结：COMPLETE。** 触发、预算、承载、上下文经济、可视化、分解、转向、审计、失败语义、交付形态全部冻结。
- **DR1 implementation：GO / COMPLETE。** WebLookupRun 多轮管线、步骤日志、steering、敏感度设置与 G12 取消复用已交付 main。

## 12. G14 临时附件冻结合同（2026-08-23 Grill，决策 1–16 + 验收门 v2）

背景：G14 现状 PARTIAL(P1)——长期资料入库已有 server-owned RagRun 与删除/重建确认，缺"当前会话临时附件"完整生命周期。Grill 已闭合，以下决策与验收门冻结；实施排期紧随本节，插队后续产品切片。

### 12.1 冻结决策

1. **类型：**第一版 PDF/DOCX/TXT/MD 文本类 + 图片（JPEG/PNG/GIF/WebP）。
2. **生命周期：**随会话存活——用户显式删除单附件、或会话归档/删除成功后清理；刷新/重启不影响。
3. **可见范围：**thread 内可见——同 thread 的 continuation/retry 可检索，新会话不可见。
4. **转正：**一键转正走 RagWriteRun 正式入长期库；复制模式（临时副本保留至会话结束）；重复转正幂等去重。
5. **上限：**每会话 ≤10 个、单文件 ≤20MiB。
6. **图片理解：**DeepSeek `deepseek-v4-flash-vision-exp`（用户现有 DEEPSEEK_API_KEY）；**默认关闭**，设置里显式开启后才将图片发往云端生成描述；每次调用记 external_call purpose=`image_description` provider=deepseek data_categories=[image_content]。
7. **索引隔离：**共享临时索引库 + thread_id 强制过滤（不复用长期 rag_index；检索时 thread 过滤为硬条件）。
8. **embedding：**沿用现状 fail-closed——cloud_context_policy 允许时用配置 provider，否则关键词+本地向量，远程阶段记 blocked_by_policy。
9. **失败语义：**单文件解析失败→换变体重试一次→仍败标 failed 并可手动重试；不阻塞其余文件提问。
10. **引用展示：**进 EvidenceTrail 标注文件名+位置；附件优先于长期资料排序；问题无关时不得强行引用附件。
11. **运行中上传：**新附件仅对"就绪"之后的提问可见（ready 才可召回），当前正在生成的回答不含它。
12. **重名处理：**允许同名文件多份独立管理；检索去重按内容哈希。

### 12.2 验收门 v2（Grill 中对草案的修订已并入）

1. **每文件状态机：**parsing→chunking→indexing→ready|failed 独立可见可重试；步骤日志按文件展示（对齐决策 12 状态体系）；失败文件的片段绝不进入提问上下文。
2. **thread 内命中：**召回时 EvidenceTrail 标注文件名+页码/位置；排序优先于长期资料；无关问题不强行引用。
3. **删除时序（关键修订）：**附件清除绑定「归档/删除成功之后」执行（兼容 G12 归档队列——排队归档的会话其附件在真正归档落盘时删除）；DB 记录与磁盘文件双重验证；归档失败则会话保留时附件一并保留。
4. **手动删除：**单附件删除入口即时生效（索引+文件同步清）。
5. **转正幂等：**一键转正走 RagWriteRun；内容哈希去重防重复入库；复制模式下临时副本随会话结束清理。
6. **双层 fail-closed：**文本 embedding 跟随 cloud_context_policy；图片 vision 受独立开关（默认关）控制，开启后逐次记录 image_description 外发。
7. **ready 才可召回：**处理中附件对任何提问不可见。
8. **重名独立：**同名文件允许多份，检索去重按内容哈希。

### 12.3 明确拒绝的替代方案

- 拒绝复用长期 rag_index 加过滤字段冒充临时生命周期（物理混存使"结束删除"不可验证）。
- 拒绝批次回滚式失败语义（一个坏文件拖垮整批上传）。
- 拒绝归档点击即删附件的时序（归档队列下会丢失"失败保留"保证）。
- 拒绝图片默认上云描述（正文离机必须显式授权 + 逐次审计）。

### 12.4 GO / NO-GO

- **G14 合同冻结：COMPLETE。实施：GO / COMPLETE。**
- owner、终态与授权合同已由 12.5 的实现和门禁证据闭合。

### 12.5 交付证据（2026-08-23）

- `f4fec33` 合同冻结 → `b4c5ade` G14-a/b（schema v22 `session_attachments` 表、CAS 状态迁移仓储、上传/解析/分块/索引/失败管线、自动重试一次+手动重试、thread 过滤检索、删除/清理/幂等转正）→ `68ec561` G14-c（deepseek-v4-flash-vision-exp 描述管线，独立开关默认关，逐次 image_description 审计）→ `4240707` G14-d1（REST 适配器，404/409/413/400 映射）→ `27b065a` G14-d2（资料面板内本会话附件区：每文件状态徽章+步骤日志+重试/转正/删除；设置面板 vision 开关）→ `c761052` G14-e（chat 检索附件优先合并+provenance 快照、归档成功后才清理且失败不回滚归档）。
- 验证：后端 pytest 1081 全过（含 17 个 G14 专项测试覆盖验收门 1/3/4/5/7/8）；前端 vitest 337 全过 + tsc 干净；ruff 全过；mypy 基线无新增（122≤128）；CI #32645814002 success。
- 验收门对照：①每文件状态机✅（stage_history 落库可展开）；②thread 内命中+文件名标注+优先排序✅；③清理绑定归档成功之后✅（archive_session 为唯一汇聚点，兼容 G12 归档队列与启动扫描）；④手动删除即时生效✅；⑤转正幂等（规范化文本哈希去重）✅；⑥双层 fail-closed✅；⑦仅 ready 可召回✅（failed 片段永不入索引）；⑧重名独立+内容去重✅。
## 13. G16 按会话记忆 ask 冻结合同（2026-08-23 Grill，决策 1–14 + 验收门 v2）

背景：跨会话记忆（read_memory_bundle）目前只受 cloud_context_policy==allow_local_evidence 一个门控制，设为 allow 即静默进入每次回答。memory_mode 只管写入不管读取。本合同补上记忆读取的显式授权控制。

### 13.1 冻结决策

1. **策略形态：**独立三档 `memory_policy: off / ask / auto`，默认 auto，位于外发数据面板；与 cloud_context_policy 解耦。
2. **ask 粒度：**会话级一次——新会话首问前确认，同意后本会话内不再询问。
3. **范围：**read_memory_bundle 全部内容（learner_profile、跨会话 summary 等）；本会话自身 learning_state/历史属于本轮上下文不算记忆；范围仅单聊（群聊不读记忆）。
4. **默认值：**auto——升级无感，维持现状行为。
5. **确认 UI：**window.confirm 弹窗，与联网 ask 同模式；仅当「ask + 会话未授权 + bundle 非空（memoryStatus.files 判定）」时出现。
6. **技术路径：**前端 confirm 同意 → 请求携带 MEMORY_CONSENT_MARKER → 后端 CAS 写入 ChatThread.settings_snapshot → 本会话后续轮次后端自读快照放行。
7. **CAS 失败语义：**落库写失败 = 当轮 fail-closed 拒绝（declined），下一问重试。
8. **拒绝/off：**无记忆继续正常回答，不阻塞。
9. **AND 双门：**需 memory_policy 放行 且 cloud_context_policy==allow_local_evidence 才进记忆；非 allow 档即使 auto 也无记忆。
10. **审计：**external_data_execution 新增顶层字段 `memory_consent ∈ {granted, declined, not_required}`；answer_data_categories 粒度不变；键缺失解释为机制上线前的历史轮次，不升 external_data_audit_version。
11. **撤销：**ask+granted 时输入区上方显示可撤销徽章；点击调用 revoke 端点 CAS 清除授权并记 revoked_at；立即生效（本轮起无记忆），下次首问重新确认。
12. **会话恢复：**session detail payload 暴露 memory_consent_granted 状态；已授权会话刷新/重启/切回后不再询问且记忆生效。
13. **记录边界：**仅 ask 的同意产生授权记录；auto/off 不落库。
14. **显式声明：**本合同不改变"记忆内容随回答发给所配置 LLM provider"的既有事实（默认 auto 维持现状），只增加可控性。

### 13.2 审计记录

两轮复审共修复 7 个问题：
- 🔴 会话恢复后前端无法判定是否弹 confirm → 决策 12（detail 暴露状态）；
- 🔴 settings_snapshot 整包覆写并发风险 → 决策 6/11 强制专用 CAS 方法；
- 🟡 declined 布尔塞类别列表破坏语义 → 决策 10（顶层三态字段）;
- 🟡 撤销语义不完整 → 决策 11（立即生效 + revoked_at + 再问）；
- 🟡 bundle 为空时询问无意义 → 决策 5（非空才问）；
- 🟡 marker 落库失败当轮归属 → 决策 7（fail-closed）；
- ✅ retry 被拒轮次自然重新确认（快照无授权），无需机制。
波及面验证：decide_external_data 仅 policy_chat_service 一个生产调用方；群聊不读记忆。

### 13.3 验收门 v2

1. 三档设置默认 auto，升级用户行为不变（门②）。
2. off = 任何上下文档位 bundle 都不进上下文。
3. ask 未授权会话：首问 confirm（bundle 非空时）；同意后会话内静默且持久化到 thread 快照。
4. 被拒本轮无记忆继续且审计记 declined；下一问再次询问。
5. AND 双门：cloud_context_policy 非 allow 时即使 auto 也无记忆。
6. 审计新增 memory_consent 三态字段，其余粒度不变。
7. 会话恢复（刷新/重启/切换）：已授权免问且生效；未授权再次首问仍询问。
8. 撤销徽章：点击即 CAS 清除、立即生效、下次首问再问。
9. 归档随 settings_snapshot 自然处理，无特殊清理。

### 13.4 GO / NO-GO

- **合同冻结：COMPLETE。实施：GO / COMPLETE。**
- 三档策略、CAS 授权/撤销、恢复与审计合同已由 13.5 的实现和门禁证据闭合。
### 13.5 交付证据（2026-08-23）

- `375a2dd` 合同冻结 → `4b64529` 实施：三档 memory_policy（helpers 默认 auto）、decide_external_data 双门、grant/revoke CAS（json_set 只动 consent 键）、acquire_chat_operation 改 json_patch 合并（修复整包覆写吞掉授权键的真实缺陷——即审计警告的并发问题在生产代码中的具体形态）、policy chat 逐轮解析授权 + marker 首次落库 + CAS 失败 fail-closed、external_data_execution.memory_consent 三态审计、revoke 端点、前端 confirm（仅 ask+非空+未授权时出现，向后端 detail 权威校验以满足恢复免问）、可撤销徽章。
- 验证：后端 pytest 1090 全过（含 9 个 G16 测试覆盖验收门 1–9）；前端 vitest 338 全过 + tsc 干净；ruff 全过；mypy 基线无新增（122≤128）；CI #32651981365 success。

## 14. G10 follow-up inheritance 冻结合同（2026-08-25，决策 1–15）

### 14.1 Grill 起点代码事实（实施前）

- `WebLookupRun` 已拥有 query、context、attempts、selected/rejected sources、read notes、预算、operation CAS、cancel/retry/resume 和 DR1 steering，但没有 `parent_run_id/root_run_id/lineage_depth`。
- retry/resume 原地继续同一个 Run；普通新查询创建独立 Run，API 只接受 query/max_items。
- owner 目前只存在于 `research_context.owner` JSON；仓储可按 owner turn 查询，不能按 thread 获取可继承的上一 Run。
- continuation/retry 会冻结原 ChatTurn 的 ResearchRun evidence owner，禁止客户端切换到另一个 Run；follow-up 因此必须是新 ChatTurn + 新 child Run，不能冒充 retry。
- `research_sources_snapshot` 已提供不含正文/query 的安全来源投影；当前 source freshness 只有 `reported/unknown`，不能直接证明旧内容仍然有效。

### 14.2 已确认决策（1–5）

1. **Durable identity：**follow-up 创建新 child `WebLookupRun`，记录 `parent_run_id + root_run_id`；父 Run 与历史完成时间不改写。
2. **触发：**系统只做相关性提示，用户确认后才继承；不得静默把同 thread 的任意下一问挂到旧研究。
3. **继承范围：**只继承来源 identity/URL/assessment 与有界结构化笔记；不直接把旧 `source_block`/网页正文当成当前事实，使用前重新检查相关性与新鲜度，必要时重读。
4. **预算：**child Run 获得独立完整预算；对继承来源的重新读取计入 child 的 read/time/token 预算。
5. **非完整父 Run：**completed/partial 可作为继承候选；failed/cancelled 只能继承已持久 checkpoint 的来源/笔记并要求明确确认，不得把失败候选升级为可信来源。

### 14.3 已确认决策（6–10）

6. **Active parent：**pending/running 父 Run 不创建 child，相关追加继续使用既有 steering；只有 terminal 父 Run 才进入 follow-up 候选。
7. **Lineage 生命周期：**v1 仅允许同一 active thread 内创建 child；thread 归档后 lineage 保留只读审计，但不得再从归档 thread 创建 child；父子 Run 不级联删除。
8. **候选与重新验证：**候选由本地确定性实体/token overlap 产生，选择同 thread 最近的 terminal Run；继承来源初始一律是 `inherited_candidate`，只有在 child 中重新搜索/读取成功后才能引用，过期或不可用来源进入 rejected/stale。
9. **Root 成本：**每个 child 仍有完整独立预算；root 额外累计 search/read/elapsed/child_count 供 UI 与审计展示。异常安全上限为 20 个 descendants，达到上限后只能创建新 root，不静默截断单个 child 的预算。
10. **UI 与 EvidenceTrail：**明确显示 parent research，并区分 `inherited candidate / revalidated / new / invalid or rejected`；回答只允许引用 revalidated 与 new 来源，不得把候选状态伪装为已验证证据。

### 14.4 已确认决策（11–15）

11. **Server authority：**`owner_thread_id / parent_run_id / root_run_id / lineage_depth` 是数据库显式字段并建立索引；客户端只提交精确 parent id 与新 query，不得提交继承 evidence，服务端验证同 active thread、terminal parent、归档状态与 descendant 上限并构造安全 seed。
12. **重新验证成功：**fresh search 命中相同 canonical URL 只验证来源 identity 与当前摘要；只有 child 中 direct read 成功，旧 read-note/fact 才能进入回答上下文。read 失败则进入 stale/rejected，旧事实不可引用。
13. **有界笔记与审计：**仅继承成功 read 产生的结构化 notes，最多 8 条、每条 1000 字符、总计 8 KB；不复制 steering、query attempts、provider payload 或失败读取内容。模型外发仍归既有 `web_results` 类别，EvidenceTrail/provenance 另记 inherited/revalidated/new 数量与来源。
14. **候选提示降级：**输入停顿或发送前仅做本地确定性候选检查，不调用外部 embedding；检查失败、超时或用户忽略时正常创建独立 root，不阻塞消息发送，并记录 suggestion unavailable。
15. **确认钉死与幂等：**用户确认钉死精确 `parent_run_id`，服务端不得替换为更新候选；创建请求携带幂等 request id，重复提交返回同一 child。parent 已失效时明确失败，允许重新选择或创建 root。

### 14.5 最后一轮覆盖复审

- **Owner：CLOSED。** parent/root/thread lineage 与 child 构造均归数据库和服务端；客户端不拥有继承 evidence。
- **状态与竞态：CLOSED。** active parent 只 steering；terminal parent 才可派生；确认钉死 parent；重复创建幂等；parent 失效不静默换绑。
- **事实与隐私：CLOSED。** inherited candidate 不是可引用事实；旧 facts 只有 direct re-read 后才恢复；外发仍受既有 `web_results` policy/audit 门约束。
- **生命周期：CLOSED。** v1 同 active thread；归档后 lineage 只读；父子不级联删除；20 descendants 后新建 root。
- **成本与失败：CLOSED。** child 独立完整预算，root 只累计展示；候选提示是非阻塞增强路径；stale/read failure 不污染回答。
- **UI 真值：CLOSED。** parent 与 inherited candidate/revalidated/new/rejected 分层显示；不得把 unknown/stale 显示为未使用或已验证。
- **Grill coverage：COMPLETE。** 未发现仍需用户选择的 API、状态机、恢复、授权或验收分叉。

### 14.6 验收门 v1

1. schema 迁移保留旧 Run；旧记录成为 root，lineage depth 为 0，不伪造 thread owner。
2. 只有同一 active thread 的 terminal Run 可创建 child；pending/running、归档 thread、跨 thread 与超过 20 descendants 均 fail-closed。
3. child 创建由服务端派生安全 seed；客户端无法注入 inherited sources/notes；幂等重试返回同一 child。
4. 候选计算完全本地、确定性且不发起 external embedding；不可用时聊天/独立 root 仍可继续。
5. inherited source 初态为 candidate；fresh search + direct read 成功后才成为 revalidated 并可进入 source block；失败来源不可引用。
6. notes 上限 8 条、单条 1000 字符、总计 8 KB，且 steering/query attempts/provider payload/失败读取正文不进入 seed。
7. child 保持独立 search/read/time/token 预算；root aggregate 正确累计 search/read/elapsed/child_count，但不反向截断 child。
8. API/UI 明示 parent research、候选确认与四类 evidence 状态；用户忽略/提示失败时不阻塞独立研究。
9. EvidenceTrail/provenance 能区分 inherited/revalidated/new/rejected；模型外发审计仍为 `web_results`，不新增含义重复的数据类别。
10. archive/recovery/retry/cancel 回归不改变既有 G12/DR1 真值与 owner 约束。

### 14.7 GO / NO-GO

- **合同冻结：COMPLETE。Implementation / delivery：GO / COMPLETE。** 14.6 的自动验收与远程交付门均已闭合。

### 14.8 本地交付证据（2026-08-25）

- schema v23 增加显式 `owner_thread_id / parent_run_id / root_run_id / lineage_depth / create_request_id` 与查询/幂等索引；迁移将 legacy Run 保留为 depth 0 root，只从已有且有效的 JSON owner 回填 thread，不制造 owner。
- `WebLookupRepository.create_child` 在单个 `BEGIN IMMEDIATE` 内验证 active thread、精确 parent、terminal 状态、同 thread、checkpoint、20 descendants 与 request id 幂等；客户端不能提交 inherited evidence。
- 本地 token/CJK bigram overlap 候选不调用 gateway/embedding；相关 active Run 返回 steering 要求，terminal Run 经确认后才创建 child；提示不可用或拒绝时显式降级独立 root。
- 安全 seed 只含来源 identity/assessment 与成功 read 的有界结构化 notes（8 条、单条 1000 字符、总计 8 KB）；fresh canonical URL 命中后仍须 direct read 成功才转为 `revalidated`，失败进入 rejected 且旧 facts 不进 source block。
- API/恢复卡展示 parent、root 累计 search/read/elapsed/child_count 以及 inherited candidate/revalidated/new/invalid-or-rejected；EvidenceSnapshot selection reason 同步保留 lineage 状态，外发类别仍为既有 `web_results`。
- 门禁：最终新增专项 8/8、G10/G12 owner 与恢复相关 19/19；最终修改前全量后端 1135/1135，steering/API 补丁后相关回归 19/19；前端最终全量 342/342、TypeScript 与 production build 通过；Ruff 全仓通过；mypy 122/128 且本批新增 0；RAG K1 baseline 通过；detect-secrets 0 finding files；`git diff --check` 通过。

### 14.9 远程交付证据（2026-08-25）

- 实现提交 `dd93fdabaa6f5f2637ef4f03604f43f91a1725c4` 已推送 `main`；推送后本地与 `origin/main` 为 `0/0`。
- [CI #32761262084 attempt 2](https://github.com/2002yy/study-agent/actions/runs/32761262084) 完整全绿：pytest、RAG K1、Ruff、package helper、detect-secrets、expanded mypy baseline、前端测试/构建、browser Golden Journeys 与 real-stack browser gates 均实际运行并通过。
- attempt 1 仅在 narrow Chromium 的既有 complex-content 旅程出现一次 `linkRectCount=0`，其余 52/53 Golden Journeys 与本批 G10 evidence 旅程均通过；未改代码直接重跑后完整通过，因此记录为未复现的浏览器时序偶发，不用无依据产品补丁掩盖。
- **G10 最终结论：GO / COMPLETE。** 截至该次交付，下一推进门曾为 G17 人工可访问性验收；2026-08-26 的 RQ1 真实反例与新路线见第 15 节。

## 15. SX1 / RQ1 / G17-LAN 冻结合同与新路线（2026-08-26 Grill，决策 1–58）

### 15.1 触发本轮复审的真实证据

- 实测 Run `web_lookup_1769bff566594e7d91bbac20f389b687` 的用户问题为“请联网研究：opus5”，但走的是 `standard / chat_tool_loop`，只执行一次 `web_search(max_results=5)`。
- 5 个候选均来自中文二手页面，含跨站转载和同源内容；没有 Anthropic 官方来源，实际独立内容家族约 3 个。
- `read_summary` 为 `attempted=0 / successful=0`，候选却全部以 `validated_tool_evidence` 进入综合；最终回答对发布日期、价格和能力给出确定性判断。
- 后端即时预览和前端 EvidenceTrail 另有前三条展示上限。因此用户看到的“3”既是 UI 截断，也掩盖了实际只有 5 个候选、零正文读取、来源不独立的问题。
- 结论：这不是单纯的展示数量缺陷。当前快速路径违反 candidate/read truth、研究意图触发和强结论证据门，正式研究质量判定为 `NO-GO`。

### 15.2 SX1 与 G17-LAN 冻结决策（1–29）

1. 仓库纳入最小 SearXNG Compose 与安全配置基线，镜像固定到 digest；公开拓扑归仓库，机器 secret/proxy 使用 ignored layering。
2. SearXNG secret 保存在 ignored 本地文件；变更前同目录时间戳备份，不自动轮换。
3. 禁止自动更新镜像；升级必须显式执行备份、candidate 测试并提交新 digest。
4. candidate 先在 `127.0.0.1:18080` 验证，再切换 `8080`；旧容器停止保留 7 天以便回滚。
5. 基线只包含单个 SearXNG，不引入 Valkey、公共 limiter 或 image proxy。
6. LAN 验收使用 production build 和绑定选定私有 IPv4 的专用 gateway；后端与 SearXNG 保持 loopback；长期 API token 只由 gateway 持有，绝不进入手机。
7. 只允许 Windows `Private` 网络，并为精确手机 IP 创建临时防火墙规则。
8. LAN session 默认 90 分钟，只允许一次显式延长；Ctrl+C、超时和异常均触发清理。
9. 原“真实数据库 + 专用 G17 thread”提案已由决策 26 替代；不得把 acceptance 写入生产学习真值。
10. 正式证据包含 machine-readable manifest 与人工 P/F/N/A；实体手机、真实屏幕阅读器和视觉对比度记录齐全前，G17 不得 GO。
11. 可信 Private LAN 上只使用 HTTP，但必须显式提示明文风险；Public 网络 fail-closed，不引入 HTTPS/tunnel。
12. 防火墙和会话绑定精确手机 IP；地址变化立即失效并要求重新授权，不回退子网范围。
13. 防火墙规则以 acceptance session 命名；正常退出清理，每次启动先清理本工具遗留规则，监听器身份不符即失败关闭。
14. raw JSON 可在 ignored artifact 中保存精确私有 IP；可提交 Markdown 必须清除 IP、SSID、MAC、token、secret 和 proxy。
15. Private 网络、物理适配器/IP、防火墙、production build、gateway 或 backend identity 任一失败均 fail-closed。SearXNG 上游 CAPTCHA/限流可降级，但搜索验收项为 BLOCKED/FAIL，G17 不能 GO。
16. 只通过窄权限 elevated firewall watchdog 触发一次 UAC；应用、gateway 和 backend 保持非管理员运行。
17. 精确 IP + 5 分钟单次随机码交换 `HttpOnly; SameSite=Strict` session cookie；随机码不进入 manifest。
18. 新建独立 `start-lan-acceptance.bat`；正常一键启动始终保持 loopback-only。
19. `docs/G17_ACCESSIBILITY_ACCEPTANCE.md` 负责流程与脱敏运行记录，并引用现有 `MOBILE_ACCEPTANCE_D4D.md`；`PROJECT_STATUS.md` 仍是唯一 GO/NO-GO owner。
20. 停止 LAN 不自动归档或删除 durable session；验收快照按 artifact policy 保留，不合并回生产。
21. 只接受物理 Private Wi-Fi/Ethernet RFC1918 地址；排除 Hyper-V、Docker、WSL、VPN 和 loopback。当前 WLAN 为 Public，启动条件不满足；脚本不得自动修改网络类别。
22. “重新授权同一手机”生成新随机码并使旧 cookie/session 失效，不延长原 TTL；QR 只在本机内存生成，不调用外部服务、不保存含码图片。
23. health/config/JSON/backend-connectivity 等确定性 candidate 故障自动回滚；第三方 CAPTCHA/限流不触发回滚循环。切换前至少一次有效搜索，旧容器 7 天后仍需显式删除。
24. raw artifacts 位于 ignored `artifacts/g17/<session-id>/`，默认保留 30 天；清理前预览精确路径、大小和脱敏记录存在性，并要求确认。
25. 如果无法证明 token 未到手机、精确物理 Private 单设备范围、TTL/listener/firewall 清理，或必须暴露 backend/SearXNG，则 LAN 保持 NO-GO；USB 转发、屏幕镜像或正式部署必须另行 Grill。
26. 使用 SQLite online backup，并复制本轮所需 RAG/附件目录到时间戳 acceptance snapshot；专用 acceptance backend 只操作快照，永不合并回生产。
27. 正式证据要求 tracked worktree clean、build SHA 等于 `HEAD`，manifest 记录 SHA 与 frontend artifact hash；dirty run 只能是 `NON-FORMAL / Decision: NO-GO`。allowlisted 无关 untracked 文件不阻塞。
28. gateway 正式预检必须覆盖 SSE 不缓冲、断连传播、取消 durable 终态、JSON、multipart、错误 header/status、大响应和超时；任一失败即正式 LAN NO-GO。
29. LAN operation/session 只有一个 controller owner；只停止它启动的 acceptance backend/gateway/firewall，不影响既有 desktop/SearXNG。睡眠、网络/profile/IP 或 watchdog 丢失时持久化 `interrupted`，关闭 listener、移除规则、保留 snapshot；恢复必须新建授权 session。

### 15.3 RQ1 有界研究质量冻结决策（30–58）

30. “研究/调查/验证/比较/综合分析”等明确意图自动进入有界研究层；快速事实查询保留快速路径，完整 DR1 深研仍是独立层。
31. 强事实原则上至少需要 1 个已读取一手来源和 2 个独立已读取佐证；无法取得一手来源时明确降级，不输出确定性结论。
32. 默认规划 3–5 个查询角度、最多 20 个候选、读取 5–8 页、约 40k 字符，45 秒软时限；范围按问题面与独立证据计算，不按 URL 数量凑数。
33. 回答至少包含结论、研究范围、逐项判断、证据、冲突、未知/限制、置信度和实际含义；重要主张可追溯到已读来源。
34. UI 显示查询/候选/已读/一手/独立佐证/淘汰计数；前三条只能作为“3/N”折叠预览，candidate/read/cited/failed 必须分开。“本次使用的来源”只用于已读且参与结论的页面。
35. 来源可信度按主张类型和证据角色判断：官方适合产品事实，可复现实测适合能力比较，独立报道适合事件佐证，社区内容只作线索/体验。
36. 通过 canonical URL、标题/正文指纹、原始出处和引用链识别内容家族；同源转载只算一次独立证据，副本只作访问备份。
37. 冲突按证据角色、日期、版本和方法解释；关键冲突无法解决时降低置信度并禁止确定性结论。
38. 回答标注截至日期；价格、可用性、当前产品线等易变事实须本轮实时读取，基准结果必须绑定版本、日期和方法。
39. 证据不足时返回部分研究，列明已确认、未确认、冲突和失败原因；不得用搜索摘要补足强结论。
40. 双门验收：确定性测试覆盖真值链路；至少 12 个真实联网案例覆盖多类来源与失败情形，真实性硬门全部通过且至少 10/12 获得人工“范围充分、分析有实质增量”。
41. 顺序冻结为 SX1 最小可复现基线 → RQ1 研究质量 → G17-LAN；禁止把三者合成大切片。
42. RQ1 是独立窄门，由本文件持有 GO/NO-GO；RQ1 未 GO 时 LAN 只能非正式调试，不能获得正式 G17 GO。
43. 规划、每次搜索/读取、去重、综合和补缺均设 cooperative checkpoint；ChatTurn 持有 `cancelled/interrupted` 终态，ResearchRun 只保留部分证据，不成为第二 owner，也不自动生成部分答案。
44. 45 秒后停止发起新查询/读取；在途单次调用受独立 timeout 约束，整轮 60 秒硬上限。超限只用已读证据返回部分研究，不能降级引用摘要。
45. 每次逻辑搜索记录授权、最小化查询、计划引擎和实际来源；网页读取与外部答案生成分别审计。无法证明的底层引擎显示 unknown，不伪造逐调用事实。
46. 真实案例的预期事实、必需来源、冲突点和评分规则不得进入研究提示词；独立评估器和人工在运行后评分，并保留 holdout。
47. 查询由需要证明的主张/问题面产生；首轮后只允许一次由明确证据缺口驱动的补充规划，并记录追加原因。
48. 官方身份通过可信域名注册表、交叉链接、canonical、发布者身份等验证；品牌词或搜索排名不能证明官方，证据不足显示“疑似官方/未验证”。
49. 首切只允许受限静态 HTTP(S) 读取：每次解析/重定向阻断私网和保留地址，限制大小、类型、解压比例和时间，剥离脚本/隐藏内容，并把网页指令视为不可信数据；动态浏览器另行安全切片。
50. 重要结论拆为原子主张，绑定短证据片段、来源角色和读取时间；独立蕴含检查失败时删除、降级为推断或标记未知。UI 可展开有限上下文。
51. 有界研究默认约 1500–3000 中文字符，但以内容覆盖为硬门：至少三个相关分析维度，并包含证据、反证/局限、冲突、未知和实际含义；不以重复内容凑字数。
52. 回答语言跟随用户，搜索语言跟随证据所在地；国际主题同时覆盖英文原始资料和中文资料，中国本地主题优先中文一手来源，翻译主张仍链接原文。
53. 程序拥有预算、抓取、去重和状态机；模型阶段化负责规划、证据提取和综合；引用验证独立执行。可复用同一已授权模型，但输入隔离、逐调用审计，综合阶段只见清洗后证据。
54. 只在缺一手来源、独立证据不足、关键冲突未解释或问题面无证据时触发唯一一次补充搜索；不得仅因数量不足盲目扩展。
55. 长期只保存 URL、元数据、读取时间、内容哈希、来源角色和有限证据片段；完整响应仅在 ignored 临时缓存保留 24 小时，不进入 Git、长期记忆或 RAG。
56. 缓存按 canonical URL、内容哈希、读取策略版本和时间建立，仅用于性能；易变事实必须重验。网页不得自动进入用户长期资料，只有用户显式“采纳为资料”才可写入。
57. 旧记录不伪造读取也不改写为 rejected；缺少正文读取证据时派生显示 `legacy candidate / 历史验证状态未知`。
58. GO 要求确定性真值/安全测试全过、12 个真实案例留存脱敏清单、真实性 12/12、质量至少 10/12、无摘要冒充/转载冒充/无绑定强结论/评估泄漏；取消 UI 200ms 确认，慢调用记录实测终止上限，逐调用授权审计与 45/60 秒预算可重复验证。任一真实性、安全或隐私硬门失败均为 NO-GO。

### 15.4 最终矛盾复审

- **DR1 与 RQ1：CLOSED。** DR1 保留 3–10 分钟、3–5 轮、10–20 页的完整深研；RQ1 是明确研究意图的 45/60 秒有界层；旧 12/20 秒路径只承担快速查询。三层预算和交付形态互不冒充。
- **Owner：CLOSED。** 两个研究层都扩展现有 WebLookupRun/ResearchRun 与 ChatTurn operation/CAS/cancellation 真值，不新增第二 run truth。
- **取消与部分证据：CLOSED。** DR1 和 RQ1 都可保留证据链；用户取消不自动生成部分答案，基础设施中断为 `interrupted`，与 G12 一致。
- **来源门与无官方主题：CLOSED。** 一手来源门在可验证一手材料存在时是硬门；不存在或不可访问时由决策 39 诚实降级，不以二手数量补齐。
- **时间与读取预算：CLOSED。** 5–8 次读取是上限范围，不保证凑满；45 秒停止扩展、60 秒硬收口优先。未达到证据门时返回部分研究。
- **存储与可审计性：CLOSED。** 有限短片段 + 内容哈希支持引用审计，完整网页仅临时保留；不把第三方网页自动注入长期 RAG。
- **隐私审计：CLOSED。** 应用、SearXNG engine provenance、网页读取和模型调用分层记录；底层事实不可见时为 unknown，不制造完整性假象。
- **G17 命名：CLOSED。** G17 继续只指首次使用/可访问性；历史 `G18 DeepResearch` 统一称 DR1；新质量门称 RQ1，SearXNG 可复现基线称 SX1。
- **历史 COMPLETE：REVISED, NOT ERASED。** 2026-08-12 的 CI 仍证明当时 provider、预算和基础 `found` 行为；它不再被解释为研究级正文证据/分析质量已完成。G9/G13 因真实反例重开为 PARTIAL。
- **Grill coverage：COMPLETE。** 1–58 已覆盖范围、非目标、身份、状态、取消、恢复、隐私、缓存、失败、兼容、UI 和验收，不剩需要实现者自行决定的高影响产品分叉。

### 15.5 冻结实施路线

1. **SX1（历史第一代码切片）：**纳入固定 digest 的最小 Compose/config 与 ignored secret layering；实现备份、`18080` candidate、有效搜索、切换、确定性回滚和 7 天保留；正常启动仍只复用 loopback SearXNG，不开放 LAN。
2. **RQ1-A / Pre-RQCE 语义止血：**禁止零正文读取候选成为 `validated_tool_evidence`；修正“本次使用的来源”和 `3/N` UI；legacy 显示 unknown/candidate；明确研究意图不再落入 snippet-only 强结论路径。该前置切片已交付，不回滚。
3. **Shared Research Quality Engine：**C1–C100 是 Quick / RQ1 bounded / DR1 deep 共用的 Claim/Evidence/Gap/Gate/Cluster/Budget/Trace/Audit 控制平面，不是第四条 research pipeline。旧 RQ1-B 不再单独造 engine，而作为共享引擎首个 production activation target 的 `bounded` preset；仍冻结 `<=20 candidates / 5–8 reads / 45s soft / 60s hard`。
4. **三级验收：**RQ1-C 的 12 个无泄漏真实案例决定 bounded preset 是否 GO；20 题 Shadow 诊断 Claim Engine 的 False Closure/Scheduler/Gate/Cost；50–60 Frozen + Live benchmark 决定完整 Research Quality / DR1 release。三者不互相替代。
5. **G17-LAN：**在 production snapshot、单设备 Private LAN、gateway token isolation、watchdog/firewall cleanup 和 raw/sanitized artifact 合同下实现；最后由实体手机、真实屏幕阅读器与对比度人工记录决定 G17 GO/NO-GO。
6. **明确延期：**动态浏览器读取、HTTPS/tunnel、公共或子网 LAN、自动镜像升级、Valkey/公共限流、USB/镜像替代验收、Android 产品化、GraphRAG 和长期画像写回均不进入上述切片。

### 15.6 当前门禁结论

- **Grill：GO / COMPLETE。** 可以按 15.5 开始实现，无需再补产品选择。
- **SX1 implementation：GO / COMPLETE。** 固定 digest、仓库 Compose/config、ignored secret/proxy、备份、`18080` candidate、切换、回滚路径和 retained-container guard 已实现并完成真实切换；实施提交 `1185b63` 已推送，匹配的远程 CI #32877392793 全绿。
- **RQ1：NO-GO / IMPLEMENTATION REQUIRED。** 真实 `opus5` Run 已证明 snippet-only 强结论与 UI 真值缺口。
- **G17-LAN：BLOCKED / AUDIT REQUIRED / Decision: NO-GO。** 当前 WLAN 为 Public，controller/gateway/snapshot/firewall 证据尚不存在；只能在 SX1 与 RQ1 GO 后推进正式验收。
- **当前执行入口：顶部 `Current Handoff` + 本文件最后一个 RQCE Stop report。** 历史章节中的旧“下一步”只保留时间语义，不得覆盖顶部 handoff。

### 15.7 SX1 本地实现证据（2026-08-26）

- 新增 `infra/searxng/compose.yml`，只包含单个 SearXNG 服务，固定 `docker.io/searxng/searxng@sha256:c2dc2d9e6b910653e8628361c23443222490e4cabbb9e02667b7847143db843b`；host port 严格绑定 `127.0.0.1`，没有 Valkey、公共 limiter 或 image proxy。
- `infra/searxng/settings.yml` 启用 HTML/JSON，关闭 debug/metrics/limiter/public-instance/image-proxy；secret 与既有容器代理被写入 ignored `.env.local`，已有 secret 不自动轮换。
- 迁移前将仓库外设置备份为 `D:\DockerDesktopData\searxng\settings.yml.backup-20260825T163030Z`；备份存在性已复核，原文件未被覆盖。
- 显式 upgrade 在 `127.0.0.1:18080` 创建隔离 candidate；exact image/config/loopback/secret 检查和 `/healthz` 通过，真实查询返回 10 条有效标题/URL 后才允许切换。
- 新 active `study-agent-searxng` 已在 `127.0.0.1:8080` 运行固定 digest，配置 mount 为仓库 `settings.yml:ro`，label 为 `sx1`；切换后的独立真实搜索再次返回 10 条结果。
- 旧 `searxng/searxng:latest` 容器已停止并保留为 `study-agent-searxng-retained-20260825T163036Z`；candidate 容器、网络和临时 volume 已删除。retained 删除要求精确名称、显式 `-ConfirmRemoval` 且满 7 天，脚本不提供提前删除旁路。
- 后端 provider probe 曾返回 `ready / valid_results_returned`；随后一键启动复验正确显示 SearXNG service `ready`，同时因 brave/duckduckgo/startpage/wikipedia 等上游超时将检索能力显示为 `degraded`。该波动没有触发镜像更新或错误回滚，符合第三方降级边界。
- 正常 `start-study-agent.ps1 -NoBrowser` 成功复用固定版本，显示后端、前端、SearXNG、检索状态和人工检查清单；普通启动不执行 pull/update。
- 门禁：SX1/搜索相关 pytest 24/24、全量后端 1141/1141、全量 Ruff、前端 Vitest 342/342、TypeScript production build、PowerShell parser、Compose config、现行文档链接与 `git diff --check` 通过；定向 detect-secrets 为 0 findings。对 retained 容器执行带确认的提前删除请求被 7 天门正确拒绝，容器仍存在且保持 stopped。

### 15.8 SX1 远程交付证据（2026-08-26）

- 实施提交：`1185b63ef6784d08046ca4244ee8ce751b549c39`（`feat: pin and manage local SearXNG`），已推送至 `origin/main`。
- 匹配的远程 [CI #32877392793](https://github.com/2002yy/study-agent/actions/runs/32877392793) 以同一 head SHA 完成，结论为 `success`；pytest、RAG K1、Ruff、package helper、detect-secrets、expanded mypy、前端 test/build、browser Golden Journeys 与 real-stack browser gates 均通过。
- 交付判断：**SX1 GO / COMPLETE。** 实施及其权威证据均已交付；后续提交/CI 的精确状态以 Git 与 GitHub Actions 为准，不在本文件建立自引用式追记链。
- 下一唯一切片（历史）：**RQ1-A 语义止血**——该切片已由 15.9 完成交付；当前下一步以顶部 handoff 为准。

### 15.9 RQ1-A 本地实施证据（2026-08-26）

- `web_search` 结果现在只形成 candidate；只有与本轮已发现公开 URL 对应、`ok=true` 且包含非空正文的 `web_read`，或独立结构化 GitHub API 证据，才能进入回答上下文、`used_sources` 和 ResearchRun `selected_sources`。搜索摘要不再进入模型联网上下文。
- chat tool trace、标准 ResearchRun 和 deep ResearchRun 在“有候选、零成功读取”时统一落为 `provider_status=candidates_only`、`stop_reason=search_candidates_only`、`answer_confidence=none`、空 `source_block`；不再产生 `validated_tool_evidence`、`direct_results_found` 或中等置信度的矛盾组合。
- “研究/调查/验证/比较/综合分析”等明确研究意图会被识别为 research，并绕开普通确定性快速路由。无论得到候选还是规划器零工具结束，只要没有可用正文/结构化证据，模型上下文就被硬性限制为只报告研究未完成、候选数量和读取缺口，不得依据搜索摘要或模型既有知识输出价格、日期、能力比较或确定性结论。
- 即时回复中的“本次使用的来源”只读取 `used_sources`，标签改为“联网正文读取已完成，本次使用的来源（预览 3/N）”；candidate-only 使用单独的可见止血提示。证据轨迹把搜索结果显示为“候选（预览 3/N）”，前三条之外可展开，candidate/read/selected/read_failed 不再混用。
- ChatTurn 的 ResearchRun 证据投影新增 `source_truth_version=2` 和有界读取计数/状态，不保存全文。现行已读或结构化证据可派生为 selected；历史 selected 若缺少正文读取真值则派生为 `legacy candidate / 历史验证状态未知`，既不伪造成已读，也不改写为 rejected。
- 定向后端回归 130/130、全量后端 pytest 1150/1150（366.76 秒）、全量 Ruff、定向 detect-secrets 0 findings、expanded mypy baseline（当前 122、基线 128、净减少 6）、前端 Vitest 344/344 与 TypeScript production build 均通过；`git diff --check` 通过。
- 真实一键启动复验：后端 `127.0.0.1:8000`、前端 `127.0.0.1:5173`、固定 SearXNG `127.0.0.1:8080` 均 ready；上游多引擎超时/限流被诚实显示为 `degraded`。Playwright 在桌面和 760px 窄屏复验旧 `opus5` turn：主证据区显示“本轮没有标记为已采用的可核对证据”，诊断区显示“候选（预览 3/5）”，其余 2 条可展开，窄屏 `scrollWidth == innerWidth == 760`。唯一 console error 为未配置 `/favicon.ico` 的 404，与本切片无关。
- **RQ1-A / Pre-RQCE implementation：GO / COMPLETE。** 实现提交 `7edfda44fa83093d7b3c3ffbe52617375fb7d5fd` 已推送 `main`；匹配的 [CI #32945352584](https://github.com/2002yy/study-agent/actions/runs/32945352584) 为 `success`。本切片只关闭候选/正文/已采用语义与 UI 止血门；不声称研究范围、分析深度或完整 RQ1 已完成。
- **RQ1：仍为 NO-GO / bounded preset + RQ1-C REQUIRED。** 45/60 秒有界研究、问题面规划、5–8 页读取、内容家族/来源角色、原子主张绑定、冲突分析、取消/逐调用审计和 12 个真实案例双门仍未实现或验收；G17-LAN 继续 NO-GO。
- 远程 `main` 已跟踪 `docs/RESEARCH_QUALITY_CODEX_TASKBOOK.md` 与 `docs/RESEARCH_QUALITY_OPENCODE_EXECUTION_PLAN.md`；它们与本节的统一结果见 15.10，不再作为平行草案参与事实投票。

### 15.10 Research Quality 路线统一（2026-08-26，docs-only reconciliation）

- **架构：CLOSED。** RQ1-A 正式定义为 `Pre-RQCE Truth Stabilization`；C1–C100 正式定义为 `Shared Research Quality Engine`，服务 quick / bounded / deep 三个 preset，不新增第四条 pipeline，不实现独立 `RQ1BoundedResearchEngine`。
- **Standard Search invariant：CLOSED。** Quick 不承担完整 Claim Graph、Deep Research 的 search/read/token/延迟成本；该约束不保护错误 evidence truth。candidate/read/selected/cited 语义必须跨 preset 一致。
- **预算：CLOSED。** bounded 保持 `<=20 candidates / 5–8 reads / 45s soft / 60s hard`；deep 保持 DR1 的 3–10 分钟、10–20 reads，12/16 reads 与 6/8 分钟是 deep `TUNABLE_DEFAULT`；quick 继续更轻。
- **Gate：CLOSED。** 12-case RQ1-C、20-case Shadow、50–60 Frozen + Live 分别拥有 bounded GO、工程诊断、整体/DR1 Release 三种不同判断权，不互相替代。
- **命名：CLOSED。** 新研究整改施工阶段统一为 `RQCE-P0 / RQCE-P1 / RQCE-P2`；C1–C100 内容与编号不变，避免和 Study Agent 历史 P1/P2 项目阶段冲突。
- **Owner：CLOSED。** 继续扩展现有 WebLookupRun/ResearchRun 与 ChatTurn operation/CAS/cancellation 真值，不新增第二套 run truth。
- **交付节奏：CLOSED。** 每个逻辑 batch 仍需独立 preflight、Exit Gate、本地验证和 Stop report；为减少重复远程 CI，用户已明确允许多个相邻且各自通过的本地小批累计后统一提交。不得跨 Gate 聚合或省略逐批验证。
- **本轮施工起点：`RQCE-P0-A0` 只读契约审计。** 该起点已按 15.11 完成；当前执行点必须读取本文件最后一个 RQCE Stop report，不得回退到本条重复施工。

### 15.11 RQCE-P0-A0 现状契约审计（2026-08-26，read-only）

- **Batch status：PASS / COMPLETE。** A0 只审计现状与冻结边界，没有修改 production code；定向基线 `51 passed in 15.26s`，文档链接、C1–C100 决策行守恒与 `git diff --check` 随本地 docs batch 继续复验。
- **运行与持久化 owner：CLOSED。** `WebLookupRun.research_context` 是第一版 Claim Engine state 的唯一持久化位置，键为 `claim_engine`；`WebLookupRepository` 已拥有 operation ownership、version CAS、checkpoint、cooperative cancellation 与 terminal transition。不得新增 ResearchRun/LocalRagRun/ClaimRun 表或第二套状态机真值。
- **可复用 evidence truth：CLOSED。** `src/domain/evidence.py` 的 `EvidenceRefV1`、`ClaimEvidenceLinkV1` 与 server-owned evidence IDs 是事实层；新的 research relation 由 Research Contracts 做窄枚举校验。`src/evidence/evidence_ref.py` 只用于旧归一化/UI 投影，不升级为持久化 owner。
- **Claim 边界：CLOSED。** `AnswerClaimV1` 继续只表示最终答案主张；`ResearchClaim` 表示研究过程中的问题分解、缺口与冲突，二者不合并。可复用 known evidence ID、重复 ID、confidence/range 等验证模式，但不得让 research contract 改写 final-answer lifecycle。
- **查询与调度边界：CLOSED。** `src/web/research_contract.py` 继续拥有 legacy query attempts / deterministic query context；`source_assessment.py` 继续只判 usability/directness，不冒充 Claim Gate；`deep_research.py` 继续只做 escalation；`concurrency.py` 的 bounded executor 可在后续调度 batch 复用。A1 不改这些文件。
- **包位置 collision：RESOLVED。** 新共享引擎使用 `src/web/research/`，避免含混的顶层 `src/research/`，也不把新合同塞入既有单文件 `src/web/research_contract.py`。测试沿用仓库 flat discovery。
- **A1 exact files：FROZEN。** 仅 `CREATE src/web/research/__init__.py`、`CREATE src/web/research/contracts.py`、`CREATE tests/test_research_quality_contracts.py`。production files = 2；A1 只实现不可变、版本化、可序列化的数据合同与纯校验，不实现 planner/gate/orchestrator/persistence adapter。
- **A1 forbidden files：FROZEN。** 不修改 `src/application/web_lookup_service.py`、`src/repositories/web_lookup_repository.py`、`src/domain/runtime_entities.py`、数据库 schema/migration、现有 evidence/answer-claim/query contracts、frontend、prompt 或 feature flag；不启动 shadow/active。
- **A1 test matrix：FROZEN。** 覆盖最小合法 state round-trip；claim kind/priority/state/relation 枚举；未知/重复 claim 与 evidence link；confidence 与 budget 边界；gap/conflict 引用完整性；schema version fail-closed；无 raw page body/secret 字段；输入顺序不影响确定性输出。
- **已知风险。** `ClaimEvidenceLinkV1` 本身允许通用字符串，因此 research-specific relation 必须在新 builder/parser 中 fail closed；`research_context` 是 JSON 边界，A2 必须使用显式 `to_dict/from_dict` 且保留 repository CAS，不能直接序列化 dataclass；现有 source assessment 的数量置信度不能作为事实真值。
- **A0 Stop report。** Behavior changed：仅权威文档冻结合同边界；Behavior intentionally unchanged：所有 runtime/search/read/answer/UI/persistence 行为；Frozen decisions satisfied：单一 owner、ResearchClaim/AnswerClaim 分离、server-owned evidence IDs、legacy 定位、exact files/tests。用户已授权连续本地累计，因此下一逻辑 batch `RQCE-P0-A1 Research Contracts v1` 可在新 Preflight 后开始，仍不提交。

### 15.12 RQCE-P0-A1 Research Contracts v1（2026-08-26，本地累计未提交）

- **Batch status：PASS / COMPLETE。** 按 A0 exact files 仅新增 `src/web/research/__init__.py`、`src/web/research/contracts.py`、`tests/test_research_quality_contracts.py`；没有修改既有 production 文件，也没有接入 runtime。
- **合同结果。** 新增 versioned/frozen `ResearchState` 及 Question/Claim/EvidenceRequirement/server-owned Evidence projection/ClaimEvidenceLink/Gap/Conflict/Cluster/Budget/Trace/Brief schema；`ResearchClaimEvidenceLink` 组合复用 `ClaimEvidenceLinkV1`，并在 research parser 中收窄为 supports/contradicts/qualifies/background/lead。
- **Fail-closed 边界。** unknown schema/field/enum、重复 ID/link、未知 claim/question/evidence/cluster/gap 引用、非有限或越界 confidence/budget、没有对应 supports/contradicts link 的 ConflictGap、把 satisfied claim 写入 unresolved brief 均拒绝；ResearchEvidence 只允许有界 locator/anchored spans，不提供 raw page body、credential 或 token 字段。
- **确定性与兼容。** Builder 对 ID/link/trace 与集合字段稳定排序；`to_dict/from_dict` 完成 JSON-safe round-trip。`unresolved` 与 `unavailable` 保持不同真值；旧 `AnswerClaimV1`、EvidenceSnapshot、query contract、WebLookup service/repository/schema/UI 全部未改。
- **验证。** A1 专项 `19 passed in 4.24s`；新增代码 Ruff 通过；新增代码与测试 mypy `Success: no issues found in 4 source files`；`git diff --check` 通过。A0 既有合同/恢复基线此前为 51/51。
- **A1 Stop report。** Behavior changed：production behavior 0；Behavior intentionally unchanged：legacy search/read/stop/synthesis/persistence/answer/UI；Known limitation：合同尚未持久化、未启用 shadow、未实现 planner/gate；Frozen decisions satisfied：exact files、单一 evidence truth、AnswerClaim 分离、严格 schema。按用户连续累计授权，下一逻辑 batch 为 `RQCE-P0-A2 State persistence adapter`，新 Preflight 后开始，仍不提交。

### 15.13 RQCE-P0-A2 State persistence adapter（2026-08-26，本地累计未提交）

- **Batch status：PASS / COMPLETE。** 新增 `src/web/research/state.py` 与 `tests/test_research_quality_state.py`，并仅在新包 `__init__.py` 导出；没有修改 service、repository、entity 或数据库 schema。
- **单一 owner 保持。** `attach_claim_engine_state()` 只复制并严格校验 `research_context["claim_engine"]`；真实 SQLite 测试通过既有 `WebLookupRepository.begin_operation/checkpoint` 的 operation owner + version CAS 完成落盘与 repository restart round-trip，没有新增写入器或第二套 run truth。
- **旧 run 与坏 state 安全边界。** 缺少 `claim_engine` 明确加载为 `absent/off`；旧 schema、非 object 或校验失败明确加载为 `unavailable/shadow`，只返回有界 reason code，不回放异常或原始内容，也不影响 legacy context。P0 只提供 `new_empty_shadow_state()`，不提供 active bootstrap。
- **为何不修改 WebLookupService。** 当前仓库没有已冻结/实现的 `RESEARCH_CLAIM_ENGINE_MODE` 配置 owner，默认又必须为 off；在 A2 直接 create 时注入 shadow 会构成未授权 runtime activation。A2 因而只交付可由后续 flag batch 显式调用的 adapter。
- **验证。** A1+A2+WebLookup 持久化/恢复回归 `32 passed in 10.10s`；新增包 Ruff 通过；新增 production package mypy 0 error；仓库 expanded mypy baseline `current=122 / baseline=128 / resolved=6 / new package diagnostics=0`；`git diff --check` 通过。
- **A2 Stop report。** Behavior changed：production behavior 0；Behavior intentionally unchanged：create/execute/checkpoint/cancel/resume/retry/search/read/stop/synthesis/UI；Known limitation：尚无 runtime flag/observer/trace writer；Frozen decisions satisfied：`research_context["claim_engine"]`、repository CAS、old run compatibility、bad schema fail-safe。按连续累计授权，下一逻辑 batch 为 `RQCE-P0-A3 Research Trace v1`，新 Preflight 后开始，仍不提交。

### 15.14 RQCE-P0-A3 Research Trace v1（2026-08-26，本地累计未提交）

- **Batch status：PASS / COMPLETE。** 新增 `src/web/research/trace.py` 与 `tests/test_research_quality_trace.py`，在尚未远程交付的 v1 contract 中补齐强制 UTC timestamp/run_id，并收窄为冻结的 13 类 trace event（任务书列出的 12 类加 `failure_recorded`，其中 stop allowed/blocked 分列）。没有修改 legacy service。
- **严格 writer。** `append_research_trace()` 生成单调 sequence、规范化 UTC、拒绝跨 run trace 混写，并对 claim/gap/evidence/budget 事件强制所需引用；追加后通过完整 ResearchState builder 再校验，不能绕过 server-owned evidence ID 或内部引用门。
- **legacy 安全边界。** `try_append_research_trace()` 在 trace contract/type/reference 失败时返回原不可变 state + `trace_validation_failed`，不抛给 legacy；当前没有 runtime 接线，因此 trace 无法改变用户答案或让现行研究失败。
- **持久化兼容。** Trace 经 `ResearchState.to_dict` 进入既有 claim-engine context adapter，并完成 attach/load round-trip；不记录 raw page body、credential、token 或 parser exception。
- **验证。** A3 专项 10/10；A1–A3 合同/state/trace 合计 34/34；新增包 Ruff 通过、mypy 0 error、`git diff --check` 通过。
- **A3 Stop report。** Behavior changed：production behavior 0；Behavior intentionally unchanged：legacy research 与 UI；Known limitation：尚未由 observer 写入真实 trace，也没有 Evidence Gate；Frozen decisions satisfied：强制字段、冻结事件、单 run、失败不拖垮 legacy。按连续累计授权，下一逻辑 batch 为 `RQCE-P0-B1 Evidence requirement policy`，新 Preflight 后开始，仍不提交。

### 15.15 RQCE-P0-B1 Evidence requirement policy（2026-08-26，本地累计未提交）

- **Batch status：PASS / COMPLETE。** 新增 `src/web/research/policy.py` 与 `tests/test_research_quality_policy.py`；只扩展尚未交付的 v1 `EvidenceRequirement` 为显式 `requires_successful_read`，没有 role-classifier LLM、Gate 或 runtime 接线。
- **显式 profile，而非错误推断。** `factual/analytical` 不能唯一决定证据规则，因此 planner 必须显式选择 official statement/current fact/quantitative/causal/community sentiment/exploratory hypothesis profile；缺少 profile 不静默套默认。
- **角色策略。** 冻结 primary/authoritative secondary/independent secondary/community/aggregator 五类。官方声明只允许成功正文读取的 primary 正式闭环；社区情绪允许 community + independent secondary，不要求官方 primary；aggregator 在所有 profile 都只能作为 lead，Critical 非官方 profile 默认要求 2 个独立来源。
- **代码 owner。** Policy 只产出 eligible roles、lead-only roles、最小独立来源、primary/read requirement 与 hypothesis-only closure semantic；它不分类 URL、不判真、不改变 ClaimState，未来 B2 仍必须用代码 hard gate。
- **验证。** B1 专项 11/11；A1–B1 合计 45/45；新增包 Ruff 与 mypy 0 error，`git diff --check` 通过。
- **B1 Stop report。** Behavior changed：production behavior 0；Behavior intentionally unchanged：legacy 与 UI；Known limitation：ResearchEvidence 还没有 read/extractor eligibility，policy 尚未执行；Frozen decisions satisfied：C2/C3/C6/C12/C14/C16/C17/C21 的 policy 侧边界。按连续累计授权，下一逻辑 batch 为 `RQCE-P0-B2 Deterministic Evidence Gate`，新 Preflight 后开始，仍不提交。

### 15.16 RQCE-P0-B2 Deterministic Evidence Gate（2026-08-26，本地累计未提交）

- **Batch status：PASS / COMPLETE。** 新增 `src/web/research/evidence_gate.py` 与 `tests/test_research_quality_evidence_gate.py`；只扩展未交付 v1 ResearchEvidence 的 lifecycle/extraction eligibility 和 ResearchBudget 的候选/读取/时间消耗量，没有 runtime 接线。
- **Hard Gate。** Critical claim 只有成功 read/selected、extractor eligible、role eligible、强度 `>=0.7` 且拥有足够独立 source clusters 的 supports links 才能闭环；primary-required profile 还必须有 primary。模型写入 `state=satisfied` 不能越过这些代码门。
- **False closure 防线。** snippet/candidate、read/extractor failure、unknown/missing metadata、重复 cluster、UNAVAILABLE、缺 primary、空 Claim Graph 均不能 PASS；strong support + strong contradiction 生成/复用 ConflictGap 并 BLOCK，不做多数投票。resolved gap 不伪装 active gap。
- **预算语义。** hard candidate/read/time 任一耗尽且仍有 open Critical 时返回 `PARTIAL`，保留 open claims/gaps/reasons 并允许 legacy 产生明确不完整结果，但绝不返回 satisfied/PASS。未耗尽则 BLOCK。
- **验证。** B2 专项 11/11；A1–B2 合计 56/56；新增包 Ruff 与 mypy 0 error，`git diff --check` 通过。
- **B2 Stop report。** Behavior changed：production behavior 0；Behavior intentionally unchanged：legacy/UI；Known limitation：Gate 尚未接 observer，0.7 为后续 benchmark 可校准阈值；Frozen decisions satisfied：C1/C4/C7/C8/C9/C16/C17/C18/C22/C23 与 Hard Gate 最小规则。下一逻辑 batch 为 `RQCE-P0-B3 Stop interceptor decision（shadow-only）`，新 Preflight 后开始，仍不提交。

### 15.17 RQCE-P0-B3 边界复审决策（2026-08-26）

- OpenCode 计划在 B3 写“对 WebLookupService 最小集成”，任务书第15节则把 B 定义为 Gate + Trace unit fixtures、把 shadow observer 明确放在 RQCE-P0-C。当前还没有 legacy-output-to-ClaimState projection；现在接 service 只会让 empty graph 全量 BLOCK，使 `legacy_would_stop_but_shadow_blocked` 指标失真。
- **冻结处理：B3 只实现纯 stop decision、false-closure candidate 指标和 fail-safe shadow boundary；不改 WebLookupService。** 真实 observer/service checkpoint 接线必须与 C 阶段的 projection/eval schema 同批完成，并证明 legacy answer byte-for-byte 不变。

### 15.18 RQCE-P0-B3 Stop decision（2026-08-26）

- **Batch status：PASS / COMPLETE。** 新增 `src/web/research/stop_gate.py` 与 `tests/test_research_quality_stop_gate.py`；没有修改 WebLookupService 或任何 legacy path。
- **Shadow truth。** Decision 同时记录 legacy_would_stop/legacy_should_stop、shadow pass/block/partial、open Critical、gaps/reasons 和 `legacy_would_stop_but_shadow_blocked`。其中 `legacy_should_stop` 始终严格等于 legacy 输入；partial 保留未闭环主张但不误记为 shadow block。
- **Fail-safe。** Shadow evaluator 任何异常都被收敛为 `unavailable + shadow_gate_failed`，不回放异常细节、不产生 false-closure candidate，也不改变 legacy stop。
- **验证。** B3 专项 5/5；A0 复用边界 + A1–B3 + 既有 Evidence/AnswerClaim/WebLookup/recovery 覆盖合计 112/112；新增包 Ruff、mypy 0 error；expanded mypy baseline `122 <= 128` 且本包 0 diagnostics；定向 detect-secrets 0 finding files；C1–C100 数量 100→100 且 normalized delta 0；四份权威文档本地链接 0 missing；`git diff --check` 通过。
- **聚合交付状态：REMOTE GO / CHECKPOINT DELIVERED。** docs reconciliation、A0、A1、A2、A3、B1、B2、B3 已由提交 `2afea76f7a37abc1a48e4f25c4974439383907fb` 推送 `main`；匹配的 [CI #32955918199](https://github.com/2002yy/study-agent/actions/runs/32955918199) 已完成且结论为 `success`。该 checkpoint 仍保持 legacy runtime 行为不变，真实 observer activation 延后到 RQCE-P0-C。
- **P0 / RQ1 仍 NO-GO。** 当前没有 claim projection、shadow observer、20-case schema/fixtures/runner/report，也没有 active runtime。下一唯一逻辑 batch 是 `RQCE-P0-C1 Benchmark/eval schema`；C 阶段必须先生成可解释 projection，再允许 service observer 接线，且 legacy answer 必须 byte-for-byte 不变。

### 15.19 RQCE-P0-C1 Benchmark/eval schema（2026-08-26，本地累计未提交）

- **Batch status：PASS / COMPLETE。** 新增 `src/evals/research_quality.py` 与 `tests/test_research_quality_eval.py`，并在 `src/evals/__init__.py` 导出新合同；新增 `tests/fixtures/research_quality/README.md` 冻结 fixture 格式文档。没有修改 `src/web/research/` 任何模块、WebLookupService 或 runtime 路径。
- **Schema 结果。** versioned/frozen `research-quality-eval-v1`：`ResearchQualityEvalCase`（id/category/mode/gold/corpus）+ `GoldContract` 8 字段（question/critical_surfaces/expected_claims/required_source_roles/primary_exists/known_conflicts/freshness_requirement/forbidden_closure_conditions）+ `FrozenCorpusDocument`（doc_id/url/title/source_role/cluster_id/published_at/content）。冻结 10 类 trap category、2 种 mode（frozen/live）、7 个 forbidden closure condition；source role/claim kind/priority 枚举与 A1/B1 冻结值一致并有同步测试。
- **Fail-closed 边界。** 未知 schema_version/字段/枚举、重复 case id/doc id/claim surface/source role、空 critical_surfaces/expected_claims/required_source_roles、live 带 corpus、frozen 无 corpus、空 freshness（既无 max_age_days 又不要求 dated evidence）、非 ISO-8601 published_at 均拒绝。类别交叉校验：no_primary_exists => primary_exists=false 且角色不得含 primary；question_unverifiable 与 unanswerable_unverifiable 双向绑定；conflicting_primary 必须声明 known_conflicts；old_primary 必须声明 freshness_requirement。
- **C1 禁止事项遵守。** 未接 WebLookupService、未启用 shadow observer、未实现 claim projection、未创建任何真实 20-case fixture（tests/fixtures/research_quality/ 只有 README）、未跑 live web、未改变 quick/bounded/deep 用户可见行为、未进入 C2。
- **Preflight 裁决。** 执行计划写 `tests/research/test_research_quality_eval.py`，与 A0 冻结的 flat test discovery 冲突；按 A0 结论采用 `tests/test_research_quality_eval.py`（与 A1–B3 命名一致）。
- **验证。** C1 专项 15/15；A1–B3 + 既有 evals 回归合计 93/93；新增/修改文件 Ruff 通过；expanded mypy baseline gate `current=122 / baseline=128 / resolved=6` 且本批 0 新 diagnostics；定向 detect-secrets 0 finding files；C1–C100 决策行守恒 100->100；`git diff --check` 通过。
- **C1 Stop report。** Behavior changed：production behavior 0；Behavior intentionally unchanged：legacy search/read/stop/synthesis/persistence/answer/UI；Known limitation：尚无 runner、metrics、projection、observer 与任何真实 fixture；Frozen decisions satisfied：gold 8 字段、10 类陷阱、frozen/live 二分、来源角色与 A1/B1 一致、fail-closed schema。按用户连续本地累计授权，下一逻辑 batch 为 `RQCE-P0-C2 20 个陷阱题`，新 Preflight 后开始，仍不提交。

### 15.20 RQCE-P0-C2 20 个陷阱题（2026-08-26，本地累计未提交）

- **Batch status：PASS / COMPLETE。** 新增 `tests/fixtures/research_quality/frozen_trap_cases.json`（10 个 frozen case，含合成 corpus）与 `tests/fixtures/research_quality/live_trap_cases.json`（10 个 live metadata-only case），以及契约测试 `tests/test_research_quality_trap_cases.py`；更新 fixture README 登记 C2 交付。没有修改任何 production code、WebLookupService 或 runtime 路径。
- **陷阱题构成。** 10 类 x 2（每类恰好 1 frozen + 1 live）：secondary_only、duplicate_source、old_primary、conflicting_primary、no_primary_exists、community_opinion、numerical_original_source、causal_competing_explanations、simple_factual、unanswerable_unverifiable。满足任务书`至少一半做 frozen corpus`要求（10/20 frozen）。
- **陷阱语义。** frozen corpus 为合成测试数据（无 live web 抓取）：secondary_only 提供易得二手 + 深藏 primary；duplicate_source 用同 cluster_id 的通讯社转载模拟伪独立来源；old_primary 的 primary 发布于 2021 并配 freshness_requirement；conflicting_primary 双 primary 簇给出冲突数值并声明 known_conflicts；no_primary_exists/community_opinion/unanswerable 均无 primary 且角色不含 primary；numerical_original_source 要求仅 primary 且提供 aggregator 引诱（5.2B vs 5,243,000,000）；causal_competing 声明双归因冲突；simple_factual 是最小禁止条件的对照 case（仅 snippet_only_evidence），用于诊断 Shadow Gate 是否误 BLOCK 简单事实。
- **契约测试。** 15 个测试覆盖：20 个唯一 case、每类 1 frozen + 1 live、frozen 必有 corpus而 live 必无、每 case 至少一个 critical claim、逐类语义断言（primary_not_read/重复 cluster/stale 日期/known_conflicts/角色约束/aggregator 引诱/控制组最小化/question_unverifiable 双向绑定）、全量 JSON round-trip。
- **C2 禁止事项遵守。** 未接 WebLookupService、未启用 shadow observer、未实现 claim projection、未跑 live web（live case 只是 metadata 定义）、未改变 quick/bounded/deep 用户可见行为、未进入 C3。
- **验证。** C2 专项 15/15；C1 + C2 + A1–B3 + 既有 evals 回归合计 108/108；新增文件 Ruff 通过；expanded mypy baseline gate `current=122 / baseline=128 / resolved=6`（本批 0 新 diagnostics、0 production 改动）；定向 detect-secrets 0 finding files；C1–C100 决策行守恒 100->100；`git diff --check` 通过。
- **C2 Stop report。** Behavior changed：production behavior 0；Behavior intentionally unchanged：legacy search/read/stop/synthesis/persistence/answer/UI；Known limitation：尚无 runner/metrics、无 projection/observer、live case 未运行（C3/C4 范围）；Frozen decisions satisfied：10 类 x 2、frozen/live 二分、合成 corpus、cluster 独立性语义、控制组。按用户连续本地累计授权，下一逻辑 batch 为 `RQCE-P0-C3 Shadow runner`，新 Preflight 后开始，仍不提交。

### 15.21 RQCE-P0-C3 Shadow runner（2026-08-26，本地累计未提交）

- **Batch status：PASS / COMPLETE。** 新增 `src/evals/research_quality_runner.py` 与 `tests/test_research_quality_runner.py`，并在 `src/evals/__init__.py` 导出新合同。没有修改 `src/web/research/` 任何模块、WebLookupService 或 runtime 路径。
- **Runner 架构。** 离线、确定性 harness：`ResearchRunTranscript`（versioned `research-quality-run-v1`：case_id/reference_date/queries/searches/reads/cited_doc_ids/addressed_claim_surfaces/llm_calls/elapsed/closed）+ `RunEvaluation` + `ShadowRunSummary`。给 transcript + frozen case gold + corpus，计算 P0-C 全量 metric 集：False Closure / Primary Retrieval / Useful Read Ratio / Independent Cluster Count / Critical Claim Coverage / Citation Entailment（本阶段 None）/ Search-Query-Read Counts / LLM Calls / Elapsed / Failure Reasons；shadow 侧在进程内构造 `ResearchState`（mode=shadow）后调用既有 `evaluate_shadow_stop`，记录 shadow_status/would_block/would_pass/legacy_would_stop_but_shadow_blocked/open_critical_claims。
- **确定性近似与边界（已文档化）。** 无 LLM：link 关系与抽取 eligibility 由 transcript 显式声明；`question_unverifiable` 语义通过将对应 claim 的 `state` 置 `unavailable` 进入 shadow 路径（gate 报 `unavailable_not_satisfied` 保持 BLOCK）；`min_independent_sources` = 2 当 gold 含 `independent_sources_below_minimum`，否则 1；`requires_primary_source` = primary_exists 且角色含 primary；known_conflicts 存在且引用簇 >=2 时跨簇链接 supports/contradicts；budget 用 bounded preset 上限（20/8/45/60）。false_closure 闭包判定对每个 gold forbidden_condition 做确定性校验，并增加隐式 `no_cited_evidence`（closed 但零引用）。
- **契约测试。** 14 个：secondary_only 抓到 primary_not_read 误闭环、正确读 primary 通过且 useful_read_ratio=1.0、duplicate_source 单簇误判、old_primary 新鲜度未满足、conflicting_primary 冲突未解决、unanswerable closed 误闭环 + shadow BLOCK、unanswerable 未闭包为正确、simple_factual 正确路径不被误 BLOCK、simple_factual snippet-only 为误闭环、零引用 closed 被标记、transcript round-trip + 未知字段/坏日期/坏枚举/重复 doc_id 拒绝、未知 doc 引用拒绝、批量与 summary（不同 case + 重复 transcript 拒绝 + 空安全）。
- **C3 禁止事项遵守。** 未接 WebLookupService、未启用 shadow observer、未实现 claim projection、未跑 live web（runner 只在 frozen corpus 上运行，live case 无 transcript 不进入 evaluate）、未改变 quick/bounded/deep 用户可见行为、未进入 C4。
- **验证。** C3 专项 14/14；C1+C2+C3+A1–B3+既有 evals 回归合计 122/122；新增/修改文件 Ruff 通过；expanded mypy baseline gate `current=122 / baseline=128 / resolved=6` 且本批 0 新 diagnostics；定向 detect-secrets 0 finding files；C1–C100 决策行守恒 100->100；`git diff --check` 通过。
- **C3 Stop report。** Behavior changed：production behavior 0；Behavior intentionally unchanged：legacy search/read/stop/synthesis/persistence/answer/UI；Known limitation：无 LLM entailment、无真实 legacy 投影（transcript 为合成 eval 输入）、Useful Read Ratio 仅 legacy baseline 维度、shadow 状态由 harness 构造而非 runtime observer；Frozen decisions satisfied：transcript schema、全量 metric 集、unavailable 语义闭环、bounded budget、确定性 link 构造。按用户连续本地累计授权，下一逻辑 batch 为 `RQCE-P0-C4 跑第一次 baseline vs shadow`，新 Preflight 后开始，仍不提交。

### 15.22 RQCE-P0-C4 跑第一次 baseline vs shadow（2026-08-26，本地累计未提交）

- **Batch status：PASS / COMPLETE。** 新增 `tests/fixtures/research_quality/legacy_transcripts.json`（10 个 frozen case 的合成 legacy transcript）、报告生成器 `tools/run_research_quality_shadow_report.py` 与 `tests/test_research_quality_shadow_report.py`；生成诊断报告 `docs/research_quality/P0_SHADOW_REPORT.md`。没有修改 `src/web/research/`、WebLookupService 或任何 runtime 路径。
- **运行范围。** 在 10 个 frozen case 上用合成 legacy transcript 跑 baseline vs shadow（live 10 题无 corpus，超出 P0 离线范围，留待真实 web）。transcript 模拟 legacy 典型失败模式（secondary_only 只读二手、duplicate_source 只读同簇、old_primary 读旧 primary、conflicting_primary 只读一侧、numerical 只读 aggregator、causal 只读 incident report、unanswerable 误闭包；simple_factual 正确路径作对照）。
- **诊断结果（详见报告）。** 10/10 closed；baseline 7 个 false closure；shadow blocked 4，caught 4，missed 3，overblocked 0。逐 case 输出 violated_closure_conditions、shadow_status、open_critical_claims。Exit Gate 自检 5 条在报告内逐条记录。
- **定位的 3 个数据结构缺口（P1 解决，非 P0 blocker）。** 1）`old_primary`：`freshness_unmet` 是 baseline metric 维度，B2 Evidence Gate 未读 published_at，shadow 无法 block 旧来源——gate 缺 freshness 维度。2）`conflicting_primary`/`causal_competing`：legacy transcript 只读冲突一侧、无 contradiction 链接，B2 gate 靠动态 supports/contradicts 检测、不读 gold.known_conflicts，shadow 看不到冲突信号——gold 预置 conflict 未注入 shadow state。3）`question_unverifiable` 已通过 claim.state=unavailable 闭环（caught）。三者均为"当前数据结构能否解释失败"的明确答案，不是 RQCE-P0 Exit Gate 失败。
- **C4 禁止事项遵守。** 未接 WebLookupService、未启用 shadow observer、未实现 claim projection、未跑 live web（只用 frozen 合成 transcript）、未改变 quick/bounded/deep 用户可见行为、未进入 RQCE-P1。
- **验证。** C4 专项 8/8；C1–C4 + A1–B3 + 既有 evals 回归合计 130/130；新增文件 Ruff 通过；expanded mypy baseline gate `current=122 / baseline=128 / resolved=6` 且本批 0 新 diagnostics（`tools/` 不在 mypy src 扫描范围但 `src/evals` 内 0 diagnostics）；定向 detect-secrets 0 finding files；C1–C100 决策行守恒 100->100；`git diff --check` 通过。
- **C4 Stop report。** Behavior changed：production behavior 0；Behavior intentionally unchanged：legacy search/read/stop/synthesis/persistence/answer/UI；Known limitation：frozen 10 题已跑、live 10 题未跑、3 个数据结构缺口留待 RQCE-P1；Frozen decisions satisfied：合成 transcript 模式、报告生成器可重跑、Exit Gate 自检、诊断三缺口定位。**RQCE-P0 整体 Exit Gate 待人工确认本报告后通过；通过后禁止自动进入 RQCE-P1。** 本地累计未提交。

### 15.23 RQCE-P0-C5 Gold-blind 修复与 live operational observation（2026-08-26，本地未提交）

- **复审结论：原 C4 报告无效，不得确认。** 原 runner 用 `expected_claims`、`primary_exists`、`forbidden_conditions`、`known_conflicts` 等 Gold 字段构造被测 `ResearchState`；因此 caught 4/7 不是独立 shadow 能力证据。原报告还只跑 frozen 10/20，却把 P0 Exit Gate 描述为可通过；Primary Retrieval denominator、Useful Read Ratio 与 Critical Claim Coverage 也混入了错误或不可审计口径。15.22 保留为当时历史记录，本节覆盖其当前 Gate 结论。
- **C5-A gold-blind harness：PASS。** transcript 升级为 `research-quality-run-v2`，显式记录 question surface、projected claims 与 claim-evidence relations；`_evaluate_shadow` 仅接收 corpus/transcript/read state，不接收 eval case 或 gold。Gold 只在 shadow decision 完成后计算 false closure 与评分。旧 v1 transcript 缺 projection 时返回 `shadow_status=unavailable / shadow_projection_missing`，不再编造 shadow 结论；gold mutation invariance 已有回归测试。
- **C5-A freshness：PASS。** `EvidenceRequirement` 新增 `max_age_days/requires_dated_evidence`，`ResearchEvidence` 新增 `published_at`，`ResearchState` 新增 `reference_date`；Evidence Gate 对要求新鲜度的 critical claim 缺日期、坏日期或过期证据 fail closed，并输出 `freshness_required`。这是 additive/backward-compatible contract，既有无 freshness state 仍按旧语义解析。
- **C5-A metric truth：PASS。** Primary Retrieval 只以 `gold.primary_exists=true` 为 denominator；Useful Read 只计实际进入 supports/contradicts/qualifies/lead relation 的 eligible read；Critical Claim Coverage 只计有 evidence-linked relation 的 critical gold surface。报告同时输出 raw numerator/denominator，避免百分比掩盖样本数。
- **修复后 frozen 10 诊断。** baseline false closure 7；gold-blind shadow caught 6、missed 1、overblocked 0；Primary Retrieval 4/7（57.14%）；Useful Read 15/15（synthetic fixture macro 1.00）；evidence-linked critical coverage 10/11（90.00%）。唯一 miss 是 `conflicting_primary`：只观察冲突一侧时，被测输入没有产生 contradiction relation；禁止从 `gold.known_conflicts` 注入该信号。该结果证明 P0 组件可表达六类失败，但仍不是 production observer 证据。
- **C5-B live operational observation：完成，但不等于 live semantic comparison。** 对 10 个真实公共问题运行现有 `GeneralWebGateway`，逐 case checkpoint，仅持久化 query、provider error、公开 URL/title/source、relevance/directness、read status/字符数/backend/elapsed；不保存网页正文、secret 或模型 prompt。实测 search API 10/10 返回 ok，50 个候选中仅 10 个满足 benchmark-local 严格 relevance、仅 2/10 case 有至少一个相关候选；6/6 读取成功，8/10 case 出现 provider error。大量 fallback 命中 `current/exact/do/why` 等词典页，说明“search ok”不能代表研究检索成功，且 legacy 单词重叠 relevance 过宽。
- **边界与未决。** 本批不修改 production `source_assessment.py`，因为这会改变用户可见检索行为，需单独冻结；benchmark-local 严格 relevance 仅用于观察。关键词匹配最多只能标记 LEAD，不能冒充 SUPPORTS/CONTRADICTS/QUALIFIES。要完成 live 10 shadow comparison，需要把读取正文交给 production-equivalent semantic projector；根据 G16 privacy truth，在用户明确授权 provider、数据范围与逐调用审计前，不发送正文给任何外部模型。
- **验证状态。** 完整 pytest `1270 passed in 398.94s`；Ruff 全仓通过；expanded mypy baseline `current=122 / baseline=128 / resolved=6`；RAG K1 deterministic baseline 成功生成；detect-secrets 全 CI 路径 0 findings；报告由 generator 重生成。package helper 在本机被仓库内 ignored `.venv-d3c`（482 files，含二进制中的随机 key-like bytes）干扰，干净 CI checkout 不含该目录，故该项只能由后续 CI 给出权威结果。当前 remote HEAD `bc650df` 的 CI #32975472636 仍有 1 个 browser Golden Journey 失败，因此即使本地后端全绿也不能把最新 HEAD 标为 REMOTE GO。
- **C5 Stop report。** Behavior changed：research contract/gate 支持显式 freshness；离线 eval harness 与 report 口径修复；新增不含正文的 live metadata observer。Behavior intentionally unchanged：legacy query/search/read/relevance/stop/synthesis/persistence/answer/UI。Known limitation：无获授权的 production-equivalent semantic projection，live 10 无 shadow decision，完整 20-case comparison 未成立。**Decision：RQCE-P0 整体 NO-GO；RQCE-P1、RQ1 bounded activation 与 G17-LAN 均不得进入。唯一下一步是先冻结 external-model semantic projection 的授权与审计合同。**

### 15.24 RQCE-P0-C5-B live semantic projection Preflight（2026-08-26，本地未提交）

- **授权已冻结：`1A 2A 3A 4A 5B 6A`。** 只允许 P0 eval 使用外部模型；provider=`deepseek`、model profile=`pro`。允许发送的数据仅为 fixture question、由 question 独立生成的 projected claims，以及公开网页 reader text；禁止发送真实聊天、记忆、本地资料、附件、eval Gold 或 secret。
- **调用与预算。** 每 case 先做一次 question-only claim projection；随后每个成功读取的 benchmark-relevant 公共页面做一次 evidence projection，每页清洗后最多 12,000 字符，每 case 最多 8 页。底层 SDK 自动重试必须关闭；应用层每个逻辑调用最多 2 attempts（首次 + 1 次受限重试），两次都逐调用记录。
- **逐调用审计。** 每个 attempt 记录 call_id/case_id/purpose/provider/model/URL（如适用）、data_categories/data_counts、正文 SHA-256/字符数、started_at/completed_at/status/result、response schema version 与 response SHA-256；不得持久化完整正文、prompt、模型原始输出或自由文本 rationale。
- **结构化输出与失败语义。** claim projection 至少生成一个 critical claim，并使用已冻结 kind/priority/policy profile/freshness 枚举；evidence projection 只允许 source_role、published_at、claim relation、strength 与枚举 reason codes。JSON、schema、枚举、引用或边界任一无效时允许一次重试；仍失败则整个 case=`projection_unavailable`，不得 fallback 到关键词 SUPPORTS/CONTRADICTS/QUALIFIES，也不得形成 shadow PASS。
- **隔离边界。** 本批只新增 eval module/tool/fixture artifact/report，不接 WebLookupService、不改 `source_assessment.py`、不改变 legacy 用户可见行为；benchmark-local relevance 仍只是 observer 选择器。live baseline closure 只能标注其观测依据，不能冒充真实 answer-generation transcript。
- **Preflight Decision：GO。** 输入、外发授权、审计、重试、fail-closed 与非目标均已明确；实现与 live 执行完成前 RQCE-P0 继续 NO-GO，RQCE-P1 不得开始。

### 15.25 RQCE-P0-C5-B live semantic projection 执行与 20 题报告重生成（2026-08-26，本地未提交）

- **Batch status：PASS / COMPLETE（执行完成，Gate 仍 NO-GO）。** 跑完全量 live 10 semantic projection（`docs/research_quality/P0_LIVE_SEMANTIC_EVAL.json`）并重生成完整 20 题 `docs/research_quality/P0_SHADOW_REPORT.md`。修复 projector 一处 mypy lambda 推断告警。
- **Live 10 projection 结果。** 8/10 completed、2/10 unavailable（`trap-duplicate-source-live` 与 `trap-unanswerable-live` 的 claim projection 两次重试均失败，整 case `projection_unavailable`，未 fallback 关键词）。14 个逻辑调用 / 17 次 attempt / 5 次失败 attempt；projected documents 仅 4 个（全属 `trap-simple-factual-live`）。8 题 claim projection 成功但无 evidence 页可投影——与 15.23 观察一致（8/10 case 无 benchmark-relevant 候选）。
- **20 题报告诊断。** Combined 18/20（2 unavailable 不计）：false closure 14、caught 13、missed 1、overblocked 0。Frozen 10：caught 6/missed 1（`conflicting_primary`，只读一侧无 contradiction，不注入 gold，符合预期）；live 10：7 false closure 全 caught、0 miss、0 overblock——但 8 题 shadow block 的原因是 `eligible_support_clusters=0`（无 evidence 投影），不是 Gate 识别了 false closure 本身。
- **Exit Gate 自检（报告内逐条）。** 1）legacy 行为不变 ✓；2）ClaimState/Trace/Gate 可持久化 ✓；3）**20-case harness repeatability = PASS / COMPLETE**（frozen 可确定性重跑、live 协议/schema/runner 可再执行、报告可由结构化输入重生成；live web URL/结果不要求字节相同）；3b）**20-case diagnostic outcome = NO-GO for production activation**（8/10 live case 无 eligible evidence 投影；live baseline closure 是 operational search-status proxy）；4）False Closure 有明确 claim/gap 原因 ✓；5）无 unknown evidence ID 绕过 Gate ✓。
- **P0 Exit Decision：C5 = PASS / COMPLETE；production activation = NO-GO。** 20-case Shadow harness 已交付且可重生成；dominant observed bottleneck = pre-projection retrieval coverage——当前证据主要指向 query planning/SearchIntent 与 legacy relevance/candidate recall，但 P1 须先对 8 个 no-projection live case 分类后才确定实现目标，不得直接宣布唯一根因。live baseline closed 仅是 `operational_search_status_ok_proxy`。`trap-simple-factual-live` 是唯一有 evidence 投影的 live case（shadow pass，primary retrieved）。
- **验证。** C5 专项 pytest 93/93（runner+projector+shadow_report+eval+trap_cases+contracts+evidence_gate+live_observation）；Ruff 全绿；expanded mypy baseline `current=122 / baseline=128 / resolved=6`（projector 0 error，修掉 lambda 推断告警）；C1–C100 守恒 100；`git diff --check` 通过。detect-secrets 与 RAG K1 待远程 CI。
- **C5-B Stop report。** Behavior changed：新增 `P0_LIVE_SEMANTIC_EVAL.json`（不含正文/prompt/raw 输出，逐调用审计齐全）与重生成的 20 题 `P0_SHADOW_REPORT.md`。Behavior intentionally unchanged：legacy query/search/read/relevance/stop/synthesis/persistence/answer/UI。Known limitation：8/10 live case 无 evidence 投影、live coverage 字符串匹配口径、`bc650df` 远程 CI 仍有 1 个 browser Golden Journey 失败。**Decision：RQCE-P0-C5 = PASS / COMPLETE；RQCE-P0 production activation = NO-GO；RQCE-P1 不得自动开始。** 唯一下一步是提交 C5 + 远程 CI 绿 + 人工复审本报告后，进入 P1-A Retrieval Failure Classification（对 8 个 no-projection live case 分类），分类完成前不得直接大改 SearchIntent / Gap Planner。

### 15.26 RQCE-P0-C5-C Harness Closure + Retrieval Failure Classification（2026-08-26，本地未提交）

- **Batch status：PASS / COMPLETE。** 新增 ``tools/run_research_quality_harness_closure.py`` 与 ``tests/test_research_quality_harness_closure.py``；升级 projector 的 unavailable artifact（``_unavailable_case`` 现在生成完整 transcript/retrieval_funnel/typed_failure_reason/stop_reason，成功路径同样带 funnel）；生成 ``docs/research_quality/P0_LIVE_SEMANTIC_EVAL_V2.json``（10/10 artifact 完整）与 ``docs/research_quality/P0_RETRIEVAL_FAILURE_CLASSIFICATION.json``；重生成 20 题报告（含 Live retrieval failure classification 段）。没有修改 production research behavior、WebLookupService、source_assessment.py。
- **Artifact completeness（任务一）。** live 10/10 全部具备 versioned funnel（attempted_queries -> returned -> benchmark_relevant -> role_fit -> scheduled -> successful -> projected docs -> eligible evidence）+ transcript + typed_failure_reason + stop_reason。2 个 unavailable case 不再以"artifact 缺失"表达：duplicate-source-live = ``claim_projection_unavailable:JSONDecodeError,ValueError``、unanswerable-live 同类，均含从 observation 派生的完整 transcript 与零 evidence funnel。frozen 10 fixture 本来就是确定性可重跑。harness closure 全程离线（无 API 调用、无新外发数据）。
- **Retrieval failure taxonomy（任务二，7 个 completed-docs=0 case）。** RELEVANCE_FALSE_NEGATIVE=7；CLAIM_PROJECTION_UNAVAILABLE=2；COMPLETED_WITH_EVIDENCE=1；QUERY_UNDERSPECIFIED=0；PROVIDER_RECALL_MISS=0；SOURCE_ROLE_MISMATCH=0；READ_NOT_SCHEDULED=0；READ_FAILED=0；PROJECTION_REJECTED=0。7 个 case 全部呈现同一漏斗形态：1 query -> 5 returned candidates -> 0 benchmark-relevant -> 0 reads -> 0 docs。对照 simple-factual-live：1 -> 5 -> 5 -> 5 scheduled -> 4 read -> 4 docs。unanswerable-live 虽然 relevance 判 5/5 相关，但 claim projection 两次失败，case 判 CLAIM_PROJECTION_UNAVAILABLE（与 retrieval 无关）。
- **诊断结论收窄（依据 taxonomy）。** 本轮实测中，7/10 案例的断点在 benchmark-relevance 判负（返回了候选但全被过滤），不是 query 缺失（query 均有且仅 1 次）、不是 provider 无返回（均返回 5 候选）。因此当前证据最直接指向 legacy relevance/candidate 区分能力不足；query planning/SearchIntent 仍是候选因素但本轮数据未显示 query 表达缺失。P1 第一刀是否落 relevance/ranking 还是 SearchIntent，由人工复审本 taxonomy 后决定；实现者不得自行宣布唯一根因。
- **Gate 指标解读（报告已区分 harness vs diagnostic）。** 20-case Shadow harness = PASS / COMPLETE（artifact 10/10、报告可重生成）。Research quality diagnostic = NO-GO for production activation：eligible evidence projection 1/10；Gate 在 evidence starvation 下 fail-closed 安全（live caught 7/7 全部因 eligible_support_clusters=0，不是 discrimination 证明）；真实 discrimination 仅 simple-factual-live 1 例验证（shadow pass + primary retrieved）。Frozen：caught 6/miss 1（conflicting-primary 只读一侧无 contradiction，禁止 gold 注入，保留为 P1 counter-evidence 设计输入）。Useful Read Ratio 存在 selection bias（只在易成功页面上 read），不作为 KPI。
- **验证。** C5-C 专项 3/3 + 全 research_quality 回归 96/96；Ruff 通过；C1–C100 守恒 100；``git diff --check`` 通过；mypy baseline 见 15.25（本轮未新增 src/ diagnostics：projector 修改在既有文件内且类型完整）。
- **C5-C Stop report。** Behavior changed：仅 eval harness/artifact/report（V2 artifact、classification、报告 classification 段、projector unavailable artifact 补全）；Behavior intentionally unchanged：legacy query/search/read/relevance/stop/synthesis/persistence/answer/UI 与 WebLookupService；Frozen decisions satisfied：10/10 artifact 完整、typed reason、7-case taxonomy、harness/diagnostic 分离、不注入 gold、不进 P1。**RQCE-P0 production activation 仍 NO-GO；下一步=提交 C5-C + 完整远程 CI + 人工复审报告。**

### 15.27 RQCE-P1-A0 Truth Fix 远程交付 + P1-A1 Preflight（2026-08-27）

- **P1-A0 status：REMOTE GO / DELIVERED。** Truth Fix 最终 HEAD `853d5dade242cad5f0915739e43731139b525ad2`；CI #33002247632 全门禁 success。独立 50-candidate manual audit 将 Provider / production assessor / benchmark surface matcher / independent audit 四层真值拆开；taxonomy 与 report V2 aggregate 静默假 0 已修复。
- **Truth-fixed diagnosis。** Provider=50、production worth_reading=50、benchmark match=10、manual answer-relevant=5/topic-only=10/off-target=35；`NO_ANSWER_RELEVANT_CANDIDATE=7`、`BENCHMARK_MATCH_FALSE_NEGATIVE=0`、`CLAIM_PROJECTION_UNAVAILABLE=2`、`COMPLETED_WITH_EVIDENCE=1`。`RELEVANCE_FALSE_NEGATIVE=7` 是旧 taxonomy 推导错误，历史 15.26 保留当时证据但不再拥有当前结论。
- **P1-A1 scope。** 新增 `src/web/research/gap_planner.py` 与 `candidate_pool.py` 的 pure contracts/logic；每 Gap 2–4 个意图不同的 query，先完整执行 batch 再合并 CandidatePool；复用既有 URL canonicalization、gateway exact-search、cancel/checkpoint。现有 `src.web.query_router.SearchIntent` 是顶层 topic router，P1-A1 使用不同类型名，禁止语义碰撞。
- **P1-A1 non-goals。** 不改 `source_assessment.py`；不把 benchmark `overlap>=2` 写入 production；不施工 semantic rerank、Read Scheduler、Extractor、Gate/stop integration；不接 WebLookupService active adapter；不重新联网或调用模型生成 P0 artifact；不改变 legacy standard/deep path 的 first-nonempty 行为。
- **P1-A1 acceptance。** focused query 不再退化为完整问句；每 batch 2–4 个 intent 且不允许纯同义改写；某 query 的首个非空结果不能终止 planned-query batch；CandidatePool 对 URL canonicalize/dedupe 并保留 query/intent/provider provenance；每 query 前后 cooperative cancellation check + checkpoint；provider failure、empty 与 returned-candidate 真值可区分，而 off-target 判定明确留给后续 rerank；单元/集成回归和全门禁通过。
- **Preflight Decision：GO。** 用户已明确“按最新结论继续”；本节只授权上述窄组件切片。production research 继续 NO-GO，直到后续 active adapter 与独立验收另行冻结。

### 15.28 RQCE-P1 A1–A3 本地大批量组件切片（2026-08-27）

- **批次调整。** 15.27 冻结了 A1 的单独边界；用户随后明确要求减少 CI 往返，先连续完成一大批再统一提交远程。因此本批在不接 runtime 的前提下，顺序扩到 A2 semantic boundary/rerank 与 A3 Read Scheduler；这不回写或扩大 production activation 权限。
- **A1 SearchIntent + CandidatePool。** `gap_planner.py` 每 Gap 生成 2–4 个 discovery/primary/provenance/verification/community/counter-evidence intent；中英文 focused surface 不再直接照搬完整问句。`candidate_pool.py` 跑完整个 planned-query batch，逐 query cancel/checkpoint，区分 unavailable/empty/returned candidates，复用 URL canonicalization 做 cheap filter/dedupe，并保留 query/intent/provider provenance。它不强制 gateway 遍历全部 enabled provider，也不修改 legacy first-nonempty 行为。
- **A2 clustering + semantic boundary/rerank。** `source_cluster.py` 以 explicit origin、quoted source、publisher 的保守顺序生成 scheduling cluster proposal，明确不等价于读后 source-independence 证明。`candidate-assessment-v1` 与 eval projector 完全分离：请求只有 bounded metadata；classifier 只能返回受限 relevance/source-role/gain labels；cluster/freshness/read-cost 由服务端附加；缺项、额外 candidate、未知字段、越界值均 fail closed。rank 顺序固定为 hard requirement → role fit/confidence → semantic relevance/confidence → new cluster → expected gain → freshness → read cost；`off_target` rejected，角色未知保持 `unknown/lead_only`，不制造假角色。
- **A3 Read Scheduler。** Critical 首波最多 3 个独立 cluster、Major 最多 2、Context 默认不主动读；默认保留约 1/3 conflict reserve，open conflict 可释放；仅显式 high-value provenance/primary/contradiction lead 可作为 lead-only 候选进入波次。`budget_exhausted`、`conflict_reserve_held`、soft/hard deadline 分开，所有未读候选保留 deferred truth；规划前后 cooperative cancel，并在成功计划后 checkpoint。预算只读不自增，实际 read 完成后的 durable budget 更新仍由后续 adapter 所有。
- **最终本地证据。** A1–A3 全链覆盖包括“首个非空是 Current dictionary、第二 query 才出现 GitHub 官方文档”：四条 query 必须全部执行，dictionary 经 semantic boundary rejected，官方 primary 成为唯一首波 read。research 回归 224 passed；全量 1317 passed；最终非有限值/边界补丁后 A1–A3 定向 37 passed；Ruff 全库通过；expanded mypy baseline current=122 <= 128；RAG K1 通过；detect-secrets 0 findings；`git diff --check` 通过。package/frontend/browser/real-stack 未在本地重复消耗时间，交由本次唯一远程 CI 从干净 checkout 执行。
- **Non-goals / Decision。** 不改 `source_assessment.py`，不复制 benchmark matcher，不调用 external embedding，不接模型 provider/逐调用外部审计，不实现 active adapter、Extractor、read execution、Gate-after-wave、resume/steering 或 production flag。**Decision：A1–A3 components LOCAL GO / COMPLETE；允许统一提交远程，但远程 CI 未绿前仍 NO-GO for delivery/activation。**
