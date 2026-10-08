# RP-1 R6c 前置阻断与真实观测

2026-10-08，本地生产候选 `3d52f5a6`，branch `codex/reading-notebook-ui`。
结果：前置阻断已定点修复；R6c / RP-1 仍 NO-GO，未推送、未开 PR。

## 定点修复

- `3d21748e`：语义提案最多5条；按RQ覆盖、官方域名与去重确定性选择，记录暂缓原因。实际查询、读取、时间不增加。
- `2bec1485`：Deep首次合法接管后，从持久父turn复制联网策略；父授权缺失/拒绝时仍拒绝，不默认授权。
- `c96453a1`：Standard复用既有提供商thinking配置；明确严格四字段schema与服务器已发现URL清单，原validator保留。真实900-token请求曾消耗788 reasoning tokens并截断；额外type字段、未发现URL仍拒绝。
- `3d52f5a6`：合法候选的unknown来源角色在证据抽取入口返回不可用，不调用模型、不产生证据。非法角色仍拒绝。修复原内部ValueError导致整个Deep中止的合同不一致。

未修改预算、事实身份/span/hash资格、Deep-4B发布门或A线学习状态。

## 真实运行与恢复

证据目录：`D:/study-agent-validation/reading-notebook-ui-evidence/`。
权威摘要：`r6c-closeout-observations.json`，原始请求/输出/validator路径、SQLite与浏览器观测分别保存。

| 样本 | Deep child | 持久终态 | 发布资格 |
| --- | --- | --- | --- |
| S3（修复unknown前） | deep-49b32b4f45ad3e14197727b7 | partial / active_runtime_unavailable | false |
| S5 | deep-52d430786a3bbfdbfabfe52b | partial / evidence_saturated | false |
| S3重放 | deep-922963bc3fbd50e7b864aad7 | partial / evidence_saturated | false |

后两条自然经过Lookup→Standard→Deep，研究执行并进入合法持久终态，审计fail / audited-but-not-approved；这不等于研究问题全部回答，也不具备发布权。
三次真实浏览器运行期间断网/重连并刷新，恢复同一child，版本不回退；SQL验证每个Standard仅一个child。
只读校验terminal/publication审计、父子lineage与source_run_digest，数据库前后hash一致。
未测试进程崩溃重启恢复，不将运行间服务重启计为恢复证据。

## TTUV

首次S1容器可见时间撤回：容器出现不能证明合格文字可见，保留NOT_OBSERVED。
严格预登记补测 `r6c-browser/S1-TTUV-registry.json` / `S1-TTUV-browser-output.txt`：
首个实际可见合格FTS5字段为5.166秒。验证文本Range在视口/滚动裁剪范围内且未被覆盖，
官方字段获准发布，assistant正文hash匹配，持久更新时间先于首次可见时间；截图人工核对。
这是一次观测，不是SLO或p95。S3/S5的未批准Deep内容不能计入TTUV。

## 验证与未完成门

- 联合影响/集成783 PASS（unknown角色修复前候选；未受影响部分沿用）。
- unknown角色影响147 PASS；最终research-presentation-v1命名L2 291 PASS。
- Ruff、mypy基线NEW0、diff-check PASS；生产候选提交后工作树干净。
- 自有浏览器/后端/Vite已关闭；main/A线原dirty未动。无远端CI证据，无L3。

原五样本完整回归和新预登记资格集未完成，不能宣布R6c CLOSED。
上述为10-08前置收口时的交接。10-09用户将UI交给另一窗口，本窗口继续RP-1。

## 2026-10-09 原样回归与新资格集：观测批次完成，R6c仍NO-GO

固定生产字节，head `88c83714`（仅增加前置交接文档，生产候选仍 `3d52f5a6`）。
证据：`D:/study-agent-validation/reading-notebook-ui-evidence/r6c-qualification-20261009/`。
`registry.json`锁定原五样本和新集3条上限；`new-set-amendment.json`在任何新样本执行前
修正观测驱动使用的API字段（user_input而非message），原请求/生产路由/预算不变。
完整`result.json`、原始Standard模型响应与validator路径、实际SQLite及`audit.json`可恢复。

| 样本 | 实际查询/结果 | Deep/审计 |
| --- | --- | --- |
| S1 | 原SQLite 3.45.3；VERIFIED | 无需升级 |
| S2 | 原模型比较；SAFE_ABSTAIN / requested_claim_plan_unavailable | 未触发 |
| S3 | 原Opus 5.5；ESCALATE_STANDARD，Standard budget_exhausted | deep-851dc65cd1c860c18d4055c4；partial / evidence_saturated；mechanically_rejected |
| S4 | 原Transformer/RAG比较；SAFE_ABSTAIN / requested_claim_plan_unavailable | 未触发 |
| S5 | 原FastAPI 0.136.0；ESCALATE_STANDARD，Standard budget_exhausted | deep-eb237b65be0dcc5bc5a72226；partial / evidence_saturated；assembled |
| N1 | Python 3.12.0发布日期与版本；VERIFIED | 无需升级 |
| N2 | SQLite 3.46.0发布日期与变化；VERIFIED | 无需升级 |
| N3 | FastAPI 0.115.0发布日期与版本；ESCALATE_STANDARD | deep-b15609d63fa100a459f91556；partial / evidence_saturated；assembled |

五个原样本各只发起一次研究；观测控制器重启沿用已完成记录，不重发请求。
新集执行时没有UI示例上下文；只读断言逐条验证真实user_message等于预登记查询。
本批没有扩样本追求通过，没有新生产修改或提供商mock。

三条Deep的原Lookup handoff、Deep terminal、审计记录、child摘要hash、Standard父ID、
唯一child及最终投影revision/status均通过原验证器/只读对照；数据库字节不变。
全部Deep审计为fail / audited-but-not-approved / publication_authority=false。
这证明自然完整lineage与终态可追溯，不能据此宣布研究问题已完成或获得发布权。

### 当前首次阻断与可复现边界

- S2/S4：终态入口要求合法requested-fields集合，通用研究问题未产生支持域字段计划，
  原守门器`requested_claim_plan_unavailable`拒绝升级。不能靠查询数或预算绕过；需要独立的
  通用研究问题规划/升级覆盖合同，不是继续修question_identity。
- S3：只读`reproduce-synthesis.py`重放实际child，原`assemble_synthesis_draft`确定性抛出
  `assertion_without_evidence_ref:a:claim_b515a8ffb15688c23a2e7e4a`。
  `extractive_writer`给每个claim建立assertion，即使投影授权refs为空；原validator正确拒绝。
  这是候选表达与证据合同不一致，不得删除assertion必须有ref的规则或补造引用。
- S5/N3：原assembler可以组装，审计仍指出`evidence_grounding_incomplete`、
  `semantic_support_unverified`、`unanswered_aspect`。每条关键claim仍unresolved，
  `independent_support_required`缺口open；研究已饱和而非证明全部问题已回答。
- S3/S5/N3实际研究模型调用分别11/8/10；不能把phase_budget的6次常量直接解释成
  当前活跃执行路径总上限。保留按purpose记录。read_count仅引用原metrics，
  不把成功读取、失败尝试和seed复用混为物理调用消耗。

### 恢复、TTUV与验证

本批S5确实捕获running快照，但“已持久model_calls”观测判据在running期间未命中，
进程重启未执行，仍NOT_OBSERVED；不解释成没有running窗口或产品恢复失败。
前置批S3/S5真实断网重连保持同child的证据保留，不能冒充进程崩溃验收。
API观测没有捕获真实可见合格正文，八条TTUV均NOT_OBSERVED。
前置严格S1可见字段5.166秒仍为单次有效观测，不能外推给本批或未经批准的Deep。

生产sha256前后一致；沿用最终角色影响147、命名L2 291、Ruff/mypy NEW0证据。
本轮仅观测与文档，不重复L3/提供商验收，未push/PR/CI；owned后端已关闭。
main/A线及另一窗口UI改动未动。

唯一下一RP-1 slice：针对S3实际无ref投影，冻结一个候选表达合同与确定性负控，
区分“未解决问题/限制”与“可引用事实assertion”；保持事实ref、semantic judge及发布门。
S5/N3证据质量与通用路由覆盖分别保留为独立资格问题；不在同刀混入扩容或UI。
