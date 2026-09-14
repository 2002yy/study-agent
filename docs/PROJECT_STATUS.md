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
- **当前唯一下一步（2026-09-14 记录）：**Finalization Breakdown 已完成（§28）：真实拆分显示 **answer_generation 就是 finalization 的全部成本**（binding 在 blocked case 下 0 次调用；projection/序列化 ≈0），且 **12 次里 7 次在 30.09–30.13s 撞上生产 LLM 30s 默认超时 → `answer.status=unavailable`** —— 之前测到的 p90≈30.8s 是**被截断的下界**，同时这是 qualification 阻塞项（reviewable answer 不达标）。下一步先**解除截断**（仅在资格/校准路径提高 answer timeout floor）拿到真实生成分布，再决定 reserve/(a)；60s 与 reserve 12s 均保持冻结不动，Live12 仍冻结。
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



