# RP-1 S3 合成候选引用合同：本地闭环

2026-10-09，branch `codex/reading-notebook-ui`，base `5796a316`。
本切片 LOCAL CLOSED；S3研究质量与RP-1总体仍NO-GO。只有本地证据，未推送/PR/CI。

## 首次丢失点与裁定

原真实S3 `deep-851dc65cd1c860c18d4055c4` 的数据层有4个EvidencePayload。
两条supports link的strength都是0.6，低于原强证据阈值0.7；另外两条是lead。
原`assess_claim_evidence`正确排除这些支持资格，投影的`evidence_refs`为空，
claim仍unresolved / not_evaluated。因此不是EvidencePayload→候选时丢失合格引用。
不能把这些link、URL或正文片段重新授予支持权，也没有修改0.7阈值。

表达缺陷发生在默认`extractive_writer`：无授权ref仍建立事实assertion，
原validator因此正确抛出`assertion_without_evidence_ref`。

## 最小修复与冻结边界

- 无授权ref：保留原claim section身份，表达为明确的待核验问题；不产生事实assertion或citation。
- 有授权ref：完整保留claim的ref、原payload内容、locator与provenance；不借用别的claim引用。
- 已声明ref却缺payload：明确fail-closed，而非静默过滤后忽略引用丢失。
- 原事实引用、claim绑定、stance、限制说明、最终语义审计与Deep-4B发布门不变。

机械coverage_report仅统计实际emit的事实assertions，不代表全问题完成。
无引用的关键问题仍由原最终auditor拒绝为`critical_question_unanswered`。
没有新增schema、持久字段、模型调用、预算、来源授权或UI改动。

## 验收证据

8项新合同正负控覆盖：可追溯引用/provenance、真实S3无ref形态、禁止借用孤立payload、
缺payload完整性拒绝、无引用事实拒绝、跨claim错误引用拒绝、存在引用但语义未获核验时
仍拒绝、已支持和未支持主张分别表达且不取得整体审批。
支持正例是明确标记的合同fixture，不声称真实S3已有合格证据。

只读重放原SQLite，字节hash不变、0提供商调用：

- S3：原机械合成拒绝→明确待核验候选，0事实assertion、0citation；最终审计仍fail。
- S5/N3：已有授权ref与provenance保持，仍为语义/证据/问题覆盖不合格；没有虚假提升资格。

随后预登记原S3一次真实API重跑，原请求不改、不注入handoff、不重放为假运行：

```text
Standard parent standard-94ca418783c9e633b53c5505
Deep child     deep-3bc03d19fd9cc345dd9ac32c
revision       101
terminal       partial / evidence_saturated
candidate      assembled
audit issue    critical_question_unanswered
authority      audited-but-not-approved / publication_authority=false
```

原终态/审计验证器、source hash、父子lineage和唯一child均PASS。
真实S3仍没有合格支持，不能宣布引用“补齐”、研究PASS或RP-1 CLOSED。
本次API运行没有新的UI TTUV或进程崩溃恢复证据，保留既有未观测状态。

验证：影响集131 PASS；最终命名research-presentation-v1 L2 373 PASS（137.51秒），
包含新合同、assembler、auditor、projection与claim assessor及原三层边界回归。
Ruff全仓PASS；mypy按CI的`--explicit-package-bases src`运行，122/128，NEW0；
格式化和diff-check PASS。未触发共享模型/持久schema/权威切换或广泛重构，
按分层策略未跑L3；本批不宣告RP-1大阶段关闭。

证据目录：`D:/study-agent-validation/reading-notebook-ui-evidence/r6c-s3-citation-contract/`，
包括focused/l2/mypy日志、只读binding trace、原始live SSE/模型/validator/SQLite、
live-observations与closeout-state。owned后端已关闭，main/A线/另一窗口UI保持独立。

## 下一切片

集中处理S5及新FastAPI的证据覆盖归因：从实际来源发现、正文读取、绑定强度/
资格、声明required_units与问题覆盖逐项定位，保持partial与发布权限。
不在此提交里修证据阈值、扩大资源或增加领域样本。进程重启恢复之后单独验收。
