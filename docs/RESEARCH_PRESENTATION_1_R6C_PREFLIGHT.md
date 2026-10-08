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
按最新用户指令，下一独立切片为Conversation-first UI：重排对话与研究资料，
保持既有快照/恢复和发布权威，不混入上述引擎修复。随后恢复R6c剩余资格门。
