# RP-1 R6b 诊断与修复证据

2026-10-08，B线 `codex/reading-notebook-ui`，合同基线 `b21b98b3`。
恢复点 `4c36b935` / `b979b7aa` / `ff8b87ca` 均保留；未推送、未开PR。

## B1：LOCAL CLOSED

先只读检查原始S3/S5 SQLite，关联请求、真实读取、transport/content hash、
结构化project/version与正文跨度、native身份验证、Lookup terminal。
原始记录的内容哈希及原有native身份验证均有效；首次身份丢失发生在
Lookup relevance：native reader将project/version分行序列化，旧相邻文本模式拒绝
`project: Claude Opus\nversion: 5.5` / `project: FastAPI\nversion: 0.136.0`。
不是resolve_identity规范化缺陷，也不是来源本身缺少精确身份。

另取两份真实官方HTTP响应，保存transport/decoded原文及字段绑定。
S5 PyPI JSON与旧transport digest相同，JSON路径能对应精确项目/版本；
S3官方HTML有精确heading/model-id跨度，但动态页面digest与旧记录不同，
只证明当前来源及生产提取链，不冒充原始旧payload重建。原SQLite字节未修改。

唯一生产修复是 `lookup_terminal._native_identity_matches` relevance适配：
仅接受原生official_metadata_http_v2支持域FastAPI/Opus，精确计划URL、成功读取、
source_version、有效transport digest、唯一project/version、精确正文span，并复用
既有verified_release_identity/verified_opus_identity及content hash验证。
通用文本匹配、语义关联规则、claim支持与发布资格保持原有规则。
未取得的release_date仍是gap，FastAPI包上传时间不视为发布日期。

先红后绿正例2条；错误项目、相邻版本、缺失/错误span、重复身份、source_version、
content/transport hash、URL及读取失败负控20条，均SAFE_ABSTAIN且没有handoff。
L1身份/Lookup/Standard绑定影响集175 PASS（62.16s）；
命名L2 research-presentation-v1 286 PASS（95.76s）。

原始S3/S5查询预登记后，经真实Chat API/提供商/隔离SQLite执行：两者均
ESCALATE_STANDARD / claim_support_insufficient；实际handoff通过原生产loader，
重算terminal取得同一payload，自然创建Standard child，无注入状态或gap。

| 样本 | thread / turn | Lookup → Standard | Standard实际结果 |
| --- | --- | --- | --- |
| S3 | chat_8fa52e73cfc34771a6ff35c193657188 / turn_10ce7287dd774522b25678401e2ad7a8 | web_lookup_a4efff442eca453ab709a72201675d83 → standard-d35fed3b2c9d486cf5d4dd0e | partial，budget_exhausted，release_date未解决 |
| S5 | chat_9a579f22305f40db8817c5a5fa8d9667 / turn_ef1b2fc57bd74651992f07cd25c92964 | web_lookup_b7007e9ca80b4f5fa20d5ff9a8cdc3ed → standard-a6cbc61618564696f64c15e2 | partial，planner_invalid，release_date未解决 |

S3自然触发Deep child `deep-4b33f2b443c70522018a8bdf`，parent为上述Standard。
持久version6、failed，stop_reason=claim_planning_blocked_by_policy，
provider_status=unavailable；claim_engine_policy_audits记录research_claim_planning
blocked_by_policy（public_research_question/research_time_context）。
Deep-4A实际审计fail、audited-but-not-approved、publication_authority=false。
这证明自然child创建，不能算成功研究或恢复资格。S5本次观察没有Deep child。

## B2：诊断记录（关闭状态见Current Handoff）

原批S2/S4没有保存原始模型响应，不能回推旧question_identity具体是空行还是重复ID。
先用透明completion观测器执行原样查询：返回值逐字透传，保存原响应与hash、
schema/task_id、调用阶段及严格parser判定，不制造合法响应。

S2新观测4个唯一RQ、3条查询，task_id正确，原parser接受；旧question_identity未复现，
根因保留未确定，不能声称已修复该旧失败。
S4新观测5个唯一RQ、task_id正确，但proposed_queries有5行，首个不一致为
`$.proposed_queries`超过既有最大3行，原parser正确拒绝invalid_rows。

只修改模型指令，明确总查询数最多3、RQ最多6且ID唯一、保留所有RQ/实体/版本并
原样echo task_id；增加validation_error观测具体guard。不修改schema/parser，
不截断响应、不改事实、不增模型调用/修复循环/预算。
修复后预登记原样S2/S4再次执行，分别5/4个RQ、均3条查询，原严格parser接受。
最终仍SAFE_ABSTAIN / requested_claim_plan_unavailable，通用比较域字段计划不支持，
不把解析成功改报为研究资格或答案成功。两次成功不代表模型永远不会产生非法结构。

新增重复RQ/5查询/错task负控均经原guard拒绝；仅1次interpret调用，无修复重试。
语义模块37 PASS（14.90s）。初次负控fixture误改共享RQ列表导致旧测试失败，
改为deepcopy后消失；不是生产回归。最终语义影响集结果在阶段封板时补记。

## 证据与边界

外部证据根目录 `D:/study-agent-validation/reading-notebook-ui-evidence/`：

- `r6b-identity/source-trace-live.json`，transport/decoded原文，before-tests/focused/l2日志。
- `r6b-identity/live/registry.json`、result.json、runtime.db：真实交接/lineage。
- `r6b-semantic/` 与 `r6b-semantic-after/`：预登记、原始model-responses.jsonl、SSE、SQLite。
- `r6b-closeout-observations.json`：生产loader重验、原响应schema判定、DB hash。

Ruff、mypy baseline无新增（122/128，NEW0）、diff-check通过；无UI变更，
沿用R6a证据，不重复前端/全后端L3/远端CI。owned服务已关闭，原main/A线dirty保留。
Lookup/Standard/Deep预算、身份/span/hash、question_identity、Deep-4B与learning权限冻结。
RP-1仍NO-GO；成功Deep执行、持久恢复、TTUV均NOT_OBSERVED。
下一slice为R6c前置诊断：辨明真实Deep策略拒绝及Standard planner_invalid，
不能通过跳过策略/伪造planner合法结果进入新资格批次。
