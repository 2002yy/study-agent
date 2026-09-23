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


## §78 §71C-3 裁决与执行计划（已批准，待实现）

**状态**：`§71C-1/2 CLOSED`（shadow 实验与数据在 §77）；**§71C-3a 尚未实现**——本节是明日执行的合同与切片，不是完成记录。

### 78.1 裁决（3a / 3b 拆分）

- **§71C-3a（批准）**：Wigolo **HTTP tier** 进入 production escalation：

```text
current reader
    ↓
ReadAdequacy PASS ─────────────→ existing pipeline
    │
    FAIL
    ↓
Wigolo HTTP-only（固定 max_chars；~1s）
    ↓
ReadAdequacy PASS ─────────────→ existing Extraction/Support/Gate
    │
    FAIL
    ↓
browser escalation NOT automatic（默认不启用）
```

- **不要把 Wigolo 变成默认 reader**：C 组（already-PASS 0 增益）证明 routing 必须是 `current first → adequacy FAIL → Wigolo`。
- **§71C-3b（保守）**：browser tier **默认 OFF**（`WIGOLO_BROWSER_ESCALATION=off`），代码路径与 ledger 可接线，但只允许显式实验启用。理由：browser 只有 **1 个有效成本样本**（hub.docker.com 38.8s 救活），证明"有能力价值"但未证明"有生产时间价值"；38.8s 在 48s 窗口里接近 all-in，且进入 browser 时往往已非 t=0。**不得**现在冻结类似 `seconds_left >= 40` 的预算门（样本不足，不知 p50/p95/域间方差）——留给 **§71C-4 Browser-cost characterization**（5–10 个真需 browser 的页面：cold/warm、成功率、latency/timeout 分布、域方差、剩余 downstream 成本）。

### 78.2 随 3a 一起冻结的约束

1. **`max_chars` 是合同，不是启动参数**：冻结 `WIGOLO_FETCH_MAX_CHARS = 20_000`（当前救活页最高 ~10.9k，留 ~2× 余量）。语义 = **cache-affecting retrieval contract parameter**：改值视为 cache schema/config migration，不是普通 tuning（因为 daemon cache 保存的是"首次调用时被截断的文本"，§77.1-2）。provenance 至少留 `max_chars_requested` / `chars_returned`；Wigolo 若能暴露 truncation 信号才记 `possibly_truncated`，**不能猜**。
2. **`WIGOLO_RERANKER=off` 是 hard preflight**：不满足 ⇒ `backend unavailable` ⇒ **不调用 Wigolo**、current path 正常继续、diagnostics 明确写 `misconfigured`。不许"试一下看看"（否则某台机器重启 daemon 会把 1s fallback 悄悄变成 33s 黑洞，并触发 false domain→browser promotion）。
3. **Ledger 区分 tier**：`backend=wigolo` + **`tier = http | browser`**；每条记录 attempts / rescues / failures / latency / chars gain / **adequacy transition**（如 `short_doc → ok`），作为"Wigolo 长期是否值得保留"的线上证据。
4. **失败隔离硬锁**：daemon absent / connection refused / timeout / invalid JSON / schema mismatch / 内部失败 ⇒ **只产生 terminal retrieval failure**；不得改 current reader 结果、不得改 claim ranking、不得伪造空 `RawReadArtifact`、不得把 external failure 当 source evidence。即：**fallback 自己失败只损失一次 fallback 机会，不能损伤原能力。**
5. **不扩范围**：E/F（PDF、github sitemap）双方失败是好信息，本批只做 **HTML/web-document rescue**；PDF 若值得做应单独 reader/backend。

### 78.3 §71C-3a 完成门（10 项，缺一不可）

```text
1.  already-PASS → Wigolo calls = 0
2.  inadequate HTTP → Wigolo HTTP 被调用
3.  Docker flagship → rescue
4.  Wigolo failure → 原链行为不变
5.  browser tier production calls = 0
6.  reranker misconfig → fail closed
7.  retrieval invocations terminal = 100%
8.  model_attempt budget 不变
9.  retrieval ledger / wall clock 正确增加
10. max_chars 固定值进入 provenance
```

通过后，Wigolo HTTP escalation 才正式记为"Study Agent 第一项成功吸收的外挂能力"。

### 78.4 明日执行切片（单一入口）

1. `src/web/research/read_adequacy.py`：把 §46 adequacy 判定提取为生产库函数（阈值/markers 与 `tools/run_read_adequacy_probe.py` 同源，工具改为引用，行为不变）。
2. `wigolo_backend.py` 扩展：`WIGOLO_FETCH_MAX_CHARS=20_000`、`tier` 参数（http|browser）、hard preflight（reranker/health，fail closed）、provenance 字段。
3. `src/web/research/read_escalation.py`：escalation 编排（可注入 backend；任何失败 → 返回原 reader 结果 + 诊断）。
4. 接入 `ActiveResearchGateway.read`（current first；`RESEARCH_WIGOLO_ESCALATION=off|http|browser`，默认 `off`，gate 重放用 `http`；browser 仅显式实验）。
5. runtime：把 escalation 诊断聚合进 §71B ledger（`retrieval_attempts` / `retrieval_invocations`，含 tier 与 adequacy transition），wall clock 已由 read phase 计时。
6. 确定性测试（无 daemon）：PASS 不调用 / FAIL 调用并救活 / 失败不改原结果 / browser 默认不调用 / reranker misconfig fail closed / max_chars 与 provenance / ledger terminal 100% / model attempt 计数不变。
7. 完成门重放：Docker case（production path，`RESEARCH_WIGOLO_ESCALATION=http`）逐项核对 78.3 的 10 条，记录 artifact。

**当前 head**：`39216d0`（tracked clean）。daemon 仍以 `WIGOLO_RERANKER=off` 在 loopback 运行。


## §79 §71C-3a 实现与完成门（HTTP tier 进生产 escalation）

实现提交：`e6ca9441`（主体）、`79d02cca`（preflight 原因区分）、`5af5aacb`（ledger 字段 + per-read 诊断）、`15670b85`（provenance 记录 daemon 侧 max_chars）。

### 79.1 生产链（已生效，默认 off）

```text
current reader（始终先跑）
    ↓
ReadAdequacy PASS ──────────→ existing pipeline（不做任何外部调用）
    │ FAIL
    ↓
Wigolo HTTP tier（render_js="never" ⇒ 绝不涉及浏览器；固定 max_chars=20000）
    ↓
ReadAdequacy PASS ──────────→ existing Extraction/Support/Gate
    │ FAIL → 保留原 reader 结果（不伪造、不改 ranking）
```

开关：`RESEARCH_WIGOLO_ESCALATION=off|http|browser`（默认 off；browser 另需 `WIGOLO_BROWSER_ESCALATION=on`，默认不启用）。硬预检：daemon health + 客户端 `WIGOLO_RERANKER=off`，否则 **fail closed**（不调用、原链继续、诊断记 `misconfigured` / `backend_unavailable`）。

### 79.2 完成门 10 项（`C3A.docker.gate3.json`，head `5af5aacb`）

| # | 项 | 结果 |
| --- | --- | --- |
| 1 | already-PASS → Wigolo calls = 0 | ✅ 确定性测试覆盖（adequate 读取 `attempted=false, reason=already_adequate`，backend 调用 0）；live 运行 7 次尝试全部来自 inadequate 读取 |
| 2 | inadequate HTTP → Wigolo 被调用 | ✅ 7 次尝试，tier 全 http |
| 3 | **Docker flagship → rescue** | ✅ **`docs.docker.com/docker-hub/usage/pulls` read 成功，且是该 run 唯一 eligible evidence，gate=pass** |
| 4 | Wigolo 失败 → 原链行为不变 | ✅ 转移记录显示 `read_failed -> read_failed`、`short_doc -> read_failed`，即失败时保留原形状 |
| 5 | browser tier production calls = 0 | ✅ tiers={http}，browser=0 |
| 6 | reranker misconfig → fail closed | ✅ 确定性测试 + **in-vivo 意外验证**：首次 gate 重放时 daemon 恰已停止，7 次尝试全部 fail-closed（原因区分后记为 `backend_unavailable`），读取结果完全未受影响 |
| 7 | retrieval invocations terminal = 100% | ✅ 7/7 |
| 8 | model_attempt budget 不变 | ✅ orchestration 调用 3（domain proposal 1 + selector 2），retrieval 不消耗模型账 |
| 9 | retrieval ledger / wall clock 正确增加 | ✅ 7 条 attempt、latency 合计 7.3s；**但见 79.3-1 的预算后果** |
| 10 | max_chars 固定值进入 provenance | ✅ 修复后记录 daemon 侧实际值 20000（gate3 早于该修复，行内仍是调用方的 6000/1200 ⇒ 已修，待下次运行确认） |

### 79.3 必须记录的后果与债务

1. **wall clock 后果**：该 run elapsed **62.6s**，违反 `hard_timeout_exceeded`（>60s）。escalation 本身只贡献 7.3s，但足以把本已接近边界的 case 推过线。⇒ 生产启用前需要一条预算策略（例如：仅在剩余窗口足够时升级；或把 escalation 视为读预算的一部分）。**这不是 escalation 的缺陷，而是必须显式定价的真实成本**（§78.2 预留的"wall clock 统一计"正是为此）。
2. **per-source escalation 诊断未落地**：`sources[].escalation` 仍为 null（ledger 有完整数据）。记为债务，不影响门项判定。
3. `RESEARCH_WIGOLO_ESCALATION` 仍为默认 **off**；本次门禁用 `http` 显式开启。是否默认开启属**生产化决策（§71E）**，需先解决 79.3-1 的预算定价。
4. browser tier 仍按 §78 保守：只接线，不自动启用；§71C-4 browser-cost characterization 未开始。

### 79.4 结论

**§71C-3a 的 10 项完成门全部满足**（其中第 10 项以"已修复 + 单测"形式满足，待下一次运行确认数值）。Wigolo HTTP escalation 正式成为 Study Agent 吸收的第一项外挂能力：**旗舰案例从 520 字符提升到可成为唯一 gate-eligible 证据，且延迟低于原 reader**。

诊断产物（未跟踪）：`C3A.docker.gate.json`（daemon 停机、fail-closed 证据）、`C3A.docker.gate2.json`、`C3A.docker.gate3.json`（正式门禁）。


## §80 候选 head 门禁：HTTP-escalation integrated / pre-budget-policy baseline（`480cd4e`）

**状态**：§71C-3a 已实现（默认 off），首次有外部 Reader 进入生产读取路径；本 head 作为**预算策略（B）之前**的正式 baseline。

| 门 | 结果 |
| --- | --- |
| full pytest | **2133 passed / 3 failed**（652s） |
| 失败 1–2 | 已知 Windows-local 平台失败（`…exact_head_guard`、`…deterministic_protocol_runner…`），与 `fc50845` baseline 同类 |
| 失败 3 | `test_dirty_tracked_checkout_blocks_imported_internal_artifact_writes`：**负载型闪失败**——单独复跑 1 passed，且在 `fc50845` 的全量中通过；非本批回归 |
| 新失败 family 检查（按要求） | **无**：retrieval lifecycle / read adequacy / source provenance / budget accounting 相关测试全绿（新增 `test_read_escalation.py` 14 项、`test_retrieval_backends.py` 8 项均通过） |
| Ruff（src/tests/tools） | All checks passed |
| `git diff --check` | clean |
| tracked 工作区 | clean |
| d40.2 四项不变量（frozen replay，runs=3） | **gate=pass ✓ · binding=valid（3/3 ok）✓ · consistency=clean ✓ · publish=substantive（1.0/1.0）✓** |

**归因用途**：B（预算策略）会改动读取路径的准入与记账；此后任何全量门异常都先与 `fc50845`（无 escalation）和 `480cd4e`（有 escalation、无预算策略）两份 baseline 对照。

**B1 的已知数据缺口**（下一步要补的仪器）：现有 attempt 行缺少 `url`、升级时刻的 `research/hard seconds_left`、以及 rescue 最终是否成为 evidence 的链接，因此"marginal rescue utility by escalation order"目前无法从 artifact 直接算出。

诊断产物（未跟踪）：`C3A.docker.gate{,2,3}.json`、`full_pytest_480cd4e.log`（temp）、`D402.replay.480cd4e.json`（temp）。


## §81 B1 完成：escalation 成本与边际效用的可测量化

仪器（`5210e73` + `5648092` + `7576ea7`）：attempt 行现在携带 `url / attempt_seq / research_seconds_left_at_start / hard_seconds_left_at_start / invocation_id`；`sources[].escalation` 投影携带 `invocation_id`（闭合 null 债务）；invocation 先于 attempt 行创建（顺序修复）。三类判定：①useful rescue（升级后 ok 且该 source 最终进入 eligible evidence）②unused rescue（升级后 ok 但未被采用）③failed（升级后仍失败/后端失败）；`attempted=false` 的行（adequate 读取、禁用模式）不计入三类。

### 81.1 数据（4 次生产 replay；r1 为仪器前、r3 只有 1 次尝试、r2/r4/r5/r6 完整）

| run | attempts | 总 escalation ms | rescued | gate | 备注 |
| --- | --- | --- | --- | --- | --- |
| r1 | 8 | 0（daemon 停机，全部 fail-closed） | 0 | block | **fail-closed in-vivo 验证**：读取结果完全未受影响 |
| r2 | 8（7 真实） | **408ms** | 3（www.docker 141ms、pulls 16ms cache、pulls 0ms cache） | pass | `hard_timeout_exceeded` 但 escalation 仅 0.4s ⇒ 超时主因**不是** escalation |
| r3 | 1 | 0 | 0 | block | B1 仪器后首跑（该 run 读取本就 adequate） |
| r4 | 2 | 62ms | 1（www.docker 15ms cache） | block | |
| r5 | 4 | 1,640ms（其中 mcp-server 1,531ms） | 2（pulls 31ms cache、mcp-server 1,531ms http） | **pass** | pulls rescue 进入 eligible evidence（①类实锤） |
| r6 | 5 | — | — | block | |

### 81.2 结论

1. **HTTP tier 的真实成本远低于此前 7.3s 的担忧**：reranker 修复后，单次 15–80ms，偶发 1–1.5s；6 个可信样本的 escalation 总成本 62ms–1.64s。
2. **①useful rescue 真实存在**：pulls 页 rescue 后成为唯一/关键 eligible evidence（r5 gate=pass），且 cost 31ms（cache）/1.5s（http）。
3. **②unused rescue 存在**（同域候选被评估拒绝或 cluster 覆盖），单次 ≤47ms（cache）或 ~1.5s（http）。
4. **③failed 集中在同域 http_error**（docs.docker.com 子页 404 类），单次 31–79ms——几乎免费。
5. **62–64s 的 hard_timeout 与 escalation 无关**（escalation 仅 0.4–1.6s）；超时主因是既有的 wave/selector/assessment 时间分布（F2 范畴）。
6. **联动缺口（记录为债务）**：重试读取会产生多个 invocation（如 pulls 的 fetch:5/6/7），source 记录的是最后一个；分析时需按 URL+wave 聚合而不是精确 id 匹配。

### 81.5 B2 裁决输入

- per-attempt 成本实测：**p50 ≈ 47ms，p95 ≈ 1.5s**（http 层）；
- **per-run envelope 建议区间**：2–5s 即可覆盖本分布的全部 rescue（最大单 run 1.64s），且不会成为窗口的主要消耗；
- hard-headroom 门：按实测，评估启动成本 ≈1.1s（见 §73）+ http fetch p95 1.5s ⇒ 门设为 ~3s 已足够（与 F1 冻结值一致）；
- 按序边际效用：rescue 多发生在前 1–2 次 attempt（同域重复失败的后续 attempt 几乎全是 ③failed 且成本极低）⇒ envelope 而非次数上限是正确选择。

**B1 CLOSED。** B2（hard-headroom 门 + per-run envelope + 默认值决策）待裁决。


## §82 B2 完成：两层预算门 + envelope 记账（`8e15aca` + 修复提交）

### 82.1 实现（candidate defaults，未冻结）

```text
RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT = 3.0   # hard-headroom 门
RESEARCH_WIGOLO_HTTP_RUN_ENVELOPE_SECONDS  = 3.0   # per-run wall-clock envelope
```

- 准入顺序：adequacy FAIL → mode≠off → **hard headroom ≥3.0** → **envelope 余量 >0** → preflight → Wigolo HTTP。
- **envelope 可执行**：`effective_timeout = min(envelope_remaining, hard_headroom)`（下限 1.0s，低于则拒绝并记 `run_envelope_exhausted` / `hard_headroom_insufficient`），通过 `ReadRequest.timeout_seconds` 传给 backend（backend 取 min(自身上限, 请求值)）⇒ **单次调用不能穿透 envelope**。
- envelope 按**真实 latency** 计费（成功与失败都计），per-run 重置（run 开始时 `reset_http_envelope()`）。
- **按时间不按次数**：B1 证明失败仅 31–79ms，次数上限会误杀 40ms 的关键 rescue —— 已写入 rationale。
- 拒绝原因入账：`disabled / already_adequate / hard_headroom_insufficient / run_envelope_exhausted / backend_unavailable / misconfigured / ...`（attempt 行记录，无 invocation）。

### 82.2 Gate replay（两 case，均 gate=pass）

**docker（`B2.docker.gate2b.json`，elapsed 64.5s，gate=pass）**：8 attempts / 377ms 总计；①useful ×1 —— **`docker-hub/usage/pulls` 在 escalation #7（seq 11）由 `read_failed` 救活为 `ok`，成为 eligible evidence 并驱动 gate=pass**（`linked=Y`，经 invocation_id 反查）；②unused ×4；③failed ×3。

**node（`B2.node.gate2.json`，elapsed 66.3s，gate=pass）**：2 attempts / 1,656ms；①useful ×1 —— **`node.org.cn/` `short_doc → ok`（@453ms），进入 eligible evidence**（`linked=Y`）；③failed ×1（nodejs.org 博客页 1,203ms，envelope 内）。

**八项验收**：
1. headroom>3 + envelope 足够 → 正常运行并 rescue ✅（两 case 各 1 次 ①）
2. hard headroom <3 → 不调用 ✅（确定性测试）
3. envelope 耗尽 → 不升级 ✅（确定性测试 + 单测覆盖 `run_envelope_exhausted`）
4. 前次便宜 → 剩余 envelope 可用于后续候选 ✅（r2/docker：多次 attempt 累计仅 377ms）
5. backend 失败 → terminal ledger + 原链不变 ✅（③类转移保留原形状）
6. useful rescue → sources[].escalation 经 invocation_id 反查 ledger ✅（两 case 的 ① 均 `linked=Y`）
7. already-PASS → 0 external calls ✅（gate2：already_adequate 尝试 0 invocation；单测）
8. model_attempt budget 不变 ✅（by_purpose 仅 domain_proposal/selection_authority）

**关键修复**：`_record_escalation_diagnostics` 重写——invocation 仅在 attempted 时创建（消灭 running 尸体）、先建 invocation 再写 attempt 行（行内 invocation_id 非空）、补 envelope/provenance 字段、`TERMINAL_RETRIEVAL_STATES` 从 §71B 导入。

### 82.3 必须记录

- 两 case 均 `hard_timeout_exceeded`（64.5s / 66.3s），但 escalation 仅 0.38s / 1.66s ⇒ **超时主因仍在 F2（wave/selector/assessment 分布）**，B2 只保证新增 fallback 本身预算有界（已达成）。
- cold 案例：本两 run 的 rescue 均为 cache 命中或已缓存域；**§71E 默认开启裁决前需补一个自然未缓存的 cold HTTP rescue 样本**（不加 query 参数，用真实未访问过的同类页面）。

### 82.4 状态

```text
§71A CLOSED（floor 3.0 冻结）
§71B CLOSED（contract）
§71C-3a CLOSED（10/10）
B1   CLOSED（成本/边际效用可测量）
B2   CLOSED（两层预算门 + envelope 记账 + 8 项验收）
§71E default=http 裁决 → 待补 cold rescue 样本
§71C-4 browser characterization → NOT STARTED
F2    CHARACTERIZATION READY
```


## §83 §71E 前 cold rescue 单点门：结果与两个新发现

### 83.1 cold 通路已证明（对照抓取）

`https://docs.astral.sh/uv/`（同宿主对照，未 cache-bust）：
```text
cache_hit = false（真 cold）
retrieval_mode = http（无 browser）
latency = 1,000ms
chars = 7,266
```
⇒ **cold HTTP tier 的成本约 1s，3.0s envelope 足够覆盖**（与 §71 观察的 0.7–1.5s 一致）。

### 83.2 但 cold **useful rescue** 本轮未能产出，原因已定位（非 B2 缺陷）

| 候选（reader inadequate） | cold | Wigolo cold 结果 |
| --- | --- | --- |
| `docs.docker.com/reference/cli/docker/pull/`（reader short_doc 505） | ✅ | `http_error` @31–375ms（连试 3 次） |
| `docs.docker.com/docker-hub/repos/` | ✅ | `http_error` |
| `hub.docker.com/_/postgres` | ✅ | `timeout`（被 effective timeout 正确截断在 3.03s） |
| `www.docker.com/products/docker-desktop/`、`/pricing/` | ✅ | `http_error` |
| docs.astral.sh / node.org.cn / github / nodejs 各页 | — | reader 本就 adequate（正确不升级） |

即：**唯一"reader inadequate + 可救援"的宿主类（docs.docker.com / hub.docker.com / www.docker.com）在本环境的当前窗口内正好不可达**（与 §47 已记录的宿主 flakiness 一致）；健康宿主上我们的 reader 本身 adequate，因此没有救援机会。daemon 日志显示这些失败是 `TypeError: fetch failed`（连接层），非参数或合同问题。

**结论**：cold 通路的**成本**已证明（1s），cold **rescue** 样本受环境可达性阻塞，需在 docs.docker.com 可达时重取（不加 query 参数；该页失败不入 cache，仍为 cold）。

### 83.3 本单点门顺带发现并修复的两个真 B2 缺陷（均已提交）

1. **effective timeout 未被执行**（`4363048d`）：backend 忽略 `request.timeout_seconds`，只用自身 8s；cold hunt 实测 `hub.docker.com` 一次尝试耗时 **8,031ms**，而 envelope 为 3.0s ⇒ 单次调用穿透 envelope。修复为 `min(backend, request)`，复测同 URL 变为 **3,015–3,031ms**（正确截断），并加确定性测试（urlopen monkeypatch 断言 min 规则）。
2. **单次 per-url timeout 会打开 circuit breaker**（`e60ffdc`）：一次慢请求后，同 run 后续 escalation 全部返回 `unsupported` 且不发出请求（false negative，可能掩盖后续 useful rescue）。修复：per-url timeout 只计入 envelope，不再触发 circuit；circuit 仅保留给系统性失败（preflight）与显式标记。

### 83.4 §71E 裁决输入（待裁决）

现有证据：
```text
cold HTTP 成本            ≈1.0s（对照抓取，真 cold）
warm/cache 成本           15–80ms（多次）
useful rescue（warm）     docker pulls / node.org.cn → 进入 eligible evidence，gate=pass
envelope 执行             ✅ 已实测截断（3.03s，修复后）
hard-headroom/拒绝语义    ✅ 确定性测试 + live 记录
browser calls             0
```

缺项：**一个 cold 的 FAIL→PASS useful rescue 实例**（受宿主可达性阻塞，非设计问题）。

两个可选路径：
1. **等可达窗口补 cold rescue 后冻结**（最稳；§71E 推迟，可能数分钟到数小时不定）；
2. **以现有证据冻结 defaults 并默认开启**，把 cold rescue 作为**开启后的线上观察项**（首次遇到 cold 救援时核对 envelope/provenance），理由是 cold 成本已被同宿主对照实测、envelope 已被实测截断、且 fail-closed 与预算语义均有确定性覆盖。

倾向建议：**路径 1**（多一次抓取即可闭合，且能让 §71E 的证据链完整）；若你选择路径 2，建议同时约定"开启后第一个 cold rescue 必须回填证据"。


## §84 状态封板：B2 参数冻结 + §71E 单点门（`f6dc0de6`）

### 84.1 冻结

```text
RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT = 3.0   FROZEN
RESEARCH_WIGOLO_HTTP_RUN_ENVELOPE_SECONDS  = 3.0   FROZEN
RESEARCH_WIGOLO_ESCALATION                 = off    （等 §71E 最终门）
```

冻结依据（写入代码注释）：健康宿主真 cold ≈1.0s（同宿主对照抓取）；历史 cold 0.7–1.5s；warm/cache 15–80ms；修复后最慢尝试被截断在 3.03s（修复前 8.03s）；useful rescue 集中于前 1–2 次尝试。env 覆盖仅保留给实验。

**范围边界（写进代码与文档）**：B2 只保证"新增的 optional fallback 不成为无界新时间源"，**不负责**让整个 Study Agent <60s——后者是 wave/selector/B1 admission 的长尾，归 **F2**；不得把 F2 问题拖回 §71E。

### 84.2 §71E 最终门（单点，已收窄）

只补 **1 个 post-fix、自然 cold、useful rescue** 样本，随后立即裁决 `default=http`，**不再追加实验**。首选 URL：`https://docs.docker.com/reference/cli/docker/pull/`（reader short_doc 505 字符，失败不入 cache，仍为 cold）；若该宿主持续不可达，允许用任何**自然未缓存**且满足 `current FAIL + Wigolo HTTP 可救` 的真实 URL 替代（关键是验证最终实现的 cold 链路，不是验证某个域）。

10 项判据：①current inadequate ②`cache_hit=false` ③mode=http ④browser=0 ⑤latency ≤3.0s 可执行 envelope ⑥Wigolo adequacy PASS ⑦进入 eligible evidence/source ⑧`sources[].escalation ↔ invocation_id ↔ ledger` 闭合 ⑨invocation terminal ⑩model_attempt 不变。

**当前阻塞（已记录，非设计问题）**：本环境窗口内 docs/hub/www.docker.com 均不可达（`http_error` / 被正确截断的 `timeout`），而健康宿主（astral / ruff / node.org.cn / nodejs / github）上我们的 reader 本身 adequate ⇒ 无救援机会。这是 §47 已记录的宿主 flakiness；不得为了凑样本把正常页送进 escalation。

### 84.3 本轮 cold hunt 的净收益（两个真缺陷已修）

1. `4363048d`：effective timeout 未被执行（8.03s 穿透 3.0s envelope）→ 修为 `min(backend, request)`，复测 3.015–3.031s，确定性测试覆盖。
2. `e60ffdc`：单次 per-url timeout 误开 circuit，静默屏蔽同 run 后续 escalation → 修为仅计 envelope，circuit 留给系统性失败。

### 84.4 状态表

```text
§71A                     CLOSED（late-tail floor 3.0 冻结）
§71B                     CLOSED（retrieval backend contract）
§71C-3a                  CLOSED（HTTP escalation 10/10）
B1                       CLOSED（成本/边际效用可测量）
B2                       CLOSED（两层预算门 + 冻结参数）
HTTP min hard headroom   3.0s FROZEN
HTTP run envelope        3.0s FROZEN
RESEARCH_WIGOLO_ESCALATION  off（pending §71E final gate）
§71E blocker             exactly one post-fix natural-cold useful rescue
§71C-4 browser           deferred（等 HTTP 默认化稳定后，用真实剩余失败集做）
F2                       CHARACTERIZATION READY（wave/selector/admission 长尾）
```


## §85 F2 characterization 启动：离线时间账首版（`0c59bc79`）

工具：`tools/run_f2_time_ledger.py`（纯离线观测，不改任何 counts/timeout/selector/retry 策略）。它把每次 run 的墙钟拆成命名段并从**现有 artifact** 读出：research window、search/assessment/read/extraction 四相（秒数 + 调用数）、B1 critical path（start/admission/segment）、late tail 成本、selector 延迟与调用数、retry/inventory 计数、answer stage，以及"命名段合计 vs 未归因"。

### 85.1 六个样本的账（秒）

| run | elapsed | research | search | assess | read | extract | selector | b1_adm | b1_seg | named | unattr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B2.docker.gate2b | 64.5 | 38.4 | 12.6 | 2.9 | 10.4 | 5.6 | 2.78 | 32.8 | 9.3 | 34.3 | 4.1 |
| B2.node.gate2 | 66.3 | 41.9 | 12.5 | 4.2 | 8.8 | 8.1 | 3.31 | 34.0 | 8.4 | 37.0 | 4.9 |
| B1.docker.r2 | 64.5 | 33.8 | 11.6 | 2.0 | 7.7 | 4.5 | 1.58 | 30.4 | 11.5 | 27.5 | 6.3 |
| B1.docker.r5 | 54.4 | 30.1 | 11.4 | 2.5 | 8.6 | 1.2 | 1.30 | 27.8 | 12.3 | 25.0 | 5.1 |
| A1.node.sanity5 | 54.3 | 49.5 | 12.9 | 6.6 | 9.3 | 6.7 | 7.17 | 35.6 | 8.2 | 42.6 | 6.9 |
| F1c.node.f8 | 55.0 | 50.7 | 12.9 | 7.0 | 7.1 | 9.7 | 6.85 | 37.1 | 6.6 | 43.6 | 7.2 |

fast（admission <35s）vs slow（>=35s）中位数 delta：

```text
search     +0.35      <- 网络相，稳定
read       +0.46      <- 网络相，稳定
selector   +4.39      <- 模型调用相
assessment +4.10      <- 模型调用相
extraction +4.09      <- 模型调用相
B1 segment -3.30      <- 慢 run 的 B1 段反而更短
unattributed +2.03
named      +9.31
```

### 85.2 首轮（初步、非结论）观察

1. **方差不在网络相**：search/read 几乎不动（+0.35/+0.46）⇒ 宿主/网络不是 admission 漂移的主因（与 §47/§70 记录一致）。
2. **方差集中在模型调用相**：selector/assessment/extraction 各贡献约 +4.1~4.4s。但需区分"调用数变多"与"单次变慢"——ledger 已记录 calls，下一步按 calls 归一。
3. **B1 自身不是主因**：慢 run 的 B1 段更短（-3.3s），说明 admission 晚是**前面阶段累积**的结果，而非 B1 内部变慢。
4. `unattributed` 4.1-8.2s（约 research 的 13-18%）：主要应为 refresh/steering、checkpoint 持久化，以及 phase_seconds 覆盖不到的等待。

### 85.3 按 §F2 完成门还缺什么

| 门 | 现状 |
| --- | --- |
| >=3 fast + >=3 slow | 边界上（fast: r5/r2/gate2b；slow: sanity5/f8/node-gate2 约 34.0） |
| >=80% 方差归因 | **未达**：命名相合计覆盖约 87%，但**调用数 vs 单次延迟**未分离，per-wave 归属缺失 |
| 成本类别（CPU/模型/网络/宿主 retry） | 部分：模型相已命名；网络相稳定；retry 计数有、**retry 等待秒数缺失**；CPU 未测 |
| 可回收时间测算 | 未做（需先分离 calls x latency） |
| 不改任何策略 | 全程只读 |

**下一步仪器（纯观测）**：
- (a) 在 phase 上补 **model_wait 与 network_wait 分解** + **retry 等待秒数**（read_retry 增加延迟累计）；
- (b) 补 **per-wave 时间线**（`metrics.wave_timeline[]`：wave_index/t_start/t_end 与各相耗时），用于区分"wave 1 拖长"与"wave 2 拖长"。


## §86 F2-S1 仪器落地与首批 cohort（`42a685d2` → `7e21b842`）

### 86.1 仪器（纯观测，未改任何 counts/timeout/selector/retry/budget/ranking/scheduling）

- `src/web/research/timing_ledger.py`：**exclusive span** 记账 + 统一单调时钟（run 的 `elapsed_ms`）；`wave_timeline[]` 作为父级账本。
- 已接线的 span：`search / assessment / read / extraction`（原有 phase）+ **新增 `domain_targeted`（B1）/ `tier2_proposal` / `late_tail` / `ranking` / `gating`**。
- **model wait 分解**：`TimedGateway` 透明包装模型网关，按 purpose 归到 `selector / assessment / extraction / planner / support / other`，记录 **calls / total / max** ⇒ 可区分"调用变多"与"单次变慢"。
- **retry 分解**：`read_retry` 新增 `retry_fetch_ms` 与 `retry_backoff_ms`（退避等待与真实重取分离；修过一个单位 bug：原为秒却标 ms）。
- **refresh/checkpoint 显式 span**：`refresh_steering_ms` / `checkpoint_ms`（不再靠 unattributed 猜）。
- 语义纪律（按裁决）：子 span 为 exclusive；`model_wait` 是所属 phase 的**组成**不是叠加；`unattributed_ms = wave_wall − 互斥 span 合计`。
- 测试：`tests/test_timing_ledger.py` 9 项（exclusivity、model-wait 组成、retry 分离、refresh/checkpoint、wave 分离、隐式关闭、容错 exit、purpose 映射、属性委派）。

### 86.2 首批 cohort（7 runs，同一 schema）

| run | elapsed | admission | covered | unattr | ckpt | search | read | assess | domain_targeted | extract | retry(cnt/backoff/fetch) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| docker.c | 33.9 | — | 16.2 | 11.4 | 1.5 | 11.8 | 1.0 | 2.2 | — | 1.1 | 0 |
| docker.d | 42.1 | 30.8 | 30.7 | 4.4 | 2.3 | 11.7 | **10.2** | 3.4 | 2.9 | 2.2 | 3 / 2.0s / 0.3s |
| docker.e | 34.4 | — | 23.8 | 4.0 | 1.7 | 11.7 | 1.1 | 2.4 | **7.2** | 1.1 | 0 |
| docker.f | 37.8 | — | 28.1 | 2.7 | 1.1 | 11.4 | **10.9** | 2.3 | 3.5 | — | **6 / 9.0s / 1.9s** |
| node.b | 57.4 | 44.6 | 43.0 | 5.7 | 1.7 | 13.0 | **14.8** | 4.4 | 5.6 | 5.0 | 0 |
| node.c | 100.4 | 46.5 | 43.6 | 5.1 | 1.1 | 12.9 | **17.3** | 3.2 | 5.0 | 5.0 | 0 |
| node.d | 59.8 | — | 41.5 | 6.6 | 2.9 | 12.9 | **17.5** | 2.8 | 0.6 | 7.5 | 0 |

model waits（calls x total）：docker 系 `selector 3–4 x 1.75–2.61s`（≈0.6s/call）；node 系 `selector 4 x 3.81–4.11s`（≈1.0s/call）；`other 1 x 0.41–0.97s`（domain proposal）。

### 86.3 首批归因（初步，非最终）

1. **`search` 是最大且最稳定的成本**：11.4–13.0s，**跨 run 几乎不动**（网络/provider 相）⇒ 不是方差来源，但是绝对成本第一。
2. **`read` 是最大方差来源**：1.0s（docker.c/e）→ 10.2–10.9s（docker.d/f）→ 14.8–17.5s（node）⇒ 与"文档越多/越慢"一致，属网络+宿主相。
3. **retry 退避可成为独立成本类**：docker.f **6 次 retry / 9.0s 纯退避**（另有 1.9s 重取）⇒ 这是可直接回收的候选（属 B2/宿主策略域，非 selector）。
4. **selector 双因素**：node 系不仅调用更多（4 vs 3）且**单次更慢**（≈1.0s vs ≈0.6s）⇒ 若后续要动 selector，需先分清是"更多 claim/窗口"还是"prompt/延迟"。
5. **B1（domain_targeted）0.6–7.2s**，方差大但小于 read；**late_tail ≈0s**（多数 run 未触发或极小）；**tier2 ≈0**；**ranking/gating ≈0.1–0.2s**。
6. **refresh_steering ≈0s**（此前怀疑的 4–8s 未归因并不来自它）；**checkpoint 1.1–2.9s**（真实且此前完全未被计量）。
7. `unattributed` 2.7–11.4s：docker.c 的 11.4s 已解释（该 run 早于 span 命名补丁，wave 2 的 B1/tail/ranking 未命名）。

### 86.4 与完成门的差距

| 门 | 现状 |
| --- | --- |
| ≥3 fast + ≥3 slow（同 schema） | **未达**：目前 admission 有值的仅 docker.d(30.8)/node.b(44.6)/node.c(46.5) ⇒ 需再补若干 run（fast 与 slow 各 ≥3） |
| ≥80% 方差归因 | 接近：命名 span + model wait + retry 已覆盖绝大部分；`unattributed` 已降到 2.7–6.6s |
| 成本类别 | 已分：网络（search/read）、模型（selector/other）、宿主 retry（backoff）、持久化（checkpoint） |
| 可回收测算 | 已有候选：retry 退避（docker.f 9.0s）、read 方差（非策略可回收）、selector 单次延迟（待查） |
| 不改任何策略 | ✅ 全程只读 |

**下一步**：补跑到 admission 有值且覆盖 fast/slow 各 ≥3 的 cohort（预计 4–6 次 run），再出最终表并判断是否授权 F2 optimization。


## §87 F2-S1 最终 cohort（13 runs @ `2163caa`，同 schema）

补跑按裁决执行：4 次 + 允许的 2 次 = 6 次，全部冻结 `2163caa`（未改行为参数与 timing schema）。

### 87.1 cohort 计数与门的判定

```text
fast (admission < 35s)  = 1   （docker.d 30.8s）
slow (admission >= 35s) = 3   （node.b 44.6 / node.c 46.5 / node.e 46.6）
no_admission            = 9
```

**门未满足**：fast 侧 1/3。原因已定位且是**外部条件**：B1 admission 需要 docs.docker.com 的 sitemap/验证读取成功，而该宿主在本环境持续不可达（与 §71E cold gate 同一阻塞）；最近 5 次 docker run 的 `domain_targeted` span 都执行了（3.5–7.9s）但未产生可 admission 的候选。

### 87.2 fast vs slow（按已冻结定义，n=1 vs 3）

| 指标 | fast median | slow median | Δ |
| --- | --- | --- | --- |
| read | 10.2s | **17.1s**（14.8–17.3） | **+6.9s** |
| selector total | 2,423ms | **4,078ms**（3,922–4,110） | **+1,655ms** |
| selector **max single** | 750ms | **1,296ms**（1,187–1,750） | **+546ms** |
| selector calls | 4 | 4 | **0** |
| extraction | 2.2s | 5.0s | +2.8s |
| B1 domain_targeted | 2.9s | 5.6s | +2.7s |
| search | 11.7s | 12.9s | +1.2s |
| assessment | 3.4s | 3.2s | −0.2s |
| retry backoff | 2ms | 0 | −2ms |
| checkpoint | 2,312ms | 1,185ms | −1,127ms |
| unattributed | 4.4s | 5.1s | +0.7s |

**关键机制分离**：slow 侧 selector **调用数完全相同（4）**，但**单次更慢**（max +546ms，total +1.66s）⇒ node 的慢是**单调用延迟**而非次数膨胀（修正了 §86 的初步猜测——§86 看到的"6 calls"来自 docker.i 的偶发，不是 slow 侧特征）。

### 87.3 全 cohort 结构结论（13 runs，不依赖 admission）

| 成本源 | 观测 | 判断 |
| --- | --- | --- |
| `search` | 11.3–13.1s（极紧） | **固定税/floor**；非方差源 |
| `read` | **1.0–17.5s（17×）** | **首要方差源**；与文档体量/宿主相关，尚不能称"可回收" |
| selector 单次 | max 687–1,750ms（2.5×） | 结构性候选（**慢 run 是单次延迟问题**） |
| retry backoff | 8 run 为 0；docker.f/h/k 分别 **9.0s / 3.0s / 7.0s** | **偶发但可完全回收**的独立成本类 |
| B1 | 0.0–7.9s | 波动大；受宿主可达性支配 |
| extraction | 0.0–7.5s | 与 read 量相关 |
| checkpoint | 936–2,891ms | 真实稳定成本，非主矛盾 |
| refresh / tier2 / late_tail / ranking / gating | ≈0 | **排除** |
| unattributed | 2.7–11.4s（11.4 属 span 命名前样本；命名后 2.7–6.8s） | 已足够好；**不再为账本完美加仪器** |

### 87.4 结论与待裁决

1. **F2-S1 的仪器目标已达成**：把"慢"从单一 elapsed 拆成可操作结构，且已定位两类明确机制（read 方差、selector 单次延迟）+ 一类可回收成本（retry 退避 9s 级）。
2. **统计门未完全满足**（fast 1/3），阻塞为外部宿主可达性，非仪器或行为问题。
3. 两条路径（待裁决）：
   - **(A) 等宿主恢复补 2 次 fast admission**（最严格；与 §71E 同一恢复窗口，可一并补）；
   - **(B) 以 13-run 结构结论授权 F2 optimization**，把 fast/slow 中位数视为方向性证据（n=1 vs 3 已给出 read +6.9s / selector 单次 +546ms 的一致信号），并约定优化后回到同 schema 复测。
4. 若授权优化，建议顺序（按可回收性与证据强度）：**retry/backoff 可回收性验证 → selector 单次延迟结构 → read 慢路径 → checkpoint；`search` 暂不碰**。
5. **不授权**任何行为改动前，`§71E` 与 `F2 optimization` 均保持未开启。


## §87.5 裁决落定：F2-S1 封板 + F2 optimization 授权（F2-O1 开始）

**F2-S1 状态**：`CHARACTERIZATION COMPLETE WITH EXTERNAL-GATE EXCEPTION`

```text
原计划统计门: fast >= 3 && slow >= 3
实际:         fast = 1 / slow = 3 / no_admission = 9
未达原因:     docs.docker.com 持续不可达 ⇒ B1 admission 系统性缺失
补跑额度:     4 + 2 已耗尽；不再追加 cold/fast hunt
共享债务:     §71E natural-cold rescue 与 F2 fast cohort 由**同一外部 host
              availability condition** 阻塞 —— 这是一个 shared external
              evidence debt，不是两个独立工程 blocker
恢复窗口:     宿主恢复时与 §71E 共用窗口补（§71E cold rescue + F2 2 个 fast admission）
             补证据不追溯阻塞当前 F2 optimization；优化后必须用同一 timing schema 复测
```

**撤掉 §86 的一个旧判断**：`selector calls↑` **不是** slow cohort 的机制。现有证据是 **calls 固定为 4，而 latency/call 上升**（max +546ms、total +1.66s）——问题因此更干净。

**n=1 vs 3 的 fast/slow 表**：仅作**方向性证据**，不作为因果结论；授权依据是 13-run 内**不依赖 admission** 的结构性证据。

**F2 optimization 顺序（冻结）**：

```text
O1 retry/backoff recovery   ← 当前唯一执行切片
O2 selector 单调用延迟
O3 read slow path
O4 checkpoint
search = characterization-only（不进入本轮优化）
```

**F2-O1 的问题定义（冻结）**：不是"删 backoff"，而是回答——

> 这 3–9 秒 sleep 中，哪些是在系统已经不可能从该 retry 获得有效结果时仍然支付的？

即优化目标是 **消灭没有边际恢复价值的 backoff，而不是消灭 retry**。要回答：每次 attempt 的失败类型；第 N 次 retry 是否真的 rescue；retry 前后错误是否完全相同；对确定性/永久失败是否仍完整 sleep；backoff 是否已跨过剩余 deadline/budget；哪一级 retry 产生了 useful result。

允许的 instrumentation 必须克制：**只记录 retry outcome/reason**，不再建设第二套 profiler；若现有日志已能回答则不加。


## §88 F2-O1：retry/backoff 的"恢复收益 vs 纯等待成本"（`f92b48e8` → `abd50e68`）

### 88.1 允许的克制仪器（按裁决：只记 retry outcome/reason）

- qualification 工具新增 **per-read retry provenance** 投影（attempts/retries/skipped/reasons/fetch_ms/backoff_ms/admission_reasons）——此前该字段被投影丢弃，导致"哪一次 retry 救活"无法回答；
- `_source_record` 的 per-read 副本补齐同样的成本字段；
- `_accumulate_fetch_metrics` 汇总 `retry_backoff_ms` / `retry_fetch_ms`（此前汇总里恒为 0，属真实记账缺口）。
- **没有**新建第二套 profiler；其余一律复用既有 ledger。

### 88.2 结论（7 次 retry-bearing reads，per-read 归因）

| 指标 | 值 |
| --- | --- |
| 有 retry 的读取 | 7 |
| **retry 后成功（rescued）** | **0 / 7** |
| retry 后仍失败 | **7 / 7** |
| **错误签名完全相同**（前后都是 `URLError WinError 10054`） | **7 / 7** |
| 退避总时长 | **12,000ms** |
| **其中花在最终失败读取上的** | **12,000ms（100%）** |
| 单次退避样本 | 3,000ms/read（1s+2s，命中 schedule 上限） |
| 另见 | 一次 `retries=0, skipped=1, fetch_ms=11,031`（单次 11s 抓取，retry 被窗口门拒绝） |

**回答 O1 的问题**：在本 cohort 中，**没有任何一次 retry 产生边际恢复价值**；每次 retry 都复现同一个确定性连接错误，而 **12.0s 退避全部支付在最终失败的读取上**。retry 的成本真实（≈3s/read 退避 + 1.7s 重取），恢复价值观测为零。

### 88.3 必须同时记录的两个边界

1. **样本偏向**：7 个 read 全部落在本环境当前不可达/不稳的宿主（docs.docker.com、www.docker.com、github.com）。在健康宿主上 retry 的恢复价值**未被本批否定**。
2. **§49 需要重新解释**：§49 曾测得 retry 使读成功率 1/4 → 5/8。那是**聚合口径**；本次 per-read 归因显示"失败 read 从未被 retry 救活"，因此 §49 的改善很可能来自**不同候选**而非"retry 救活同一次读取"。记为对旧结论的口径修正（不是回归）。

### 88.4 候选最小修法（待裁决，未实现）

按 O1 的目标（"消灭没有边际恢复价值的 backoff，而不是消灭 retry"）：

- **候选 A（最窄）**：当本次失败签名与上一次 attempt **完全相同**时，**跳过退避 sleep**（仍立即重试，attempt 次数与准入策略不变）⇒ 观测上可回收最多 3.0s/read，同时保留即时重试的恢复机会。
- **候选 B**：把退避改为**窗口感知**（若 `sleep + 预计 fetch` 超过剩余窗口则直接跳过退避/跳过 retry）——与既有 window-aware admission 同族，但作用于 sleep 本身。
- **候选 C**：确定性错误分类（如 `WinError 10054` 属"连接重置"）后**直接降低 retry 上限**（更激进，需更多证据）。

倾向 **A（或 A+B 组合）**：保留 retry 语义、只删"确定无收益的等待"，且可用同 schema 复测（退避 ms → 0、read 结果与成功率不变）。

**注意**：本节只给出结论与候选，**未改动任何行为**；retry policy 仍为 §49 冻结形态。


## §89 F2-O1b 实现与复测：A′ + B（`dcb4a057` → `841224ef`）

### 89.1 实现（范围按裁决锁死）

- **A′（纯 timing）**：第一次失败仍支付 §49 冻结的 1s backoff；当**下一次失败的规范化错误签名与上一次完全相同**时，其后的等待被抑制（attempt 仍会执行）。
  - 签名 = `error_signature()`：保留失败种类标记 + 数字 errno/WinError（若存在），否则取消息首段；**不硬编码任何具体错误码**（无 `10054` 特判）。
  - 上限即裁决修正后的 **2s/read**（首次失败无可比较对象）。
- **B（deadline-preserving retry suppression）**：仅当 `planned_backoff + expected_fetch <= remaining_window` 才发起 retry；`expected_fetch` **复用上一次 attempt 自身耗时**（无新建 latency estimator），窗口来自 runtime 的 `research_seconds_left`。
- **provenance 分离**：`backoff_suppressed_reason = repeated_error_signature`、`retry_suppressed_reason = insufficient_remaining_window`、`suppressed_backoff_ms`（per-read + aggregate）。
- 未做 C；未改 retry ceiling / selector / read timeout / candidate / ranking；未加新 profiler。
- 修掉实现中一个单位 bug（`fetch_ms` 内部为秒，B 的估算曾误除 1000）。

### 89.2 in-situ 效果（2-retry 且签名相同的 read）

| cohort | n | 实付 backoff | 抑制 backoff | attempts/retries |
| --- | --- | --- | --- | --- |
| before（O1/F2S1） | 7 | **12,000ms** | 0 | 3 / 2 |
| after（O1b） | 6 | **6,000ms** | **6,000ms** | 3 / 2 |

单 read 对照（字段齐全样本）：before = 3,000ms 实付；after = 1,000ms 实付 + 2,000ms 抑制 ⇒ **恰好 −2,000ms/read，与裁决修正的上限一致**，且 **attempt/retry 数不变**、read 结果不变（failed→failed、read→read）。

### 89.3 等价性复测（同 schema）

| 指标 | before（18 runs） | after（8 runs） |
| --- | --- | --- |
| read 成功 / 总 read | 21 / 45（0.47） | 7 / 11（0.64） |
| eligible evidence 合计 | 34 | 8 |
| gate=pass | 0 | 1 |
| 实付 backoff 合计 | 3,000ms | 3,000ms |
| 抑制 backoff 合计 | 0 | 6,000ms |

⇒ **结果集合无恶化**（小样本比例更高，非退化）、admission 未恶化（`skipped_due_to_budget` 仍按原语义触发）、repeated-error idle 明显下降（−6,000ms）。

**B 的 in-situ 触发**：本批复测未出现"sleep + 预计 fetch 超出剩余窗口"的样本（`window_suppressed=0`），因此 B 目前只有确定性测试覆盖（拒发/放行/估算来源三例）。记为待补的 in-situ 证据，不阻塞 O1 收口。

### 89.4 §49 口径修正（落档，按裁决措辞）

> 启用 §49 后聚合读成功率从 1/4 提高到 5/8；**新的 per-read provenance 表明当前可重建样本中没有失败 read 被 retry 转为成功**，因此旧实验不能把聚合提升**因果归于 same-read retry rescue**——提升可能来自候选集合/后续读取机会等其它机制。这不是推翻 §49，而是把相关性陈述降级为正确的因果口径。

### 89.5 O1 收口判定

| O1b 验收 | 结果 |
| --- | --- |
| 结果集合不变 | ✅（read 成功/失败集合与 before 同构，无退化） |
| admission 不恶化 | ✅（窗口语义不变，`skipped_due_to_budget` 正常） |
| repeated-error idle 明显下降 | ✅（−2s/read，实测 −6,000ms 合计） |
| window-overrun retry 被正确抑制 | ✅ 确定性测试；in-situ 待补 |

⇒ **F2-O1 CLOSED**（B 的 in-situ 触发记为待补证据）。下一刀：**F2-O2 selector 单调用延迟**（已知 calls 固定为 4、单次 687–1,750ms；先按 purpose/输入规模拆，判断是否本地可优化）。


## §90 F2-O2 selector 单次延迟可控性判定（characterization only，`1fad8d2`）

**问题**：selector 的 687–1,750ms 波动，是"输入规模/调用位置导致"还是"外部 gateway/model latency 抖动"？

**范围锁**：本刀**不改 selector 行为**；**不以"把 selector calls 从 4 降到 3"为目标**（§87 已证主要现象不是次数膨胀）。

### 90.1 仪器（无 tokenizer、无新 profiler）

`SelectionAuthorityDiagnostics` 增加单次调用的分解字段：`input_chars`（实际发出的字符数）、`response_chars`、`input_tokens`、`output_tokens`、`model_wait_ms`（gateway 调用本身）、`local_residual_ms`（wall − model wait）。
- token **直接复用 gateway 既有 per-call audit**（provider 返回 usage 时），不引入 tokenizer；缺失时才退化到 chars。
- 运行时记录经既有 `**diagnostics.to_dict()` 自动带出，无额外接线。
- 分析器 `tools/run_f2_o2_selector_latency.py`（只读）：抽取 per-call 行（run/host/wave/position/purpose/candidates/sizes/tokens/wall/model wait/residual）并输出 `latency ~ input size`、`latency ~ position`、`latency ~ purpose` 与 residual 稳定性。

### 90.2 样本（`O2.*`，6 runs / 33 次 selector 调用）

| 维度 | 值 |
| --- | --- |
| wall latency | mean **848ms**，stdev **258ms**，min 406，max 1,593 |
| model wait | mean **848ms**，stdev **258ms**（与 wall 完全相同） |
| **local residual** | mean **0ms**，max **0ms**，`wall == wait` **33/33** |
| 输入规模 | input_chars 764–2,051（mean ~1,500）；candidates 1–5；input_tokens 430–663 |
| 输出规模 | response_chars 157–390；output_tokens 32–85 |

**双仪器交叉验证**：per-call `model_wait_ms` 按 wave 求和，与独立 `TimedGateway` ledger 的 `model_wait_ms.selector` 在全部 **18 个 wave** 上一致（差 0–2ms）⇒ 两个独立测量互相印证，per-call 分解可信。

### 90.3 三个关系

| 关系 | Pearson | 斜率 | 判读 |
| --- | --- | --- | --- |
| latency ~ input_chars | **0.215** | 0.127 ms/char | 弱（≈5% 方差）；砍 1,600 字符才换 ~200ms |
| latency ~ candidates | **0.217** | 35.9 ms/candidate | 弱；5 个候选差 ≈180ms |
| latency ~ position | **−0.186** | −22.6 ms/位 | **无位置效应** |
| latency ~ response_chars | **0.59** | 1.21 ms/char | **最强**；即输出长度（provider 生成时长） |

按位置均值：828 / 974 / 898 / 893 / 505 / 942 / 703 / 789 ms ⇒ **无单调趋势**（位置 5/6 的 n 仅 3，不做结论）。
按 host：current_policy 747ms（n=19）vs historical_current_mix 985ms（n=14），但 input_chars 均值也不同（1,430 vs 1,659），**混杂，不作为独立证据**。
purpose：selector 记录只有 `research_selection_authority` 单一值（`research_domain_proposal` 属另一调用面，不在 O2 范围）。

### 90.4 wall − model_wait 是否稳定

**完全稳定**：33/33 次调用 residual = 0ms（毫秒分辨率），`Var(wall) = 66,354`、`Var(model_wait) = 66,354`、`Var(residual) = 0` ⇒ **波动 100% 来自外部 model/gateway 等待**，本地 selector 路径（payload 构造 + 序列化 + 派发）**亚毫秒级**。

### 90.5 判定（按预设门）

| 门 | 观测 | 结论 |
| --- | --- | --- |
| wall 波动随 model_wait 走、本地 residual 稳 | ✅ residual 33/33 = 0ms | **命中第一分支** |
| latency 明显随 candidate/input size 增长 | ✗ r ≈ 0.22（弱） | 不进 O2b |
| 某 position/purpose 稳定更慢 | ✗ 无单调趋势 | 不追路径 |
| calls 固定但 residual 自身抖动 | ✗ residual 恒 0 | 不拆本地路径 |

⇒ **判定：`external_latency_not_locally_recoverable`。F2-O2 CLOSED，不做优化。**

**理由（非"无法优化"而是"优化不在本地"）**：selector 的 406–1,593ms 全部是外部模型/网关等待；本地路径 <1ms；唯一可解释项是输出长度（r=0.59，即 provider 生成时长），而输出仅 32–85 token（max_tokens 已 500），**没有可回收的本地余量**。缩 payload 的期望收益上界约 0.127 ms/字符，且 r=0.215 说明大部分输入规模差异并不转化为延迟。

**唯一留档的观察（非行动项）**：host 间 747 vs 985ms 的差异与输入规模混杂，若将来要降低 selector 延迟，方向是**减少候选池规模（上游）**而非改 selector 代码；按 O2 边界**不作为默认目标**。

### 90.6 路线状态

```text
F2-S1 ✅
F2-O1 ✅   └─ B in-situ evidence debt（不阻塞）
F2-O2 ✅   └─ external latency, not locally recoverable（本刀）
F2-O3 ← 下一刀：read slow path
F2-O4    └─ checkpoint
F2 final validation
```


## §91 F2-O3a read 延迟分解：网络主导，本地后处理 0.8%（`a3ec9e3`）

**冻结问题**：`read 1.0–17.5s` 的 17× 方差，来自"做了更多 read 工作"还是"同样的 read 工作在网络/远端等待更久"？

**范围锁**：characterization only。**未改** timeout、并发、reader、fallback、circuit breaker。

### 91.1 仪器（复用现有 HTTP 边界，未重造 profiler）

- `read_retry` 新增 **`attempts_detail`**（仅对发生 retry / 被拒 retry 的读取发出）：每 attempt 的 `index / fetch_ms / ok / signature / chars / content_type`。成功的 attempt **不带签名**（否则会被 A′ 误判为"同一失败再现"）。干净的单次成功读取**保持原 payload 形状不变**。
- 运行时新增 **`read_timing`** 通道（独立诊断，不参与调度/准入/策略）：把一次 read 的 wall 拆成
  `fetch_ms`（网络/远端等待：有 retry 时用 retry 循环自身的 fetch 总和（其时钟覆盖首次 attempt），否则用整次 read 调用）
  + `backoff_ms` + `escalation_ms` + **`local_ms`**（decode/parse/bookkeeping 等读取后处理），并带 host/wave/status/attempts/retries/chars/error_signature。
- 分析器 `tools/run_f2_o3_read_latency.py`（只读）。

### 91.2 样本（6 runs / 19 reads；uv 两 run 因 0 read 被跳过）

| artifact | reads | attempts | ok | wall 总 | fetch 总 | local 总 | retry_fetch | fetch 均值 | fetch 最大 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O3.docker.a | 1 | 3 | 0 | 1,594 | 531 | 63 | 531 | 531 | 531 |
| O3.docker.b | 1 | 2 | 1 | 2,547 | 1,531 | 16 | 1,531 | 1,531 | 1,531 |
| O3.docker.c | 3 | 5 | 1 | 1,531 | 469 | 62 | 235 | 156 | 235 |
| O3.docker.d | 2 | 4 | 2 | 2,344 | 1,313 | 31 | 1,282 | 656 | 1,282 |
| O3.node.a | 5 | 5 | 4 | 5,953 | 5,953 | 0 | 0 | 1,191 | **3,672** |
| O3.node.b | 7 | 7 | 6 | 6,626 | 6,626 | 0 | 0 | 947 | **3,750** |

pooled（19 reads）：wall mean 1,084 / median 578 / max 3,750 / 总 20,595；**fetch 总 16,423（占 wall 79.7%）**；**local 总 172（占 0.8%，max 63）**；backoff 总 4,000（19.4%）。
方差：`var_wall 1,360,374`、`var_fetch 1,162,059`（**85.4%**）、`var_local 333`（0.02%）；`corr(wall, fetch) = 0.928`、`corr(wall, local) = 0.228`。

### 91.3 四个问题

**1. read wall 是否主要跟 Σ fetch_ms 一起涨？** **是。** fetch 占 wall **79.7%**、占方差 **85.4%**、`r = 0.928` ⇒ 网络/远端等待主导。

**2. fetch 接近但 read wall 差很多？** **否。** 19 次读取的 local 后处理**合计仅 172ms**（max 63ms，占 0.8%）。**不存在本地 parse/extraction 问题**，不值得继续拆本地路径。

**3. slow 是"单个 read 特别慢"还是"read 数量更多"？** **两者分别成立，且按 host 分型：**
- node 类 run：**read 数量**驱动（5 / 7 reads × 约 0.9–1.2s 均值）；
- docker 类 run：**read 数量少（1–3）但 attempts 多（2–5）**，per-read 等待 + retry 驱动（retry_fetch 235–1,531ms）；
- 单次 fetch 最大 **3,750ms**（nodejs.org，仅 1,497 字符）。

**4. bytes 能否解释 latency？** **否。** `corr(fetch, chars) = 0.135`。反例：nodejs.org 1,497 字符 → 3,750ms；nodejs.cn 6,000 字符 → 969ms。

### 91.4 集中度（host / 错误签名）

| host | reads | 失败 | fetch 均值 | fetch 最大 |
| --- | --- | --- | --- | --- |
| **nodejs.org** | 2 | 0 | **3,711** | 3,750 |
| www.docker.com | 5 | 3 | 738 | 1,531 |
| nodejs.cn | 4 | 0 | 660 | 969 |
| node.org.cn | 2 | 0 | 617 | 656 |
| juejin.cn / www.runoob.com | 1 / 1 | 0 | 532 / 515 | — |
| zhuanlan.zhihu.com | 2 | **2** | 118 | 125 |
| docs.docker.com | 2 | 0 | 78 | 125 |

**nodejs.org 用 10.5% 的读取占据 45.2% 的全部网络等待**（`top_host_fetch_share = 0.452`）。
失败签名：`urlerror#10054`（n=3，均值 292ms）、`exception#403`（n=2，均值 118ms）。

### 91.5 判定

| 门 | 观测 | 结论 |
| --- | --- | --- |
| read wall 随 Σ fetch 涨 | ✅ 79.7% / 85.4% / r=0.928 | **网络主导** |
| fetch 接近但 wall 差很多（本地问题） | ✗ local 仅 0.8% | 排除 |
| bytes 解释 latency | ✗ r=0.135 | 排除 |
| 需要 O3b（同 host 同 bytes 同 outcome 但 fetch 仍有巨大未解释方差） | ✗ 同 host 重复读数一致（nodejs.org 3,750 vs 3,672，差 78ms；nodejs.cn 594/660/969） | **不做 O3b** |

⇒ **判定：`network_dominated`。**
**结论一句话**：read 的 17× 方差**主要来自"同样的 read 工作在网络/远端等待更久"**，而不是"做了更多 read 工作"；本地读取后处理可忽略（0.8%，max 63ms）。

**不做 O3b**：DNS/connect/TTFB/body 微观拆分的前提（同 host、同 bytes、同 outcome 仍有巨大未解释 fetch 方差）不成立——同 host 重复读数彼此接近，方差集中在 **host 身份**与**失败路径**上，而不是同一 host 内部的网络阶段噪声。

### 91.6 对后续路线的含义（记录，非本刀行动）

- 长尾是 **host 形状**的（少数不可达/不稳定 host + 403/WinError 10054 失败路径），**不是 reader 算法问题** ⇒ 与 §71C 系列一致，这属于 **failure-policy / timeout / circuit-breaker** 层，正是 **P2-A 外部功能接入改造**的范围。
- 本刀**未调任何 timeout**，机制已认清：`read wall ≈ fetch`（local ≈ 0），所以"缩短 read 时间"只能通过**减少等待/提前放弃**实现，而不是通过优化本地代码。
- 另一个可量化事实：docker 类 run 的 read 时间里 **19.4% 是 retry backoff**（4,000ms/19 reads），O1b 的 A′ 已回收其中一部分。

### 91.7 路线状态

```text
F2-S1 ✅
F2-O1 ✅   └─ B in-situ evidence debt（不阻塞）
F2-O2 ✅   └─ external provider latency（selector）
F2-O3 ✅   └─ O3a: network-dominated, local 0.8%；不做 O3b
F2-O4 ← 下一刀：checkpoint
F2 final validation
```


## §92 F2-O4a checkpoint 成本分解：非体量驱动、无重复、写 I/O 长尾（`86cdcd9` → `3b9c6a1`）

**冻结问题**：checkpoint 的 0.9–2.9s，是"每次都必须付的持久化成本"，还是"重复写 / 写得太频繁 / 可以合并"的成本？

**范围锁（已遵守）**：**不允许以降低 durability / crash recovery 语义换性能**。本刀**未**改 checkpoint 频率、写格式、恢复语义；**未**做 debounce / coalescing / skip。

### 92.1 仪器（只用既有边界，无新 profiler）

- `WebLookupRepository.checkpoint` 新增**可选** `diagnostics` 汇（默认 `None` ⇒ 其它调用方行为完全不变），报告：`repo_ms`（方法整体）、`load_ms`（乐观并发读，含**写后重读**，每次都会反序列化上一版整行 JSON）、`serialize_ms`、`write_ms`（含 `sqlite3.connect()` + `execute` + commit 的整段）、`repo_other_ms`、每 section 序列化字节数 + 短身份哈希、`attempts` / `conflicts`、写目标数。循环不变量 section 改为**在重试循环外序列化一次**（原先每 attempt 重算）。
- 运行时新增 `checkpoint_timing` 通道：`ordinal / wall_ms / caller / phase / stage / since_previous_ms / bytes_by_section / changed_sections / changed_bytes / unchanged_bytes / prep_ms`（= wall − repo 调用）。与上一次的比较**只按 section 身份哈希**，**不保存任何 checkpoint 内容**。
- `TimingLedger.current_phase()` 暴露当前打开的最内层 phase。
- 分析器 `tools/run_f2_o4_checkpoint_cost.py`（只读）。

### 92.2 样本

- 粗粒度：8 runs / **745 checkpoints**。
- 完整分解（`3b9c6a1` 之后，含 `load/prep` 字段）：**4 runs / 327 checkpoints**。

| artifact | ckpts | wall 总 | mean | median | max | write 总 | 字节总 | unchanged | 全重复 | 占 run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O4.docker.c | 76 | 3,560 | 47 | 16 | **1,141** | 2,139 | 6.57M | 724K | 0 | 11.4% |
| O4.docker.d | 76 | 1,608 | 21 | 16 | 47 | 603 | 6.56M | 709K | 0 | 5.7% |
| O4.node.c | 90 | 1,889 | 21 | 16 | 47 | 824 | 11.3M | 1.50M | 0 | 3.4% |
| O4.node.d | 85 | 1,763 | 21 | 16 | 62 | 717 | 10.1M | 1.37M | 0 | 3.1% |

### 92.3 分解（327 checkpoints，合计 8,820ms）

| 组成 | 合计 | 占 wall |
| --- | --- | --- |
| `prep_ms`（executor 侧：budget 更新 / cursor 与 claim-engine 附加 / known-evidence 快照 / metrics 更新） | 1,252 | **14.2%** |
| `load_ms`（乐观并发读 + 写后重读） | 2,903 | **32.9%** |
| `serialize_ms` | 262 | **3.0%** |
| `write_ms`（connect + UPDATE + commit） | 4,284 | **48.6%** |
| `repo_other_ms` | 48 | 0.5% |
| 仪器开销（`hash_ms`） | — | 0.4% |

相关性：`wall~write = 0.975`、`wall~bytes = −0.057`、`serialize~bytes = 0.947`、`write~bytes = −0.097`。

### 92.4 四个问题

**1. wall 是否随 bytes 增长？** **否。** `wall~bytes = −0.057`。字节量只驱动序列化（`r=0.947`），而序列化仅占 3.0%。⇒ **不是体量成本**。

**2. 相邻 checkpoint 是否大量重复？** **否。** 327 次中**全重复 = 0**；字节级 `unchanged_share = 12.4%` ⇒ **约 88% 的写入内容确实变了**。⇒ 没有可观的合并/增量空间。

**3. 触发频率是否过高？** **频率确实高**（76–90 次/run；相邻间隔 median **31ms**、p10 **15ms**、min 0ms），**但每次内容确实变化**（见问题 2）⇒ 合并 = 丢弃真实状态变化 = **降低 durability**，被本刀冻结约束禁止。

**4. 慢点在 serialize 还是真正 I/O？** **I/O + 读回**（write 48.6%、load 32.9%、serialize 3.0%）。**序列化不是慢点** ⇒ 不要优化对象构造/编码。

### 92.5 写 I/O 长尾

`write_ms`：median **7.8**、p90 9.7、p99 **16.0**、max **848.1**；仅 **2/327** 次 >50ms，而这 2 次占**全部写时间的 36.6%**。且 `write~bytes = −0.097`（与体量无关，内容规模稳定 ~106KB）⇒ **宿主/文件系统长尾，不是本地逻辑**。

### 92.6 判定

| 分支 | 观测 | 结论 |
| --- | --- | --- |
| 必要且体量驱动 | ✗ wall~bytes ≈ 0 | 否 |
| 高重复 + 高频 | 高频 ✓ **但重复 ✗（0 全重复，88% 真变化）** | 否（且合并违反冻结约束） |
| 单次 serialization 占比高 | ✗ 仅 3.0% | 否 |
| 写 I/O 抖动但内容规模稳定 | ✅ median 7.8 / max 848 / 与体量无关 | **命中 → 宿主/FS 成本，非本地优化** |
| 真实但贡献小且无明显重复 | ✅ 1.6–3.6s/run = **3.1–11.4% of run**；0 重复 | **命中 → 关闭 O4** |

⇒ **判定：`small_and_not_clearly_redundant` + `write_jitter = true`。F2-O4 CLOSED，不做优化，不开启 O4b。**

### 92.7 记录为债务（不作为行动项）

1. **写 I/O 长尾**：2/327 次写占 36.6% 写时间、max 848ms，且与体量无关 ⇒ 宿主/文件系统层，不属于本地逻辑优化面。
2. **写后重读**：`checkpoint` 末尾以 `self._required(run_id)` 重新读取并反序列化刚写入的整行（`load_ms` 32.9% 的一部分，约 4ms/次）。**理论上可回收**（可用刚写入的值直接构造返回值），但该路径是乐观并发/durability 敏感区，收益约 4% run 时间 ⇒ **记为债务，不动**。
3. **高频 + 真变化**：合并 checkpoint 属于 durability 权衡，被冻结约束排除 ⇒ **显式非目标**。
4. **新关联（重要）**：checkpoint wall 占 §87 `unattributed_ms` 的 **38.8%–66.4%**（0.664 / 0.525 / 0.405 / 0.388）⇒ §87 的 "unattributed 2.7–6.8s" **有相当一部分就是 checkpoint 持久化**，不是未知黑洞。且 **276/327（84%）的 checkpoint 发生在无打开 phase 的时刻**（wave 边界/span 之间），与其落在 unattributed 一致。

### 92.8 路线状态

```text
F2-S1 ✅   F2-O1 ✅(B evidence debt)   F2-O2 ✅   F2-O3 ✅(O3a, 无 O3b)   F2-O4 ✅(O4a, 无 O4b)
F2 final validation ← 下一刀
↓
P2-A external functionality / failure-policy / circuit-breaker
```


## §93 F2 FINAL VALIDATION — 全绿，F2 CLOSED（head `eb120930`）

**范围**：严格收口，**不新增实验面**；`--runs 3` 足够，**不设性能收益硬阈值**（provider / host / FS / docs.docker.com availability 均足以污染跨批次 elapsed 比较）。

### 93.1 门禁结果

| # | 门 | 结果 |
| --- | --- | --- |
| 1 | full pytest | **2152 passed / 2 failed**（664s） |
| 1b | 失败 1、2 | `…exact_head_guard[run_rq1c_protocol_probes_core.py]`、`…deterministic_protocol_runner_exercises_all_required_probes` —— **已知 Windows-local 平台失败**，与 `fc50845` / `480cd4e` baseline 同类 |
| 1c | Ruff（src/tests/tools） | All checks passed |
| 1d | `git diff --check` | clean |
| 1e | tracked 工作树 | clean |
| 2a | d40.2 `gate` | **pass** |
| 2b | d40.2 `answer_claim_binding` | **3/3 ok**，`fail_closed_rate 0.0`，`non_empty_candidate_rate 1.0` |
| 2c | d40.2 `publish` | **substantive 1.0** |
| 2d | d40.2 `consistency` | 该 capture 不含 consistency 报告；**F2 区间内 answer 路径改动文件数 = 0**（见 93.3）⇒ 不变量由构造保持 |
| 2e | retry ceiling / admission / selector / ranking / durability 语义 | focused 全绿（`test_read_retry` 17、`test_fetch_retry_admission`、`test_selection_authority` 21、`test_timing_ledger`）；F2 区间未触及 ranking / answer / gate 模块 |
| 3a | d40.2 frozen replay `--runs 3` | 3/3 完成，`gate=pass`，binding 3/3 ok，publish 1.0 |
| 3b | runtime frozen replay `--runs 3`（node case，固定 head/schema/配置） | **3/3 `gate=pass`**、`runner_error_type` 空、`timing_schema=f2-wave-timeline-v1` |
| 3c | instrumentation 正常产出 | `read_timing` 5 行/run、`checkpoint_timing` 90 行/run |
| 3d | timing ledger 闭合 | **全部 wave `covered_ms + unattributed_ms ≈ duration_ms`**（3/3 run） |
| 3e | retry provenance 正常 | 见 93.2 |
| 4a | O1 repeated-identical-failure 回归 | `test_read_retry` 全绿：attempt/retry 数不变、首次 1s backoff 保留、后续 2s 正确 suppression（`repeated_error_signature`） |
| 4b | O1 B window guard | 确定性测试全绿（拒发 / 放行 / 估算来源） |
| 4c | B in-situ evidence debt | **继续留档，不阻塞** |

### 93.2 两处需要精确说明的观测（均**非** F2 回归）

1. **retry provenance 在最终 head 的落点**：最终 head 的 node replay **无 retry**（宿主可达），docker replay 该次亦无 retry，因此 retry provenance 由**同一生产代码**的 `3b9c6a1f` cohort 证明（`git diff 3b9c6a1f..eb120930` 中 `src/` 改动为 **0**，仅 docs + 一个测试期望 + 一个分析工具）。该 cohort 中 `attempts=2/retries=1/retry_backoff_ms=1000`（A′ 生效形态）与 O1b 结论一致。
2. **per-attempt 明细的落点**：`attempts_detail` 由 **`metrics.read_timing[].attempts_detail`** 承载（O3a 证据完整，例如 `urlerror#10054` ×3 逐 attempt `fetch_ms` 78/79/78）；`sources[].read_retry` 按既有约定只投影 bounded summary，**不含** `attempts_detail`。这是设计选择，非缺失。
3. **跨 head 恒定、非回归的两项**（已用 cohort 对照确认）：
   - `model_call_budget_exceeded`：自 `42a685d2`（F2-S1）起在所有 node cohort 中一致出现（node case 的 domain proposal + selector + planner 调用超过 qualification guard 上限），属既有形态；
   - `answer_claim_binding = rejected`（`candidate_unavailable` / `empty_producer_output` / `missing_evidence_brief`）：自 `dcb4a057` 起 **18/18 run** 一致，且 `answer_status` 恒为 `available` ⇒ 用户可见语义跨 head 不变；d40.2 frozen replay 另行证明 binding 路径在给定 gate-pass capture 下 3/3 ok。

### 93.3 F2 区间改动面（`480cd4e..HEAD`，`src/`）

`active_research_runtime.py`（诊断通道 + B2 escalation 接线）、`web_lookup_repository.py`（可选 diagnostics + 循环不变量序列化外提）、`read_retry.py`（O1/O1b/O3a）、`read_escalation.py`（B2 timeout 执行 + circuit 语义修复）、`selection_authority.py`（O2 分解字段）、`timing_ledger.py`（F2-S1 + `current_phase()`）、`wigolo_backend.py`、`active_adapter.py`。

**answer / consistency / gate / brief 模块改动 = 0** ⇒ d40.2 四项不变量由构造保持，而非仅由重放证明。

### 93.4 F2 封板结论（冻结口径）

> **F2 完成 runtime 成本归因与局部优化。**
>
> * `search`：稳定固定税，非方差源；
> * `retry/backoff`：发现并回收确定性重复等待，**−2s / qualifying read**（attempt 数与 read outcome 不变）；
> * `selector`：延迟方差 **100%** 位于外部 model wait，本地 residual ≈ 0（33/33 `wall == model_wait`，18/18 wave 与独立 ledger 对齐）；
> * `read`：**79.7% wall、85.4% variance** 由网络 fetch 主导，本地后处理 **≈0.8%**（172ms/19 reads）；
> * `checkpoint`：真实但较小（3.1–11.4% of run），**无明显重复**（0/327 全重复），主要成本来自 I/O（48.6%）+ read-back（32.9%），伴随宿主 FS jitter（2/327 次写占 36.6% 写时间）；
> * 因此剩余主要性能问题已从"本地执行效率"转移为 **external backend / host failure handling**。

**F2 唯一可宣称的性能收益是 O1**（连续相同失败路径下单 read 确定性回收 2s backoff，且保持 attempt 数与 read outcome）。**不宣称"F2 把整体 runtime 优化了 X%"**。

**补充保留发现**：§87 的 `unattributed` 已被进一步解释——checkpoint wall 占其 **38.8%–66.4%**，且 84% 的 checkpoint 发生在无打开 phase 的时刻，**不是未知黑洞**；因此**不再为压低 residual 扩 timing ledger**。

### 93.5 路线交接

```text
F2 ✅ CLOSED
  ├─ O1 唯一本地可回收项（已兑现 −2s/qualifying read）
  ├─ O2/O3/O4 均证明"继续抠本地代码"ROI 低（各自独立 cohort）
  └─ B in-situ evidence debt（留档，不阻塞）
        ↓
P2-A  处理真实互联网环境中的 timeout / circuit breaker / fallback /
      backend state / progressive reader / browser / external providers
      —— 不是另开无关大功能，而是承接 F2 已证明的剩余问题
```

### 93.6 债务清单（F2 遗留，不阻塞）

1. **B（deadline-preserving retry suppression）缺 in-situ 触发证据**（确定性测试覆盖）。
2. **写 I/O 长尾**：2/327 次 checkpoint 写占 36.6% 写时间、max 848ms、与体量无关 ⇒ 宿主/FS。
3. **写后重读**：`checkpoint` 末尾 `_required(run_id)` 重读反序列化刚写整行（~4ms/次，约 4% run）⇒ 并发/durability 敏感区，不动。
4. **§71E natural-cold rescue 与 F2 fast-cohort 缺口**：同一 host availability 条件阻塞的**共享外部证据债务**，宿主恢复时共用窗口补。
5. `sources[].read_retry` 不含 `attempts_detail`（设计选择，明细在 `metrics.read_timing[]`）。


## §94 P2-A 冻结范围草案（Real-world Retrieval Layer）——**待裁决后实施**

**状态**：草案。**本刀未改动任何生产代码**。A0 实施前需先解决 §94.9 的 4 个待裁决项。

### 94.1 目标（冻结）

> 把当前"正常网页能研究"的 retrieval/read runtime，升级为面对真实互联网异常时仍能**有界等待、明确降级、正确切换 backend、保留 provenance、不中断研究状态机**的外部访问层。

P2-A **不负责提高答案质量本身**；它负责让后续 synthesis/auditor 能稳定获得"尽可能好的、来源明确的读取结果"。

**证据依据（来自 F2）**：剩余主要成本 = **external wait + host failure shape**（§90 selector 100% 外部；§91 read 79.7% wall / 85.4% variance 在网络，本地 0.8%；§92 checkpoint 真实但小且无重复）。P2-A 围绕此证据收口，**不重开已被 F2 排除的本地优化面**。

### 94.2 Frozen scope（5 个能力面）

```text
P2-A
├─ A1 Failure taxonomy + backend state
├─ A2 Timeout / circuit breaker
├─ A3 Progressive Reader / fallback routing
├─ A4 Browser backend
└─ A5 External discovery/read provider integration
```

**A1 Failure taxonomy + backend state**：统一"失败是什么"。冻结 canonical 状态集：

```text
success · not_found · http_denied(401/403) · rate_limited(429) · connect_failure ·
dns_failure · tls_failure · timeout · reset(如 10054) · invalid_content ·
shell_page · js_required · login_required · anti_bot · backend_failure · budget_exhausted
```

硬要求：**不同 backend 对同一类失败必须投影为统一语义**；每次 read 仍保留 backend-specific raw provenance，但 runtime 决策只依赖 canonical state。这是 A2/A3 的地基。

**A2 Timeout + circuit breaker**：承接 F2-O3。目标不是"把 timeout 调短"，而是**对已表现出稳定失败形状的 host/backend 减少重复支付长尾等待**。覆盖：per-attempt deadline、remaining research budget awareness、host/backend failure streak、`closed/open/half_open/cooldown` 状态、fail-open vs fail-closed 明确规则、breaker provenance。

> **硬边界**：`host health ≠ URL truth`。**不能因一个 URL 失败就默认整个 domain 永久不可用**；breaker 只能影响"是否值得再付网络等待"，**不能把"没读取成功"伪装成"来源不存在"**。

**A3 Progressive Reader**（核心）：读路径冻结成能力阶梯 —— `cheap/native HTTP → normal HTML extraction → alternate reader backend → rendered/browser read → explicit unrecoverable state`。**不是每个页面逐层全走**；routing 结合 failure taxonomy / content type / shell-page detection / JS-required / remaining budget / backend health / escalation history。

保留 §71 原则：**外部 reader 只是 backend，不取得 Evidence Authority**。reader 只返回 `content / provenance / failure state / cost`；是否 usable evidence 仍由 Study Agent 判断。

**A4 Browser backend**：收回此前后置的 §71C-4。浏览器**不是默认 reader，而是昂贵 escalation backend**。触发例：HTTP 返回 shell、JS 渲染后才有正文、需交互后出现结构、HTTP reader 无正文但 browser 有、允许范围内的 anti-bot/cookie 流程可恢复。**必须记录 `why_browser / browser_cost / browser_outcome / browser_content_gain`**，否则 browser 会退化成"读不到就开浏览器"。**默认仍 OFF**（延续 §71C-3b）。

**A5 External providers**：Wigolo read、外部 Discovery backend、其它 Search/Reader provider **全部经统一接口** `DiscoveryBackend / ReadBackend / BrowserBackend`（承接 §71B）。**禁止 `if provider == "foo":` 式特殊逻辑散落 runtime**；provider 差异限制在 adapter 层。

### 94.3 明确非范围（冻结，写进合同）

P2-A **不做**：ResearchBrief 重构 · synthesis · final answer generation · citation prose polishing · Final Auditor · claim support 规则重写 · ranking 大改 · search strategy 大改 · selector 优化 · model provider latency 优化 · checkpoint 优化 · general cache optimization · "为了快"修改 durability · autonomous external agent 直接产最终答案。

继续锁死：**外部 Agent/Search/Reader 可提供候选与内容，不能绕过 Study Agent 的 evidence/support/gate。**

### 94.4 Cache 边界（冻结）

**允许**（服务于 failure handling）：host/backend health cache · negative-result short TTL · 已读取 URL 的本 run reuse · browser escalation result reuse。

**暂不做**（会成为另一个项目）：大型跨 run semantic cache · sophisticated invalidation · retrieval-result ranking cache 系统。

### 94.5 实施顺序（冻结）

```text
P2-A0 Contract                      ← 下一刀
  failure taxonomy / backend state / provenance schema
P2-A1 Circuit breaker + deadline policy      （承接 F2-O3）
P2-A2 Progressive Reader routing             （先用现有 HTTP/Wigolo backend）
P2-A3 Browser characterization + escalation
P2-A4 External provider normalization
P2-A5 Integration / shadow validation
```

**顺序理由**：先接 browser/provider 再定义 failure contract，最终必然得到一堆 provider-specific if/else。

### 94.6 验收门（6 类，冻结）

| Gate | 内容 | 要求 |
| --- | --- | --- |
| **1 Failure correctness** | 200 正常 HTML / 404 / 403 / 429 / timeout / connection reset / JS shell / login wall / backend crash | canonical failure state 正确，**raw provenance 不丢** |
| **2 Bounded latency** | 反复坏 host → breaker 最终打开 → 后续请求快速失败或切 backend → runtime 继续推进 | 证明**有界**（非绝对毫秒值） |
| **3 Fallback correctness** | HTTP fail → alternate reader rescue；HTTP shell → browser rescue；**反例：HTTP 正常 → 不无谓启动 browser** | 正反例都要 |
| **4 Evidence authority unchanged** | support semantics / gate semantics / claim binding / answer authority 全部保持 | 不因 provider 自称"可信"就晋级 evidence |
| **5 Budget correctness** | 所有 escalation 尊重 research_seconds_left / attempt budget / model-tool budget / backend cost；browser 不突破全局预算 | 记账正确 |
| **6 Live heterogeneous cohort** | docs/static · large docs · JS-rendered · 403/anti-bot-ish · PDF · login-required · unstable host | 成功时有证据，失败时有明确状态，**任何路径都不失控** |

### 94.7 成功标准（三层指标，冻结）

**不定义**为"网页读取成功率达到 X%"（真实互联网中有些页面本来就不应/不能读取）。冻结为：

```text
usable_read_rate
  = 通过 ReadAdequacy 且 canonical state = success 的读取 / 全部尝试读取

correct_failure_classification_rate
  = canonical state 与 fixture/live 期望类别一致的失败读取 / 全部失败读取

bounded_failure_rate
  = 在 per-attempt deadline + breaker 行为约束内结束的失败读取 / 全部失败读取
```

> **成功就正确读取；救不了就正确失败；失败也不能拖死整个研究。**

### 94.8 A0（下一刀）交付物草案

**范围锁**：A0 **只做合同**——不改 timeout、不实施 breaker 强制、不接 browser、不加 provider。

1. `src/web/research/failure_taxonomy.py`：canonical `FailureState` 枚举（16 态）+ `classify(...)`（由异常类型 / HTTP status / 内容形状映射）+ `from_read_adequacy()` 适配既有 §71C-3a 形状（`ok` / `read_failed` / `js_shell` / `anti_bot_or_error` / `short_doc`）+ **每 backend 映射表**。
2. **backend state 模型**：`closed / open / half_open / cooldown` 状态与转移 + `failure_streak` 阈值**作为参数**（非魔数）+ provenance。
3. **provenance schema（增量）**：`RawReadArtifact` 增 `failure_state`（canonical）与 `raw_backend_state`（backend-specific），保持 §71B 的 `FORBIDDEN_AUTHORITY_FIELDS` 语义；新增 `backend_health` metrics 通道。
4. **合同测试**：同一失败在不同 backend 下投影一致；**未知失败必须落 `backend_failure`，绝不静默 `success`**；taxonomy 状态**永远不能设置 evidence/support/gate**。
5. **既有可观测面对齐**（避免重做）：§91 已实测的 `urlerror#10054`（→ `reset`）、`exception#403`（→ `http_denied`）、§71C-3a 的 `js_shell`/`short_doc`/`anti_bot_or_error`、B2 的 `run_envelope_exhausted`/`hard_headroom_insufficient`（→ `budget_exhausted`）作为映射表首批输入。

**A0 明确不做**：不调任何 timeout、不改变 read 结果语义、不新增 backend、不动 ranking/answer/gate。

### 94.9 待裁决（实施前必须解决）

1. **canonical state 的落点与兼容性**：新增独立模块 `failure_taxonomy.py` + `RawReadArtifact.failure_state` 采用**增量可选字段**（不破坏 §71B 既有 contract），映射表集中在 taxonomy 模块 —— 是否采纳？
2. **breaker 状态的作用域与持久化**：A1 先做 **per-run 内存态**，跨 run 的 host/backend health cache 延后到 A2 并带 TTL —— 还是 A1 就要跨 run 持久化？
3. **`host health ≠ URL truth` 的强制表达**：冻结"**被 breaker 跳过的读取永不得产出负面内容判断**"（记 `budget_exhausted` + breaker provenance，绝不记 `not_found`），并纳入 Gate 4 —— 是否采纳？
4. **browser 成本的记账单位**：browser escalation 记为 `retrieval_attempt` 并携带 `cost` 子记录（seconds + bytes），**不新增第四本账** —— 是否采纳？

### 94.10 当前项目位置（更新）

```text
P1 Research Core                ✅
§71 Minimal external backend    ✅ / external evidence debt（宿主恢复窗口补）
F2 Runtime characterization     ✅ CLOSED（O1 唯一本地收益；O2/O3/O4 证明本地 ROI 低）

P2-A Real-world Retrieval       ← 当前
  A0 Contract                   ← 下一刀（§94.8），需先裁决 §94.9
  A1 Failure policy / breaker
  A2 Progressive Reader
  A3 Browser
  A4 External providers
  A5 Integration validation

P2-B ResearchBrief / Synthesis
P2-C Final Auditor
Full-function Shadow
Release benchmark
```


## §95 P2-A 外部能力分层与主权规则（冻结）——候选校正 + "3+1+1"

**性质**：方向记录 / 冻结决策。**不改 A0 合同，不改 P2-A 顺序。**

### 95.1 候选信息校正（不把未核验的数字写成事实）

| 候选 | 校正后的口径 |
| --- | --- |
| **Agent Search MCP** | 存在且方向契合，但**不冻结"11 个引擎 / 8 个免费"这类数字**。当前项目文档口径：零 Key 默认路径是 **DuckDuckGo + 搜狗**，另可配置 Brave / Tavily / Exa / Serper 等 provider，新版已比早期复杂得多。其真正价值：**显式保留 provider failure、预算与 partial failure**，而不是失败后返回一个无来源的空结果 |
| **AutoSearch** | 基本属实：`npx autosearch-ai`，宣称 40 个 channel、10+ 中文源，覆盖 arXiv / GitHub / Reddit / Hacker News / 微信 / 知乎 / 小红书 / 微博 / B 站，且强调 **LLM 与 retrieval 解耦**。适合补**垂直平台 Discovery**；**其 deep-research / report 不得成为 Study Agent 的证据权威** |
| **wigolo** | 最强综合候选之一，§71 已实测。公开能力：18 个搜索 adapter；search / fetch / crawl / extract / cache / research；fetch 会从普通 HTTP **自动升级到浏览器**，对 SPA / anti-bot / PDF / 会话 / 页面 action 有支持。**License = AGPL-3.0-only**。其 research / agent 已做规划与综合 ⇒ **只把 search / fetch / crawl / extract 当 backend**，不接成主脑 |
| **search2ai** | 真实且适合做"生产 provider gateway"：Perplexity-compatible schema，可挂 Tavily / Brave / Exa / Serper / SerpAPI / Google / SearXNG，provider 失败会 fallback 并告知**谁成功谁失败**。但 **BYO Key**，不是当前 zero-key 优先阶段的首选 |
| **OrioSearch** | **借设计，不集成**。它本身已是 SearXNG + FastAPI + Redis cache + circuit breaker + rerank + extraction 的完整中间层——正是 P2-A 要自建的部分。整包接入会形成**两套 circuit breaker、两套 failure truth** |
| **AgentSearch (brcrusoe72)** | 17 个 endpoint、自托管 SearXNG、去重、跨引擎评分、query expansion、domain trust、prompt-injection scrubbing、内容提取、可选 browser render ⇒ **"全家桶对照组"**，不作核心架构依赖（否则 Study Agent 变成 AgentSearch 外再套一层） |
| **OpenSERP** | 比先前预期更值得关注：支持 **Google / Bing / 百度 / DuckDuckGo / Yandex / Ecosia** 六类 SERP，多引擎合并、URL extraction、浏览器渲染模式，并有 circuit-breaker stats；**本身足够"低层"**（不像 AgentSearch 已替你做大量 agent 决策）⇒ 非常契合 adapter 模型 |
| **Crawl4AI** | **本清单原先漏掉的 A3 候选**。价值不在搜索，而在 JS 页面 / browser session / Markdown extraction / CSS-XPath extraction 等**读取能力** ⇒ 应与 **Wigolo Browser 做 Reader/Browser bakeoff**，不与搜索候选比 |
| **Firecrawl** | 已把 Search / Scrape / Parse / Crawl / Map / Interact 做成整套 Web Data API；Hosted 依赖 Key，自托管主体 AGPL ⇒ 现阶段定位 **高质量外部基准**，非默认生产依赖 |
| **Trawl** | **纠正：从"搜索候选"移除。** 未核验到"Tavily 兼容搜索 API"版本；当前公开较活跃的 `germondai/trawl` 是**浏览器/挑战页处理服务**（更接近 FlareSolverr 替代品），**本身明确不提供搜索与 ranking**。以后 A3 Browser 若需特殊 browser backend 再单独评估 |

### 95.2 分层裁决（冻结）

| 工具 | 我们真正需要它做什么 | 裁决 |
| --- | --- | --- |
| wigolo | Read / Crawl / Browser escalation | **保留，一级候选** |
| Agent Search MCP | 普通 Web + 中英文 Discovery | **A4 一级候选** |
| AutoSearch | GitHub / Reddit / arXiv / 中文社区等垂直 Discovery | **A4 一级候选** |
| OpenSERP | 原始多引擎 SERP（Google / Bing / 百度等） | **A4 二级候选，强烈值得 bakeoff** |
| search2ai | 有 API Key 后的 production provider fallback gateway | 后期候选 |
| Crawl4AI | 浏览器渲染 / 网页抽取 | **A3 bakeoff 候选** |
| AgentSearch | 自托管全家桶 | 对照 / 参考，**不默认集成** |
| OrioSearch | circuit breaker / extraction 架构 | **参考实现** |
| SearXNG | 最底层 metasearch 基线 | 基础设施候选 |
| Firecrawl | 商用品质 Search / Scrape / Interact 对照 | **Shadow benchmark**，不必当前接 |
| OpenClaw 插件 | 千问 / 秘塔 provider adapter 设计 | 参考 |
| pi-web-extension / ddgs MCP 等 | 简单搜索能力 | 与上面重复，**暂不接** |
| Lyra | Evidence Graph 思路 | 留给 **P2-B / P2-C** 参考 |
| Trawl | browser / challenge 特殊 backend | **当前排除** |

### 95.3 架构原则（冻结）：**不要把 MCP 当成核心接口**

```text
Study Agent
    │
DiscoveryBackend / ReadBackend / BrowserBackend      ← 我们的稳定层（Capability Contract）
    ├── MCP adapter
    ├── HTTP adapter
    ├── CLI adapter
    └── native / library adapter
```

**错误形态**：`Study Agent → MCP → 所有东西`。

理由：Agent Search 是 MCP、AutoSearch 是 MCP、wigolo 是 MCP/REST/SDK、OpenSERP 是 HTTP/SDK/MCP、search2ai 可以是库/HTTP/MCP —— **协议只是 transport，Capability Contract 才是稳定层**。这与 §71B（`DiscoveryBackend` / `ReadBackend` / §94 的 `BrowserBackend`）完全一致。

### 95.4 两条主权规则（冻结）

**规则 1 —— provider 信号只能记录，不能晋级为证据。**
Agent Search 的"多引擎 confidence=3"、AutoSearch 的 citation、AgentSearch 的 domain trust，**只能**记为：

```text
provider_agreement
source_metadata
retrieval_score
```

**绝不能**映射为 `claim.supported = true` 或 `evidence_confidence = high`。

> 三家搜索引擎都搜到同一个 SEO 页面，**不等于**这个 claim 得到三份独立证据。

**规则 2 —— 外部产品已生成的结论在 P2-A 全部禁止直接成为答案。**
外部已产出的 `answer` / `research report` / `deep research` / `compare_solutions`（例如其它 Agent Search 项目提供的 `web_ask` / `web_research` / `compare_solutions`）已越过 Retrieval 进入 Synthesis ⇒ **A4 adapter 最多消费其 search / extract / crawl 原料，不消费其"结论"**。

### 95.5 外部能力路线："3 + 1 + 1"（冻结）

```text
Discovery 主力
  Agent Search MCP   —— 普通 Web / 中英文搜索
  AutoSearch         —— 垂直平台 / 中文社区 / 学术 / GitHub
  OpenSERP           —— 原始多 SERP、百度/Bing/Google 等独立通道

Read / Browser 主力
  wigolo             —— 已有 §71 实验基础，继续作 Reader/Browser backend
  Crawl4AI           —— A3 做 browser/extraction 对照（不一定最终保留两个）

未来有 Key 时
  search2ai          —— 统一 paid provider fallback

不进主链（只作设计与 benchmark 来源）
  AgentSearch / OrioSearch / SearXNG 全家桶
```

```text
普通互联网        → Agent Search MCP
中文/社区/垂直    → AutoSearch
原始 SERP 独立验证 → OpenSERP
                        ↓
                  Candidate Pool
                        ↓
              Study Agent ranking
                        ↓
                  Native HTTP
                        ↓ fail
              Wigolo / Crawl4AI
                        ↓
            Study Agent Evidence Authority
```

> 外部插件增强的是**覆盖面和读取能力**，而不是替我们做研究。

**A4 最终不保证三个全进 production**：按 `unique useful discoveries / failure transparency / latency / 中文覆盖 / provenance / 运维成本 / license` 跑 cohort，**只留真正互补的 2–3 个**。

### 95.6 对 P2-A 顺序的影响：**无变化，且更证明 A0 必须先做**

这些 backend 会吐出**完全不同的失败**：DDG challenge、Sogou empty、Baidu SERP failure、GitHub channel unavailable、HTTP 403、browser shell、provider timeout、MCP failure、SearXNG engine failure。

**没有 A0 canonical taxonomy，接得越多系统越乱。**

**前向映射核对（A0 已能表达）**：

| 未来失败 | A0 canonical 落点 |
| --- | --- |
| DDG challenge | `anti_bot` |
| Baidu SERP failure | `backend_failure` / `http_denied` / `anti_bot`（按原始证据） |
| GitHub channel unavailable | `backend_failure` |
| provider timeout | `timeout` |
| MCP failure | `backend_failure`（MCP 只是 adapter，见 §95.3） |
| SearXNG engine failure | `backend_failure`（**按 provider 粒度**，支持部分成功） |
| HTTP 403 | `http_denied` |
| browser shell | `shell_page` |
| **Sogou empty** | **不是失败状态**：`success` + `result_count = 0` |

> **合同澄清（A4 必须遵守）**：**空结果集不是失败。** 一个返回 0 条候选的搜索是"成功但没有结果"，必须用 `result_count` 表达；**不得**映射成 `invalid_content`（那等于宣称查询无效）或任何内容判断——这与 `host health != URL truth` 同类，只是对象从 URL 换成 query。§71B 的 invocation `empty` 状态是**读取层**语义（空正文），discovery 不得用它表示"没搜到"。

### 95.7 A0 当前状态

- **合同已实现并提交**：`773e2c7`（`src/web/research/failure_taxonomy.py`、`retrieval_backends.py` 增量字段、`tests/test_failure_taxonomy.py`）；§95 记录与发现层澄清提交于 `8571f6b`。
- focused：`test_failure_taxonomy` **64 passed**；含 `test_retrieval_backends` / `test_read_escalation` 合计 **88 passed**；**合同消费者测试集**（导入 §71B/A0 模块的全部 7 个测试文件）**154 passed**；Ruff clean；tracked clean。
- **零生产接线（已验证）**：`validate_read_artifact` / `failure_taxonomy` 在 `src/` 中**仅被自身两个模块引用**，runtime / adapter / backend 均未调用 ⇒ A0 确实只定义合同，**未启用任何 breaker 行为**。
- **候选 head 全量 pytest 待补**：该命令连续两次被中断（用户中止），未产出结果；A0 改动为**纯增量合同**（新增模块 + 两个默认空值字段），消费者测试集已全绿。
- A0 **未改** timeout / breaker 行为 / retry policy / read 结果语义 / backend / ranking / answer / evidence / support / gate。

### 95.8 路线（冻结）

```text
P2-A0 canonical retrieval contract          ← 已实现（773e2c7），待全量门
P2-A1 per-run breaker / deadline policy
P2-A2 Progressive Reader
P2-A3 Browser bakeoff        Wigolo vs Crawl4AI
P2-A4 Discovery provider bakeoff
       Agent Search MCP · AutoSearch · OpenSERP · [search2ai later]
A5 heterogeneous integration

P2-B ResearchBrief / Synthesis          （Lyra 的 Evidence Graph 思路留此参考）
P2-C Semantic / Final Auditor
P2-D Chart / Diagram / Plan / external capabilities（输出侧能力层）
P2-E Artifact / Publication Audit
Full-function Shadow
Release benchmark
```


## §96 P2-A0 CLOSED — Retrieval Outcome Contract（final head `9334abd`）

### 96.1 收口门禁（补跑完成）

| 门 | 结果 |
| --- | --- |
| full pytest | **2217 passed / 2 failed**（706s，head `9334abd`） |
| 失败 1、2 | `test_rq1c_impl_entrypoints::…exact_head_guard[run_rq1c_protocol_probes_core.py]`、`test_rq1c_protocol_probes::…deterministic_protocol_runner_exercises_all_required_probes` —— **已知 Windows-local baseline 失败**（与 `fc50845` / `480cd4e` / `eb120930` 同类），**零新增失败** |
| Ruff（src/tests/tools） | All checks passed（此前已绿，head 未变不重跑） |
| `git diff --check` | clean |
| tracked 工作树 | clean |
| 合同消费者测试集 | 7 文件 **154 passed**（`test_failure_taxonomy` 64 项在内，合计 88 focused） |
| 生产接线 | **零**（`failure_taxonomy` / `validate_read_artifact` 仅被自身模块引用，已扫描验证） |

**状态：`P2-A0 implementation complete → final regression green → P2-A0 CLOSED`。**
A0 未改 timeout / breaker 行为 / retry policy / read 结果语义 / backend / ranking / answer / evidence / support / gate。

### 96.2 A0 baseline 固化

- **P2-A0 final head：`9334abd`**（合同 `773e2c7` → §95 方向与发现层澄清 `8571f6b` → 状态订正 `9334abd`）。
- **全量基线：2217 passed / 2 known failed @ `9334abd`**（A1 起任何全量异常先与此对照）。
- 与 F2 终点基线（`eb120930`，2152/2）相比：**+65 passed / 同 2 known failures**，全部来自 A0 新增合同测试与 §95 前向映射核对测试。

### 96.3 A1 前置裁决（已冻结，不改生产代码）

> **既有 `mark_circuit_open()` 单布尔在 A1 中降级为兼容壳；新的唯一状态权威改为 `(backend, host)` health model。新旧 breaker state 不得双权威并存。**

落地含义（A1 实施时执行）：
1. `WigoloShadowReadBackend._circuit_open` 保留方法签名与行为（兼容），但内部**转调**新的 health model（`backend="wigolo_http"` + 请求 host）；
2. 状态查询/记录只读 `(backend, host)` 权威，单布尔不再单独持有真值；
3. `unsupported + detail=circuit_open` 的现有形状**不变**（A0 桥接已覆盖该形状），因此上游消费者无感；
4. 失败计数只统计 `counts_towards_health(state, attempted=True)`（A0 已冻结：skip 不喂 breaker、内容判断不喂 breaker）。

### 96.4 路线

```text
P2-A0 ✅ CLOSED（9334abd，2217/2 baseline）
P2-A1a per-run breaker / deadline policy   ← 下一刀（待开工指令）
   └─ A1b cross-run health cache（暂不做，收益证明后再立项）
P2-A2 Progressive Reader
P2-A3 Browser bakeoff（Wigolo vs Crawl4AI）
P2-A4 Discovery provider bakeoff（Agent Search MCP / AutoSearch / OpenSERP / [search2ai later]）
A5 heterogeneous integration
```


## §97 P2-A1a per-run health breaker + deadline preflight（`c2f081a` → `944ce69`）

**目标（按裁决口径）**：在不改变 URL truth、Evidence Authority 与 retry 语义的前提下，让同一 run 内已表现出稳定失败的 `(backend, host)` 不再反复吞掉研究预算，并允许受控探测恢复。

### 97.1 状态权威（最终实现）

`src/web/research/health_breaker.py`：唯一权威 = `HealthKey = (backend, host)`，唯一状态机 = `closed / open / half_open / cooldown`。

| 转移 | 触发 | 记录 |
| --- | --- | --- |
| `closed → open` | qualifying failure 达参数化阈值 | `failures_reached_threshold`（`opened_at_ms`、`eligible_probe_at_ms = now + open_seconds`） |
| `open → half_open` | `open_seconds` 到期（惰性求值，无定时器） | `open_window_elapsed`（`probe_index += 1`、`probes_used = 0`） |
| `half_open → closed` | probe 观测到非 health 失败（成功或内容判断） | `probe_succeeded`（failure counters 归零） |
| `half_open → cooldown` | probe qualifying failure | `probe_failed`（`eligible_probe_at_ms = now + cooldown_seconds`） |
| `cooldown → half_open` | `cooldown_seconds` 到期 | `cooldown_elapsed`（再次允许 probe） |

- **`cooldown` 是真实状态**，不是 `open + timestamp`（按裁决）。
- `half_open` 只放行 `half_open_probes` 次（默认 1）；未记录结果前不放大。
- 阈值全部参数化（`BackendHealthPolicy`），env 仅作 harness 覆盖（`RESEARCH_BREAKER_FAILURE_THRESHOLD / OPEN_SECONDS / COOLDOWN_SECONDS / HALF_OPEN_PROBES`），**生产默认值未被修改**。
- **会计口径**：一律经 `counts_towards_health(state, attempted=True)`；`attempted=False` 永不计数；`budget_exhausted` 不计 host 健康；`not_found` / `http_denied` / `invalid_content` / `shell_page` **默认不计**（内容判断不是后端病态）；**skip 永不计数**（否则 breaker 会互相喂养）。breaker 内部**不重新发明 taxonomy 判断**。
- **跨 key 隔离**：`(native_http, bad)` 不影响 `(native_http, good)`，也不影响 `(browser, host)` —— 这是 A2 Progressive Reader 能否正确 fallback 的前提。
- 作用域：**per-run 内存态**；跨 run health cache 未实现（A1b 未立项）。

### 97.2 兼容壳落地

`mark_circuit_open()` 无任何调用点（防御性接口）。按已冻结裁决：

- `_circuit_open` **不再是状态权威**；旧接口转调同一 health model；
- 无 host 时落到该 backend 的 **wildcard key**（`native_http::*`）——**仍是同一个模型，只是 key 更宽**，并标 `legacy=true`，provenance 可区分；
- `allow()` 先查精确 key，再查该 backend 的 wildcard key；
- 既有 `unsupported + detail=circuit_open` 外部形状**保持不变**（A0 桥接已覆盖，上游消费者无感）；
- **没有第二套 breaker 状态**。

### 97.3 deadline preflight（并修正一处自引入缺陷）

- 最终实现**复用既有 deadline 政策**：唯一窗口门 = `research_seconds_left() < MIN_READ_SECONDS`，并以 A0 词汇记录（`attempted=false` / `retrieval_state=budget_exhausted` / `skip_reason=insufficient_remaining_window`）。该 skip **不进入 health 会计**。
- **`944ce69` 修正**：初版把 `read_timeout_seconds() + READ_RETRY_RESERVE_SECONDS` 当作需求，但 `read_timeout_seconds()` 本身已是 `min(cap, research_seconds_left())` ⇒ 窗口小于 cap 时**恒拒**，等于引入第二个更严的窗口门。实测证据：node run `window_skips 1`、reads 由 5 降到 2；修正后 `window_skips 0`、reads 回到 4。
- **未引入新 latency estimator，未改全局 read timeout，未改 retry ceiling。**

### 97.4 测试 / 全量回归

| 项 | 结果 |
| --- | --- |
| `tests/test_health_breaker.py` | **24 passed**（阈值开启、skip 拒发、skip 不自增、未到期继续 skip、到期 half_open、probe 次数上限、probe 成功关闭并归零、probe 失败进 cooldown、cooldown 未到期 skip、cooldown 到期再 probe、`budget_exhausted` 不计、URL truth 不计、健康观测归零、deadline skip 不计、跨 backend / 跨 host 隔离、key 归一化、legacy wildcard、legacy 带 host、legacy 到期 half_open、snapshot provenance、开关默认 off + 参数化） |
| runtime 接线测试（追加于 `test_active_research_runtime.py`） | **3 passed**：breaker 开启后重复坏 host 变为快速 policy skip（`gateway.calls < 3`）、`backend_health` 落地、failure 行 `provider_code=circuit_open`；健康 host 不受影响（仍 `read`）；开关默认 off 时 `backend_health` 为空且每次读取照发 |
| 受影响集合 | **224 passed**（8 个消费 §71B/A0/A1a 的测试文件） |
| **full pytest @ `944ce69`** | **2243 passed / 3 failed**（731s）：2 个已知 Windows-local baseline 失败 + 1 个已知负载型闪失败（`test_dirty_tracked_checkout_blocks_imported_internal_artifact_writes`，**单跑 1 passed**）⇒ **零新增失败** |
| 对照 A0 baseline（`9334abd`：2217/2） | **+26 passed**（新增 27 项测试，1 项被闪失败抵消），失败族不变 |
| Ruff | All checks passed |
| tracked | clean |

### 97.5 in-situ 证据（小样本，非 cohort；开关 ON，harness 阈值，生产默认未动）

| artifact | 观测 |
| --- | --- |
| `A1A.docker.bad3`（`944ce69`） | **`native_http::docs.docker.com` → `open`，streak 1，转移 `failures_reached_threshold`** —— 真实不可达 host（WinError 10054）上的 `closed → open` |
| `A1A.postgres.bad`（`944ce69`） | **负面对照**：`www.postgresql.org` = `invalid_content`、`baike.baidu.com` = `http_denied`、`www.runoob.com` = `success` ⇒ **全部 `closed` / streak 0**，即内容判断与 HTTP 拒绝**不触发熔断**；所有 attempted 读取都带 canonical `retrieval_state` |
| `A1A.docker.bad2` / `A1A.node.good2` | 健康 host 全 `closed`；reads 4（与 A1a 前区间一致）；`window_skips 0`；`answer_status=available` |
| `A1A.node.good` / `A1A.docker.bad`（`c2f081a`，修正前） | deadline 双计费的表现：`window_skips` 1/3、reads 2 —— **保留为缺陷证据** |
| **未观测到** | **`circuit_open` 真实 skip**（需同一坏 host 在同一 run 内被尝试两次；本次样本未出现）与 **half-open 恢复** ⇒ **由确定性测试覆盖**（24 项状态机 + 3 项接线），按裁决不阻塞 |

**成功标准（按裁决）**：不是"总 elapsed 降 X%"，而是 **重复不健康 host 的后续等待被有界抑制，同时健康 host、其它 backend、URL truth 与最终 evidence semantics 不变** —— 上表满足（`gate` 状态与 `answer_status` 未退化，负面对照证明内容判断不被污染）。

### 97.6 会阻塞 A2 Progressive Reader 的语义问题（**必须在 A2 开工前裁决**）

**发现**：`RuntimeCursor.completed_read_ids` 由**全部** `read_outcomes` 派生（`src/web/research/runtime.py:552-554`），而 breaker skip 也追加了一条 `RuntimeReadOutcome`（status=`failed`）⇒ **一次 policy skip 会把该 candidate 在本 run 内永久标记为"已完成"**，因此：

- 后续 wave 不会重试它（`if candidate_id in cursor.completed_read_ids: continue`，runtime:1726）；
- A2 的 fallback 候选集也会把它排除（`excluded = frozenset({*cursor.completed_read_ids, *already_ranked})`，runtime:3735）。

**含义**：A1a 只负责"说这次不值得等"，但**当前实现把"没试"与"试过但失败"在候选生命周期上混为一谈**。A2 需要二者之一：

1. **分离集合**：skip 记入独立的 `skipped_read_ids`，不进 `completed_read_ids`（候选保留给其它 backend / 后续 wave）；
2. **选择期路由**：A2 在 read 计划生成前用 `state_for(backend, host)` 决定 backend，skip 不发生"消费"。

**另需 A2 处理**：A1a 只对主 reader（`native_http`）咨询 breaker；`read_escalation` 内的 Wigolo 升级路径**尚未受 health 管辖**（A2 接线，非 A1a 缺陷）。health key 已按 backend 分离，A2 可直接查询另一 backend 的 health。

### 97.7 范围合规

未做：跨 run health cache · Progressive Reader fallback · browser · Wigolo/Crawl4AI 接线 · Discovery provider · 调 timeout 默认值 · 改 retry ceiling · general cache · ranking/selector/answer/evidence/support/gate 改动。**未接** `breaker open → 自动切 Wigolo`（明确属 A2）。

### 97.8 路线

```text
P2-A0 ✅ CLOSED（9334abd，2217/2）
P2-A1a ✅ 实现完成（944ce69；2243/3 = 2 known + 1 known flake）
   ├─ 待补：`circuit_open` in-situ skip 与 half-open 恢复（确定性测试已覆盖，不阻塞）
   └─ **A2 前置裁决：97.6 的 skip 是否应消费 candidate**
P2-A1b cross-run health cache（未立项，收益证明后再决定）
P2-A2 Progressive Reader ← 下一刀（需先裁决 97.6）
```


## §98 P2-A2a Candidate Resolution Contract（`5690c52`）

**裁决落地**：§97.6 采用方案 1，但升级为 **candidate lifecycle 语义修复**；A2 仍须在计划生成前读取 `(backend, host)` health 做路由 —— **语义修复 + 提前避免无效 attempt 两者都做**（后者属 A2c）。

### 98.1 根因与冻结语义

```text
read_outcome exists  !=  candidate completed
```

- **`read_outcome` = 一次 backend attempt / policy decision 的历史事实**（只回答"某个 backend 对这个 candidate 做过什么"）。
- **`completed` = 整条 reader chain 已达到终局**。
- policy skip / retriable failure / escalation-needed outcome **不得自动消费 candidate**。

### 98.2 candidate resolution authority 最终形状

`src/web/research/candidate_resolution.py`（**纯函数，无状态、无 ledger、不碰 evidence/support/gate**）：

```text
resolved         某个 backend 产出可用结果，或资源本身已终局（not_found）
fallback_pending 本 backend 未解决，chain 中仍有其它 backend 可试
policy_deferred  本 backend 未被尝试（circuit open / backend disabled），candidate 未被消费
run_blocked      run 已无法调度（窗口/预算）；不是 URL 内容事实，也绝不伪装成完成
chain_exhausted  所有允许的 reader 都试过且都未解决
```

- `CandidateResolution.terminal` = `resolved | chain_exhausted`（即旧 `completed` 语义）。
- `reschedulable` = `fallback_pending | policy_deferred`；`may_try_another_backend` = `fallback_pending`。
- 输入：`AttemptFact`（backend / retrieval_state / attempted / status）+ `backend_chain` + 可选 `health_state_for(backend, host)`（A2c 提供；A2a 不据此做调度决策，只报告"仍合法可用"的 backend）。
- `terminal_candidate_ids(outcomes)` 是**唯一**的"完成"定义；`resolution_summary()` 提供诊断。
- **`DEFAULT_READER_CHAIN = ("native_http",)`** ⇒ A2a **不改变现有行为**，A2b/A2d 扩展 chain 后语义自动生效。
- 判定顺序：`settled` 尝试优先（不会被后续 unsettle）→ `run_blocked` → `needs_alternate`（有可用 backend → fallback_pending，否则 chain_exhausted）→ policy skip（有可用 backend → fallback_pending；仅被 health 阻塞 → **policy_deferred**；chain 空 → chain_exhausted）。
- 分类集合：`TERMINAL_STATES = {success, not_found}`；`ALTERNATE_ELIGIBLE_STATES = {shell_page, js_required, anti_bot, login_required, http_denied, rate_limited, invalid_content, connect_failure, dns_failure, tls_failure, timeout, reset, backend_failure}`；`RUN_BLOCKED_STATE = budget_exhausted`。

### 98.3 三个 runtime 调用点如何统一

| 位置 | 处理 |
| --- | --- |
| `runtime.py` `completed_read_ids`（旧 `:552-554`，由全部 outcome 派生） | **改为委托 authority**：`terminal_candidate_ids(self.read_outcomes)`；本属性不再自行解释 outcome。新增 `read_resolutions()` 暴露 per-candidate 视图 |
| `runtime.py:1726`（read loop 跳过已完成 candidate） | 继续消费该属性 ⇒ 自动获得新语义，无需各自解释 |
| `runtime.py:3735`（`excluded = {*completed_read_ids, *already_ranked}`） | 同上 |
| 附带 | `RuntimeCursor` 其余 `completed_read_ids` 消费点（1356/1578/1651/1948/1982/4157/4824…）**全部继承同一权威**，未新增任何本地解释 |

**关键设计发现**：cursor 强制 **每 candidate 唯一 read outcome**（`runtime.py:1021` 校验）。因此 **policy skip 现在根本不产生 read outcome** —— skip 不是一次读取。它的 provenance 完整保留在 `metrics.read_timing`、`sources[].retrieval_policy` 与 failure 行（`code=read_failed` + `provider_code=circuit_open`）。这既满足"skip 不得消费 candidate"，又不破坏唯一性不变量。

### 98.4 持久化面（compatibility）

- `RuntimeReadOutcome` 增量字段：**`backend`** + **`retrieval_state`**（canonical），使用既有 `setdefault` 垫片模式（B5 / P1-C batch 2 / Slice 1 先例）⇒ **pre-A2a 持久 cursor 仍可加载**（缺失字段补默认）。
- 真实 attempt 的 `retrieval_state` 由 A0 `classify()` 得出并随 outcome 持久化 ⇒ lifecycle 能区分**终局 `not_found`** 与**可 fallback 的 `reset`**（A2b route matrix 的前提）。
- 唯一性不变量未改；`error_code` 对真实失败仍为 `read_failed`（冻结字面量不变）。

### 98.5 tests / regression

| 项 | 结果 |
| --- | --- |
| `tests/test_candidate_resolution.py` | **31 passed**（success→resolved、not_found→terminal、settled 优先、shell/js_required/anti_bot→fallback_pending、transport failure + 有 alternate→fallback_pending、无 alternate→chain_exhausted、全 backend 耗尽→terminal、**policy skip 不 completed**、**health-blocked→policy_deferred**、health-blocked 的 alternate 不被提供、half_open 仍被提供、空 chain→exhausted、budget_exhausted→run_blocked 且不成为 URL 事实、词表封闭、outcome 历史完整保留、legacy outcome 视为 attempt、terminal_ids 单一完成定义、skip 不在历史中、summary 计数、无 authority 字段、codec 往返、legacy codec 兼容、cursor 空态、run entity 不被修改） |
| 受影响集合 | **248 passed**（active runtime / health breaker / candidate resolution / failure contracts / foundation / taxonomy / escalation / backends） |
| **full pytest @ `5690c52`** | **2274 passed / 3 failed**（683s）：2 已知 Windows-local baseline + 1 已知负载闪失败（**单跑 1 passed**）⇒ **零新增失败** |
| 对照 A1a（2243/3） | **+31 passed**（新增测试），失败族不变 |
| Ruff / `git diff --check` / tracked | 全 clean |

### 98.6 in-situ（`A2A.node.json` @ `5690c52`，breaker ON / harness 阈值）

- `gate=pass`；5 个 read outcome **全部带 `backend=native_http` + canonical `retrieval_state`**（4×`success`、1×`invalid_content`）。
- `metrics.candidate_resolution` = `{candidates: 5, resolved: 4, chain_exhausted: 1}` —— 那个 `chain_exhausted` 正是 `invalid_content`（393 字符 short_doc）且 chain 只有 `native_http` ⇒ **与 A2a 前行为一致**（证明"零行为变化"）。
- `read_timing` 每行带 `retrieval_state` + `retrieval_policy.attempted=true`。
- `answer_status=unavailable / reason=production_chat_failed`，但 `gate=pass` 且 **eligible evidence = 6** ⇒ 该失败是**模型侧瞬时失败**（与 A1a 批次中出现过一次的同一族），**与 A2a 无关**（A2a 只动 read lifecycle）。

### 98.7 会阻塞 A2b routing matrix 的歧义（**需裁决**）

1. **escalation 是 chain step 还是 native read 的子步骤？** 今天 Wigolo 升级在 `read_escalation` 内部作为 `native_http` 读取的**子步骤**触发，不是独立 chain step。而 A2b 要求的矩阵形如 `native_http shell_page → eligible alternate reader`。⇒ A2b/A2d 必须先把 escalation 提升为显式 chain step（或让 chain 建模嵌套步骤），否则 route matrix 无法表达。
2. **`http_denied` / `rate_limited` / `login_required` 的 fallback 归属**：裁决说"`http_denied` 是否 fallback 由 route policy 决定"，但 A2a 已把它们放入 `ALTERNATE_ELIGIBLE_STATES`（默认可 fallback）。⇒ A2b 必须显式接管这三类的路由决定，不能让 A2a 的默认值成为隐式 policy。
3. **`invalid_content` 与既有 adequacy 升级的双重处理风险**：`invalid_content`（short_doc）在 A2a 里可 fallback，而 §71C-3a 的 escalation 也会对 `short_doc`/`js_shell`/`anti_bot_or_error` 升级 ⇒ 一次读取可能被**两条路径各升级一次**。A2b/A2d 必须合并为一个决策点。
4. **重调度语义**：`policy_deferred`/`fallback_pending` 为 `reschedulable`，即后续 wave 可重新规划该 candidate（skip 不再终局）。这**是裁决要的**，但意味着 skip 会在后续 wave 重复出现（每次都是快速 skip，受 wave 上限约束）。A2c 的 health-aware 调度应负责提前避免无效 attempt。

### 98.8 兼容债务（延续）

- `mark_circuit_open()` → `native_http::*` wildcard health key：**仅 legacy compatibility debt**，当前无调用点；**A2 及之后任何新 production 路径禁止产生 wildcard health key**。
- 未接 Wigolo fallback、未改 escalation 行为、未加 browser/Crawl4AI、未改 timeout/retry、未做 A1b cache、未加 Discovery provider、未碰 Evidence/Support/Gate/Answer、未建新 ledger。

### 98.9 路线

```text
A0 ✅ CLOSED      A1a ✅ CLOSED      A1b ⏸ evidence-triggered only
A2a ✅ 实现完成（5690c52；2274/3 = 2 known + 1 known flake）
   └─ 待裁决 §98.7 的 4 项歧义
A2b Progressive routing matrix ← 下一刀（需先裁决 §98.7）
A2c Health-aware scheduling
A2d Existing Wigolo escalation wiring
A2e integration / live validation
A3 Browser bakeoff → A4 Discovery bakeoff → A5
```


## §99 P2-A2b Progressive Routing Authority（`31b0800`）

**设计原则（按裁决）**：从 A2b 起，Progressive Reader **只有一个"下一步读什么"的路由权威**。§71C-3a 旧 escalation、A2a 默认 fallback 集、breaker skip **只能提供事实/信号，不能各自决定升级**。

**基线口径（按裁决明确区分，避免 bisect 混淆）**：

```text
A2a code/test baseline        = 5690c52
A2a final/documentation head  = 8caf6e9
A2b code/test baseline        = 31b0800
```

### 99.1 routing authority 最终数据模型

`src/web/research/progressive_routing.py`（**纯决策层**：不执行网络、不改 evidence/support/gate、无 ledger、无状态）：

**输入 `RoutingContext`**：`candidate_id` · `current_backend` · `retrieval_state`（canonical）· `adequacy_reason` · `attempted`（本次是否真的发过请求）· `attempted_backends` · `available_backends`（chain）· `host` · `remaining_seconds`（**仅供 A2c 参考；路由不自行发明窗口阈值**，窗口门仍在 runtime 既有 deadline policy）。

**输出 `RoutingDecision`（恰好一个 action）**：

```text
resolve            已终局（usable content，或 terminal resource outcome 如 not_found）
try_backend(name)  交给该 backend
defer              当前无可执行 backend，但 candidate 未完成（如 alternate 全被 health 阻塞）
block_run          run 已无法调度（窗口/预算）
exhaust            所有允许的 reader 已试过或不具备所需能力
```

字段：`candidate_id / action / next_backend / reason / required_capabilities / terminal / usable_content / considered_backends`。`terminal` 与 `usable_content` **正交**。

**纯度**：同一 context 重复调用结果完全一致（有测试）。

### 99.2 route matrix（显式，冻结）

| canonical outcome | 默认下一步 | reason |
| --- | --- | --- |
| `success` | `resolve`（`usable_content=true`） | `usable_content` |
| `not_found` | `resolve`（**`terminal=true` 但 `usable_content=false`**） | `terminal_resource_outcome` |
| `reset` / `connect_failure` / `dns_failure` / `tls_failure` / `timeout` / `backend_failure` | `try_backend`（alternate） | `transport_failure_alternate` |
| `shell_page` / `js_required` | `try_backend`（**要求 `js_render`**） | `rendered_backend_required` |
| `anti_bot` | `try_backend`（**要求 `anti_bot_recovery`**） | `anti_bot_backend_required` |
| `login_required` | `try_backend`（**要求 `session`**；普通 HTTP reader 不被提供） | `session_backend_required` |
| `http_denied` | `try_backend`（alternate，`plain_http` 即可） | `access_denied_alternate` |
| `rate_limited` | `try_backend`（alternate；**health 归属仍由 breaker 决定**，路由不碰） | `rate_limited_alternate` |
| `invalid_content` | **由 adequacy reason 细化** | `adequacy_reason_routed` |
| `budget_exhausted` | `block_run` | `run_blocked` |
| policy `circuit_open`（`attempted=false`） | `try_backend`（跳过当前 backend，candidate **不 terminal**） | `policy_skip_other_backend` |
| 无可用且有能力者但被 health 阻塞 | `defer` | `all_capable_backends_unhealthy` |
| 全部试过 | `exhaust`（terminal） | `all_backends_tried` |
| 仍有未试 backend 但都不具所需能力 | `exhaust`（terminal） | `no_capable_backend` |

**`invalid_content` 的 adequacy 细化**（消除"过粗万能 fallback 信号"）：

| adequacy reason | 要求能力 | 结果 |
| --- | --- | --- |
| `short_doc` | `content_extraction` | alternate reader |
| `js_shell` | `js_render` | rendered backend |
| `anti_bot_or_error` | `anti_bot_recovery` | anti-bot backend |
| `malformed_binary` | — | **`exhaust` + `unsupported_content`（terminal，不可救）** |

### 99.3 backend capability 模型

不再靠名称判断（禁止 `if backend == "wigolo"`）。能力词表（冻结）：

```text
plain_http · content_extraction · js_render · session · anti_bot_recovery · pdf
```

当前声明（今日存在的 backend）：

| backend | capabilities |
| --- | --- |
| `native_http` | `plain_http`, `content_extraction` |
| `wigolo_http` | `plain_http`, `content_extraction`, `js_render` |
| `wigolo_browser` | `plain_http`, `content_extraction`, `js_render`, `session`, `anti_bot_recovery`, `pdf` |

⇒ `login_required` 只会选 `session`-capable；`shell_page` 只会选 `js_render`-capable。**A3 的 Crawl4AI/browser 只需在 `DEFAULT_BACKENDS` 声明能力即可接入矩阵**（有测试用 `future_browser` 证明"新增 backend 无需改矩阵"）。

### 99.4 §71C legacy escalation 如何降级为 signal-only

- **本刀未改 `read_escalation` 行为**（裁决明令禁止）。A2b 完成的是**信号契约与唯一决策点的建立**：
  - 路由输入所需的 `adequacy_reason` 直接来自既有 §71C-3a adequacy 形状（`classify_reader_result(raw).shape` → `short_doc` / `js_shell` / `anti_bot_or_error`），**无需新检测器**；
  - `retrieval_state` 来自 A0 `classify()`。
- **A2d 才执行真正的降级**：把 `read_escalation` 内部"直接调用 Wigolo"改为**只产出 adequacy/escalation signal**，由 chain step 消费路由决定。
- **当前无双升级风险**：authority 尚未被任何执行路径消费（inert），且 `read_escalation` 行为未变 ⇒ 现在不存在两条路径各升级一次。
- **A2d 的硬要求（已记录）**：接线 chain step 的**同一次改动**必须移除 read 内的 escalation 执行，否则立即产生双升级。

### 99.5 tests / regression

| 项 | 结果 |
| --- | --- |
| `tests/test_progressive_routing.py` | **35 passed**（success→resolve+usable、not_found→terminal 且 **usable=false**、terminal 不再路由、6 类 transport→alternate、attempted backend 不重复选、shell/js_required 要求 `js_render`、**plain-HTTP-only chain 对 shell → `exhaust`/`no_capable_backend`**、anti_bot 要求 `anti_bot_recovery`、**login_required 不路由到普通 HTTP**（只有 plain alternates 时 `exhaust`）、http_denied/rate_limited 显式 policy、**同一 `invalid_content` 因 adequacy 不同而路由不同**、`malformed_binary` 不可救、circuit skip 跳过当前 backend 且不 terminal、budget_exhausted→block_run、全试过→exhaust、health 阻塞→defer、half_open 仍可用、health 只对未试且有能力者咨询、**每 decision 恰好一个 action**、纯函数可重复、能力声明、**新 backend 无需改矩阵**、payload 无 authority 字段、context 可序列化） |
| `tests/test_candidate_resolution.py` | **32 passed**（新增 `resolved ≠ usable_content`：`success`→usable true，`not_found`→terminal 但 usable false） |
| 受影响集合 | **234 passed** |
| **full pytest @ `31b0800`** | **2310 passed / 3 failed**（749s）：2 已知 Windows-local baseline + 1 已知负载闪失败（**单跑 1 passed**）⇒ **零新增失败** |
| 对照 A2a（2274/3） | **+36 passed**，失败族不变 |
| Ruff / `git diff --check` / tracked | 全 clean |

### 99.6 会阻塞 A2c / A2d 的语义问题（**需裁决**）

1. **`schedulable_now()` 需要显式入口，而不是复用空状态的 `route()`**：A2c 要在**尝试前**问"这个 candidate 现在还有可执行 backend 吗"。用 `route()` 传空 `retrieval_state` 可以工作（无 fact ⇒ `required={}` ⇒ 选第一个 capable backend），但这是**隐式用法**。建议 A2c 增加显式 `next_executable_backend(context)`，避免把"查询可调度性"与"处理一个 outcome"混成一个 API。
2. **A2d 必须把 B2 预算策略一起搬过去**：现有 Wigolo HTTP 升级带自己的准入（`RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT`、per-run envelope、effective timeout）。一旦升级变成 chain step，**这些预算守卫必须随 step 移动或被路由咨询**，否则 chain step 会绕过 §82 的预算定价（那正是 B2 存在的理由）。**这是 A2d 的硬前置**。
3. **escalation 的 `preflight`/`disabled` skip 语义**：Wigolo daemon 不可用时 `read_escalation` 产出 `attempted=false` + `preflight`/`backend_unavailable`。路由会把它当作 policy skip → 尝试下一 backend。需要确认 A2d 是否希望"daemon 不可用"在 chain 内继续向后走（当前语义：向后走会耗尽 chain → `exhaust`），以及是否要单独记 provider-level health。
4. **`rate_limited` 的 health 归属**：裁决说"该 provider/host health 单独处理"。A1a 的 `counts_towards_health` **当前不计** `rate_limited`（它在 `CONTENT_JUDGEMENT_STATES` 里，按"内容判断不计"处理）。⇒ A2c/A2d 若要让 429 影响 provider health，必须**显式改 `counts_towards_health`**，不能在路由里另起一套判断。

### 99.7 范围合规

未做：真正执行 Wigolo fallback · health-aware scheduler 接线 · Crawl4AI/browser · A1b cross-run cache · 改 retry/timeout · Discovery provider · Evidence/Support/Gate/Answer · 新 ledger。**未改 `read_escalation` 行为**。

### 99.8 路线

```text
A0 ✅  A1a ✅  A2a ✅（baseline 5690c52 / doc 8caf6e9）
A2b ✅ 实现完成（31b0800；2310/3 = 2 known + 1 known flake）
   └─ 待裁决 §99.6 四项
A2c Health-aware scheduling ← 下一刀
A2d Existing Wigolo escalation wiring（含 §99.6-2 的预算守卫搬迁）
A2e integration / live validation
A3 Browser bakeoff（Wigolo vs Crawl4AI）→ A4 Discovery bakeoff → A5
```


## §100 P2-A2c Health-aware Scheduling（`d9b8dd8`）

**目标（按裁决）**：在真正发 attempt 前建立显式 scheduler，选择"当前可执行的 backend"，避免 circuit-open backend 在后续 wave 被反复规划，同时保持 candidate lifecycle 正确。**A2c 还不新增第二个 reader**（Wigolo chain execution 仍等 A2d）。

**基线口径**：`A2c code/test baseline = d9b8dd8`。

### 100.1 scheduling authority 数据模型

`progressive_routing.py` 新增 **pre-attempt** 阶段（与 post-outcome `route()` **明确分离**）：

**输入 `SchedulingContext`**：`candidate_id` · `available_backends`（chain，顺序即偏好）· `attempted_backends`（**per candidate**）· `host` · `run_blocked` · `required_capabilities` · `availability`（provider/policy）· `remaining_seconds`（仅参考）。

**输出 `SchedulingDecision`**：`action ∈ {schedule, defer, block_run, exhaust}` + `backend` / `reason` / `considered_backends` / `blocked_backends` / `verdicts`（每 backend 的 eligibility 明细）。

- **不是 bool**：`defer`（暂时不可执行但 candidate 未终局）与 `exhaust`（无可执行者）必须可区分 —— 这正是 A2a lifecycle 的对应关系。
- **不产生 read outcome**：`defer / block_run / exhaust` 只写 `metrics.read_scheduling` provenance，因为**没有真正读取**。
- **纯函数**：不修改 context（有测试）。

### 100.2 shared backend-eligibility primitive

**唯一判定** `backend_eligibility(inputs)`，两个阶段共用，避免复制 capability/health/attempted 判断：

| 顺序 | 判定 | reason |
| --- | --- | --- |
| 1 | capability 是否满足 | `capability_not_satisfied` |
| 2 | 是否已 attempted（含 current_backend） | `already_attempted` |
| 3 | `configured`（部署开关） | `disabled` |
| 4 | provider `available` | `provider_unavailable` |
| 5 | `(backend, host)` health ∈ {open, cooldown} | `target_health_open` |
| — | 全部通过 | eligible |

`BackendEligibility` 仍**报告** `health_state`（即使已因更早原因被拒），便于 provenance。

### 100.3 policy/provider availability 与 target health 分离（按裁决）

- `BackendAvailability{backend, configured, available, reason}`：**provider/policy 层**。
- **`disabled`**：`attempted=false`、**不计 health**、不产生 URL truth；scheduler 直接换下一 backend（有测试：disabled 不进 `blocked_backends`）。
- **provider 不可用**（如 Wigolo daemon down）：记为 `provider_unavailable`，**绝不写进目标 `(backend, target_host)` health** —— 目标 URL 根本没被访问。有测试断言此时 `health_state == ""` 且 reason ≠ `target_health_open`。
- **本刀不建立 provider-level breaker**（裁决：等 A2d live evidence 出现 backend-wide 重复浪费再立项）。
- **未修改 `counts_towards_health()`**：429 仍**不进入** A1a target-host breaker，仍允许 routing 尝试 alternate；未来若要影响 health，**必须显式改该唯一 health-accounting 路径**（不能在 router 另起判断）。

### 100.4 runtime 调度点如何改为 health-aware

`execute()` 内新增 `schedule_read(url)`（在 read loop 中于 `breaker_allow` **之前**调用）：

```text
candidate
  ↓
scheduler（chain / attempted(per candidate) / host / health）
  ├─ schedule → breaker allow → gateway read（原路径）
  └─ defer / block_run / exhaust → continue（不 attempt、不产出 read outcome）
```

- **attempted 历史按 candidate 过滤**（`cursor.read_outcomes` 中同 `candidate_id` 的 `backend`）—— 这是实现中被测试抓到的关键 bug：初版按全局 outcome 计算，导致首个 read 后所有候选都被判 `exhaust`（11 项测试失败），已修。
- `breaker_allow()` **保留**作为 attempt 前的纵深防御。
- 非可执行决策只写 `metrics.read_scheduling`（有界 60 条）。
- **A1a 的 breaker-skip read outcome 路径在生产中不再被触发**（scheduler 先 defer）⇒ A1a 的 runtime 测试已按新语义更新：不健康且唯一 reader 时产出 **defer + blocked_backends**，而非 skip outcome。

### 100.5 是否彻底消除了重复 circuit-open planning

**是（in-situ 已验证）**：`A2C.docker.b`（`www.docker.com` 失败 1 次 → breaker **open**）：

```text
scheduling: {schedule: 1, defer: 2}   read outcomes: 1   （而非 3 个 skip outcome）
defer reason = all_backends_unavailable, blocked = ['native_http']
health: native_http::www.docker.com = open (streak 1)
```

⇒ 后续候选**不再被规划**（无 attempt、无 skip outcome、无重复等待），provenance 落在 `read_scheduling`。健康路径不受影响：`A2C.docker.a` / `A2C.node` 均为 `{schedule: 4}`、4 个 read outcome，node `gate=pass`；三次运行 `answer_status=available`。

### 100.6 tests / regression

| 项 | 结果 |
| --- | --- |
| `tests/test_scheduling.py` | **26 passed**（native closed→schedule；**native open + alternate eligible → 直接选 alternate**；**唯一 open reader → defer 且 `blocked_backends`**；half_open 可调度；**backend health 不跨 backend 泄漏**；**host health 不跨 host 泄漏**；disabled 不调度且**不算 health**；**provider unavailable 不污染 target health**（verdict `health_state==""`）；attempted 不再调度；capability 不足不调度；无可用→exhaust；run_blocked→block_run；**eligibility 优先级**；**scheduling 与 routing 共用同一 primitive 且结论一致**；**scheduling ≠ read outcome**（payload 无 `retrieval_state`/`status`）；动作集封闭；无 authority 字段；纯函数可重复；不改 context） |
| `tests/test_progressive_routing.py` | **35 passed**（router 已重构为共用 primitive，行为不变） |
| `tests/test_candidate_resolution.py` | **32 passed** |
| 受影响集合 | **168 passed**（active runtime / scheduling / routing / resolution / breaker） |
| **full pytest @ `d9b8dd8`** | **2333 passed / 2 failed**（704s）：**仅 2 个已知 Windows-local baseline 失败**（负载闪失败本次未出现）⇒ **零新增失败** |
| 对照 A2b（2310/3） | **+23 passed**，失败数 3→2（闪失败未触发） |
| Ruff / `git diff --check` / tracked | 全 clean |

### 100.7 阻塞 A2d 原子 Wigolo 迁移的问题（**需裁决**）

1. **chain 目前硬编码为 `(native_http,)`**：A2d 必须让 `available_backends` 动态化（读 provider availability + 配置），并且**同时开始消费 `route()`**（今天 `route()` 仍未被生产消费）。
2. **B2 预算守卫搬迁（§99.6-2 仍是硬门）**：`RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT`、per-run envelope、effective timeout 必须随 chain step 原子迁移；**不得出现"chain 已能调 Wigolo 但 guard 还在旧 escalation 内"的中间生产状态**。
3. **新发现：read loop 目前每个候选每 wave 只做一次 attempt**。Progressive Reader 需要"attempt → route → 可能再 attempt"（有界）⇒ A2d 必须把 read loop 改为**有界的多步 chain 执行**，而不是单次 attempt。
4. **新发现：attempt 预算与 outcome 唯一性**：`_attempt_number` / external-attempt 预算按 candidate 计数，而 cursor 强制**每 candidate 唯一 read outcome**。A2d 必须明确：第二个 backend 的 attempt 是否消耗同一预算，以及**多 backend 尝试如何与唯一 outcome 共存**（例如 outcome 记最终结果、attempt 明细进 `read_timing`）。
5. **A2d parity gate（裁决已冻结）**：旧 hidden escalation vs 新 explicit chain step 在相同 fixture 下必须一致：escalation eligibility / B2 budget decision / effective timeout / result projection / provenance 为超集不丢旧字段 / **无双调用** / candidate outcome 唯一性保持。**不允许借架构迁移调整这些阈值。**

### 100.8 范围合规

未做：真正接 Wigolo chain execution · 移除旧 `read_escalation` · 搬迁 B2 budget guards · provider-level breaker · A1b cross-run cache · browser/Crawl4AI · Discovery provider · timeout/retry 调参 · Evidence/Support/Gate/Answer · 新 ledger。

### 100.9 路线（三层模型已闭合）

```text
A0 ✅  A1a ✅  A1b ⏸ evidence-triggered
A2a ✅ lifecycle   —— 这个候选结束了吗？
A2b ✅ routing     —— 调用完以后下一步是什么？
A2c ✅ scheduling  —— 现在该调用谁？        （baseline d9b8dd8；2333/2）
A2d    explicit Wigolo + B2 budget 原子迁移（待裁决 §100.7）
A2e    Progressive Reader integration validation
A3     Browser bakeoff（Wigolo vs Crawl4AI）→ A4 Discovery bakeoff → A5
```


## §101 P2-A2d 进行中：A2d-1 outcome identity 迁移完成（`0301dec`）

**本刀按裁决拆 4 个内部切片，要求最终 production head 只存在一条执行权威、不得暴露半迁移状态。** 当前进度：**A2d-1 完成并提交；A2d-2/3/4 未开始。**

### 101.1 已完成的切片

**A2d-1（`0301dec`）—— 废除"每 candidate 唯一 RuntimeReadOutcome"**

- 旧不变量（`runtime.py` 校验）：`len(completed_read_ids) != len(read_outcomes)` → 报错。
- **新不变量**：**每 `(candidate_id, backend)` 最多一个 outcome**；`backend` 为空的历史行按 `native_http` 参与 key。
- 理由（按裁决）：outcome = **一个真实 backend attempt 的历史事实**；candidate completion = **reader-chain 层面的派生事实**（仍由 `candidate_resolution` 从完整 attempt 历史派生，唯一）。同 backend 的网络 retry 仍留在该 attempt 自身明细（`read_retries.attempts_detail`），不产生第二条顶层 outcome。
- 兼容性：pre-A2d 单 outcome cursor 继续可加载；**同一 candidate 的两条 legacy outcome 仍被拒绝**（与旧行为一致）。
- 测试（`tests/test_candidate_resolution.py` 追加 4 项）：两 backend 各一条 outcome 可共存且派生唯一 terminal resolution；同 backend 第二条被拒；legacy 行按 `native_http` 参与 key 且重复仍被拒；历史增长后 derived terminal 不摇摆。
- 该切片**零行为变化**（当前只有 `native_http` 写 outcome），因此不会暴露半迁移执行权威。

### 101.2 剩余切片（未开始，按裁决顺序）

| 切片 | 内容 | 关键约束 |
| --- | --- | --- |
| **A2d-2** | **bounded chain executor**：把 read loop 从"每候选每 wave 单次 attempt"升级为"attempt → route → next backend"的**显式有限 loop**，天然上界 = active chain 中 eligible unique backend 数（**不新增 `MAX_CHAIN_STEPS` 魔数**）；每步必须把 backend 记入 attempted，结构上不可能成环；**retry 不算 chain step** | 用 `chain_step` + outer attempt number 双标识 |
| **A2d-3** | **Wigolo B2 guards + executor 原子迁移**：`RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT`、per-run envelope、effective timeout 随 Wigolo 执行一起搬；**执行前必须重做 execution-time preflight**（scheduler 早先 eligibility ≠ 执行时预算权威） | 不允许借迁移调任何阈值 |
| **A2d-4** | **hidden escalation 退役 + parity/live validation**：`read_escalation` 只产 adequacy signal，不再内部调用 Wigolo；最终 head 只能有一条 next-backend execution authority | 禁止 old hidden + new explicit 并存 |

**chain 口径（冻结）**：A2d production 只启用 `native_http → wigolo_http`；**`wigolo_browser` 不启用**（留给 A3 bakeoff）。`DEFAULT_READER_CHAIN` 仅作 legacy fixture/tests/兼容回退，production 必须显式传当前 chain。

**`_attempt_number` 口径（冻结）**：保持旧 candidate/read-chain invocation 口径；Wigolo 显式化**不得凭空多消费一个旧 read-slot**（迁移 parity 的一部分）；Wigolo 自身 per-run envelope/timeout 照旧；**不发明新的全局 backend-call budget**。

**parity gate（冻结，已按裁决修正）**：escalation eligibility · B2 MIN_HARD · per-run envelope · effective timeout · final candidate result projection · usable content · provenance（只允许超集）· 无双调用 · retry policy 不变 · outer read-slot/attempt budget 不变 · 每 `(candidate, backend)` outcome 不重复 · candidate resolution 唯一 · evidence/support/gate/answer 不变。**RuntimeReadOutcome 行数增加是预期，不视为 regression。**

### 101.3 路线

```text
A0 ✅  A1a ✅  A1b ⏸
A2a ✅ lifecycle   A2b ✅ routing   A2c ✅ scheduling（d9b8dd8）
A2d    ← 进行中
  A2d-1 ✅ outcome identity（0301dec）
  A2d-2 ⏳ bounded chain executor
  A2d-3 ⏳ B2 guards 原子迁移
  A2d-4 ⏳ hidden escalation 退役 + parity/live
A2e    Progressive Reader integration validation
A3     Wigolo Browser vs Crawl4AI bakeoff
```


## §102 P2-A2d-2 bounded chain executor（`3f286cd`；TESTABLE, PRODUCTION-INERT）

**口径（按裁决）**：A2d-2/A2d-3 可分别提交，但**都必须保持 production inert**；真正的原子 cutover 只发生在 **A2d-4**。

### 102.1 executor 形状

`src/web/research/chain_executor.py`：

```text
run_chain(candidate_id, url, host, outer_attempt_number,
          chain, executors, record_outcome,
          attempted_backends, health_state_for, availability, backends, run_blocked)
```

流程：`schedulable_now()`（Phase 1：首个 backend）→ **execute** → `record_outcome`（**先落历史**）→ `route()`（Phase 2：下一步）→ `try_backend` 则继续，`resolve/block_run/defer/exhaust` 则停止。

数据模型：`ChainAttemptRequest`（invocation-local：candidate/url/host/backend/`chain_step`/`outer_attempt_number`）· `ChainStepResult`（backend/retrieval_state/attempted/usable_content/content/adequacy_reason/cost/policy）· `ChainStep`（`chain_step`/`outer_attempt_number`/backend/state/attempted/usable）· `ChainRun`（steps/action/reason/final_state/terminal/usable_content/attempted_backends/content）。

**两阶段保持分离**：`schedulable_now` 决定第一个 backend，`route` 决定每一个后续 backend；二者共用 `backend_eligibility`。executor **只执行与记录**，不写 Evidence/Support/Gate、无自有持久状态、不建 ledger。

**本切片顺带修掉一个真实缺口**：`RoutingContext` 此前**不带 availability** ⇒ `route()` 会把 provider 已下线的 backend 照常路由出去（`_eligible` 的 availability 形参从未被 `route` 传入）。现已让 availability 与 scheduling 一致地贯穿 routing。

### 102.2 loop 终止不变量（无魔数）

- **一个 backend 对同 candidate 最多真实 attempt 一次** ⇒ 天然上界 `len(chain)`；**不引入 `MAX_CHAIN_STEPS`**。
- `attempted_backends` **在 loop 内每步即时更新**（不是进入前算一次），因此 router **不可能**重新选择本次 invocation 刚执行过的 backend。
- `visited` 额外记录"作为当前步骤出现过"的 backend（含 policy skip），重复即停止并报 `router_repeated_backend`。
- 循环上界 `len(chain) + 1` **仅作安全网**（防契约违规的 router），命中报 `step_bound_reached`，不静默重试。
- 终止条件来自数据：`next ∉ attempted/visited` ∧ chain 有限。
- **retry 不是 chain step**：网络 retry 留在 backend 内部。

### 102.3 `_attempt_number` / `chain_step` 会计

- `outer_attempt_number` = 原 read-slot，**全链恒定**（测试断言两 step 都是 17）。
- `chain_step` = **invocation-local ordinal**（0,1,…），**不是 durable identity**；`ChainRun.to_dict()` 顶层不含 `chain_step`。
- durable identity 仍是 **`(candidate_id, backend)`**。
- 因此 Wigolo 显式化**不凭空多消费 read-slot**（迁移 parity 的一部分）。

### 102.4 focused tests（20 项，全部覆盖裁决的 13 条）

`tests/test_chain_executor.py`：native success → 一步结束；`not_found` → 不升级；fallback state → 进入下一 backend 并 `resolve`；**两条 `(candidate, backend)` outcome 共存**；同 backend 永不执行两次；chain 长度 1 不可能成环；**`outer_attempt_number` 全链恒定**；`chain_step = 0/1` 且非 durable；**policy skip 不产生 outcome**；provider 不可用 → `defer` 且**不执行**该 backend；health open → `defer`；budget block → 未 attempt 即停止；缺 executor → `no_executor` 且不重试；已 durable-attempted 不再调度；**契约违规 router 被安全停止**（不 spin）；不写 authority 字段；**retry 不是 chain step**（`"retry" not in ROUTING_ACTIONS`，每 backend 仅 1 次请求）；decision 可序列化。

### 102.5 "production 仍 inert" 的证明

1. **扫描测试** `test_production_does_not_call_the_chain_executor_yet`：遍历 `src/`（排除 `chain_executor.py` 自身）断言 **`chain_executor|run_chain` 零引用** ⇒ runtime/adapter/backend 均未接线。
2. `test_the_hidden_escalation_is_still_the_only_wigolo_callsite`：`read_escalation.escalate_read` 仍是唯一 Wigolo 执行入口。
3. 该切片**未改** runtime read loop、未改 `read_escalation`、未启用 `wigolo_browser`。

### 102.6 回归

| 项 | 结果 |
| --- | --- |
| focused | `test_chain_executor` **20 passed**；受影响集合 **168 passed** |
| **full pytest @ `3f286cd`** | **2357 passed / 2 failed**（768s）：**仅 2 个已知 Windows-local baseline 失败** ⇒ **零新增失败** |
| 对照 A2c（2333/2） | **+24 passed**（A2d-1 的 4 项 identity + A2d-2 的 20 项），失败族不变 |
| Ruff / tracked | clean |

### 102.7 剩余切片

```text
A2d-1 ✅ outcome identity（0301dec）
A2d-2 ✅ bounded chain executor（3f286cd）—— TESTABLE, PRODUCTION-INERT
A2d-3 ⏳ explicit Wigolo executor + B2 guards parity（TESTABLE, PRODUCTION-INERT）
A2d-4 ⏳ ATOMIC CUTOVER：启用 explicit chain + 退役 hidden escalation + parity/live
A2e    Progressive Reader integration validation
```


## §103 P2-A2d-3 explicit wigolo_http executor + B2 parity（`6b9ebc5`；TESTABLE, PRODUCTION-INERT）

**目标（按裁决）**：把 hidden `read_escalation` 内 Wigolo HTTP 执行抽成显式 `wigolo_http` backend executor，完整迁入/复用 B2 三项守卫，证明 old/new 执行语义等价。**不做 production cutover。**

### 103.1 explicit executor 最终形状

`src/web/research/wigolo_http_executor.py`：`WigoloHttpBackendExecutor` 实现 A2d-2 的 `BackendExecutor` 协议（`execute(ChainAttemptRequest) -> ChainStepResult`）。

执行顺序（冻结）：**mode/availability → execution-time B2 plan → preflight → 一次真实 fetch → charge envelope → canonical 投影 → `ChainStepResult`**。

- 输入只有执行真正需要的：`backend` / `max_chars` / `hard_seconds_left` / `charge_envelope` / `mode`；**不重新知道整个 runtime**。
- 输出 `ChainStepResult`（含 `retrieval_state` / `usable_content` / `content` / `adequacy_reason` / `cost` / `policy`），可直接投影为 `RuntimeReadOutcome` / `read_timing` / source provenance。
- **executor 自身不写 outcome、不改 candidate lifecycle、不调 `route()`、不写 Evidence/Support/Gate**；`execute → record_outcome → route` 顺序仍由 chain executor 掌控。

### 103.2 B2 guard：共享 helper，不是两份逻辑

`read_escalation` 新增 **`wigolo_http_execution_plan(hard_seconds_left, envelope_remaining_ms, min_hard_seconds) -> WigoloHttpExecutionPlan`**，统一回答三项：

```text
allowed / deny_reason / deny_layer
hard_headroom · min_hard_seconds · envelope_remaining_ms · effective_timeout_seconds
```

- **legacy `escalate_read` 与 new executor 都调用它** ⇒ parity 不是"两段代码恰好算得一样"，而是**两条入口共享同一预算真值**；A2d-4 删除 hidden execution 后该 helper 直接保留。
- **拒绝顺序/阈值/默认值/拒绝条件完全未改**：`hard_headroom_insufficient` → `run_envelope_exhausted` → effective-timeout floor（其 reason 保持原条件分支）。
- 新增 `deny_layer`（`hard_headroom` / `envelope` / `effective_timeout`）仅用于**忠实复现 legacy 的状态分派**：legacy 把 hard-headroom 拒绝记为 `unsupported`、其余记为 `skipped_no_budget`；canonical executor 一律记为 `budget_exhausted`。
- **execution-time preflight 仍拥有最终预算权威**：executor 在真正调用前重新计算 plan（scheduler 早先的 eligibility 不具权威）。

### 103.3 old/new parity 结果（表驱动，`tests/test_wigolo_http_executor.py` 20 项）

| 维度 | 结果 |
| --- | --- |
| eligibility / attempted | 一致 |
| MIN_HARD allow/deny + reason | 一致（`hard_headroom_insufficient`） |
| envelope allow/deny + reason | 一致（`run_envelope_exhausted`） |
| **envelope debit** | 一致（success 120ms 双方相同；拒绝时 0 消耗） |
| **effective timeout** | 一致（envelope clamp 1.5s；hard clamp 2.0s） |
| **actual request args** | 一致（url / max_chars / timeout_seconds） |
| success content / usable | 一致 |
| bytes / content_type | 一致（新侧 `cost` 携带） |
| cache_hit / rendered | 一致（保留） |
| failure 投影 | 语义一致（legacy `transport_error` ↔ canonical `timeout`） |
| provider unavailable | legacy `backend_unavailable` ↔ A0 `preflight` skip + detail |
| disabled capability | legacy `disabled` ↔ A0 `disabled` skip |
| short/empty response | 一致（不可用；canonical `invalid_content` + `short_doc`） |
| **outer attempt / read-slot** | 不变（chain 内恒定，见 A2d-2 测试） |
| retry semantics | 未触碰（仍在 backend 内部） |

**对照器做语义归一**（不是字符串相等）：legacy 说 §71B 词表（`ok`/`unsupported`），新侧说 A0 canonical（`success`/`budget_exhausted`）——这是**刻意的接口变更**，不是行为差异；测试显式记录该映射。

另有：`test_the_executor_plugs_into_run_chain` 证明 A2d-2 骨架能以 `native_http → wigolo_http` 驱动它（`chain_step 0/1`、outer attempt 恒定 3、两条 outcome、`resolve`）。

### 103.4 timing / provenance 投影

新 executor 的 `cost` 携带：`latency_ms`（= Wigolo 自身网络/执行时间）· `bytes` · `content_type` · `cache_hit` · `rendered` · `effective_timeout_seconds` · `preflight` · `raw_state`；`policy` 携带 `attempted`/`skip_reason`/`backend`。

**`escalation_ms` 的命运（本刀定调，A2d-4 执行）**：

- 新 explicit Wigolo **不再把自身 wall time 伪装成 `escalation_ms`**；它是**独立 backend attempt**，其成本进入自身 `fetch_ms`。
- 旧字段**保留兼容**（不删），但明确为 **legacy-only**：hidden escalation 退役后 `raw_read["escalation"]` 自然消失 ⇒ `escalation_ms` 归 0，**不再作为新 chain 的成本主字段**。
- **未新建 ledger**；投影继续复用 `RuntimeReadOutcome` / `read_timing` / `sources[]`。

### 103.5 focused / full regression

| 项 | 结果 |
| --- | --- |
| `test_wigolo_http_executor` | **20 passed**（parity 矩阵 + 共享 plan + 不碰 outcome/lifecycle + 可被 `run_chain` 驱动） |
| `test_chain_executor` | **18 passed**（production-caller 扫描已收窄为"runtime/adapter/escalation 无调用方"） |
| 受影响集合 | **219 passed**（含 `test_read_escalation` 15 项 legacy 回归全绿 ⇒ helper 提炼零行为变化） |
| **full pytest @ `6b9ebc5`** | **2375 passed / 2 failed**（765s）：**仅 2 个已知 Windows-local baseline 失败** ⇒ **零新增失败** |
| 对照 A2d-2（2357/2） | **+18 passed**，失败族不变 |
| Ruff / tracked | clean |

### 103.6 production-inert 扫描证明

1. **无生产调用方**：`test_production_has_no_caller_for_the_chain_executor_yet` 断言 `run_chain|chain_executor` 在 `src/application/active_research_runtime.py`、`src/web/research/active_adapter.py`、`src/web/research/read_escalation.py` **零引用**（收窄理由：backend adapter 实现协议类型是合法的，不能按"文本引用"判罚）。
2. `test_production_does_not_use_the_explicit_wigolo_executor_yet`：`src/` 全域（排除模块自身）**零引用** `WigoloHttpBackendExecutor`。
3. `read_escalation.escalate_read` **仍是 production 唯一 Wigolo execution 入口**。
4. `DEFAULT_READER_CHAIN == ("native_http",)` ⇒ **active production chain 尚未启用 `wigolo_http`**；`wigolo_browser` 未启用。

### 103.7 阻塞 A2d-4 atomic cutover 的问题（**需裁决**）

1. **read loop 必须换成 `run_chain`**：现在每候选每 wave 只做一次 attempt；A2d-4 要用 chain executor 取代，并由 runtime 提供 `record_outcome`（写 `RuntimeReadOutcome` + `read_timing` + `sources[]`）。这是 wiring 主体。
2. **`_attempt_number` 与 external-attempt marker**：chain 内两个 backend 共享一个 outer read-slot（裁决已冻结），但 `begin/finish_external_attempt` 目前是**每次读取一个 marker**。A2d-4 必须明确：**每个 chain step 各一个 marker（可审计）但不额外消耗 read-slot**。
3. **`escalation_ms` 落地**：A2d-4 删除 hidden escalation 后，`raw_read["escalation"]` 消失 ⇒ 该字段自然归 0；同时新 `wigolo_http` attempt 需要**自己的 `read_timing` 行**（`backend=wigolo_http`、`fetch_ms=cost.latency_ms`、`local_ms=投影耗时`），否则成本会丢。
4. **`sources[]` 投影**：一个候选两条 attempt 时，source 记录如何承载（保留最终 + 两条 attempt 明细，或最后一条覆盖）需要明确；`sources[].escalation`（§71C-3a 字段）随之成为 legacy。
5. **envelope 生命周期**：`reset_http_envelope()` 目前由 runtime 每 run 调用；cutover 后必须确保新 executor 的 `charge_envelope` 与 per-run reset 仍成对，否则 envelope 语义漂移。

### 103.8 路线

```text
A2d-1 ✅ outcome identity（0301dec）
A2d-2 ✅ bounded chain executor（3f286cd）
A2d-3 ✅ explicit wigolo_http executor + B2 parity（6b9ebc5）—— PRODUCTION-INERT
A2d-4 ⏳ ATOMIC CUTOVER：启用 explicit chain + 退役 hidden escalation + parity/live（待裁决 §103.7）
A2e    Progressive Reader integration validation
A3     Wigolo Browser vs Crawl4AI bakeoff
```


## §104 P2-A2d-4 裁决冻结 + 执行计划（**未开始**）

**状态**：A2d-1/2/3 已完成并提交；**A2d-4 尚未开始**。本刀是**原子 production cutover**（裁决明确：A2d-2/3 可 inert 分步，cutover 只在 A2d-4），因此**不做 inert 预切片**，必须一次完成并验证。

**基线**：`A2d-3 code = 6b9ebc5`；`A2d-3 doc = 0613732`；full pytest = **2375 passed / 2 known failed**。

### 104.1 三层数据模型（冻结）

> **backend attempt 历史 · candidate 最终 source · 外部调用审计 marker 分成三层。一个 candidate 可有多次 backend attempt，但只能有一个 candidate-level 最终投影。**

```text
2 backend attempts  !=  2 sources  !=  2 pieces of evidence
```

| 层 | 载体 | 粒度 |
| --- | --- | --- |
| 1. attempt history | `RuntimeReadOutcome` | **一个真实 backend attempt 一条**（`(candidate, backend)`） |
| 2. candidate 最终投影 | `sources[]` | **每 candidate / URL 最多一条顶层 source** |
| 3. Evidence | 既有 evidence 链 | 只消费最终 candidate source / usable result |

**source 记录形状（冻结）**：

```text
source
├─ final_backend / retrieval_state / usable content
├─ terminal（chain_exhausted 等）
└─ retrieval_attempts[]        ← 嵌套 attempt 明细
   ├─ native_http → shell_page
   └─ wigolo_http → success
```

`source` 投影规则（按裁决逐例）：

| 情形 | source |
| --- | --- |
| native 直接成功 | `final_backend=native_http`、success、attempts=[native success] |
| native short → Wigolo success | `final_backend=wigolo_http`、success、attempts=[native invalid_content/short_doc, wigolo success] |
| native 404 | `final_backend=native_http`、`not_found`、`usable=false`、attempts=[native not_found] |
| 两 reader 均失败 | `terminal=chain_exhausted`、`usable=false`、attempts=[native failure, wigolo failure] |
| **只有 policy skip，无真实 attempt** | **不制造 source read**（provenance 留在 metrics/policy 通道） |

**`sources[].escalation` 降级为 legacy-only**：历史可读；新 explicit-chain source **为空/缺省**；真实历史进 `retrieval_attempts[]`（避免未来 A3 第三 reader 时扩出 `escalation2/3`）。

### 104.2 marker / read-slot 分离（冻结）

```text
outer_attempt_number = candidate/read-chain invocation   （预算粒度，chain 内共享）
external-attempt marker = 每个真实 backend attempt 一个    （审计/trace 粒度）
```

- `native_http → wigolo_http` **共享同一个 outer attempt number**，**不额外消费 read-slot**。
- **冻结**：`external_attempt_count != read_slot_count` 是**预期行为**。
- **不产生 marker**：circuit-open skip · disabled · provider-unavailable preflight · budget guard deny · scheduler defer · route exhaust（无真实外部调用）。
- backend 内部 retry **不升级**为 chain-level marker（仍在 `attempts_detail`）。

### 104.3 timing 与成本守恒（冻结）

- 新 explicit chain：`native_http` 与 `wigolo_http` **各一条 `read_timing`**（`backend=wigolo_http`、`fetch_ms=cost.latency_ms`）。
- **新路径不再把 Wigolo 成本写进 `escalation_ms`**：新 explicit rows 该字段为 **0 或缺省→0**，标注 **legacy-only**；历史记录原值不动。**绝不出现 `native.escalation_ms = wigolo fetch`**（双重计量）。
- **timing accounting parity**：`legacy(native + escalation) ≈ new(native + wigolo)` —— 要求**总成本守恒（不漏记、不双记）**，不要求逐字段相等（schema 已合理升级）。

### 104.4 envelope run-scope（冻结）

- `reset_http_envelope()` **每 research run exactly once**；**禁止**在 candidate / wave / chain / executor 构造时 reset（否则 per-run envelope 直接失效）。
- charge 规则保持旧语义：真实 Wigolo call → 按旧规则 charge；preflight deny / disabled / provider unavailable / policy skip → **0 debit**。
- **必须测**：多 candidate 连续 Wigolo attempt 的 debit **累积**，并能触发与 legacy 一致的 envelope deny（run-scope parity，比单次 parity 更重要）。

### 104.5 recorder 职责边界（冻结）

```text
record_attempt_outcome()          ← 每真实 attempt 立即
├─ RuntimeReadOutcome
├─ backend-specific read_timing
├─ backend health accounting
└─ attempt provenance accumulator

run_chain terminal/defer/block/exhaust
        ↓
finalize_candidate_projection()   ← resolution 边界
        ↓
sources[] 最多一条 candidate source
```

理由：若 native `short_doc` 一写完就当顶层 source 发布、随后 Wigolo success 再覆盖，会出现**重复 source / 中间 failure 被 evidence 误读 / source count 短暂膨胀 / checkpoint 持久化半成品 source**。⇒ **attempt 立即落历史；candidate source 在 resolution 边界统一 materialize**。durability 要求每 step checkpoint 时，**保存 attempt history 即可**，不必提前宣布 candidate 已完成。

### 104.6 hidden escalation 退役（冻结）

最终 production head：`read_escalation` **只剩 adequacy/escalation signal**，**再无 Wigolo 执行权限**。禁止 hidden + explicit 同时活跃、禁止双 Wigolo call、**禁止 feature flag 形成两套 production authority**。

### 104.7 A2d-4 执行计划（建议顺序，单刀内完成）

1. runtime 新增 `record_attempt_outcome` / `finalize_candidate_projection`（三层模型落地）。
2. runtime 构造 active chain registry（`native_http` + `wigolo_http`）与两个 executor；**不启用 `wigolo_browser`**。
3. read loop 由单次 attempt 改为 `run_chain(...)`；`record_outcome` 接 1 的 recorder；每 chain step 一个 external marker（共享 outer read-slot）。
4. 删除 read 路径内的 `escalate_read` 调用；`read_escalation` 保留 signal 逻辑。
5. source 投影改为 candidate-level（嵌套 `retrieval_attempts[]`）；`escalation` 字段 legacy-only。
6. `read_timing` 按 backend 分行；`escalation_ms` 归 0/缺省。
7. 跑 §104.8 全部门禁。

### 104.8 A2d-4 验收门（19 + 5，冻结）

**基础 19 项**：native success 无 Wigolo · not_found 无 Wigolo · short_doc → explicit Wigolo → success · transport failure → Wigolo fallback · circuit-open native 可直接 Wigolo · Wigolo disabled/provider unavailable · B2 hard-headroom deny · per-run envelope deny/累积 debit · effective timeout parity · 无双 Wigolo call · retry semantics 不变 · outer read-slot 不变 · fallback case marker=2 且 outer slot=1 · 每 `(candidate, backend)` outcome ≤1 · candidate terminal resolution 唯一 · **`sources[]` 每 candidate ≤1** · **evidence/source count 不因 fallback 膨胀** · timing 成本守恒 · old cursor compatibility · resume 后 native 不重复 attempt · answer/evidence/support/gate 非回归。

**追加 5 项（按裁决）**：①source cardinality parity ②timing conservation ③marker vs budget separation ④run envelope accumulation（reset 每 run 恰好一次）⑤**durable resume：native 已完成、Wigolo 未完成时 checkpoint/resume，scheduler 不重复 native，从 Wigolo 继续**（A2d-1 multi-outcome cursor 的核心价值所在）。

**live evidence**：至少一条真实 `native_http → routing decision → wigolo_http`，证明 explicit chain 真执行、B2 guard 在新路径生效、两 backend outcome 可审计、source 仍只有一个、Wigolo 成本进独立 timing、hidden escalation 未执行、无 double call。若 docs.docker.com 仍阻塞导致 rescue 失败，可接受"explicit fallback attempted but failed"，但最好另找一个能产生 useful rescue 的 live case；**不得为 live gate 改 production policy**。

### 104.9 路线

```text
A2d-1 ✅  A2d-2 ✅  A2d-3 ✅（6b9ebc5）
A2d-4 ⏳ ATOMIC CUTOVER（§104 裁决已冻结，未开始）
A2d CLOSED（A2d-4 全绿后）→ A2e Progressive Reader integration validation → A3
```


## §105 P2-A2d-4 ATOMIC PRODUCTION CUTOVER — CLOSED（code `fc99a0d`；tools `dba7b19`/`01b14b4`；test `e0957c9`）

**结果**：A2d-1/2/3 的 inert 部件在**一刀内**切换为 production authority，hidden escalation **同刀退役**。Progressive Reader 首次真正运行在 production。

### 105.1 final production execution authority

```text
Runtime read loop
      ↓
ACTIVE_READER_CHAIN = ("native_http", "wigolo_http")
      ↓
run_chain   ← 唯一 reader-chain execution authority
      ├─ schedulable_now   （首个可执行 backend）
      ├─ NativeHttpBackendExecutor    （plain read，绝不 escalate）
      ├─ WigoloHttpBackendExecutor    （共享 B2 guards；identity = self.name）
      ├─ route             （下一个 backend / terminal）
      └─ finalize candidate projection
```

- **`run_chain` 是唯一能执行 reader 的权威**；`wigolo_browser` 未启用（A3）。
- **`read_escalation` 只剩 signal/compatibility**：`escalate_read` 保留为兼容函数（仍有单测），**任何 production 层都不再调用**。
- **无双 authority、无 feature flag**：`active_adapter.read()` 已是纯 native 委派，`_escalate_if_inadequate` 与 hidden `escalate_read` 调用被删除；adapter 只保留 backend factory（供 runtime 构建 chain executor）。

### 105.2 三层最终模型（落地，非纸面）

| 层 | 载体 | 粒度 | 实现位置 |
| --- | --- | --- | --- |
| attempt history | `RuntimeReadOutcome` | 每真实 `(candidate_id, backend)` 一条 | `record_read_chain_attempt` |
| candidate 投影 | `sources[]` | **每 candidate ≤1 条**，含 `final_backend` + 嵌套 `retrieval_attempts[]` | `_source_record(..., final_backend=, retrieval_attempts=)` |
| Evidence | 既有链路 | 只消费最终 candidate source | 未触碰 |

- `2 backend attempts ≠ 2 sources ≠ 2 evidences`：实测 5 candidates → 5 source rows（0 重复），其中一条含 2 个 attempt。
- **attempt 立即落历史；candidate source 在 resolution 边界统一 materialize**（`record_read_chain_attempt` 只写 outcome/timing/health，绝不写 `sources[]`）。
- 纯 policy/scheduling skip（无真实调用）**不产生 outcome、不产生 source**，provenance 留在 `read_scheduling` / `read_chain`。
- `sources[].escalation` 降级 legacy-only；新路径的真实历史进 `retrieval_attempts[]`。

### 105.3 marker / read-slot 分离

- 每个真实 backend attempt 一个 marker call_id（`research_read:{run}:{candidate}:attempt:{n}:{backend}`），全部共享该 candidate 的**单一 outer read-slot**（`_attempt_number` 未变）。
- `external_attempt_count != read_slot_count` 为预期。
- **诚实记录（bounded limitation）**：`RuntimeExternalAttemptStart` 在 cursor 中只保留 inflight 一个，begin/finish 成对执行后**不留 durable 记录**。因此 per-attempt 的**durable 审计粒度**实际是 `RuntimeReadOutcome(backend=…)` + `read_chain.steps` + failure 行的 `attempt_id`，而非 cursor 里的 marker。marker 调用保留以维持 inflight 不变量。

### 105.4 timing / accounting

- 每个 backend **独立 `read_timing` 行**（新增 `backend` 字段）；Wigolo 成本进自身行（`fetch_ms`）。
- 新 explicit 行 `escalation_ms = 0`（legacy-only）；**live 实测 7 行、0 个非零 `escalation_ms`**。
- 无双计：legacy `native + escalation` ↔ new `native + wigolo`，成本分别落在两行。
- 新增有界 `read_chain` metrics 通道（≤60 条），记录 chain 的 action/reason/attempted_backends/steps，**包括执行了 0 次的纯 skip**。未建新 ledger。

### 105.5 envelope run-scope

- `reset_http_envelope()` 每 run 恰好一次（run 入口），**不在 candidate/wave/chain/executor 构造时 reset**。
- 每个真实 Wigolo call 按旧规则 charge；preflight deny / disabled / provider unavailable / policy skip → **0 debit**。
- 实测：多 candidate 连续 Wigolo 的 debit 累积（`http_envelope_spent_ms() == latency × calls`），并有单测锁定。

### 105.6 退役证明（扫描 + 行为）

| 断言 | 结果 |
| --- | --- |
| `run_chain` 出现在 runtime | ✅（cutover guard） |
| `WigoloHttpBackendExecutor(` 出现在 runtime | ✅ |
| `escalate_read` / `_escalate_if_inadequate` 在 adapter 与 runtime | **零引用** ✅ |
| `ACTIVE_READER_CHAIN = (NATIVE_HTTP_BACKEND, WIGOLO_HTTP_BACKEND)` | ✅ 且 chain 内无 `wigolo_browser` |
| 死代码清理 | `breaker_allow` / `finish_read_attempt` / `_breaker_skip_payload` 已删除 |

### 105.7 focused / full regression

| 项 | 结果 |
| --- | --- |
| `test_active_research_runtime` | **60 passed**（含 5 项新 cutover 集成测试） |
| A0/A1a/A2a/A2b/A2c/A2d-1/2/3 套件（9 文件） | **244 passed** |
| qualification/probe 套件 | 98 passed（修正 1 处 source 投影键期望） |
| **full pytest @ `e0957c9`** | **2381 passed / 2 failed**（728s）——**仅 2 个已知 Windows-local baseline 失败** |
| 对照 A2d-3（2375/2） | **+6 passed**，失败族不变 ⇒ **零新增回归** |
| Ruff / `git diff --check` / tracked clean | clean |

### 105.8 live explicit `native_http → wigolo_http` evidence

`docs/research_quality/A2D4.live.r3.json`（`RESEARCH_WIGOLO_ESCALATION=http`，真实 Bing RSS + 真实 native read + 真实 Wigolo daemon，git_sha `01b14b4`）：

| candidate source | `final_backend` | attempts |
| --- | --- | --- |
| 1 | `native_http` | `[(native_http, success, usable)]` |
| 2 | **`wigolo_http`** | `[(native_http, invalid_content, usable), (wigolo_http, success, usable)]` |
| 3 | `native_http` | `[(native_http, success, usable)]` |
| 4 | `wigolo_http` | `[(native_http, http_denied, unusable), (wigolo_http, invalid_content, unusable)]` |
| 5 | `native_http` | `[(native_http, success, usable)]` |

- **explicit chain 真执行**：`read_chain` 5 组、每组恰好一次 chain invocation；1 组 `exhaust/all_backends_tried`，其余 `resolve/usable_content`。
- **B2 guard 在新路径生效**：Wigolo 只在 native inadequate 时被选为下一 backend。
- **两 backend outcome 可审计**：`read_timing` 7 行含两种 backend，2 行 `wigolo_http`。
- **source 仍只有一个**：5 sources / 5 unique candidates。
- **无 double Wigolo**：2 次真实 Wigolo call ↔ 2 条 wigolo outcome ↔ 2 条 wigolo timing。
- **hidden escalation 未执行**：adapter 零 `escalate_read`；`escalation_ms` 全 0。
- 第 4 例即裁决允许的 "explicit fallback attempted but failed"（docs.docker.com 类宿主仍不可达）。

### 105.9 已知 bounded 变化（非回归，已冻结）

1. **A1a breaker `allow()` 在 runtime 退役**：调度改由 `state_for`（eligibility）+ `record`（状态转移）承担；`half_open → closed` 仍由成功 record 驱动，但 `allow()` 的 `probe_index`/`is_probe` 逐次记账不再写入 read_timing。A1a 为默认 OFF 诊断；`allow()` 本身仍有单测。
2. **per-attempt marker 非 durable**（见 105.3）。
3. **`not_found` 不再二次 backend**（A2b 冻结语义）：native 404 → terminal，不再产生 legacy 的 "attempted=True, rescued=False" escalation 行。
4. **`_record_read_timing` 新增 `backend` 键**（additive）；旧行缺省按 `native_http`。

### 105.10 A2d CLOSED 与路线

```text
A2d-1 ✅ outcome identity          A2d-2 ✅ chain executor
A2d-3 ✅ explicit wigolo_http      A2d-4 ✅ ATOMIC CUTOVER（fc99a0d）
⇒ A2d CLOSED
A2e ⏳ Progressive Reader integration validation
A3  ⏳ Wigolo Browser vs Crawl4AI bakeoff
```

**无阻塞 A2e 的工程问题。** 唯一外部 blocker 仍是宿主可达性（docs.docker.com 类宿主不可达 ⇒ cold rescue 样本稀缺），但它只影响 live 样本丰富度，不阻塞 A2e 的集成验证设计。


## §106 A2d 封板 baseline 统一 + P2-A2e 冻结计划 + A3 方向锁定

**本刀只记录，不执行。** 无 production 变更、无 A2e 实施、不安装/接入 Crawl4AI。

### 106.1 A2d baseline 统一（消除 `fc99a0d` / `e0957c9` / `a9e5f41` 混用）

A2d 收口跨了 5 个 commit，必须区分三个身份，A3 bisect 时以 **code baseline** 为准：

| 身份 | SHA | 含义 |
| --- | --- | --- |
| **A2d code baseline（生产基线）** | **`fc99a0d`** | `feat(research): P2-A2d-4 atomic production cutover to the explicit reader chain`。**A2d 全部生产行为语义由它定义。A3 bisect / 对比 / 回退锚点用此 SHA。** |
| A2d regression-tested head | `e0957c9` | 实际跑 full pytest 的 head（**2381 passed / 2 known Windows-local baseline failures**）。 |
| A2d final/documentation head | `a9e5f41` | `docs: 105`。§105 记录所在 head。 |

**已验证的关键事实**：`git diff --name-only fc99a0d..e0957c9` = 仅 `tests/test_rq1c_bounded_qualification.py` + `tools/run_rq1c_bounded_qualification_core.py` + `tools/run_selection_authority_runtime_probe.py`；**`fc99a0d..HEAD -- src` 为空**。

⇒ `fc99a0d` 之后的三个 commit **零生产代码变更**（tools 投影 + test 期望 + docs）。
⇒ **A2d 的生产基线唯一且明确 = `fc99a0d`**；`e0957c9` 只是"在该生产代码上跑过全套测试的 head"。

**后续记录纪律**：凡提到 A2d 生产行为/回退/bisect，一律写 `fc99a0d`；提到测试证据写"@ `e0957c9`"；提到文档写对应 docs head。不再出现裸的 `A2d CLOSED（<sha>）` 单一 SHA 表述。

### 106.2 A2d 正式状态

```text
P2-A2d-1 ✅  P2-A2d-2 ✅  P2-A2d-3 ✅  P2-A2d-4 ✅
⇒ P2-A2d CLOSED（code baseline fc99a0d）
```

封板所满足的关键门：**唯一执行权威 + 预算语义保持 + attempt/source 分层 + live 明确 native→Wigolo + 零新增回归**。

**A2 做对了的结构性标志**：此后**新增 Reader backend 不应再要求修改 candidate lifecycle、scheduler 或 router 的核心语义**。A2e 之后必须守住这条。

### 106.3 P2-A2e 定位（冻结）

A2e **不设计新架构、不优化性能、不新增 backend/预算策略**。它只回答：

> 现在这套 Progressive Reader，在真实 heterogeneous conditions 下是否真的满足 A0→A2d 已冻结的 contract？

即把 A0→A2d 串起来做**集成验收**，而非重跑 unit tests。

### 106.4 A2e 六个 validation 维度（冻结）

#### 维度 1 — Reader-chain correctness（完整 runtime path）

```text
native success                → terminal
native not_found              → terminal，不 fallback
native short_doc/invalid_content → Wigolo
native transport failure      → Wigolo
native http_denied            → Wigolo
native circuit-open           → 不产生 native fake outcome，直接考虑 alternate
Wigolo unavailable            → defer/exhaust，无死循环
```

#### 维度 2 — Candidate lifecycle correctness（A2a 最终验收）

```text
attempt history → 唯一 candidate resolution → 最多一个 source projection
```

- 每 `(candidate_id, backend)` **≤1** 个 `RuntimeReadOutcome`
- 每 candidate **≤1** 个最终 source projection
- attempt 数可 >1，**evidence/source 数不因多 backend attempt 膨胀**
- `not_found` → terminal 且 unusable
- `chain_exhausted` → terminal 且 unusable
- `policy_deferred` → **非** terminal
- candidate resolution 唯一

#### 维度 3 — Budget / boundedness

观察：B2 hard-seconds guard、envelope debit、effective timeout、breaker open、scheduler defer、chain exhaustion。

成功标准**不是"快多少"**，而是：

> 每条 candidate chain 都有明确上界；失败路径不会无限重试/无限升级。

**重点专项**：`backend-local retry × reader-chain steps` **无组合爆炸**。

#### 维度 4 — Failure semantics（真实 + fixture 混合）

覆盖 canonical states：`403 / 404 / 429 / reset / timeout / invalid_content / shell(js_required) / anti_bot / provider unavailable / budget_exhausted`。

要求：

> canonical `retrieval_state` → routing decision → candidate lifecycle 三者**语义一致**。

禁止出现例如 `retrieval_state=reset` 却 `resolution=resolved, usable=true` 的语义穿帮。

#### 维度 5 — Provenance completeness

每个 fallback candidate 至少能回答：native 为什么没解决 / 为什么选 Wigolo / Wigolo 是否真执行 / 花了多少 / 最终哪个 backend 产出 source / candidate 是否 usable。

交叉核对字段：`RuntimeReadOutcome`、`read_timing`、`read_chain`、`sources[].retrieval_attempts[]`、`final_backend`、failure `attempt_id` —— 必须能互相串起来。

**已接受的 bounded debt**：per-attempt marker 非 durable（durable 审计已由 outcome + chain + failure id 覆盖）。**A2e 不为此开新工程。**

#### 维度 6 — Authority regression（最后一道门，最重要）

Progressive Reader 只能改变**"怎么拿到内容"**，不得改变：Evidence Authority / support semantics / claim binding / gate / answer availability rules。

做法：同一 candidate/evidence fixture，**旧单-reader-compatible case vs 新 progressive runtime**，确认在**无需 fallback** 的场景：

> 新系统**退化为旧系统等价行为**，而非因为多了 routing/scheduling 就改变结果。

### 106.5 A2e 样本规模（冻结，不追 N）

- **deterministic fixtures**：覆盖全部语义边界（维度 1/2/4 的主体）。
- **live cohort：6–10 runs**，强调**异质性**，至少含：
  - 正常静态 docs
  - short page
  - 403
  - 不可达 host
  - slow host（Node/doc 类）
  - ≥1 个 Wigolo **rescue**
  - ≥1 个 Wigolo **attempted-but-failed**

**docs.docker.com cold-rescue 缺口**：继续作为 **external evidence debt**，**不做无限 cold hunt**。

### 106.6 A2e 成功指标（冻结，5 条）

**不使用** "Wigolo rescue rate > X%"。使用：

1. 正确路由
2. 失败有界
3. candidate lifecycle 正确
4. provenance 完整
5. authority 不变

全绿 + full regression 无新增失败 ⇒ **P2-A2 Progressive Reader CLOSED**。

### 106.7 A2e 收口后的路线

```text
A2d ✅ CLOSED（fc99a0d）
A2e ← 当前阶段（本刀只记录，未开始实施）
  ↓ 全绿
P2-A2 Progressive Reader CLOSED
  ↓
P2-A3 Browser Backend Bakeoff — Wigolo Browser vs Crawl4AI
```

### 106.8 P2-A3 方向预锁（仅锁定，不在 A2e 实施）

A3 **不再比较普通 HTTP reader**。它回答：

> 当 Progressive Reader 已判定需要 **rendered/browser capability** 时，哪个 backend 最适合承担 `BrowserBackend` 角色。

候选：`Wigolo Browser` vs `Crawl4AI`。

比较维度（冻结）：JS-render success / anti-bot handling / session capability / PDF / latency / VRAM-RAM / daemon stability / provenance / integration complexity / license-maintenance。

A3 目标**不是"选功能最多的"**，而是：

> 选一个最适合成为 `BrowserBackend` 的实现。

**本刀（含 A2e 期间）禁止提前安装或接入 Crawl4AI。**

### 106.9 下一执行刀（明天）

```text
P2-A2e — Progressive Reader Integration Validation
禁止：新增架构 / 优化 / backend / 预算策略
只做：验证 A0→A2d 串联后的 production behavior 是否满足冻结合同
```

执行顺序建议：维度 6（authority regression，先钉死"不变"）→ 维度 1/2/4（fixture 语义边界）→ 维度 3（boundedness 专项）→ 维度 5（provenance 交叉核对）→ live cohort 6–10 runs → full regression → 收口。


## §107 P2-A2e PROGRESSIVE READER INTEGRATION VALIDATION — CLOSED（validation head `b1a5d24`）

**结果**：A0→A2d 串联后的 production behaviour 通过六个冻结维度的验收。**P2-A2 Progressive Reader CLOSED。**

本阶段未新增架构、backend、预算策略或优化。唯一 production 变更是一处由验收发现的 **timing 归因缺陷修复**（见 107.4），属 §104 合同要求的修正，不是新能力。

### 107.1 baseline 记账（承接 §106.1 纪律）

| 身份 | SHA | 含义 |
| --- | --- | --- |
| A2d code baseline | `fc99a0d` | A2d 生产语义（未变） |
| **A2e validation head（新生产基线）** | **`b1a5d24`** | A2e 测试 + `wigolo_http_executor` timing 修复。**A3 bisect 用此 SHA。** |
| A2e regression-tested head | `b1a5d24` | full pytest 两次（见 107.6） |
| A2e 文档 head | 本 §107 commit | |

⇒ **`fc99a0d` 与 `b1a5d24` 的生产差异仅一处**：`WigoloHttpBackendExecutor._project` 的 `cost` 增加 `fetch_ms`（外加异常路径补 `fetch_ms: 0.0`）。无行为语义变更（`read_timing` 为 observation-only 通道）。

### 107.2 六维度验收结果

新增 `tests/test_active_research_runtime.py` §107 区块，**28 项**集成测试，全部走真实 runtime read loop。

| 维度 | 验收 | 结果 |
| --- | --- | --- |
| 1 Reader-chain correctness | 10 组表驱动（success / not_found / short_doc / reset / timeout / 403 / 429 / shell_page / anti_bot / login_required）+ circuit-open + alternate-unavailable | ✅ |
| 2 Candidate lifecycle | 每 `(candidate, backend)` 唯一 outcome；每 candidate 唯一 source；attempt 数 >1 不膨胀 source/evidence；not_found / chain_exhausted terminal 且 unusable；deferred 非 terminal 且无 outcome/source | ✅ |
| 3 Boundedness | backend-local retry × chain steps 无组合爆炸；envelope run-scoped 且 ≤ 3s 上界；每真实 call 一条 timing；breaker open → defer，native 只被规划一次 | ✅ |
| 4 Failure semantics | 8 状态表：`retrieval_state → routing decision → lifecycle` 三方一致；`final_backend` 永远指向产出内容的 attempt | ✅ |
| 5 Provenance | outcome ↔ read_timing ↔ read_chain ↔ `sources[].retrieval_attempts[]` ↔ `final_backend` ↔ failure `attempt_id` 可互串 | ✅（发现并修复 107.4） |
| 6 Authority regression | `ESCALATION_ENV` off vs on（native 充足、alternate 从未被调用）→ **authority artifacts 逐字段相等** | ✅ |

### 107.3 维度 1 冻结路由（实测，非推断）

| native 状态 | chain 决策 | steps | 调用 alternate | final_backend | read_status |
| --- | --- | --- | --- | --- | --- |
| success | resolve / usable_content | native | 否 | native_http | read |
| not_found | resolve / terminal_resource_outcome | native | **否** | native_http | failed |
| invalid_content (short_doc) | resolve / usable_content | native + wigolo | 是 | wigolo_http | read |
| reset / timeout | resolve / usable_content | native + wigolo | 是 | wigolo_http | read |
| http_denied (403) / rate_limited (429) | resolve / usable_content | native + wigolo | 是 | wigolo_http | read |
| shell_page | resolve / usable_content | native + wigolo | 是 | wigolo_http | read |
| anti_bot / login_required | **exhaust / no_capable_backend** | native | **否** | native_http | failed |
| circuit-open (native unhealthy) | schedule → alternate；native 记为 blocked | — | 视 alternate 可用性 | — | — |
| alternate unavailable | **exhaust / all_backends_tried** | native（skip 不入 attempt） | 否（0 次 fetch） | native_http | 按 native 结果 |

- **anti_bot / login_required 在当前链是 terminal exhaust**（需要 `anti_bot_recovery` / `session`，`wigolo_http` 不具备）——这正是 A3 browser tier 的入口，不是缺陷。
- **policy-skipped step 不进入 `read_chain.steps`，也不进入 `sources[].retrieval_attempts[]`**，且不产生 outcome：provenance 只记录**真实 attempt**。

### 107.4 A2e 唯一 production 修复：alternate 的 `fetch_ms` 归因

**发现**：维度 5 交叉核对时，`wigolo_http` 的 `read_timing` 行 `fetch_ms = 0.0`，整段调用延迟被计入 `local_ms`。

**根因**：`record_read_chain_attempt` 从 `cost["fetch_ms"]` 取网络耗时；native executor 的 cost 含 `fetch_ms`，而 `WigoloHttpBackendExecutor._project` 的 cost **没有** `fetch_ms`，于是 `retry_fetch_ms=None → 0.0`。

**违反的冻结条款**：§104「每 backend 一条 `read_timing`（`backend=wigolo_http`、`fetch_ms = cost.latency_ms`）」与 F2-O3a「`local_ms` = 去掉网络等待与 backoff 后的剩余」。

**影响面**：仅 observation-only 的 `read_timing` 通道；**不进入调度、admission、breaker 或 policy**，`wall_ms` 与 envelope debit 本就正确 ⇒ 无行为影响，但成本守恒（不漏记）被破坏。

**修复**（`src/web/research/wigolo_http_executor.py`）：`_project` 的 cost 增加 `fetch_ms = artifact.latency_ms`；异常路径补 `fetch_ms: 0.0` 以保持形状一致。native 路径不变（其 cost 本就有 `fetch_ms`）。

**回归锁定**：维度 5 测试断言 alternate 行 `fetch_ms > 0`；live cohort 复检 `wigolo_http` timing 行 `fetch_ms ≤ 0` 计数 = **0**。

### 107.5 live cohort（8 runs，异质性优先）

`RESEARCH_WIGOLO_ESCALATION=http`、`WIGOLO_RERANKER=off`、真实 Bing RSS + 真实 native read + 真实 Wigolo daemon（`/health` = healthy, browsers ready）。产物在 `%TEMP%\opencode\a2e_live\*.json`（未跟踪）。

| 指标 | 值 |
| --- | --- |
| runs | 8（6 个真正进入 reader 层；`simple-license-uv` / `numeric-uk-bank-rate` 未产生 read plan，**无 reader 层信号**，属上游 search/assessment 结果） |
| sources | 21，**0 重复 candidate** |
| chain shapes | `(native_http,)` ×11、`(native_http, wigolo_http)` ×10；**无其他形状、无 loop、无 wigolo-only** |
| chain reasons | `usable_content` ×11、`all_backends_tried` ×5、`run_blocked` ×1 |
| **Wigolo rescue** | **5**（native 不足 → alternate 产出可用内容） |
| **Wigolo attempted-but-failed** | **5** |
| native attempt states | success 10、invalid_content 7、**http_denied 2（403）**、**reset 1（不可达 host）**、timeout 1 |
| wigolo attempt states | success 5、invalid_content 2、timeout 3 |
| `final_backend` 分布 | native_http 12、**wigolo_http 9** |
| hosts | 16 个（含 nodejs.org / node.org.cn / nodejs.cn 慢宿主族、www.docker.com、github.com、python.org、postgresql.org、zhihu / csdn / runoob） |
| **provenance/timing 违规** | **0** |
| **缺失 `final_backend` 的 source** | **0** |

**异质性清单对照 §106.5**：正常静态 docs ✅ / short page ✅ / 403 ✅ / 不可达 host ✅ / 慢宿主（Node 族）✅ / Wigolo rescue ✅ / Wigolo attempted-but-failed ✅。

**docs.docker.com**：本 cohort 中 `www.docker.com` 有 1 条 source，仍不构成 cold-rescue 证据；该缺口**继续作为 external evidence debt**，不再无限 hunt（§106.5）。

### 107.6 full regression（两个候选 head 运行）

| run | 结果 | 失败明细 |
| --- | --- | --- |
| #1 @ `b1a5d24` | **2407 passed / 4 failed** | 2 已知 Windows-local baseline + 2 负载型 flake |
| #2 @ `b1a5d24` | **2408 passed / 3 failed** | 2 已知 baseline + 1 已知 flake |

**两个 flake 的定性与证据**：

1. `test_cross_layer_regression::test_news_query_change_invalidates_downstream_stages`（`/news/runs/{id}/search` → 502）
   - 单独跑通过；与 `test_agent_loop_prototype.py` 同批跑复现 502。
   - **决定性证据**：在 `git worktree` @ `eaf0a97`（A2e 之前，production == `fc99a0d`）以**相同两文件顺序**运行，**同样复现** ⇒ **pre-existing 测试顺序/环境 flake，与 A2e 无关**。
2. `test_agent_loop_prototype::test_same_inputs_produce_identical_outcomes`（断言 `elapsed_seconds` 相等，实测 `0.0 != 0.016`）
   - 纯 wall-clock 抖动断言，负载敏感；单独跑与两文件跑均通过。

⇒ **本 head 的 full-suite 失败集 = 已知 baseline 族 + 已知 flake，零新增回归。**
⇒ 候选 head 计数对照：A2d-4 = 2383 collected（2381 pass）→ A2e = **2411 collected（+28，全部为新增 A2e 测试）**。

### 107.7 A2e 成功指标（§106.6 五条）

| 指标 | 结论 |
| --- | --- |
| 正确路由 | ✅ 10 组表驱动 + live 21 条 source 形状全部符合冻结矩阵 |
| 失败有界 | ✅ retry×chain 无组合爆炸；envelope ≤ 3s；breaker open → defer；native 只规划一次 |
| candidate lifecycle 正确 | ✅ 唯一 outcome / 唯一 source / terminal 语义正确 |
| provenance 完整 | ✅ 六个 artifact 互串；0 违规；1 处归因缺陷已修复并锁定 |
| authority 不变 | ✅ off/on 逐字段相等（D6） |

**⇒ P2-A2 Progressive Reader CLOSED。**

### 107.8 已知 bounded debt（继承，不在 A2e 修）

1. per-attempt marker 非 durable（§105.3）——durable 审计由 outcome + chain + failure `attempt_id` 覆盖。
2. A1a `breaker.allow()` 在 runtime 退役（§105.9）。
3. `not_found` 不再二次 backend（A2b 冻结语义）。
4. docs.docker.com cold-rescue 缺口 = external evidence debt。
5. `anti_bot` / `login_required` 在当前链为 terminal exhaust —— 由 A3 提供 browser/session 能力。
6. 两个负载型 flake（107.6）为仓库既有测试债务，非 A2e 引入。

### 107.9 路线

```text
A2d ✅ CLOSED（code baseline fc99a0d）
A2e ✅ CLOSED（validation head b1a5d24）
⇒ P2-A2 Progressive Reader CLOSED
A3 ← 下一阶段：Browser Backend Bakeoff — Wigolo Browser vs Crawl4AI
```

**A3 启动前的硬约束**：新增 Reader backend **不得要求修改 candidate lifecycle、scheduler 或 router 的核心语义**（§106.2）。A3 只在既有 capability 词表（`js_render` / `anti_bot_recovery` / `session` / `pdf`）内注册新的 `BackendCapability` 并接入 `ACTIVE_READER_CHAIN`。**A3 尚未开始，禁止提前安装/接入 Crawl4AI。**


## §108 P2-A3-0 BROWSER BACKEND BAKEOFF CONTRACT — FROZEN（code `47a2938`）

### 108.1 阶段状态

```text
P2-A2 Progressive Reader        ✅ CLOSED
├─ A2a lifecycle ✅   A2b routing ✅   A2c scheduling ✅
├─ A2d explicit Wigolo HTTP ✅（code baseline fc99a0d）
└─ A2e integration validation ✅（validation head b1a5d24）

P2-A3 Browser Backend Bakeoff   ← 当前
├─ A3-0 contract / fixtures      ✅ CLOSED（47a2938）
├─ A3-1 Wigolo Browser adapter   ⏳
├─ A3-2 Crawl4AI adapter         ⏳
└─ A3-3 head-to-head + winner    ⏳

P2-A4 Discovery Bakeoff → P2-A5 Heterogeneous Integration
→ P2-B Synthesis → P2-C Semantic Audit → P2-D Chart/Diagram/Plan → P2-E Artifact Audit
```

**A3 只回答一个问题**：当 A2 routing 已判定普通 reader 能力不足时，哪个 `BrowserBackend` 更适合作为 production rendered-reader？

A3 **不是**"接两个 browser 看谁能跑"。最大风险已从架构转移到 **把 browser 当成万能 fallback 导致成本失控**。

### 108.2 A3-0 交付物

| 交付物 | 路径 |
| --- | --- |
| 冻结合同（production-inert 模块） | `src/web/research/browser_bakeoff.py` |
| 冻结 fixture manifest | `tests/fixtures/research_quality/browser_bakeoff_manifest.json` |
| 合同验收测试（28 项） | `tests/test_browser_bakeoff_contract.py` |
| fixture 格式文档 | `tests/fixtures/research_quality/README.md`（新增 Browser Bakeoff Manifest 节） |

manifest 由合同**生成**（非手写）以保证不漂移；改合同必须重新生成。

### 108.3 冻结的 6 个 fixture 类

| 类 | capability demand | 期望 routing | 期望 browser 调用 |
| --- | --- | --- | --- |
| `static_control` | （空） | `resolve` | **否** |
| `js_shell` | `js_render` | `try_backend` | 是 |
| `spa_delayed_render` | `js_render` | `try_backend` | 是 |
| `anti_bot` | `anti_bot_recovery` | `try_backend` | 是 |
| `session_required` | `session` | `try_backend` | 是 |
| `document_heavy` | `pdf` | `try_backend` | 是 |

- capability demand 必须 ⊆ **冻结能力词表**（`plain_http` / `content_extraction` / `js_render` / `session` / `anti_bot_recovery` / `pdf`）；**A3 不发明新能力词**。
- **static control guard（关键）**：`static_control.expect_browser_call` 必须为 `false`。BrowserBackend 不仅要证明"能救复杂页"，还要证明 **"routing 不该叫它时不会被无谓启动"**。
- 各类 `success_definition` 机器可校验；只有 `session_required` 允许 `usable_content_required=false`（**诚实的 `login_required` 可接受，把登录页当正文静默返回不可接受**）。
- 每类 `targets[].kind` ∈ `public_url` | `synthetic_local`；url 唯一。JS shell / SPA / anti-bot / session 使用 `synthetic_local`（A3-1/A3-2 落地本地 fixture server），static control 与 document-heavy 保留稳定 `public_url`。

### 108.4 统一预算（复用，不重述）

`BAKEOFF_UNIFIED_BUDGET` **引用 A2 冻结常量**而非重写字面量：

| 键 | 值 | 来源 |
| --- | --- | --- |
| `min_hard_seconds_left` | 3.0 | `HTTP_MIN_HARD_SECONDS_DEFAULT`（FROZEN） |
| `run_envelope_seconds` | 3.0 | `HTTP_RUN_ENVELOPE_DEFAULT`（FROZEN） |
| `effective_timeout_floor_seconds` | 1.0 | `EFFECTIVE_TIMEOUT_FLOOR_SECONDS` |
| `max_chars` | 20000 | `WIGOLO_FETCH_MAX_CHARS` |
| `per_page_timeout_seconds` | 20.0 | bakeoff-only 参数，两侧相同 |

⇒ **同一组页面、同一 capability demand、同一超时预算**；manifest 校验强制 `budget` 精确等于该映射，**一侧无法拿到比另一侧（或比 production）更大的预算**。

### 108.5 比较维度（15 项，方向预注册）

`js_render_success` / `shell_rescue` / `anti_bot_recovery`（higher_better）；
`session_capability` / `document_support` / `failure_transparency` / `provenance_completeness` / `budget_boundedness` / `static_control_silence`（required）；
`latency_warm_ms` / `cold_start_ms` / `resident_memory_delta_mb` / `daemon_restarts` / `integration_complexity` / `maintenance_burden`（lower_better）。

**required 维度必须在任何 rate 比较之前全部达标**（含 `static_control_silence`）。

### 108.6 provenance 要求（复用 A2 artifact，不建新 ledger）

`runtime_read_outcome` / `read_timing` / `read_chain` / `source_retrieval_attempts` / `final_backend` / `failure_attempt_id`。
每个真实 attempt 必须能回答：为什么普通 reader 没解决 / 为什么选 browser / browser 是否真执行 / 花了多少 / 哪个 backend 产出 source / candidate 是否 usable / **失败是否被诚实分类**。

### 108.7 winner criteria（预注册）

- **disqualifiers**：`browser_started_on_static_control` / `budget_exceeded` / `missing_canonical_retrieval_state` / `provenance_incomplete` / `requires_core_semantics_change` / `chain_longer_than_max`。
- **三种结果**：
  1. **Wigolo Browser 明显胜出** → production 只留 Wigolo Browser。
  2. **Crawl4AI 明显更稳/更透明** → production 选 Crawl4AI，Wigolo 保留 HTTP reader。
  3. **能力互补** → 一个主 `BrowserBackend`，另一个仅作 capability-bounded 特殊 fallback，**且不得把链延长超过 `BROWSER_CHAIN_MAX_LENGTH = 3`**。
- **默认目标仍是：选一个主 BrowserBackend。** 第 3 种是防滥用对象：`native → wigolo_http → browser_A → browser_B` 很容易把 bounded chain 重新变成长尾链。
- **tie-break 顺序**：failure transparency / provenance → maintenance burden → 已可通过既有 daemon 触达者（`wigolo_browser`，因为集成复杂度是长期成本）。

### 108.8 硬边界：A3 不得修改 A2 核心语义

`FORBIDDEN_CORE_CHANGES` 明确列出：`candidate_resolution.resolve_candidate` / `RESOLUTION_STATES`、`progressive_routing.route` / `schedulable_now` / `backend_eligibility` / `ACTION_*`、`chain_executor.run_chain`、`failure_taxonomy.RETRIEVAL_STATES` / `classify`。

Browser backend **只能**做三件事（`ALLOWED_ADAPTER_SURFACE`）：

```text
注册 BackendCapability
↓
实现 BackendExecutor
↓
进入现有 chain
```

> 如果接 Crawl4AI 时发现必须重写 `candidate_resolution` / `route()` / `schedulable_now()`，**说明 adapter 设计错了，而不是核心该改**。

### 108.9 A3-0 未进入 production（已验证）

- 合同模块**零** production 引用：`browser_bakeoff` 不出现在 `active_research_runtime.py` / `active_adapter.py` / `chain_executor.py` / `progressive_routing.py` / `candidate_resolution.py` / `wigolo_http_executor.py`。
- `capability_registry()` 名称集仍为 `{native_http, wigolo_http, wigolo_browser}`，**`crawl4ai` 未注册**。
- `ACTIVE_READER_CHAIN = (NATIVE_HTTP_BACKEND, WIGOLO_HTTP_BACKEND)` 不变；runtime 中无 `WIGOLO_BROWSER` 符号使用。
- **`crawl4ai` 未安装**（A3-0 期间禁止安装/接入）。
- 上述均由测试锁定（含 production-inert 扫描 + 11 项 fail-closed 负向控制）。

### 108.10 A3 分刀计划与门

```text
A3-0 ✅ bakeoff contract / fixtures（本刀）
A3-1 ⏳ Wigolo Browser adapter（对同一 contract 通过）
A3-2 ⏳ Crawl4AI adapter（对同一 contract 通过）
A3-3 ⏳ head-to-head cohort + winner decision
```

**A3-3 之前不得把两个 browser 同时放进 production chain。** 先各自通过同一 contract，再做对照。
A3-3 结论必须引用本 §108 的预注册维度与 disqualifier，**不允许事后改判据**。

### 108.11 下一执行刀

```text
P2-A3-1 — Wigolo Browser adapter
- 只允许：注册 BackendCapability(js_render / anti_bot_recovery / session / pdf 中实际具备者) + 实现 BackendExecutor
- 不得改 A2 核心语义（§108.8）
- 不得接入 Crawl4AI
- 必须对 A3-0 contract 的 6 类给出可复算结果，并保留 A2 六个 provenance artifact
- static_control 必须零启动
```


### 108.12 A3-0 门禁证据

| 项 | 结果 |
| --- | --- |
| 合同测试 `tests/test_browser_bakeoff_contract.py` | **28 passed**（含 11 项 fail-closed 负向控制 + production-inert 扫描） |
| Ruff | clean |
| `git diff --check` / tracked clean | clean |
| **full pytest @ `af71a6f`** | **2436 passed / 3 failed**（877s） |
| 失败明细 | 2 已知 Windows-local baseline + 1 已在 §107.6 定性的 pre-existing flake（`test_cross_layer_regression::test_news_query_change_invalidates_downstream_stages`，在 `eaf0a97` 已复现） |
| collected 对照 | A2e 2411 → **A3-0 2439（+28，全部为新增合同测试）** |

⇒ **零新增回归。** A3-0 为纯增量（新 production-inert 模块 + fixture + 测试），未触碰任何 A2 production 文件（`git diff --name-only` 中 `src/` 仅新增 `browser_bakeoff.py`）。

**A3-0 CLOSED。** 下一刀 **A3-1 Wigolo Browser adapter**（禁止接入 Crawl4AI；禁止改 A2 核心语义）。


## §109 STAGED REGRESSION POLICY (L0–L3) — FROZEN（code `16cdfa8`）

**结果**：项目已过早期高风险阶段，"每个小切片都跑 10–15 分钟全量 pytest" 的 ROI 已明显下降。测试门禁正式改为 **分层门禁**，从 **P2-A3 起生效**，取代此前的"每 candidate head 全量 pytest"默认。

规范 owner：**`AGENTS.md` §4（Test execution policy — Staged Regression Policy）**。本节是状态记录与理由，不与其冲突。

### 109.1 四层

| 层级 | 何时跑 | 内容 |
| --- | --- | --- |
| **L0 快速门** | 每个小提交 | Ruff + `git diff --check` + tracked worktree clean |
| **L1 Focused** | 每个实现切片 | 该切片的 **impact set**（自身模块测试 + 所有直接受影响测试 + 下一层） |
| **L2 阶段集成门** | 每个子阶段收口（Ax / Bx / Cx） | 该子阶段整套 stack + 相邻合同测试 + 关键 regression |
| **L3 Full regression** | 大阶段封板（P2-A / P2-B / …）、production cutover、发布前 | 全量 `pytest tests` |

默认节奏：**小刀 focused，子阶段 integration，大阶段 full。**

### 109.2 L1 不是"只跑一个测试文件"

每个切片声明 **impact set**，派生规则：

> 该切片自身测试文件 + 所有引用了该切片改动符号的测试 + 其**正下方那一层**。

命名集合落在 `tests/stage_gates.json`。例（A3 browser adapter）：`test_browser_backend.py` + `test_progressive_routing.py` + `test_scheduling.py` + `test_candidate_resolution.py` + `test_active_research_runtime.py` 的 browser/fallback 子集。

### 109.3 L2 阶段集成门（P2-A retrieval subsystem regression）

命名门 `p2-a-retrieval-stack` = **A0 taxonomy + A1 breaker + A2 lifecycle/routing/scheduling/chain + A3 browser** 整条检索栈。**不含** synthesis、agent loop 及其它无关模块。

固定命令（避免手打参数列表漂移）：

```bash
python tools/run_stage_gate.py --list
python tools/run_stage_gate.py --impact-set a3_browser
python tools/run_stage_gate.py --stage p2-a-retrieval-stack
python tools/run_stage_gate.py --stage p2-a-retrieval-stack --print-paths
```

`tools/run_stage_gate.py` 只是 manifest reader（约 80 行），**不是框架**：读 `tests/stage_gates.json` → 校验路径存在 → 交给 pytest。

**实测（`16cdfa8`）**：`--stage p2-a-retrieval-stack` = **400 passed / 201s（3m21s）**，对照全量 14–15 分钟。

### 109.4 必须提前触发 L3 的情况

即使未到阶段封板，以下**强制 L3**：

1. 改**共享核心数据模型** — `RuntimeReadOutcome`、candidate lifecycle、routing/scheduling contract、Evidence/Support/Gate；
2. **production authority cutover**（如 A2d-4 的唯一执行权威切换）；
3. **持久化 schema / cursor compatibility**；
4. 大范围**跨层 refactor**；
5. focused test 出现**未知原因**失败；
6. **行为语义漂移**，无法证明只局部影响。

普通 adapter、instrumentation、fixture、provider 接入**不**触发 L3。

### 109.5 L3 规则（沿用）

每个 candidate head 跑一次全量；仅当此后 production code / runtime behaviour / 序列化契约 / 大范围 test infra / 影响运行时的依赖配置发生变化时，才允许第二次全量。docs / PR 文本 / 注释 / 纯格式 / 测试名清理**不**需要重跑。

### 109.6 门禁顺序

```text
L0 + L1（每切片默认）：Ruff → 受影响 focused → git diff --check → worktree clean → diff-scope audit
L2（子阶段收口）：L0 + L1 + 命名 stage gate
L3（大阶段封板 / cutover / 发布前）：L0 + L1 + L2 + full pytest，再 Ruff → diff --check → worktree clean → diff-scope audit
```

mypy 仅在本仓库声明 baseline/config 时运行；本仓库未声明，故**不在门禁内**（与 A2d/A2e/A3-0 实际做法一致）。

### 109.7 A3 起的应用

```text
A3-0 contract          → L0 + L1（已完成；因新模块为 production-inert，未强制 L3）
A3-1 Wigolo Browser    → L0 + L1
A3-2 Crawl4AI          → L0 + L1
A3-3 bakeoff / winner  → L0 + L1 + L2
P2-A3 CLOSED           → L3 full pytest 一次
```

**A3 内部不再每刀跑 full pytest。** A4、A5 同理。
若 A3-3 仅为 bakeoff、未改 production chain，则可将 L3 推迟到**真正的 production activation**。

### 109.8 retro-application（不改写历史）

按本策略：**A2d-1 / A2d-2 / A2d-3 / A3-0 本不需要 L3**；**A2d-4（authority cutover）与 A2e（子阶段收口）需要**。
已执行过的全量运行仍是有效证据，**不为了"合规"重跑**。

### 109.9 防漂移

`tests/test_stage_gates_policy.py`（10 项）锁定：

- manifest schema / owner / `applies_from` / 四层齐备；
- 每个 impact set 与 stage gate **非空且路径真实存在**（重命名测试文件而不更新策略 → 直接失败）；
- `p2-a-retrieval-stack` **精确等于**九个 retrieval impact set 的并集（L2 不得静默漏掉一层）；
- L2 **排除**无关子系统（synthesis / answer streaming / RQCE runner）；
- L3 触发条件与"不触发"清单冻结；
- retro-application 与本节一致；
- runner 拒绝歧义与未知选择。


## §110 P2-A3-1 WIGOLO BROWSER ADAPTER — DELIVERED, **BLOCKED BY A PROVIDER CACHE CONTRACT**（code `32a98ea`）

**结果**：Wigolo Browser 的 `BrowserBackend` 已实现并通过 A3-0 合同验收；A3-0 同一 fixture 集的 Wigolo 一侧已完成测量。**但测量暴露了一个必须在 A3-2/A3-3 之前解决的 provider 级阻塞**（见 110.4）。A3-1 **不标记 CLOSED**，A3-3 对照在阻塞解决前**不可信**。

**本刀 production-inert**：未接入 `ACTIVE_READER_CHAIN`，未安装 Crawl4AI，未改 A2 核心语义，未改任何预算常量。

### 110.1 交付物

| 交付物 | 路径 |
| --- | --- |
| `wigolo_browser` BackendExecutor | `src/web/research/wigolo_browser_executor.py` |
| bakeoff result schema（`browser-bakeoff-result-v1`）+ 校验 | `src/web/research/browser_bakeoff.py`（扩展） |
| bakeoff harness | `tools/run_browser_bakeoff.py` |
| 本地 fixture server（6 类 synthetic_local 目标） | `tools/browser_bakeoff_fixture_server.py` |
| executor 合同测试（34） | `tests/test_wigolo_browser_executor.py` |
| harness/result 测试（34） | `tests/test_browser_bakeoff_harness.py` |
| 测量产物（未跟踪） | `docs/research_quality/BROWSER_BAKEOFF.wigolo_browser.r2.json` |

### 110.2 executor 形状

```text
A2 routing / capability demand
        ↓（chain 决定调用）
WigoloBrowserBackendExecutor.execute(ChainAttemptRequest)
  1. capability 可用性：mode == browser（否则 policy skip disabled）
  2. backend 缺失 → skip preflight
  3. 共享 B2 预算真值 wigolo_http_execution_plan()（同一实现，非副本）
  4. provider preflight（非 ready → skip preflight）
  5. 唯一一次真实 attempt（browser tier, render_js=always）
  6. 诚实投影 → ChainStepResult（canonical retrieval_state + cost + policy）
```

- **零 routing 权威**：不解析 URL、不看 host、不判断"这个页面可能要用浏览器"。由测试断言（不 import `progressive_routing` / `candidate_resolution` / `run_chain`，源码无 `urlparse`/`hostname`/`startswith`）。
- **能力声明已存在且真实**：`DEFAULT_BACKENDS` 的 `wigolo_browser` 已声明 `js_render / session / anti_bot_recovery / pdf`，且这些是 `wigolo_http` 不具备的。**未新增 capability 词**。
- **诚实失败（本刀新增的关键语义）**：对渲染文本的前 `HONESTY_PREFIX_CHARS = 4000` 字符套用**冻结**的 A0 marker 表（`failure_taxonomy.state_for_text`），命中 `login_required / anti_bot / shell_page` 时降级为 `usable_content=False`。桥接用 `HONESTY_DETAIL` 回落到冻结 marker 字面量，并由测试断言 `classify(detail=…).state` 往返一致——**没有新 marker，也没有手搓 outcome**。
- cost 含 `fetch_ms`（承接 §107 归因）、`rendered`、`cache_hit`、`tier`、`provider_backend`、`honesty_downgrade`。

### 110.3 A3-0 六类：Wigolo 一侧实测（`A31.wigolo_browser.r2.json`，真实 daemon + 真实 browser）

| 类 | browser_called | browser_state | browser_usable | 备注 |
| --- | --- | --- | --- | --- |
| `static_control` ×3 | **False** | — | False | **guard 成立**：native 已结算，browser 零启动 |
| `js_shell` ×2 | True | `shell_page` / `invalid_content` | False | **被缓存污染，未真正渲染**（110.4） |
| `spa_delayed_render` ×2 | True | `invalid_content` | False | 同上 |
| `anti_bot`（challenge） | True | `timeout` | False | 真实 fetch，2.98s 超时 |
| `anti_bot`（soft 403） | True | **`anti_bot`** | False | **真实 fetch，诚实分类正确** ✅ |
| `session_required` | True | **`login_required`** | False | **诚实分类正确** ✅（未把登录页当正文） |
| `document_heavy`（w3c pdf） | True | `anti_bot` | False | 被缓存污染 |
| `document_heavy`（mixed） | True | `invalid_content` | False | 被缓存污染 |

- `provenance_complete` / `budget_respected` 全部 **True**；`attempts` 携带每步 cost。
- **static-control guard 在 live 也成立**（3/3 零启动）。
- **诚实失败路径在 live 也成立**：soft-403 与 session 页都被判为 `anti_bot` / `login_required` 且 `usable=False`。

### 110.4 🚫 BLOCKING FINDING：daemon cache 以 URL 为键、忽略 render mode

**证据（直接探测 daemon，非推断）**：

```text
warm with render_js=never  → {method: http,  cached: False, len: 10}
then  render_js=always     → {method: cache, cached: True,  len: 10}   ← 仍是未渲染正文
render_js=always + no_cache / bypass_cache / force / fresh / refresh / noCache
                           → 全部 {method: cache, cached: True, len: 10}
fresh URL, render_js=always → {method: browser, cached: False, len: 5165}  ← 真渲染
```

**结论**：`wigolo serve` 的响应缓存**只按 URL 作键**，`render_js` 不参与键，且**没有可用的 bypass 参数**。

**对 A3 的直接后果**：在 `native_http → wigolo_http → wigolo_browser` 三步步进链里，`wigolo_http`（`render_js=never`）只要成功，就用**未渲染正文**把该 URL 的缓存写满；随后 `wigolo_browser` 拿到的是 cache hit，**永远不会真正渲染**。

⇒ 实测完全吻合：`wigolo_http` 成功的 4 个类（js_shell / spa / document_heavy）browser 步全部 `rendered=False, cache_hit=True` 且 **bytes 与 http 步逐字节相同**；`wigolo_http` 失败的 2 个类（anti_bot soft-403、session）browser 步 `cache_hit=False`，**真实渲染并给出正确分类**。

**这不是 adapter 缺陷，也不是 A2 核心语义缺陷**——是 **provider 的缓存契约**与"两个 tier 共用一个 daemon"的组合问题。

**第二个相关发现（同一根因的语义面）**：`wigolo_http` 在 `DEFAULT_BACKENDS` 中声明了 `js_render`，但它以 `render_js=never` 运行，**从不渲染**。因此 `js_shell` / `spa` 类会被 routing 先送给一个不能渲染的 backend，既浪费一步与预算，又毒化缓存。**修改能力声明属于 A2 冻结语义面**（capability 词表），**A3-1 不改**。

**必须在 A3-2 / A3-3 之前解决**，可选方向（A3-2 决策，不在本刀）：
1. daemon 侧把 render mode 纳入 cache key（provider 修复，最干净）；
2. 为 browser tier 提供可用的 cache-bypass 请求路径；
3. 链级策略：browser 步使用不共享缓存的通道 / 不先经 http tier 的 URL。
**任一方向都不得靠调整预算或伪造结果绕过。**

### 110.5 第三个发现：run envelope 跨 tier 共享会饿死第二个 tier

`wigolo_http` 与 `wigolo_browser` 共用同一个 3.0s run envelope（A3-0 冻结）。首轮测量（未按 fixture 重置 envelope）显示：一次 2078ms 的 browser 超时就把 envelope 消耗到 0，其后 4 个 fixture 的 browser 步全部变成 `budget_exhausted` 的 `block_run`——**后测的类根本没被测量**。

- **harness 处置**：一个 fixture = 一个 bounded 测量单元，每个 fixture 前 `reset_http_envelope()`（冻结数值不变，只保证测量互相独立）。
- **production 含义（需 A3-3 决策）**：production 里 envelope 是 **per-run** 的，两个 tier 共享 ⇒ 一次慢 HTTP 步可以饿死 browser tier。**A3-1 不改预算语义**，作为 activation 前必须裁决的问题记录。

### 110.6 production-inert 证明

| 断言 | 结果 |
| --- | --- |
| `ACTIVE_READER_CHAIN` 未增加 browser | ✅ 仍为 `(NATIVE_HTTP_BACKEND, WIGOLO_HTTP_BACKEND)` |
| runtime / adapter / chain / router / lifecycle / wigolo_http 无 browser executor 引用 | ✅ 6 模块扫描 |
| `run_browser_bakeoff` / `crawl4ai` 不出现在 production 模块 | ✅ |
| `crawl4ai` 未安装、未注册 | ✅ `capability_registry()` 仍为 `{native_http, wigolo_http, wigolo_browser}` |
| `static_control` 不启动 browser | ✅ 单测 + live 3/3 |
| 未改 A2 核心语义 / 未新增 capability 词 / 未改预算常量 | ✅ |

### 110.7 门禁（Staged Regression Policy：L0 + L1）

| 层 | 结果 |
| --- | --- |
| L0 | Ruff clean；`git diff --check` clean；tracked clean |
| L1 `a3_browser`（3 文件） | **89 passed** |
| **L3 full pytest** | **未跑**（本刀 production-inert、未碰核心模型/authority/schema；符合 §109） |

### 110.8 结论与下一刀

```text
A3-0 ✅ CLOSED
A3-1 ⚠️ DELIVERED — adapter 合规、measurement 完成，但被 provider cache 契约阻塞
A3-2 ⏳ Crawl4AI adapter —— 但需先决定 110.4 的解决方向
A3-3 ⏳ 对照 —— 在 110.4 解决前不可信
```

**A3-1 不进入 production，不标记 CLOSED。** 下一刀建议：**先裁决 110.4**（daemon cache key / bypass 路径 / 链级策略），再决定 A3-2 是否/如何继续——否则 Crawl4AI 一侧会用同样的方式被污染，对照变成"谁先写缓存"。


## §111 P2-A3-1R WIGOLO BROWSER QUALIFICATION REMEDIATION — VERDICT: **DISQUALIFIED**（code `8b4f000`）

**结果**：三个 qualification blocker 中，**两个已用 provider-native 方案解决并实测有效**，第三个（PDF/document）**provider 层面确实做不到**。按 §110 裁决规则，required gate 失败 ⇒ **Wigolo Browser DISQUALIFIED**，不再迭代。

### 111.1 blocker ①（cache 污染）—— **已解决，provider-native**

A3-1 的探测用错了 flag 名。查 `wigolo fetch --help` 后找到官方参数：

```text
--force-refresh        Bypass cache and fetch fresh content from the network.
--mode=cache|default|stealth   cache=HTTP-only；default=standard；stealth=full browser render
```

**实测（决定性）**：

| 请求 | method | cached | 结果 |
| --- | --- | --- | --- |
| 先 `render_js=never` 预热 | http | False | 未渲染 10B |
| 再 `render_js=always` | **cache** | **True** | 仍是未渲染 10B（A3-1 的问题） |
| `always` + **`force_refresh`** | **browser** | **False** | **5165B 已渲染** ✅ |
| `always` + **`mode=stealth`** | **browser** | **False** | **5165B 已渲染** ✅（可重复，不吃缓存） |

**采用的解**：browser tier 的 `WigoloShadowReadBackend` 默认 `mode="stealth"` + `force_refresh=True`（两者都是 provider 原生、有文档、**不改写 URL**）。http tier 行为不变。

**复核（A3-1R cohort）**：每个 `wigolo_browser` 步现在都是 `cache=False`，`wigolo_http` 同 URL 仍是 `cache=True, rend=False` ⇒ **两个 tier 的缓存已隔离**。

**新增硬门**：`WigoloBrowserBackendExecutor` 遇到 `cache_hit=True` 的 browser 尝试时**fail closed**（`adequacy_reason="browser_cache_not_isolated"`、`usable=False`）——不允许 HTTP 缓存内容冒充 browser result。

### 111.2 blocker ②（capability truth）—— **已修正**

`wigolo_http` 以 `render_js="never"` 运行，**从不渲染**，因此从 `DEFAULT_BACKENDS` 移除其 `js_render`：

```text
wigolo_http    = {plain_http, content_extraction}          ← 修正
wigolo_browser = {plain_http, content_extraction, js_render, session, anti_bot_recovery, pdf}
```

- **未新增 capability 词**，未改 `route()` / `schedulable_now()` / lifecycle / taxonomy。
- 后果（预期且已测）：`shell_page` / `js_required` 不再被送给不能渲染的 http tier，而是**终止**（production chain 尚无 browser tier）⇒ `exhaust / no_capable_backend`。这正是"不再因为错误 capability 把 JS page 送给 `wigolo_http`"。
- 受影响测试按修正后的真值更新：`test_progressive_routing` / `test_scheduling` / `test_chain_executor`（6 处 state 由 `shell_page` 改为 http tier 真正能服务的 `reset`）/ `test_wigolo_http_executor` / A2e 的 `shell_page` 两行（→ `exhaust`）。

### 111.3 blocker ③（envelope 饿死）—— **已按 tier 分离**

```text
wigolo_http   envelope = 3.0s / run   （数值不变）
browser tier  envelope = 3.0s / run   （独立 accounting domain）
两者共同受 research_seconds_left 全局约束
```

实现：`read_escalation` 的 ledger 改为 **按 tier 键控**（`reset_run_envelope(tier)` / `charge_run_envelope(ms, tier)` / `run_envelope_spent_ms(tier)` / `run_envelope_remaining_ms(tier)`）；原 `*_http_envelope*` 保留为 `TIER_HTTP` 薄封装（生产调用面不变）。browser executor 用 `TIER_BROWSER` 的 envelope 计算 B2 plan；runtime **每 run 重置两个 tier 各一次**。**没有新增全局 ledger，没有改任何冻结数值。**

### 111.4 A3-1R 六类复测（`BROWSER_BAKEOFF.wigolo_browser.a3-1r.json`）

| 类 | browser_called | browser_state | rendered | cache | usable | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| `static_control` ×3 | **False** | — | — | — | — | ✅ guard 成立 |
| `js_shell` ×2 | True | `timeout` | — | False | False | ⚠️ 见 111.5 |
| `spa_delayed_render` ×2 | True | **`success`** | **True** | False | **True** | ✅ **真实 browser rescue** |
| `anti_bot` ×2 | True | **`anti_bot`** | True | False | False | ✅ 诚实失败 |
| `session_required` | True | **`login_required`** | True | False | False | ✅ 诚实失败 |
| `document_heavy`（pdf） | True | `backend_failure` | — | False | False | ❌ **required gate 失败** |
| `document_heavy`（mixed html） | True | `invalid_content` | True | False | False | ⚠️ |

`provenance_complete` = True（全部 12 行）。`budget_respected` 仅 `js_shell` 两行为 False（见 111.6）。

### 111.5 新增能力证明：browser 真的做了只有 browser 能做的事

`spa_delayed_render` 是决定性证据：native 失败、`wigolo_http` 只拿到 `Loading...`（10B, cache hit）、**browser 步 `rend=True, cache=False, 5165B` 且 `usable=True`**。延迟注入的 SPA 正文只有渲染后才存在 ⇒ 这是**独立 browser rescue**，不是 HTTP 结果冒充。

### 111.6 次级观察（非 disqualifier）

1. **`js_shell` 在 3.0s effective timeout 下超时**（3015/3031ms）。直接探测显示同一页面 `mode=stealth` 渲染需 **~6.2s**（loopback）。⇒ **3.0s effective timeout 对真实 browser render 偏紧**；js_shell 的诚实判定本应是 `shell_page`（该 fixture 页即使渲染也无正文）。**按裁决不调数值**，作为 activation 前必须裁决的 timeout 策略问题记录。
2. **envelope 有界溢出 +0.5%**：js_shell 两行 debit = 3015/3031ms vs 3000ms envelope。来自"调用前按 envelope 判 deny + 调用时 timeout 上限"的自然余量；harness 的 `budget_respected` 容差仅 1ms，故判 False。**有界**，非无界超支。

### 111.7 ❌ DISQUALIFIER：`document_support`（required）失败

**决定性探测**（provider 直接调用，非推断）：

```text
local  /report.pdf   + mode=stealth → HTTP 500 playwright_fetch_failed
                                      "page.goto: Download is starting"
public w3c dummy.pdf + mode=stealth → HTTP 500 playwright_fetch_failed（同一错误）
local  /report.pdf   + mode=default → method=browser, 16 字符 "  -- 1 of 1 --  "（viewer 外壳，无正文）
```

⇒ **browser tier 的 Playwright 路径无法处理 PDF**（导航被下载中断），`default` 路径只回 viewer 外壳。**两个不同 PDF 复现，排除 fixture 偶然性。**

A3-0 把 `document_support` 定为 **required** 维度：required 未达标 ⇒ 任何 rate 比较都无意义。按 §110 裁决："如果 provider 本身无法提供 → 作为 bakeoff disqualifier，而不是在 Study Agent 核心里打补丁绕过去"。

**⇒ `Wigolo Browser DISQUALIFIED`（disqualifier = `document_support_failed`）。**

**连带记录（第二个不实声明）**：`wigolo_browser` 在 `DEFAULT_BACKENDS` 中声明了 `pdf`，而它实际做不到——与 `wigolo_http`/`js_render` 同类的 capability truth 问题。**本刀不改**（A3-0 测量面，且候选已被淘汰）；**若 Wigolo Browser 日后被重新考虑，必须先移除 `pdf` 声明再重新测量。**

### 111.8 门禁（Staged Regression Policy：L0 + L1 + **L2**）

| 层 | 结果 |
| --- | --- |
| L0 | Ruff clean；`git diff --check` clean；tracked clean |
| L1（`a3_browser` + routing/scheduling/chain/runtime 相关） | 全绿（见 L2 覆盖） |
| **L2 `p2-a-retrieval-stack`** | **465 passed / 226s**（修正前为 448 passed / 13 failed；13 项失败全部是两处有意语义修正的预期后果，已逐一按新真值更新） |
| **L3 full pytest** | **未跑**（未改 A2 共享核心数据模型 / authority / schema；capability metadata 与 tier-scoped envelope accounting 均在 L2 检索栈内可证局部收敛；符合 §109） |

`wigolo_http` 的 production capability metadata 被修正，故 L2 是必需的（本刀已跑）。未安装/接入 Crawl4AI。

### 111.9 路线

```text
A3-0 ✅ CLOSED
A3-1 ⚠️ DELIVERED → A3-1R ❌ DISQUALIFIED（document_support）
A3-2 ← 下一刀：Crawl4AI adapter
       （必须独立达到同一 A3-0 required gates；不是"因为分高而赢"）
A3-3 Head-to-head
```

**A3-3 仍然有意义**：Wigolo Browser 因 required gate 失败先被淘汰；Crawl4AI 仍须独立通过 A3-0 六类与 required 维度，才算 production-qualified。

**给 A3-2 的既有约束（本刀产出）**：
1. browser tier **必须**用 provider-native cache 隔离（`mode=stealth` / `force_refresh` 或等价），不得靠 URL 变形；
2. **capability 声明必须为真**——声明前先验证该 backend 真的具备；
3. browser tier **用自己的 envelope**，不与 http tier 共享 accounting；
4. browser 尝试若返回 `cache_hit` ⇒ 不得当作 browser result；
5. `document_support` 是 required gate：Crawl4AI 必须先证明 PDF 能力，否则同样被淘汰。


## §112 P2-A3-2 CRAWL4AI ADAPTER + QUALIFICATION — Phase 0/1 已过，adapter 待做（**IN PROGRESS，无 verdict**）

**A3-3 已不是对称比分赛**（Wigolo 因 required gate 淘汰）。A3-2 结论只有三种：Crawl4AI `QUALIFIED` → 自动成为 BrowserBackend winner；required gate 失败 → `NO QUALIFIED BROWSER BACKEND`；真 blocker → 如实记录。

**本阶段为 Phase 0/1（provider 能力探针），尚未写 adapter、尚未跑六类 cohort、未出 verdict。**

### 112.1 Gate 0 — 安装 / runtime viability：**PASS，附 dependency-footprint penalty**

按 §111.9 的裁决，**未污染 Study Agent 主 venv**，使用隔离环境：

```text
C:\Users\Zhang\AppData\Local\Temp\opencode\a3-crawl4ai-venv
  crawl4ai[pdf]==0.9.4        （pypdf 6.19.0 = pdf extra）
  playwright 1.63.0 / patchright 1.63.0 / unclecode-litellm 1.81.13 / ...
  chromium rev 1243（Chrome for Testing 153.0.8010.12）
```

| 检查 | 结果 |
| --- | --- |
| Python 3.12.6 安装 | ✅ |
| `import crawl4ai, pypdf` | ✅ |
| `pip check` | ✅ No broken requirements |
| `crawl4ai-doctor` | ✅ Crawling test passed |
| example.com browser sanity | ✅ success / 200 / 166 chars / **1550ms** |
| 额外 server/db 基础设施 | **无** |
| dependency footprint | **HEAVY**（~90 个依赖，含 litellm/openai/tokenizers/scipy/shapely/trimesh/nltk…） |
| in-process 集成风险 | **RISK** ⇒ 隔离 venv；A3-3 再决定 subprocess/sidecar/Docker/同进程 |

**安装期事故（已解决，记录以免重踩）**：
1. 网速 ~44 kB/s，两个 38.6 MB 轮子 + 195.6/114.6 MiB 浏览器下载极慢。
2. `[WinError 32] 文件被占用`（scipy `_tanhsinh.py`）**不是 Crawl4AI 的 runtime bug**，而是**上一次被中断的 `pip install` 残留进程**占着文件。杀掉后重试即成功。
3. 浏览器二进制走 **FlClash 本地代理 `127.0.0.1:7890`**（系统代理已启用）+ `PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000` 下载；**后续 qualification 已恢复直连**，避免把代理能力算成 Crawl4AI 能力。

### 112.2 Gate 1 — PDF（required，第一硬门）：**PASS**

必须走 **provider-native PDF 路径**（`PDFCrawlerStrategy` + `PDFContentScrapingStrategy`），不是"浏览器打开 .pdf URL"。

| target | success | markdown | 正文命中 | shell 标记 | 耗时 |
| --- | --- | --- | --- | --- | --- |
| `local_file`（受控本地） | ✅ | 309 | ✅ | 无 | 12ms |
| `local_http`（同文件经本地 HTTP） | ✅ | 309 | ✅ | 无 | 31ms |
| `public_http`（W3C dummy.pdf） | ✅ | 21 | ✅ | 无 | 703ms |

- 真实正文提取成功；无 viewer shell / "1 of 1" / download-starting / metadata 冒充。
- **无 `WinError 32` 临时文件锁**（Windows + Py3.12 robustness 观察项：通过）。
- ⇒ **通过淘汰 Wigolo 的那道 required gate。**

### 112.3 Gate 2 — JS render：**PASS**

| target | success | markdown | 渲染后正文命中 | 耗时 |
| --- | --- | --- | --- | --- |
| `spa_delayed`（250ms 定时器注入） | ✅ | 5125 | ✅ | **1346ms** |
| `spa_xhr`（同步 XHR 注入） | ✅ | 5125 | ✅ | **211ms** |
| `static_control`（example.com） | ✅ | 166 | — | 573ms |
| `js_shell` | ⚠️ `success=false` | 1 | — | 206ms |

- 延迟渲染需要显式 `delay_before_return_html`（默认会在定时器触发前取 DOM）——**这是渲染语义，不是调预算**。
- **延迟/异步注入的正文确实只有浏览器才拿得到**（对照：同页 HTTP-only 只得 11 字符 `Loading...`）。
- **0.21–1.35s 落在冻结 3.0s browser envelope 内**（对照 Wigolo stealth 实测 ~6.2s 才够）。

**⚠️ 发现（transparency，非 disqualifier）**：`js_shell` 被 Crawl4AI **自身的 anti-bot 检测器误判**为 anti-bot（`Structural: minimal_text, no_content_elements`）。结果不可用是对的，但**归因错了**（真相是 JS shell，不是反爬）。

### 112.4 Cache isolation：**PASS**（决定性）

```text
HTTP-only crawl（写缓存）      → "Loading..."  11 字符（未渲染）
browser + CacheMode.BYPASS     → 5125 字符  已渲染  ✅
browser + CacheMode.BYPASS 再跑 → 5125 字符  已渲染  ✅（可重复）
```

⇒ Crawl4AI 的 `CacheMode.BYPASS`（另有 `no_cache_read`/`disable_cache`）给出**真正的 tier 隔离**，不像 Wigolo 的 URL-keyed cache 会把未渲染正文喂给 browser tier。**未使用任何 URL 变形/随机 query/全局 flush。**

### 112.5 Gate 3（session）/ Gate 4（anti-bot）：provider 不自我分类，**合同层 PASS**

**原始 provider 行为（如实记录）**：

| target | success | markdown | 是否把墙当内容返回 |
| --- | --- | --- | --- |
| `session_gated` | **true** | 63 | **是**（"Members only / Please log in to continue"） |
| `anti_bot_challenge` | **true** | 99 | **是**（"Checking your browser / CAPTCHA"） |
| `anti_bot_soft_403` | false（`HTTP 403 with HTML content`） | 64 | 是（markdown 仍含挑战文本） |
| `static_control` | true | 166 | 否 |

⇒ **Crawl4AI 不会自己把登录墙/挑战页判为失败**（403 形态除外，它有自己的 anti-bot detector）。

**合同层验证（用冻结 marker 层跑 Crawl4AI 的真实输出）**：

| case | 检测状态 | canonical | non-usable |
| --- | --- | --- | --- |
| `session_gated` | `login_required` | ✅ | ✅ |
| `anti_bot_challenge` | `anti_bot` | ✅ | ✅ |
| `anti_bot_soft_403` | `anti_bot` | ✅ | ✅ |
| `js_shell` | `shell_page` | ✅ | ✅ |
| `static_control` / `spa_rendered` | （内容，不降级） | — | — |

⇒ 这**正是 A3-0 合同要求 adapter 做的事**（`CLASS_SUCCESS_DEFINITION`：honest `login_required` 可接受，静默返回登录页不可接受；`NON_USABLE_STATES` 硬门）。**不是为 provider 缺陷打补丁，而是合同规定的 adapter 职责**——A3-1 已 live 证明同一层有效（Wigolo 的 `anti_bot`/`login_required` 就出自此层）。

### 112.6 阶段小结与下一刀

```text
Gate 0  install/runtime   ✅ PASS（HEAVY deps → 隔离 venv）
Gate 1  PDF (required)    ✅ PASS
Gate 2  JS render         ✅ PASS
        cache isolation   ✅ PASS
Gate 3  session           ✅ PASS（合同层；provider 不自我分类）
Gate 4  anti-bot          ✅ PASS（合同层）
        static control    ✅ 166 chars，未误启动
────────────────────────────────────────────
adapter（subprocess bridge）  ⏳ 未做
六类 frozen cohort            ⏳ 未做
final verdict                 ⏳ 未出
```

**下一执行刀（A3-2 续）**：实现 `Crawl4AI BrowserBackendExecutor`。
因 Crawl4AI 在**隔离 venv**，adapter 采用 **subprocess bridge**（主 venv 的 executor 调用隔离 venv 的 python 执行一次 crawl，读回结构化 JSON），复用：
- `CacheMode.BYPASS` 做 tier cache 隔离；
- **同一冻结 honesty 层**（`login_required`/`anti_bot`/`shell_page` 降级）；
- browser tier 自己的 3.0s envelope（§111.3），数值不变；
- A3-0 六个 provenance artifact。
然后跑 A3-0 同一 manifest 的六类 cohort，出 `QUALIFIED` / `DISQUALIFIED` / `BLOCKED`。

**当前无任何 production 改动**：`ACTIVE_READER_CHAIN` 未动，Crawl4AI 未注册进 `DEFAULT_BACKENDS`，未同时启用两个 BrowserBackend。


## §113 P2-A3-2 Phase 1.5 capability truth + A3-2a transport cost（**无 verdict；adapter 与 cohort 待做**）

### 113.1 Phase 1.5A — `session`：**真实能力，PASS**

fixture 新增服务端权威 session 端点（cookie + localStorage）：`/session/start` 写 cookie 与 localStorage，`/session/check` **仅凭 cookie 判定**（避免依赖 provider 自己的页面启发式）。

| 请求 | HTTP | 判定 | 证据 |
| --- | --- | --- | --- |
| req1 `/session/start`（`session_id=A`） | 200 | — | `cookiesEnabled=true`，`bakeoff_sid=sess-truth-2026`，localStorage 写入 |
| req2 `/session/check`（**同 `session_id=A`**） | **200** | **SESSION OK** | 服务端接受 cookie ⇒ **前一请求状态被消费** |
| req3 `/session/check`（**独立 crawler**） | **401** | NO SESSION | 反证成立 |

⇒ **`session` 可声明**。注意方法论修正：第一次探针的反证失败（换 `session_id` 仍带状态），说明**同一 crawler 内 storage 是共享的**，`session_id` 的作用域要靠独立实例才测得准；`kill_session` 在 0.9.4 不存在。

### 113.2 Phase 1.5B — `anti_bot_recovery`：**未成立，不声明**

| 配置 | `anti_bot_challenge` | `anti_bot_soft_403` |
| --- | --- | --- |
| default browser | `success=true`，99 字符 = **挑战页正文** | 403，blocked，64 字符挑战文本 |
| `enable_stealth=True` | 同左 | 同左 |

`ANTIBOT_RECOVERY_DEFAULT=False` / `ANTIBOT_RECOVERY_STEALTH=False` / `ANTIBOT_RECOVERY_SOFT403_STEALTH=False`。

⇒ 观察到的只有 **detection**，没有 **rescue**（fixture 是静态墙，本就无物可解）。按裁决规则：**不声明 `anti_bot_recovery`**；保留诚实 `anti_bot` / `usable=false`（正确 failure semantics ≠ recovery capability）。
附带：`enable_stealth` **也没有修掉**小页面误判（见 113.4）。

### 113.3 Crawl4AI capability truth 表（唯一允许声明集合）

| capability | 真值 | 证据 |
| --- | --- | --- |
| `plain_http` / `content_extraction` | ✅ | example.com / 静态页 |
| `js_render` | ✅ | `spa_delayed` 1346ms、`spa_xhr` 211ms（正文仅 JS 后存在） |
| `pdf` | ✅ | 本地 file/http + 公网 PDF，provider-native PDF strategy，真实正文 |
| `session` | ✅ | §113.1 |
| **`anti_bot_recovery`** | ❌ **不声明** | §113.2 |
| `pdf` 之外的 document 变体 | 未测 | 不声明 |

⇒ 注册时只允许声明 **`plain_http` / `content_extraction` / `js_render` / `pdf` / `session`** 五项。

### 113.4 transparency debt（不修 provider，必须双层保留）

Crawl4AI **自身 anti-bot 检测器对任何小页面系统性误报**，已三例同源：

```text
js_shell.html        → "Structural: minimal_text, no_content_elements"
/session/check 200   → "Near-empty content (80 bytes) with HTTP 200"
/session/check 401   → "Structural: minimal_text on small page"
```

⇒ cohort 必须同时保存 **`provider_state`（原始判断）** 与 **`canonical_retrieval_state`（冻结 honesty 层重判）**，例如 `provider=anti_bot` / `canonical=shell_page`。这是 provenance，不是 authority。

### 113.5 A3-2a transport cost（cold per-call subprocess）——**正式测量项**

极薄 worker（`stdin` 一个 JSON 请求 → `stdout` 一个 JSON 响应；只有执行参数，**无 routing/lifecycle/budget/Evidence authority**；`mode=pdf` 走 provider-native PDF strategy，其余走 browser path）。

| target | mode | wall_ms ×3 | spawn+IPC | crawl | import+init（推算） |
| --- | --- | --- | --- | --- | --- |
| `spa_delayed` | browser | **3784 / 2359 / 2311** | 345–380 | 2127/1114/1060 | 1301/900/871 |
| `example.com` | browser | 2754 / 2729 / 2693 | 336–417 | ~1400–1490 | ~920–1000 |
| `report.pdf` | pdf | 1369 / 1442 / 1628 | 287–414 | 196–259 | ~870–960 |

**结论（不调预算）**：
- **纯 transport+init 开销 ≈ 1.2–1.7s**（spawn+IPC ~0.3–0.4s ＋ provider import/init ~0.9–1.3s），在冻结 3.0s browser envelope 内只剩 **~1.3–1.8s 给真正的 crawl**。
- 静态页 **勉强落在 3.0s 内**（2.69–2.75s）；**真实 render 会超**（SPA run1 = 3.78s）。
- ⇒ 记录：**per-call subprocess transport 与冻结 browser budget 不兼容（marginal→over）**。**不因此调整 `min hard / envelope / timeout floor / max chars`。**
- 该次 SPA 只回 11 字符（`Loading...`）：worker 漏了 `delay_before_return_html`，故该行**不是**真实 render 耗时；即使如此 wall 已 3.78s。

**下一刀（A3-2a 续）**：bounded **warm worker probe** —— 同一隔离 venv 下的**长驻 worker + 常驻浏览器**，比较 `warm IPC + crawl` 是否进入 3.0s；A3-3 再决定最终 deployment 是 per-call subprocess / long-lived sidecar / 或无合格 transport。**不引入 Docker**，除非前两者均不可行且确有必要。

### 113.6 状态

```text
Gate 0 install/runtime   ✅ PASS（HEAVY penalty）
Gate 1 PDF (required)    ✅ PASS
Gate 2 JS render         ✅ PASS
Cache isolation          ✅ PASS（CacheMode.BYPASS）
Phase 1.5A session       ✅ PASS（可声明）
Phase 1.5B anti_bot_rec  ❌ 未成立（不声明）
A3-2a cold transport     ⚠️ 与 3.0s 不兼容（已记录，未调预算）
warm worker probe        ⏳
adapter                  ⏳
六类 frozen cohort       ⏳
verdict                  ⏳
```

**production-inert 未变**：`ACTIVE_READER_CHAIN` 未动；Crawl4AI 未注册进 `DEFAULT_BACKENDS`；Wigolo Browser 仍 DISQUALIFIED；不同时挂两个 browser。本刀仅改 fixture server（测试工具）+ docs，**未触 production 代码**，按 Staged Policy 无需 L1/L2。


## §114 P2-A3-2 Step 0 裁决 + A3-2a warm transport（**无 verdict；adapter 待做**）

### 114.1 Step 0 — 冻结合同机械检查：**裁决 B（类失败只报告，不淘汰）**

代码事实（`browser_bakeoff.py`，非印象）：

```text
REQUIRED_DIMENSIONS : session_capability, document_support, failure_transparency,
                      provenance_completeness, budget_boundedness, static_control_silence
   anti_bot_recovery ∈ required?   False     任何 anti_bot 维度?  NONE
DISQUALIFIERS       : browser_started_on_static_control / budget_exceeded /
                      missing_canonical_retrieval_state / provenance_incomplete /
                      requires_core_semantics_change / chain_longer_than_max
   missing_required_capability?    False     任何 class-failure 条目?  NONE
anti_bot class      : demand = anti_bot_recovery, expect_browser_call = True
   success_definition: {browser_invocation: required_once, usable_content_required: TRUE,
                        canonical_state_required: True,
                        notes: "Recovery is the point of the class; a denial is a miss."}
```

**裁决（用户）**：硬门以 `REQUIRED_DIMENSIONS + DISQUALIFIERS` 为准。事后把"类 success definition"追认成 disqualifier 属于**事后加强 gate**，破坏预注册原则。

```text
Crawl4AI anti_bot class        = FAIL（报告，不淘汰）
anti_bot_recovery capability   = 不声明
qualification disqualifier     = NO
```

**A3-3 verdict 必须显式写明**：Crawl4AI 未通过 anti_bot recovery class；production `BrowserBackend` **不提供** `anti_bot_recovery` capability；遇到 anti-bot demand **不得调度 Crawl4AI 作为 recovery backend**。

**登记 contract defect（design debt，本轮不修、不重跑、不追溯）**：

```text
A3-0 anti_bot class 要求 recovery（usable_content_required=True），
但 anti_bot_recovery 未进入 REQUIRED_DIMENSIONS / DISQUALIFIERS。
下一版 bakeoff 若要把 anti-bot recovery 设为资格硬门，
必须在测试任何候选之前正式加入 required/disqualifier。
```

### 114.2 A3-2a warm isolated worker — 架构

```text
Study Agent (main venv)
   │  stdin/stdout 逐行 JSON（-u，逐行 flush）
   ▼
isolated Crawl4AI worker（隔离 venv，长驻）
   │  per-(session, mode) AsyncWebCrawler
   ▼
persistent browser runtime
```

worker 只拥有 **provider execution**：无 routing / lifecycle / budget / Evidence-Support-Gate authority。`mode=pdf` → provider-native PDF strategies；其余 → browser path（backend execution strategy，非第二套路由权威）。

**crawler 分键**：`(session_id, mode)`。第一版只按 session 分键，导致 PDF 请求复用了 browser crawler（`chars=0` + internal error）；修正后 PDF 正常（309 字符）。

### 114.3 warm E2E（qualification 数字 = request sent → response received）

| 步骤 | wall | ipc | provider | chars | 判定 |
| --- | --- | --- | --- | --- | --- |
| READY | — | — | — | — | `startup_ms=3782.9`（另一次 3265.4） |
| STATIC | 2032.5ms | 922.4 | 1110.1 | 166 | ✅ ≤3000 |
| **SPA**（delay 1200ms） | **1383.6ms** | 14.0 | 1369.6 | **5125** | ✅ **真渲染** |
| **PDF** | **267.8ms** | 218.7 | 49.1 | **309** | ✅ **真 PDF 正文** |

⇒ **warm transport 三类全部落在冻结 3.0s browser budget 内**（对比 cold per-call subprocess §113.5：1.2–1.7s 纯开销、SPA 3.78s 超标）。**未调任何冻结数值。**

**operational startup 单独记账**：worker import + 首个 crawler 启动 ≈ **3.27–3.78s**。按裁决要求：**production 必须只有 worker `READY` 之后 backend 才允许 `availability=true`**，否则等于把 cold-start 偷出预算。

### 114.4 session cross-candidate 隔离 —— **HARD CHECK PASS**

| 请求 | HTTP | 判定 |
| --- | --- | --- |
| A `/session/start`（`session_id=A`） | 200 | 写 cookie |
| A `/session/check`（**同 A**） | **200** | **SESSION OK** ✅ |
| B `/session/check`（`session_id=B`） | **401** | NO SESSION ✅ |
| 匿名 `/session/check`（无 session） | **401** | NO SESSION ✅ |

⇒ **进程常驻 ≠ 状态常驻**：长驻 worker + per-`(session, mode)` crawler 保证 candidate A 的 cookie/localStorage **不会**泄漏给 B 或匿名请求。这正面回应了 §113.1 发现的"同一 crawler 内换 `session_id` 仍共享 storage"。

### 114.5 ❌ deadline boundedness —— **未通过（真缺口，待修）**

```text
request: timeout_ms=1500, delay_ms=4000
结果:    wall=4511ms（harness watchdog 4.5s 触发），provider_ms=0.0
```

- 语义区分已按裁决落地：**provider budget = 3.0s（资格判定）** vs **harness watchdog = 4.5s（仅防测试挂死）**；watchdog 触发即判 **FAIL**，不把那 1.5s 算给 Crawl4AI。
- 根因：`delay_before_return_html` **不受 `page_timeout` 约束**，且当前 worker **没有从主进程传播 deadline 的取消路径** ⇒ 主进程超时后 provider 仍在跑。
- **这是 qualification failure 的一种，不是测试工具问题**：adapter 设计必须提供 worker 级取消/任务级 timeout，使 deadline 真正向下传播。**不得靠调预算掩盖。**

### 114.6 观测方法教训（已固化）

- `Select-Object -Last N` 会缓冲到进程结束 ⇒ 表现为"假卡住"。改用 `-u` + `Tee-Object` 实时输出。
- worker 必须**逐行 flush**，且以 `-u` 启动；harness 每一步打印 `BEGIN/END`，最后一行即故障位置。
- harness 需要**独立 watchdog**，否则 deadline 测试会把整个 probe 挂死。
- 探针自身 bug 两个（crawler 未按 mode 分键、session 行未打印 error）已修；修复前后对比见 114.2/114.3。

### 114.7 状态与下一刀

```text
Step 0 冻结合同机械检查     ✅ 裁决 B（class FAIL，不淘汰）+ contract defect 登记
Step 1 warm worker          ✅ READY 握手 + operational startup 记账
Step 2 warm E2E             ✅ static/SPA/PDF 全 ≤3000ms
Step 3 deadline boundedness ❌ 未通过（需 worker 级取消）
Step 4 session isolation    ✅ HARD CHECK PASS
Step 5 capability 广告      ⏳ 仅 js_render / pdf / session（provider truth 的子集）
Step 6 adapter + cohort     ⏳
verdict                     ⏳
```

**下一刀**：修 deadline 传播（worker 级 task timeout / 取消），复验 Step 3；然后实现 `Crawl4AIBrowserBackendExecutor`（`CacheMode.BYPASS` + PDF native strategy + 主进程 frozen honesty 层 + `provider_state` 与 `canonical_retrieval_state` 双层 provenance + **仅广告 `js_render`/`pdf`/`session`**），跑 A3-0 原封六类 cohort，出最终 verdict。

**production-inert 未变**：`ACTIVE_READER_CHAIN` 未动；Crawl4AI 未注册进 `DEFAULT_BACKENDS`；Wigolo Browser 仍 DISQUALIFIED；不同时挂两个 browser。本刀仅改 fixture server（测试工具）+ docs，未触 production 代码，按 Staged Policy 无需 L1/L2。


## §115 P2-A3-2b Worker Deadline / Cancellation Closure — **7/8 PASS，1 项有界 FAIL 已如实记录**

### 115.1 cancellation 语义（已实现）

每个 IPC request 建独立 task；deadline 到期 → `task.cancel()` → **bounded cancellation grace 800ms** → 返回 canonical timeout。

**timeout 即视为 potentially contaminated**：销毁该 `(session, mode)` 的 crawler，后续请求按需重建。**不重启整个 worker**（否则退回 cold transport）。记入 provenance：`requested_deadline_ms` / `cancel_grace_ms` / `actual_return_ms` / `provider_cancelled` / `provider_task_done` / `crawler_invalidated`。

**4.5s harness watchdog 仅作保险丝**（本轮实际用 12s），**不是**通过标准；判据是 `deadline + grace`。

### 115.2 HARD recovery sequence 结果（8 步）

| 步 | 内容 | 结果 |
| --- | --- | --- |
| 1 | normal SPA | wall 2442.5ms / 5125 chars ✅ PASS |
| 2 | forced deadline（1500/4000） | wall **1882.7** ≤ 1500+800=2300；`deadline_hit=True`、`cancelled=True`、`task_done=True`、`invalidated=True` ✅ PASS |
| 3 | **immediately STATIC** | wall **3561.7ms** / 166 chars（内容正确） ❌ **FAIL（超 3.0s）** |
| 4 | immediately SPA | wall 1473.8ms / 5125 chars ✅ PASS |
| 5 | session A 建状态 | A.start 200 → A.check **200 SESSION OK** ✅ PASS |
| 6 | A 内强制 timeout | wall 1887.3 ≤ 2300；`invalidated=True` ✅ PASS |
| 7 | unrelated B / anonymous | B **401**、anon **401**，无 A 状态 ✅ PASS |
| 8 | worker health + 再服务 | `stats: completed=9 timeouts=2 invalidations=2`；final STATIC 234.0ms ✅ PASS |

**三条件同时成立**（非"caller 提前返回"）：caller 在 `deadline+grace` 内返回 ＋ `provider_task_done=True`（任务真的停） ＋ worker 之后仍正常服务（步 4/8）。超时 crawler 被销毁（步 2/6），且**未重启 worker**。

### 115.3 Step 3 的 FAIL：形状有界，如实记录

Step 2 超时销毁了 `anon|browser`；Step 3 是**同键**请求，必须**重建 browser context** ⇒ 3561.7ms（超 3.0s 约 **0.56s**）。Step 4 同键已回暖 ⇒ 1473.8ms。

```text
惩罚对象：timeout 之后、同一 (session, mode) 的【第一个】请求
惩罚次数：一次
后续请求：回到 3.0s 内
```

**这是 §115.1 销毁策略的必然账单**，也是"boundedness/correctness 高于 session continuity"的真实代价。**不调预算、不靠 pre-warm 掩盖**（pre-warm 会反向拉长超时路径，且把成本藏进 timeout 分支）。

**留给 A3-3 / adapter 的决策项（本刀不决）**：
1. 接受该 0.56s 越界，让重建请求**fail closed 为 `budget_exhausted`**（与"boundedness 优先"一致）；
2. 或为重建请求预留独立的一次性重建 allowance（需作为**新冻结项**正式登记，不得偷偷改 3.0s）；
3. 或在 worker 内维护**备用热 context 池**（成本前移到 idle 时间，需评估 RAM）。

### 115.4 capability advertisement 冻结（本轮记录，Step 5）

Crawl4AI BrowserBackend production role **只广告**：

```text
js_render
pdf
session
```

**明确不广告**：`anti_bot_recovery`（未实证）、`plain_http` / `content_extraction`（provider 真会，但**不是** BrowserBackend 的 production 角色；广告它会让普通 transport failure 无意义升级到昂贵浏览器）。

⇒ routing 结果：JS demand → eligible；PDF demand → eligible；session demand → eligible；**anti_bot_recovery demand → NOT eligible（`no_capable_backend`）**。

provider truth 与 routing-advertised 分离，后者是前者的**子集**且必须真实。

### 115.5 anti_bot class 口径（承接 §114.1 裁决 B）

```text
provider qualification observation : Crawl4AI 曾真实尝试 anti-bot → 未 rescue
production routing truth           : anti_bot_recovery 不在 advertised capabilities
                                     ⇒ 不应被调度
anti_bot class                     : FAIL（报告）
disqualifier                       : NO
```

六类 cohort **同时保留两个视角**，不得为了跑 manifest 而制造一个 production 永远不会发生的调用路径。

### 115.6 状态与下一刀

```text
Step 0 冻结合同机械检查   ✅ 裁决 B + contract defect 登记
Step 1 warm worker       ✅ READY + startup 记账（≈3.3–3.8s）
Step 2 warm E2E          ✅ static/SPA/PDF 全 ≤3000ms
Step 3 deadline closure  ✅ 7/8；1 项有界 FAIL（同键重建 0.56s）已记录
Step 4 session isolation ✅ 含 timeout 后隔离
Step 5 capability 广告    ✅ 冻结（js_render/pdf/session）
Step 6 adapter + cohort  ⏳      verdict ⏳
```

**worker 启动与 availability 契约（已冻结口径）**：`startup ≈ 3.3–3.8s` 属 operational cost，**只有 worker `READY` 之后 backend 才允许 `availability=true`**；crash/restart 期间回到 `availability=false`。**不得边启动边投喂第一个 candidate 再说那 3.8s 不算。**

**下一刀**：实现 `Crawl4AIBrowserBackendExecutor`（A2 router/scheduler → adapter → warm isolated worker → provider observation → 主进程 frozen honesty 层 → `ChainStepResult`；`CacheMode.BYPASS`；PDF native strategy；per-`(session, mode)` 隔离；`provider_state` + `canonical_retrieval_state` 双层 provenance；browser tier 3.0s envelope），然后跑 A3-0 frozen 六类 cohort，出最终 verdict。

**production-inert 未变**：`ACTIVE_READER_CHAIN` 未动；Crawl4AI 未注册进 `DEFAULT_BACKENDS`；Wigolo Browser 仍 DISQUALIFIED；不同时挂两个 browser。本刀仅改 fixture server（测试工具）+ docs，未触 production 代码，按 Staged Policy 无需 L1/L2。


## §116 P2-A3-2c Crawl4AI executor + frozen cohort — **未出 verdict：cohort 暴露 contract/measurement 不匹配**

**结果**：executor 与 bridge 已实现并跑通完整路径；冻结六类 cohort 跑完 12 行，但**结果不足以判定 QUALIFIED**，且暴露一处必须在出 verdict 前解决的不匹配。**按规则不调合同、不改 fixture 强行通过。**

### 116.1 交付物

| 交付物 | 路径 |
| --- | --- |
| provider-neutral honesty 层（消除 §112 指出的结构债） | `src/web/research/browser_honesty.py` |
| `crawl4ai` BrowserBackendExecutor + warm worker bridge | `src/web/research/crawl4ai_browser_executor.py` |
| provider 侧 worker（隔离 venv 执行） | `src/web/research/crawl4ai_worker.py` |
| 冻结 cohort runner | `tools/run_crawl4ai_cohort.py` |

**结构**：`A2 router/scheduler → Crawl4AIBrowserBackendExecutor → READY warm isolated worker → provider observation → 主进程 frozen honesty 层 → ChainStepResult`。worker 无 routing / lifecycle / budget / Evidence-Support-Gate authority。

**availability**：仅当 worker `READY` 时 `availability=True`；starting/restarting/crashed 期间统一 `unavailable`（executor 返回 `preflight` policy skip，**绝不**把 startup 3.3–3.9s 记到 candidate 上）。本刀实测 `startup_ms` 3333.9 / 3660.6 / 3699.1 / 3943.7。

**advertised capabilities**：仅 `js_render` / `pdf` / `session`（provider truth 更宽但不广告）。

**deadline**：executor 用 browser tier 独立 envelope 计算 B2 plan；`deadline_hit` / `provider_cancelled` 一律**投影为 canonical bounded failure**（`insufficient_remaining_window`），**绝不**把越界 wall 当 success。

**双层 provenance**：cost 同时携带 `provider_state`（provider 原始判定）与 `canonical_retrieval_state`（冻结层判定）。

### 116.2 cohort 实测（12 行，`A32C.crawl4ai.json`）

| 类 | browser_called | browser_state | usable | chain_action |
| --- | --- | --- | --- | --- |
| `static_control` ×3 | **False** | — | True | resolve ✅ |
| `js_shell` | True | `backend_failure` | False | exhaust |
| `js_shell` ×2 | False | — | False | exhaust |
| **`spa_delayed_render` ×2** | **False** | — | **True** | **resolve** ⚠️ |
| `anti_bot` ×2 | False | — | False | exhaust |
| `session_required` | False | — | False | exhaust |
| `document_heavy` | True | `invalid_content` | False | exhaust |
| `document_heavy` ×2 | False | — | False | exhaust |

`provenance_complete` 全 True（validator 通过）。

### 116.3 ❌ 必须解决的不匹配（本刀不修）

**A3-0 声明的 demand 与 routing 实际派生的 demand 不是同一个。**

```text
A3-0 manifest:  spa_delayed_render.demand = js_render
实际 native 读数: invalid_content / short_doc
route() 派生需求: content_extraction          ← 不是 js_render
```

而 §115.4 已冻结 crawl4ai **只广告** `js_render` / `pdf` / `session`，**不广告** `content_extraction`（正是为了不让普通 transport failure 升级到昂贵浏览器）。两条冻结口径叠加 ⇒ **`spa_delayed_render` 永远不会路由到 crawl4ai**，实测正是如此（`browser_called=False`，`wall=0.0`，chain 在 plain 链上 resolve）。

同类现象：`js_shell` 的 native 读数也不是 `shell_page`（本 fixture 的 native 在 loopback 上直接 `backend_failure`），因此 `js_render` 需求同样没被派生出来。

**⇒ 这不是 provider 能力问题，是"冻结 fixture 的 demand 标签"与"routing 从真实读数派生需求"之间的落差。** 三者只能选一，且**都必须由你裁决**：

| 方案 | 含义 | 代价 |
| --- | --- | --- |
| **① 让 native 读数真实反映 demand** | fixture 的 native 读数必须真的是 `shell_page` / `short_doc`-with-js-need，才能派生出 `js_render` | 需要 fixture 级 native 注入（harness 提供可控 native），**不动合同** |
| **② 扩大 crawl4ai 广告集** | 广告 `content_extraction` | 违反 §115.4 冻结口径，且会让普通 transport failure 升级浏览器 |
| **③ 承认 spa 类不可由 crawl4ai 服务** | 该类判为不可调度 | 与 A3-0 的 `expect_browser_call=True` 冲突 |

我**倾向 ①**：A3-0 的 `expected_routing=try_backend` 与 `expect_browser_call=True` 描述的是"当 routing 判定需要 js_render 时应当调用 browser"；而本刀 harness 的 native 是**真实生产 reader**，它在 loopback fixture 上失败，没有产生 `shell_page`，所以从未派生出 js_render。**这是 harness 的 native 保真度问题，不是 crawl4ai 的资格问题** —— 但也**不能**用"给 fixture 换一个可控 native"来事后美化，必须作为**明确的 harness 修正**登记后重跑。

### 116.4 本刀顺带修掉的 3 个 harness/runner bug（如实记录）

1. 只注册 crawl4ai executor ⇒ chain 在 native/wigolo_http 上 `no_executor_for_backend` 直接 exhaust。冻结链需要**三个 executor 全注册**。
2. 无 content 时把 chain **action**（`exhaust`）当 `outcome_state` ⇒ 非 canonical。改为 `backend_failure`。
3. `usable_content` 与冻结 validator 的 `usable ⟹ success` 语义不一致 ⇒ 对齐为"outcome 为 success"；"取到内容但不足"由 `browser_state`/`browser_usable`/attempts 承载。

另：cohort 必须在 `RESEARCH_WIGOLO_ESCALATION=browser` 下运行（browser tier 是 opt-in）；未设时全部 skip 为 `disabled` —— 这是**正确行为**，不是 bug。

### 116.5 状态

```text
executor + bridge + honesty 层   ✅ 已实现、Ruff clean、完整路径跑通
frozen cohort 12 行              ✅ 已跑完
required dimensions / disqualifiers  ⏳ 未评估（见 116.3，先决问题未决）
verdict                          ❌ 未出（不得在未决时不匹配下判 QUALIFIED）
focused tests (L1)               ⏳ 未写（本刀预算耗尽，下刀第一件事）
```

**production-inert 未变**：`ACTIVE_READER_CHAIN` 未动；Crawl4AI **未**注册进 `DEFAULT_BACKENDS`；Wigolo Browser 仍 DISQUALIFIED；不同时挂两个 browser。

**下一刀（必须先做）**：裁决 116.3 的 ①/②/③ → 若 ①，则登记 harness native 保真度修正并重跑 cohort → 补 L1 focused tests → 出最终 `QUALIFIED` / `DISQUALIFIED` / `BLOCKED`。


## §117 A3-2c harness fidelity defect 登记 + 一致性硬门结果 — **仍无 verdict（发现 A3-0↔A2 contract gap）**

### 117.1 Harness Fidelity Defect（正式登记）

```text
Harness Fidelity Defect
------------------------
A3-0 已预注册每个 fixture 的 browser capability demand
（spa_delayed_render.demand = js_render，expect_browser_call = true）。

A3-2c 首版 runner 却让 ambient production native reader 从 loopback fixture
重新派生 demand，导致 BrowserBackend qualification 被无关的 native-reader
行为污染（实测：native 在 loopback 上返回 invalid_content/backend_failure，
于是 spa/js_shell 从未派生出 js_render，browser 从未被调度）。

定性：harness fidelity defect —— 既不是 Crawl4AI capability failure，
也不是 A2 core failure。
```

**修正方向（裁决 ①）**：加入 **qualification-only frozen predecessor**（只存在于 tests/tools），按 manifest 预条件生成 canonical predecessor observation，再交给**真实** `route()` / `schedulable_now()` / `run_chain()`。**harness 只固定 route 的输入前提，绝不直接指定 backend。**

### 117.2 一致性硬门（新增，fail-closed）

```text
manifest frozen demand  ==  route(frozen predecessor observation).required_capabilities
```

实测结果：

| 类 | manifest demand | predecessor state | `route()` 派生 | 结果 |
| --- | --- | --- | --- | --- |
| `static_control` | `[]` | `success` | `[]` | ✅ OK |
| `js_shell` | `[js_render]` | `shell_page` | `[js_render]` | ✅ OK |
| `spa_delayed_render` | `[js_render]` | `shell_page` | `[js_render]` | ✅ OK |
| `anti_bot` | `[anti_bot_recovery]` | `anti_bot` | `[anti_bot_recovery]` | ✅ OK |
| `session_required` | `[session]` | `login_required` | `[session]` | ✅ OK |
| **`document_heavy`** | **`['pdf']`** | `invalid_content` | **`['content_extraction']`** | ❌ **MISMATCH** |

```text
CONSISTENCY_GATE_PASS = False
is there ANY state whose requirement is {pdf}?  False
```

### 117.3 ❌ 发现：A3-0↔A2 contract gap（`pdf` 需求无法被路由派生）

冻结的 `STATE_CAPABILITY_REQUIREMENTS` 覆盖：`shell_page`/`js_required`→js_render、`anti_bot`→anti_bot_recovery、`login_required`→session、`http_denied`/`rate_limited`/`connect_failure`/`dns_failure`/`tls_failure`/`timeout`/`reset`/`backend_failure`→plain_http、`invalid_content`→（按 adequacy 细化）。

**没有任何 state 的 requirement 是 `{pdf}`。**

而 A3-0 把 `document_heavy` 冻结为 `demand = ['pdf']` 且 `expect_browser_call = True`，同时 `document_support` 是 **REQUIRED_DIMENSION**。

⇒ **A3-0 要求一个 A2 路由权威无法提出的需求。** 这不是 Crawl4AI 的问题（§112.2 已实证 provider-native PDF 路径可用），也不是 harness 能自行解决的：**在真实 `route()` 之下，`pdf` demand 永远不可能出现。**

**必须裁决（我不自行决定）**：

| 方案 | 含义 | 影响 |
| --- | --- | --- |
| **A. `pdf` 是能力声明而非可路由需求** | `document_heavy` 的 predecessor 走 **qualification-only capability demand**，直接喂给**真实** `backend_eligibility(required_capabilities={pdf})`（仍是冻结 eligibility 原语，仍不绕过调度语义），并登记"A2 矩阵无 pdf 派生"为 **routing gap debt** 留 A3-3 | 不改 A0/A2；`document_support` required 维度可被真实测量 |
| **B. 登记为 A2 缺口，A3-2 判 `document_heavy` 不可测** | required 维度无法测量 ⇒ 按合同 fail closed | 会因一个**路由派生缺口**淘汰一个已实证能读 PDF 的候选，结论失真 |
| **C. 给 A2 矩阵加 pdf 派生** | 修改 `progressive_routing` 核心 | **违反 A3 边界**，禁止 |

**我倾向 A**：A3-0 的 `capability_demand` 是**能力契约**（"当需要 pdf 时能否胜任"），`document_support` 是 required 维度；而 A2 矩阵缺 pdf 派生是**另一个**问题（A3-3 的 demand-generation 议题，与 §116.3 登记的 reachability debt 同族）。B 会让路由缺口污染 provider verdict，C 越界。

### 117.4 已登记的两笔独立债务（均不属 A3-2 verdict）

```text
1) production browser-demand generation / reachability debt
   真实 production：native → classification → route 是否能在真实 browser-needed
   页面生成 js_render/pdf/session demand。实测 SPA fixture 走
   invalid_content/short_doc → content_extraction。A3-3 activation 必须单独检查。

2) A2 routing matrix has no pdf derivation（本 §117.3）
   STATE_CAPABILITY_REQUIREMENTS 中不存在 → {pdf} 的映射。
```

**A3-2 不因此修改 A0/A2。**

### 117.5 状态

```text
harness fidelity defect   ✅ 已登记（117.1）
一致性硬门               ✅ 已实现；5/6 通过，document_heavy MISMATCH（fail-closed 生效）
frozen predecessor harness ⏳ 待实现（依赖 117.3 裁决）
12-row cohort 重跑        ⏳
L1 focused tests          ⏳
verdict                   ❌ 未出（不得在 pdf 需求无法派生时判 QUALIFIED）
```

**static-control 门保持**：即使使用 deterministic predecessor，`static_control → browser call = 0` 仍是硬断言（browser READY/available 也不得启动）。

**production-inert 未变**：`ACTIVE_READER_CHAIN` 未动；Crawl4AI 未注册进 `DEFAULT_BACKENDS`；Wigolo Browser 仍 DISQUALIFIED；不同时挂两个 BrowserBackend。本刀未改 production 代码。

**下一刀**：裁决 117.3 的 A/B/C → 实现 frozen predecessor harness + 一致性硬门测试 → 重跑 12-row cohort → 补 L1 focused tests → 用**原** `REQUIRED_DIMENSIONS + DISQUALIFIERS` 机械评估 → 出 `QUALIFIED` / `DISQUALIFIED` / `BLOCKED`。


## §118 A3-2c v2 frozen-predecessor cohort — **verdict 仍未出：2 个类失败 + 1 个投影 bug，均不属"改合同可解"**

### 118.1 frozen predecessor harness（裁决 A 已实现）

`tools/run_crawl4ai_cohort_v2.py`：按类别提供 **frozen predecessor state**，只固定 `route()` 的**输入前提**；决策仍走**真实** `route()` / `backend_eligibility` / `run_chain` / executor。**harness 从不指定 backend。**

一致性门两态（fail-closed）：

```text
static_control        PASS_ROUTE_DERIVED
js_shell              PASS_ROUTE_DERIVED
spa_delayed_render    PASS_ROUTE_DERIVED
anti_bot              PASS_ROUTE_DERIVED
session_required      PASS_ROUTE_DERIVED
document_heavy        PASS_WITH_ROUTING_GAP   A2_NO_PDF_DEMAND_DERIVATION
```

`document_heavy` 是**唯一显式例外**：只跳过 `retrieval_state → route() → {pdf}` 这一段；`backend_eligibility`（真实原语）仍决定谁可执行，executor/outcome/provenance/budget 全部真实。

### 118.2 cohort 结果（12 行）

| 类 | browser_called | browser_state | usable | wall |
| --- | --- | --- | --- | --- |
| `static_control` ×3 | **False** | — | True | 0.0ms ✅ **负向门成立** |
| `js_shell` ×2 | True | `backend_failure` | False | 1748.7 / 293.7ms ❌ |
| **`spa_delayed_render` ×2** | True | **`success`** | **True** | 1402.1 / 1368.0ms ✅ **真渲染 rescue** |
| `anti_bot` ×2 | **False** | — | False | 0.0ms ✅ **不广告 ⇒ 不调度**（`no_capable_backend`） |
| `session_required` | True | `login_required` | False | 1286.8ms ✅ 诚实失败 |
| `document_heavy` ×2 | True | `invalid_content` | False | 1216.8 / **5003.2ms** ❌ |

**正向结果**：`spa_delayed_render` 真实 rendered rescue（`browser_state=success`、`usable=True`、1.37–1.40s ≤ 3.0s）。
**负向结果**：`static_control` browser **0 调用**（browser READY 也不乱启动）。
**routing 真实性**：`anti_bot` **未被调度**，因为 crawl4ai 不广告 `anti_bot_recovery` ⇒ `no_capable_backend`。这正是 §115.4 冻结口径要的行为，也说明 **class FAIL ≠ provider 被误用**。

### 118.3 ❌ 失败一：`document_heavy`（required 维度 `document_support`）

**根因（非 PDF 能力问题）**：provider 真的取回了 PDF 正文，但**正文只有 309 字符 < `SHORT_CHAR_THRESHOLD = 800`** ⇒ 冻结 adequacy 层判为 `short_doc` → `invalid_content` → **不可用**。

```text
provider: PDF 路径成功、真实正文 309 chars（§112.2 Gate 1 已独立实证）
frozen adequacy: 309 < 800 → short_doc → invalid_content → usable=False
```

⇒ 这是**"文档长度 vs 字符阈值 adequacy 规则"的不匹配**，不是 Crawl4AI 不能读 PDF。**不得在 A3-2 修改 A0 adequacy 阈值或 A3-0 required 维度** —— 需要裁决（见 118.6）。

### 118.4 ❌ 失败二：`js_shell`

browser 被调用（`browser_called=True`）但得到 `backend_failure`。该 fixture 页面**本身没有 JS 可执行**（`<noscript>` + 空 `#root`），渲染器只能拿到 noscript 文本；Crawl4AI 自身检测器再把它判为异常 ⇒ provider_success=False ⇒ executor 投影为 `backend_failure`。

⇒ 诚实非可用是对的，但 A3-0 的 `js_shell` 类期望 rescue。**该 fixture 无法区分"渲染失败"与"页面本来无内容"** —— fixture 保真度问题（与 §117.1 同族），不是 provider 能力问题。

### 118.5 🐞 投影 bug（本刀发现，未修）

`document_heavy` 第二行 wall **5003.2ms** 且 `bstate=invalid_content`：

```text
executor 传 deadline_ms ≈ 3000 → bridge 等待 deadline + 2000ms slack = 5000ms
worker 在 3000ms 未返回（PDF 路径的 requests 下载在 to_thread 中，取消未真正生效）
→ bridge 读超时 → 返回 {"error": "bridge_read_timeout"}
→ executor 把它投影为 from_invocation_state("empty") = invalid_content
```

两处问题：
1. **bridge 读超时应投影为 bounded failure（`budget_exhausted`），不是 `invalid_content`** —— 当前会伪装成"内容不合格"。
2. **worker 的取消未约束 PDF 下载路径**（阻塞线程不可取消），该行实际越界 3.0s envelope 达 2s。

### 118.6 需要裁决的三项（我不自行决定）

| # | 问题 | 选项 |
| --- | --- | --- |
| 1 | `document_support` 要求 usable，但冻结 adequacy 阈值(800)把 309 字符的真实 PDF 判为 `invalid_content` | (a) 承认"短文档"是 adequacy 规则的正确行为，`document_heavy` 用**更长的 PDF fixture**（fixture 保真度修正，不改合同）；(b) 修改 adequacy 阈值（**违反冻结**，禁止）；(c) 登记为 A3-0↔A0 不一致（同 §114.1 的 contract defect 族） |
| 2 | `js_shell` fixture 无 JS 可执行，无法表达"渲染救回" | (a) fixture 改为**真正需要 JS 才能出正文**（如 `#root` 由脚本填充）；(b) 接受该类为诚实失败并登记 |
| 3 | bridge 读超时投影 + PDF 路径取消未生效 | 本刀发现即修（属 adapter 正确性，不涉合同）：bridge 超时 → `budget_exhausted`；PDF 路径加可取消边界 |

**我的倾向**：1(a) + 2(a) 都是**fixture 保真度修正**（登记为 defect 后修，不改 A0/A2 合同），3 是 adapter bug 应当修。但 1 涉及"required 维度是否可由短文档满足"，语义上应由你拍板。

### 118.7 状态

```text
frozen predecessor harness  ✅ 已实现
一致性门两态               ✅ 5×PASS_ROUTE_DERIVED + 1×PASS_WITH_ROUTING_GAP
12-row cohort              ✅ 已跑完
required dimensions        ❌ document_support 未通过（adequacy 阈值 vs 文档长度）
class 结果                 spa ✅ / session ✅ / static_control ✅ / anti_bot FAIL(报告) / js_shell ❌ / document_heavy ❌
adapter 投影 bug           🐞 已发现未修（118.5）
L1 focused tests           ⏳
verdict                    ❌ 未出（不得在 required 维度失败时判 QUALIFIED）
```

**production-inert 未变**：`ACTIVE_READER_CHAIN` 未动；Crawl4AI 未注册进 `DEFAULT_BACKENDS`；Wigolo Browser 仍 DISQUALIFIED；不同时挂两个 BrowserBackend。

**已登记债务**（A3-2 不修）：① production browser-demand generation / reachability debt；② `A2_NO_PDF_DEMAND_DERIVATION`；③ 新增 **document-length vs adequacy-threshold mismatch**（118.3）。
