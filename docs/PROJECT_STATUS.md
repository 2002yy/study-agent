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
- **当前唯一下一步（2026-09-16 更新）：**§37B-selection 已完成并给出**第一个可信的正例丢失定位**：目标候选 `https://nodejs.cn/api/modules.html`（provider ✓ → normalized ✓ → materialized ✓ → pool ✓）**死在 bounded assessment window（`_bounded_assessment_candidates`，cap=2）**，terminal_reason = `candidate_pool_excluded`（观察到的分支：`window_limit_reached`）——**没有进入 H9、没有进入 read plan、也没有触发任何 authority/mirror/budget 规则**（read budget 2/8 未用尽）。工具：`tools/run_selection_provenance.py`（`daebd8a`/`cea5db4`）。⇒ 未来 ranking 接线点是**评估窗口的候选排序**，不是此前猜的 harvest seam。**§38 agent-loop prototype**（`7dca213`/`0b61afd`/`9ddfd7d`）首批实测：纯模型 planner+selector 在同样的 provider/reader/extractor 下**目前弱于 pipeline**（Docker case 4 次 search 未召回 docs.docker.com；Node case 未召回 `/api/modules.html`；planner 需 provider 感知提示，模型调用有超时噪声）。下一批 = **§38b hybrid**：保留冻结的 query planning，只把 selection（评估窗口/读选择）交给模型，直接验证"selection 是死因"的假设。**reserve 12s、60s、Live12、30s timeout、PARTIAL/PASS、extractor/Gate/answer、read adequacy 全部继续冻结。**（注：§37B 生产 instrumentation 的全量 pytest 门禁因用户要求切换方向而中断，pending 一次完整复跑。）
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

## 39. §37A.1 Diagnostic Accounting Repair（已实施，纯诊断口径修正）

**用户纠正（接受）：**§38 里"`selected_for_harvest=0/475` → §36A/§36B harvest 排序基本没参与"**不成立**——harvest 探针本就不存在，必须记 `unobserved` 而**不能记 false**；`475` 是 **query-result occurrence**，不是 475 个候选，同一 URL 被 8 条 query 召回就会在 8 行上重复计数。

### 39.1 实施（`f38d1f0`）

- 三态：`STATE_TRUE/STATE_FALSE/STATE_UNOBSERVED`；**未埋探针 ≠ false**。read 可按 case 观测（结果 URL 要么被读要么没有）；**harvest 只有在确实发生过 harvest 尝试时才可记 true/false**。
- URL 去重：`dedupe_candidates`（用**生产 canonicalizer** 做 key，返回 occurrence map）→ 人工标注只对**unique candidates** 填一次，再投影回各 query occurrence。
- 人工字段两层分离：`human_candidate_classification ∈ {likely_target, near_hit, irrelevant, unknown}`；`human_target_fact_present_after_read ∈ {true, false, unobserved}`，且**只有真的读过正文才能填 true/false**——违反会被记为 `accounting_violations`（不静默接受）。
- case 级计率（不按 475 行加权）：
  ```text
  target_fact_candidate_rate = 含 >=1 likely_target 的 case / 完成分类的 case
  target_fact_selected_rate  = likely_target 被 harvest/read 的 case / 含 likely_target 的 case
  target_fact_read_rate      = 读到 likely_target 的 case / 含 likely_target 的 case
  target_fact_present_after_read = 读到且正文含事实的 case / 读到 likely_target 的 case
  target_fact_harvest_rate   = unobserved（探针补上之前不猜；绝不用 read 冒充 harvest）
  ```
- 饱和量化：`unique_urls_per_case` / `new_url_gain_after_q1` / `pairwise_result_set_overlap`。

### 39.2 修复后的真实数字（同一份 §37A probe，`SUPPORT_FORMATION_AUDIT.after_37a1.json`）

| case | queries | occurrences | unique | gain>q1 | pairwise overlap | harvest_probe |
| --- | --- | --- | --- | --- | --- | --- |
| current-policy-container-registry | 10 | 50 | 5 | 0 | 1.0 | no_harvest_attempt |
| current-support-postgresql | 10 | 50 | 5 | 0 | 1.0 | no_harvest_attempt |
| numeric-uk-bank-rate | 8 | 40 | 5 | 0 | 1.0 | no_harvest_attempt |
| numeric-uk-inflation | 9 | 45 | 5 | 0 | 1.0 | no_harvest_attempt |
| simple-license-uv | 4 | 20 | 5 | 0 | 1.0 | no_harvest_attempt |
| academic-primary-attention | 8 | 40 | 10 | 5 | 1.0 | no_harvest_attempt |
| provenance-xz | 8 | 40 | 5 | 0 | 1.0 | no_harvest_attempt |
| conflict-python-gil | 8 | 40 | 5 | 0 | 1.0 | no_harvest_attempt |
| community-rust-async | 9 | 45 | 5 | 0 | 1.0 | no_harvest_attempt |
| causal-cloudflare-2025 | 8 | 40 | 10 | 5 | 1.0 | no_harvest_attempt |
| historical-current-node-modules | 9 | 45 | 10 | 5 | 1.0 | no_harvest_attempt |
| unverifiable-python-security | 4 | 20 | 5 | 0 | 1.0 | no_harvest_attempt |

```text
475 occurrences → 75 unique candidates（比例 0.158）
每个 case 的相邻 query 结果集 overlap 恒为 1.0（Q2..QN 与 Q1 返回同一批 URL）
9/12 case 的 new_url_gain_after_q1 = 0（其余 3 个 case +5）
harvest：12/12 全部 no_harvest_attempt（本轮 §36A harvest 路径压根没触发）
read：unique 层 25 read / 50 not read（read 可观测，故 false 合法）
rates：pending_human_classification；target_fact_harvest_rate = unobserved；accounting_violations = []
```

**修正后的结论：**"结果饱和"比 §38 的描述**更强**也更干净——不是"8–10 条 query 只换回 5–10 个 URL"，而是**相邻查询返回完全相同的结果集（overlap 恒 1.0）**，且 9/12 case 在 Q1 之后再无新增 URL。同时 §36A/§36B 的 harvest 路径本轮**一次都没触发**（`no_harvest_attempt`），因此"harvest 排序是否有效"在本轮**不可判定**（unobserved），不得再作为结论。

### 39.3 `root_or_shallow` 正式降级

用户外核验：PostgreSQL 真正正确的页面是 **`/support/versioning/`**（URL 浅但就是权威事实页），Docker 正确页为 **`docs.docker.com/docker-hub/usage/pulls/`**。因此从 §37 起 `root_or_shallow` **不再作为任何方向性证据**，只保留为次要诊断。真正有意义的是四层：`有没有召回事实承载页 → 召回后有没有选它 → 选后有没有读到 → 读到后 extractor 有没有认可`。

### 39.4 下一批：§37B Positive-Control Provider-Recall Probe（未开工，等人工 rate 后执行）

在改任何生产搜索逻辑之前，先用**已知正例页**做 positive control（用户已独立核验两例）：

```text
Docker : docs.docker.com/docker-hub/usage/pulls/  （"Docker Hub pull usage and limits"）
PostgreSQL: postgresql.org/support/versioning/    （"Versioning Policy"）
```

判定矩阵（用户给定）：

| positive-control 结果 | 真正瓶颈 |
| --- | --- |
| 连精确页面标题都召不回 | provider/search backend recall |
| 精确标题能召回、§36B query 召不回 | query formulation |
| provider raw response 有目标页但 §37A 看不到 | request normalization / cache / adapter |
| §37A 能看到但没 harvest | pre-H9 harvest ranking |
| harvest/read 到但 reader 没正文 | read adequacy |
| reader 有事实但 extractor 仍 lead | extractor false-negative |

**必须同时排除的候选机制（§37A 尚未排除）：**`95/95 query 字符串唯一 ≠ provider cache key 唯一`。若更下层存在 `cache_key = claim_id` 或过度归一化的 key，不同字符串仍可能命中同一缓存结果。因此该 probe 需同时记录：`final provider query hash`、`provider request params`、`cache-key hash（若可见）`、`cache hit/miss`、`raw returned canonical URLs`。

只有 positive control 稳定失败（连精确标题都召回不到）时，才有资格宣布：**瓶颈不再是 query intelligence，而是 search/provider retrieval surface 本身。**

## 40. §37A.2 Model-assisted Blind Annotation（已执行）+ 指标口径修正

### 40.1 指标口径修正（用户指出）

`pairwise_result_set_overlap` 的公式是 **Jaccard `|A∩B| / |A∪B|`**（现在写死在文档里）。此前我在 §39.2 写"相邻查询返回完全相同"是**从截断输出（只打印前 3 个）过度概括**。完整数组为：

```text
9/12 case：全部相邻对 overlap = 1.0（结果集完全一致）
3/12 case：各有 1–2 处 overlap = 0.0（相邻结果集完全不相交），新增 URL 即来自该处
```

即结果集**要么完全相同、要么完全不相交**，不存在部分重叠。稳妥表述：**9/12 case Q1 后零增量；其余 3/12 存在新增候选；查询结果高度重叠（或完全切换）**。

### 40.2 双遍独立盲标（`6f14b2c`）

- 工具：`tools/run_discovery_annotation.py`（6 测试）——盲标任务只含 `claim / page_intent / url / title / snippet`（无 relation/caveat/read 状态/answer/authority/已知正确 URL）；按固定种子逐遍洗牌；presence 任务只覆盖**确实读过**的候选并附 bounded 重抓正文（记录 freshness caveat）；`validate_annotations` 强校验 `reviewer_type=opencode` + `reviewer_model` + 词表；`merge_passes` 输出一致率与分歧清单；`summarize_model_rates` 出四级漏斗率，**read 状态从观测系统 join，绝不用 presence 字段冒充**；`target_fact_harvest_rate` 保持 `unobserved`。
- 两遍在**独立上下文**中完成（pass A / pass B，B 为洗牌顺序），逐条对照：

```text
75/75 候选：candidate_classification 完全一致（exact agreement = 1.0）
75/75 候选：presence 字段完全一致（= 1.0）
标签分布（两遍相同）：likely_target 2 · near_hit 47 · irrelevant 26 · unknown 0
分歧清单：空 → 无需人工裁决
reviewer_type = opencode；reviewer_model = opencode-go/deepseek-v4.1-flash
（human_* 字段按约定保持为空；本结果只记为 model-assisted）
```

### 40.3 四级漏斗首次可读（`DISCOVERY_RATES.json`）

```text
12 cases
  ↓ search recall
cases with >=1 likely_target            = 1        → model_target_fact_candidate_rate = 0.0833
  ↓ read selection
cases where likely_target was read      = 0        → model_likely_target_read_rate  = 0.0
  ↓ page precision / reader
present_after_read                      = n/a      → model_target_fact_present_rate = null（无分母）
  ↓ extractor
supports among present                   = n/a      → model_extractor_capture_rate   = null
target_fact_harvest_rate                = unobserved（探针仍缺）
```

两个 agreed `likely_target`（均在 `rq1c-historical-current-node-modules`）：

```text
https://node.org.cn/api/modules.html   （Node.js v26 模块文档；snippet 明说 CommonJS + ECMAScript 两套模块系统）
https://nodejs.cn/api/modules.html     （同上，镜像）
两者均 read=False → presence 只能 unobserved
```

### 40.4 判定：本次触发的是 **selection 链**，不是 provider recall

按 §39.4 预先锁定的分叉规则：

```text
candidate_rate > 0（0.0833）但 likely_target_read_rate 很低（0.0）
→ 先研究 search-result → read selection 链，不碰 provider recall
→ 也**不**提前跑 Docker/PostgreSQL positive control（避免用已知答案污染 recall 判断）
```

同时保留一个并行事实：**11/12 case 连一个 likely_target 都没有召回**（recall 弱），但那属于"零候选"情形的另一条支线，按规则排在 selection 之后。

**下一步（§37B-selection，未开工）**：查清"被召回的正确页面为什么没进 read 选择"——观察对象是 search result → `rank_candidate_pool`(H9 语义层，冻结) → read plan 这条链上的**选择**环节；本文档同时确认 §36A/§36B 的 harvest 路径本轮 `no_harvest_attempt`（unobserved），因此 selection 失败发生在**非 harvest** 路径上。

### 40.5 冻结项（未改动）

reserve 12s、60s、Live12、30s answer timeout、PARTIAL/PASS 策略、extractor/Gate/answer、研究预算与物理模型调用数、Lead caps、H9 scheduler、read adequacy。

## 41. §37B-selection：正例丢失的第一层定位（已完成，`daebd8a`/`cea5db4`）

### 41.1 真实调用链（代码路径实测，不是设计图）

```text
ActiveResearchGateway.search_detailed(query)              ← 同一 provider stack（§37A 观测点）
  → execute_candidate_pool_batch(one_query, results_per_query=5, max_candidates=budget)
      → merge_candidate_pool                                   [第 1 层压缩：canonicalize/dedupe/cap]
  → _merge_runtime_candidates(cursor.candidates, ...)          [第 2 层：跨 query 去重/上限]
  → _candidates_for_claim
  → cluster_candidate_sources(assignments)
  → _bounded_assessment_candidates                             [第 3 层压缩：评估窗口 cap=2]
  → candidate_assessor.assess（模型）
  → rank_candidate_pool (H9)                                   [只排序已评估者，不改语义]
  → _fair_read_plan → schedule() → plan_read_wave              [covered cluster / normal_limit / reserve]
  → 读循环（budget / research window / already_read）
```

**此前假设的"normalized result → harvest"接线点不正确**：本 case harvest 全程 `no_harvest_attempt`（unobserved），真实压缩发生在 `merge_candidate_pool`、`_merge_runtime_candidates` 与**评估窗口**。

### 41.2 观测机制（纯 telemetry，零行为变更）

- `src/web/research/selection_trace.py`：每个 canonical URL 一条 trace（seen/normalized/materialized/deduped_survivor/duplicate_merges/pool/window/scheduler_rank/read…），`terminal_reason` 由 **first observed drop** 在 payload 生成时定型；未观察到原因 = `unobserved`，读过的候选 = 空。
- 只记录既有代码**已经做出**的决定（分支原因名取自真实分支：`window_limit_reached` / `cluster_represented_by_earlier_candidate` / `covered_cluster` / `budget`…），禁止诊断代码重推选择。
- payload 只进 `metrics.selection_trace`（resume 可 hydrate），**不进入 cursor / evidence qualification**；H9 rank 直接取现成输出，不改 H9。
- 12 条契约测试（blinding/顺序/预算/cursor/determinism/first-drop 稳定性）。

### 41.3 首次真实结论（case `rq1c-historical-current-node-modules`）

```text
https://nodejs.cn/api/modules.html（agreed likely_target）
  provider ✓（4 次出现，duplicate_merges=3）
  normalized ✓ → materialized ✓（deduped survivor）
  entered_candidate_pool ✓
  entered_scheduler ✗  ← 死在这里之前
  scheduler_rank null / read_dispatched false
  terminal_reason = candidate_pool_excluded
  filter_reason  = assessment_window:window_limit_reached
```

- 该 run 的评估窗口 cap = 2（`CANDIDATE_ASSESSMENT_WINDOW_MAX_CANDIDATES = 2`），每 wave 只允许最早 `first_seen_rank` 的前 2 个 cluster 代表进入评估；目标页在 wave 1/2 都被窗口截断，**未触达 H9、未触达 read plan**。
- **不是** authority/mirror 过滤（链上没有 mirror 规则触发）、**不是** read budget（2/8）、**不是** canonicalization 错误、**不是** scheduler 未选（它从未进入 scheduler）。
- `https://node.org.cn/api/modules.html` 在带 trace 的两次真实运行中**未被召回**（unobserved）→ 两个镜像的召回本身在 run 间不稳定（与 §37A 原 run 对照）。
- 读到的 4 个候选（2 wave × cap 2）中 1 个 read 失败；gate=block、answer=available（32 字符 fail-closed surface）。

**判定（按 §39.4 分叉）**：目标丢失发生在**评估窗口的候选排序/上限**，属于 selection/ranking 问题；修复 seam 在**窗口的候选排序**（§36B `rank_search_results` 的自然落点），不在 harvest、不动 H9。**positive control（Docker/PostgreSQL）仍未运行**。

## 42. §38 Agent-loop prototype：首批实测（`7dca213`/`0b61afd`/`9ddfd7d`）

架构假设：把 PLAN（query planning）与 SELECT（结果选择）从规则链交给 flash 模型，代码只保留硬约束（搜索/读取上限、超时、去重、citation、reader/extractor/Gate 原样）。工具 `tools/run_agent_loop_prototype.py`（diagnostic_only，8 契约测试；bounds 4 search / 6 read / 60s per case；复用 `ActiveResearchGateway` 与冻结 `RuntimeEvidenceExtractor`）。

首批（2 case，v0–v3 迭代）：

```text
rq1c-current-policy-container-registry:
  v0-v2: planner 产出 8–12 词堆叠 query（含 Bing RSS 不支持的 site:/布尔），召回全是教程/无关页；
         selector 全部返回空列表（现在可见：model completed，raw=[]）→ reads=0
  v3:    provider 感知提示后 query 变短（"Docker Hub usage and limits" pull rate），
         仍**未召回 docs.docker.com 官方页**；1 次 read（docker.com 首页，无正文）→ supports=0

rq1c-historical-current-node-modules:
  未召回 /api/modules.html；selector 多次 unavailable（model_call_attempts_exhausted，模型侧超时噪声）
```

**诚实结论（首批）**：纯 agent loop 在当前 provider（Bing RSS）与当前 planner 提示下**没有显示出优于规则 pipeline 的召回**；它验证了"模型选择环节可用"（Node v1 正确选中 nodejs.org/ 并把 caveat 说清楚：页面未陈述目标事实），但 **query planning 交给模型并没有立刻变好**——反而暴露 provider 交互（`site:` 无效、结果稀疏）才是共同瓶颈。**§37B 的结论仍然成立**：在 pipeline 内部，目标死因是评估窗口选择，而不是"缺少一个更像 agent 的 planner"。

**下一批（§38b hybrid，建议）**：保留冻结的 query construction（规则变体已被证明能召回目标），**只把评估窗口/读选择替换为模型 selector**——在同一个 case 上直接对比 supports/binding/reads。这是"AI 决定去哪读、代码决定读多少"的最小可控实验，也是 §37B 修一个 seam 而非重写 architecture 的路径。

### 42.1 §38b selector replay：离线 A/B + 稳定性复测（`8769926`/`7ad3c96`）

在 §37A 冻结数据上（95 query / 475 结果 → 每 case 5–10 个 unique 候选），对每个 case 重建完全相同的候选池，把**规则窗口实际做出的选择**（`selected_for_read` / `read_status`）与**模型 selector 的 top-K（K=2）**逐 case 对比。模型 = 生产同一通道（provider `deepseek`，model `deepseek-flash`，structured research 调用 thinking disabled，temperature 0，timeout 30s，max_attempts 2）。

**单轮结果（`SELECTOR_REPLAY.v1.json`）**

```text
cases_with_targets = 1（仅 rq1c-historical-current-node-modules，agreed likely_target ×2）
rule_target_hits  = 0    ← 规则窗口：两个目标都没被选（与 §37B 的 candidate_pool_excluded 一致）
model_target_hits = 1    ← 模型 top-2 恰好是两个目标（rank1 nodejs.cn/api/modules.html，rank2 node.org.cn/api/modules.html）
```

**稳定性复测（`--repeat 5`，60 次调用，`SELECTOR_REPLAY.repeat5*.json`）**

```text
repeat5 : model_target_hit_runs = 3/5（命中时为两个目标且顺序正确；2/5 为空返回）
repeat5b: model_target_hit_runs = 0/5；model_status_counts = {completed 41, unavailable:model_call_attempts_exhausted 19}
```

⇒ 结论必须分开写：

1. **内容上模型选择有效**：只要 flash 调用成功返回，Node 池子的 top-2 就是两个 agreed likely_target（多次复现，顺序正确）；非目标 case 大多返回空而非硬选。
2. **调用层不稳定**：同一提示+同一池子，返回会整体空掉（2/5 甚至 5/5），且约 1/3 的调用两次尝试都失败（`model_call_attempts_exhausted`，模型侧超时）。**这意味着"把 selection 交给模型"必须先定义失败语义**：模型空/不可用时回退到规则窗口（deterministic shell 保住下限），模型可用时用模型选择提升上限。
3. 仍**未证明端到端 supports**：selection 正确后仍需 read + extractor 成功；positive control（Docker/PostgreSQL 精确页）仍未运行。

### 42.2 §38b hybrid 链：第一次出现 `supports > 0`（`cd893fa`，4/4 复跑）

工具 `tools/run_hybrid_selection_chain.py`（诊断-only，生产 runtime 未动）。单变量：只把 selection authority 从规则窗口换成模型 selector，其余全冻结（同一冻结候选池、同一 provider、同一 reader、同一 `RuntimeEvidenceExtractor`、同一 parser）。失败语义：模型最多尝试 3 次；**任何一次可用决定即采用；全部不可用才回退规则读取集**（模型有优先权但无权把研究留空）。

```text
selector_input_candidate_set = 冻结 Node 池 10 个 canonical URL（与离线 replay 完全一致，不变量已入 artifact）
selector_output_urls         = [nodejs.cn/api/modules.html, node.org.cn/api/modules.html]

run1: attempts=[unavailable×2, completed(2)] → authority=model
run2: attempts=[unavailable×2, completed(2)] → authority=model
run3: attempts=[completed(2)]  run4: attempts=[completed(2)]

分层验收（4/4 全部相同）：
  target_selected  = true
  target_read      = true（两页各 6000 chars，ok=true）
  extractor_relation = supports ×2（冻结 extractor，caveat 诚实记录"未对比新旧指引"）
  target_fact_present = true
  supports         = 2
```

**这是项目历史上第一次：被召回的正确候选 → 被选中 → 被读取 → 被冻结 extractor 判为 `supports`。**对比规则路径（§37B 同一 case）：`candidate_pool_excluded(window_limit_reached)`，supports=0。

**空返回分型（`model_calls_runs` 逐调用记录）**：本 case 观察到的全部空返回都是 `unavailable:model_call_attempts_exhausted`（调用可靠性/超时），**没有一次是"模型 completed 但决定返回空"**；所有拿到可用决定的运行都精确选择两个目标（0 次选错）。即：**precision 已展示，问题在 usable-decision reliability**，而 retry+fallback 语义使链级结果不受影响（4/4 到达 supports）。

**保留与边界**：两个 supports 来自同一内容的两个镜像，且 cluster 未建模（常量 `hybrid_cluster`）——Gate/binding 阶段可能合并为 1；`binding_rows` 与 `substantive_answer` 层尚未测（需要 runtime 路径）；`target_fact_present` 由 extractor relation 推导（supports 针对"支持哪些模块系统"，caveat 明确指出未回答"新旧指引差异"这一子句）。**positive control 仍未运行；生产默认路径未改。**

**§38b 下一执行切片**：把该 hybrid 作为**诊断变体**接进 runtime 的 `_bounded_assessment_candidates` 调用点（env 开关，默认 rules），跑 Node case 的完整链 `target_selected → … → binding_rows → answer`，并核对 runtime 的 selector input 集与离线池的一致性（诊断记录已在 `metrics.selection_trace` 中准备好）。

### 42.3 §38b runtime 诊断变体：已接入并跑通（`8d0e1f1`/`a4fd498`）

实现（生产默认不变）：

- `src/web/research/selection_authority.py`：`RESEARCH_SELECTION_AUTHORITY=model` 时由模型选择进入评估窗口的候选；未设置/未知值 → 原 `_bounded_assessment_candidates` 行为。模型只能从 runtime 自己的 pooled candidate 集里按 canonical 匹配，输出 ≤ 原窗口 cap；空/不可用/异常 → **回退规则窗口**（模型可抬上限、不能拆地板）。7 条 focused 测试，其中一条专门断言默认路径**完全不会调用模型**。
- runtime `_select_assessment_window`：逐 wave/claim 把 `selector_input_candidate_set`、`selector_output_urls`、状态、`fallback` 写入 `metrics.selection_authority`（40 条封顶）——离线/在线分歧可见，不靠猜。
- `tools/run_selection_authority_runtime_probe.py`：走 **raw（非 guard）driver** 跑单 case，因为 qualification guard 的 6 次研究调用上限会把逐 wave selector 调用饿死（实测 wave2+ 直接 `qualification_research_model_budget_exhausted` → fallback → 目标再次被规则窗口丢掉）。artifact 记录 `/guard_bypass_reason/` 与 selector 记账 caveat（selector 调用**不进** runtime 的 durable model-attempt ledger，单独计数）。

三次 raw 运行（Node case，flag=model）：

```text
run1: wave2 模型 completed，选中目标 → H9 rank1 → **read plan 未读**
      observed_drops = [candidate_pool_excluded(窗口), read_budget_exhausted(reserve 门), …]
      ← 选中后的隐藏压缩点：normal_limit = max_reads - reads_used - reserve(=3) 关闭了预算门
run2: 同 run1 形态（目标进输入集、被选中、被 reserve 门挡在读之前）
run3: wave1 模型选中目标 → read ✓（6000 chars，role=primary）→ 冻结 extractor **eligible**
      但 relation = **background**（strength 0.3，caveat 明确："describes the current dual
      module system … does not explicitly contrast them with older guidance"）
      → supports=0 → gate=block（eligible_support_clusters=0/1, primary_required）
      → answer=available（32 字符 fail-closed 面）
```

**因果链（单变量）在 runtime 里被推进到最后一步**：

```text
规则路径（§37B）  ：target ✗ 评估窗口（从未进入 scheduler/read）
模型路径（run3）  ：target_selected ✓ → target_read ✓ → extractor_relation = background
                    （同一页面、同一冻结 extractor，在 §38b 离线单-claim 链里判为 supports）
```

⇒ §38b 的下一步瓶颈不再是 selection，而是**claim 分解后目标页被绑到"新旧指引差异"子 claim 时 extractor 给 background**（以及 r run1 形态下的 read-plan reserve 门）——两者都属于用户分层表里"选中/读到之后"的行。**生产默认路径未改；positive control 仍未运行。**

附带的观测修正（`a4fd498`）：`_bounded_assessment_candidates` 曾把所有被排除候选标为 `already_read`（排除集同时含已评估者），现只由读循环记录真实 already-read；`metrics.selection_authority` + trace 两套记录均可复核。

## 43. §38c Claim-shape / Extractor Disambiguation（已完成，`67d1aca`，结果 `CLAIM_SHAPE.node.json`）

方法：冻结 runtime 实际读到的目标页正文（`https://nodejs.cn/api/modules.html`，6000 chars，sha256 `c8d4e733…`）与同一个冻结 extractor（同 flash、同参数），只交换两个维度：**claim 形状**（3 行）× **harness 约定**（2 列：离线约定 vs runtime 实际 source 元数据）。矩阵共 6 格，另加原子 claim 两格是因为 runtime 把该页绑定到了比较 claim、而 gate 的关键 claim 是原子事实 claim。

实际输入（来自 capture2 的真实 runtime run）：

```text
runtime_atomic_claim     : "What module systems does current Node.js officially support"
                           kind=factual  priority=critical  policy_profile=official_statement
runtime_comparison_claim : "how does current guidance differ from older CommonJS-versus-ES-modules guidance?"
                           kind=analytical priority=major     policy_profile=causal_analysis
目标页 owner claim（runtime 实际抽取时绑定）= runtime_comparison_claim（relation=background）
gate 关键 claim = runtime_atomic_claim（eligible_support_clusters=0/1）

关于 harness 两列：capture2 中两列的 role/title/published_at 实际上完全相同，
唯一差异是 source_cluster_id 字符串 → 该维度**不构成有效自变量**（见下）。
```

结果（同一冻结正文，6 次真实 extractor 调用）：

```text
A: offline_question         x offline_harness → supports    (0.70)
B: offline_question         x runtime_harness → background  (0.35)
C: runtime_comparison_claim x offline_harness → background  (0.30)
D: runtime_comparison_claim x runtime_harness → qualifies   (0.55)   ← runtime 本 run 为 background
E: runtime_atomic_claim     x offline_harness → supports    (0.95)
F: runtime_atomic_claim     x runtime_harness → supports    (0.90)
```

**判定（按预设决策树裁剪后）**：

1. **claim 形状是决定性变量**：原子 claim 在两列下都是 `supports`（0.9–0.95）；比较 claim 在两列下都**不是** `supports`（background/qualifies）→ 比较 claim 需要跨来源证据，单页自足式抽取无法成立。**不应调整 extractor 去把比较 claim 改成 supports。**
2. **harness 列无效**：两列唯一差异是 cluster id 字符串；A/B、C/D 的行内差异与既有 extractor 方差一致（比较 claim 在 runtime 本 run 是 background、复测是 qualifies）→ 判据落在 claim 形状，不在包装。
3. **runtime 的真实缺陷是绑定路由**：该页被抽取时只绑定到比较 claim；而 E/F 证明**同一页面对关键原子 claim 是 0.9+ 强度的 `supports`**。gate 的 `eligible_support_clusters=0/1` 不是因为证据不存在，而是因为**证据从未被绑定到需要的 claim 上**。
4. 混合问句（A/B 出现 supports/background 分裂）进一步支持：混合问句不是稳定的单来源抽取目标。

**结论**：这是一个 **claim decomposition 与 evidence binding 的职责边界问题**——比较类子 claim 应交由 binding/synthesis 由两条原子事实组合（旧 guidance × 新 guidance），而不是要求单个 current-state 页面证明"变化"。extractor 行为正确。

## 43.1 当前状态与唯一下一步

```text
offline evidence path:      4/4 supports PASS（§38b 链）
runtime selection path:     target reachability demonstrated（§38b runtime 诊断）
runtime read path:          demonstrated once（capture2：目标页 6000 chars 已读）
runtime support path:       NOT YET（关键 claim 未拿到 supports —— 绑定路由问题，非证据缺失）
runtime binding path:       NOT REACHED
runtime end-to-end answer:  NOT YET（仍 32 字符 fail-closed）
```

**下一批 = §39 Binding/Decomposition 职责边界**（不先修 read reserve、不生产化 selector）：目标是让读到的页面在**正确的 claim** 上被抽取与绑定——具体方向由 §38c 给出：原子事实 claim 独立抽取 + 比较 claim 由 binding/synthesis 组合。read reserve 门（run1/2 复现两次）仍记录为独立待修项，排在 §39 之后。

## 44. §39 Evidence-to-Claim Routing / Atomic Claim Extraction（已实现，run7 首次 runtime gate PASS）

### 44.1 实现（`b1a208e`/`400ecdf`，默认关闭）

- `src/web/research/atomic_routing.py`：读到的页面可被**同一 run 内仍缺 `supports` 的 factual claim** 追加消费；比较/analytical claim **永不路由**（其支持属于后续 synthesis）；硬上限：每个 read artifact ≤2 个、每 wave ≤4 个；不重读页面、不做 page×all-claims 笛卡尔积。route reasons 按契约记录（`missing_atomic_child`/`origin_claim`/`already_supported_skip`/`unrelated_skip`/`bounded_cap_skip`/`already_bound_skip`）；6 条 focused 测试。
- runtime 接线：在 `_restore_completed_read_targets` 之后扩展 `extraction_targets`（路由行**紧跟在 origin 行之后**，保证与 origin 同等的机会，`400ecdf`），流经同一条 extraction → evidence → Gate 路径；`metrics.atomic_routing` + `metrics.atomic_routing_extractions`（每对 read_artifact × claim 的 status/relation/cluster）。
- 开关：`RESEARCH_ATOMIC_ROUTING=on`（默认 off，生产行为不变）。

### 44.2 验收运行（Node case；`RESEARCH_SELECTION_AUTHORITY=model` + `RESEARCH_ATOMIC_ROUTING=on`，raw driver）

```text
run1/5/6 : 目标页已读并被路由（missing_atomic_child）→ routed extraction = extractor_failed
           reason（run6 捕获）= model_call_attempts_exhausted（wave 2 尾部窗口）
run2/3/4 : 路由抽取正常完成，但目标是 juejin（background）；目标页未被读（selector/窗口方差）
run7     : 目标页被读 → 路由到原子 claim → extractor = supports（role=primary, cluster 7dcd…）
           → eligible_support_clusters ≥ 1 → **gate = pass**（open_critical_claim_ids 空）
           → answer stage 28.61s → candidate answer = EMPTY（sha256=e3b0c442…）→ 32 字符 fail-closed
run9     : 同页同 claim 同样 supports，但该页被 assessor 判为 authoritative_secondary →
           不满足 primary_required → gate 仍 block
```

**§39 验收结论**

```text
atomic_claim_routed      ✓（run1/5/6/7/9）
atomic extraction        ✓ supports（run7/run9）
eligible_support_clusters 0 → 1   ✓（run7）
gate                     ✓ pass（run7；首次）
binding                  ✓（gate pass 即计数）
substantive answer       ✗ NOT YET → 新暴露的 blocker 在 answer generation：
                          gate=pass 时 answer 路径**不**走 BLOCK-only thinking-off，
                          生成在 28.6s/30s 处返回空 candidate（与 §28–§31 的 30s 截断一致）
```

**run9 的方差发现（记录，不现在修）**：同一页面在同一 claim 上，assessor 给出的 `source_role` 会在 run 间变化（primary ↔ authoritative_secondary），而关键 claim 有 `primary_required`——这决定 supports 是否被 gate 计入。属于 assessment 层的 run 间不稳定性，与 §38b selector 的不稳定性并列，留作后续批次。

**边界声明**：以上全部是 **raw（非 guard）driver 诊断运行**；生产默认路径未启用 selector/atomic routing；`read reserve` 门仍待修；recall（11/12 case 无 likely-target）与 selection 不稳定仍未被本批解决。

## 45. §40 Answer Formation：输入已冻结，但被账户余额阻塞（`9aba24c`/`a991aa8`）

### 45.1 已完成的准备

- `tools/run_answer_formation_probe.py`（13 项 focused 测试合计）：`capture` 模式在 raw driver 上按 qualification guard 的同一拦截点包装 chat 依赖，冻结 answer-stage 请求（messages/kwargs/超时/profiles/重试/thinking extra_body）与原始回复（chars/sha256/excerpt/异常/耗时）；`replay` 模式对冻结调用做 N 次重放并按 **A/B/C 分类**（A_model_empty / B_parse_loss / C_call_unavailable），支持 `--task`（single_chat / answer_claim_binding / all）与 `--policy captured|thinking_off|both`，输出 non_empty/substantive/fail_closed/latency 指标。
- 冻结样本 `ANSWER_FORMATION.capture3.json`：**gate=pass** 运行，两个 answer 调用均被捕获。

### 45.2 capture3 已观测到的事实（冻结输入）

```text
answer generation  (single_chat)        : pro 模型, max_tokens 1600, retries 0, thinking ON
                                          5246 chars → 305 chars, 17.3s, completed
                                          但输出是"无法给出结论（研究未完成）"——而其 system prompt
                                          **确实包含 supports 行**（api/modules.html + supports 标记）
answer claim binding (answer_claim_binding): pro 模型, same config, thinking ON
                                          2213 chars → **空输出**, 18.4s
                                          验证层：outcome=rejected, error_type=empty_producer_output
                                          → 发布 32 字符 fail-closed
```

即 gate=pass 之后仍有两个独立的失败面：**生成层给出拒答文本**（尽管输入含 supports 证据）、**绑定层空输出**（导致整条回答被拒）。两者都是 §40 的复现与 A/B 目标，工具已就绪。

### 45.3 环境 blocker：DeepSeek 账户余额耗尽（HTTP 402）

对 capture3 的重放**全部立即失败**：

```text
RuntimeError: API call failed: Error code: 402 -
{'error': {'message': 'Insufficient Balance', ...}}
```

⇒ **§40 的单变量 A/B 在账户充值或更换 key 之前无法执行**。在余额恢复前，任何依赖模型调用的诊断批次都不应解释为能力结论。

**需要一并回看的 confound**：§39 的 run1/5/6 里 routed extraction 的 `model_call_attempts_exhausted`（当时解释为窗口/预算）与本次 402 是同一类"调用不可用"信号；在健康余额下重跑之前，这两个解释**不能区分**。此类记录已在 §44.2 标注为待复核。

### 45.4 §40 执行结果（充值后，`986a239` 工具 + `ANSWER_FORMATION.replay.*.json`）

**Step 1：empty 机制定性（capture3 冻结输入，N=5 × 两 policy × 两个调用）**

```text
问题1 empty 是否稳定复现？
  binding  : captured policy  0/5 非空（5/5 empty，20.6–22.0s）
  generation: captured policy 2/5 非空（3/5 empty，19.9–23.1s）

问题2 empty 时 model call 状态？
  全部 completed，无异常、无 402、无超时 —— 调用本身"成功"，只是返回空串（~21s 的推理型耗时）

问题3 机制分类？
  **A_model_empty（模型真的返回 ""）**；B_parse_loss 0 次；C_call_unavailable 0 次。
  与 §1.1 已知的 DeepSeek 行为一致：thinking 吃掉 1600-token 输出预算 → content 为空。
```

**A/B（同一冻结输入，只换 generation policy）**

```text
single_chat (answer generation, pro + 1600 tokens):
  captured   : non_empty 2/5 (40%), p50 21.8s
               两个非空文本**内容准确**（[web-1] 引用 + 明确说明对比部分证据不足）
  thinking_off: non_empty 5/5 (100%), p50 4.5s
               但 fidelity 混合：1 条清晰合格（引用+strength 0.9+缺口说明）、1 条基本合格、
               1 条错误声称"没有任何已校验证据"、2 条部分合格
answer_claim_binding (结构化输出):
  captured   : 0/5（全 empty）
  thinking_off: 5/5 **结构化有效**：refused=false、13/13 segment 全覆盖、
               0 个未知 evidence id / research claim id / segment ref，p50 3.4s
```

**结论（按用户口径）**

1. **C 被排除**：不是超时/不可用；**B 被排除**：不是 parse 层丢失；**A 成立**：模型返回空串。
2. **generation policy 是单变量主因**：thinking-off 使两个调用非空率 0–40% → 100%，延迟约 1/5。
3. **但不能只看非空**：thinking-off 的 generation 有 2/5 文本**错误描述证据状态**（声称"没有读取正文"，而输入里含 supports 行）——"非空"不等于"忠实"；binding 侧则 5/5 结构与 allow-list 全通过。
4. 推荐（**未实施**）：把 gate-pass 的 answer 两个调用改为 bounded thinking-off **作为诊断开关**，然后在完整 raw run 里检查发布决策与答案-证据一致性（不是只看 non-empty）。

**§39 confound 复核**：本次健康余额下重放全部 `completed`，说明 402 只在余额耗尽后出现；run1/5/6 的 `model_call_attempts_exhausted` 仍需一次健康余额的 §39 重跑才能定性（已列为待办）。

### 45.5 §40c 执行（`4ad32435`/`73450b3`/`50915f0`）：门已实现，live publish 被新一层卡住

实现（两个诊断开关，默认关闭）：

- `RESEARCH_ANSWER_BOUNDED_POLICY=on`：gate-pass 的 generation 与 binding 两个调用都走 bounded thinking-off（已测试：开=两个调用都带 thinking-off extra_body；关=与生产一致）。
- `RESEARCH_ANSWER_CONSISTENCY_GATE=on`：binding 通过后做**机械一致性门**（`src/application/answer_consistency.py`）：unknown evidence ids / unknown claim ids / unbound substantive claims / direction violations（须 supports 行）/ **evidence-state conflict**（ledger 有 supports 时，文本不得出现有界否认词表）。失败→发布 fail-closed，保留真实 binding snapshot，binding phase 记 `error_type=consistency_failed:<codes>`；成功→`rag.answer_consistency.ok=true`。6+3 条 focused 测试。

live raw run（四开关：selector=model、routing=on、bounded policy、consistency gate；`ANSWER_FORMATION.c40c1/2.json`）：

```text
c40c1: gate=block → generation 409 chars（thinking-off ✓, 4.3s）→ binding rejected: missing_evidence_brief
c40c2: gate=pass  → generation 545 chars（thinking-off ✓, 4.5s）→ binding rejected: **answer_not_segmentable**
        （未到 consistency gate；published = 32 字符 fail-closed）
```

**c40c2 根因（离线复算，全部机械可复核）**：

1. **分段预算**：545 字符文本被 `_SEGMENT_BOUNDARY` 切成 20 个非空段 > `_MAX_SEGMENTS=16` → `_segment_answer` 返回空 → `answer_not_segmentable`。thinking-off 的 generation 更丰富，**3/7 生成超出 16 段预算**（replay：14/9/0/13/12 段；c40c1=11 段，c40c2=0 段）。
2. **生成输入没有正文**：capture3 的 generation system prompt（5101 chars）只含证据**行元数据**（relation/claim/source/strength/anchor/url），**不含已读正文**；因此 thinking-off 文本里"没有已读取的正文/无法给出确定性结论"是对其输入的**诚实描述**，但与 ledger 状态（supports strength 0.9）不一致——这正是 §40c 一致性门要拦的对象，说明**下一步该修的是 answer 输入表示与产出形状，而不是 extractor**。
3. 一致性门自身工作正常（测试覆盖 denial-over-supports 拦截与 clean 发布）；它尚未在 live run 中被触发，因为 c40c2 先死在分段预算。

**§40d 建议（未实施，待决策）**：在 answer generation 输入中加入**有界的已读内容/受支持片段**（evidence row 的正文摘录），并约束输出形状（≤16 段或结构化答案计划）——两者都属 answer 输入合同、不动 extractor/Gate/binder 语义。做完后重跑同一验收：`gate pass → generation → binding → consistency clean → publish`。

## 46. §40d 完成：首个完整 runtime E2E positive control 闭环（`f449083`；`ANSWER_FORMATION.d40.2.json`）

### 46.1 实施（两刀 + 诊断；全部默认关闭）

- **Evidence-grounded answer input**（`RESEARCH_ANSWER_GROUNDED_INPUT=on`）：`_evidence_brief` 为每条 eligible row 附加**有界正文 excerpt**（优先 anchor 周围 ±200 字符，找不到则取页首；单条 ≤400、总量 ≤6000），`_format_evidence_brief` 渲染 `excerpt:` 行；brief 同时附加输出形状契约（≤12 个实质段落/条目、每段一个结论、引用置段内）——**`_MAX_SEGMENTS=16` 未动**。
- **分段溢出诊断**：`segment_answer_with_stats` 记录 `raw_nonempty_segment_count / segment_limit / segment_overflow / overflow_reason`，挂在 `BoundAnswerClaims.segment_stats` 并写入 turn rag 的 `answer_binding_segments`——"0 段"不再掩盖"20>16 被拒"。

### 46.2 验收（第 2 次 run 即通过；五开关：selector=model、routing=on、bounded policy、consistency gate、grounded input）

```text
d40.1: gate=block（生成 1617 字符、prompt 已含 excerpt/shape；binding missing_evidence_brief）
d40.2: gate=pass
  prompt_has_excerpt=true / prompt_has_shape_contract=true
  generation: 606 chars, thinking-off  ✓
  binding: outcome=passed（结构化输出，factual 段全部绑定 web_c7a26954e016ab458dc09362 + claim_12f2…）✓
  consistency: ok=true, 4 claims / 4 links, 0 violations（unknown ids / unbound / direction / state-conflict 全 0）✓
  publish: 606 字符实质回答（**非** 32 字符 fail-closed）✓
```

验收清单（全部满足）：`candidate_non_empty ✓ / raw_segments≤16 ✓（binding passed 即证）/ binding_schema_valid ✓ / unknown_evidence_ids=0 ✓ / unknown_claim_ids=0 ✓ / unbound_substantive_claims=0 ✓ / direction_violations=0 ✓ / evidence_state_conflicts=0 ✓ / published=true ✓`。

**发布答案**：明确列出 CommonJS + ECMAScript 两套系统（[web-1] 引用），描述 `.cjs/.mjs/package.json type` 判定规则，并**对照回答了新旧指引差异**（旧表述把 CommonJS 当默认唯一、现为并列双系统；显式扩展名消除歧义），末尾诚实标注证据边界。人工核查：`.cjs/.mjs` 在 excerpt 内；**`package.json type` 恰位于 400 字符截断点之后**（模型用先验补全，方向正确但超出 excerpt 原文）——记录为 excerpt 窗口的后续 polish 项，不属本批缺陷。

### 46.3 状态（按用户口径）

```text
Discovery / recall           OPEN
Selection                    OPEN（规则窗口 target-loss 已定位）
Read                         DEMONSTRATED
Atomic routing               PASS as mechanism
Extraction                   PASS on positive control
Eligible support formation   PASS demonstrated（run7 / d40.2）
Gate                         PASS demonstrated
Answer formation             **PASS demonstrated（d40.2，首个 E2E）**
Production default           NOT YET（全部开关默认关闭）
```

⇒ **§35 起追的完整 research E2E positive control 首次闭环**。后续顺序：§39 confound 复核 → read reserve → selector 生产化（含 guard 预算语义）→ recall/selection 稳定性；本批所有开关仍为诊断态，生产默认未变。

### 46.3.1 黄金 artifact 与登记债项

- **黄金 positive-control artifact**：`docs/research_quality/ANSWER_FORMATION.d40.2.json`（未跟踪诊断产物，本地保留）。**回归不变量**：未来任何 read reserve / selector / recall / 生产化改动，必须至少保证该 case 不回退——`gate=pass`、`binding=valid`、`consistency=clean`、`publish=substantive`（四项同时成立）；对应开关组合：selector=model + routing=on + bounded policy + consistency gate + grounded input。
- **登记债项（不阻挡既定顺序，先作为人工/诊断指标，不新增模型 gate）**：**Answer grounding entailment / unsupported-detail audit** —— 现有一致性门验证的是 segment↔evidence/claim 绑定、evidence-id 合法性与方向，**不验证"段落中的每个事实可从给定 excerpt 推出"**（d40.2 的 `package.json type` 即位于 400 字符窗口之外、由模型先验补全）。生产默认开启前需要一个（非模型的）文本蕴含/未支持细节审查方案。

### 46.4 §39 confound 复核（已完成，`SELECTION_AUTHORITY.node.confound1–4.json`）

**窄目标**：只在 run1 形态（`RESEARCH_SELECTION_AUTHORITY=model` + `RESEARCH_ATOMIC_ROUTING=on`，不掺任何 answer 改动）下、健康余额重跑，判定当时的 `model_call_attempts_exhausted` 属于哪类。

```text
confound1: target_read=false；juejin 路由 eligible/background（wave2/3）；elapsed 57.2s
confound2: target_read=true → routed extraction **eligible / relation=supports**（wave2）；elapsed 58.0s
confound3: target_read=false；juejin 路由 eligible/background；elapsed 59.5s
confound4: target_read=true → routed extraction **eligible / relation=supports**（wave2）；elapsed 56.5s

model_call_attempts_exhausted 复现次数：**0/4**；
research_model_call_count 10–11，extraction phase 3.9–7.2s。
```

**判定**

1. **资源/402 假设为最俭省解释**：这批失败与账户在 capture3 之后立即出现 `402 Insufficient Balance` 时间重合；gateway 在全部尝试失败时统一返回 `model_call_attempts_exhausted`，余额耗尽与超时在该记录里**不可区分**——健康余额下 0/4 复现，指向资源类原因。
2. **60s research window 假设被削弱**：confound2/4 的 routed extraction 在 **wave 2、总 elapsed 56.5–58.0s**（距 60s 硬预算仅 2–3.5s）依然成功完成。
3. **30s 单调用窗口假设同样不被支持**：成功 run 的 extraction phase 仅 3.9–7.2s。
4. 残留不确定性：当时未记录 provider 错误文本，无法追溯性证明；**建议**（未实施）在 extraction 失败路径的有界 detail 中附带首个 provider 错误码/文本，避免再次出现"402 与超时不可区分"。
5. 附带收获：confound2/4 又贡献两个"目标页 → 路由 supports（primary, cluster 7dcd…）"实例（这两次 gate 仍 block，属评估角色/选择方差，不属本项）。

### 46.5 Read reserve 命中量化（测量完成，待方案决策）

对 22 份含 `selection_trace` 的近期 artifact 全量扫描：

```text
entered_scheduler 候选总数          169
read_budget_exhausted 淘汰          10   （≈6%）
其中"已进 scheduler（ranked）后被 budget 门淘汰"  10
涉及 artifact                        3（ATOMIC_ROUTING.run6/run9、rawprobe1）
其中目标页被该门淘汰                 1（rawprobe1 的 nodejs.cn/api/modules.html）
其余被淘汰 URL                       低价值页（juejin/zhihu/csdn）
```

**结论**：reserve 门不是普遍性失败（10/169），但它确实命中过一次唯一的目标页；对 E2E 成功率是**窄而真实**的风险。

**待决策的修复选项（未实施）**：

- (a) `normal_limit` 对"尚无 eligible support 的 critical claim"临时抬升 1 个读位——直接但改预算语义；
- (b) **无开放冲突时把 reserve 还给普通调度**：reserve 的语义是"留给冲突解"，`open_conflict_claim_ids` 为空时它本来就不会被 `schedule(conflict_claims, reserve, allow_reserve=True)` 用掉——这是最小、语义自洽的改动（有冲突时行为完全不变）；
- (c) 只改选择/排序让高价值候选在 wave1 被读（属 selector/selection 生产化，不属本项）。

推荐 (b)（一行级改动 + 2 条 focused 测试），等确认后实施。

### 46.6 §41 Read Reserve Reclaim（已实施 `505aca8`，三层验收完成）

**语义（用户冻结）**：`open conflict 存在 → 一切不变；不存在 → 未使用的 conflict reserve 在既有 hard read budget 内回流给普通调度`。措辞 = **reclaim unused conflict reserve within the existing hard read budget**（不是增加预算）。不改 ranking/eligibility/conflict 优先权/search/model budget。

**实现**（`_fair_read_plan`）：`reclaimed = 0 / reserve` 由 `open_conflict_claim_ids` 决定；`normal_limit` 加回 reclaimed；同一致回落到 wave planner 的第二层 reserve（`preserve_conflict_reserve` 仅在冲突存在时为 True——否则 planner 内部还会再扣一份，使 reclaim 变成空操作）。`metrics.read_reserve = {configured, reclaimed, reclaim_reason, hard_cap, reads_used}`。

**第一层（focused，3 条）**：无冲突→reserve 可被普通候选使用；有冲突→reserve 严格保留（普通 claim 不排、冲突 claim 可排）；两种模式下 `总 dispatch ≤ max_reads - reads_used` 的 hard cap 不变量。

**第二层（历史复现，run1 形态 4 次；`SELECTION_AUTHORITY.node.reserve1–4.json`）**：

```text
4/4 run：read_reserve = {configured 3, reclaimed 3, reason no_open_conflicts}
4/4 run：**无任何 read_budget_exhausted**（对照 rawprobe1：目标页曾被该门挤掉）
目标页：entered_scheduler=true (rank1) 4/4；read_dispatched = true 3/4
  reserve1 的唯一丢失原因是 assessment window（candidate_pool_excluded）——既有的另一个瓶颈，非 reserve
reserve2：全链 gate=pass（post-fix 新实例）
hard cap：reads_used 2–3，总 dispatch 未超 cap
```

**第三层（黄金不回退）**：`ANSWER_FORMATION.d40.2.json` 是 answer-stage 冻结重放，不经过 scheduler；它继续证明 **下游契约不回退**（gate=pass/binding=valid/consistency=clean/publish=substantive 由 freeze 保证）。**历史 reserve-loss replay + d40.2 downstream golden 两个角色分别保留**：前者证明修复命中测量到的故障，后者证明下游契约稳定。

**§39 confound 关闭措辞（按用户定稿）**：`model_call_attempts_exhausted` 的旧样本无法事后区分具体 provider failure，但与余额耗尽/402 时间高度重合；健康余额下 0/4 复现，且在 elapsed 56.5–58.0s 的 wave2 中 extraction 仍可成功，因此现有证据**不支持** 60s research-window tail 或 30s per-call timeout 是主要原因（**最俭省解释 = 资源/402**，保留 strongest-current-explanation 措辞，不升级为"已证明"）。"extraction 失败 detail 附带首个 provider error code"列为后续诊断项（未实施）。

## 47. §42 Selector Production Contract（已实施 `69b7eb4`；默认关闭）

### 47.1 合同（用户冻结）

```text
candidate_pool → [1 次 model selector（≤K=2，无 app 级 retry）] → usable?
  ├─ yes → model picks
  └─ no  → deterministic legacy window（在**同一原始 pool** 上重跑）
        → 既有下游
```

- **usable 机械判定（不由模型自述）**：调用 completed + schema 合法（`urls: [str]`，parse 失败经 attempt audit 的 error types 区分为 `invalid_schema`）+ 每个 URL 都在**输入候选集**内 + 无 forbidden（已排除候选）+ 无重复 + 数量 1..K（**over_k 直接 fallback，不截断后偷偷接受**）。
- `unusable_reason` 枚举：`empty / call_unavailable / invalid_schema / unknown_url / duplicate_only / over_k / policy_violation`。
- **fallback = 原始 pool 上的 legacy window**（不是模型剩余的候选）：`original_pool / model_picks / fallback_picks / final_picks / selection_source` 独立可审计。
- **预算**：selector 属于 **orchestration** 工作——`metrics.orchestration_model_calls` 每次尝试 +1；不动 search/read/evidence budget；qualification guard 下仍计入全局物理调用 cap（"语义上属于 orchestration；资源上仍然是真实模型调用"）。
- 默认 off：bit-for-bit 保持原 selection（有测试断言默认路径**完全不会调用模型**）。

### 47.2 测试（17 条合同测试，`tests/test_selection_authority.py`）

合法 2 选 → model picks；`[]` → empty；unavailable → call_unavailable；schema 失败 → invalid_schema（与 transport 区分）；池外 URL → unknown_url；3 选 K=2 → over_k；重复 → duplicate_only；forbidden → policy_violation；异常不抛出；**每 window 恰 1 次逻辑调用**；诊断字段全量；默认 off 不触模型；**fallback 在原 pool 上**（与直接调 legacy window 结果逐 id 相等）；model 路径记账；**availability 不变量（unavailable 模型也不能把 legacy 能填的窗口变空）**。

### 47.3 Live 验收（Node case ×6；`SELECTION_AUTHORITY.node.s42_1–6.json`）

```text
selector_caused_availability_loss = 0/6 runs（0/28 windows）  ← 合同核心目标达成
usable 窗口 → selection_source=model（s42_5 等多次出现）
unusable 窗口 → legacy_fallback，final_picks 恒非空（2/1 交替，与 legacy 一致）
目标页：entered_scheduler rank1 5/6；read_dispatched 3/6；gate=pass 1/6（s42_5）
orchestration_model_calls = 4–6/run（与 window/claim 数一致）
```

**观察（记录为债项，不属本批修复）**：unusable 中 `invalid_schema` 占多数（约 16/28 windows）——DeepSeek json_object 输出对 `{"urls": [str]}` 契约的遵从度不稳；`empty`、`call_unavailable` 次之。合同已证明"模型输出不达标也不会降低 availability"，但若要提升 model-path 占比，下一步应做 **schema 遵从性硬化**（不是调提示词追命中率），列为后续项。

## 48. §43A Selector Schema Reliability（已完成 `de7fcf4`；invalid_schema → 0）

### 48.1 分型（先分类，不改 prompt）

- 工具 `tools/run_selector_schema_probe.py`（7 条分类测试）：同传输（同 prompt/池/模型/`json_object`/`max_tokens=500`）直接采样原始响应，形状分类：`contract_shape / url_array / fenced_json / valid_json_wrong_shape / valid_json_wrong_field / truncated_json / non_json_text / empty_content`。
- **首轮采样 20/20 `contract_shape`** ⇒ `invalid_schema` **不是模型输出形状问题**。

### 48.2 根因：selector 调用缺 thinking-off 传输配置

对比 gateway 路径后发现：`select_candidates_with_model` 是**唯一**没有携带 provider thinking-off extra_body 的结构化研究调用（assessor/extractor 都经 `research_structured_output_capabilities` 注入）。DeepSeek 默认 thinking 会吃光 500-token 输出预算 → 空/截断 JSON → `json.loads` 失败 → 被记为 `invalid_schema`。属**传输配置缺口**，非语义/遵从性问题。

### 48.3 修复（表示层，不动语义）

- `select_candidates_with_model`：解析 `research_structured_output_capabilities(provider_profile)` 并传入 thinking-off `extra_body`（与 assessor/extractor 同款）。
- `parse_selection_response`：额外接受**无歧义**的顶层 URL 字符串数组（`["url1","url2"]` → `urls`）——纯表示层归一，不解析自然语言、不截断、不猜。
- 新增测试：url 数组接受/拒绝；fake gateway 断言 selector 调用携带 thinking-off extra_body。

### 48.4 复测（4 runs；`SELECTION_AUTHORITY.node.s43a_1–4.json`）

```text
invalid_schema：**0 次**（约 30 个 window；修前 ≈16/28）
usable/model path：~28/30 window（s43a_3/4 全部 usable=model）
selector_caused_availability_loss = 0/4（不变量保持）
目标页：read_dispatched 4/4；gate=pass 2/4
orchestration_model_calls：4–7/run
残余 unusable：仅 "empty"（个别尾部 wave 的池子几乎空时模型返回 []）→ fallback 正常
```

**§43A 关闭**。记录一个小债项：无输入（`limit==0`）时也会写 selection_authority 记录且 `unusable_reason=""`，后续可补 `no_input` 语义（不影响合同）。

**§43B（下一批）**：在 **target-containing pools** 上做 paired A/B（同一 frozen original_pool、同 K=2：A=legacy window，B=production-contract hybrid），统计 `conditional_target_selection_rate`、`conditional_target_read_rate`、`legacy/hybrid/model_path/fallback target hits`、`selector_caused_losses=0`，并报告成本 `incremental_target_reads / orchestration_model_calls`；之后才讨论 selector 默认开启与 recall。

## 49. §43B Paired A/B：legacy window vs production-contract hybrid（已完成，3×4=12 pairings）

工具 `tools/run_selector_ab.py`（3 条 focused 测试）：同一 frozen pool、同 K=2，A=deterministic legacy window，B=production-contract hybrid（1 次 selector 调用；usable→model picks；否则同一原始 pool 上跑 legacy）。Pool 来源：Node=**agreed 标注** likely-targets；Docker/PostgreSQL/uv=**已知权威目标页注入**（附在 frozen pool 末尾，标注 `injected`——测"埋没目标的恢复"，不是 recall 主张）。

**逐池结果（第 1 次 run，含真实 read）**

| Pool | Source | Legacy hit | Hybrid hit | Path | Target read L/H | Calls |
|---|---|---:|---:|---|---|---:|
| rq1c-current-policy-container-registry | injected | 0 | 1 | model | – / failed* | 1 |
| rq1c-current-support-postgresql | injected | 0 | 1 | model | – / ok | 1 |
| rq1c-simple-license-uv | injected | 0 | 1 | model | – / ok | 1 |
| rq1c-historical-current-node-modules | annotated | 0 | 1 | model | – / ok | 1 |

\* Docker 页首次 read 失败为瞬时问题：单独复读成功（ok，520 字符——正文偏短，另行观察；不影响 selection 指标）。

**汇总（3 次重复 ×4 pools = 12 pairings）**

```text
conditional_target_selection_rate  legacy = 0/12 (0.0)   hybrid = 12/12 (1.0)
wins = 12   ties = 0   losses = 0   selector_caused_losses = 0
model path = 12/12（无 fallback 触发；fallback 合同已由 §42 live 验证）
orchestration_model_calls = 12
incremental_target_reads = 12
incremental_target_reads_per_selector_call = 1.0
```

**结论与限定**：

1. **在"池中已存在目标页"的条件下，hybrid 12/12 选中目标、legacy 0/12；wins>0、losses=0、selector_caused_losses=0** —— 满足用户设定的"值得讨论默认开启"的门槛。
2. **限定必须写清楚**：12 个 pairing 中 9 个来自 injected pools（目标被刻意放在队尾），legacy 的 0/12 部分由构造决定；Node 是唯一自然标注池（legacy 0/1 与 §37B 的窗口丢失一致）。因此这批证明的是 **model preference authority 的 buried-target recovery + 零回退损失**，不是野外 selection 分布。
3. 成本口径：`incremental_target_reads_per_selector_call = 1.0`（这里每池 1 次调用换来 1 个额外 target read）；prompt/语义未做任何调优（§43A 只修传输）。

**下一步（按既定顺序）**：selector 默认开启的决策材料已具备（以"零 losses + 成本可解释"为前提），但建议先补**更多 natural target-containing pools**（而非重复同一池）再定默认；随后回到 **recall**（11/12 case 无 likely-target）。

## 50. §43C Natural Selection Lift 采样（已完成，`16ed41c`）

工具（不改 selector）：

- `tools/run_natural_target_scan.py`：读取自然运行 artifact，从各 case 自己的 search discovery 重建候选池，检查已知目标页（Node 标注 + Docker/PostgreSQL/uv 权威页）是否**已进入池**，冻结每个 distinct 的自然 target-pool（presence-only，不是 recall 主张）。
- `tools/run_selector_ab.py`：新增 `--pools-file`（冻结自然池输入）、池分类 `A_recovery / B_preservation`、以及 **`replacement_loss`**（legacy 命中而 hybrid 丢失）——与 `selector_caused_losses`（窗口不得变空）区分开。

**自然采集（4 个已知目标 case × 2 次 = 8 次自然运行，全部默认 legacy、无任何 selector 开关；另对历史 17 份 artifact 全量扫描）**：

```text
distinct natural target-containing pools = **6**（全部 Node：§37A 池含双镜像 + 5 个单镜像变体）
Docker / PostgreSQL / uv：17 份 artifact 中 **0 次**目标进池
→ 自然 target-pool 的供给本身被 recall 限制（与 11/12 无 likely-target 的结论一致），且当前唯一自然供给源仍是 Node 单 case
```

**自然池 paired replay（`SELECTOR_AB.natural6.json`，N=6）**：

```text
pool_class = A_recovery × 6（legacy miss / target in pool）
legacy hit = 0/6 → hybrid hit = 6/6（source=model ×6）→ wins = 6
replacement_losses = 0；selector_caused_losses = 0
orchestration calls = 6；incremental_target_reads / selector_call = 1.0
（read 列本轮 --no-read 跳过；单池真实 read 已在 natural1 验证 ok）
```

**结论与阶段判定**：

1. 机制层面：**target 一旦进池，model preference authority 的恢复稳定存在**（12/12 injected + 1/1 natural），且至今**零 replacement loss、零 availability loss**。
2. **selector 默认开启的"野外分布"判据仍未满足**——不是 selector 不行，而是**自然样本供给受 recall 限制**（8 次自然运行仅 1 个池含目标）。继续堆同池重复只测 stochastic stability，不测泛化。
3. 因此主精力按计划切回 **recall**：等 recall 改善产生更多自然 target-pool 后，再回来做默认开启决策（判据已冻结：wins>losses、losses/replacement/availability 全 0、model-path usable 保持、成本可接受）。

**阶段总结（用户口径）**：Evidence chain 闭环 ✅ · Answer path 闭环 ✅ · Reserve 已修 ✅ · Selector transport 已修 ✅ · Selector safety 已证 ✅ · Selector lift 已证（条件性）✅ · **Recall = 当前最大开放问题**。

## 51. §44A Known-target Recall Audit（已完成 `19747a1`；结论：provider 检索面是首要嫌疑）

### 51.1 历史 query 审计（`RECALL_AUDIT.historical.json`；§37A 全量 + 8 次自然运行）

对每个已知目标页，把**历史上实际发出的每条 query** 做机械相关度分层 + provider 返回事实：

| case/target | queries | relevance 分布 | 目标页返回 | 同域返回 | 近似页返回 |
|---|---:|---|---:|---:|---:|
| Docker `docs.docker.com/docker-hub/usage/pulls/` | 10 | direct 5 / plausible 1 / weak 4 | **0** | **0** | 0 |
| PostgreSQL `postgresql.org/support/versioning/` | 12 | plausible 12 | **0** | 12 | 0 |
| uv `github.com/astral-sh/uv/.../LICENSE-MIT` | 4 | plausible 4 | **0** | 4 | 0 |
| Node `nodejs.cn/api/modules.html`（参照） | 9 | weak 9 | **4** | 9 | 4 |

**读法**：
1. **Docker 是最强信号**：5/10 条 query 属 `direct_targeting`，但目标页与**同域任何页面**都从未返回 → 不只是"query 太泛"。
2. PostgreSQL/uv：同域返回充分（12/12、4/4），但**深页/功能性页面从未出现**（版本政策页、LICENSE 文件）。
3. Node 参照证明 provider **并非完全召不回深页**（4/9），所以问题是**不稳定/不可解释**，而不是绝对能力缺失。

### 51.2 exact-title 正例探针（`RECALL_AUDIT.probe.json` top5 / `RECALL_AUDIT.probe10.json` top10）

3 类 query（exact title / title+entity / semantic）× 4 目标：

```text
top5  : 0/12 hit
top10 : 0/12 hit（结果形态见下）
  Docker   exact "Pull usage and limits" → 词典/百科"pull"词条（连 docker.com 都没回）
  PostgreSQL exact "PostgreSQL Versioning Policy" → postgresql.org 首页 / download
  uv       exact "uv LICENSE-MIT" → runoob/csdn 教程
  Node     exact "Node.js two module systems" → 百度知道/经验（历史 4/9 命中过）
```

**判定（按用户预设决策树）**：

> **exact title 都召不回 → 现有 provider 合并栈的 retrieval surface 不适合作为高精度 research recall backbone。**

即：**瓶颈主要在 provider 检索面（或合并/排序逻辑），不在"LLM query 表达能力"**。因此：

1. **暂不做** LLM-intent→deterministic compiler 的大改（该方向只有在"exact title 能召回、semantic 召不回"时才成为首选）。
2. 下一步应是 **provider 级归因**：对 exact-title 类 query 分别探测 searxng / bing_rss / duckduckgo_html 的**单独返回**（谁返回了什么、rank 多少），并检查合并层（top-k 截断、去重、排序）是否丢掉了深页；若单 provider 也召不回 → 讨论**换/补 provider**（例如直连官方站内检索、或增加可返回深页的 provider）。
3. Docker 的 `direct_targeting + 0 同域` 也提示：SearXNG/Bing 的**中文区域化结果**（词典/百科/教程）可能压过了英文官方深页——provider 的区域/语言参数值得进入归因清单。

**状态表（更新）**：Research E2E positive control PASS · Answer formation PASS demonstrated · Atomic routing PASS demonstrated · Read reserve FIXED · Selector transport PASS · Selector safety/fallback PASS · Selector conditional lift PASS · Natural selector generalization supply-limited · **Recall = PRIMARY OPEN BLOCKER（当前定位：provider retrieval surface）**。

## 52. §44B Provider Attribution Audit（`aea23d8`；结论：生产栈实际只有 Bing RSS）

### 52.1 决定性历史事实：effective provider surface = Bing RSS 单栈

对 §37A 冻结语料（95 query / 475 结果）逐结果统计 `provider` / `providers` 字段：

```text
bing_rss: 475/475（100%）
searxng / duckduckgo_html: 0
```

⇒ 历次"多 provider 合并栈"在此环境下**实际只有 Bing RSS 在供结果**；searxng 与 DDG 的 attempt 只出现在 `providers_attempted`，从未贡献任何结果。（与早期环境记录"仅 Bing RSS 稳定"一致，但此前未被量化到 100% 这个程度。）

### 52.2 §44B 工具与当前归因（`PROVIDER_ATTRIBUTION.json`）

工具 `tools/run_provider_attribution.py`（4 条 focused 测试）：对每个 known target × 3 类 query 分别取三 provider **raw top-20**，重放生产 round-robin merge（width 10 / width 5），记录 `provider_returned / raw_rank / post_merge_rank / survived_topk / drop_reason`、官方深页 merge 前/后计数、结果语言分布，并对 searxng 腿做 `language=en` 诊断变体（生产固定 `zh-CN`），按冻结决策树输出分支。

本轮运行结果：**12/12 探针全部 A_provider_capability_insufficiency**（无任何 provider 在 raw top-20 返回目标；en 变体也未命中）。

### 52.3 环境限定（必须与结论一起读）

运行时的 provider 存活状态：

```text
bing_rss            : 正常（200；可返回 10 条 generic 结果）
searxng（容器已启动）: 引擎全部失败 — brave:timeout; duckduckgo:timeout; google cse:HTTP connection error; startpage:timeout
duckduckgo_html     : urllib timed out
直连观测            : bing.com 200 / postgresql.org 200 / duckduckgo.com timeout / google.com connection refused
```

因此：
1. **A 类结论只对"实际生效的 provider = Bing RSS"成立**：exact-title 在 Bing raw top-20 也召不回四个已知深页（Docker/PostgreSQL/uv/Node 全含）。
2. **locale 分支（D）本轮不可测**：searxng 的 en 变体没有可用引擎，无法区分"locale 问题"与"引擎被网络阻断"。
3. 若网络恢复（DDG/Google/Brave 可达），§44B 应重跑以区分 searxng/DDG 各自能力；但鉴于 475/475 的历史事实，**provider surface 的真实上限目前就是 Bing RSS**。

### 52.4 对 recall 路线的影响（记入决策）

- "换/补 provider"已从可选项升级为首要候选：可选方向 = 官方站内检索 / 支持深索引的搜索 API（带 key 的 Bing Web Search、Google CSE 等）/ domain-aware targeted retrieval（已知官方域时直接读站内搜索页）。
- query compilation / LLM-intent compiler 继续搁置（其前提是"exact title 能召回、semantic 召不回"，当前不满足）。
- 复跑条件：网络出口允许 DDG/Google（或选用其它可达 provider）后，§44B 重跑 + 对候选新 provider 做同一 exact-title 三件套。

## 53. §44C Replacement Provider Qualification（已准备 `aa77a260`；等待 Brave API key）

### 53.1 候选顺序与依据（用户冻结）

```text
Tier 1: 通用高质量 Web provider（首选 Brave Web Search API）
Tier 2: 已知官方 domain 的 targeted retrieval（planner 已给出 desired domain 时；general provider miss 之后才用）
Tier 3: fallback
```

- **为什么不是 Bing/Google API**：Bing Search APIs 已于 **2025-08-11 退役**（现推荐 Grounding with Bing Search，不是同层通用 Search API）；Google 旧的 Custom Search Site Restricted JSON API 已于 **2025-01-08 停服**；Google 新的 Web Search Service API 需 API key **+ partner agreement 的 client ID**，不能即取即用。Brave 提供正式 Web Search API：独立索引、结构化 url/title/description、单次最多 20 条、支持 `country` / `search_lang` / `ui_lang`——正好匹配 §44A/§44B 的 raw-top20 harness。
- 成本：$5/1000 requests + 每月 $5 credits；本批 4 targets × 3 query × 2 参数集 = **24 次调用 ≈ $0.024**，在免费额度内。

### 53.2 资格考试（provider-only，不接 merge/planner/selector）

工具 `tools/run_brave_qualification.py`（5 条 focused 测试）：

```text
四目标 × 三 query 类（exact title / title+entity / semantic）× 两参数集（default / country=us,search_lang=en,ui_lang=en）
count=20；记录 target_returned / target_raw_rank / official_domain_hit /
official_deep_page_count(merge 前) / latency / status/error / CJK 结果数
```

**冻结 gate**：Docker 与 PostgreSQL 的 **exact-title raw-top20 必须命中**，否则该 provider 直接判不合格；exact/title+entity 的缺失按 target 列出。

运行方式：`.env` 增加 `BRAVE_SEARCH_API_KEY=<key>`（`.env.example` 已加占位）后执行
`python -m tools.run_brave_qualification --output docs/research_quality/BRAVE_QUAL.json`
——当前无 key 时工具会干净退出并提示（已验证）。

### 53.3 通过后的既定路线（未实施）

1. 先只做 **provider → normalization → existing merge contract → existing selector** 的接线验证（仍不动 planner/selector 语义）。
2. **provider 健康指标升级**（记入待办）：`providers_configured / attempted / succeeded / contributed_results / result_count_by_provider`，并加实用告警——**某 provider 连续 attempted N 次但 contributed=0 时，不再计入"有效 provider 数"**（§44B 用 475/475 的代价换来这条教训）。
3. Tier-2 的 domain-targeted retrieval 只在 Tier-1 miss 后触发，避免再次规则膨胀。

## 54. §44C 路线修订：约束"仅依赖 DeepSeek API" → Brave 取消，改走 §44C-Alt（已通过）

### 54.1 约束修订（用户）

**项目只允许依赖 DeepSeek API**（不加任何新的第三方搜索 API / 账号）。因此 §44C 的 Brave 路线**取消**（Brave key = 其 Search API dashboard 的订阅 token，需要注册第三方账号与计费，与本约束冲突）。合并栈维持：Bing RSS（免费抓取，实际唯一在跑的 Tier-1）+ SearXNG 容器（引擎被网络阻断时贡献 0）+ DDG（网络阻断）。

### 54.2 §44C-Alt：LLM URL 提案 + reader 验证（DeepSeek-only，已实施 `411a054`）

机制（只加一个 Tier-2 候选来源，不动 merge/planner/selector 语义）：

```text
claim（+ 已有的 entity/domain 线索）
   ↓ 1 次 flash 调用（json_object、thinking off、≤3 个 URL）
proposed official URLs
   ↓ 既有 reader 实测（ok + 非空正文）
verified deep page → 作为候选进入既有下游（评估/读取计划/抽取/Gate 不变）
```

- 反幻觉护栏：只接受 https、只作为**候选提案**（先 reader 验证才成立）、抽取决不与 Gate 语义改变——证据资格仍由 extractor + Gate 决定。
- 与 Tier-1 的关系：Bing RSS 保持现状（免费、无需 key）；提案层是"当搜索召不回官方深页时"的第二级；Tier-3 仍是 fallback。

**资格测试（`tools/run_url_proposal_qualification.py`，4 条 focused 测试；`URL_PROPOSAL_QUAL.json`）**：

```text
gate = PASS（hard：Docker/PostgreSQL exact 提案；每 case 至少 1 个可读页）
docker     : 精确提案 docs.docker.com/docker-hub/usage/pulls/（reader ok）
postgresql : 精确提案 postgresql.org/support/versioning/（reader ok）
uv         : github.com/astral-sh/uv + blob/main/LICENSE + docs.astral.sh/uv/（reader ok）
node       : nodejs.org/api/modules.html 等（reader ok，6000 chars）
延迟：0.5–2.2s/案（1 次 flash 调用）；无新增外部依赖。
```

对照：这些深页在 §44A/§44B 里经 **Bing RSS raw top-20 全部召不回**（含 exact title）——**提案+验证在本环境可稳定恢复官方深页**。

### 54.3 下一步（建议，未实施）

1. 把提案层接成 runtime 的 **Tier-2 诊断开关**（默认关闭）：在 gap/claim 有明确 entity 或 desired domain、且 Tier-1 结果里无官方深页时，允许 1 次提案调用 + reader 验证，候选带 `discovery_method="llm_proposed"` 溯源；预算计入 orchestration 层（与 selector 同口径）。
2. 用同一验收链（Node/Docker）验证 `提案 → 候选 → read → extract supports → gate pass → answer`，并保持 selector/atomic routing/consistency 开关组合不变、不回归 d40.2 四项不变量。
3. 仍排队：provider 健康指标升级（configured/attempted/succeeded/contributed + attempted-N-contributed-0 告警）、§44B 在网络允许时的 provider 级复核、recall 的更大样本。

## 55. §45 Tier-2 LLM 提案接入 runtime（已实施 `8bb3310`/`8a1ade2`/`bc771af`，默认关闭）

### 55.1 合同与实现

```text
proposal → URL 校验 → reader 验证 → candidate → assessment → extraction
        → support → eligibility → Gate          （LLM 提案永不直接成为证据）
```

- `src/web/research/llm_proposal.py`：`RESEARCH_LLM_PROPOSAL`（默认 off）、https-only 严格解析（≤3、canonical 去重）、Tier-1 miss 谓词、提案 messages。
- runtime `_tier2_proposal_step`：每 claim 每次运行最多 1 次提案调用（json_object + thinking-off，与 selector 同传输契约）；候选写入 `discovery_method="llm_proposed"` + 该 claim 的 query 锚点；`metrics.tier2_proposal`（miss 原因/调用状态/proposed/verified/dropped+detail/verification_reads/added ids）与 `metrics.tier2_funnel`（proposed→assessed_relevant→read→extracted_supports→gate_eligible，逐 wave 重算）。
- **触发契约（精确）**：仅当"该 claim 已有 ≥1 次完成的物理 read、仍无 supports、且当前评估里没有 answer_relevant 候选"时触发；`claim_has_support=True` 或 Tier-1 尚未被消费（completed_read=0）时保持静默（单元测试覆盖）。

### 55.2 两次真实缺陷修复（都记录在案）

1. `8a1ade2`：验证 read 用了位置参数，而 `gateway_read(url, *, max_chars)` 是 keyword-only → TypeError 被吞成空 dict → 全部 `read_failed` 且无 detail。现用 `read_fn(url, max_chars=1200)`，异常文本入 detail。
2. `bc771af`：Node 对照跑显示 Tier-2 在 **Tier-1 尚未被消费前**（wave 1、无任何 read）就触发；触发谓词加入 completed_read ≥1 与 claim_has_support 两项状态条件。

### 55.3 验收（raw run，开关：`RESEARCH_LLM_PROPOSAL=on` + selector=model + routing=on，部分含 answer 开关组）

```text
docker run3: Tier-1 miss → 提案精确 URL ×3（pulls/usage/根）→ 验证 2 个（pulls 命中瞬时
            WinError 10054 被丢弃）→ 候选走完 assessment(read=1)/extract(lead)/gate_eligible=1
docker run4: 提案精确 pulls 页并在**正常读取路径**中成功读出（sources: read + eligible）→
            gate_eligible=1（relation=lead, primary）；gate 仍 block，但**原因已换层**：
            页面正文过短（520 字符壳页）→ extractor 无法给出 supports ⇒ Docker 的下一个
            blocker = **read adequacy**（不再是 recall/discovery）
node   run2: gate=pass；Tier-2 在该 claim"已读但尚无 support"时触发，其候选
            （nodejs.org/api/modules.html）被评 relevant → read → extract **supports** →
            gate_eligible=1 ⇒ 本轮 supports 实际来自 Tier-2 通道；触发先于 Tier-1 support
            落地，属状态谓词（契约不矛盾）
```

**结论（本批冻结）**：

1. **Tier-2 作为独立 discovery 通道已闭环**：proposal→验证→候选→评估→read→extraction→Gate eligibility 全链可跑；Docker 从"永远召不回"变成"精确页进链并以 lead primary 计入门禁"。
2. **Discovery 可换、证据链不换**成立：同一 extractor/Gate/answer 语义下，Tier-2 候选与 search 候选走完全相同的下游。
3. 下一层 blocker 已由数据指出：**Docker 的 read adequacy**（壳页 520 字符）与 **Tier-1 support 落地前的时序**；均记录为后续项，不在本批修。
4. 默认关闭不变；生产路径不启用。

### 55.4 冻结记录的两处修正（按用户 §45 冻结语句核对）

1. **触发条件的 read 计数改为 claim 级**（`3c69463`）：用户冻结语句要求"**当前 claim** 已完成至少一次 read"，而实现此前用的是**运行级** `len(completed_read_ids)`——其他 claim 的 read 可能误解锁 Tier-2。现改为统计属于该 claim 候选集的 read outcome，并新增测试证明"外 claim 的 read 不触发"。
2. **全量 pytest 门禁补跑**（head `3c69463`）：**2036 passed / 2 failed（650s）**；两个失败均是已登记的 Windows-local 平台族（`test_rq1c_impl_entrypoints::…exact_head_guard`、`test_rq1c_protocol_probes::…deterministic_protocol_runner…`），父提交同样复现，**非本批回归**。此前记录中的"existing suite = PASS"应以此条为准。

其余冻结项复核一致：`RESEARCH_LLM_PROPOSAL` 默认 off；未新增第三方商业 Search API；Tier-1 / selector / routing / extractor / Gate / answer consistency 语义未动；Discovery 可换、证据链不换。

## 56. §46 Read Adequacy 特征化（首轮完成 `82caa33`/`df0763f`；结论：本地方案无提升空间）

工具 `tools/run_read_adequacy_probe.py`（9 条 focused 测试；纯本地、无新依赖）：对样本 URL 同时测 (a) 生产 read（`ActiveResearchGateway.read`，6000 上限）与 method；(b) 原始 HTML 抓取（chars/final_url/reason）；(c) **三个本地抽取器**各自产出（trafilatura-precision / readability / HTMLParser，20000 上限）——回答"同一页面是否有更完整的本地抽取路径"。形状分类：`ok / short_doc / extraction_loss / js_shell / anti_bot_or_error / redirect_landing / fetch_failed`。

**样本**：4 个已知目标 + 4 个 artifact 中观测到的官方深页（去重，cap 12）。**结果（`READ_ADEQUACY.probe2.json`，8 URL）**：

```text
ok           : 5   （postgresql versioning 2384 / uv LICENSE 1077 / nodejs.cn+nodejs.org modules 6000 /
                      github.com/docker 1117——多个页面本地抽取器还能给更多，但生产均已达标）
short_doc    : 1   ← docs.docker.com/docker-hub/usage/pulls/：
                     production=520 chars，而原始 HTML=**349,998 chars**，三个本地抽取器**全部只有 520**
                     ⇒ HTML 可成功抓取，但正文不在常规文本节点中 ⇒ **本地抽取器无法补救**
fetch_failed : 2   ← docs.docker.com 两页（连接重置 10054；该 host 抓取在本环境反复出现瞬时 reset）
short_doc_ratio      = 1/8 = 12.5%
unreadable_or_failed = 3/8 = 37.5%（1 short_doc + 2 fetch_failed）   ← 不得与"短页比例"混用
local_richer_available = 0    answer_question_3 = **no**
```

**三问的答案（冻结记录，措辞已按精度要求修正）**：

1. **比例必须拆分**：真正 `short_doc` = **1/8（12.5%）**；`unreadable_or_failed`（不可正常读取或失败）= **3/8（37.5%，1 short_doc + 2 fetch_failed）**。两者不可混为一谈。
2. **形状**：`short_doc`（HTML 约 350k 字符而三种本地抽取器恒 520 字符）符合 **JS/client-rendered 或 script-embedded 内容形态**——本轮**未做浏览器执行验证**，不做比实验更强的断言；`fetch_failed` = connection reset / 10054（**fetch 层**失败，非 extractor）；**没有** extraction_loss、anti-bot、redirect。
3. **不存在"同一 URL 的本地更完整路径"（0 extraction_loss）** ⇒ **不应实施 trafilatura→readability→parser 的抽取器 fallback**——无本轮实验支持。

**可选的下一层（仅记录，不实施）**：

- (a) 对 `fetch_failed`：reader 侧有界重试/退避（本地行为，不改依赖）——**§47 将先把它量化**；docs.docker.com 的 10054 为**本实验环境内观测到的 fetch flakiness**，不应泛化为"官方站点整体稳定性"结论。
- (b) 对短文本页：需要**本地 headless browser** 才能验证/获取 client-side 渲染正文——这是 **runtime dependency / reader capability 决定**，不是 extractor fallback；本轮不实施。
- (c) 接受现状：把此类页面视为 unreadable，证据资格交给既有链。
- 观测项：Docker 的 read adequacy 由**两类不同问题**组成——内容形态（正文不在常规文本节点）与 fetch 层波动（10054）；不是本项目 reader 选择问题。

## 57. §47 Fetch Retry/Backoff 特征化（`7853cfb`；结论：retry 有效、成本可承受）

工具 `tools/run_fetch_retry_characterization.py`（5 条 focused 测试；注入式 fetch 序列 + 实时 fetch 两用）：每 URL 6 trials，每 trial 最多 3 attempts、固定 1s/2s 退避；记录 `first_attempt_failure_rate / retry_success_rate_given_first_failure / attempts_to_success / final_success_rate / latency / failure_signature_counts`。样本 = 3 个 docs.docker.com 页 + 1 个对照页。

**结果（`FETCH_RETRY.probe1.json`，24 trials）**

| URL | 首发失败率 | 首败后重试成功率 | K=3 最终成功率 | 失败签名 |
|---|---:|---:|---:|---|
| docker-hub/usage/pulls | 3/6 = 50% | 1/3 = 33% | **4/6 = 66.7%** | WinError10054 ×7 |
| docker-hub/usage | 3/6 = 50% | 3/3 = 100% | **6/6 = 100%** | WinError10054 ×5 |
| desktop/windows-install | 4/6 = 66.7% | 3/4 = 75% | **5/6 = 83.3%** | WinError10054 ×7 + RemoteDisconnected ×1 |
| postgresql 对照 | **0/6** | — | 6/6 = 100% | 无 |

**延迟成本**：成功单次 p50 ≈ 3.0–4.5s（Docker 页本身慢；对照 1.3s）；带重试的 trial 总延迟 p50 ≈ 3.6–4.5s、max 4.4–8.0s（≈ 成功那次 + 1–2 次退避）。在 48s research window / 60s hard budget 内属**每秒级、可承受**成本。

**结论（冻结）**

1. **在当前实验环境下呈现明显的 docs.docker.com 特异性**：Docker 三页首发失败 50–67%，同环境对照页 0/6；失败签名以 WinError10054 为主（另有 1 次 RemoteDisconnected）。**不将其绝对归因为 host 固有属性**——6 trials/URL 属特征化实验，不用于估计长期失败分布或通用网络失败率。
2. **有界 retry/backoff 显著恢复可用性**：最终成功率 50%→100%（usage）、67%→83%（windows-install）、50%→67%（pulls，仍有 1/6 trial 三次皆失败）。**retry 是恢复机制，不是可达性保证。**
3. **只对症 `fetch_failed`**：§46 的 `short_doc`（HTML 349,998 chars → 提取恒 520）是内容形态问题，retry 不会带来正文；**不得把 retry 当作 short_doc 的修复**。
4. 若动 runtime，最小方向是 **reader 侧有界重试（≤2 次、1s/2s 退避、仅 fetch-layer 失败）**；不改 extractor、不改依赖边界、不引入外部服务。
5. **样本限制（正式记录）**：4 URLs × 6 trials = 24 trials；结果用于失败形态识别、retry 是否值得进入下一阶段、延迟数量级判断；**不用于**估计长期失败率、推断通用网络失败率或给出生产成功概率。Docker pulls 的 `3/6 首发失败 / 4/6 K=3 成功` 属当前环境的 observed characterization，不是 SLA。

## 58. §48 Reader Retry 接入（默认关闭）与 E2E 对照（`8ecbff0`/`79ff540`）

**实现**（`RESEARCH_READ_RETRY=on`，默认 off）：

- `src/web/research/read_retry.py`：≤2 次重试、固定 1s/2s 退避、**仅 fetch-layer 失败**（URLError/RemoteDisconnected/10054/reset/timeout/SSL handshake 等 signature）；**成功读取（无论多短）与 policy 失败（如 `unsafe_or_empty_url`）一律不重试**——不得把 §46 的 `short_doc` 当网络问题。
- `ActiveResearchGateway.read` 仅在开关开启时走 `read_with_bounded_retry`；返回附带 `read_retry:{attempts,retries,retry_reasons}`；runtime `_source_record` 将其有界保入 source record（诊断字段，不触证据语义）；probe 已能捕获。
- 9 条 focused 测试（策略/上限/退避/异常计入/两条 adapter 路径）。

**E2E 对照（Docker case，恒定开关：selector=model + routing=on；proposal=off 以隔离变量；各 2 次）**

```text
off1: reads=3  ok=0 failed=3  gate=block   elapsed=33.7s  retried=0
on1 : reads=5  ok=3 failed=2  gate=block   elapsed=50.0s  retried=1
        ← docker.com：10054 → retry#1 → 成功
off2: reads=1  ok=1 failed=0  gate=block   elapsed=28.2s  retried=0
on2 : reads=3  ok=2 failed=1  gate=partial elapsed=72.9s  retried=1
        ← github.com/docker：TimeoutError → retry#1；SSL handshake timeout → retry#2（共 2 次）

读成功：OFF 1/4 vs ON 5/8（小样本，方向性）
```

**结论（冻结）**

1. **机制在真实运行中复现**：3 次重试事件分别命中 10054 / read timeout / SSL handshake timeout，均按 ≤2 次、1s/2s 策略执行。
2. **延迟成本真实且不可忽略**：ON 臂 elapsed +16s ~ +45s；on2 达 **72.9s**（超过 48s research window，finalization 与窗口重叠）。⇒ 若将来采纳，retry **必须做窗口感知**（剩余研究时间不足时不再发起重试），否则以 finalization 头寸换 recall。
3. `gate=partial`（on2）是单次观察，**不作为因果增益证据**（受 assessment/extraction 方差影响）。
4. d40.2 四项下游不变量本批未触碰（answer 路径无改动）；**默认仍为 OFF**，生产行为未变。
5. 样本量：2 对 OFF/ON，属 observed characterization，不构成分布结论。

**下一步候选（未实施，待拍板）**：(a) 窗口感知版的 retry 诊断开关 + 更大样本 E2E（含 Node 对照与 d40.2 不变量复核）；(b) 本地 headless browser 的 runtime 依赖决定（针对 §46 short_doc 形态）；(c) provider health metrics 升级（§46+ 清单）。

## 59. §48 结项（用户冻结版 §59，摘要；实现见 §58）

**Status：PASS / CLOSED（characterization）。** 冻结要点：

1. **机制成立**：bounded retry 在真实 E2E 复现（10054 / TimeoutError / SSL handshake timeout；共 3 次实际 retry attempt），恢复后的 source 进入既有 downstream。
2. **读成功率方向性改善**：本批 OFF 1/4=25% vs ON 5/8=62.5%（+37.5pp）；N=2 对，**不得作为总体成功率或统计显著结论**。
3. **延迟成本是新的主要约束**（本批核心）：两对 Δ=+16.3s / +44.7s，且 on2 elapsed=**72.9s**，超过 48s research window 与 60s hard budget。该 Δ 是**观察到的运行时差异**，不作纯因果开销估计。
4. **新冻结设计约束**：retry 必须具备 **window awareness** —— `remaining_research_time >= retry_attempt_floor` 才允许 retry，floor 覆盖 expected attempt + backoff + finalization reserve；**具体阈值留待下一轮 characterization 决定，本批不拍脑袋固定**。
5. **Gate 观察不构成因果证据**：on2=partial 记为正向 in-situ observation。
6. **边界冻结**：`fetch_failed → bounded retry candidate`；`short_doc → NOT retry`（§46 的 JS/client-rendered 形态由 headless 路线单独决定，两者正交）。
7. **默认 OFF**；answer/evidence/DeepSeek-only 边界均未变。

**本地实现状态**（以本地工作树为准）：§47 `7853cfb`→`4bafce5`→`94faa69`；§48 `8ecbff0`→`79ff540`→`03725ac`。远端 `2002yy/study-agent` 尚未包含这些 SHA（本地提交，未推送）；以本地 `git log` 为准。

## 60. §49 Window-aware Retry Admission + 三臂 E2E（`cd1e7dd`/`a4bd969`；机制已实现并测试，样本仍未足）

### 60.1 实现

- `read_retry.read_retry_mode()`：`off`（默认）| `unbounded`（§48 臂，`on/1/yes` 复现）| `window_aware`；`retry_window_floor_seconds()` 可配（`RESEARCH_READ_RETRY_FLOOR_SECONDS`，**临时默认 18s** = attempt 估计 + backoff + finalization reserve；按用户要求不在本批冻结阈值）。
- `read_with_bounded_retry(..., admission)`：每次 retry 前过 admission；被拒时记 `skipped_by_admission`。
- **retry 改接在 runtime 的 `gateway_read`**（窗口在那里可见）；adapter 恢复为纯转发，避免双重重试。
- 11 条 focused 测试：mode/floor 边界/admission 拒绝与 retry 序号语义/策略与上限/退避。

### 60.2 三臂 E2E（Docker case，各 2 次；恒定 selector=model + routing=on；proposal=off）

```text
run          reads  ok failed gate   elapsed  win_remaining retries skipped
off1             1   1    0    block   30.5     34.5           0       0
off2             4   2    2    block   46.5     18.3           0       0
unbounded1       1   1    0    block   31.3     36.2           0       0
unbounded2       4   3    1    block   55.4     11.0           0       0
aware1           3   2    1    block   60.3      2.4           1       0
aware2           4   3    1    block   53.8     11.6           0       0
```

**读成功**：OFF 3/5 · unbounded 4/5 · aware 5/7（N=2/臂，方向性观察，不是分布结论）。

### 60.3 本批的诚实结论

1. **机制成立且可复现**：aware1 真实触发 1 次 retry（admission 放行，`skipped=0`）；§48 的 unbounded 臂在本批恰好未撞上 fetch 失败（0 retries）——说明**retry 触发本身高度依赖 run 运气**。
2. **window-aware 的 headroom 收益在本样本无法证明**：admission 的"拒绝"路径只在**剩余研究时间 < floor** 时才会出现，而 N=2 尚未观察到该时刻的失败；该路径目前由单元测试覆盖（`skipped_by_admission` 语义），不是 in-situ 证据。
3. 窗口余量分布（`remaining_after_research_seconds`）：18.3 / 34.5 / 36.2 / 11.0 / **2.4** / 11.6——重 run 的余量本就紧张；aware1 在 60.3s 处结束（贴近 60s hard cap），说明**即使有 admission，重 run 仍会逼近预算上限**；floor=18s 是否足够留出 finalization headroom，本批未定论。
4. gate 全为 block（本批无 partial），与 §48 的 on2=partial 对照说明 gate 结果受运行方差主导，不能用于本批臂间归因。
5. 默认仍 OFF；生产行为未变；d40.2 下游不变量未触碰。

### 60.4 下一刀（建议，未实施）

- **确定性注入**：要验证 floor 穿越，需要可**注入 fetch 失败**的机制（例如测试用 gateway 或在 `gateway_read` 注入失败计划），否则靠自然 flakiness 需要大量 run 才有信号；
- 或把样本扩大到 Node + 多次 Docker，并同时记录 `post_research_projection` / `answer_stage` 秒数以量化 finalization headroom；
- **headless browser（§46 short_doc）与 retry 严格正交，继续独立冻结**。

## 61. 已证明结论汇总（可引用；每行含证据位置与适用边界）

> 本表是**结论索引**，不是新实验；所有数字都可回溯到对应章节与 `docs/research_quality/` 下的诊断产物（未跟踪）。默认状态与边界一栏必须随结论一起引用。

| 领域 | 结论 | 证据位置 | 默认/边界 |
|---|---|---|---|
| **端到端** | 首次完整 runtime E2E 正例闭环：`target_read → routing supports → eligible → gate pass → grounded generation → binding valid → consistency clean → substantive publish` | §44（run7）+ §46（`ANSWER_FORMATION.d40.2.json` 黄金 artifact） | 诊断开关组合；生产默认未启用 |
| **Answer formation** | 空返回=**A_model_empty**（thinking 吃 1600-token 输出预算；非 timeout、非 parse）；thinking-off 使 generation 与 binding 各 5/5 非空、p50≈1/5 延迟；一致性门（unknown ids / 未绑定实质段 / 方向 / 证据状态矛盾）可机械拦截并保留真实 binding snapshot | §45.4/§46 | `RESEARCH_ANSWER_BOUNDED_POLICY`、`RESEARCH_ANSWER_CONSISTENCY_GATE`、`RESEARCH_ANSWER_GROUNDED_INPUT` 均默认 off |
| **Atomic routing** | 读到的页面可 bounded 路由到缺 support 的 factual claim（≤2/read、≤4/wave、不重读、不做 page×all-claims）；分析/比较类 claim **永不路由** | §44（`b1a208e`/`400ecdf`） | `RESEARCH_ATOMIC_ROUTING` 默认 off |
| **Read reserve** | reserve 的语义是"留给冲突解"；**无 open conflict 时在既有 hard read cap 内回流**；修复后该形态的 `read_budget_exhausted` 归零，历史目标页丢失模式消失 | §46.6（`505aca8`） | 有冲突时行为与修前完全一致 |
| **Selector** | ① `invalid_schema` 根因=**缺 thinking-off 传输配置**（修后 0/≈30 window）；② 生产合同=模型偏好+确定性 legacy fallback，**0/28 availability loss**；③ 条件性 lift：injected 12/12、natural 6/6，`wins>0 / losses=0 / replacement_loss=0`（natural 供给受 recall 限制）；④ 未证实普遍优于规则 | §47/§48/§49（`69b7eb4`/`de7fcf4`/`8769926`/`6989c75`） | `RESEARCH_SELECTION_AUTHORITY` 默认 off；只换 selection authority，不动 K/H9/下游 |
| **Recall** | 生产"三 provider"实际是 **Bing RSS 单栈（475/475 结果）**；四个已知深页在 raw top-20（含 exact title）**全部召不回** ⇒ 瓶颈在 **provider retrieval surface**，不在 query 表达或 merge/topK | §51/§52（`19747a1`/`aea23d8`） | query/intent compiler 因此继续搁置 |
| **Tier-2** | DeepSeek URL 提案 + reader 验证构成**第二 discovery 通道**并闭环（proposal→verify→candidate→assessment→read→extract→gate-eligible）；Docker 由"永不召回"变为"精确页进链（lead/primary）"；触发器为 claim-scoped 状态谓词（该 claim 已读≥1、无 support、无 answer_relevant、Tier-1 已消费） | §55（`8bb3310`/`8a1ade2`/`bc771af`/`3c69463`） | `RESEARCH_LLM_PROPOSAL` 默认 off；提案永不直接成为证据 |
| **Read adequacy** | 本地抽取器**无提升空间**（0 extraction_loss）；短页分两类：`fetch_failed`（连接重置）与 `short_doc`（HTML≈35 万字符而三种本地抽取器恒 520 字符，符合 client-rendered/script-embedded 形态，未做浏览器执行验证） | §56（`82caa33`/`df0763f`） | `short_doc_ratio=1/8`、`unreadable_or_failed=3/8`（两者不可混用） |
| **Fetch retry** | flakiness 真实且在当前环境呈 docs.docker.com 特异性（首发失败 50–67% vs 对照 0/6）；有界 retry 恢复 50→100% / 67→83% / 50→67%；成本为观察差值 +16.3s/+44.7s，一次 **72.9s** 同时超过 48s research window 与 60s hard budget | §57/§58/§59（`7853cfb`/`8ecbff0`） | **冻结约束：retry 必须 window-aware**；默认 off；`fetch_failed` 才 retry，`short_doc` 不 retry |
| **架构原则** | **Discovery 可换、证据链不换**；`proposal ≠ candidate ≠ evidence ≠ support`；全部在 **DeepSeek-only** 边界内完成（未引入 Brave / r.jina.ai 等外部服务） | §54/§55 + 各批合同段 | 生产默认行为始终未启用任何诊断开关 |

**引用规则**：引用表中任一结论时必须同时引用其"默认/边界"列；所有带 N 的数字都是 **observed characterization**（样本量在各章节标注），不是分布估计或 SLA。

## 62. 当前方案：从"定位"转入"能力建设"（记录于 2026-09-21）

### 62.1 为什么之前没做这些（批次纪律，非遗漏）

§35→§49 全部是 **RQCE 诊断批次**，固定节奏为：`audit → localize → probe → contract → implement(default off) → characterize`。
在这个阶段，**能力建设被有意推迟**，因为先必须回答"到底是哪一层坏、坏到什么程度"。定位结果（见 §61）：

```text
Recall   : provider retrieval surface（Bing RSS 单栈，深页 raw top-20 全 miss）
Read     : fetch flaky（10054/timeout）+ JS/client-rendered 页面无正文 + retry 未窗口感知
Analysis : 比较/演进类 claim 没有综合层（单页抽取永远给 background/qualifies）
```

因此"ChatGPT 式连续搜索+分析"缺的不是模型能力，而是**三件基础设施 + 生产化**。从现在起进入建设阶段。

### 62.2 方案（按杠杆排序；每批独立可回滚、默认 off、单独验收）

**B1 — Tier-1.5 域内定向检索**（最高杠杆；DeepSeek-only、无新依赖）
- 机制：planner 已有/可产出 `desired_domain` → 用**现有 reader** 读取该官方域的**站内搜索页**（如 `docs.docker.com/search/?q=…`、`postgresql.org/search/`）→ 从正文抽取候选链接 → 候选标记 `discovery_method="domain_targeted"` → 走既有 assessment/read/extract/Gate。
- 触发器：与 Tier-2 同级的状态谓词（Tier-1 已消费、该 claim 无 support），**有界**（≤1 次/claim、≤N 候选）。
- 验收：四个已知深页中至少 2 个可经此路径进入 evidence 链并成为 `gate-eligible`；d40.2 四项不变量不回归。

**B2 — Retry 窗口感知的 in-situ 证据**（§50 确定性失败注入）
- 用可注入失败计划的 reader/gateway，构造"剩余研究时间跨过 floor"的确定性场景，证明：**floor 之上 retry、floor 之下 skip 并保留 finalization headroom**。
- 顺带校准 `retry_attempt_floor`（当前临时 18s）。

**B3 — Headless browser 决定与最小接入**（runtime 依赖决定）
- 目标：让 JS/client-rendered 页面可读（Docker pulls 520 → 正文可提取），并顺带增强站内搜索的可执行性。
- 必答：许可/体积/启动成本/超时与预算耦合；验收：指定 JS 页面正文达标且不破坏窗口预算。

**B4 — 综合层（comparison synthesis）**
- 比较/演进类 claim **不再要求单页 supports**：由 binding/synthesis 组合两条原子事实（§38c 已给设计依据）。
- 验收：Node/Docker 的比较类问题从"永不 supports"到可形成组合结论；Gate/answer 语义不变。

**B5 — 生产化（逐开关、逐批）**
- 顺序建议：selector → atomic routing → Tier-2 → grounded answer + consistency gate；每项单独批次、单独证据、单独回滚点。
- 预算语义随附：selector = orchestration 记账；retry = window-aware；所有开关默认 off 直到各自批次验收。

**B6 — Provider health metrics**（小、可并行）
- `configured / attempted / succeeded / contributed / result_count_by_provider` + "attempted>0 且 contributed=0" 告警；用于区分"配置了 provider"与"真的贡献了结果"。

### 62.3 冻结边界（跨所有新批次，不得静默更改）

- **DeepSeek-only**：不引入 Brave / r.jina.ai 等外部服务。
- 不给 Bing RSS 做 provider-specific 补丁；不调 selector prompt 追命中率；不把 retry 当作 `short_doc` 修复；不改 K / H9 / extractor / Gate / answer 语义（除非该批次明确立项并给出证据）。
- **d40.2 黄金 artifact 四项不变量**（gate=pass / binding=valid / consistency=clean / publish=substantive）是所有改动的回归底线。
- 全量 pytest 每个候选 head 一次；诊断产物（`docs/research_quality/*.json`）不提交。
- 每个结论引用必须带"默认/边界"（§61 引用规则）。

**§38b 下一步（唯一执行切片）**：在**诊断变体**中把评估窗口替换为模型 selector（≤2 picks/次，其余全部冻结：query construction、H9、budget、reader、extractor、Gate），在同一 case 上实测 read → extract → supports 是否从 0 变 >0；不改生产默认路径。


## §63 B1 Tier-1.5 域内定向检索（实现完成，能力前提被观测否定）

### 63.1 实现（`e557381` + `2ad66a2`，默认 off）

- `src/web/research/domain_targeted.py`：域提案严格解析（`parse_domain_proposal`）、claim 显著词（`claim_search_terms`/`build_search_query`）、确定性站内搜索 URL 模式（`site_search_urls`，3 形态）、`_AnchorExtractor` 同域锚点抽取与词重叠打分（`extract_candidate_links`，≤5/次）、`domain_targeted_enabled()`。
- runtime `_domain_targeted_step`：与 Tier-2 同一状态谓词（该 claim 有完成 read、无 supports、当前评估无 answer_relevant）、每 claim 每 run ≤1 次；候选标 `discovery_method="domain_targeted"`；**预算护栏**：站内搜索页 fetch ≤3 次/claim、仅当 `research_seconds_left() >= 12s` 才发起（否则记 `skipped_by_window`）。
- 漏斗泛化：`metrics.discovery_funnel` 同时覆盖 `llm_proposed` 与 `domain_targeted`（含 `by_discovery_method`）；`metrics.tier2_funnel` 被取代。
- 10 个 focused 测试（解析/搜索词/URL 模式/锚点过滤与排序/上限、已验证候选、有 support 时不触发、每 claim 一次、fetch cap、窗口护栏）；Ruff clean。

### 63.2 验收（Docker case，`RESEARCH_DOMAIN_TARGETED=on` + selector=model + routing=on，Tier-2 off）

- **run1（修复前，`e557381`）**：域提案正确（`docs.docker.com` + `hub.docker.com`），5 个站内搜索 URL 依次 12s 超时 → **elapsed 99.985s，穿透 60s 硬预算**（fetch 层不是 read 层，无 deadline 检查）。此预算漏洞即 63.1 护栏的由来。
- **run2（`2ad66a2`）**：elapsed **29.2s**（预算修复），gate=block；站内搜索页 3 次 fetch 后 `search_fetch_cap` 截断；`links_found=[]`、`verified=[]`、`added_candidate_ids=[]` → 该通道**零候选**。

### 63.3 搜索面特征化（一次性探针，非生产工具）

同一 fetch 层 + 原始 urllib 探针，对 `docs.docker.com`：

| 通道 | 结果 |
| --- | --- |
| `/search/?q=`、`/search?q=`、`/?s=` | 全部 `URLError`（连接失败；`/docker-hub/` 同 run 正常返回 350KB ⇒ 非宿主整体不可达） |
| `/docker-hub/`、`/docker-hub/usage/` | 返回**逐字节相同**的 349,998 字符 nav shell（531–532 同域链接），目标深页 `docker-hub/usage/pulls` **不在其中** |
| `sitemap.xml` / `sitemap_index.xml` / `robots.txt` | URLError / HTTPError(404) / 200 但无 sitemap 指令 ⇒ **无 sitemap 可用** |

### 63.4 搜索面跨站点特征化（8 站点，同一 fetch 层）

对 docker / postgresql / python / kubernetes / redis / npm / node / rust 八个文档站：

| 形态 | 结果 |
| --- | --- |
| `/search/?q=`、`/search?q=` | **7/8 站 404**（含 docs.docker.com 的 URLError） |
| `/?s=`、`/?search=` | 8/8 返回 200，但**锚点数与根页逐一致**（22/22、45/45、72/72、644/644、104/104、202/202、241/241、8/8）⇒ 查询被忽略，返回的就是根页 |
| `/sitemap.xml` | docs.docker.com **200 urlset 1811 条**、redis.io **200 sitemapindex 26 子图**、其余 404 |

⇒ **站内搜索 URL 猜测是共性失败面**（不是 docs.docker.com 个性）；**sitemap 是共性可行面**（在有的站点上）。此前的"docker 无 sitemap"是把一次 flaky `URLError` 误读为缺失，已纠正。

### 63.5 通道改为 sitemap 采集（三次验收 run）

实现：域提案 → `/sitemap.xml`、`/sitemap_index.xml`（index 时按 page/route/doc 优先取 ≤2 子图）→ 解析 `<loc>` → 按 claim 词干匹配排序 → reader 验证 → 候选；仍受窗口护栏与 3 次 fetch 上限。`article_fetcher` 新增 `_fetch_text_payload`（同一安全 opener，仅把内容类型闸门从 html/text 放宽到 html/text/xml/json，既有调用者行为不变）。

| run | head | 关键观测 |
| --- | --- | --- |
| run3 | `2ee312f` | sitemap 成功（**1811 loc**）→ 3 候选验证入库；但深页目标排第 4 被 candidate_cap 截掉 |
| run4 | `bb7498a` | 排序修复后深页目标**排第 1**；但 3 次验证读取连续 `WinError 10054`（`read_failed`）⇒ 无候选入库 |
| run5 | `bb7498a` | **sitemap 自身** 3 次 `inventory_fetch_failed`（URLError/HTTPError）⇒ links_found 空 |

排序修复（`bb7498a`）：term 上限 6 → 排序用 12（原上限把主实体 "Docker Hub" 截掉）；词干化去复数重复计数（limits/limit）；改用"不同词干命中数"而非 idf（idf 反被 preamble 空词 official/current 拉高，实测更差）。离线用真实 1811 条 sitemap 复算，短/长两种 claim 文本下目标均第 1。

### 63.6 结论

- B1 的发现环节**已成立**：模型只给域，本地 sitemap 采集能把深页排到第 1（run4 证据）。
- 剩余失败**不是 B1 的设计问题，而是既有读取面 flakiness**（§47：docs.docker.com 首发失败 50–67%；run4 验证读取、run5 sitemap 抓取各连挂 3 次）。B1 的验证读取走 `gateway_read`（可用 §49 window-aware retry），但**inventory 抓取走 `fetch_text`，目前无 retry**。
- 与 §45 Tier-2 的关系：Tier-2 在 Docker run4 曾把精确页送进链；B1 的增益是"不依赖模型给 URL"且能系统性枚举域内深页，但同样受读取面约束。

### 63.7 待用户裁决（B1 收尾）

1. **给 inventory 抓取接上同一 §49 window-aware retry**（推荐）：run5 三次失败即该系统可救的情形；风险是 §49 已证 retry 成本 +16~45s、曾一次 72.9s 超窗，而本 case 已用 50~56s，需先确认地板值。
2. **接受现状收口 B1**：保留默认 off，把读取面列为 B3 的前置（headless/更稳的抓取）。
3. **加一层 domain 级 fallback**：sitemap 抓取失败时退回 HTML hub 页锚点（实证 docker hub 页 531 链接但不含深页，收益有限）。

诊断产物：`docs/research_quality/B1.docker.run1..5.json`（未跟踪）。


## §64 B2 共享 window-aware retry admission（完成）与 B1 E2E 阶段化账目

### 64.1 裁决落地

- **B1 状态**：`MECHANISM PASS / E2E QUALIFICATION PENDING READ RELIABILITY`。不再改 discovery（ranking / planner / sitemap heuristic 冻结）。
- **§62 排序修订**：B1（机制 PASS）→ **B2 共享 window-aware fetch retry**（inventory + page read）→ B1 E2E qualification → B3 headless（只解 JS/short_doc）→ B4 综合层 → B5 生产化 → B6 health metrics（B2 可顺带补字段，但不施工 dashboard）。

### 64.2 B2 实现（`e60be823`，默认 off）

- **规则是公式，不是魔法数**：`retry_allowed = remaining_research_time >= attempt_budget + next_backoff + finalization_reserve`；`retry_window_requirement(n)` 由分量参数算出，18s 只是首例（12+1+5），retry #2 为 19s（backoff 2s）。`RESEARCH_READ_RETRY_FLOOR_SECONDS` 仅作实验覆盖，不再是语义来源。
- **逐次重审**：`make_window_admission` 在**每次** retry 前重新计算并返回 `RetryAdmission(allowed, reason, remaining, required)`——retry #1 获准不自动授予 retry #2（这正是 72.9s 超窗的结构性修因）。
- **语义/指标分离**：`read_with_bounded_retry(..., diagnostics_key=...)`；页面读取记 `read_retry`、sitemap 采集记 `inventory_fetch`，runtime 各自聚合进 `metrics.read_retry` / `metrics.inventory_fetch`（`attempts / retries / skipped_due_to_budget / retry_reasons / admission_reasons / fetches`），reader retry 统计不会被 sitemap 请求污染。
- **inventory 纳入同一策略**：`_inventory_fetch_with_retry`（适配抛异常的 4 元组 fetch 层），共享 admission、独立指标、不改 reader 语义。
- **阶段化账目**：`domain_targeted` 记录新增 `stages`（domain_proposed / inventory_fetched / links_ranked / verification_attempted / verification_succeeded / candidate_admitted）；下游阶梯（assessed → read → extracted → gate）由 `discovery_funnel` 逐候选 join（`by_discovery_method`）。**计数器 only，无启发式改动。**
- **漏斗在硬预算退出路径也记录**（`ff60387a`）：run6 以 `evidence_budget_exhausted` 收尾、未走到逐波 gating，导致 `discovery_funnel` 缺失——恰是失败时最需要账目的情形。
- 测试：`tests/test_fetch_retry_admission.py` 11 项（四确定性点：远高于 / 刚高于 / 刚低于 / 第二次 retry 重审；floor 覆盖；inventory 键隔离；runtime 接线 + 指标分离）；`test_read_retry.py` 断言随新增字段更新。Ruff clean，focused 99 passed。

### 64.3 E2E 运行（Docker case，`RESEARCH_DOMAIN_TARGETED=on` + selector=model + routing=on + retry=window_aware）

| run | head | 契约 | 关键观测 |
| --- | --- | --- | --- |
| run6 | `e60be823` | **违反**：7 calls（研究 6+答案 1 > 6 上限触发 research 拒呼）、elapsed 65.8s > 60s | inventory 1811、目标 rank #1、verified 3、admitted 3；但 `discovery_funnel` 缺失（硬预算路径未记录）；retry 全被 `insufficient_window` 拒绝 |
| run7 | `ff60387a` | **clean（violations []）**，elapsed 59.3s | `discovery_funnel`: proposed 3（全部 `domain_targeted`）、read 0、gate_eligible 0；`read_retry`: fetches 3 / attempts 5 / **retries 2（两次均获准后仍 10054 失败）** / skipped_due_to_budget 2；`inventory_fetch`: 1 fetch、retry 被窗口拒绝 |

### 64.4 失败归因（run7 阶段化结论）

```text
domain proposed        PASS (docs.docker.com, hub.docker.com)
inventory fetched      PASS (urlset, 1811 loc)
target present         PASS (rank #1)
verification           PASS (3 verified → 3 candidate admitted)
assessment / read      FAIL  (深页 read 连续 10054；retry 已按策略发出 2 次仍失败)
extraction / gate      未到达 (read 0 → support 0 → eligible 0)
```

- 契约层：B1 多消耗 1 次研究模型调用（域提案），run6 因此触发研究调用上限拒呼；run7 在无 selector 完成调用时 fit 进 6 次上限。
- 结论：**B1 的发现链已全部 PASS，唯一阻塞是读取面 transient failure**；B2 策略按设计工作（重审、跳过、分离记账），但无法凭空修复宿主级 10054。

### 64.5 下一步（唯一执行切片）

四页 B1 E2E：对 §62 的四个已知深页各跑一次（同配置、window_aware retry），按 §64.4 的阶梯逐页统计，硬指标 **≥2/4 gate-eligible**；同时记录每页卡在哪一级，以及 read retry 的获准/跳过分布。若 10054 持续主导，则按 §62 进入 B3（headless）前先报告该证据。

诊断产物：`docs/research_quality/B1.docker.run6.json`、`run7.json`（未跟踪）。


### 64.6 建设阶段首个候选 head 门禁（`5ecca001`，2026-09-20）

| 门 | 结果 |
| --- | --- |
| focused（domain_targeted / fetch_retry_admission / read_retry / llm_proposal / active_research_runtime） | **99 passed** |
| 全量 pytest | **2087 passed / 3 failed**（678.4s） |
| Ruff（src/tests/tools） | All checks passed |
| `git diff --check` | 干净 |
| 工作区（tracked） | clean |
| d40.2 四项不变量（frozen replay，`--runs 3`） | **gate=pass ✓ · binding=valid（3/3 ok）✓ · consistency=clean（captured report ok, codes []）✓ · publish=substantive（substantive_answer_rate 1.0 / 1.0）✓** |

3 项失败归因：

- `test_rq1c_impl_entrypoints::…exact_head_guard`、`test_rq1c_protocol_probes::…deterministic_protocol_runner…`：**已知 Windows-local 平台失败**（父提交同样复现，非本批回归）。
- `test_discovery_annotation::test_classification_tasks_are_blind_and_deterministic`：**负载型闪失败**——单独运行连续两次 6/6 通过；本批未触碰 annotation 路径（改动文件：`active_research_runtime.py` / `read_retry.py` / `domain_targeted.py` / `article_fetcher.py` 新增函数 / 测试）。

diff 范围审计：本批共 6 个提交，语义边界为「§63 sitemap 发现 + §50/B2 admission + 账目/文档」；未触碰 selector prompt、K=2、H9、extractor、Gate、answer 语义，全部新行为在默认 off 开关后（`RESEARCH_DOMAIN_TARGETED`、`RESEARCH_READ_RETRY`）。

诊断产物（未跟踪）：`docs/research_quality/B1.docker.run1..7.json`、`ANSWER_FORMATION.replay` 输出（temp）。


### 64.7 B1 E2E：四个已知深页逐页归因（head `9cf823d`，同 run7 配置）

配置：`RESEARCH_DOMAIN_TARGETED=on` + selector=model + routing=on + `RESEARCH_READ_RETRY=window_aware`。

| case | 目标深页 | 域提案 | inventory | 目标进链 | 目标 gate-eligible | 卡点 |
| --- | --- | --- | --- | --- | --- | --- |
| container-registry | docs.docker.com/docker-hub/usage/pulls/ | ✅ 正确 | ✅ urlset 1811 | ✅ **rank #1** | ❌ | 目标 read 两次获准 retry 后仍 10054 |
| historical-current-node-modules | nodejs.cn/api/modules.html | ⚠️ nodejs.org + developer.mozilla.org（**未含 nodejs.cn**） | ✅ index 10 | ❌ | ⚠️ 该页 eligible，但**来自既有链**（Tier-1/lead），非 B1 | 域提案未覆盖目标宿主 |
| current-support-postgresql | postgresql.org/support/versioning/ | ❌ endoflife.date + ubuntu.com | ⚠️ index 55，links_ranked 0 | ❌ | ❌ | **域提案错误**（模型选了第三方追踪站） |
| simple-license-uv | github.com/astral-sh/uv/blob/main/LICENSE-MIT | —（通道未触发） | — | ❌ | ❌ | **触发前置未满足**：该 case `reads=0`，claim-scoped 谓词要求"该 claim 有完成 read" |

**硬指标：0/4 由 Tier-1.5 成为 gate-eligible。**

### 64.8 归因（三个独立阻塞，非单一 flakiness）

1. **读取面 transient failure**（Docker）：B1 已把目标排到 #1、验证读取两次获准 retry，仍连续 10054 ⇒ §47 宿主级 flakiness，B2 策略按设计工作但无法凭空修复。
2. **域提案精度**（PostgreSQL）：模型给出 `endoflife.date` / `ubuntu.com` 而非 `postgresql.org`。发现机制无责，问题在 proposal 内容质量；且该 case 的 `links_ranked=0`（词干不匹配）说明排序对"域内无相关路径"的情形是诚实返回空。
3. **触发前置**（uv）：B1 与 Tier-2 共用 claim-scoped 谓词（要求该 claim 至少 1 次完成 read）。当 Tier-1 完全无可读候选时，B1 **永远不会触发**——而 B1 的立项动机恰恰是"Tier-1 召回不到深页"。这是设计层面的限制，需在 §62 决策（放宽谓词 / 独立触发条件）中显式处理。

附带：postgres 与 node 两个 case 出现 `model_call_budget_exceeded`——B1 多消耗 1 次研究模型调用，在这些 case 的其他编排调用已接近上限时越界。这与 §62 的"预算语义随开关逐项立项"一致，属于生产化（B5）必须解决项。

### 64.9 结论与下一步

- B1 机制结论不变（`MECHANISM PASS`）；E2E 结论为 **0/4**，且阻塞分布在读取面、proposal 质量、触发谓词三处。
- 按 §64.5 的约定，进入 B3（headless）前先报告本证据（已完成）。B3 只能解第 1 类阻塞中的 JS/short_doc 部分，不能解 10054、proposal 精度与触发谓词。
- 建议下一步（待裁决）：优先修 **触发谓词**（让"Tier-1 零可读"时也能触发 Tier-1.5），再评估 proposal 精度；headless（B3）留到读取面证据齐备后。

诊断产物（未跟踪）：`docs/research_quality/B1E.postgres.json`、`B1E.node.json`、`B1E.uv.json`、`B1.docker.run7.json`。


## §65 B1-T1 触发合同修复（`50bb71a4`）与 uv 复验

### 65.1 修复内容（只做这一件事）

旧谓词只在"该 claim 已有完成 read"后才可能触发，于是"Tier-1 有候选但永远读不成"的 claim（uv 形态）永远进不了 Tier-1.5——而 Tier-1.5 的职责恰恰是覆盖"Tier-1 没给出可读结果"。新谓词两个合法入口：

```text
trigger iff enabled
           AND not already tried for this claim
           AND not claim_has_support
           AND ( tier1_miss_reason(...)      # 旧入口：有完成 read 且无 support
                 OR no_viable_read_path )    # 新入口
```

`no_viable_read_path`（最窄、纯计数、可审计）：`wave_index >= 2` 且该 claim 有计划 query（Tier-1 已走完一整波）**且该 claim 完成 read 数 == 0**。不会在第一波抢跑，也不看 run-level reads。记录里 `tier1_miss_reason` 会写成 `no_viable_read_path`，机器可查。

同时按用途拆分 orchestration 记账：`metrics.orchestration_model_calls_by_purpose`（`research_url_proposal` / `research_domain_proposal` / `research_selection_authority`）。理由：资格契约限制的是**全部**模型调用，B1 多消耗一次调用可能把后续饿死而不代表 discovery 失败，失败报告必须能区分二者。

测试：4 条确定性触发用例（有 read 无 support 仍触发；Tier-1 走完波次且 0 read **现在触发**；第一波有候选不抢跑；别的 claim 有 read 不影响本 claim）+ 既有每 claim 一次约束。

### 65.2 uv 复验（`B1T1.uv.json`，契约 clean，elapsed 46.5s）

| 阶段 | 修复前 | 修复后 |
| --- | --- | --- |
| trigger | **未触发** | ✅ 触发（`tier1_miss_reason=no_viable_read_path`, wave 2） |
| domain proposed | — | ✅ `github.com`, `docs.astral.sh` |
| inventory fetched | — | ⚠️ 2 次：`github.com/sitemap.xml` → **HTTP 406**；`sitemap_index.xml` → 超时 |
| 第二域 | — | ❌ `docs.astral.sh/sitemap.xml` 与 `sitemap_index.xml` 均 **`skipped_by_window`**（窗口护栏拒绝） |
| candidate | — | ❌ links_ranked 0 |

`orchestration_model_calls_by_purpose` 实测：`{research_domain_proposal: 1, research_selection_authority: 3}`；`violations: []`。

**结论**：触发合同修复成立（uv 从"永不触发"变为"触发并走完 proposal → inventory"）。uv 剩余阻塞已换类为两条，均非 trigger：

1. **宿主无可用 sitemap**：github.com 对本站点返回 406 / 超时（且 GitHub 本就不提供 sitemap）；
2. **窗口护栏饿死第二域**：第一域两次失败（含一次 12s 超时）后，`docs.astral.sh`（**确有其 sitemap，84 locs**）被 `skipped_by_window` 跳过——顺序与配额问题，不是能力缺失。

### 65.3 下一步

按裁决顺序进入 **B1-T2：域提案 official 契约**（模型返回 `domain` + `domain_role = official | project-host | third-party`，运行时只接受前两类；把"官方性"变成机器可查字段，不做长 prompt 工程）。T2 之后再跑四页 E2E，并按剩余失败分类（fetch_failed → B2 策略；short_doc/JS → B3）。§65.2 的两条 uv 阻塞记入 T2 之后的待办（宿主覆盖 / 域间配额公平性），不在 T2 范围内。

诊断产物（未跟踪）：`docs/research_quality/B1T1.uv.json`。


## §66 B1-T2 canonical target 契约（`2f3d6aaa` + `bf7b950d`）

### 66.1 冻结合同（按裁决实现）

```text
{"targets": [{"host": "postgresql.org",
              "scope": "https://www.postgresql.org/",
              "domain_role": "official"}]}
```

- `host + scope` 取代裸域；`project-host` 的 scope 必须指向项目（`https://github.com/` → `project_host_scope_too_broad` 拒绝）。
- 角色是**模型声明**，内部记 `proposed_domain_role`，不得读作 server-verified official status；本批**不做 verifier**。
- runtime 接受 `official` / `project-host`，拒绝 `third-party`（tracker/镜像/博客/社区站，信息正确也算）。
- accepted 上限 2；解析审计列表单独限 4，避免第三方声明把合法 official 挤出契约检查。
- **每条可解析声明都保留**并带 `reject_reason`（`third_party` / `unsupported_role` / `invalid_scope` / `project_host_scope_too_broad`），记录里同时写 `targets` 与 `rejected_targets`——这样能区分"模型没提"与"契约拒绝"。

### 66.2 确定性验收（三条冻结用例 + 补充）

| 输入 | 期望 | 结果 |
| --- | --- | --- |
| `docs.astral.sh` / official | accept | ✅ |
| `https://github.com/astral-sh/uv/` / project-host | accept | ✅ |
| `https://github.com/` / project-host | reject（scope 过宽） | ✅ `project_host_scope_too_broad` |
| endoflife.date / ubuntu.com / third-party | reject，且不挤掉同批 official | ✅ |
| unknown role / 非 https / host 不匹配的 scope | reject + 原因 | ✅ `unsupported_role` / `invalid_scope` |

focused：`test_domain_targeted` 23 passed；runtime/llm_proposal/fetch_retry 72 passed；Ruff clean。

### 66.3 PostgreSQL 实跑（`B1T2.postgres.json` + `B1T2.postgres.run2.json`）

两次实跑一致：模型只声明 **1 个 target** —— `endoflife.date`，且**自报 `third-party`**，被 runtime 正确拒绝（`reject_reason=third_party`）；`postgresql.org` **根本没被提出**。因此 `domains=[]`、无 inventory、无候选。

归因（新审计能力直接证明，不是推测）：

1. **契约机制 PASS**：角色枚举、scope 规则、审计字段、拒绝路径全部按设计工作；
2. **主验收未达成**，但阻塞**不是契约**，而是 **proposal recall**：模型没有提出官方宿主。对照 §64.7（T2 之前）该 case 曾提出 `endoflife.date + ubuntu.com` 并都自报 official——角色字段引入后输出变成 1 条，属模型行为变化，需在 T2 之外处理（prompt 属后续微批，按裁决"不在 T2 堆 prompt 规则"）。

附带观测：本 case `research_selection_authority` 消耗 **10 次**调用（B1 仅 1 次），`model_call_budget_exceeded` 的主因是 selector 而非 B1——这正是 §65.1 拆分按用途记账要暴露的东西。

### 66.4 结论与下一步

- B1-T2 = **CONTRACT PASS**（确定性 + 实跑拒绝路径）；PostgreSQL 主验收受 **proposal recall** 阻塞，单列为后续项。
- 按裁决顺序，下一步是**四页 B1 E2E 重跑**（T1+T2 生效后的净效果），并按剩余失败分类：`fetch_failed` → B2 策略；`short_doc/JS` → B3；`no accepted target proposed` → proposal recall 微批；宿主无 sitemap / 域间配额 → host coverage。

诊断产物（未跟踪）：`docs/research_quality/B1T2.postgres.json`、`B1T2.postgres.run2.json`。


## §67 四页 E2E characterization（T1+T2 后，head `b0f79b0`）

配置同上（B1 on + selector=model + routing=on + retry=window_aware）；每 case 一条统一漏斗，失败按 A–H 归档。诊断产物：`B1E2.*.json` + `B1E2.summary.json`（未跟踪）。

### 67.1 漏斗（统一 14 级）

| 级 | docker | node | postgres | uv |
| --- | --- | --- | --- | --- |
| triggered | ✅ | ✅ | ✅ | ✅ |
| targets_proposed / accepted | 1 / 1 | 1 / 1 | 1 / **0** | 1 / 1 |
| inventory_attempted / succeeded | 1 / ✅ 1811 | 1 / ✅ | 0 / ❌ | 2 / ❌ |
| target_present / rank | ✅ **#1** | ❌ | n/a | ❌ |
| verification_attempted / succeeded | 5 / 3（**含目标**） | 3 / 3（不含目标） | 0 / 0 | 0 / 0 |
| candidate_admitted | 3（含目标） | 3 | 0 | 0 |
| assessment_relevant / read_succeeded | 0 / **0** | 0 / **0** | 0 / 0 | 0 / 0 |
| extraction_support / gate_eligible | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 目标最终 eligible | ❌ | ⚠️ 是（**来自既有链**，非 B1） | ❌ | ❌ |

### 67.2 失败分桶（首要阻塞）

| case | 首要桶 | 证据 |
| --- | --- | --- |
| docker | **H downstream** | 目标 verified（verified[0]）且已 admitted，但 3 个 B1 候选 `read: false`——**admitted 后从未被读** |
| node | **A′ proposal host mismatch** | 模型给 `nodejs.org`（scope 指向 `/api/modules.html`），目标是 **nodejs.cn** 的镜像页 → 该宿主不在 inventory；nodejs.cn 页由既有链读到并 eligible |
| postgres | **A proposal_recall** | 唯一 target 为 `endoflife.date` 且自报 `third-party` → 正确拒绝，无 accepted target |
| uv | **B host_coverage** | `github.com` project-host 被接受，但 `/sitemap.xml` **406**、`/sitemap_index.xml` **404** → 无可用 inventory |

其余桶本轮为 0：C domain_fairness 0（uv 本轮只提 1 个域）、D fetch_failed 0 作为首要（docker 的 10054 本轮落在其他 URL，目标自身验证成功）、E short_doc_js 0、F ranking 0（无"在 inventory 但超 cap"实例）。

### 67.3 频率排序与新发现的系统类

1. **G orchestration_budget：3/4**（`model_call_budget_exceeded`；selector 调用 docker 4 / node 4 / postgres 8；uv 3 且 clean）。按裁决口径 Node+Postgres 均超 ⇒ **升级为当前 E2E blocker**。
2. **A+A′ proposal 质量：2/4**（postgres 无 accepted target；node 宿主错配）。若按字面"A 桶"仅 1/4；合并"proposal 质量"则达 2/4。
3. **H admitted-but-unread：2/4（新系统类）**：docker 与 node 各有 3 个 B1 候选被 admitted，**0 个被读**（`read: false`）。这是本轮新暴露、且比 fetch 更靠前的阻塞：候选进入池后没有进入读取计划/窗口。
4. B host_coverage：1/4（uv）。
5. fetch_failed / short_doc / fairness / ranking：0/4 首要。

### 67.4 结论

- T1+T2 的净效果可证：**触发 4/4**（此前 uv 永不触发）；**角色契约 4/4 生效**（postgres 的第三方声明被拒，不再污染 downstream）；docker 目标 **rank #1 且验证通过**——"基础设施能否到达深页"在 docker 上已答"能"。
- 失败质量已从混杂变为**少数可重复类别**：proposal 质量（2/4）、orchestration 预算（3/4）、admitted-but-unread（2/4）、宿主覆盖（1/4）。
- **"B1 失败"不是准确表述**：本轮 B1 机制端 4/4 触发、3/4 拿到 accepted target、docker 端到端走到 admitted；剩下的缺口分布在 proposal、预算、读取调度与宿主覆盖。

### 67.5 待裁决（按裁决阈值）

- A 桶字面 1/4 → 记为单点 variance；A+A′ 合并 2/4 → 触发 B1-T3（proposal 质量微批）。**取决于是否把 node 的宿主错配计入 proposal 质量。**
- G 3/4 → 按裁决升级为当前 blocker，建议提前 B5 子批（selector 预算），不顺手改。
- H 2/4 为新类，建议单列 B1-T5（admitted-but-unread 的读取调度归因），先 characterize 再 contract。


## §68 B1-T5 admitted-but-unread probe（离线，未改任何生产语义）

### 68.1 归因结果：6/6 唯一原因

对 `B1E2.docker.json` / `B1E2.node.json` 的 6 个 admitted 候选（id 由 URL sha256 反推）：

| 观测 | 结果 |
| --- | --- |
| 在 selector input 中 | **6/6 否** |
| selection_trace 有条目 | **6/6 无** |
| read outcome 存在 | **6/6 否** |

**机制（代码级证据，行号为当前 head）**：波内顺序是
`_select_assessment_window`（L1176，按 claim 固定本波窗口）→ 评估 → **`_domain_targeted_step`（L1324，此时才 admitted 新候选）** → `_fair_read_plan`（L1419，只消费由该窗口评估得到的 `claim_rankings`）。因此本波 admitted 的候选**不在该 claim 的 ranking 里**，读取计划看不到它们。

**唯一原因（按冻结链的第一处失败）**：`not_in_rank_window`
**恢复被阻断于**：`time_budget_exhausted` —— 两个 run 都止于 wave 2（`research_window.exhausted=true`，deadline 48s、实际 research ≈50s），不存在下一波重新选窗的机会。

⇒ 即裁决中怀疑的 **phase-order / scheduler re-entry** 路径，但精确位置是"**窗口先于 admission 固定**"，而非"读取计划先于 admission 构造"。根因类别 = scheduler/phase ordering（**不是** orchestration/model-call budget）。

### 68.2 Node 诊断问题的回答

问题：`nodejs.org` 是否存在语义等价、可支持同一 claim 的 canonical page？

- **存在且可读**：`https://nodejs.org/api/modules.html` 返回 200（161,237 字符，同时提到 CommonJS 与 ESM），是 `nodejs.cn/api/modules.html` 的 canonical 对应页。
- **但不在 sitemap 里**：nodejs.org `/sitemap.xml` 共 1036 条，**0 条** `/api/` 路径（该 sitemap 只覆盖 `/en/...` 页面）。

⇒ Node 的结论：既不是 proposal 失败，也不是目标不存在；是 **A′ benchmark 镜像未命中 + nodejs.org sitemap 覆盖不全**（host coverage 的又一实例）。因此 Node **不计入 proposal quality**（按裁决），且 host coverage 的实际频率由 1/4 上调为 **2/4**（uv github 无 sitemap；nodejs.org sitemap 缺 api 段）。

### 68.3 待裁决：窄修方案（三选一，均不新增模型调用优先）

| 方案 | 做法 | 代价/风险 |
| --- | --- | --- |
| R1 追加式扩窗 | 每 claim 循环结束后、`_fair_read_plan` 前，把"本波 admitted 且该 claim 窗口仍有空位"的候选**确定性追加**进该 claim 的 ranking（不重跑 selector） | 需保持窗口的 cluster-diversity 与 ≤2 上限语义；无新增模型调用 |
| R2 下一波重选窗 | 记录"admission 发生在选窗之后"的 claim，强制下一波重选该 claim 窗口 | 本轮两 run 都无下一波（时间耗尽），单独用不足以修复；且可能增加 selector 调用（预算已紧） |
| R3 提前 admission | 把 B1/Tier-2 step 移到选窗之前 | **与状态谓词冲突**（谓词依赖本波 assessment 的 answer_relevant/完成 read），不可行 |

倾向 **R1**（确定性、零新增模型调用、不触碰 selector）；R2 可作为 R1 的兜底（当波内有剩余时间时）。

### 68.4 下一步顺序（按裁决锁定）

```text
B1-T1 trigger              PASS
B1-T2 target role          PASS
四页 characterization       COMPLETE
B1-T5 admitted-but-unread  COMPLETE（6/6 = not_in_rank_window；恢复被 time_budget_exhausted 阻断）
        ↓
窄修 read scheduling（待裁决 R1/R2/R3）
        ↓
B5-S1 selector/orchestration budget attribution（G 3/4，已升级为当前 blocker）
        ↓
PostgreSQL proposal recall 1/4 → 暂不 T3
uv/node host coverage 2/4 → 后续 host-coverage 微批
short_doc/JS 0/4 primary → B3 继续延期
```

B1 状态措辞（按裁决收紧）：**discovery capability demonstrated；E2E 失败已由 post-admission scheduling/orchestration 主导，而非"找不到深页 URL"**。


## §69 B1-T5 R1′ 实现（`152dfc0c`）与 Docker/Node targeted replay

### 69.1 冻结合同（按裁决）

```text
initial_assessment_window : <=2 / claim / wave  （source = 窗口冻结前的候选池）
late_assessment_tail      : <=2 / claim / wave  （source = 本波窗口冻结后才 admitted 的候选）
⇒ 一波最多新增 assessment = 2 + 2 = 4（已写进 contract）
```

六条硬约束实现情况：仅本波 late（记录 `wave_index` 必须相等）✓；claim-scoped ✓；**selector +0**（`selector_calls: 0` 记账）✓；不驱逐既有 ranking（合并后走同一 H9，`claim_rankings` 允许 >2）✓；多样性用既有 `_bounded_assessment_candidates` 规则 ✓；**assessment 不可绕过**（无 completed+validated assessment 不进 ranking）✓。预算不特权：`LATE_TAIL_MIN_SECONDS_LEFT=8.0` + 模型 attempt 账本，跳过原因记入 `late_assessment_tail` 记录。

10 条确定性测试（裁决的 7 条 + 预算门 + 跨波/跨 claim 隔离 + 已读 late 候选），focused 105 passed，Ruff clean。

### 69.2 Replay 结果（3 次运行，全部命中预算门）

| run | B1 结果 | tail | 跳过原因 | 备注 |
| --- | --- | --- | --- | --- |
| docker（`B1T5.docker.json`） | target accepted，但 **两条 sitemap 均 `skipped_by_window`** | 未触发（无 admitted） | — | B1 自身窗口护栏先拒绝 inventory |
| docker run2（`B1T5.docker.run2.json`） | inventory 1811、admitted 2（目标 read 10054 未 verified） | ✅ 触发：late 2 → selected 2、selector +0 | **`time_budget_exhausted`**（`seconds_left=-0.219`） | 目标本轮未 verified |
| node（`B1T5.node.json`） | admitted 3（nodejs.org 博客页） | ✅ 触发：late 3 → selected 2、selector +0 | **`time_budget_exhausted`**（`seconds_left=-1.031`） | — |

### 69.3 归因更新（按裁决"若仍没读，就重新归因"）

- **`not_in_rank_window` 已消除**：tail 在 2/3 运行中正确触发并完成"late → selected（≤2）→ 准备 assessment"，selector 调用保持 0。
- **新的绑定约束 = 时间预算**：B1 结构上是 **wave 2+ 通道**（旧入口需要上一波完成 read；新入口要求 wave ≥2，且不得在第一波抢跑），而 wave 2 的 per-claim 循环发生在 search+assessment 之后 ⇒ admission 落在 ~45–50s，**已在 48s research deadline 之后**（`research_window.exhausted=true`；hard 60s 尚有 8.5s reserve，但按裁决 tail 不得动用特权预算）。
- 因此 R1′ 把 phase-order 缺口修好之后，暴露出的下一层就是 **orchestration/time budget**（G 类）：selector 每 run 4–5 次、`model_call_budget_exceeded` 3/3。

### 69.4 结论与下一步

- **B1-T5 的机制修复成立**（tail 存在、有界、claim-scoped、selector +0、不绕过 assessment）；**H 的旧归因 `not_in_rank_window` 已不可复现**，取而代之的是真实预算拒绝——这正是裁决要求区分的情形。
- H 因此可记为：**phase-order 部分 CLOSED；剩余为预算门（time + model-call），转 B5-S1**。
- 下一步：**B5-S1 selector / orchestration budget attribution**（为什么 docker 5 次、postgres 8 次 selector；调用发生在哪一波/哪个池；是否有未变化池的重复调用；预算耗尽点在 read scheduling 之前还是之后），并同时量化"selector 成本 → B1 admission 时间点"的因果，因为它是当前 tail 无法执行的最直接上游。
- 附带记录（不修）：Tier-2 的 late admission 与本轮 B1 同相位，具有同一缺口；本批按裁决只覆盖 domain_targeted，Tier-2 记为 T5b 待办。

诊断产物（未跟踪）：`B1T5.docker.json`、`B1T5.docker.run2.json`、`B1T5.node.json`。


## §70 B5-S1 selector/orchestration budget attribution（纯诊断，`b191a48f` + `c1b75bf6`）

仪器（全部只写 metrics、不进 cursor、参数默认 None，行为零变化）：selector 记录新增 `input_fingerprint / previous_input_fingerprint / input_changed / input_ids / new_candidate_count / removed_candidate_count / excluded_fingerprint / assessment_state_changed / t_started_ms / t_ended_ms`；`domain_targeted` 记录新增 `t_started_ms / t_proposal_ms / t_admitted_ms`；新增 `metrics.b1_critical_path`（含 `admission_seconds / headroom_at_admission_seconds / headroom_at_gate_seconds / critical_path_ms`）；tail 记录补齐同名字段。

### 70.1 Q1 — selector 调用解剖：**没有找到冗余**

| case | selector 记录 | 实际发生模型调用 | 输入有实质变化 | identical-input 且有耗时 |
| --- | --- | --- | --- | --- |
| docker | 8 | **5**（其余 3 条 `window_limit=0`、latency 0） | 4/4（有耗时者）+1 条无耗时 duplicate | **0** |
| node | 4 | 4 | 4/4 | **0** |

调用由"每 claim 每波的窗口选择"驱动，池变化真实（wave 2 的移除来自 read 状态；docker wave 3 新增 1 个候选）。**"5 次/8 次 = 浪费"的假设被否定。**

### 70.2 Q3 — B1 critical path（事件级）

| case | B1 开始 | 域提案完成 | **admitted** | B1 段耗时 | admission 时刻 | headroom |
| --- | --- | --- | --- | --- | --- | --- |
| docker | 29.02s | 29.47s | **40.56s** | **11.09s** | 40.56s | **+7.438s** |
| node | 25.98s | 26.64s | **43.13s** | **16.48s** | 43.13s | **+4.875s** |

B1 段内部 = inventory（1811 loc）+ 3–5 次验证读取（含一次 10054 retry），是整条链的最大单段。

### 70.3 Q2 — 第一个不可满足的预算事件

**不是** 48s research deadline，**不是** model-call cap，而是 **late tail 自己的 8s 门**：

```text
docker: seconds_left = 7.438s  < LATE_TAIL_MIN_SECONDS_LEFT = 8.0  → refused（差 0.56s）
node:   seconds_left = 4.875s  < 8.0                               → refused（差 3.13s）
```

### 70.4 Q4 — 反事实：**不成立**

离线移除"重复 selector 工作"可回收 **0 ms**（无 identical-input 且有耗时的调用）⇒ **即使消除全部 selector 冗余，B1 也进不了 read**。可行动杠杆不在 selector。

### 70.5 结论与下一批（B5-S2 待裁决）

1. **selector 侧无可回收成本**（本批最重要的否定结论）；
2. 绑定约束是 **tail 的 8s 地板 vs 实际 headroom 7.4s / 4.9s**——而 8.0 是本批我引入的**未冻结参数**（不是用户冻结项），当时裁决明确要求 B5-S1 期间不得改动，现已完成，可进入校准决策；
3. 第二杠杆是 **B1 段自身 11–17s**（inventory + 3–5 次验证读取，其中 retry 属 B2 策略，验证次数属 B1 自身上限）；
4. 附带：node 本轮 `hard_timeout_exceeded`（74.7s）且 gate=pass，说明该 case 有另一条时间问题（5 reads + retry），与 B1 无关，记为观察。

候选方案（B5-S2 裁决项）：
- **F1 校准地板**：把 `LATE_TAIL_MIN_SECONDS_LEFT` 从 8.0 降到观测 assessment 延迟量级（约 3–5s）；Docker 可过、node 边界；
- **F2 缩短 B1 段**：限制验证读取次数/字节（不动 retry 策略）；
- **F3 不动**：接受 late 通道在 48s 窗口下经常来不及，等更大窗口决策。

诊断产物（未跟踪）：`B5S1.docker.json`、`B5S1.node.json`、`B5S1.summary.json`。


## §71 F1 地板校准（`37254a26` 实验旋钮 + 6 次 replay）与一个诊断生命周期缺陷

### 71.1 实验旋钮（F1）

`RESEARCH_LATE_TAIL_FLOOR_SECONDS`（默认 8.0，clamp 1–60）——**未冻结的实验参数**，每次决策记录 `floor_seconds`。其余全部保持冻结：no reserve privilege、selector +0、≤2/claim/wave、assessment mandatory、同 H9、同 attempt ledger。测试覆盖默认/clamp/非法输入 + "7.4s 在 8s 拒绝、在 4s 放行并进入 claim_rankings"。

### 71.2 六次 replay（floor=4.0）

| run | B1 admitted | admission 时刻 | headroom | tail 结果 |
| --- | --- | --- | --- | --- |
| docker r1 | 0 | — | — | 无（B1 未产出） |
| docker r2 | 0 | — | — | 无（B1 未产出） |
| docker r3 | 3 | — | — | 诊断记录未落盘（见 71.3）；该 run 有 1 个 B1 候选被 read |
| node r1 | 3 | ~42.3s | ~5.7s | 诊断记录未落盘 |
| node r2 | 3 | **47.484s** | **0.516s** | tail 触发 → 2 选中 → **`time_budget_exhausted`**（0.5s 无法支撑 ~3s assessment，拒绝正确） |
| node r3 | 3 | — | — | 诊断记录未落盘 |

**观测到的关键事实**：node 三次 admission 落在 42.3 / 43.1 / 47.5s（deadline 48s），即 **B1 段自身 11–18.5s** 让 headroom 只剩 0.5–5.7s。以 ~3s 的 assessment 成本计，只有最幸运的样本能过。**在已观测样本中，绑定约束是 B1 延迟而非 4s 地板**——但样本量不足以定论。

### 71.3 诊断生命周期缺陷（阻断 F1 定量结论）

新增的 `late_tail_invocations` 标记暴露：live run 中 wave-2 的调用条目停在初始值（`late_ids: 0`、`outcome: returned_early`、无 `matching_records`、无 `store_target_type`），即**该次调用既没走 `no_late_ids` 也没走 `_store()`**；而 `domain_records: 1` 证明记录当时可见。

- **离线复现证明 tail 逻辑本身正确**：同一函数、同一输入形状（wave 1 无记录 → `no_late_ids`；wave 2 有记录 → `assessed:1` + 记录落盘 + 进入 ranking）。
- 因此缺陷在 **runtime 的 context/metrics 生命周期**（live 运行中 metrics 映射在 marker 与 store 之间被替换或替换后未回写），不在 tail 逻辑。
- 影响：**诊断数据丢失**（部分 run 无 tail 记录），并且在"看不到 late ids"的路径上会**跳过实际 assessment 工作**——这会直接影响 F1 结论的可靠性。

### 71.4 待裁决：§71A-1（小批，先修可见性）

建议在继续 sweep 前做一个最小批：让 tail 的读写都经过**同一个 live metrics 映射**（store 时重新获取并做容错 upsert；若映射身份变化则显式记录 `metrics_identity_changed`），并补一条确定性测试锁住"live 形状下 marker 与记录必须同时落盘"。

### 71.5 结论措辞

- F1 旋钮已就绪、机制正确；**4.0s 实验值下尚未取得可定量结论**，因为 (a) docker 三次里两次 B1 未产出，(b) node 三次里两次诊断丢失，(c) 唯一完整样本显示的是 B1 延迟绑定。
- 不改变 §70 的封板结论；不进入 F2；不动 8.0 默认值（仍为默认）。

诊断产物（未跟踪）：`F1.docker.f4*.json`、`F1.node.f4*.json`。


## §72 §71A-1 完成：live metrics/context 生命周期修复（`f9f1edd8` → `f0446c46`）

### 72.1 根因链（三层，逐层被证据钉死）

1. **metrics key 被替换**：每次 invocation 的 `metrics_identity` 都不同 ⇒ runtime 频繁重建 `context[metrics_key]`；早期实现在函数入口捕获一次映射，写诊断时已过期。
2. **read-only 映射**：某些时刻该值是只读 Mapping，`isinstance(..., dict)` 检查失败 ⇒ 诊断静默丢弃（对应 `returned_early` 尸体）。
3. **整个 context 被替换**（真正根因）：`refresh_steering()` 执行 `nonlocal context; context = merge(...)`，把**整个 context 对象**换掉；tail 持有的 `context` 参数已失效，所有写入落到被丢弃的对象上。phase marker 最终定位：尸体停在 `phase="assessing"` 且**没有任何异常**——排除 abort 路径，只剩"写到了旧对象"。

### 72.2 修复（仅诊断一致性，行为零变化）

- `_resolve_live_metrics(context)`：每次读写边界重新解析；遇只读 Mapping 时把 context 重绑为同内容可写副本（业务状态仍以 live context 为准）。
- invocation 以稳定 `invocation_id = claim:wave:seq` 为键，初始 `outcome="running"`，`_finalize_late_tail_invocation` 按该键 **upsert 到 live 映射**（旧映射里的条目会被 `recovered` 迁移，绝不重复 append）。
- identity 漂移只记录（`metrics_identity / store_metrics_identity / metrics_identity_changed`），**不改变行为**。
- tail 新增 `live_context` 访问器（调用点传 `lambda: context`），在 marker / 域状态读取 / store / critical-path / 各 finalize 处**全部重新解析**。
- abort 包装：任何 `BaseException` 逃逸时先 finalize 为 `aborted:<Type>` 再 re-raise（控制流不变）。
- phase marker：`entered → decided:n → selected:n → assessing → stored`。

### 72.3 完成门（裁决四项，全部满足）

| 门 | 证据 |
| --- | --- |
| 行为零变化 | 只改诊断；focused 92 passed、Ruff clean；未触碰 eligibility/budget/ranking/assessment |
| 无悬空 invocation | node sanity **6/6 = 100%**、docker sanity **4/4 = 100%** terminal |
| identity 漂移可见 | 受影响 invocation 记录 `metrics_identity_changed: true` |
| 事件链一致 | 同一 run：`late_ids:3 → selected:2 → assessed:2 → ranked_after:5`（node）；docker `late_ids:2 → assessed:2 → ranked_after:6`；`late_assessment_tail` 与 `b1_critical_path` 同步落盘 |

**顺带首次在 live run 看到 late tail 完成真实工作**：node `headroom_at_admission=12.422s`、docker `15.641s`（admission 分别约 35.6s / 32.4s），selector 调用保持 **0**。

### 72.4 状态与下一步

```text
§70                CLOSED
§71A-1             CLOSED（本批）
F1 default         8.0（仍为默认，未冻结）
F1 calibration     可恢复：重启 8/6/5/4/3 sweep（数据现在可信）
F2                 NOT STARTED
F3                 NOT SELECTED
```

诊断产物（未跟踪）：`A1.node.sanity*.json`、`A1.docker.sanity.json`。


## §73 F1 calibration 结果（10 次 replay：floor 4.0×6、3.0×2、8.0×2）

### 73.1 数据（全部为 §71A-1 修复后的可信样本）

| run | gate | admission | head_adm | head_gate | floor | assessment 成本 | late | assessed | late read |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| docker 4.0 ×3 | partial | 26.4 / 31.4 / 32.4s | 21.6 / 16.6 / 15.6s | 20.6 / 15.5 / 14.5s | 4.0 | 0.97 / 1.09 / 1.11s | 2–3 | 2 | **✅ 3/3** |
| node 4.0 ×3 | block | 35.5 / 35.6 / 37.5s | 12.5 / 12.4 / 10.5s | 11.3 / 11.5 / 9.4s | 4.0 | 1.14 / 0.97 / 1.13s | 3 | 2 | ❌ 0/3 |
| node 3.0 | block | 35.6s | 12.4s | 11.5s | 3.0 | 0.95s | 3 | 2 | ❌ |
| node 8.0 | block | 37.1s | 10.9s | 10.0s | 8.0 | 0.89s | 3 | 2 | ❌ |
| docker 3.0 / 8.0 | — | — | — | — | — | — | 0 | 0 | —（该两次 B1 未产出候选） |

### 73.2 关键测量

1. **assessment 成本 = 0.89–1.14s**（8 样本，稳定）——远低于 8.0s 地板所隐含的假设。
2. **干净样本的 headroom at admission = 10.5–21.6s**，全部高于 8.0 ⇒ **在本分布下 floor 对 3.0/4.0/8.0 都不绑定**；地板只在低 headroom 异常样本（此前观测到 0.5 / 4.9 / 5.7 / 7.4s）上起作用。
3. **docker：late 候选 assessed → read 成功（3/3）**——首次观测到 Tier-1.5 候选走完到 read。
4. **node：late 候选 assessed 但未 read 是正确结果**：评估判定 `answer_relevant=false`（nodejs.org 博客页与"官方支持哪些模块系统"不相关），trace 显示 `covered_cluster / scheduler_not_selected`；第 3 个候选被 selector 窗口排除（`model_selection_not_chosen`）。**这不是缺陷，是冻结证据链按设计工作。**

### 73.3 F1 结论与冻结建议

按裁决标准——"floor 只负责阻止明显不可能完成有意义 downstream work 的启动"——现在有实测依据：

- 有意义 downstream work 的最低成本 ≈ assessment **1.1s** + read 计划/调度余量；
- 异常样本中 headroom 7.4s 时：评估后仍余 ~6.3s（足以调度 read），8.0 地板却会误杀；headroom 0.5s 时：连 assessment 都不够，拒绝正确；
- ⇒ 建议**冻结 floor = 3.0s**（≈2.7× 实测 assessment 成本 + 余量），把 8.0 明确记为"过保守的初值"。3.0 与 4.0 在现有数据上无行为差异，选 3.0 只因它更贴近实测下限；若倾向保守可选 4.0。

待裁决：冻结值取 **3.0** 还是 **4.0**（两者在全部干净样本上等价，仅在异常低 headroom 样本上不同）。

### 73.4 附带观察（不修）

- docker 的 B1 产出率仍受宿主 flakiness 影响：10 次 replay 中 2 次完全未产出候选。
- 干净样本的 admission 分布（26.4–37.5s）与此前异常样本（42.3–47.5s）差异很大 ⇒ B1 延迟方差是后续 F2 的主要输入。

诊断产物（未跟踪）：`F1b.*.json`、`F1c.*.json`、`F1.sweep.json`。


## §74 F1 冻结 3.0s 与 §71A CLOSED（`b47a9fe2`）

**冻结值**：`RESEARCH_LATE_TAIL_FLOOR_SECONDS = 3.0`（原 8.0 记为 *conservative bootstrap value*，不再作为默认）。

**冻结语义（写进代码注释与 contract）**：

> **Floor is an assessment-viability guard, not a downstream-completion reservation.**

它只回答"是否还值得启动 assessment"；ranking、read scheduler 与证据链自己决定后续，入口地板不得替它们做决定。

**依据**：修复后 assessment 实测 0.89–1.14s（8 干净样本），3.0s 提供约 2.6–3.4× 余量；3.0/4.0/8.0 在全部干净样本上行为等价，唯一差异区是 `3s < remaining < 4s`——4.0 无证据支持多拒绝这一秒。测试锁住：低于地板拒绝、3–4s 带内在冻结值放行、4.0 override 在该带拒绝。

**§71A 完整链路已闭合**：`late admission → tail selection → assessment → ranking → scheduler → read`；docker 3/3 late read 成功；node 的 0/3 是**正确拒绝**（`answer_relevant=false` + `covered_cluster`），即 late channel 已从"能不能跑"进入"正常接受语义筛选"。

**F2 状态**：`CHARACTERIZATION READY / not optimization-authorized`。待查 admission 长尾来源：inventory / 验证 read 数量 / 单次 fetch 延迟 / 10054 retry / 宿主 flakiness。先解释 26→47s 方差，再决定是否有可砍项。

---

## §75 §71B Retrieval Backend Contract（`061b88a9`，contract/types only）

**四条冻结边界**（以类型与校验器编码）：

| 边界 | 合同 |
| --- | --- |
| Discovery 外挂 | 只能产出 `DiscoveryCandidate` |
| Read 外挂 | 只能产出 `RawReadArtifact` |
| Evidence 权威 | 仍须经本地 assessment → extraction → support |
| Gate 权威 | 外部 confidence/evidence/score 永不映射进本地 Gate；`FORBIDDEN_AUTHORITY_FIELDS` 直接拒绝，未声明字段必须移入 `external_metadata`（惰性） |

**接口**：`DiscoveryBackend.search(DiscoveryRequest) -> list[DiscoveryCandidate]`；`ReadBackend.fetch(ReadRequest) -> RawReadArtifact`（Protocol，最小字段集）。

**生命周期（继承 §71A-1 教训）**：`retrieval_invocation_id = claim:wave:backend:operation:seq`；创建与终结都通过 **provider callable 重新解析 live metrics**（backend 不得持有长期 context/metrics 引用）；终结按 id upsert，旧映射条目 `recovered` 迁移，绝不重复；非终态被拒；`assert_retrieval_invocations_terminal` 固化"created ⇒ terminal"不变式。

**预算合同（只定义，不实现策略）**：三本账共用一口钟——`model_attempt`（外部后端永不消耗）/ `retrieval_attempt`（按 backend 记账）/ `wall_clock`（每秒钟都记在它头上，因为浏览器 fetch 的 4 秒与研究窗口里模型调用的 4 秒等价）。

**测试**：8 条合同测试（边界、id 格式、终态不变式、映射替换下的 recovered upsert、预算分离）。

**后续顺序**：§71C Wigolo `fetch`-only shadow reader → §71D discovery bakeoff（Current / DDGS / Agent Search / AutoSearch，强制指标含 ΔB1 admission 与 Δlate-tail headroom）→ §71E 最小 production routing。


## §76 候选 head 门禁：pre-external-backend baseline（`fc50845`）

**状态**：`§71A CLOSED + §71B CLOSED + tracked clean`，作为引入任何外部 retrieval backend 之前的完整基线。

| 门 | 结果 |
| --- | --- |
| full pytest | **2120 passed / 2 failed**（728.6s） |
| 失败 signature 对照（vs `5ecca00` 的 3 项） | 已知 2 项 Windows-local 平台失败保持同类（`test_rq1c_impl_entrypoints::…exact_head_guard`、`test_rq1c_protocol_probes::…deterministic_protocol_runner…`）；上次的负载型闪失败（`test_discovery_annotation::…blind_and_deterministic`）本次未复现 ⇒ **失败数 3→2，无新增 failure family** |
| 回归检查 | 无 retrieval-contract / late-tail 相关新回归 |
| Ruff（src/tests/tools） | All checks passed |
| `git diff --check` | clean |
| tracked 工作区 | clean |
| d40.2 四项不变量（frozen replay，runs=3） | **gate=pass ✓ · binding=valid（3/3 ok, fail_closed 0.0）✓ · consistency=clean ✓ · publish=substantive（1.0 / 1.0）✓** |

**基线用途**：§71C 起会首次引入外部运行时依赖（浏览器/本地模型）、额外 wall-clock 与新失败面；此后任何全量门异常都先与此 baseline 对照，用于区分 tail/contract 改动与 Wigolo 接入引入的问题。

诊断产物（未跟踪）：`full_pytest_fc50845.log`（temp）、`D402.replay.fc50845.json`（temp）。


## §77 §71C-1/2 Wigolo fetch-only shadow 实验（`5c0e73ef`，shadow only）

**接入方式**：REST `POST 127.0.0.1:3333/v1/fetch`（不走 MCP）；`wigolo@0.2.1`；浏览器经 `warmup --browser` 预装（setup cost 单独记录，不进 fetch 延迟）；daemon 无任何 LLM/API key；只用 `fetch`，未用 search/research/agent/extract。代码：`src/web/research/wigolo_backend.py`（§71B `ReadBackend`）、`tools/run_wigolo_shadow_bakeoff.py`（10 URL corpus A–F、cold/warm 分跑、`--cache-bust`）。

### 77.1 三个环境坑（必须先记录，否则数据不可信）

1. **`WIGOLO_RERANKER` 默认会毁掉测量**：reranker 未安装时每次请求都反复 `Loading rerank model`（≈11s × 3 ≈ **33s/请求**，连 cache 命中也要 33s）；更糟的是超时使 `http fetch failed` 三次后 daemon 把域**标记为 playwright**，污染域学习（这就是首轮"browser 升级 40s"的来源）。设 `WIGOLO_RERANKER=off` 后延迟从 ~33s 降到 **23–299ms**（cache）/ ~1s（http）。
2. **cache 按 URL 存"首次调用时的截断文本"**：先用 `max_chars=2000` 取过，再用 `max_chars=20000` 取同 URL 仍返回 2,000 字符的缓存版本 ⇒ 测量与生产都必须固定 `max_chars`，或把 max_chars 纳入 cache key 认知。
3. **cache-bust 查询参数会改变站点行为**（部分 URL 直接 4xx）⇒ 不能作为通用 cold 测量手段；本批 cold 结论以 plain-URL 行为准。

### 77.2 关键结果（plain URL、reranker off）

| class | URL | current reader | Wigolo | 判定 |
| --- | --- | --- | --- | --- |
| A_known_thin | docs.docker.com/docker-hub/usage/pulls（§47/§63 旗舰案例） | short_doc **520** chars @2.0–3.0s | **ok 10,793 chars @0.73–1.27s（http，无 browser）**，heading recall 0.0→1.0 | ✅ **救活且更快** |
| A_known_thin | docs.docker.com/ | fetch_failed / extraction_loss | **ok 3,020 @1.03s（http）** | ✅ 救活 |
| D_spa_shell | github.com/astral-sh/uv | extraction_loss **0** | **ok 10,915 @1.44s（http）** | ✅ 救活 |
| B_js_heavy | hub.docker.com | fetch_failed @44s | **ok 5,030 @38.8s（browser）** | ✅ 救活但**极贵** |
| B_js_heavy | docs.docker.com/search/?q=… | 不稳定（ok/failed 交替） | http 3,020 @1.7s 或 http_error | ⚠️ 不稳定 |
| C_already_pass | nodejs / postgresql / redis | ok | ok，chars ≥ 现状，cold 0.9–1.3s（比现状 1.7–3.5s 更快） | 无实质增益（**false escalation value = 0**） |
| E/F | PDF / github sitemap | failed | failed（anti_bot / http_error） | 双方均失败 |

**裁决指标（按 77.1 修正后）**：failure 集合 7 个（A×2、B×2、D、E、F），**救活 4（≈57%）**；其中 **http 层 3 个（≈43%）每个仅 ~1s**，browser 层 1 个（~39s）。already-PASS 页面 0 个出现实质增益。added latency：http 层救活为**负值**（Wigolo 比现有 reader 更快）。

### 77.3 §71C-3 建议（待裁决）

授权**升级式**使用，而非把 Wigolo 当默认 reader：

```text
current HTTP reader
      ↓
ReadAdequacy FAIL
      ↓
Wigolo http tier（render_js 与 max_chars 固定；~1s）
      ↓
仍 FAIL 且剩余预算充足 → Wigolo browser tier（~39s，需显式预算门）
```

依据：http 层在真实失败页上 3/3 救活、~1s、负增延迟；browser 层能救但吃满 48s 窗口（hub.docker.com 39s），只能作为"最后手段 + 预算门"。already-PASS 页面无增益 ⇒ 不升级。

**待办（不修）**：daemon 启动必须带 `WIGOLO_RERANKER=off`（记录为运行前提）；cache/max_chars 交互需在生产接入前固定；browser tier 的预算门与超时需要单独 characterization。

诊断产物（未跟踪）：`WIGOLO_SHADOW.cold{,2,3}.json`、`WIGOLO_SHADOW.warm.json`、`wigolo_serve*.log`（temp）。
