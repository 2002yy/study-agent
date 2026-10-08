# RP-1 Deep seed 按候选复用完整批次

2026-10-09，branch `codex/reading-notebook-ui`，base `65f587697333028ffa7a28cb43430b5ea02b3fc6`。
seed 复用切片 LOCAL CLOSED；RP-1 / R6c 仍 NO-GO，最终回归结果见本报告验收段与 closeout-state。

## 合同与生产修复

首次阻断已由前批真实记录确定：官方首页和 release-notes 共用一个来源 cluster，
首页处理后 `covered_cluster` 排除了尚未 materialize 的 release-notes seed。
独立来源保护是正确的，但不能等同于“该来源所有已保存正文都已处理”。

生产仅 `src/application/active_research_runtime.py` 调用与私有 `_fair_read_plan`：
从已通过原 Deep preflight / seed hash 校验的来源映射传入候选 ID；
沿当前 claim 原排名和原 is_schedulable_candidate 筛选 seed，使用原波次槽位。
seed 可进入原本的本地 materialization 分支，不受已覆盖 cluster 或物理读取额度阻断。
排队计数和最终截断只计算真实新读取，seed 不占新物理槽位。
新物理读取仍按 covered_cluster / 独立来源 / 冲突预留 / hard cap 筛选。

不增加独立 cluster 或 evidence ref；原 assessor 仍从实际 evidence/link 判断支持。
同 candidate/claim 的 wave 内 target 去重，下一波已 materialize 正文由原 content_available
排除，原 extraction prior / cursor / cancellation / terminal 保护保留。
字符额度、研究绝对截止、每逻辑模型操作尝试数均未改；本地处理仍在原边界校验。
helper 能计划复用不意味着可绕过全局终态/截止：原 runtime stop rules 仍有最终执行权。
非 Deep/无 seed 调用的默认参数为空，原物理读取行为保留。

## 集中正负控与回归

新 `tests/test_deep_seed_reuse.py` 7 项：旧无seed计划排除同cluster正文的对照；
新seed复用但fresh同cluster拒绝；最后一个物理槽位不被seed消费；
reads耗尽仍可计划本地复用；candidate/claim不重复；rejected与无增益lead不绕资格；
无当前claim排名不路由。不会因为“是seed”自动取得来源支持。
既有 deep_runtime_seams / seed / execution / active runtime 负控继续覆盖错hash、
char上限、已处理候选、claim绑定、取消、crash/resume与终态不执行。

首轮影响集259 PASS / 1失败：新测试误用不存在的 eligibility=ineligible，
真实合同为 rejected；纠正fixture枚举后新7项全部PASS，生产未为该错误改变。
最终命名L2包含完整影响栈，再统一确认修正后的候选。
格式工具曾改写大文件无关排版，已恢复无关区段并比较 AST 相同；
最终生产diff仅调用/private helper，格式检查针对新测试，Ruff全仓PASS。
mypy按CI参数 current122 / baseline128 / NEW0 / resolved6，diff-check PASS。
不改共享模型、持久schema、资格或权威，不触发L3；旧21项真实重启证据不重复施工。

## 原样真实 S5 / N3

证据 `D:/study-agent-validation/reading-notebook-ui-evidence/r6c-seed-reuse/`：
执行前 registry（base/生产patch hash/原payload）、原 Standard wire/validator、
runtime.db、SSE与GET记录、原seed正文、materialization/extraction、audit.json。
只用原S5和既有N3，不注入升级或事实；两例共34项原validator/hash/预算/资格检查PASS，
SQLite审计前后字节一致，本窗口服务关闭。

| 结果 | S5：0.136.0 | N3：0.115.0 |
| --- | --- | --- |
| Deep child | `deep-3e1d4ba6f86c7e33795657fc` | `deep-9d2e50db067c75b0da1d17ce` |
| version | 92 | 161 |
| release-notes复用 | deep_seed / read / 原hash保留 | 同左 |
| 该正文物理读取 | 0次 | 0次 |
| 原抽取结果 | supports0.9，精确版本/日期span和caveat保留 | lead0.1，明确目标旧版本缺失，不提升相邻版本 |
| 支持独立cluster（原assessor） | 2，satisfied | 1，partially_satisfied |
| Deep终态 | completed / evidence_gate_pass | partial / evidence_saturated |
| 字段语义覆盖 | not_evaluated，required_units未声明 | 同左 |
| 最终审计 / 发布权 | fail / false | fail / false |
| 本例合格TTUV | NOT_OBSERVED | NOT_OBSERVED |

S5 的官方同域首页与 release-notes 仍是同一个 cluster；另一个支持来自 PyPI cluster。
不是把多个同域页面改成多个独立来源。S5在真实路径自然取得研究结构门完成证据，
不是人工调整 score / threshold；原引用span/hash/provenance与模型caveat均保留。
N3正文不含目标旧版本，继续缺证据，不借用其中的新版本日期。
完整thread/turn/parent lineage、字符/时间预算、引用和原审计hash在audit.json。

两例最终审计 issue_codes 均为 semantic_support_unverified /
evidence_grounding_incomplete / unanswered_aspect，audited-but-not-approved。
完成研究结构门不能直接宣称答案语义合格或正式发布；Deep-4B仍无qualified judge。
另保留观测债务：selection_trace累积旧window exclusion可仍显示materialized=false，
实际持久selected_sources/materialization/extraction才是本次复用权威；本批不混入trace重构。

## 下一完整批次与验收记录

唯一下一批：**FastAPI 精确版本定向读取与日期绑定合同**。
先取得可信读取边界的原始HTML/transport hash → exact-version section → 字段span/hash trace，
区分S5已有正文但无合格字段绑定与N3截取缺旧版本。
只在原source adapter内修可证明的读取/提取缺陷；不通过普通文本相似版本自动合格。
集中负控：错项目/相邻版本、更新时间或上传时间冒充发布日期、多个冲突日期、
无版本section/错hash/缺span；原预算内定向取段、引用可追溯后原样S5/N3真实重放。
字段级claim单元与qualified semantic judge独立保留，不混入源读取合同或授予发布权。

最终命名L2：675 PASS / 362.26秒，完整覆盖影响栈与修正后的7负控；
影响集原259 PASS＋纠正fixture后新7 PASS，最终L2统一确认。Ruff/mypy NEW0/diff-check通过。
本批集中一次提交，未push/PR/CI；最终head/clean/scope由Git及证据closeout-state恢复。
原main/A线及另一窗口UI未改，研究预算/发布门/学习写入继续冻结。
