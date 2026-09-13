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
- **当前唯一下一步：**hardening batch 已交付（`178dbf4`）并已重跑 Live12（`9/12` reviewable，budget violation `12→3`，§7）；**第一个真实 blocker 已定位为候选选择/assessment 层**（Bing RSS 候选被判 `off_target`+`aggregator` → `rejected` → 0 reads → 饱和；见 §10），不是 reader / Gate / stop policy。下一步在该链上做最小真实修复，不改 Gate、不改 45s/60s 门。
- **exact-head 提醒：**本文件更新提交会使 #142 head 前移；未来正式 Live12 必须以新的 `git rev-parse HEAD` clean head 重新认定 source SHA，不得回用 `be48a96` 或 `178dbf4` 之前的 head。

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
