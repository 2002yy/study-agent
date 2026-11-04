# M4-C3 真实生成评测计划（待授权，未执行）

## 基线与执行资格

2026-11-04已核验main `5d4d8381`，精确main CI
[41808661402](https://github.com/2002yy/study-agent/actions/runs/41808661402)成功，六层集成已结束。
当前已实现完整执行器与离线浏览器评分；本批准备不包含真实付费调用。
执行时保留当前SHA与实际出站请求。B线M4-D原型已获授权并行，不再等待本评测结束。

## 一条命令执行完整演练

在仓库根目录运行（输出目录与临时账本必须全新）：

```powershell
py -3.12 -m tools.m4c3_run --out D:/study-agent-validation/m4c3-demo-new --ledger D:/study-agent-validation/m4c3-demo-new/spend.db --pricing config/m4c3_pricing_20261104.json --browser
```

默认fake HTTP，仅供应商响应为构造数据，其余是真实ChatService、llm_client、SDK、计价/预留、
回答存储、HTML提取与产品沙箱。一次运行12个独立会话，保存request-body.json/request.json、
reservation.json、provider-response.txt/json、answer.txt、原始HTML与result.json；
批次report.json/index.json与sandbox-1280/sandbox-390截图/观测/错误，scores.json汇总正确性。
fake_http不生成真实模型质量结论；即使构造HTML通过，也不能当成生成成功率。

授权后在同一命令添加 `--allow-paid --authorization <授权JSON>`，并将ledger明确设为
`D:/study-agent-validation/live-20261102/spend.db`。授权结构见
`config/m4c3_authorization.example.json`（当前authorized=false，不是许可）。付费模式拒绝其他账本、
拒绝非当天官方价格快照、重复调用、额外请求与超限。不要用演练账本替代共享历史。

完整请求计价发生在原有费用门，批次检查与预留在同一SQLite事务；HTTP发送必须持有该次新预留，
每题固定invocation_key、SDK重试0，异常/未知发送占用保守预留，不能以新输出目录重发已付费题。
截图/评分可独立恢复，不调用模型：
`py -3.12 -m tools.m4c3_results --run-dir <已有运行目录>`；已有双视口报告则只核对哈希并汇总。
报告部分缺失时保留原始回答和browser.log，先修复重放，不重跑付费生成。

冻结产品配置：普通聊天、flash、fast、nahida角色、context_mode=none、无RAG/历史/个人记忆，
settlement assembly关闭（使用现有标准聊天费用门）。未声称覆盖可选assembly-on路径。
实际12题均max_tokens=6000，temperature请求值0.7，thinking=disabled；按实际wire保存，不拿配置猜请求。
模型别名公开版本为DeepSeek-V4.1-Flash-1017；供应商仍可能更新别名，响应model与公开版本分列。

## 冻结批次

- 顺序：J01/J02/A01/A02/D01/D02/C01/M01/M02/P01/S01/N01，各一次首次生成。
- 题目与正确性标准完全沿用 `M4C_ACCEPTANCE.md` §1–2，不用结果反向调整题目、容差或观察器。
- 每题新建独立会话，无历史、附件、搜索或外部工具；统一前缀“请制作可交互的界面演示以下任务”，
  后接 §1 对应任务、输入和事实约束。12 条完整 prompt、哈希与离线预算已保存到 `M4C3_PROMPTS_V1.json`；
  不把参考实现、故障样本、观察器定位属性或标准答案 HTML 发给模型。
- 走现有 Study Agent 真实生成/清洗/保存/沙箱链路，不能以裸模型生成替代产品路径。
- 提议 provider/model：DeepSeek / `deepseek-flash`，12 题保持同一模型标识，每题使用独立请求 ID；这是模型标识，
  不是已证明不可变的供应商快照。执行前核验配置并记录响应 model/version；若只能使用滚动别名，
  明确版本不可严格冻结，限制同一批短时间执行，不宣称结果跨版本可复现。
- 源码核验后的随机性方案：沿用产品路径默认 temperature=0.7，top_p/seed 不发送，记录为供应商默认。
  `chat_service.py` 的生成入口未传 temperature，`llm_client.py` 的 stream/async 默认值为0.7；
  不声称环境中的任务级 temperature=0 已生效，也不声称 top_p 已固定为1。
  实际出站请求仍须离线截获核对；若产品路径发生变化，先修订清单，不暗中换成独立 SDK 路径。
- 预算档采用当前已提交的 UI 分配规则，逐题预先保存档位和实际 max_tokens，输出硬上限 9000；
  不为过关临时提高档位。输入超出预留或每次最坏费用超限，在发出请求前拒绝。
- SDK/HTTP/应用层自动重试均为 0；无自动续写、自动修复。超时、截断、拒绝、空回答均保留，
  不补抽样。中断恢复只处理从未发出的题；是否已发送不明的请求占用次数与预留，不能重发。

## 费用提案（不是授权）

提议最多 **12 次实际模型请求，每次保守预留 ≤¥1.00，本批总预留 ≤¥12.00**。
沿用共享账本 `D:/study-agent-validation/live-20261102/spend.db` 与
experiment `study-agent-live-20261102`，全实验上限仍 ¥30，不能新建空账本重置余额。
本批只读快照确认23条预留、累计 ¥8.630826、余额 ¥21.369174；这是保守预留，非提供商账单。
快照不是执行时额度承诺，本次未新增预留；执行前仍须重新核验。
执行前必须只读核验余额、并发占用和现有费用门，再验证调用计数与本批子限额能在发送前生效；
无法强制三项限制则不得执行。实际可用额度取“¥12、本批批准额度、共享余额”最小值。
计费单价和版本支持在执行前核验并保存来源/时间，不能直接采用旧工具中的历史单价。
账本无法访问、价格无法界定、预留失败或累计将超限立即停止；失败请求不假定免费。
用户需单独明确批准模型、12 次上限、¥1 单次、¥12 本批及沿用 ¥30 共享上限后才能调用。

## 原始证据与判定

建议输出目录 `D:/study-agent-validation/m4c3-generation-20261104/`（执行时创建）。
manifest 保存基线/执行 SHA、题目/提示词哈希、模型/参数/预算档、依赖与浏览器版本、授权引用。
逐题保存实际脱敏请求、未经改写的原始回答、finish_reason、usage、请求/响应 model ID、耗时、
请求 ID、预留/结算状态、抽取 HTML 与 SHA256、清洗后沙箱源码、控制台错误、截图与操作记录。
密钥、认证头不进入证据；原始回答不手工修正。无文档也保存回答和失败原因。

在真实产品沙箱重新采集 declared/observed/expected，运行冻结任务判据和所有通用可用性检查；
桌面 1280×800、手机 390×844 分列。重用 taskObservers 与 judgeUsability；现有重放入口是否
完整覆盖真实沙箱、手机和全部题族需在执行前离线验证，未覆盖不能借直接渲染结果充数。
找不到按钮、节点或刻度则保存定位失败，返回 indeterminate，不修改页面来迎合观察器。

### 离线准备入口与已知缺口

运行 `py -3.12 tools/m4c3_prepare.py --out <新文件路径> [--ledger <共享账本路径>]`：
只生成固定输入/哈希/预算档，账本通过 mode=ro/query_only 和同一读事务观察；缺失不创建，
共享cap不是¥30即拒绝，输出已存在即拒绝覆盖。始终 paid_authorized=false，没有模型发送代码。
12题当前离线分类均为 interactive / 6000 tokens；这只验证分配函数，不能替代完整产品请求快照。

原始文档入口已补齐：`py -3.12 -m tools.m4c3_export --db <runtime.db> --out <新目录>`，
可重复传入 --db，按原始HTML哈希去重；不注入桥接桩、不包裹HTML、不覆盖旧目录。
`--task-map <JSON>` 显式指定 component-id 到冻结题编号的映射；默认不猜题，映射必须人工核对题目实例。
设置 `M4C3_RAW_DIR=<导出目录>` 后运行离线配置中的 `rawReplay.spec.ts`，逐份核验文件哈希、
经真实产品清洗/CSP/沙箱在1280×800与390×844执行，保存原始观测、错误、判据、截图与步骤。
J01使用不依赖测试属性的语义适配器；未支持的冻结题检查保持indeterminate；非冻结题实例unjudged，
但仍记录运行错误及所有通用可用性判据。参考页/负控与saved_model历史文档分别测试，不混合计分。
输出有 historical_replay_only=true，历史修订不计入12题首次生成成绩。

已有调查中的两个数据库导出9份真实原文，双视口18次重放全部无运行错误；两视口均复现
J01 r3箭头错误/独立一致性缺证据，J01其余三版任务检查全部确定通过；9/9字体均为13px，
通用字号判据全部fail。5份非冻结题实例保持unjudged，不映射成P01/D02。
证据目录：`D:/study-agent-validation/m4c3-raw-batch2-20261104/`。

`tools/m4c3_budget.py` 已在现有共享账本的同一预留事务内实现固定批次12次、单次¥1、本批¥12、
全实验¥30限额；每题首次请求使用固定key，重启后仍拒绝重复，其他实验工作占用共享余额。
执行器 `tools/m4c3_run.py` 现已将“真实请求→保守计价→同事务预留→单次SDK发送”接通，
完整12题假HTTP演练已验证；原有费用门保留，不能把调用者传入金额当费用，也没有新增付费授权。

手机测量已新增独立沙箱视口探针：内层 window.innerWidth 必须等于1280/390；
900px固定宽页面在390px视口必须报告溢出，响应式页通过。该证据不等于12题真实输出手机验收。
离线影响集入口为 `npx playwright test --config=playwright.m4c-offline.config.ts`，
只收集 acceptance 目录；完整浏览器门禁仍使用原配置及其Golden Journey收尾校验。

### CI修复记录

bd3bf1c2的CI 41786784266中classify/frontend/browser通过，backend因清单中的12个
prompt_sha256值触发熵扫描而失败；pytest与mypy基线通过。字段统一为已有安全扫描规则识别的
input_sha256，哈希值与提示词字节保持不变，未扩大扫描排除规则；变更文件扫描结果0项。

输出：首次完整成功率（两视口全部必要检查 pass 的题数/12）、确定失败题数、无法判定题数、
必要检查自动判定覆盖率、分题/领域/视口结果、耗时/token/费用。失败与无法判定可同时出现，
同时给出互斥分类：有 fail → failed；无 fail 但有 indeterminate → indeterminate；全部 pass → passed。
无产物/请求失败保留在 12 题分母；因预算未发出的题标 not_run，并将批次标 incomplete。
人工检查与自动结果分列，人工意见不回填自动 pass。错误检测有效率引用离线故障矩阵，
不能用生成样本替代已知故障。一次追问修复率本批为 not_run，另行授权。

## 数据后的选择

按 PROJECT_STATUS §0B，先报告原始结果、失败归因（model / orchestration-contract / UI，
若涉及 retrieval 则说明为何偏离无搜索计划），再提出条件建议。无预设成功率门槛，不在结果后补造。
A：确定生成错误集中 → 先做 M4-C4 针对性修复，并将复现缺陷转为静态回归。
C：人工可核验正确但观察器 indeterminate → 先扩观察器；保留原输出后离线重判，不能改写模型成绩。
B：首次生成不能证明修改稳定性；M4-D基础原型按用户新决定并行开发，模型接入与默认策略仍需
同批真实修改任务的局部修改/完整重建比较。比较的付费调用单独授权。
不实施M4-E/F/G或ChatGPT对照；无对照不声称优于ChatGPT。
