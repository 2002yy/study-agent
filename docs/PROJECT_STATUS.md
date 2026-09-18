# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-09-13
> 产品定义：**Study Agent 是长期保持“正在学什么、已经确认什么、还不会什么、下一步是什么”的个人学习工作台。**

本文件只维护当前事实、可复核证据、冻结边界和唯一下一步。历史状态全文已归档到 [`archive/PROJECT_STATUS_PRE_RQ1C_CLOSURE_2026-09-08.md`](archive/PROJECT_STATUS_PRE_RQ1C_CLOSURE_2026-09-08.md)；历史内容保留当时的时间语义，不再拥有当前执行权。

## 0. Current Handoff

- **当前 initiative：**Draft PR #142，分支 `codex/rq1c-bounded-qualification`。仓库侧 RQ1-C remediation、DeepSeek structured-output compatibility、一次性 qualification 资产清理均已收口。**严格 provider-faithful Live12 已在 exact clean head `be48a9667c0cd37ef7a2e246617dcc437a0ad3a3` 上真实执行并失败**（见 §7）；首要 blocker 已从"RQ1-C claim/evidence 逻辑未知"收敛为"**provider failure policy 不是 deadline-aware + 本机外部 provider 可用性**"。
- **主线基线：**PR #143 answer/claim binding 已交付到 `main@f3f17824c132e2a88caf4dac4a9d6eae78e35910`；PR #144 仓库清理已以 merge commit `96f8a80e923311e2866a395f32c3ce33a92657df` 合入 main。PR #142 在其上继续 RQ1-C bounded qualification。
- **仓库清理：**`cc7b8d4ee5060676d35c4ca7ed1de8fa0f77b09a` 已退役 13 个一次性 RQ1-C qualification/diagnostic 资产：6 个 GitHub Actions workflow、3 份 trigger 文档、2 个 diagnostic runner、2 个 diagnostic-only tests。长期 runner / rubric / 6+2 reservation / git identity / protocol probes / evaluator / guardrail / runtime core 保留。
- **资格执行位置：**真实 production API qualification 只在**本地 / 手动**执行；GitHub CI 不持有 provider、API key 或 endpoint，也不执行真实 provider Live12。
- **当前唯一下一步（2026-09-15 记录）：**§37A Search Discovery Observability 已实现并验收（`f9fb023`，13 测试）：12/12 case、95 条已发出 query、475 条有界结果全部记录；**机械结论**：query 无重复（95/95 unique）、**变体确实进入 provider**（variant_matches 18/21，否决"Q2/Q3 未生效"猜测）、但每 case 8–10 条不同 query 只换回 **5–10 个唯一 URL**（provider 结果饱和）、`selected_for_harvest=0/475`。⇒ 待人工填 `human_candidate_classification` 与 `human_target_fact_present_after_read` 后，`discovery_rates` 直接给出 `candidate_rate`/`selected_rate`，据此在 §37B 分叉：candidate=0 → Query/Provider Recall；>0 且 selected=0 → 接 pre-H9 `rank_search_results`（接线点已指定，H9 不动）。**reserve 12s、60s、Live12、30s timeout、PARTIAL/PASS、extractor/Gate/answer、read adequacy 全部继续冻结。**
- **exact-head 提醒：**本文件更新提交会使 #142 head 前移；未来正式 Live12 必须以新的 `git rev-parse HEAD` clean head 重新认定 source SHA，不得回用 `be48a96` / `178dbf4` / `f5d12c4` / `4d1ed67` 等旧 head。

## 1. DeepSeek structured-output compatibility closure

### 1.1 已闭环根因

真实 API 探针使用仓库实际常量、实际 manifest 问题和生产 parser：

1. **Planner Probe A：**原 `json_schema + 320 + temperature=0` 请求被 DeepSeek 立即以 HTTP 400 拒绝：`This response_format type is unavailable now`。根因 1 CLOSED。
2. **Planner Probe B：**改为 `json_object` 但保留默认 thinking 后，`finish_reason=length`、`content` 为空、320 output tokens 全被 reasoning 消耗。根因 2 CLOSED。
3. **Planner Probe C：**`json_object + thinking disabled` 可以正常返回，但无 wire schema 时模型自造错误输出形状；严格 `_parse_claim_plan` 正确 fail-closed。
4. **Planner Probe D：**把精确 schema 注入 system prompt 后，59 output tokens、`stop`，经 gateway 真实 `json.loads` + `_parse_claim_plan` 端到端 PASS；320 预算无需放宽。
5. **Candidate-Assessor D：**3 candidates，`json_object + thinking disabled + 动态 schema prompt`，100/220 output tokens、`stop`，真实 `parse_compact_candidate_assessment_response` PASS，恰好 3 rows。
6. **Extractor 第三层根因：**DeepSeek 首次真实 production smoke 镜像输入 envelope（多 `claim_text` / `page`、缺 `caveats`）。修复为 json_object-only provider 注入从 `_EXTRACTION_FIELDS` / `_RELATIONS` 派生的精确输出契约；`_parse_extraction` 一字未放宽，OpenAI/default prompt 不变，900-token budget 不变。

### 1.2 Production compatibility contract

- DeepSeek bounded research structured calls：`response_format=json_object`。
- Planner / Assessor / Extractor：`thinking=disabled`，`temperature=0`。
- Planner token cap = **320**；Candidate Assessor window cap = **220**；Extractor token cap = **900**。
- json_object-only provider 必须在 prompt 中携带与代码 parser 同源的精确结构契约；代码 parser 仍拥有最终 fail-closed 权威。
- 非 DeepSeek / 原支持 strict `json_schema` 的 provider 保持既有 transport 行为。
- 不得把 thinking disabled 扩展为全应用 answer generation 的默认策略。

### 1.3 真实 production smoke

在 source head `8a3ae107b962cfe2f947e7c3aa52ee885a219c85` 上，真实 `ResearchModelGateway` + `RuntimeClaimPlanner` + `RuntimeCandidateAssessor` + `RuntimeEvidenceExtractor` 使用 DeepSeek API 完成三段 smoke：

| Stage | Physical calls | Result | Output tokens | Finish | Parser |
| --- | ---: | --- | ---: | --- | --- |
| planner | 1 | completed | 59 | stop | PASS |
| assessor | 1 | completed | 96 | stop | PASS |
| extractor | 1 | completed | 196 | stop | PASS |

总物理模型调用 **3**，重试 **0**；三段均为 `json_object + thinking disabled`，无 `json_schema` 发往 DeepSeek。planner critical anchor verbatim；assessor 恰好 3 rows 且 candidate identity 未被模型篡改；extractor 的 server-owned ids 不变，locator 与 anchored spans 均被生产 parser 验证位于 excerpt 内。

随后 `06679dd5efe4e69cefd7a186c6561eb8fa5d67b1` 仅增加 fake-client 测试隔离（显式 test timeout），**production tree 未变化**。

## 2. Remote gate closure

source-equivalent exact head `06679dd5efe4e69cefd7a186c6561eb8fa5d67b1` 已取得双 CI 全绿：

- push CI `34242184863` → `completed / success`
- PR CI `34242191710` → `completed / success`

两条 run 均真实执行并通过：pytest、RAG K1、Ruff、package helper、detect-secrets、expanded mypy baseline、frontend test/build、Playwright browser install、Golden Journeys、real-stack browser gates。

关键证据：

- detect-secrets：0 findings。
- mypy baseline：`122 <= 128`，resolved 6，NEW=0。
- 新 structured-capability fake-client tests 不依赖 OpenAI/DeepSeek API key，不做网络调用；此前 CI 的 7 个 `*_API_KEY is missing` 失败已由测试隔离修复，而非通过向 GitHub 添加 secrets 绕过。
- Windows 本地 `user_cancellation` / `unreadable_page` protocol probe `PermissionError` 已在补丁前 head A/B 同样复现；Ubuntu exact-head CI protocol/full suite 通过，登记为 pre-existing local-platform behavior，不修改 production guardrail。

**Repository / compatibility status：REMOTE GO。**

本次文档治理提交是 docs-only closure；它不改变上述 production tree。**在开始 Live12 前，仍必须让本 docs-only 当前 HEAD 自己通过 exact-head CI，并以 `git rev-parse HEAD` 得到的当前 clean SHA 作为 qualification source SHA。**不得回退使用旧 source SHA 伪装 exact-head qualification。

## 3. RQ1-C frozen qualification contract

整体 RQ1-C 仍为 **FROZEN / NO-GO**，直到本地真实 API Live12 满足冻结门。

冻结门不得因 provider compatibility 修复而变化：

- cases >= **12**
- truthfulness = **12/12**
- quality >= **10/12**
- hard failures = **0**
- max candidates = **20**
- max reads = **8**
- max model calls = **8**
- soft timeout = **45s**
- hard timeout = **60s**
- protocol probes required
- final answers 必须来自真实 production answer surface
- 强硬失败继续包括：summary/snippet 冒充 read、repost independence error、strong claim 无 eligible evidence、eval-data leakage

模型调用容量继续锁定为 **6 research + 2 answer reservation**；不得通过缩减 production answer token limit、增加 hosted/local timeout、放宽 parser/Evidence Gate 或修改 rubric 来取得 GO。

## 4. 已作废 qualification evidence

以下证据不得作为 GO：

- 旧 local-hosted surrogate Live12：7/12 reviewable surfaces、5 次 hosted answer timeout cancellation；它只证明 surrogate throughput 不足，**不证明真实 API production path 同样超时**。
- 第一次真实 API Live12 秒败 artifact：12/12 在第一次 research model call 即 `claim_plan_unavailable`；根因已由 DeepSeek `json_schema` 400 + thinking budget 探针闭环，旧 artifact 只保留根因证据，不参与新 GO 判定。
- 任何绑定旧 SHA、脏工作树、临时 diagnostic workflow 或 GitHub provider secret 的 qualification 结果。

## 5. 唯一下一步

1. ~~完成 RQ1-C closure 前最后一个 hardening batch：deadline-aware provider failure policy~~ **DONE（`178dbf4`，§8）**。
2. ~~补一次 DeepSeek V4.1-Flash 三段 structured compatibility smoke~~ **DONE（3/3 PASS，§9）**。
3. 在**本机同一网络环境**（VPN 出口 `23.80.90.156`，provider 仍降级）重跑 Live12：若系统能快速跳过坏 provider 并进入 read/answer，这比"换干净节点跑绿"更强。可选先跑 `python -m tools.run_rq1c_provider_preflight` 快速确认环境。
4. 本地确认 `git status --porcelain --untracked-files=no` 为空，记录 `git rev-parse HEAD`；该 SHA 是新 Live12 唯一 source identity（不得回用 `be48a96` 或 hardening 之前的 head）。
5. 若 artifact 通过冻结门，进入 independent evaluation / qualification closure；随后才允许 default activation 决策以及 PR #142 squash/merge。
6. 若失败，只处理新 artifact 暴露的最小真实 blocker，再从同一冻结门重跑；不得回改已通过的门槛。
7. **暂停换 VPN 节点作为主线**：网络问题已证明是出口 IP 被搜索引擎风控，不是代理传递缺失；换节点属环境恢复手段，非工程解决方案。

## 6. 文档与多窗口纪律

- 本文件是唯一当前进度 owner；不得新增并列长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT 文档。
- 历史完整状态保存在 [`archive/PROJECT_STATUS_PRE_RQ1C_CLOSURE_2026-09-08.md`](archive/PROJECT_STATUS_PRE_RQ1C_CLOSURE_2026-09-08.md) 与 Git 历史。
- 多窗口施工前必须重新读取远端 branch head；只允许 fast-forward，不得 force-push 覆盖另一个窗口。
- Windows Desktop 工作树曾出现一次 checkout exit 0 但 278 个 tracked files 未落盘；checkout 后必须检查 `git status --porcelain --untracked-files=no`，必要时用 `git restore --worktree .` 自愈。pytest 运行期间禁止编辑仓库文件，否则 rq1c clean/exact-head guard 会按设计 fail-closed。
- 本地历史恢复备份 `.git.corrupt-bak/` 与 `study-agent-clean/` 已删除；不再作为恢复来源。

## 7. 严格 Live12 执行事实（2026-09-13）

**执行身份：** exact clean head `be48a9667c0cd37ef7a2e246617dcc437a0ad3a3`（`git status --porcelain --untracked-files=no` 为空；`GITHUB_SHA` 未设置）。runner：`python -m tools.run_rq1c_bounded_qualification`，冻结 manifest `tests/fixtures/research_quality/rq1c_bounded_holdout_manifest.json`。

**结果（严格 Live12，provider 全集）：** `case_count=12`、`partial_runs=12`、`failed_runs=0`、`reviewable_answer_cases=0`、`budget_violation_cases=12`、`runner_error_cases=12`。

- 每例：`stop_reason=evidence_budget_exhausted`、`elapsed 65.7–86.6s`（>60s hard）、`read_count=0`、`model_call_count=1`、`answer=unavailable(production_chat_failed)`。
- 12 例 search 全量 provider 结果统计：`bing_rss` **ok 35/35**（各 5 results）；`duckduckgo_html` **failed/timeout 35/35**；`searxng` **failed/challenge 33、timeout 1、ok 1**。
- 判定：**NO-GO**。首个真实 blocker = **provider degradation 串行重试耗尽 60s hard budget**，在进入 assessment/read 之前即终止；RQ1-C claim/evidence 逻辑本身的 fail-closed 行为正确（gate=partial、answer 被挡）。

**Bing-only diagnostic（非 GO，不作为 qualification evidence）：** 临时在未跟踪 `.env` 关闭 searxng/duckduckgo 后重跑（output 单独文件，未纳入权威 artifact）：

- `reviewable_answer_cases=12`、`budget_violation_cases=0`、`runner_error_cases=0`、`elapsed 21.5–36.0s`（全部 <60s）。
- 但 `gate=block×11 / partial×1`、`stop_reason=evidence_saturated`、`read_count 0–1`、`eligible_evidence=[]`、cluster 0；answer 均为 fail-closed 安全文案（32 字符），`answer_claim_binding` outcome=`rejected`（`missing_evidence_brief`）。
- 意义：证明去掉坏 provider 后 runtime 能在预算内走到 assessment/read/answer；**不能算 qualification GO**，且暴露"预算充足时仍 read_count≈0"的 research-quality 问题（后续单独处理）。

**网络出口事实（2026-09-13）：** Windows 直连 IPv4 `223.12.160.235`；Windows via `127.0.0.1:7890` = VPN `23.80.90.156`；容器 direct / env proxy / explicit `host.docker.internal:7890` **全部 = `23.80.90.156`**。即 Docker 流量已被 VPN 整体接管，代理传递链无缺失；问题为该出口 IP 被 DDG/Brave/Startpage/Qwant engine 风控（Bing RSS 不受影响）。

**Live12 重跑（hardening 后，2026-09-13，clean head `fd4295ee747045d6541f5796fc3b497c2002787d`）：** `partial_runs=12`、`reviewable_answer_cases=9`（此前 0）、`budget_violation_cases=3`（此前 12）、`failed_runs=0`。circuit breaker 生效：每个 case 中 searxng 仅被尝试一次（`challenge`）后本 run 跳过、duckduckgo_html 一次（`timeout`）后跳过，跨 query 累计 `skipped_provider_degraded` 各 67 次，`bing_rss` ok 79；elapsed 45.4–60.1s。**仍非 GO**：全部 `partial / evidence_saturated`，gate `block×10 / partial×2`，`read_count 0–2`、无 eligible evidence，answer 均为 32 字符 fail-closed 安全文案；3 例仍撞 60s hard deadline。**下一个真实 blocker = 研究质量（read/evidence 充分性），不再是 provider budget 耗尽。**

## 8. RQ1-C provider resilience hardening（DELIVERED，`178dbf4`）

**问题（§7 实测）：** 60s bounded preset 下，坏 provider 串行重试（searxng challenge + ddg timeout，各 2 attempts × ~6s/query）即可吃光整轮预算，导致 assessment/read/answer 无预算可用。

**交付（`178dbf4`，仅 production resilience，不改 45s/60s 门、不增预算）：**

- `src/web/research/provider_search.py`：`search_exact(..., deadline=)` deadline-aware 调度——剩余预算 < `MIN_USEFUL_PROVIDER_SECONDS` 时 skip（可观测 reason `skipped_insufficient_budget`）；per-attempt timeout 收敛到剩余预算；transient retry 仅在预算足够时进行；`empty` 不视为 failure、不 retry；failure truth（challenge/timeout/connection）原样保留。
- 单轮 circuit breaker：block 类响应（`challenge` / `http_status:401/403/429`）立即熔断且不 retry；任一 provider 在本 run 最终 `failed` 即标记 degraded，后续 query 以 `skipped_provider_degraded` 跳过（不伪装成 0 results）。
- `src/web/research/active_adapter.py`：`search_detailed(..., deadline=)` 仅对 deadline-aware backend 转发（legacy/测试 backend 不变）。
- `src/application/active_research_runtime.py`：`SEARCH_STAGE_RESERVE_SECONDS = 20.0`，search 阶段 deadline = now + (hard − elapsed − reserve)，为 downstream assessment/read/answer 预留尾部预算。
- 新增 `tools/run_rq1c_provider_preflight.py`：几秒~几十秒跑代表性 query，输出 `qualified` / `degraded` / `unqualified`（exit 0/0/2），避免在已知坏环境下空跑 12-case。
- 故障注入测试：A timeout / B challenge / C success；deadline skip / capped timeout / circuit breaker / empty-not-failure / legacy 无 deadline 行为保持。

**门禁：** focused `tests/test_research_provider_search.py` 20/20、`tests/test_research_active_adapter.py`、`tests/test_rq1c_provider_preflight.py` 全通过；全量 pytest **1746 passed / 2 failed**（两个失败为 Windows 本地既有环境问题，已在父提交 `c029984` 同样复现：`test_rq1c_impl_entrypoints` subprocess `ModuleNotFoundError: src`、`test_rq1c_protocol_probes` 本地 probe；Ubuntu exact-head CI 通过，登记为 pre-existing local-platform behavior）；Ruff all clean；mypy baseline `122 ≤ 128 / resolved=6`。

**真实 preflight 结果（2026-09-13）：** `decision=degraded`，`result_bearing_providers=[bing_rss]`，`degraded_providers=[searxng, duckduckgo_html]`。

## 9. DeepSeek 接口变更（2026-09-10）：V4.1-Flash

- 官方发布 DeepSeek-V4.1-Flash，规范模型名 **`deepseek-flash`**（1M context、输出最大 384K、原生多模态、支持 Json Output）。
- 旧名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` **已下线**，仅兼容路由到 V4.1-Flash（按 Flash 计费）。
- `deepseek-v4-pro`（V4-Pro-0813）仍可用，计费不变。
- **影响：** §1 的 DeepSeek structured-output compatibility closure 是针对 **V4 Flash** 验证的；现在同一模型名实际由 **V4.1-Flash** 提供服务，因此该 closure **不再是"当前模型已验证"的有效证据**，必须用规范名 `deepseek-flash` 重跑三段 structured smoke（planner/assessor/extractor）确认 `json_object + thinking=disabled + schema prompt + strict parser` 仍 PASS。
- **配置收敛（已交付）：** `.env` 与 `.env.example` 的 `DEEPSEEK_MODEL_FLASH_NAME` 由 `deepseek-v4-flash` 改为规范名 `deepseek-flash`（仅模型名，`DEEPSEEK_MODEL_PRO_NAME=deepseek-v4-pro` 与其余 API 参数不动）。代码层不硬编码模型名，provider 层动态解析，因此无需改 adapter。
- **V4.1-Flash 三段 structured smoke（2026-09-13，3/3 PASS）：** 生产 `ResearchModelGateway` + `RuntimeClaimPlanner` / `RuntimeCandidateAssessor` / `RuntimeEvidenceExtractor`，真实 DeepSeek、规范名 `deepseek-flash`：planner `completed` 81 output tokens、assessor `completed` 43、extractor `completed` 135，均 `finish_reason=stop`、attempt 1、strict parser PASS。**协议代码暂不改**：保持 `json_object` + `thinking=disabled` + 精确 schema prompt + strict Python parser，不因 V4.1 新而改用 `json_schema`。

## 10. Evidence-path trace（2026-09-13）：第一个真实 blocker 定位

**工具：** `tools/run_rq1c_evidence_path_trace.py`（复用 runner core 的 production 装配，跑 1–3 个 holdout case，dump durable cursor + monkeypatch `rank_candidate_pool` 捕获 eligibility；只记录结构化原因，不落正文/query 文本）。artifact：`docs/research_quality/RQ1C_EVIDENCE_PATH_TRACE.json`（未跟踪诊断产物，非 qualification evidence）。

**3 个代表 case 结果（clean head `6b06f36` 之上、网络降级、Bing-only）：** 全部 `stop_reason=evidence_saturated`、`planned_read_ids=0`。

| case | 候选 | planned reads | reads | eligibility | relevance | source_role |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `rq1c-current-policy-container-registry` | 5 | **0** | 0 | rejected 11 | off_target 11 | aggregator 11 |
| `rq1c-current-support-postgresql` | 10 | **0** | 2 | eligible 3 / lead_only 3 / rejected 16 | answer_relevant 3 / topic_only 3 / off_target 16 | primary 5 / secondary 4 / aggregator 11 / community 2 |
| `rq1c-numeric-uk-bank-rate` | 10 | **0** | 0 | rejected 22 | off_target 22 | aggregator 21 / community 1 |

**结论：证据链断在候选选择 / assessment 层，不在 reader / EvidenceGate / claim binding（这些根本没被触达）。**

- 机制：Bing RSS 候选大多被 assessor 判为 `relevance=off_target` 且 `source_role=aggregator` → `_eligibility` 返回 `rejected (semantic_off_target)` → `is_schedulable_candidate=false` → `plan_read_wave` 选 0 → 0 reads → gain 全空 → 连续 3 个 no-gain batch → `evidence_saturated`。
- `evidence_saturated` 是**后果不是原因**：不是"提前饱和"，而是"无可调度候选 → 零 gain → 饱和"。stop policy 行为正确。
- `support-postgresql` 证明 assessor **能**产出 eligible（answer_relevant + primary + `new_primary`/`new_provenance_lead` 信号）→ 该 case 有 2 次 read；因此问题不是"assessor 永远全拒"，而是**多数 Bing RSS 结果质量/角色（aggregator）不足以进入可读集合**。
- **下一步：** 见 §11（Lead discovery 路径）。

## 11. Lead discovery 路径（Slice 1 DELIVERED：`ccfbaf8` / `bd9fea5` / `40ce103`）

**概念锁定（用户拍板）：** `Lead = 用于发现 Evidence 的研究资产`；`Lead ≠ weak Evidence`。lead read 永不直接产生 eligible evidence；Evidence eligibility / Gate / 45s-60s / Truth 边界全部不动。`rejected` 候选 v1 永不读取。

**已交付：**

- `src/web/research/lead_discovery.py`：独立契约 `LeadDiscoveryPayload`（`source_candidate_id` / `discovered_urls` / `domains` / `organizations` / `primary_source_hints` / `warnings`），**类型层面不含** claim_support / evidence_strength / eligible_evidence / evidence_id；严格 parser（字段集精确、schema 版本、server-owned candidate_id、http(s) 绝对 URL、数量/长度上限、去重）；`RuntimeLeadDiscoverer`（单次物理调用、`json_object` + thinking disabled + schema 契约、`purpose=research_lead_discovery`、max_tokens 700）。
- `src/web/research/scheduler.py`：新增**独立**确定性谓词 `is_schedulable_lead`（`lead_only` + candidate intent ∩ {primary, provenance, verification} + gap 仍缺 primary + lead budget 可用），**不复用** `_LEAD_SCHEDULABLE_SIGNALS` / `new_provenance_lead`（解开 Evidence gain 与 Discovery 的语义耦合）。
- `src/web/research/runtime.py`：durable cursor 新增 `lead_read_ids` / `lead_discoveries`（严格 round-trip + 向后兼容 setdefault），`MAX_LEAD_READS_PER_RUN = 2`。
- `src/application/active_research_runtime.py`：evidence read 之后执行 **bounded lead read**（每波 ≤1、每 run ≤2），`_lead_read_plan` + `_claim_lacks_primary_evidence`；lead read 计入共享 read 预算与 model call；`policy` deny → `policy_blocked`；失败保留真实 failure code；发现结果写入 cursor（审计/provenance）。

**测试：** `tests/test_lead_discovery.py` 14（parser 拒绝 evidence-shaped 字段、非绝对/不安全 URL、超限、去重；discoverer 成功/空内容不调用/模型失败；调度谓词确定性；cursor round-trip 与 pre-Slice-1 兼容）；`tests/test_active_research_runtime.py` 新增 lead read 集成测试（1 次 lead read → 1 条 typed payload → 无 evidence 字段）。focused 88 passed；Ruff clean；mypy `122 ≤ 128 / NEW=0`。

**未做（Slice 3）：** lead 预算/可观测/故障注入扩展。

## 12. Lead → Discovery 回灌（Slice 2 DELIVERED：`b45ec27` / `1aeea11` / `f758691`）

**目标（用户拍板）：** 把 `LeadDiscoveryPayload` 真正变成新的 discovery 输入，且**严格不扩大 Truth 边界**。

**Slice 2A — URL 回灌（`b45ec27`）：**
- `CandidatePoolItem` / `RuntimeCandidate` 新增 provenance 字段：`parent_lead_candidate_id` / `discovery_method` / `discovery_depth`（cursor 严格 codec + 向后兼容 setdefault）。
- `_lead_discovered_candidates`：`discovered_urls` → `canonicalize_url`（内置 safe/SSRF 校验）→ 去重 → run-level cap `MAX_LEAD_DISCOVERED_CANDIDATES_PER_RUN = 4` → 新候选（继承 parent 的 `query_ids` 以便既有 per-claim 评估路径可见）。
- **Slice 2C**：identity 仍是 canonical URL；`parent_lead_candidate_id` 只是 provenance，不生成平行 identity。
- **Slice 2D**：新候选**无任何特权**——必须重新经过 assessment → eligibility → scheduler。
- 深度护栏：`MAX_LEAD_DISCOVERY_DEPTH = 1`，`_lead_read_plan` 跳过 `discovery_depth >= 1` 的候选，禁止 Lead→Lead→Lead 递归。

**Slice 2B — primary hint 回灌（`1aeea11`）：**
- `plan_gap_queries(..., source_hints=)`：hints 只影响 PRIMARY/PROVENANCE 的措辞（`site:<domain>` + 一个术语 hint，bounded ≤4、≤120 字符）。
- **Gap Planner 仍是唯一 query strategy owner**；hint 不能创建候选、不能改 eligibility（Slice 2E）。
- runtime 通过 `_lead_hints_for_claim` 从 `lead_discoveries` 关联到 claim（parent candidate 的 query_ids → claim）。

**Saturation 交互（Slice 2 必要补充）：** 产生新 lead-discovered 候选的 wave 记为 **discovery progress**，不计入 no-gain batch（否则会在新候选被评估前就饱和停止）。discovery 预算（depth 1、≤2 lead reads/run）保证该延迟有界。

**闭环验收（`f758691`）：** 集成测试证明 `Lead-only candidate → lead read → discovered primary URL（不同域）→ 新 Candidate（provenance）→ assessor → eligible → schedulable evidence read` 全链成立。同域 discovered URL 会被既有 cluster-diversity 正确挡掉（同 publisher 同 cluster），测试用不同域 fixture 覆盖。

**门禁：** focused **135 passed**；Ruff clean；mypy `122 ≤ 128 / NEW=0`。

**未做（Slice 3）：** 见 §13。

## 13. Lead 生产化（Slice 3 DELIVERED：`7f2df71`）

**预算一致性（冻结门槛不动）：** lead read 计入共享 `max_reads=8`（`successful_reads` + `update_budget`）；lead discovery LLM 调用计入 `max_model_calls=8`（经 `model_gateway` 审计 → cursor `model_calls`）。保留 `≤2 lead reads/run`、`≤1/wave`、`depth=1`、`discovered URL cap=4`。集成测试显式断言 `len(lead_read_ids) + successful_evidence_reads ≤ 8` 且 `len(model_calls) ≤ 8`。

**进展语义（显式两条轴）：**
- `evidence_progress = gain.substantive_gain`（冻结的 Evidence gain 契约）。
- `discovery_progress =` 本波新增 lead-discovered candidate **或** 新增非空 discovery 资产（URL/domain/org/hint）。
- 规则：`no_gain_incremented = not (evidence_progress or discovery_progress)`；**discovery progress 只延迟本批 no-gain，不产生 evidence gain、不重置饱和历史**（弱 lead 无法反复续命）。
- 每波写入 `metrics.wave_progress`（`wave_index` / `evidence_progress` / `discovery_progress` / `discovered_candidates_added` / `no_gain_incremented`），有界 `[-MAX_RESEARCH_WAVES:]`。

**可观测性：** `metrics.lead_discovery` 计数器 —— `lead_read_started` / `lead_read_failed` / `lead_discovery_succeeded` / `lead_discovery_failed` / `discovered_candidate_added` / `duplicate_url_rejected` / `unsafe_url_rejected` / `cap_exhausted` / `depth_blocked` / `policy_blocked` / `insufficient_budget` / `no_lead_candidate`。`_lead_discovered_candidates` 返回 `(added, stats)`；`tools/run_rq1c_evidence_path_trace.py` 现在输出 `lead_read_ids` / `lead_discoveries` / `lead_discovered_candidates`（含 `parent_lead_candidate_id`）/ `lead_discovery_metrics` / `wave_progress`。

**故障注入测试（deterministic，不把失败包装成"无结果"）：** parser 拒绝 → `unavailable` + `parse_failed`；模型失败 → `unavailable`；不安全 URL（`javascript:` 等）→ `unsafe_url_rejected`；重复 URL → `duplicate_url_rejected`；run cap → `cap_exhausted`；depth ≥ 1 → `depth_blocked`；空内容 → 不调用模型。focused **145 passed**；Ruff clean；mypy `122 ≤ 128 / NEW=0`。

**优先级（已锁定）：** eligible evidence read > conflict/verification reserve > lead read（lead 排在 evidence read 循环之后，不抢已确定可读的 Evidence）。

**下一步（用户指定顺序）：** ① 先跑 evidence-path trace 3 case，观察 `lead_reads / discovered_candidates / eligible_evidence / gate` 是否真的出现 lead 闭环；② 再跑 Live12。不设 "trace 通过 = GO"。

## 14. Evidence-topology gap 修正（Slice 4 DELIVERED：`b2d1a3d`）+ 首次真实 lead 闭环

**语义修正（用户拍板）：** Lead 调度从"缺 primary 才需要 discovery"改为"只要 Evidence topology 存在可由 discovery 弥补的缺口即可 bounded lead read"：

```text
discovery_gap = missing_primary
             OR (0 < eligible_support_clusters < required_support_clusters)
```

`0/N` **不**触发 cluster 分支（那属于基础 discovery/assessment，不应把 lead 拿去读）。intents 仍为 `{primary, provenance, verification}`；`≤1/wave`、`≤2/run`、`depth=1`、shared budget、优先级（eligible evidence > conflict reserve > lead）全部不变。

**实现：** `evidence_gate.claim_support_topology(state, claim)` 新增为共享只读 helper（Gate 自身流程未改），runtime `_claim_has_discovery_gap` 复用它；新增 drift-guard 测试断言 helper 与 Gate 的 `eligible_support_clusters=x/y` 一致。

**3-case trace（真实 provider，clean head `b2d1a3d`）——边界完全符合预期：**

| case | lead 触发 | 结果 |
| --- | --- | --- |
| `container-registry` | **否** | 无 `lead_only`（全部 off_target→rejected），`no_lead_candidate: 3` |
| `support-postgresql` | **是** | 1 次 lead read → discovery → 新候选 → 被读取 |
| `numeric-uk-bank-rate` | **否** | 无 `lead_only`，`no_lead_candidate: 3` |

**首次真实 lead 闭环（support-postgresql）：**
- `lead_read_ids = ['candidate_b87f957780883c46']`；`lead_discovery_succeeded=1`、`discovered_candidate_added=1`、`duplicate_url_rejected=1`
- 发现资产：`https://www.postgresql.org/download/`、`https://git.postgresql.org`，hints = PostgreSQL 官方下载页 / 源码仓库 / 文档构建 / Software Catalogue
- 新候选带 `parent_lead_candidate_id` + `discovery_method=lead_url` + `discovery_depth=1`，随后被 **assessment → eligible → evidence read**（`read_outcomes` 含该候选，`evidence_id_present=True`）
- `wave_progress` wave 4：`discovery_progress=True, no_gain_incremented=False`（语义按设计工作）
- gate 仍 block（`eligible_support_clusters` 未达 2），但 `eligible_evidence` 2 → 3

**门禁：** focused 82 passed（gate+lead+runtime）；Ruff clean；mypy `122 ≤ 128 / NEW=0`。

**下一个真实问题（用户已锁）：** `off_target` vs `topic_only` 的 assessor/discovery 边界 —— 为什么相关搜索结果被判 `off_target`，以及 Bing discovery 为何无法产生更好的候选（影响 container-registry / numeric-uk-bank-rate）。

## 15. Live12（Slice 1–4 后首轮，clean head `f5d12c4`）：仍非 GO，blocker 已完全收敛到上游

**Artifact：** `docs/research_quality/RQ1C_BOUNDED_QUALIFICATION_RUNTIME.json`（`git_sha=f5d12c4ccd7d564fa675e706ef63521ef0bef767`）；上一轮 `fd4295e` 轮结果备份为 `RQ1C_BOUNDED_QUALIFICATION_RUNTIME.fd4295e.json`（未覆盖）。frozen gate 未改：12 cases / truthfulness 12-12 / quality ≥10-12 / hard failure 0 / candidates ≤20 / reads ≤8 / model calls ≤8 / soft 45s / hard 60s。

**结果：** `reviewable_answer_cases=11`（上轮 9）、`budget_violation_cases=1`（上轮 3）、`runner_error_cases=1`（上轮 3）、`partial_runs=12`、`failed_runs=0`、elapsed 47.3–60.2s。**仍非 GO**：`eligible_support_clusters=0/N` 为 **12/12**，quality / truthfulness 不成立。

**锁定结论（下一阶段不得回头怀疑 Slice 1–4）：**

1. **Provider resilience 已不再是主 blocker**：60s violation 3 → 1；坏 provider 不再吞掉整轮预算。
2. **Lead architecture 已完成并验证正确**：类型隔离 / 回灌 / 预算 / progress semantics / cluster-gap 调度均已通过真实 trace（§14 首次真实闭环）。
3. **本轮 `lead_reads=0` 是 intent gate 正确工作，不是功能失效**：全轮 `lead_only=8`（全部 topic_only），但其 intents 只有 `discovery`，不含 `{primary, provenance, verification}` → `no_lead_candidate`（12/12 case）。
4. **当前唯一主要 blocker 在上游**：95 个 assessment 中 `off_target=86` / `topic_only=8` / `answer_relevant=1`；`source_role` 以 `aggregator=73` 为主；eligible evidence 全轮仅 1。

**下一阶段禁止改动：** Evidence Gate、45s/60s、read/model budget、`rejected → lead`、Lead caps、provider hardening。

**下一阶段问题定义：** 为什么"与主题有关、可能包含 provenance/primary 线索"的 Bing 结果被 assessor 判成 `off_target`，以及 discovery query/result 本身差到什么程度。**先不要改 assessor prompt**：先做 `86 off_target` 的误判率审计，把 `off_target` 拆成 `true_off_target`（搜索真跑题）与 `false_off_target`（相关但被判死），再决定修 discovery 还是修 assessor relevance taxonomy（把 `off_target → rejected` 纠正为 `topic_only → lead_only`，而不是放宽 Evidence eligibility）。

## 16. `off_target` 审计（2026-09-13）：根因是 discovery query 构造，不是 assessor

**方法：** 扩展 `tools/run_rq1c_evidence_path_trace.py` 捕获候选级审计字段（bounded title/snippet/canonical_url/intents/query_ids + `query_index`），对 6 个 case 抽样（47 条 ranked 行）。artifact：`docs/research_quality/RQ1C_EVIDENCE_PATH_TRACE.json`（未跟踪诊断产物）。

**抽样分布：** `off_target 41` / `topic_only 5` / `answer_relevant 1`。

**核心发现：`off_target` 绝大多数是 `true_off_target`，原因是 query 构造，不是 assessor 过严。**

查询文本本身就是不自然的碎片（由 claim 文本拼接 + 后缀堆叠而成）：

- `"pull-rate limits apply unauthenticated users authenticated Personal users on Docker Hub"`
- `"oldest supported major version reach end life 2026"`
- `"on date was that decision announced"`
- `"month it cover"`
- `"Bank Rate was set at recent Bank England Monetary Policy Committee decision 2026"`

搜索引擎因此命中单个单词，返回**词典/百科词条**：Cambridge/百度百科/爱词霸/查查/给力词典 的 `pull`、`oldest`、`date`、`bank`、`month` 词条，PULL&BEAR 服装站，timeanddate，以及"中国银行/北京银行"（bank 字面命中）。这些**确实与 claim 无关**——assessor 判 `off_target` 是正确的。

**混淆矩阵（本轮 47 条抽样，人工初判）：**

| assessor 判定 | true_off_target | topic_related（应 topic_only/lead） | answer_relevant |
| --- | ---: | ---: | ---: |
| `off_target` (41) | **~37** | ~4（runoob PostgreSQL 教程、postgres.ac.cn 文档镜像、gov.uk 门户、visituk 概况） | 0 |
| `topic_only` (5) | 2（百度百科/爱词霸 month 词条） | 3（postgresql.org Downloads、git.postgresql.org、postgres.ac.cn 文档） | 0 |
| `answer_relevant` (1) | 0 | 0 | **1**（postgresql.org 主页） |

→ `off_target` 中约 **90% 为真跑题**；`false_off_target` 约 10%。assessor 总体判对，**不应放宽**。

**结论（下一阶段方向）：**

1. **修 discovery query 构造**（`gap_planner`）：把 claim 文本碎片转成自然检索式；避免后缀堆叠（`official documentation primary source` / `original source announcement`）；优先使用 lead hints（`site:<domain>` / organization / official terminology，Slice 2B 已具备）做锚定。
2. **不要放宽 assessor relevance taxonomy**；`off_target → rejected` 保持。
3. 附带确认：本轮 trace 中 `support-postgresql` 再次出现完整 lead 闭环（1 lead read → 1 discovered → 3 reads），其余 case 因无合适 `lead_only` 而 `no_lead_candidate`。

**禁止改动（延续 §15）：** Evidence Gate、45s/60s、read/model budget、`rejected → lead`、Lead caps、provider hardening。

## 17. Query Construction Hardening（DELIVERED：`a6e30c9`）

**范围（用户锁定）：** 只修 `gap_planner` 如何从 gap/claim 生成检索式；不改 assessor / Gate / Lead / provider / budget；**不新增 LLM query rewriter**。

**交付：**
- 查询从"claim 语法残片 + 后缀堆叠"改为 **显式锚点组合**：`subject_anchor + fact_anchor + 单一 source_anchor (+ year)`。
- 确定性规范化：`_QUERY_FRAGMENT_TOKENS`（代词/助动词/疑问词/限定词/连词/介词-除 of/话语填充词）；所有格剥离；token 去重；≤14 tokens。
- `_query_anchors`：subject = 最长大写 token run（实体，如 `Docker Hub` / `PostgreSQL`）；句首大写不算实体；fact = 其余内容 token；无实体锚时剥掉前导泛时间名词（`date`/`month`/…）。
- 无实体锚的 claim 用 **question surface 提供实体 + claim 提供事实**（避免多 claim 折叠成同一 query）。
- `source_anchor` 每 intent 只取一个（primary=`official docs`、provenance=`announcement`、verification=`independent verification`…；中文 surface 用中文锚），**不再叠加** `official documentation primary source` / `original source announcement`；lead hint 的 `site:<domain>` 优先。
- `PlannedGapQuery.anchored` 暴露"是否含实体锚"，trace 可区分"表面本身弱"与"规范化失败"。

**冻结回归样本（`tests/test_query_construction.py`）：** 审计中的 5 个真实坏例（docker-pull-rate / postgresql-oldest-version / bank-rate-mpc / fragment-date / fragment-month）+ 负面断言（不得只由功能词构成、不得以 `it/that/this/was/on date/month` 残片开头、不得堆叠 primary 后缀、必须保留实体锚或显式标记 `anchored=False`）。

**6-case trace 效果（真实 provider，同一网络）：**

| 指标 | 修复前 | 修复后 |
| --- | ---: | ---: |
| `off_target` 占比 | 87%（41/47） | **68%（21/31）** |
| `topic_only` 占比 | 11%（5/47） | **29%（9/31）** |
| `answer_relevant` | 1 | 1 |
| reads（6 case） | 0/3/0/2/0/0 | 1/2/0/2/0/5 |

典型改善：Docker 查询现在首个候选是 **www.docker.com**（`topic_only/lead_only`、role=primary），词典/百科词条大幅减少；PostgreSQL 查询得到 4 个可用候选（postgresql.org 主页 eligible + Downloads / git.postgresql.org / postgres.ac.cn 文档为 lead_only）。**残留**：`Bank of England …` 仍被搜索引擎匹配到中国银行/北京银行与百科 `Bank` 词条（专有名词歧义），属搜索引擎侧限制。

**门禁：** focused 96 passed；Ruff clean；mypy `122 ≤ 128 / NEW=0`。按用户要求**本轮不跑 Live12**：先确认 query trace 改善（已确认），再决定是否重跑。

## 18. Live12（Query Hardening 后，clean head `4d1ed67`）：评估层大幅改善，blocker 推进到 extraction→Gate 段

**Artifact：** `docs/research_quality/RQ1C_BOUNDED_QUALIFICATION_RUNTIME.json`（`git_sha=4d1ed678…`）；上一轮 `f5d12c4` 结果备份为 `RQ1C_BOUNDED_QUALIFICATION_RUNTIME.f5d12c4.json`。frozen gate 未改。

**Summary：** `reviewable_answer_cases=10`（上轮 11）、`budget_violation_cases=2`（上轮 1）、`runner_error_cases=2`（上轮 1）、`partial_runs=12`、`failed_runs=0`、elapsed 37.1–60.1s。**仍非 GO**（`eligible_support_clusters=0/N` 12/12）。

**评估层对照（f5d12c4 → 4d1ed67）：**

| 指标 | 前 | 后 |
| --- | ---: | ---: |
| `off_target` | 86 | **40** |
| `topic_only` | 8 | **24** |
| `answer_relevant` | 1 | **2** |
| `rejected` | 86 | **40** |
| `lead_only` | 8 | **24** |
| `role:primary` | 3 | **13** |
| `role:authoritative_secondary` | 4 | **9** |
| `role:aggregator` | 73 | **22** |
| reads | 4 | **18** |
| lead_reads | 0 | **1** |
| eligible（assessment 层） | 1 | **2** |
| model_calls | 78 | 81 |

**读到的来源已是对官方域**：`www.docker.com`、`www.postgresql.org`、`www.gov.uk`、`github.com/tukaani-project/xz`、`www.python.org`、`rust-lang.org`、`nodejs.org`。

**新的真实 blocker（已定位到最末一段）：** 官方页面被成功读取，extraction 也成功（`extraction_statuses=["eligible"]`），但产出的是 **`relation="lead"` + 极低 strength（0.05–0.1）+ 诚实 caveat**，例如：

- docker.com → locator `20B+ pulls a month on Docker Hub`，caveat「页面提到 Docker Hub 拉取量，但没有给出未认证/Personal 用户的拉取速率限制」
- postgresql.org → locator `PostgreSQL is a powerful, open source object-relational database system`，caveat「没有提到任何版本号或支持策略」

Gate 的 support cluster 只认 `relation=="supports"` 且 `strength >= STRONG_EVIDENCE_THRESHOLD`，因此 `lead` 链接不计入 → `eligible_support_clusters=0/N`。**这是正确行为**：官方首页确实不含具体事实。

**结论（下一批方向）：** 研究已经"读对了地方"，但停在"首页/入口页"——需要把 **evidence 阶段的 `relation="lead"`（locator/caveat 指向的更深页面）转成下一轮 discovery**（更具体的子页面/文档 URL 或 follow-up query）。注意这与 Slice 1–4 的 lead **candidate** 路径不同：那条路径处理的是 `lead_only` 候选；这里处理的是 eligible evidence 上的 `lead` 关系。

**禁止改动（延续 §15/§17）：** Evidence Gate、45s/60s、read/model budget、`rejected → lead`、Lead caps、provider hardening、assessor。

## 19. Evidence Lead Follow-up（DELIVERED：`71e0a3f` + `be8eea6`）

**触发源（与 Candidate Lead 区分）：** 已读取页面的 extraction 产出 `relation="lead"`（页面相关但不足以 support claim）→ 产生更深层 discovery；**不重读该页、不额外调模型**，只消费已读内容与 extraction 产物。

**交付：**
- `_harvest_page_urls`：从已读正文（≤6000 chars）确定性抽取绝对 URL，`canonicalize_url`（safe URL/SSRF）过滤，排序优先级 = 同域 + claim 关键词 > 同域 > 关键词。
- `_evidence_lead_followup_candidates`：生成 `discovery_method="evidence_lead_url"` 候选（provenance: `parent_lead_candidate_id` = 来源候选，depth ≤1）；**不重读、不调模型**。
- **Admission（第一版就有）**：`≤1 follow-up/wave`、`≤2/run`（`MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_WAVE/RUN`），全部计入共享 reads/model calls/60s；剩余时间 < `EVIDENCE_LEAD_FOLLOWUP_MIN_REMAINING_SECONDS (20s)` → 记 `evidence_lead_followup_skipped_insufficient_budget`，不启动半轮；claim 已有足够 support cluster → 记 `no_support_gap`。
- **Hint 回退（`be8eea6`）**：无 URL 可抽时记录 `hint_domain` + `hint_terms`（bounded），由 `_lead_hints_for_claim` 回灌 Gap Planner（仍是唯一 query owner）→ `site:<domain> <terms>`。
- **Content-scoped query id（`be8eea6`）**：query id 原为 `gap:intent`，hint 改写后的新 query 会因 id 相同被静默丢弃；现在同 `(gap,intent)` 但文本不同的查询获得确定性内容后缀 id，不再被吞。
- Gate 完全未动：`relation="lead"` **永不计入 support cluster**（lead = discovery signal）。
- Progress（延续 Slice 3）：只有新 canonical candidate 或**具体 source hint** 才算 `discovery_progress`；仅改写 query 文本不算。

**Frozen 集成验收（均通过）：**
1. `homepage → extraction lead → follow-up → deeper official URL → 新候选 → assessment eligible → read → extraction supports → Gate clusters 0/2 → 1/2`。
2. 无 URL 可抽时：`follow-up → hint_domain → Gap Planner → site:<domain> 查询`。

**真实 trace（6 case，同网络）：** follow-up 已在 3 个 case 触发（`evidence_lead_followup_started`），但全部 `evidence_lead_no_deeper_url` —— reader 返回的是纯文本正文，不含 URL。因此 hint 回退与 content-scoped query id 是**必需**的（这正是 `be8eea6` 修复的内容）。

**门禁：** focused 148 passed；Ruff clean；mypy `122 ≤ 128 / NEW=0`。**下一步：** 重跑真实 trace，确认 hint 真正产生 `site:` 查询且候选质量继续改善；之后再跑 Live12。

**真实 trace 复跑（`06a19c1`）：** hint 回退已在真实环境生效，`site:` 查询确实进入计划：

- container-registry：follow-up（docker.github.net.cn）→ hint terms `pull-rate/limits/apply/unauthenticated` → `… site:docker.github.net.cn`
- numeric-uk-inflation：follow-up（www.gov.uk）→ `UK Consumer Prices Index CPI latest 12-month inflation rate published Office National Statistics site:www.gov.uk`
- academic-primary-attention：follow-up（blog.csdn.net）→ `Transformer optimizer learning-rate schedule used train site:blog.csdn.net`

`followup_started` 在 3 个 case 触发，全部 `no_deeper_url`（reader 只返回纯文本）→ 全部走 hint 回退。**clusters 仍 0/N**：site 查询尚未在本轮内产出可 support 的更深页面（预算与检索结果的双重限制）。机制链已完整，剩下的是"site 查询能否命中真正含事实的页面"这一经验问题。

## 20. 下一批（明天执行）：Evidence-lead fallback domain policy

**状态：** 已记录，**未开工**。`git_sha` 基线 `1472398`（记录提交之前）。**在完成本批并通过 trace 验收前，不要跑 Live12。**

### 20.1 新发现的确定性缺陷（真实 trace 证据）

fallback 的 `site:<domain>` 锚点**继承"当前 lead 页的域"**，而该域未必是目标事实的权威来源：

```text
Docker      → site:docker.github.net.cn   （镜像域）
CPI         → site:www.gov.uk             （门户域；claim 指向 ONS）
Transformer → site:blog.csdn.net          （聚合域）
```

第 1、3 例尤其明确：一旦把搜索锁死在镜像/聚合域，**再好的 query planner 也不可能找到 primary evidence**——这不是搜索引擎偶然未命中，而是 follow-up 的 search space 被自己错误收窄。当前链：

```text
正确识别 evidence-stage lead
→ 无 deeper URL
→ fallback
→ 用当前页面 domain 当 primary locator
→ site:弱域/镜像/聚合域
→ search space 被错误收窄
→ 仍无 support
```

**结论：** 现在跑 Live12 信息增益低（只会再次证明 `site:docker.github.net.cn` / `site:blog.csdn.net` 找不到 primary）。

### 20.2 修复范围（非常小，只改这一条规则）

> **"当前页面 domain" 不能自动等价于 "应该继续深挖的 domain"。**

按 source role 分流：

| 当前 candidate/source_role | fallback 行为 |
| --- | --- |
| `primary` | 允许优先 same-domain `site:<domain>` |
| `authoritative_secondary` | 保留 domain hint，但**不强制 `site:`**——除非该机构本身就是目标事实的发布主体 |
| `aggregator` / `community` / `independent_secondary` | **禁止**把当前 domain 用作 `site:` 锚；只回灌 organization / entity / official terminology，由 Gap Planner 重新找 primary |

预期结果：

```text
docker.github.net.cn → 不再 site:docker.github.net.cn
                    → "Docker Hub + pull rate limits + official docs"

blog.csdn.net       → 不再 site:blog.csdn.net
                    → "Transformer + optimizer / learning-rate schedule + 原始论文/官方实现实体"
```

`gov.uk` 需按 assessment 的 source role + claim owner 判断：若该页本身是目标政策/统计的正式发布主体可保留；若 claim 明确指向 ONS 而 GOV.UK 只是门户，则不锁死 `site:www.gov.uk`。

### 20.3 数据层护栏（必须同时做）

`site:` 是**强约束**，只应在"有理由相信该 domain 就是 evidence owner"时使用：

```text
trusted_primary_domain → site:<domain>
mere_source_domain     → 普通 hint，不加 site:
```

- 建议在数据层分开 `hint_domain` 与 `trusted_primary_domain`；
- v1 至少让 planner 接收一个 `domain_constraint_allowed: bool`；
- 目的：避免以后再把"见过这个域"与"这个域值得锁定"混为一谈。

### 20.4 验收（本批唯一验收方式）

重跑同一 6-case trace，至少应满足：

```text
docker.github.net.cn → 不再作为 site constraint
blog.csdn.net        → 不再作为 site constraint
真正 primary page    → 允许 same-domain site constraint
```

并观察：`primary/authoritative` 候选比例 ↑、support extraction 是否首次出现。

**升级条件：** 若 trace 出现哪怕一条

```text
homepage/aggregator lead
→ follow-up
→ deeper primary page
→ relation="supports"
→ cluster 0/N → 1/N
```

**则立刻跑 Live12。**

### 20.5 本批禁止改动

Evidence Gate、45s/60s、read/model budget、Lead caps、query hardening、assessor、provider hardening、`rejected → lead`。

### 20.6 交付与验收结果（DELIVERED：`7180740`）

**实现：**
- `plan_gap_queries(..., trusted_domain="")`：**只有显式 `trusted_domain` 才能产生 `site:`**；普通 hint 不再被嗅探成 site 约束（`_hint_fragments` 已移除，改为 `_first_term_hint`，且跳过 domain-like hint）。
- `_bounded_domain` / `_looks_like_domain`：site 值必须匹配域名形态。
- runtime：follow-up 记录 `trusted_primary_domain`（**仅当该页 server-owned `source_role == "primary"`**）与 `hint_domain`（审计用）；`_lead_hints_for_claim` 现在返回 `(trusted_domain, hints)`，只信任两类来源：lead read **发现**的域，或 source role 为 primary 的页面域。cursor codec 同步（`trusted_primary_domain`）。
- 测试：§20 单元回归（mirror 域不可信 / primary 域可信）+ Slice 2B 测试改为同时验证"普通 hint 不产生 site:；显式 trusted_domain 才产生"。

**验收 trace（6 case）：全部达标**

| 观察项 | 结果 |
| --- | --- |
| `docker.github.net.cn` | **不再**成为 site 约束（仅审计字段保留） |
| `blog.csdn.net` / `www.zhihu.com` | **不再**产生 site 查询 |
| `www.gov.uk`（非 primary 角色） | **不再**产生 site 查询 |
| 真正 primary 页（`www.docker.com`、`postgresql.org`） | 允许 same-domain `site:` |

**首次出现真实 support cluster：** `rq1c-current-support-postgresql` → `eligible_support_clusters 0/2 → **1/2**`，`eligible_ev 3`，2 次成功读取（postgresql.org 主页 + 另一页），并有 1 个 lead-discovered 候选（`parent_lead_candidate_id` 链完整）。这是整个 RQCE 会话中第一次由"发现链"走到 supports。

**门禁：** focused 149 passed；Ruff clean；mypy `122 ≤ 128 / NEW=0`。

**触发升级条件（§20.4）→ 立即跑 Live12。**

## 21. Live12（§20 后，clean head `7b6f4aa`）：发现层继续改善，但预算成为绑定约束

**Artifact：** `docs/research_quality/RQ1C_BOUNDED_QUALIFICATION_RUNTIME.json`（`git_sha=7b6f4aa…`）；上一轮 `4d1ed67` 结果备份为 `RQ1C_BOUNDED_QUALIFICATION_RUNTIME.4d1ed67.json`。frozen gate 未改。

**Summary：** `reviewable_answer_cases=8`（上轮 10）、`budget_violation_cases=4`（上轮 2）、`runner_error_cases=4`（上轮 2）、`partial_runs=12`、`failed_runs=0`、elapsed 49.3–60.1s。**仍非 GO**（`eligible_support_clusters=0/N` 12/12）。

**对照（4d1ed67 → 7b6f4aa）：**

| 指标 | 前 | 后 |
| --- | ---: | ---: |
| reviewable answers | 10 | **8** |
| budget violations | 2 | **4** |
| eligible_support_clusters | 0/N ×12 | 0/N ×12（无变化） |
| eligible（assessment 层） | 2 | 2 |
| reads / model_calls | 18 / 81 | 18 / 81 |
| `role:primary` | 13 | 9 |
| `role:aggregator` | 22 | **28** |
| lead_reads | 1 | 2 |
| `evidence_lead_followup_started` | 0 | **8**（全部 `no_deeper_url`） |
| `evidence_lead_followup_cap_reached` | 0 | 3 |
| `evidence_lead_followup_skipped_insufficient_budget` | 0 | 1 |

**判定（对应 §20 预判的第三分支）：** §20 的 domain policy 在 **trace 验收成立**（mirror/aggregator 域不再锁定；primary 域可用；出现首个 support cluster 1/2），但在 **Live12 的成本侧**：8 次 evidence-lead follow-up 全部走 hint 回退 → 生成新的 `site:` 查询 → 触发额外 search/assess/read → **4 个 case 撞 60s、reviewable 下降**，而 cluster 覆盖没有提升。

**结论：** 发现层机制已完整且策略正确，但现在**绑定约束转移到 phase-budget / scheduling**：
- follow-up 产生的 hint 会驱动新查询与候选，其成本没有被独立核算；
- `evidence_lead_followup_cap_reached=3` 说明 admission 已在生效，但仍不足以保护尾部预算。

**下一批（待用户确认）：** phase-budget / scheduling 优化（不是继续加 discovery 功能）。**禁止改动：** Evidence Gate、45s/60s、read/model budget 上限、Lead caps、query hardening、assessor、provider hardening。

## 22. RQ1-C Phase Budget & Scheduling（DELIVERED：`39fb046` + `7384dce`）

**背景（§21）：** 发现层机制已完整，但 follow-up 的边际收益 < 其消耗的尾部时间 → 4 个 case 撞 60s、reviewable 10→8。本批**不加任何 discovery 能力**，只加统一成本—价值调度。

### 22.1 Slice A — Phase Budget Controller（`src/web/research/phase_budget.py`）

- 六类动作与冻结优先级：`evidence_read` P0 > `conflict_read` P1 > `evidence_lead_direct_url` P2 > `evidence_lead_trusted_domain` P3 > `evidence_lead_hint_query` P4 > `candidate_lead` P5。
- 每类动作带**完整链**成本估计（确定性 v1，可后续用真实数据校准）：`ACTION_COST_SECONDS` / `ACTION_REQUIRED_READS` / `ACTION_REQUIRED_MODEL_CALLS`（例如 hint 链 = search + assessment + read + extraction = 28s / 1 read / 2 calls）。
- `FINALIZATION_RESERVE_SECONDS = 12.0`：Gate、answer synthesis、answer binding/auditing、serialization 的尾部保留；进入 reserve 后**禁止启动任何新 branch**。
- `PHASE_RESEARCH_MODEL_CALL_BUDGET = 6`：research 阶段模型调用上限（frozen 8 total − 2 answer reservation）。
- `admit_phase_action(budget, action_type)`：按序检查 reserve → **soft-deadline 优先级闸门**（>P2 的动作在 45s 后停止）→ 完整链 wall-clock → read 余量 → model-call 余量；返回 `PhaseAdmission(admitted, reason, priority, estimated_seconds, required_reads, required_model_calls)`。skip reason 稳定：`finalization_reserve` / `past_soft_deadline` / `skipped_insufficient_phase_budget` / `insufficient_read_budget` / `insufficient_model_budget`。

### 22.2 Slice B/C — 接入 runtime

- **evidence-lead follow-up**：先做免费 harvest，再按可用产物分类为 P2 `direct_url` / P3 `trusted_domain` / P4 `hint_query`，然后 admission；**未获准入时不写候选、不写 hint**（研究树不扩张），只记 skip 计数。取代原先粗糙的 `<20s` 检查。
- **candidate lead**：P5 admission（需最大尾部预算），未准入则跳过该波 lead read。
- **action-level observability**：`metrics.phase_actions`（有界 64 条）记录 `action / priority / estimated_seconds / remaining_seconds_before / remaining_reads_before / remaining_model_calls_before / admitted / skip_reason / outcome`，可据此按动作类型统计 started/completed/eligible/support/time。

### 22.3 Slice D — 故障注入（`tests/test_phase_budget.py`，7 passed）

固定场景：剩 35s → direct URL 可执行；剩 18s → generic hint 被 `skipped_insufficient_phase_budget` 拒绝；剩 10s → 全部 `finalization_reserve`；`reads=0` → `insufficient_read_budget`；`calls=1` → direct URL 可执行但 hint 链 `insufficient_model_budget`；过 soft deadline → P3/P4/P5 `past_soft_deadline`、P0/P1 走自身预算判定；candidate_lead 需最大尾部（35s 时被拒）。

### 22.4 冻结与未动

Evidence Gate、assessor、query hardening、provider resilience、Lead contracts、45s/60s、8 reads / 8 model calls 全部未动。**没有降低 follow-up cap**（仍 ≤1/wave、≤2/run）——先让调度器决定"不值得跑"，cap 是否收紧留给数据。

**门禁：** focused 125 passed + phase budget 7 passed；Ruff clean；mypy `122 ≤ 128 / NEW=0`。

**验收（下一步）：** 重跑 6-case trace → Live12，期望：`reviewable` 回升、`budget violations` 明显下降、60s 碰撞减少、`reads/model calls` 不再盲目增加、且 `support clusters` 不因节流而下降。若 cluster 仍不足，则成本调度层已收口，可继续看证据深度本身。

## 23. Phase Budget 接线回退 + 环境漂移发现（`e78a109`）

**结论：§22 的 admission 接线在真实 Live12 中连续三轮退化，已回退；策略模块与单测保留。**

### 23.1 三轮实验记录（同一网络、同一 frozen gate）

| 状态 | reviewable | budget violations | 备注 |
| --- | ---: | ---: | --- |
| `7b6f4aa`（接线前） | 8 | 4 | §21 基线 |
| `39fb046`（discovery 路径接入 admission） | 4 | 8 | 过严：28s 成本估计让大多数 discovery 被拒 |
| `103c330`（+read 链闸门） | 4 | 8 | 无改善 |
| `04e6140`（+wave 尾部 reserve 停机） | 1 | 11 | 更差：wave 内相位无 deadline 感知，reserve 检查无法阻止单波吃满预算 |
| `e78a109`（回退接线，代码 == `7b6f4aa`） | **1** | **11** | **同代码、同 workload，结果却与 §21 的 8/4 不同** |

### 23.2 关键发现：环境延迟漂移主导 Live12 结果

`e78a109` 与 `7b6f4aa` 的**代码逐字节相同**（`git diff 7b6f4aa -- active_research_runtime.py` 为空），但：

| 指标 | `7b6f4aa` 当年 | 回退后同代码 |
| --- | ---: | ---: |
| reads | 18 | 16 |
| model_calls | 81 | 81 |
| eligible | 2 | 2 |
| `elapsed >= 60s` 的 case | 4 | **11** |

→ workload 几乎一致，wall-clock 显著变长：**provider/API 延迟在这段时间明显上升**。因此 §21–§23 之间三轮回退**至少部分（很可能主要）是环境漂移，而非代码回归**；这些对比当前不可作为判据。

### 23.3 结构性结论（下一批的真正方向）

1. **runtime 的 wave 内相位没有 deadline 感知**：search / assessment / read 循环只受 hard 60s 约束，单个 wave 可以先吃掉 40s+，任何 admission 检查都发生在太晚的位置。这是"最后十几秒没有 answer 时间"的根因，比常数校准更根本。
2. **§22 的成本常数（28s 等）未经真实校准**：在 60s 预算下过严，直接砍掉了曾产出首个 support cluster 的 discovery 能力。校准需要 action-level 数据 + **稳定的环境**。
3. **Live12 在 60s 边界附近是 latency-dominated**：跨 run 比较必须先固定/记录环境延迟基线（例如每次跑前记录 provider preflight 延迟），否则无法归因。

### 23.4 当前状态与建议

- 代码状态：`e78a109` = `7b6f4aa` 的 runtime 行为；`src/web/research/phase_budget.py` + `tests/test_phase_budget.py`（Slice A/D 策略与故障注入）保留且通过，**未接线**。
- 门禁：focused 82 passed（runtime/lead/query/phase_budget）；Ruff clean；mypy `122 ≤ 128 / NEW=0`。
- **建议下一批（不要在环境不稳时做）**：给 wave 内各相位加 research-window 感知（search/assessment/read 循环统一用同一个 stage deadline），再用真实 action-level 数据校准 §22 的成本常数，然后才重新接线 admission；每次 Live12 前记录环境延迟基线以便归因。

## 24. Research Window Deadline Hardening（第一层 deadline safety，DELIVERED：`1be3e18`）

**范围（用户锁定，先做 deadline safety，不做 cost prediction）：** 只保证"一个 wave 无论 provider/model 多慢都不能侵占 finalization window"。**未重新接线 §22 的成本常数**（28s 等值在 60s 预算下过于敏感且无统计基础）。

**交付（Items 1–3）：**
1. **Unified research deadline**：`RESEARCH_WINDOW_RESERVE_SECONDS = FINALIZATION_RESERVE_SECONDS (12.0)` 成为**唯一** reserve；`research_seconds_left() = hard − reserve − elapsed`。原先分开的 `SEARCH_STAGE_RESERVE_SECONDS=20` 已并入同一常量（搜索阶段 deadline 复用同一边界），各层不再各自计算 60s。
2. **Deadline-aware timeout/cancel**：`remaining_timeout()`（planner/assessor/extractor/lead-discovery 所有模型调用）clamp 到 `research_seconds_left()`，不再 clamp 到 hard deadline；wave 顶部新增 `research_window_exhausted()` 守卫 —— 窗口耗尽即停止启动新 wave（复用 `_HardBudgetReached` settle 路径，不新增终态语义）。
3. **Phase telemetry**：`metrics.research_window` 记录 `reserve_seconds / hard_seconds / deadline_elapsed / research_elapsed_seconds / remaining_after_research_seconds / exhausted`，在三条终端路径（crash-resume settle、正常 settle、hard-budget handler）写入并 checkpoint；用于下一批用真实数据校准 reserve，而不是继续拍脑袋。

**明确的边界说明：** 12s 是 **safety reserve，不是已校准的 finalization cost**。它的作用是结构性保证"研究阶段不会吃满 60s"；真实 finalization p50/p90 需要配对运行数据。

**测试：** 新增 `test_research_window_stops_new_waves_before_the_hard_deadline`（合成时钟触发窗口守卫，断言 telemetry 常量与 `exhausted=True`，并明确合成时钟不能替代真实时序证据）；focused **150 passed**；Ruff clean；mypy `122 ≤ 128 / NEW=0`。

**未做（下一批）：**
- **Item 4：environment fingerprint + paired-run harness**（latency baseline snapshot：DeepSeek 三段 smoke 延迟、provider probe 延迟/状态、reader fetch 延迟；以及 A→B→A 少量 calibration cases 的配对运行框架）。这是"性能归因必须建立在可比环境上"的落地工具。
- 用真实 telemetry 校准 reserve 与 §22 成本常数后，再重新接线 cost-aware admission（第二层）。

**当前不做 Live12**：环境不稳（§23 已证明同代码 4 → 11 cases ≥60s），且本批只完成 deadline safety 层。

## 25. Item 4 v1：Environment fingerprint（DELIVERED：`run_environment_fingerprint.py`）

**交付：** `tools/run_environment_fingerprint.py` —— 结构化、可比较的环境快照（**原始数值，绝不降级成 good/bad 布尔**）：

- `deepseek`：planner / assessor / extractor 固定最小 fixture，记录 `elapsed_ms + input_tokens + output_tokens + finish_reason + attempt_count + model_name`
- `providers`：固定 query（`python 3.13 release notes`），逐 provider 记录 `status / reason / attempts / result_count / elapsed_ms`（elapsed 由 per-attempt audit 汇总）
- `reader`：固定轻量官方 URL，记录 `elapsed_ms / ok / content_chars`
- `fingerprint_id`：对测量值取短哈希，便于两轮对比
- 产物：`docs/research_quality/ENVIRONMENT_FINGERPRINT.json`（未跟踪诊断产物）

**首次真实测量（2026-09-14）：**

| 探针 | 结果 |
| --- | --- |
| DeepSeek planner / assessor / extractor | 1203 / 829 / 875 ms（正常，无 429/超时） |
| `bing_rss` | ok，344 ms |
| `duckduckgo_html` | **failed，24016 ms** |
| `searxng` | failed，4094 ms |
| reader | 546 ms |

### 25.1 两个立刻确认的发现

1. **provider 失败成本是预算主消耗，且 timeout 不是真实上限**：DDG 单次 query 失败耗时 **~24s**（2 attempts × ~12s），而配置的 provider timeout 是 **6s**。即失败路径远超配置上界（connect/read 或内部重试未被 6s 完全约束）。加上 searxng 4s，**一条 query 的失败 provider 成本 ≈ 28s** —— 这直接解释了 §23 的 4 → 11 cases ≥60s：环境侧失败成本上升时，Live12 必然恶化。
2. **reader 未受 research window 约束**：`GeneralWebGateway.read` 内部固定 `timeout=10`，runtime 不传 deadline → 与你预判一致，存在"最后一个 reader 跨过 research window"的尾部穿透。本批按约定**只暴露、不修改**（已在工具输出与本节记录）。

### 25.2 下一步（未开工）

- **Item 4 剩余：A→B→A paired-run harness**（3–4 个 calibration cases；fingerprint→A1→fingerprint→B→fingerprint→A2→fingerprint；朴素确定性判据输出 `comparison_status = stable | environment_unstable`；不稳定时**禁止**性能归因）。
- **候选下一批修复**：provider 失败路径必须在配置 timeout 内真正中止（否则任何保留窗口都会被失败成本穿透）；reader 接受共享 deadline。
- 之后才用 telemetry 校准 `FINALIZATION_RESERVE_SECONDS` 与 §22 成本常数。

## 26. Timeout Invariant Hardening（Item 4 前置修复：provider wall-clock 上界 + reader 共享 deadline）

**触发：**§25.1 证明配置的 6s provider timeout 不是 wall-clock 上界（DDG 单 attempt 实测 6.05s / 12.02s），且 reader 完全不受 research window 约束。任何"保留窗口"都会被这两条穿透路径吃掉。

### 26.1 Provider：aggregate deadline 变成真实上界

- **aggregate provider budget：**每个 provider 的**整个生命周期**（attempts + retries）由 `provider_deadline = now + provider_timeout_seconds` 约束；单 attempt timeout = `min(configured, provider_remaining, stage_remaining)`。provider 不再能用"2 × 6s"烧掉 12s。
- **wall-clock 强制：**新增 `_call_with_wallclock`（daemon thread + `join(timeout)`）真正中止等待；超时返回 `wallclock_timeout`（**独立 reason，不并入通用 `timeout`**），被放弃的 worker 既不阻塞 provider 循环也不阻塞进程退出。
- **retry 闸门：**aggregate 余量不足以吸收一次有用 attempt 时不再重试，审计里留 `retry_budget_exhausted`（可观测，不静默）。
- 行为变化被既有故障注入测试捕获并**有意更新**：single-provider 失败成本 12s→6s，三 provider 全坏 24s→18s（§5 的 `fault_injection` / `deadline_prevents_...` 两个 frozen 用例）。

### 26.2 Reader：共享 research window deadline

- `GeneralWebGateway.read(url, *, max_chars, timeout=None)` → `fetch_article_read_result(timeout=int(timeout or 10))`（截断而非进位，绝不越过 deadline）；`ResearchWebGateway.read` 与 `ActiveResearchGateway.read` 逐层转发。
- 兼容性用**签名探测**（`read_gateway_accepts_timeout`）而非强制：legacy gateway / 测试替身只接受 `max_chars` 时自动退回原默认。
- runtime 所有物理 read（证据 read + bounded lead read）统一走 `gateway_read(...)`，传入 `min(10.0, research_seconds_left())`；窗口不足 `MIN_READ_SECONDS` 时不启动新 read 并记 `research_window_skips`。

### 26.3 门禁与真实测量

- focused **130 passed**（provider 22、runtime、adapter、lead、query、phase budget、gateway read codes、github research tools）；全量 pytest 一次 **1792 passed / 2 failed**（两个失败为既有 Windows-local 环境问题：`test_rq1c_impl_entrypoints::test_direct_protocol_internal_execution_cannot_bypass_exact_head_guard`、`test_rq1c_protocol_probes::test_deterministic_protocol_runner_exercises_all_required_probes`，在父提交 `9707d59` 同样复现并已登记）；Ruff 全仓 clean；expanded mypy `current=122 / baseline=128 / resolved=6 / NEW=0`；`git diff --check` clean。
- **同一 fingerprint 工具复跑（2026-09-14，未跑 Live12）：**

| 探针 | §25 首测 | 本批复测 |
| --- | --- | --- |
| `duckduckgo_html` | failed，24016 ms | **failed，6000 ms** |
| `searxng` | failed，4094 ms | failed，4094 ms |
| `bing_rss` | ok，344 ms | ok，328 ms |
| DeepSeek planner / assessor / extractor | 1203 / 829 / 875 ms | 1015 / 1969 / 1329 ms |
| reader | 546 ms | 516 ms |

- **验收：**DDG 失败成本 24016 ms → **6000 ms**（等于配置上界）；一条坏 query 的失败 provider 成本从 ≈28s 降到 ≈10.1s（DDG 6.0 + searxng 4.1）。
- **已知边界（不夸大）：**`skipped_insufficient_research_window` read 守卫在合成 harness 中不可达——窗口耗尽时 wave / evidence-budget 守卫会先终止研究（回归测试断言的正是这个更高层不变量：`read_count=0`、`window.exhausted=True`、`remaining_after > 0`、`stop_reason=evidence_budget_exhausted`）。该守卫按 defense-in-depth 保留；reader 侧已证实的保证是**转发出去的 timeout 上界**（健康窗口下测试断言恰为 `10.0`）。

### 26.4 下一步

1. **Item 4 剩余：A→B→A paired-run harness**（3–4 calibration cases，`comparison_status = stable | environment_unstable`；不稳定禁止性能归因）。
2. 用真实 telemetry 校准 `FINALIZATION_RESERVE_SECONDS` 与 §22 成本常数。
3. 之后才在 clean exact head 上重跑严格 Live12。

## 27. Paired Performance Attribution Harness（`tools/run_paired_attribution.py`）

**冻结规则：环境不稳定时，禁止把性能变化归因给代码。** 本批不是优化性能，而是建立"先证环境、再谈代码"的测量纪律。

### 27.1 结构与锁定项

```text
F0 -> A1 -> F1 -> B -> F2 -> A2 -> F3
```

- `A1`/`A2`/`B` 执行**同一组** calibration case、同一 frozen budget、同一 provider/model 配置；`A` = baseline ref，`B` = candidate ref，两者都 check out 到一次性 git worktree，因此每次运行都绑定 exact 40-char SHA + clean tracked tree（沿用 `rq1c_git_identity` 的 exact-head 语义）。
- `F0`..`F3` 是环境指纹（`run_environment_fingerprint`）。
- **稳定性只看 A1↔A2 的外部依赖基线**（比较紧邻 A 运行的 `F1`↔`F3`），先于任何 case 比较：DeepSeek planner/assessor/extractor、Bing RSS、DDG failure path、SearXNG、reader。判定 = 各 probe 超出 v1 宽松容差（abs 2000/3000ms + rel 1.0）**或** provider 状态/reason 实质变化**或** fingerprint 自身报错 → `comparison_status = environment_unstable`、`attribution_allowed = false`。原始值全部保留。

### 27.2 Calibration cases（全部取自既有 holdout，不造新 workload）

| 标签 | case | 形态 | 选取依据（来自 `7b6f4aa` 历史 artifact） |
| --- | --- | --- | --- |
| C1 | `rq1c-numeric-uk-inflation` | direct-primary | 搜索直达 primary，无 lead 动作 |
| C2 | `rq1c-unverifiable-python-security` | candidate-lead | `lead_discovery_succeeded` + `lead_read_started` |
| C3 | `rq1c-academic-primary-attention` | evidence-lead | `evidence_lead_followup_started`（relation=lead → follow-up） |
| C4 | `rq1c-provenance-xz` | deadline-stress | `evidence_lead_followup_skipped_insufficient_budget`，历史上触及 research window 边界 |

### 27.3 输出（不是只给 reviewable）

- **phase/action delta**：per case 的 search / assessment / read / extraction / discovery 秒数（新增生产 telemetry `metrics.phase_seconds`，纯累加、不改控制流）、research elapsed、finalization elapsed（= total − research）、provider attempts、reads、model calls、lead action 计数、support clusters；全部保留 A1/A2 原始值与 A mean、`B − A` delta、方向标注。
- **`reserve_calibration`**：finalization latency（research stop → run completed）p50 / p90 / max + `sample_adequate_for_reserve`，用于以后按 **finalization**（而不是总 runtime）校准 `FINALIZATION_RESERVE_SECONDS`，规则是 `reserve ≈ p90 + margin`；样本不足时**保持 12s 不动**，先建立测量。
- 产物：`docs/research_quality/PAIRED_ATTRIBUTION.<candidate8>.json`（未跟踪诊断产物）。

### 27.4 技术债登记（非阻塞，用户要求）

**被放弃的 wall-clock worker（`provider_search._call_with_wallclock`）**：超时后 daemon worker 不被等待——这是正确的 wall-clock containment，但底层网络调用可能短暂继续存在。登记观察项：`abandoned_worker_count`、`peak concurrent abandoned workers`、`worker eventually completed`；当前 provider 数量有限、上限低，不阻塞 RQ1-C，但极差网络下多 query 可持续累积后台线程/连接。

**边界检查（当前判定健康）**：worker 只把结果写入**局部**列表，调用方超时后彻底丢弃该结果，不触碰 cursor/审计/共享状态；因此"被放弃的 worker 晚到后修改当前 run 结果"这条风险在现有实现下不成立。若以后 worker 改为写共享对象，必须先加 fence。

### 27.5 首次真实 paired calibration（2026-09-14）

**配置：** A = `0ea2689`（Timeout Invariants，尚无 phase telemetry），B = `37ab2e0`（harness + phase telemetry），4 cases × 3 runs = 12 次真实运行 + 4 次 fingerprint；产物 `docs/research_quality/PAIRED_ATTRIBUTION.37ab2e01.json`。

**A1↔A2 环境基线：`stable`，`attribution_allowed = true`，0 drift、0 provider 状态变化。** 原始值（F0/F1/F2/F3）：

| probe | F0 | F1 | F2 | F3 |
| --- | --- | --- | --- | --- |
| DeepSeek planner | 1250 | 1516 | 1203 | 1625 |
| DeepSeek assessor | 563 | 781 | 922 | 703 |
| DeepSeek extractor | 1125 | 1219 | 1046 | 1078 |
| bing_rss | 391 | 360 | 360 | 328 |
| duckduckgo_html | **6016** | **6000** | **6000** | **6016** |
| searxng | 4109 | 4094 | 4078 | 4093 |
| reader | 687 | 672 | 765 | 531 |

（单位 ms。四轮 DDG 恒在 6s 上界，等于顺带证明 §26 的 wall-clock 不变量在整轮 calibration 中持续成立。）

**Phase telemetry（仅 B；A 的 ref 早于本批）：**

| case | search | assessment | read | extraction | discovery | research 合计 | finalization |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 numeric-uk-inflation | 13.173 | 3.688 | 3.531 | 1.234 | — | 25.141 | 31.124 |
| C2 unverifiable-python-security | 11.844 | 2.109 | 1.125 | 4.282 | 1.578 | 23.766 | 26.672 |
| C3 academic-primary-attention | 11.407 | 1.579 | 1.749 | 4.077 | — | 21.984 | 26.626 |
| C4 provenance-xz | 12.688 | 2.781 | 4.454 | 3.781 | — | 27.078 | 30.781 |

→ **research 内 search 占 ≈50%**（11.4–13.2s / 22–27s），与 §26 的"一条坏 query ≈10.1s"一致。

**reserve 校准（12 个 finalization 样本）：**

```text
finalization  p50 = 26.626s   p90 = 30.781s   max = 31.124s
research      p50 = 23.484s   max = 27.360s
sample_adequate_for_reserve = true（就本轮的 descriptive 统计而言）
```

**这是本轮最重要的发现：**实测 finalization（research stop → run completed：Gate settle + answer generation + binding + serialization）是 **~27–31s**，而 `FINALIZATION_RESERVE_SECONDS` 仍是 **12s**。当前之所以没爆 60s，是因为 research 在 19–27s 就自行结束了（gap/saturation 而非窗口边界），把差额让给了 finalization；一旦 research 真的跑满窗口（48s），finalization 会把总时长推到 ~78s，越过冻结的 60s hard budget。因此**12s 不是"够用的 reserve"，而是尚未被触发的预算缺口**。

**归因纪律（规则生效的直接案例）：** B 相对 A 在两个 case 上 elapsed 高 ~10s（numeric +10.406、provenance +11.156），但 A1↔A2 的组内离散本身就很大（academic finalization 29.578 vs 19.767 = 9.8s；unverifiable 30.703 vs 24.577 = 6.1s；numeric 19.360 vs 23.422 = 4.1s），且 A/B 只差"纯累加 telemetry"。**结论：不作任何代码归因**——这正是本 harness 存在的理由。同理，support cluster 的差异（academic A1 0 / A2 1 / B 2）是内容与模型输出方差，不得读成代码效果。n=1/ref/case 不足以支撑任何显著性主张。

### 27.6 下一步（由测量决定）

1. **把 finalization 拆开测**：当前只有一个总数（27–31s）。需要在 answer stage（generation → binding → serialization）内部加入与 `metrics.phase_seconds` 同构的累加 telemetry，才能定价"一次 answer generation 值多少秒"。
2. **提高每 ref 样本量**（建议每 case 每 ref ≥3 次）后再谈 reserve 数值；在此之前**保持 12s 不动**。
3. **结构性选择（需要用户决策）**：60s hard budget 无法同时容纳"跑满的 research 窗口"和 ~30s 的 finalization。三选一：(a) 收紧 research 窗口使 reserve 真实成立；(b) 降低 finalization 成本（answer 阶段模型调用/绑定轮次）；(c) 调整 60s 预算本身（冻结项，需显式解冻）。
4. 之后才在 clean exact head 上重跑严格 Live12。

### 27.7 状态

```text
Provider Resilience       CLOSED
Lead architecture         CLOSED
Query Construction        CLOSED
Evidence Lead Follow-up   CLOSED
Timeout Invariants        CLOSED
Performance Attribution   DELIVERED（instrument + 首次真实 calibration；归因规则已生效）
Cost-aware Admission      BLOCKED by finalization telemetry split（见 §27.6.1）
Strict Live12 rerun       BLOCKED by §27.6.3 决策
```

## 28. Finalization Breakdown（测量层完成）+ 决定性发现：answer generation 撞 30s 生产超时

**用户决策（本批路线）：**60s hard budget **不解冻**；(a) 是结构上必须成立的 correctness boundary；(b) 是拿到拆分 telemetry 后优先检查的优化方向；在拆分数据出来前**不把 reserve 从 12s 改成拍脑袋的新值**。

### 28.1 测到的真实结构（不发明阶段）

| 段 | 真实归属 | 实现 |
| --- | --- | --- |
| `research` | 含 Gate settle、checkpoint（均在 runtime 内） | `finalization_breakdown.research_seconds` |
| `post_research_projection` | 记录投影（source/brief/cluster/evidence） | runner 计时 |
| `answer_generation` | 生产 `chat(task_name="single_chat")` 物理调用 | guard `_AnswerStageBudget` 计时 |
| `answer_claim_binding` | 生产 binder 物理调用 | 同上（本批 blocked case 下被拒 → 0 次） |
| `artifact_write` | 校准 artifact 序列化 | calibration runner 计时 |
| `answer_stage_tokens` | **不可观测**（生产 chat 边界只返回文本） | 记录 `null`，不编造 |

### 28.2 证据（repeats=3：4 cases × A1/B/A2 × 3 = 36 次真实运行；A=`0ea2689`，B=`63e397f`）

- 环境 `stable`（0 drift、0 provider 状态变化），DDG 四轮恒 6000/6016ms。产物：`PAIRED_ATTRIBUTION.63e397f6.json`、原始 probe `CALIBRATION_BREAKDOWN_PROBE.json`。
- **research**：p50 **22.875s** / p90 25.547 / max 27.828（n=36）。
- **finalization**：p50 **28.531s** / p90 30.798 / max 30.828（n=36）。
- **拆分（B 侧 n=12）**：`answer_generation` p50 **30.094s**、max 30.125；`answer_binding` 0.0（`outcome=rejected, error_type=missing_evidence_brief` → blocked case 不发起 binder 调用）；projection ≈ 0.0；artifact write ≤ 0.016s。

### 28.3 决定性发现（qualification-blocking，比 reserve 问题更靠前）

B 侧 12 次里 **7 次 `answer_generation` 在 30.094–30.125s 以 `RuntimeError` 结束** —— 这是撞上生产 LLM 默认超时（`LLM_TIMEOUT_SECONDS`/`DEEPSEEK_TIMEOUT_SECONDS`，默认 **30.0s**），不是模型自然延迟。原始 probe 直接证据：

```text
rq1c-provenance-xz   elapsed 56.437s
  answer.status = unavailable / reason = production_chat_failed
  runner_error_type = RuntimeError
  answer_generation = 30.094s（单次调用，outcome=RuntimeError）
  answer 文本长度 = 0
```

推论：

1. **§27 的 "finalization p90 ≈ 30.8s" 是被截断（censored）的下界**，不是真实 p90 —— 真实 answer 生成延迟分布被 30s 上限切掉；成功样本里已经出现 29.0s（贴着上限）。
2. 因此 reserve 不能按"30.8 + margin"来定；先要拿到**未被截断**的分布。
3. 这是**验收阻塞项**：generation 超时 → answer unavailable → `reviewable_answer_cases` 不达标（12/12 门槛）。本轮 4-case probe 已复现 1/4；36-run 批次 7/12。
4. 按用户决策树定位：不是"情况 2（冗余浪费）"（binding 0 调用、projection/序列化≈0），而是 **情况 3（调用级 timeout）**——与 §26 的 provider "6s 配置却烧 24s" 同类，只是这次方向相反：**超时太紧，把真实工作切掉了**。

### 28.4 下一步选项（需要用户拍板，本批不擅自改）

1. **先解除截断（推荐第一步）**：只在资格/校准路径提高 answer 阶段 timeout floor（`rq1c_qualification_guardrails` 已有 `answer_timeout_floor_seconds`，本地为 `None`、hosted CPU 才用 120s），拿到真实生成分布后再决定 reserve/(a)。属测量配置，不改产品默认。
2. **同时查生成为何到 30s**：answer prompt/证据块大小、`max_tokens`、模型 profile（是否可用更快 profile）、能否流式分块。
3. **注意与 60s 冻结的交互**：若真实生成 p90 ≈ 35–40s，则 (a) 成立时 research window 只剩 ~15–20s —— 这会显著改变 (a) 的形态，也可能让 (b) 从"优化空间"升级为"必须"。

### 28.5 本批附带修正

第一版 harness 投影缺少 answer 字段，导致 36-run artifact 掩盖了"answer unavailable"这一事实。已修：投影新增 `answer_status / answer_reason / answer_text_chars / binding_outcome / binding_error_type / runner_error_type`（2 个新测试），后续 calibration 不再能隐藏该状态。

### 28.6 门禁（head `eae8aa9`）

focused：`test_paired_attribution.py` 20/20、`test_rq1c_bounded_pre_dispatch_budget.py` 11/11、`test_rq1c_bounded_qualification.py`、`test_rq1c_protocol_probes.py`（后者的 1 项为既有本地失败）；Ruff 全仓 clean；单次全量 pytest **1814 passed / 3 failed**：三项全部属既有 Windows-local 平台族（`test_rq1c_impl_entrypoints` 两项 + `test_rq1c_protocol_probes` 一项，根因均为 cloned/imported checkout 下 `ModuleNotFoundError: No module named 'src'` 与 git identity 子进程行为；`test_dirty_tracked_checkout_blocks_imported_internal_artifact_writes` 单独运行时通过，全量顺序下复现同族失败，本批未触及任何 git identity / clone 逻辑）。

## 29. Untruncated Answer Calibration（诊断路径解除 30s 截断）

**用户决策（本批路线）：**只解除**校准/诊断路径**的 30s 截断；**绝不**把它当成 qualification 配置，也绝不为了让 Live12 变绿而提高资格路径 timeout。提高诊断 timeout 的唯一目的是**测量被截断的真实分布**。

### 29.1 交付与边界

- `tools/run_answer_stage_replay.py`：**每 case 只跑 1 次真实 research**，然后对同一 frozen ResearchRun 做 N 次**真实 production answer generation**（复用 `_production_chat_command` + 同一 production chat service，不做任何 prompt 简化）。
- `make_guarded_run_case(..., diagnostic_limits=...)`：测量 seam；qualification 路径**不传**，冻结的 60s/30s 契约不变；artifact 里 `diagnostic_limits` 明确标注测量用途。
- **deadline invariant 保持成立**：每次调用仍是 `min(configured_or_floor, remaining)`；per-call telemetry 现在记录 `timeout_seconds`、`remaining_at_dispatch_seconds`、`remaining_after_call_seconds`、`message_count`、`message_chars`（只有尺寸，无内容）。
- 所有诊断 artifact：`qualification_evidence = false`。

### 29.2 测量结果

**A. 解除截断（cap 90s / deadline 240s，4 cases × 3 = 12 generations）：**

```text
available = 12/12      p50 = 21.547s   p90 = 27.703s   max = 27.891s
per case: numeric 18.0/16.8/21.5 · unverifiable 18.3/27.7/22.2
         academic 20.9/21.4/15.0 · provenance 24.8/27.9/26.2
```

**B. 同一工具、生产同值 30s cap（再 12 generations）：**

```text
available = 12/12      p50 = 23.547s   p90 = 26.719s   max = 27.703s   → 0 次超时
```

**C. in-situ 复测（生产 limits，4 cases × 1，prompt 规模已入库）：**

```text
numeric        prompt 3548 chars  → 14.172s  ok
unverifiable   prompt 3060 chars  → 22.984s  ok
academic       prompt 4712 chars  → 30.110s  RuntimeError → answer unavailable
provenance     prompt 3118 chars  → 30.125s  RuntimeError → answer unavailable
```

### 29.3 结论（可被证伪的表述）

1. **生成的自然完成成本没有"远超 30s"**：未截断分布 p50 ≈ 21.5–23.5s、p90 ≈ 27s、max ≈ 27.9s（两次共 24 次 generation，12/12 可用）。
2. 但 **30s cap 确实切进了这个分布的尾部**：in-situ 命中率 7/12（36-run 批次）与 2/4（本轮复测），被切掉的样本真实耗时**未知（censored ≥30.1s）**。
3. **prompt 重量不是解释变量**：in-situ 与 replay 的 prompt 规模几乎一致（3060/3548/4712/3118 vs 3060/4090/4732/4590 chars），且失败样本的 prompt 并非最大。"更多 evidence → prompt 更大 → 更慢"在本组（blocked、小 prompt）case 上**不成立**。
4. **deadline invariant 没有被违反**：in-situ 失败样本的 dispatch 余量 ≈ 36s（`remaining_after_call` 5.9 / 9.5s + 30.1s elapsed），`min(30, 36) = 30`，**是 30s cap 而不是窗口把调用切掉的**。
5. **in-situ 与 replay 的差异尚未解释**（同一 cap、同一 case、同时段：replay 0/12 超时 vs in-situ 2/4）。不得手滑归因；下一步候选假设：调用发生的时机（长进程内第 ~20–24s）、客户端重试/socket 行为、跨时段负载。

### 29.4 对 reserve 与决策树的含义

- 未截断 p90 ≈ 27.7–28s → `reserve ≈ p90 + 3–6s margin` ≈ **31–34s**；对应 research window ≈ **26–29s**，而实测 research p50/p90 = **22.9 / 25.5s** → **数学上装得进 60s，但很薄，且系统当前正好工作在这个边界上**。这落在用户决策树的 **A（p90 ≈ 32–35s）**附近，而不是 B/C。
- 但 in-situ 尾部确实存在 ≥30s 的样本（2/4、7/12），(b) 的**正确目标不是"平均生成太慢"，而是"压掉 ≥30s 的尾部/方差"**。
- **reserve 仍未改动（12s）**，60s 继续冻结，Live12 继续冻结：在 (i) in-situ/replay 差异被解释、(ii) reserve 按未截断分布正式校准之前不做参数改动。

### 29.5 下一步（未开工）

1. 解释 in-situ vs replay 差异（同一诊断工具，把 generation 放在 case 时间线的相同位置做 A/B；或对同一 case 连续 in-situ 重复 ≥3 次）。
2. 用未截断分布做一次正式 reserve 校准（(a)），并把 research window 收紧到真实成立的位置。
3. 若尾部/方差确认为主要成本，(b) 转向降低 answer 阶段方差（prompt/输出契约/调用策略），仍以 telemetry 为依据。

## 30. Timeline/Reasoning Probe：in-situ vs replay 差异已解释（隐藏 reasoning）

用户决策（本批路线）：**本批只解决一件事 = 为什么同一 production generation 在 replay 30s cap 下 12/12 成功，而 in-situ 同时段 2/4 精确撞 30s。** 不做 prompt trimming（已被 §29 排除），先观测不修改。

### 30.1 工具

`tools/run_answer_timeline_probe.py`（诊断专用，`qualification_evidence=false`）三种模式：`position`（同一 frozen input 在 3 个时间位置生成）、`insitu-replay`（真实 in-situ 后立刻 replay）、`thinking`（同一 frozen production prompt 下对比 production 默认 vs thinking disabled，直接走 SDK 以便观测隐藏 reasoning tokens）。per-call telemetry 新增 `request_max_retries`（只观测）。

### 30.2 结果（1 个代表 case：`rq1c-academic-primary-attention`）

**position 臂（无位置效应）：**

```text
immediate 21.063s ok · delayed 20.062s ok · delayed2 16.407s ok   → 3/3 成功、无 30s 命中
```

**thinking 臂（决定性）：**

```text
production_default r1 = 59.718s   reasoning_tokens = 4067   ok
production_default r2 = 29.297s   reasoning_tokens = 1775   ok
thinking_disabled  r1 =  3.672s   reasoning_tokens = none   ok
thinking_disabled  r2 =  3.844s   reasoning_tokens = none   ok
```

**retry policy（回答用户的具体问题）：** answer 路径实际传入 **`request_max_retries = 0`**（SDK 内部 retry 被显式关闭，replay/in-situ 两侧一致）→ `30.11s RuntimeError` 是**单次请求超时**的形态，不是 retry 边界。

### 30.3 结论：差异 = reasoning token 采样，不是 prompt / 位置 / retry

1. **answer 路径的 thinking 是开启的**（`_build_request_kwargs` 从不注入 `extra_body`；关 thinking 只用于 structured research 调用）。32 字符的可见答案背后是 **1775–4067 个不可见 reasoning tokens**。
2. 单次 generation 的耗时 ≈ reasoning tokens 量级 → **同 prompt 下 29s vs 60s 的差异只是采样**；30s cap 因此切在分布中部偏上：in-situ 2/4（本批）与 7/12（36-run 批次）与 replay 0/12 的差别是**抽到长 reasoning 的概率差**，不需要额外机制解释。
3. §29 的"prompt 重量无关"得到机制层确认：耗时由隐藏 reasoning 决定，与 prompt 大小/可见输出长度无关。
4. **position 臂无效应**：把同一调用放在 +0/+25/+50s 位置不改变结果 → 排除"长进程/连接生命周期位置效应"。

### 30.4 对 reserve 与 (b) 的含义（重要）

- 不改变现状时：generation 的**可见**分布 p90 ≈ 28s，但 reasoning 尾部可达 60s → `reserve ≈ 31–34s` 只能覆盖 p90，**p99 仍会被 30s cap 切断**；Reserve 单靠数值无法解决（与"成本分布本身不稳定时不能用常数解决"一致）。
- **精确且便宜的 (b) 杠杆已找到**：answer 阶段关闭 thinking（与 research structured 调用同款处理）→ generation 从 ~20–60s 降到 **~3.7–3.8s**（本轮 8–16×），此时 reserve 可降到 ~5–8s，research window 可回到 ~50s 量级。
- **必须显式对待的权衡（未验证）**：关闭 thinking 可能改变答案质量；本轮 case 均为 blocked/conditional（可见答案 32 字符），**无法用质量证据支持该改动**。可选折中：若 provider 支持带 budget 的 thinking 上限，则保留"有限 reasoning"而非直接关闭。
- **reserve 仍为 12s、60s 与 Live12 继续冻结**；任何 timeout/thinking 配置变更都必须先由该 probe 复测分布，再谈 reserve 校准。

### 30.5 下一步

1. 用户决策 (b)：answer path 是否关闭（或限界）thinking；若同意，先只改诊断路径复测分布与答案质量样本。
2. 之后才做正式 reserve 校准（(a)）与 research window 收紧。
3. `insitu-replay` 模式已实现但**不再需要**用于解释本差异（保留备查）。

## 31. Answer Reasoning Policy Diagnostic：(b) 从"优化项"升级为结构性问题

**用户决策（本批路线）：**(b) 必须处理，但**不能一刀切全局关 thinking**；先做分层策略与 A/B 诊断，只改诊断默认，不动 qualification。reasoning 应发生在可审计的 research/evidence pipeline，final answer 更应是 **grounded renderer**。

### 31.1 工具与方法

`tools/run_answer_reasoning_policy_probe.py`（`qualification_evidence=false`）：每个 frozen 真实 research artifact 上跑三臂 —— `A_production`（真实生产 answer path，含 binding/validation 真相）、`A_sdk_default`（同一 frozen messages，SDK 默认 thinking，可观测 reasoning tokens）、`B_sdk_disabled`（同一 messages，thinking disabled）。质量用确定性代理：长度/句数、conditional/fail-closed 措辞、**答案中出现但 evidence 里不存在的数字**。原始文本留档供人工复核。

### 31.2 结果（4 cases，均 gate=block）

| case | A_production | A_sdk_default（n=3，reasoning tokens） | B_sdk_disabled（n=3） |
| --- | --- | --- | --- |
| numeric-uk-inflation | 23.094s（可见 32 字符） | p50 20.734 / max 27.031（874–1020） | p50 **4.390** / max 6.938 |
| provenance-xz | **31.359s**（>30s，生产 cap 下必被切） | p50 36.797 / max 41.328（1546–1917） | p50 **7.968** / max 11.907 |
| current-support-postgresql | 16.140s | p50 31.047 / max 37.016（1343–2083） | p50 **6.656** / max 10.781 |
| historical-current-node-modules | 25.672s | p50 29.281 / max 34.547（1330–1547） | p50 **6.656** / max 6.859 |

→ thinking disabled 快 **4–6×**；默认臂 reasoning 1330–2083 tokens。

### 31.3 BLOCK 分层的结论（强）

1. `A_production` 四例的可见答案**完全相同且固定 32 字符**：`联网检索未通过证据核验，因此回答未采用任何联网来源的结论。` —— 这是**发布门（publication gate）替换后的 fail-closed 表面**，不是模型自己写的文本。
2. 也就是说：**门已经 BLOCK 的 case，answer model 花 1330–2083 个隐藏 reasoning tokens、16–41s，产出的内容随后被门丢弃**。这是纯浪费，且是 30s 截断的来源。
3. **方法学注意（不许夸大）**：`B_sdk_disabled` 臂直连 SDK，**绕过了发布门**，因此它的长文本不是生产会发布的内容；生产同样会把 B 的文本替换成同一句 fail-closed 表面。所以对 BLOCK 而言，"质量等价"是**结构性**结论（用户可见文本由门决定），而不是对两段文本打分的结论。
4. 由此 (b) 在 BLOCK 层有两条路：**(i) answer path 关 thinking**（改动最小，省 10–35s/case，可见行为不变）；**(ii) 完全 deterministic fail-closed surface（不再调用 answer LLM）**——收益更大但属产品行为变更，用户已明确"先不做"。

### 31.4 PARTIAL / PASS 覆盖：本批未取得（测量缺口，不是走捷径）

4 个候选 case（含历史上有 2–3 clusters 的 `current-support-postgresql` / `historical-current-node-modules`）在本轮**全部 gate=block**；历史 artifact 中 gate=partial 仅出现过 1 次、pass 从未出现。因此：

```text
BLOCK        coverage = 4 cases   → 结论可用（见 §31.3）
PARTIAL      coverage = 0         → 待测
PASS         coverage = 0         → 待测
```

**在拿到 gate=partial / pass 的真实 artifact 之前，不得把 BLOCK 的结论外推到 substantive answer**。下一步需要等 research 层真的产出 gate=pass（或 partial 且有 evidence brief）的 run，再用同一工具跑分层 A/B。

### 31.5 reserve 与后续顺序

- 若 BLOCK 分层先落地（thinking disabled 或 deterministic surface），blocked case 的 finalization 将从 ~16–41s 降到 ~4–12s；但 **PARTIAL/PASS 尚未测量**，所以 reserve 依旧**不动**（12s）。
- 顺序保持用户的冻结表：`Answer Thinking Quality A/B（本批 BLOCK 部分完成）` → `决定 answer reasoning policy` → `重新测 finalization 分布` → `再校准 reserve` → `cost-aware scheduling` → `paired validation` → `strict Live12`。
- 产品默认（60s / 30s answer timeout / thinking 开关）本批**未改**；60s 与 Live12 继续冻结。

## 32. BLOCK-only thinking disabled（已落地并生产路径验证）

**用户决策：**现在就落 `Gate=BLOCK → answer thinking disabled`，**只改 BLOCK 分支**；PARTIAL/PASS 保持 production default，不外推；reserve、60s、Live12 继续冻结。理由不是"disabled 文本质量差不多"，而是**结构性事实**：Gate=BLOCK 时无论模型写什么，release gate 都会替换成固定 fail-closed surface，因此那 1330–2083 reasoning tokens / 16–41s 对用户可见结果的贡献严格为 0。

### 32.1 实现（窄边界）

- `src/application/chat_service.py`：抽出与 gate **同源**的两个判定 `_answer_attempt_budget(prepared)` / `_evidence_rows_present(prepared)`（`_gate_research_answer` 也改用它们，杜绝策略与门判定漂移），新增 `_answer_generation_extra_body(prepared)`：
  - BLOCK（无 eligible evidence rows 或 attempt budget < 1）→ `{"thinking": {"type": "disabled"}}`
  - 其他 → `None`（production 默认不变）
  三个生成调用点（`generate` / `stream` / `async_stream_chat`）统一使用该策略。
- `src/llm_client.py`：`chat` / `stream_chat` / `async_stream_chat` 增加**可选** `extra_body`（默认 `None`，其余调用点行为不变）。
- `tools/rq1c_qualification_guardrails.py`：per-call telemetry 新增 `thinking_disabled`，使**生产路径**可被验证而不是假设。
- **answer 调用仍然发生**（6 research + 2 reserved answer 的 qualification accounting 不变）；发布门逻辑完全未动。

### 32.2 防漂移测试（4 个新测试，`tests/test_answer_publication_gate.py`）

1. 无 evidence brief → BLOCK：生成请求显式 `extra_body={"thinking":{"type":"disabled"}}`，**发布 surface 与改动前完全一致**（`RESEARCH_ANSWER_BLOCKED_COPY` + `missing_evidence_brief` 审计）。
2. attempt budget=0 → 同样 disabled。
3. streaming surface 同样注入。
4. **substantive answer（有 evidence rows）→ `extra_body is None`**（防止 BLOCK 策略泄漏到 PARTIAL/PASS）。

### 32.3 生产路径复测（`BLOCK_THINKING_OFF_PROBE.json`，4 cases，生产 limits）

| case | answer_generation 改前 | 改后 | thinking_disabled | 可见 surface |
| --- | --- | --- | --- | --- |
| numeric-uk-inflation | 14.172s | **4.782s** | true | available，32 字符（不变） |
| unverifiable-python-security | 22.984s | **2.719s** | true | available（不变） |
| academic-primary-attention | **30.110s（超时）** | **4.094s** | true | available（不再超时） |
| provenance-xz | **30.125s（超时）** | **5.859s** | true | available（不再超时） |

- **finalization：2.797–5.969s**（改前 16–41s，约 5–8×），**timeout rate 0/4**（改前 2/4）。
- 每例 `answer_claim_binding` 仍为 `rejected / missing_evidence_brief`、0 次 binder 调用，**发布面与审计语义零变化** ✓
- 改后 total elapsed 22.7–29.5s，**research（19.9–23.5s）重新成为唯一主要成本**。

### 32.4 仍未做的事（守住边界）

- **PARTIAL / PASS 未改**，且其 finalization 分布仍未知 → **全局 reserve 仍是"未校准"，保持 12s 不动**。
- 下一步：① 用历史真实 PARTIAL artifact（`4d1ed67` 的 `rq1c-historical-current-node-modules`）做第一份 PARTIAL A/B；② PASS 等真实 artifact（不可 synthetic 冒充质量证据）；③ 之后才重测最终 finalization 分布并校准 reserve → research window / cost-aware admission → paired validation → strict Live12。

## 33. 模型配置对齐 flash + PARTIAL A/B 的测量缺口（历史 artifact 全部为 answer-blocked）

### 33.1 测试/诊断 API 统一到 flash（用户指令 1）

本地 `.env` 存在两处漂移：`DEFAULT_MODEL_PROFILE=pro`、`MODEL_FLASH_NAME=deepseek-v4-flash`（已退役名）。后果：诊断探针用 `get_model_name(None)` 实际测的是 **pro**，而产品 answer path 走的是 **flash**。已修：

- `.env`：`DEFAULT_MODEL_PROFILE=flash`，`MODEL_FLASH_NAME=deepseek-flash`；`.env.example` 显式写出 `DEFAULT_MODEL_PROFILE=flash`。
- `run_answer_reasoning_policy_probe` / `run_answer_timeline_probe`：改为显式 `get_model_name("flash")`；新增测试断言（禁止 `get_model_name(None)`、禁止退役名）。

**方法学更正（不许含糊）：**§30/§31 里 `59.718s / 29.297s`、`reasoning 1775–4067` 等数字是在 **pro** 上测的；§32 的生产路径验证（BLOCK 4.78s → 4.09s 等）本就是 flash ✓。方向性结论（隐藏 reasoning 主导、与 prompt 大小/可见输出长度无关）在 flash 上也成立（同一批 in-situ flash 调用同样是 14–30s+ 且只产出 32 字符），但**具体 token/秒数按模型区分**，后续一律以 flash 数字为准。

### 33.2 历史 artifact 全量扫描：从未产出 substantive answer

对 6 份真实 artifact × 12 case（≈70 次真实运行）逐 case 检查 `answer.status / chars / binding`：

```text
所有成功发布：chars=32（fail-closed 文案），binding=rejected/missing_evidence_brief，binder 调用=0
其余：answer=unavailable（production chat 超时或失败）
gate=partial 的 3 次（academic ×2、historical-current-node-modules ×1）同样落到 missing_evidence_brief
```

根因（可引用）：这 3 次 partial 的 `eligible_evidence` 行**全部是 `relation="lead"`**，而 `research_binding_rows` 只接受 `relation == "supports"` → binding rows 为空 → 发布门直接走 fail-closed。**即 `gate=partial` 在答案阶段未必是"部分可答"，仍可能是 answer-blocked。**

### 33.3 结论：PARTIAL/PASS A/B 现在无法测（不是工具问题）

- 用户要求的第一份 PARTIAL A/B（default vs disabled，判据：supported-claim retention / unsupported leakage / uncertainty preservation / binding outcome）**缺少可用输入**：唯一的历史 PARTIAL artifact 其实是 answer-blocked，用它做 A/B 只会重复测量已经上线的 BLOCK 策略。
- **正面含义**：已上线的 BLOCK 策略覆盖了当前系统**全部**实际产出（含 partial-gate 但 lead-only 的情形）；在 research 尚未产出 `supports` 关系证据之前，答案阶段的 reasoning 优化空间已经被吃完。
- 下一步的杠杆不在 answer policy，而在 **research 能否形成 supports 关系证据**（RQ1-C 证据质量本身）。

### 33.4 新增工具：`tools/run_frozen_answer_ab.py`（带拒跑路径）

- `classify_answer_input(case)`：用与发布门**同一谓词**（`relation == "supports"`）判定 `substantive` / `blocked_no_binding_rows`。
- 非 substantive 且未显式 `--allow-blocked-replay` → 记录 `status=refused_not_substantive` + 原因，**不跑 A/B**（防止以后拿 lead-only artifact 冒充 PARTIAL 实验）。
- substantive 时：从冻结 artifact 重建生产 answer 输入（question、eligible rows、bounded source rows）→ 两臂（production default / thinking disabled）走**真实 production chat service**，输出四类质量判据 + binding outcome + latency；并明确标注 `web_context_source=reconstructed_from_bounded_sources`（artifact 不存 page body，故非逐字节复现；仅诊断，非 qualification 证据）。
- 6 个确定性测试覆盖：lead-only → blocked、supports → substantive、真实 4d1ed67 artifact 判定、拒跑路径、缺失 case fail-closed、诊断标记。
- 实跑证据：`docs/research_quality/FROZEN_AB_PARTIAL_4d1ed67.json` → `refused_not_substantive`（`eligible=2 / binding=0 / lead=2 / gate=partial`）。

### 33.5 未改与下一步

- **reserve 仍 12s（未校准）**；60s、Live12、30s answer timeout、PARTIAL/PASS thinking 策略均继续冻结。
- 等出现真实 `supports` 关系证据的 artifact（即 research 质量改善后）→ 直接 `--artifact <该 artifact> --case-id <case>` 跑锁定判据的 PARTIAL A/B → 再决定 PARTIAL/PASS policy → 之后重测分层 finalization 分布 → 决定 reserve 是否 gate-aware。

### 33.6 门禁与已知闪失败登记（head `38be0ad`）

- focused：`test_frozen_answer_ab.py` 6/6、`test_answer_reasoning_policy_probe.py` + `test_answer_timeline_probe.py` 12/12、`test_answer_publication_gate.py` 20/20（含 4 个 BLOCK 不变量）；Ruff 全仓 clean。
- 全量 pytest 同 head 两次：第一次 `3 failed / 1843 passed`，第二次 `2 failed / 1844 passed`。两次都含既有两项 Windows-local 平台失败（`test_rq1c_impl_entrypoints::…exact_head_guard`、`test_rq1c_protocol_probes::…all_required_probes`）。
- **新登记闪失败（非本批回归）**：`tests/test_chat_research_run_owner.py::test_chat_tool_trace_cancelled_by_owner_turn_cannot_complete` —— 第一次全量失败、第二次全量通过、单文件运行 7/7 通过；该路径为 `WebLookupService` durable ownership + cancel + SQLite，与批内改动（chat_service 策略 / `llm_client.extra_body` / `.env` 模型口径 / tools+tests）无交集。判定：负载相关的本地竞态闪失败（debt，非阻塞），后续如再复现再单独立项。

## 34. 状态再定性（2026-09-15 记录，仅记录、无代码改动）

### 34.1 重新定性

```text
Answer 侧：已知性能问题已基本处理完
（BLOCK 策略已上线并生产验证；PARTIAL/PASS 策略在缺少 supports 证据前无法测）

RQ1-C 主 blocker：回到 Research 侧 —— 如何形成真正的 supports 证据
```

**阶段性结论（重要）：**当前所有**已经真实发布**的 RQ1-C answer 本质上都是 **non-substantive fail-closed surface**（32 字符固定文案，`binding=rejected/missing_evidence_brief`）。也就是说：**到目前为止从未真正测试过"RQCE 有证据之后能不能生成一个好答案"**。下一里程碑因此被明确为：

> **第一份可重复形成 `supports` + `binding rows > 0` + substantive answer 的真实 artifact。**

### 34.2 语义分层（不得再混用）

```text
Research Gate        block / partial / pass
Evidence relation    supports / contradicts / lead
Answerability        substantive / non-substantive
```

三次历史 `partial` 的实际链路：

```text
gate = partial
eligible_evidence > 0            ← 容易被误读成"部分可答"
但 eligible_evidence 全是 relation="lead"
↓
research_binding_rows = 0
↓
answerability = non-substantive
↓
最终 fail-closed（binder 一次都不会被调用）
```

**规则（冻结）：**今后**不得**再用 gate state 直接决定 answer reasoning policy；判据必须是 **answerability**（即 `relation=="supports"` 的 binding rows 是否存在）。`tools/run_frozen_answer_ab.py` 已按此谓词实现，方向正确。

**待做（下一批的一个小 slice，尚未实现）：**把该概念正式落进代码/telemetry（哪怕先只是 derived field）：

```text
answerability: blocked_no_support | substantive
answer_support_rows: <int>
answerable_claim_count: <int>
```

目的：避免以后再次出现"看到 gate=partial → 以为需要做 PARTIAL answer A/B，但 binder 实际上一次都不会被调用"。

### 34.3 方法学锁定：性能 artifact 必须自带模型口径

flash/pro 漂移更正必须保留为**方法学结论**，两套数字**不得**混入同一张 latency distribution：

```text
旧 diagnostic numbers（pro）:      59.7s / 29.3s，reasoning 1775–4067 tokens
production RQ1-C answer（flash）:   in situ 14–30s+；BLOCK thinking-off → finalization ~3–6s
```

**规则（冻结）：**所有性能 artifact 强制带

```text
provider_profile
model_name
thinking_mode
```

缺少这三个字段的 latency 样本**不参加跨实验比较**。

### 34.4 时间表（当前权威版本）

```text
✅ Provider resilience
✅ Query hardening
✅ Candidate Lead
✅ Evidence Lead follow-up
✅ Timeout invariants
✅ Environment attribution
✅ Answer latency root cause
✅ BLOCK-only thinking disabled
✅ flash/pro diagnostic drift corrected
✅ Fake PARTIAL experiment prevented

➡️ Support Formation Audit              ← 当前真正 blocker
➡️ 修 discovery depth 或 extractor（由审计决定）
➡️ 得到真实 supports artifact
➡️ Frozen substantive Answer A/B
➡️ 决定 PARTIAL/PASS reasoning policy
➡️ 建立真实 finalization 分布
➡️ 校准 reserve / research window
➡️ cost-aware scheduling
➡️ paired validation
➡️ strict Live12
```

表述纪律：不要把工作描述成"等真实 PARTIAL/PASS artifact"，准确说法是——

> **主动把 Research 推到第一次稳定产生 `supports`，answer 侧 A/B 工具已经在那里等着。**

### 34.5 下一批施工定义：Support Formation Audit（尚未开工）

目标不是改 Gate、也不是改 answer，而是回答：

> **为什么现在大量研究最终只能形成 `relation="lead"`，而不是 `supports`？**

方法：抽取已 read 成功的官方页样本，按下列表格分类（沿用 `off_target` 审计思路：先区分"上游输入差"还是"判定器错"）：

| Claim | URL | 正文是否实际含目标事实 | extractor relation | 人工判断 |
| --- | --- | --- | --- | --- |
| … | … | 是/否 | lead/supports/contradicts | correct / missed_support / false_lead |

输出两类占比：

```text
A. lead_because_page_lacks_fact     （页面本身没有答案 → discovery depth 问题）
B. false_lead                        （正文已含答案但 extractor 仍给 lead → extractor/support classification 问题）
```

决策规则（先锁死，避免事后解释）：

- 若 ~90% 属 A → 下一刀打 **discovery / deeper-page targeting**（继续 lead → deeper discovery → 真正的 docs/policy page）。
- 若 false_lead 占比明显 → 下一刀打 **extractor contract/prompt**。
- 两者**不得混着修**。

### 34.6 冻结项（本记录不改变任何实现）

- reserve 仍 **12s（未校准）**；60s hard budget、Live12、30s answer timeout、PARTIAL/PASS thinking 策略均继续冻结。
- 今日为**纯记录**：无代码、无参数、无测试变更。

## 35. Support Formation Audit v1（已执行，结论：A 类主导 → 下一刀打 discovery depth）

### 35.1 工具与方法

`tools/run_support_formation_audit.py`（诊断专用，`qualification_evidence=false`）：

- **判定行来自真实 qualification artifact**（extractor 自己的 `relation / strength / locator / anchored_spans / caveats`），不重跑 research、不改任何产品路径；
- **正文用生产 reader 重新抓取**（artifact 按 leakage contract 从不存 page body），记录 `content_chars / content_sha256 / 以 anchor 为中心的 bounded excerpt`；
- 计算确定性提示：`anchor_hits / locator_hit / anchor_numbers_missing_from_page / page_contains_recorded_anchors|recorded_anchors_absent_from_page`；
- **`human_classification` 故意留空**：A（`lead_because_page_lacks_fact`）vs B（`false_lead`）需要人工判定，工具不替人做语义结论。
- 方法学注意：重新抓取的页面可能与原始 run 读到的内容有 freshness 漂移，提示只作复核证据。
- 7 个确定性测试（行提取、anchor 命中/缺失、数字缺失、excerpt 定位与回退、无抓取路径、缺失 artifact 不造假）。

### 35.2 实测（3 份真实 artifact，27 个 eligible-evidence 判定行）

```text
relation 分布        : lead 24 · qualifies 2 · background 1 · supports 0     ← supports = 0
anchor 提示          : page_contains_recorded_anchors 25/27 · absent 2/27
caveat               : 27/27 行都有 caveat，且 27/27 的 caveat 明说"页面不含目标事实"
URL 形态             : root_or_shallow 13/27（docker.com / postgresql.org / gov.uk / nodejs.org / python.org / rust-lang.org）
页面正文 < 400 字符  : 6/27（其中 gov.uk ×3 只有 125 字符 = cookie 同意横幅）
域名                 : 14 个，非官方/镜像/教程/社区居多（runoob 3、csdn 2、zhihu 2、aliyun 1、163 1、juejin 1、docker.github.net.cn 1、node.org.cn 1）
```

典型行（caveat 摘要 = extractor 自己的判定）：

```text
Docker 首页            lead 0.10  "mentions Docker Hub pull volume but does not state any pull-rate limits"
postgresql.org         lead 0.05  "does not mention any PostgreSQL version numbers or support policy"
gov.uk                 lead 0.05  "cookie-consent notice and contains no CPI or inflation data"（正文 125 字符）
python.org             lead 0.10  "only states the latest Python version; does not mention free-threaded Python"
nodejs.org             lead 0.20  "shows only ESM-style import syntax ... does not explicitly enumerate supported module systems"
runoob（PyTorch 教程）  qualifies 0.40  "uses Adam with lr=0.001, not necessarily the original paper"（近似命中，但来源不对）
```

### 35.3 结论（按 §34.5 预先锁死的判据）

- **A 类主导：27/27 行的 caveat 都指向"页面本身没有目标事实"，B 类（false_lead）在本样本为 0。** 且 25/27 的 anchor 在页面中确实存在（说明 extractor 的引用是真实的），`supports=0`。
- ⇒ **extractor/support classification 不是当前瓶颈**；瓶颈是 **页面选择/发现深度**：读到的多是首页、落地页、镜像站与教程/社区页，而不是含目标事实的官方深层页（docs/policy/release/changelog 等）。
- 依锁定规则：**下一刀 = discovery / deeper-page targeting**；**不得**顺手改 extractor（无证据支持）。

### 35.4 附带发现的独立小项（不得与 discovery 混修）

**读取内容充分性（read content adequacy）**：`gov.uk` 三次被判为"已读"的正文只有 **125 字符的 cookie 同意横幅**，却照常进入抽取并产出 `lead`。即读取验收只看 `ok == True and content.strip()`，缺少"是否含实质内容"的门槛/样板检测。登记为独立小项：**要么在读取验收处加最小实质内容门槛/样板识别，要么至少不以这类正文计数为 evidence-bearing read**（涉及 read budget 语义，需单独立项与验收）。样本：6/27 行正文 < 400 字符。

### 35.5 下一批建议（施工顺序，待用户确认）

1. **Deeper-page targeting（主）**：把发现从 root/shallow 与镜像/教程页推向官方深层页——可复用既有 bounded lead/follow-up 机制（`lead → deeper discovery`），并利用 caveat 所揭示的"缺什么事实"来构造定向更深的查询/候选偏好；不得改动 Gate/extractor/answer。
2. **Read content adequacy（次，独立小批）**：正面处理 125 字符样板正文被当作有效读取的问题。
3. 两者完成后重跑 audit 复测（同工具、同判据），目标里程碑仍是 **第一份 supports + binding rows>0 + substantive answer 的真实 artifact**。

## 36. §36A Deeper-page Targeting（已实现并完成首次真实验收；里程碑尚未达成）

### 36.1 冻结范围（用户定义，已严格遵守）

链路：`浅层/近命中页面 → extractor 给出"缺什么" → bounded follow-up → 更深/更权威页面 → 原 extractor 重判`。
**禁止**：改 supports binding predicate、extractor prompt/parser/threshold、Evidence Gate、answer policy、BLOCK/PARTIAL/PASS 语义、research 总预算、物理模型调用数、Lead caps、provider/query hardening、顺手修 125-char cookie 页、人工把 qualifies 升成 supports。

### 36.2 实现（`5e73042`）

- 新增 `src/web/research/deeper_targeting.py`（纯函数、可单测）：
  - `gap_from_extraction`：仅 `relation ∈ {lead, qualifies}` + 有效 locator/anchor + 含 missing-fact 的 caveat 触发；`supports`/`background`/无 anchor/无 caveat 一律不触发；
  - `missing_fact_terms` / `targeted_query_terms`：把 caveat 的**缺失事实**转成正向 query 词（claim 主体最多 3 词，其余留给 gap 词；否定词/填充词被过滤，绝不搜 "does not mention …"）；
  - `authority_class`：只惩罚已知 mirror/tutorial/community 域；**官方身份不靠域名猜**，而由服务端 source role（`primary`）决定 → tutorial 源不会把发现锁死在自己域名；
  - `rank_targeting_candidates`：分层确定性排序，严格遵循用户给的优先级 `authoritative deep page > same official domain deep page > generic deep page > root/landing`（层内软分数 + URL tie-break）；**排序只是发现偏好，relation/strength/binding eligibility 仍由 extractor + Gate 决定**。
- runtime 接线（最小）：触发条件加入 `qualifies`；harvest 后的 URL 用新排序；`hint_terms` 改为 gap-aware 正向词。
- **durable cursor 记录保持冻结的 8-key 形状**（codec 严格校验；实测加字段会导致 resume 失败 → `active_runtime_unavailable`），§36A 诊断改记 `metrics.deeper_targeting`：`followup_reason / source_candidate_url / source_authority_class / targeting_strategy / gap_hint / selected_candidate_url / selected_candidate_depth`。

### 36.3 测试（8 类 + 不变量，全部通过）

official homepage→official deep docs / →policy-support page / →spec-PEP-reference；**unofficial tutorial 不得锁死自己域名**；`already supports` 不触发；`background` 不触发；重复 URL 不占 slot；**caveat 否定表达 → query 只搜正向 missing fact**；同一输入 → 排序确定性一致。另加 runtime 断言：follow-up 记录仍是 8 个 key、`hint_terms` 不含否定词、`metrics.deeper_targeting` 有诊断。

### 36.4 首次真实验收（12 case 全量 probe，`DEEPER_TARGETING_PROBE.json`）

- 运行健康：12/12 case 完成，`budget_contract_violations=0`、`runner_error_cases=0`，总耗时 321.8s（单 case 17.9–39.7s）。
- 审计对比（同一工具/判据）：

| 指标 | §35 baseline | §36A 首次验收 |
| --- | --- | --- |
| rows | 27 | 11 |
| relations | lead 24 · qualifies 2 · background 1 · **supports 0** | lead 10 · background 1 · **supports 0** |
| anchor hit | 25/27 | 11/11 |
| caveat 指出"页面无目标事实" | 27/27 | 11/11 |
| root_or_shallow | 13/27（48%） | 5/11（45%） |
| tutorial/community | 10/27（37%） | 3/11（27%） |
| 正文 <400 字符 | 6/27（22%） | 2/11（18%） |

- **判定：里程碑未达成（supports 仍为 0，binding rows 仍为 0）。** 方向性变化（root/shallow 与 tutorial 占比略降）在 n=11 且非同一 case 组合下**不构成证据**，不据此宣称改善（遵守"不写死百分比目标"的约定）。
- 一个值得记录的正面信号：`provenance-xz` 出现 **`https://github.com/tukaani-project/xz`（CVE-2024-3094 的上游项目仓库）** 行——即发现已能触达官方一手页；但仍判 `lead`，因为该 README 本身不回答"哪些来源构成原始披露"。
- 两个仍未解决、且**不得混修**的旁证：`gov.uk` 125 字符 cookie 正文依旧被当有效读取（read adequacy，独立小批）；本轮多个 case 的 eligible 行为 0（run 间方差）。

### 36.5 三岔口判定（按用户预设规则）

```text
搜到的仍是浅层页 / 深层页仍无目标事实 → 瓶颈仍是 discovery/query targeting → 继续 §36B，不动 extractor
页面只有 cookie/壳内容                → Read Content Adequacy（独立小批 §37）
深层官方页有事实但 extractor 仍判 lead → 才首次出现 B 类 false-negative，才有资格开 extractor repair
```

本轮证据落在**第一条**：页面仍普遍不含目标事实（11/11 caveat 如此），**extractor 依旧无责**；`github.com/tukaani-project/xz` 这类官方一手页已经能触达但内容本身不回答问题。⇒ **下一步 = §36B（继续 discovery/query targeting）**，Read Content Adequacy 作为独立小批待排期。

### 36.6 门禁账目（code head `5e73042`，clean tree）

- focused：`test_deeper_targeting.py` 12/12、`test_active_research_runtime.py` 52/52（含 §36A 诊断与 8-key 契约断言）；Ruff 全仓 clean；mypy `122 ≤ 128 / NEW=0`。
- 全量 pytest（该 head，dirty docs 未提交时执行）：**1861 passed / 4 failed**，逐项定性：
  1. `test_rq1c_impl_entrypoints::…exact_head_guard` —— 既有 Windows-local 平台失败（父提交同样复现）。
  2. `test_rq1c_protocol_probes::…all_required_probes` —— 同上，既有平台失败。
  3. `test_rq1c_protocol_probes::test_protocol_runner_rejects_non_rq1c_runtime_artifact` —— **跑测时工作树 dirty（docs 未提交）造成的 exact-head 契约行为**；提交 docs 后 clean tree 复跑已 **PASS** ✓。
  4. `test_chat_turn_cancellation::test_concurrent_cancel_during_slow_retrieval` —— 负载型并发闪失败；单文件复跑 **32/32 passed** ✓，与本批改动（research discovery 路径）无交集。

## 37. §36B Evidence-bearing Page Discovery（Slice 1+2 已实现；里程碑仍未达成）

用户定义的三刀：① page-intent inference（有界 taxonomy，纯函数，不引入新 LLM 判定器）② bounded query diversification（**在既有 follow-up slots 内**，总 search budget 不变）③ search-result title/snippet 的 missing-fact lexical targeting。明确不做：扩 authority 白名单、crawler、read adequacy。

### 37.1 实现（`5e73042` + `c2b5be0`）

- 新增 `src/web/research/page_intent.py`：9 类有界 taxonomy（`limit_policy / support_lifecycle / feature_status / spec_standard / api_reference / pricing_plan / security_advisory / benchmark_performance / original_source`）、`infer_page_intent`（确定性、**token 边界匹配**、无模型调用）、`query_variants`（≤3 个确定性变体：subject+missing fact / +page-intent / +docs；无否定词、去重、硬上限）、`lexical_targeting_score` + `targeting_preference_key` + `rank_search_results`（title/snippet 的 missing-fact 覆盖，**authority 优先于 lexical**，防 tutorial 靠词面压过权威页）、`selection_reason`。
- runtime：由 §36A gap 推导 intent + variants；第一个 variant 写入**冻结的** `hint_terms` key；`page_intent / query_variants / selected_query_variant / selection_reason` 记入 `metrics.deeper_targeting`；cursor 8-key 契约不变。
- **本轮诊断自身暴露并修复两个真实缺陷**（`c2b5be0`）：① 子串匹配导致 `learning-rate` 误命中 `rate`（academic→limit_policy）、`prices` 误命中 pricing（CPI→pricing_plan）→ 改为 token 精确匹配；② caveat 无否定模式时回退成原始 caveat 文本当 query 词（出现 `runoob.com`/`third-party` 垃圾词）→ 无 absence clause 时不再产出 missing-fact 词，query 只用 claim 词 + intent。
- 测试：`test_page_intent.py` 17 + `test_deeper_targeting.py` 13（含 8/11/12 类要求、`budget 不增长`、**tutorial 高词面不得压过权威页**回归、两个负控）；runtime 断言诊断键在册。Ruff clean；mypy `122 ≤ 128 / NEW=0`。

### 37.2 首次真实验收（两轮，12 case 全量 probe）

| 指标 | §35 baseline | §36A | §36B r1 (`PAGE_INTENT_PROBE`) | §36B r2 (`PAGE_INTENT_PROBE2`) |
| --- | --- | --- | --- | --- |
| rows | 27 | 11 | 12 | 12 |
| relations | lead 24 · qualifies 2 · background 1 · **supports 0** | lead 10 · background 1 · **0** | lead 11 · background 1 · **0** | lead 11 · background 1 · **0** |
| caveat 指出页面无目标事实 | 27/27 | 11/11 | 12/12 | 12/12 |
| root_or_shallow | 48% | 45% | 50% | 58% |
| tutorial/community | 37% | 27% | 25% | 17% |
| binding rows | 0 | 0 | 0 | 0 |

- 两轮 12/12 case 均健康（0 budget 违规、0 runner error，总耗时 ~333s/343s）。
- **live 诊断证明 Slice 1 真的在运行**：`page_intent_counts = {support_lifecycle 2, limit_policy 2, pricing_plan 1, feature_status 1, spec_standard 1}`；每例产出 ≤3 个变体（例如 `postgresql major versions supported version support` / `… support versioning` / `… support docs`）；`selection_reason = page_intent_match 7 / fallback_order 1`。
- **判定：§36B PASS as implementation / FAIL as milestone**（`supports` 仍 0、binding rows 仍 0）。审计同时显示 extractor 的 caveat 现在会**直接点名页面性质**（"marketing copy from Docker's homepage"、"general homepage introduction"、"product marketing page"、"third-party tutorial page"），与 §35 的"页面不对"结论一致。

### 37.3 未解决：recall vs ranking 仍无法分离（下一批的仪器缺口）

§36B 的验收指标 `target_fact_candidate_rate`（搜索结果里是否**出现过**可能承载目标事实的候选）与 `target_fact_selected_rate`（它是否**被选中**读取）目前**算不出来**：qualification/诊断 artifact 都不存 search result 的 title/snippet（只有被选中/读取的 `sources`）。

⇒ 下一批的**第一步是补仪器**（诊断产物，非 qualification）：在 calibration/diagnostic artifact 中记录有界的候选 `title/snippet/url`（仅尺寸与文本片段，标注 diagnostic-only），然后 audit 工具据此产出上述两个 rate。只有这两个 rate 出来，才能判定：

```text
搜索结果里根本没有正确页面 → 继续 query/discovery（§36C）
搜索结果里有正确页面但没被选中 → 下一刀是 ranking（且需要指定一个非冻结接线点）
正确页面被选中且读到事实但 extractor 不支持 → 首次进入 extractor 分支
```

附注：title/snippet 排序（§36B 第三刀）的**唯一候选排序位置是冻结的 H9 scheduler**（`candidate_ranking.rank_candidate_pool`，产出 eligible/lead_only 语义），因此它需要一个明确指定的非冻结接线点才能接入；`page_intent.rank_search_results` 已作为纯函数就绪并测试完毕，等待该接线点。

### 37.4 冻结项

- reserve 12s、60s、Live12、30s answer timeout、PARTIAL/PASS thinking 策略、extractor/Gate/answer、research 总预算与物理模型调用数、Lead caps、read adequacy（§37 独立小批）均**未改动**。

## 38. §37A Search Discovery Observability（已实现并完成首次真实验收；recall/ranking 首次可分离）

**用户冻结的 contract：**只增加**有界**的 search-result 可观测性——记录实际发出的 query variant 与 provider 返回的有界 `title/snippet/url`、机械 targeting 信号、selected/read 状态；**不改变**任何搜索、排序、预算、资格或回答行为；人工 audit 计算两个 rate，从而正式区分 recall 与 ranking。

### 38.1 实现（`f9fb023`）

- 新增 `src/web/research/discovery_observability.py`（纯函数、13 测试）：
  - `record_search_call` 每个**实际发出的 query** 记一条有界记录：`slot_index / query_sha256 / query_chars / query_excerpt / claim_id / page_intent / generated_query_variants / variant_matches / hint_terms`，以及 provider Top-K（默认 5）的 `result_rank / url / title(≤200) / snippet(≤240) / provider / authority_class / lexical_targeting_score / selection_reason`；
  - `human_candidate_classification / selected_for_harvest / selected_for_read / read_status / final_relation / final_caveat` **一律留空**（工具不宣布"这是正确页面"）；
  - 上限：queries ≤24、results ≤Top-K；同输入**确定性**输出；空结果也记录（"没有召回"≠"没有观测"）；异常 payload 不抛错。
  - `issued_variant_coverage`：生成的 variant 中有多少**真的**与已发出 query 有机械词面重叠。
- runtime：在既有 `search_exact` 闭包内 **observe-then-return**（payload 不变）；`intent/variants` 取最近一条 §36A/§36B 诊断（近似关联已在代码注释与文档说明，且逐条查询的 `hint_terms` 是精确的）。
- audit 工具新增 `search_discovery`（按 URL 与 harvest/read/extraction 连接）+ `discovery_rates`：`target_fact_candidate_rate` / `target_fact_selected_rate` / `target_fact_present_after_read`，在人工字段未填时显式返回 `pending_human_classification`。

### 38.2 首次真实验收（12 case，`SEARCH_DISCOVERY_PROBE.json` → `SUPPORT_FORMATION_AUDIT.after_37a.json`）

```text
观测覆盖        : 12/12 cases，95 条已发出 query，475 条有界结果
query 重复率    : 95 issued / 95 unique = 0%（无重复查询）
variant 覆盖    : generated 21 / matched 18（变体确实影响了已发出 query）
result 饱和度   : 每 case 8–10 条不同 query 只得到 5–10 个唯一 URL（provider 反复返回同一批浅层页）
authority 分布  : unknown 327 · tutorial 130 · mirror 18
selected_for_harvest = 0/475（§36A harvest 路径本轮未选中任何结果）
selected_for_read    = 154/475
rates           : status = pending_human_classification（等人工标注）
```

**机械结论（不需要人工即可成立）：**

1. **"Q2/Q3 没进 provider"的猜测被否决**：95/95 query 唯一，且变体形态（`… official docs` / `… announcement` / `… independent verification`）都真实出现在已发出 query 中；`variant_matches` 18/21。
2. **召回天花板在 provider/query 层**：同一 case 的 8–10 条不同 query 只换回 **5–10 个唯一 URL**（Docker 例：docker.com / docker.github.net.cn / runoob 反复出现；PostgreSQL 例：postgresql.org / postgresql.org/download / runoob），即**查询多样化没有扩大结果空间**。
3. `selected_for_harvest=0` 说明 §36A/§36B 的 harvest 排序在本轮**几乎不参与**；被读取的 154 条来自既有 pool 选择（H9），与 §35 的"页面不对"一致。

**待人工填写后才能判定的两项**（工具已就绪）：`human_candidate_classification`（`likely_target|near_hit|irrelevant|unknown`）与 `human_target_fact_present_after_read`。填完后 `discovery_rates` 会直接给出：

```text
candidate_rate = 0            → Recall（§37B query/provider recall）
candidate_rate > 0, selected=0 → Ranking（接 pre-H9 rank_search_results）
selected 且正文无事实          → Discovery precision（继续 page targeting）
selected 且正文有事实但 lead    → 首次允许动 extractor
```

### 38.3 下一批分叉（按你的矩阵，等人工 rate 后执行）

- 若 `target_fact_candidate_rate` 为 0 → **§37B Query/Provider Recall**（换查询空间/查询形态，注意 provider 结果饱和是机械证据）。
- 若 >0 且 `selected_rate` 低 → **接 `rank_search_results`**，接线点已由你指定：`normalized search results → [rank_search_results] → bounded URL harvest → candidate construction → H9(不动)`。
- `read adequacy` 与 `extractor` 两条支线继续冻结，直到对应证据出现。

### 38.4 冻结项（未改动）

reserve 12s、60s、Live12、30s answer timeout、PARTIAL/PASS 策略、extractor/Gate/answer、研究预算与物理模型调用数、Lead caps、H9 scheduler、read adequacy。















