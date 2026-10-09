# RP-1 字段级研究单元合同与只读覆盖追踪

2026-10-09；branch `codex/reading-notebook-ui`，base `4cf8dcec`。
下文诊断基线对应 `e1542050`：只读追踪已关闭，当时生产声明、抽取和验证尚未实施。
2026-10-09 后续 shadow 实现见末节；语义 stop 接线仍未实施，RP-1 / R6 仍 NO-GO。
当前状态统一由 PROJECT_STATUS.md 管理。

## 真实记录与首次缺口

只读使用既有三条自然 Deep 链，没有新的运行、搜索、读取或模型调用：

| 历史记录 | 独立支持 cluster / 要求 | 原结构 Gate / run终态 | required / extracted units | 原字段状态 |
| --- | --- | --- | --- | --- |
| S3 / deep-851dc65cd1c860c18d4055c4 | 0 / 2 | block / partial | 0 / 0 | version、official_positioning 已在 Lookup 绑定；release_date 未绑定 |
| S5 / deep-3e1d4ba6f86c7e33795657fc | 2 / 2 | pass / completed | 0 / 0 | version 已在 Lookup 绑定；release_date 未绑定 |
| N3 / deep-9d2e50db067c75b0da1d17ce | 1 / 2 | block / partial | 0 / 0 | version 已在 Lookup 绑定；release_date 未绑定 |

精确 run ID/parent/thread/turn/version 以外部 S3/S5/N3.json lineage 为准。
三例原 assessor 均为 semantic_adequacy=not_evaluated；原最终发布审计 fail、无批准。
这些是**历史 Deep 输入**。上一批 4cf8dcec 的新 S5/N3 已自然 Lookup VERIFIED，
日期字段由新的官方定向读取得到；本工具不会把新证据倒写到历史 Deep，
也不把历史未绑定日期解释为上一批修复回归。

沿原代码路径定位四处合同边界：

1. `claim_planner._build_initial_state` 使用 policy 的 code-owned requirement；
   `policy.evidence_policy_for_claim` 声明角色/独立来源/读取要求，没有声明 required_units。
   因而“发布日期和版本号”可以是一个合法原文 anchor，但不是两个已声明字段要求。
2. `active_semantics.ExtractedEvidenceLink` 产出整句 claim 的 relation/strength/
   anchored_spans 等，没有字段单元协议；正文抽取不会自动生成 EvidenceUnit。
   不能把已有来源数、读取次数、span 或整句 supports0.9 自动转成字段覆盖。
3. `claim_evidence_assessment` 对空 required_units 返回 not_evaluated，
   不是 adequate。其 generic unit 覆盖以已声明 unit_id/modality 为前提，
   仍不能自动替代字段事实关系验证或 qualified judge。
4. 原 Evidence Gate 是结构/角色/独立性/时效/冲突门，不消费 required_units；
   `coverage_stop_assessment` 明确是未接线的 advisory。无 requirement 的兼容行为
   可能给 covered/stop_candidate，并同时报告 adequate_critical_claim_count=0。
   两者不能据此被解释为字段语义完成。本批没有改 frozen Gate 或 advisory。

这不是提取后丢掉了两个既有字段 unit：当前生产路径尚未声明或抽取它们。
强行补 ID 会制造缺乏事实资格的覆盖，增大预算也不能补协议。

## 冻结的字段单元合同

### 要求侧：先于证据

- 从原始问题及已验证 handoff 的完整 requested_fields / RQ 身份生成要求；
  不从已经返回的字段、最后取得的来源或模型答案反向删减要求。
- 每个字段关联 question_id / RQ、claim_id、精确请求实体与版本、原问题跨度、
  稳定 unit_id、字段关系及 modality。不能把相邻版本归一为目标版本。
- `release_date` 与 `distribution_uploaded_at` 等关系分别声明；未知字段保留未知，
  不能转成零、已覆盖或被省略。
- 多字段可以仍属于一个合法原文 claim；增加覆盖粒度不要求伪造多个重复 anchor。
  通用研究或多主题问题没有已有严格 requested-field planner 时，保持未声明，
  不用关键词猜测其全部事实要求。

### 证据侧：独立验证每一项

- 候选单元必须关联现有 evidence ref、原成功读取及同版本 source hash/span、
  source role、cluster、精确实体/版本、字段关系和已验证值；model 只能提案。
- 原文存在 span 不等于支持字段；同名 unit_id、高 confidence、来源数量或
  整句 supports 不足以证明 release_date 等关系。
- 官方结构化字段走原 reader/provenance 验证；可确定验证的关系走原 binder。
  其余关系保留 NOT_EVALUATED，不能用未资格化的模型 judge 补齐。
- 错项目、相邻版本、伪造或损坏 hash、缺 span、错关系、日期冲突、上传时间冒充
  发布日期、弱或不合格 evidence、重复同域来源均继续拒绝。
- 原 cluster/主来源/强度/角色/时效/冲突要求及审计门不变；字段粒度不能减少门槛。
  部分字段支持须分别表达，不能提升整个多字段问题为已验证。

### 覆盖、停止与发布分别记录

声明缺失=NOT_DECLARED，未验证字段=NOT_EVALUATED，部分覆盖与冲突分别保留；
声明了单位但尚无证据不是“声明缺失”，不能混为一类。
结构完成、generic content-unit 覆盖、字段关系资格、最终审计及发布权是不同记录。
本批不让新的追踪输出参与 Evidence Gate、stop、routing、持久 cursor 或发布。
未来生产接线必须独立验收协议、兼容、恢复与字段正负控；任何共享合同或
生产权威切换需按仓库 L3 规则执行，不能借本次观测批准。
Deep-4B/qualified judge、预算及 A 线 durable learning 继续冻结。

## 已实施：可重复只读工具

`tools/trace_research_field_coverage.py --db <已保存DB> --turn-id <turn> --out <JSON>`：

- SQLite mode=ro + query_only；原 handoff、terminal、publication 验证器、实际 child
  source_run_digest、源请求/父子/owner 身份及原 ResearchState loader 校验。
- 要求字段来自原已验证 handoff；Lookup 已绑定 refs 和 Standard **recorded** status
  分开报告。Standard snapshot status 不是重新签发的支持资格。
- Deep generic unit assessor、原结构 Gate 与原 advisory 原样报告；没有冻结的
  字段映射时，字段绑定状态统一 NOT_EVALUATED、field_semantic_completion_observed=false。
- field_trace_id 只按 query hash/field 稳定生成，是诊断标识，**不写入 RequiredUnit**。
- 输出永不授予发布权，不生成证据、不增加模型调用、不改研究状态；
  检查输入 state 与 DB/WAL fingerprints 前后相同，拒绝输出覆盖 DB/sidecar/同文件别名。
- 未进入 production API/runtime/UI；只有工具与测试直接消费。

工具当前要求已有完整 Deep terminal 与 audited publication artifact；缺少这些记录
时不支持追踪，不回退为已合格，也不会创建任务补齐。本批唯一新实现是诊断工具，
生产 src/ 未修改。已有 R6a、定向来源读取、seed、
进程重启、TTUV 和 UI 不重做，不重复八个真实运行。

## 验收与保留的失败

20 新测试覆盖结构 pass 但语义未观测、已知版本/缺日期隔离、unit 覆盖 adequate
也不能凭空创建字段映射、声明但缺证据、输入无 mutation、错问题/版本/hash/
权限/额外字段拒绝、稳定 trace ID、参数化只读 SQL 与输出保护。
命名 L1 `research_field_unit_trace` **221 PASS / 88.09 秒**。
首轮命名 L2 `research-field-unit-trace-v1` 389 PASS / 129.23秒；收尾时明确关闭只读
连接，再对最终候选复验 **389 PASS / 129.10秒**，最终工具自身20项及三例30+3
检查再次PASS。范围为整个诊断/单元/
claim/Gate/advisory/原 terminal/pub/绑定/审计邻接栈，不重跑无关工作台或全 RP 栈。
Ruff、两新文件 format、mypy baseline NEW0（122/128、resolved6）、diff-check PASS。
不触发 L3：没有生产行为、共享模型/schema/cursor或权威切换；原生产869回归保留。

三条真实 DB trace 共30项检查；独立副本损坏 source audit input、child owner、
handoff hash 的3项拒绝负控PASS；所有原 DB 字节不变，0 provider calls / 0 admissions。
首次审计 hash 负控只修改 row.version，原 source_run_digest 不包含该技术计数，
所以正确未触发 hash 拒绝；已改为修改实际 selected_sources 审计输入。
没有为了让负控变绿而改变原 digest 合同。初次工具使用不存在的 terminal.parent_run_id
已按实际 Standard child lineage 修正，原终态/持久数据未改。

证据 `D:/study-agent-validation/reading-notebook-ui-evidence/r6c-field-unit-trace/`：
registry/base/tool hash、S3/S5/N3完整 trace、30+3 audit、隔离负控副本、测试日志和
closeout-state。所有操作只读，无本窗口服务启动，未 push/PR/CI。

## 唯一下一批

**字段要求声明 → 字段证据候选抽取 → 严格验证的 shadow 闭环**。
使用本合同及既有请求/来源记录，在读取前确定要求，只对可证明关系做支持绑定，
集中错身份/版本/关系/hash/span/部分覆盖/恢复负控；先保持原结构 stop 和 Deep-4B，
不自动将同名 EvidenceUnit 接入权威。生产范围需要触碰共享合同或跨层运行时协议时
执行 L3；语义 stop 切换与 qualified judge 独立留门，不与这个诊断 slice 混并。

## 2026-10-09 后续：字段声明/证据验证 shadow 闭环

branch `codex/reading-notebook-ui`，base `e154205062b1b8a2096abcc037b988f3cf6228bd`。
实现范围只有 `field_unit_shadow.py`、Deep admission、runtime 三个旁路接缝及定点测试。
本批 shadow 闭环 LOCAL CLOSED；RP-1 / R6 仍 NO-GO，最终 head/clean 由 Git及外部closeout恢复。

- 新 Deep 的首次合法 admission，在同一原子 attach 中持久保存原 query、精确目标、
  全量严格 requested fields、原问题跨度和稳定 unit ID；在 dispatcher、模型或读取之前。
  未有严格字段规划或实体不唯一时 NOT_DECLARED，不猜测通用问题的全部要求。
  原 envelope 已存在的旧 child 不回填；没有从历史证据倒推声明。
- read 边界保存实际输入与存储正文切片的 SHA；原成功抽取后绑定 server-owned
  evidence ID。每次原 checkpoint 旁路重算 coverage，与原 state/cursor/sources 原子持久化。
  不追加重复单元，不修改 ResearchState / EvidenceUnit / RequiredUnit 或 cursor schema。
- 只消费原 Gate 同一强度、角色、时效和成功读取规则下的 eligible supports。
  每项候选必须有实际正文 hash、原有效 anchored span、同一窗口的唯一精确身份、
  evidence/claim/question/cluster/source ref；窗口不能借用相邻段落引用。
- version 仅证明精确具名身份，不证明 latest、稳定版、性能或整个问题。
  release_date 只接受具名版本直接表达的有限 released/release date ISO 语法，
  再经过原 binder；上传、更新、否定、其他产品的日期、歧义及未知定位关系不授予支持。
  相邻版本、预发布版和精度仍由原 resolve_identity 区分；本地 ASCII 边界允许中文紧邻
  版本号，未修改原身份适配器或 Lookup/Standard 判定。
- 每个字段独立保留原 min-independent-sources / primary 要求；重复 cluster 不增加票数，
  缺主来源、原主张不可用或存在强冲突时不能 COVERED。可验证字段值冲突保留 CONFLICT，
  有支持但来源要求未齐为 PARTIAL，无可证明关系为 NOT_EVALUATED。
- declaration hash 及从原 query 重算的完整要求共同校验，不能读后删掉缺失字段。
  malformed shadow 仅 INVALID，不改变研究的原错误/取消/停止路径。
  所有 shadow 状态的 stop_authority/publication_authority 均 false。

原 Evidence Gate/结构 stop、模型协议、全部研究预算、审计和 Deep-4B 不改；
`COVERED` 是上述字段旁路的观察状态，不能转成 generic assessor adequate 或正式答案批准。
源记录的新增 seal 是内部兼容 metadata，旧记录缺 seal 时不自动补资格。
UI 与 A 线学习持久状态未修改，也不把新状态输出给前端。

38 定点测试包括正例、错项目/版本/预发布/关系、缺跨度与损坏哈希、私有 URL、弱证据、
同 cluster、主来源/冲突/不可用、部分覆盖、未知关系及非法删减声明。
生产服务 admission 测试证明首次 dispatch 前已持久声明，旧 envelope 不回填。
实际 runtime + SQLite 路径在 eligible extraction checkpoint 后模拟中断，用新 repository/
dispatcher 连接恢复原 cursor；两项字段最终各两个独立支持 cluster，物理读取共2次，
没有重复已完成读取。legacy 和 malformed 对照均保留原 completed/evidence_gate_pass。
这些使用确定性模型/工具替身，不能替代真实提供商或真实进程重启验收；此前真实重启
证据保留，本批不重复或扩充其主张。

外部 `r6c-field-unit-shadow/` 保存 final-qualification-tmp 的实际 DB、原声明/字段候选、
read-only runtime-witness.json、14核对、聚焦/集成/全套日志与最终 closeout。
其中三条历史自然 Deep 原 DB 只读检查，仍 NOT_DECLARED、字节未改变。
没有启服务/发起新自然研究；新 live qualification、浏览器 TTUV 均 NOT_OBSERVED。

后续唯一门：**新自然 Deep 的字段 shadow 实际观测与持久恢复资格**。
预登记有限样本，沿原 Lookup→Standard→Deep 资格链观察字段声明、正文/span、每字段
cluster 与恢复；不强造 child、不倒写旧证据、不切换语义 stop/发布门。
若新样本自然 Lookup VERIFIED 或未能升级，要保留该真实结果，不能当成 Deep 成功。


### 本候选验收结果

最终定点38 PASS/13.70秒；初轮命名L1 308 PASS/208.68秒。增加归属/冲突负控后，最终命名RP整栈907 PASS/448.96秒包含完整影响集；唯一后端 L3：**4311 passed, 6 skipped in 5922.84s (1:38:42)**。生产/test字节在最终focused、L2、L3期间不变，candidate-registry 重核PASS。Ruff全src/tests/tools、两新文件format、mypy baseline NEW0（122/128、resolved6）、diff-check、7文件范围与局部自审PASS。首轮未提交L3为4309PASS/6SKIP/2FAIL，1536.27秒，两个RQ1-C失败均为exact-clean-HEAD门的正确拒绝；先固定0f3a4913候选，preflight和RQ1-C聚焦通过后在干净HEAD复验完整套件，未修改或绕过资格门。l3-first-failed.log保留。收尾只改文档并amend未推送提交，生产/test bytes不变，不再重跑L3。

初次夹具未声明cluster导致原ResearchState builder拒绝，已补正确的已知cluster；原Unicode边界会漏掉中文紧邻版本的query，shadow专用ASCII边界兼容中文并拒绝prerelease/相邻版本。引用窗口内另一产品或否定的日期不能绑定为目标release_date，已用严格直接关系语法及负控封住。未修改原身份归一、事实资格、预算或发布门。

最终实际SQLite证据的14项只读核对PASS；新模型/读取/搜索均为测试替身，真实provider与自然Deep资格未新增，不以本地COVERED宣布R6完成。保留此前真正进程重启与S1 TTUV证据，但新协议的真实运行/恢复与TTUV仍待下一批。

## 新协议自然观测与产品样本（2026-10-09）

生产头8dcf222e保持不变。本批预登记5例、真实提供商各执行一次，无路由/结果注入，未扩功能或额度。

| 样本 | 实际路径与结果 | 资格判定 |
| --- | --- | --- |
| 原样S3 Opus5.5日期/版本/定位 | Lookup→Standard→自然Deep，真实进程重启后partial/evidence_saturated | 3声明字段均NOT_EVALUATED，0候选；不是字段资格PASS |
| Python3.14.0日期/版本 | Lookup VERIFIED/requested_claims_bound | 正常不升级；不是Deep样本 |
| 原样S5 FastAPI0.136.0日期/版本 | Lookup VERIFIED/requested_claims_bound | 已修路径保留；不强造Deep |
| G1 流萤首发至目标4.2版本攻略 | SAFE_ABSTAIN/requested_claim_plan_unavailable | 无Standard/Deep；严格planner适用域不足，版本未知不能补造 |
| W1 9×9气与提子教学 | 普通模型文字/ASCII图，只有搜索候选未读正文，无Standard/Deep | 五项确定性矛盾，教学FAIL；不声称棋盘UI已经接入 |

### 真正重启与字段权威

S3 child `deep-2b9090d90d7147eb7507a743`，parent `standard-ca870c691a955ccabb6548f7`，
thread `chat_8d630582256443e1b26eb678f44a99c4`，turn `turn_fba0af75c8e7429f8fc5a467d7b55de6`。
首次声明事件10:56:34.466913 UTC，首个child规划10:56:34.522870 UTC；生产admission仍先于dispatch。
PID18116在version12/searching/有已完成planner与inflight search时硬终止；PID27500正常启动，
默认lease/scan恢复同child，version164终态。声明sha
`9737e5e42f06bc47d4580b32c1c46d2a5cae1909fee1c343a237b3b1be85c873`
在重启前后不变，原截止/seed不变；已完成操作一次，未知外部请求可以按原预算重试，
不能宣称远端exactly-once。终态再新启动，经过17秒scan，全部run rows、child/version/shadow不变。
38只读原validator/hash/span/声明重算/预算/恢复核对及4终态核对PASS。
Deep elapsed145.671秒含恢复等待，硬180/软120秒、12physical reads/40candidates/80000chars不变，
0新physical read，复用真实Standard正文；11模型操作不是所谓统一6-call上限的证据。

S3只有一条supports0.6，低于原0.7，其余三条lead0.05；旁路未接受强支持候选。
这是原资格不足，不能为了样本变绿提高strength。release_date仍无绑定；Lookup已绑定的
version/official_positioning照原权威保留，Deep影子字段未支持不撤销Lookup资格。
原audit fail/critical_question_unanswered，audited-but-not-approved，stop/publication_authority=false。
新真实COVERED正例、真实错版本/引用错位负控尚未取得；不能用本地负控或42恢复检查替代。
无浏览器正式回答首次显示观测，TTUV NOT_OBSERVED，绝非0秒。RP-1仍NO-GO。

### 用户批准的流萤与围棋样本

流萤采用跨版本/机制/投入/环境/证据类别问题，目标4.2无可靠来源则未知。
原Lookup入口在`requested_lookup_fields`不能声明全量请求时返回
`requested_claim_plan_unavailable`；G1恰好停在此处，不能归因于Deep时间或搜索额度。
G1/W1严格shadow预检查NOT_DECLARED；当前只支持已定义的严格字段，不具备游戏配队/机制单元合同。

W1实际回答有：声称只剩1气却画四面围子；落子前后图相同；己方白子连接落点称自杀
（实际连块8气）；练习中心为已无气黑子；四个白块各3气，根本没有题目所述单步提子解。
原始回答与五项计算反例保留，不以说明文字或独立正确样件覆盖失败。
独立`go-liberties.html`与三SVG为UI线可复用配图/交互验收样件：固定9×9坐标、气数、
黑E4提白E5前后图、唯一黑C2提白C3练习；同一状态驱动图与判定。
确定性穷举与真实Playwright1440桌面/390手机点击已占点拒绝、合法提子反馈、移除白子与
无横向溢出PASS，截图已人工查看。一个favicon404为非阻断静态请求。
不是系统真实生成内容或生产UI，不含完整对弈/劫/死活引擎，不写入durable学习状态。

外部`r6c-field-shadow-live/`包含registry/source hashes、原SSE/GET/DB、checkpoint/declaration事件、
before-kill-row/after-kill.db、audit.json(38)/terminal-probe.json(4)、product-audit.json、
原回答、棋盘样件/SVG/截图与closeout。所有owned服务与浏览器全关，无push/PR/CI；
生产字节未变，复用已有38/907/L3 4311PASS6SKIP/mypy NEW0，文档检查足够，不重复全套。

下一RP-1唯一切片：以G1首断点为入口的**通用复杂问题请求规划与自动路由适用域合同/只读诊断**。
先确定原问题全量/RQ与可验证来源如何取得合法handoff，不删字段、放宽身份/证据、
强造child或改预算/stop/Deep-4B。围棋棋盘结构/规则校验属于独立UI/教学线；
产品样本失败如实保留，不把其额外能力混入已冻结的RP-1验收来宣布CLOSED。
