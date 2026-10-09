# RP-1 字段级研究单元合同与只读覆盖追踪

2026-10-09；branch `codex/reading-notebook-ui`，base `4cf8dcec`。
本批关闭的是诊断/合同/可复核追踪；字段单元的生产声明、抽取、验证及 stop 接线
尚未实施，RP-1 / R6 仍 NO-GO。当前状态统一由 PROJECT_STATUS.md 管理。

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
