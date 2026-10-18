# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-10-18（完整聊天产品主线；运行中/下一轮附件链路）
> 产品定义：**Study Agent 是体验接近 GPT-6 Chat 的智能聊天与研究 Agent。自然聊天、自主研究、持续交互、智能 UI、统一多模态、工具执行是六项通用核心能力；长期学习与教学是其上的专业场景。**

本文件只维护当前权威状态、可复核边界和唯一下一门。2026-10-06 本次收敛前的完整状态原样归档到 [`archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)；更早历史继续由既有 archive 与 Git 历史持有。

## 0. Current Handoff（cold-start 入口）

**2026-10-18 最新切片：研究未结束先显示已读资料摘录（本地，未合并）。** 分支 `codex/research-early-findings-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base `facb8f37062029df95276a52f29d2abf5e28281a`；提交由本段所在Git提交恢复。只读投影当前Deep笔记与成功读取正文：候选摘要、失败/不可用正文、私网/非法URL、无正文依据的笔记与已失效笔记均不展示。最多3条/每条280字、稳定身份、原文出处；SSE `findings` 快照在转向时清除失效项，低版本拒绝/跨run隔离，旧事件省略字段兼容。聊天中直接可读，标注仍在核对；不进入答案token/复制文本/证据权威，不新增模型或工具请求。Deep已读数量改用既有read_summary，Active计数优先不变。**这是阶段性来源摘录，不是完成了模型阶段性综合答案。**

本片L1 `research_early_findings` **164 PASS / 1 SKIP / 152.83s**，前端影响集 **59 PASS**，桌面/移动浏览器 **2 PASS / 6.1s**（最终答案前可见出处和正文、原研究可继续插话），build/Ruff/diff-check PASS，mypy122/128 NEW0。真实SQLite checkpoint观察到运行中已有摘录；附件文本未混入网页摘录；无L3、无新CI/推送/PR/合并/部署。日志 `D:/study-agent-validation/early-findings-{backend,frontend,browser,build,mypy}.log`。本机/项目配置只读检查未发现 Guardian旧字段，未改用户配置。

**最新用户反馈与唯一下一片（覆盖下方旧NEXT）：UI需要克制、疏朗；纳西妲头像不能是灰占位。** 检查真实头像/fixture差异，收敛消息头、研究状态和输入区的边框、体积与重复说明，保持已有选附件、追加/排队、停止、过程展开行为；用桌面/移动截图复核。这是六项通用能力中的智能UI与连续交互改进，非学习系统扩张。

**2026-10-18 当前执行片：下一轮问题的附件保存/恢复/发送（本地，未合并）。** 分支 `codex/chat-queue-attachments-20261018`，工作树 `D:/study-agent-validation/chat-steer-attachments`，base 为上一片 **`1ecf7b47ce6352c6ebb11dda4d4fff3270126378`**；提交由本段所在 Git 提交恢复，审阅仅 `1ecf7b47..HEAD`。原 `codex/chat-steer-attachments-20261018` 分支停留在1ecf，保留独立切片。队列现在保存服务端附件身份（ID/hash/filename），不把附件放入当前研究；恢复后手动发送仅带该条选择，并重走本会话/ready检查。无效或绑定期间消失的附件拒绝整个入队；同请求ID改选附件拒绝；文本相同但附件ID/hash不同的已完成turn不能隐藏或完成队列。UI显示附件数量；失败保留选择、成功清除本次选择，网络重试保持身份。兼容旧无附件队列，无数据库迁移/新执行权威，未扩展当前研究的工具权限。验证与最新下一片见下方。

**当前片证据：** 命名后端L1 `chat_queue_attachments` **72 PASS / 31.30s**（含真实SQLite重载/旧checkpoint合并、旧纯文字队列、同ID改附件拒绝、跨会话/未就绪/删除/绑定时消失负控、错误文件/同ID不同内容hash不能冒充已交付）；前端影响集 **75 PASS**（API载荷、失败重试身份、更改选择新身份、队列恢复与后续turn附件）；桌面+移动focused浏览器 **2 PASS / 7.3s**（入队503保留选择、重试同身份、只在后续turn发送该附件）；TypeScript/Vite build、全范围Ruff、diff-check PASS，mypy **122/128 NEW=0**。仅队列接线的有界L1，无L3；JSON已有队列条目增加可选refs，旧条目按空附件处理，未变schema/cursor/研究权威。运行日志 `D:/study-agent-validation/chat-queue-{impact,backend,browser,build,mypy}.log`；源码与交接在本提交后保持干净。无新远端CI、未推送/PR/合并/部署，不授予真实模型/研究质量GO。

**上一片：完整聊天能力盘点 + 运行中附件补充修复（已本地提交，未合并）。** 分支 `codex/chat-steer-attachments-20261018`，base 为原产品线末端 `4ffa44521cb5ef2c1a50e73c6d03b0ce42710beb`，提交 `1ecf7b47ce6352c6ebb11dda4d4fff3270126378`。main 仍为 `335fc9b7875b848f202122362f2e0f8b5a9db0ee`，本片不是 main 已交付能力。独立 Async 候选 `2c58eb0eecc37ba004a7deb601e991091248bf1a`、原审计 `4a549f7d` 与测试修复线保持不变；本片不重新混入 Async 接线。用户要求以 GPT-6 式聊天、搜索分析、UI 为最终目的，按有界功能和影响集推进；本轮未运行 L3。

| 用户要求 | 当前实现情况（原产品线，不等于 main/真实验收） | 尚未闭环 |
| --- | --- | --- |
| 自然智能聊天 | 已有多轮上下文、角色/模式、历史会话、重试/继续与答案流 | 未完成类 GPT-6 的综合体验验收；研究中插话目前按补充处理，仍需明确改变话题与继续研究的产品语义 |
| 智能聊天 UI | Rev 3 同一对话承载答案、过程、补充回执、计算/图表卡片；有桌面/移动离线证据 | 模型通用选择地图/按钮/滑块/棋盘等富交互内容尚未闭环；移动附件 chip 显示空间偏窄，记为相邻 UI 债务 |
| 搜索分析、边研究边讲 | 已有搜索/阅读/补查过程事件、来源与答案链路，Deep 过程入聊天 | 真实读取、来源复用、比较覆盖、答案引用质量仍需资格验收；A/B/C 整体未放行 |
| 边研究边回答、连续交互 | 已有计划开场、过程播报/去重恢复，Deep安全边界、持久补充与回执；两片补齐运行中/下一轮的附件链路 | 过程播报不等于已有有用的阶段性答案；实质增量答案尚需补齐/验证，Lookup/Standard无同等转向能力，真实模型延迟及方向准确性待验收 |
| 文件/多模态 | 已有消息级绑定、研究消费、补充附件后端与隔离校验；G1/G2 实现已完成，旧待办过期 | 真实视觉模型和研究联动复验、长期资料转正端到端验收 |
| 工具、计算、图表 | 已有有界计算协议、结构化结果/图表、隔离 Python，历史容器负控证据保留 | 真实模型自主工具选择和完整任务质量未验收 |

**本片修复与证据：** 原运行中补充丢弃 `attachmentIds`，失败返回也会清空输入区附件选择；现在文字/附件共用同一 steer 请求，失败保留选择，成功仅清除本次提交的附件。同内容/同附件集合重试复用 request ID；换附件则换 ID。3 项新增检查在旧代码上失败；修复后前端 L1 影响集 **72 PASS**，后端绑定/多模态联动/生产 policy 影响集 **36 PASS / 18.74s**，桌面+移动 focused 浏览器 **2 PASS / 5.7s**（含一次503失败、保留选择、同身份重试、空附件后续补充、不中断原 SSE），TypeScript/Vite build PASS，Ruff/diff-check PASS。浏览器首次使用全旅程配置及开发者诊断文本定位失败；已改用既有 `playwright.conversation.config.ts` 与用户可见错误提示，不更改全旅程门槛。日志 `D:/study-agent-validation/chat-steer-{negative,impact,backend,build,browser-focused}.log`；当前仅前端及交接变更，未改后端/迁移/预算/Gate。无新远端 CI、未推送/PR/合并/部署；真实供应商验收未重跑，原资格门保持关闭。

**唯一下一slice：让研究中更早出现有用内容。** 对照已有过程播报与答案生产点，补齐有来源依据的阶段性发现展示并逐步补全，区分“正在搜索”与“已取得什么发现”；复用既有证据资格与来源身份，不将未验证的临时内容升级成正式答案/完成状态。继续独立小片和影响集；最终候选仍遵守 AGENTS.md 的发布/审阅门。

**产品优先级（用户2026-10-18明确）：** P0可靠聊天/长期研究（Async-R1c）；P1自主搜索分析引用（M4-C5/RP-1/Arm C）；P2边查边讲/插话/增量答案；P3模型选用Python/计算/绘图；P4富交互UI；P5统一多模态/跨会话；P6学习和专业场景。P2–P5可以在安全底座稳定后独立推进，不以全部研究质量达标为界面开发前提。每项工程必须指出改善哪项可感知能力；优先快速出现有用内容、持续更新、不中断插话、保留已有成果、统一入口。租约/CI/证据系统是实现手段，不是产品定位。

**2026-10-11 研究开场 + 过程播报（Research Approach）Slice A 后端合同（独立分支，未合并）：** 新分支 `codex/research-approach`，worktree `D:/study-agent-validation/research-approach`，基线 main `7a8b6d55`。新增展示合同 `ResearchApproach`（`schema=research-approach-v1`），**无证据权威**：不写 Evidence Gate、不使目标变 `supported`、不作答案引用、不喂回核验器；**不改动严格计划合同** `standard-research-plan-v1`（四键 envelope 原样）。落盘于 `research_context["approach"]`（SQLite `web_lookup_runs.research_context`，刷新不丢），经既有 `research` SSE 事件的可选 `approach` 字段发出，旧客户端忽略即可。起源优先级 `model_plan` > `model_generated` > `direction_update` > `fallback`；`status∈{pending,ready,failed}`，创建期 `pending` 种子（暂无开场时显示既有确定性工具进度）。保证：**开场失败不阻断研究**（`generate_approach_or_fallback` 吞掉超时/空/非法负载降级 fallback）、**不突破预算**（单次有界调用并回报是否计费）、**不走答案 token 流**（走 `research` 进度通道）、确定性校验（模式长度上限、空/超长、空泛过渡语、未验证完成宣称、与上一条重复）。接线：`WebLookupService.create()` 落种子；`chat_routes._research_progress()` 绑定 run 身份发出 `approach`。证据：`tests/test_research_approach.py` 18 PASS；L1 影响集 91 PASS（web_lookup_run / research_contract / dispatch / run_owner / answer_streaming / standard_research / pedagogy）；ruff、mypy 122/128 NEW0。文档 [RESEARCH_APPROACH.md](RESEARCH_APPROACH.md)。**下一刀（Slice B）**：把 Standard 规划保存后投影为 `model_plan` 开场、接线有界模型生成（含预算计费）、前端 `ChatResearchProgress.approach` 类型 + 控制器按 `(run,turn,sequence)` 去重/恢复 + `AnswerProgress`/`ChatPanel` 呈现 + 复制仅答案/取消显示已停止/会话隔离，以及真实 DeepSeek 延迟校准。**边界冻结**：不拥有 L/S/D 研究质量与完成率门、M4-C5 Evidence Gate/核验器/来源资格、模型调用上限与研究预算与计费口径、自动升档、学习状态/记忆/正式答案与引用权威、既有对话角色切换；生产 B OFF、RP-1/M5 NO-GO 不变。

**2026-10-11 多窗口整合 / 当前执行权（覆盖下方旧 NEXT）：** 主目录干净，原混合改动、26份图片及旧工作树继续保留；64工作树最终复核：12 dirty（保留混合工作树 + 11本地MCP覆盖），11配置另做逐文件SHA256备份于 `D:/study-agent-validation/consolidation-20261011-final-audit/local-config-backups.json`，见 [工作区索引](WORKSPACE_INDEX.md)。#205/#208已合并；#207/#214在各自exact-head CI成功、当前范围审阅无未解决finding后expected-head合并，当前main为 `5155f107fae23fb19ce7d857745075b5b6a21bc2`。本地隔离组合head `be03002084fd9d6ce6a130dc9d79489bc391036c` 全量 **4294 passed / 6 skipped / 1433.69s**；main与该候选的src/tests/tools/frontend/依赖/config/CI/infra树完全一致，属于同树回归证据，不称新main独立跑过L3。frontend457、browser77、真实栈14、平台46、导航51、build/Ruff/diff-check/mypy NEW0均PASS。专用L3预检脚本在全量启动后补核PASS，未冒称启动前调用。远端 exact-main push CI `38117936966` 对 `5155f107fae23fb19ce7d857745075b5b6a21bc2` 已 SUCCESS；当前已合并主线可以称 REMOTE GO，新待合并 PR 仍分别等待新 head CI。

| 项目 | 完整候选 SHA / branch / worktree | 当前证据与结果 |
| --- | --- | --- |
| #207 | `3d457835abfa61ed596f26e6a6a12f803f451017` / `codex/ui-heading-focused-port-20261009` / `D:/study-agent-validation/ui-heading-review-fix-20261011` | pull_request CI `38115979560` SUCCESS；merge `5bc175389f54cf088ac794441b04c3c36d2f0bff` |
| #214 | `1e5b89260ffdd16d14be09cdc0fa95d0a301b6a0` / `feat/m4c2-navigation-diversity` / `D:/study-agent-validation/m4c1-eval` | pull_request CI `38115047192` SUCCESS；merge `5155f107fae23fb19ce7d857745075b5b6a21bc2`；展示层回归不授予研究质量GO |
| #215 | `codex/workspace-index-20261011` / `D:/study-agent-validation/workspace-index-20261011` | 旧head `962fce09cdfa53a6acc16459b258c5ce4a7f5e3b` 的CI `38116155805` SUCCESS；两条新增P1在本刀修复，新head由Git恢复，旧CI不授予新head |

| #203 | `b0590c4ce62b14cad6335738d7747ee7f85fa23a` / PR branch `codex/learning-state-1-closeout` / 修复 worktree `D:/study-agent-validation/learning-isolation-review-fix-20261011`（本地 branch `codex/learning-isolation-review-fix-20261011`） | 两条 P1 已补证并 resolve；真实研究/HTTP populated SQLite 快照与落库负控，影响集299 + 相邻12 PASS，合入5155后边界回归124 PASS；Ruff PASS、mypy122/128 NEW0；新提交CI尚待，不沿用旧绿灯 |
| #204 | `cf906e2c86135d329611f133050a40ced38f89ef` / PR branch `codex/rp1-ab-evidence-archive` / 修复 worktree `D:/study-agent-validation/rp1-archive-review-fix-20261011`（本地 branch `codex/rp1-archive-review-fix-20261011`） | 原失败CI实际133项告警均为固定Git/校验值，逐项精确登记；Linux原报告133、本地37均无剩余；18负控 + 41 CI enforcement PASS；实际scanner合成AWS格式负控保留告警，409原文件及Git blob校验不变，新head CI尚待 |

**唯一下一slice：现有改动合并收口。** #215修复后记录一次新exact-head CI和最终审阅；#203/#204修复已推送，门前读取PR当前完整head；表中SHA为本次快照，若head移动须重新绑定新SHA的CI与增量审阅，不可沿用旧绿灯；下一轮查询精确head CI与新增审阅；精确head绿灯且最终审阅无未解决finding后expected-head逐个合并。不得重复触发已运行的CI，不降低门槛。当前Learning State-1 L1 CLOSED、L2–L6仍NOT CLOSED；RP-1/Deep-4B及B-Search资格裁定不变。禁止从历史设计文档启动新UI开发；合并后新main必须另核对exact-main CI，不能继承当前5155的远端绿灯。

**2026-10-09 本地MCP固定配置单独交付：** 用户授权提交远端尚无的本地完成成果。branch `codex/playwright-mcp-pin-delivery`、base origin/main `f35b13b7`，只迁移既有已验证本地playwright server配置至当前main，固定 `@playwright/mcp@0.0.83 --browser chrome --isolated`，其他server逐项未变；JSON/版本/差异核验通过。复用2026-10-05原真实JSON-RPC MCP smoke记录 `D:/study-agent-validation/mcp-migration-20261005/RESULT.md`，不宣称本次新增smoke；用户级配置与现有备份不动，不复制旧frontend锁文件（远端已有1.62.1）。仅开发工具配置与交接，无研究预算/Gate/UI实现/另一窗口代码改动，无生产部署；推送refs与一次CI观察由local-delivery-closeout恢复。A/B归档与B线生产接线在独立分支，RP-1仍NO-GO。

**阶段状态（本段旧NEXT由上方2026-10-11整合门覆盖）：A线 Learning State-1 L1 CLOSED，L2–L6 NOT CLOSED。** Deep-4A implementation 已合并并 CLOSED；**Deep 阶段除 Deep-4B 外全部 CLOSED**。Deep-4B（automatic publication）= **NO-GO**（无 qualified semantic judge）。A 线：**Learning State-1 / L1 已 CLOSED**（authority `0de80751`），学习信息来源权威已封板；**L2–L6 仍未 CLOSED**，下一门 = **Learning State-1 L2–L6 验收收尾**（整理 T07–T18 的直接/间接证据，满足合同即关闭，不为制造增量而改实现）。B 线：**Intelligent UI × Lookup/Standard/Deep** —— UI 工作台 **#201 已合并**；**Research Presentation-1（RP-1）仍在 B 线施工**（原 `reading-notebook-ui` 分支，R6 未 CLOSED），只读 `learning_view` 接口**未启动**；A / B 两线各自独立 PR，不得混入同一 PR。

**2026-10-08 B 线：UI 工作台已接入（#201 MERGED）：** [UI 接入 PR #201](https://github.com/2002yy/study-agent/pull/201) 已合并，merge commit `5f4e81e22ab85c0a27c3ad82214c0f1dc62b79eb`。独立 worktree `D:/study-agent-validation/ui-main-integration`、branch `codex/ui-main-integration`；包含阅读并排/对话居中、纸白蓝灰及设备字体偏好、四角色最新版头像、内部角色设置、框内紧凑自增高输入框、右上资料开关、可记忆拖动宽度、只读正文/PDF 与引用定位，以及已完成的教学交互组件。**Learning State-1 与 Research Presentation-1 均不混入此 PR**；研究协议 / 真实三层 R6 继续由原 `reading-notebook-ui` 分支负责（**RP-1 未 CLOSED**）。

**2026-10-08 PR #201 合并前本地证据（后端范围证据，不声称新 SHA 独立跑过 L3）：** 生产精修 head `e1a24697f1fad1546614fd81123bc56db90cdca4`；`f60c27e576a8c2d2460d7747f1fee7f4d504b5d4` 后端全量 4142 PASS / 6 SKIP / 1500.96s；f60 到 e1 只改前端/浏览器测试/docs，后端树及后端测试完全相同。最终前端 453 / 浏览器 77 / 真实 React+FastAPI+SQLite 交互 14 / tsc+Vite build 均 PASS；mypy 无新增错误（122/128）。QA 证据索引：`D:/study-agent-validation/reading-notebook-ui-evidence/ui-integration-qa.json`。

**失败与恢复证据（#201 内）：** 首次 real-stack 11/14（旧“更多开始方式”定位与手机未开导航的整理入口过期）；第二次 13/14（测试把完整可见 token 误当 durable commit，改为等待真实 turn-end 状态后 14/14）；精修后浏览器首轮 75/77（底部字号旧 13px 断言过期），统一为 12px 后 77/77，提示条新增高度/折叠/键盘展开断言。日志及 1440/390 截图留在 `D:/study-agent-validation/reading-notebook-ui-evidence/ui-integration-*` 与 `ui-refined-final-*`。

**Current Action：**
```text
Deep-4A is merged and CLOSED (authority ea73b855).
Deep-4B automatic publication is NO-GO until a qualified semantic judge exists.
Learning State-1 L1 is CLOSED (authority 0de80751); L2-L6 remain NOT CLOSED.
Next gate = existing PR integration closeout (2026-10-11 handoff above).
B line = Intelligent UI x Lookup/Standard/Deep: UI workbench #201 MERGED (5f4e81e2); Research Presentation-1 still in progress; read-only learning_view not started.
```

**Deep 阶段合同（已冻结）：**

```text
Deep-1  docs/DEEP_1_CONTRACT.md           CLOSED
Deep-2  docs/DEEP_2_CONTRACT.md           CLOSED
Deep-3T docs/DEEP_3T_TRIGGER_CONTRACT.md CLOSED
Deep-3  docs/DEEP_3_CONTRACT.md           CLOSED
Deep-4A docs/DEEP_4A_CONTRACT.md          CLOSED (87 sections)
Deep-4B automatic publication             NO-GO until qualified semantic judge
```

**Learning State-1 / L1 CLOSED ✅（A 线第一刀）**

**2026-10-11 #203 L2–L6 本地补证 / 待远端收口：** [验收矩阵](LEARNING_STATE_1_ACCEPTANCE.md) 已补齐真实Lookup/Standard/Deep生产服务及普通UI HTTP动作的已填充SQLite durable全表快照；四个真实落库变异负控均检出，显式授权closure正控仍能写入。原两条P1已修复并resolve；299影响集+12相邻回归、Ruff和mypy122/128 NEW0通过。重新合入main `5155f107fae23fb19ce7d857745075b5b6a21bc2` 只解决交接文档冲突，不改变生产语义；等待新head CI与最终语义审阅后收口。L1权威仍`0de80751`，**L2–L6目前NOT CLOSED**；外部模型/recorded Deep terminal fixture不冒称自然研究或浏览器验收。**唯一下一slice为现有PR合并收口**，历史NEXT不授权新开发。

```text
authority   squash merge **0de807513e758bac3ab6d10a35be3e1320772552**
            PR #200
exact head  **f96cdab9aa243da6dc0c223a885d355e9ea0edf3**
exact-head CI **37763976833 SUCCESS**（含 Enforce required CI outcomes）
contract    docs/LEARNING_STATE_1_CONTRACT.md（A+ 细化版；L1–L6 / T01–T18 / M1–M6）

closed scope
            read-only authority 分类（learning_authority_projection.py）
            user_goal / user_self_report / system_inferred / verified /
            legacy_unverified；仅 verified 是 mastery evidence
            消除 confirmed_points → expected_concepts 隐式回退
            （chat_service.py + policy_chat_service.py，两处消费点）
            navigation / resume 只读来源标签（legacy 标 legacy_unverified）
            durable authority 的 source_id = 真实 UnderstandingEvidence id
            （lineage 解析后仍指向实际验证记录；无记录则空）

validation  本地 impact set **280 passed**（含 policy / standard /
            external-data-policy 生产路径）
            M1（基类消费点）与 M1b（policy 生产路径）负控均单独验证
            ruff PASS | git diff --check PASS
            mypy baseline PASS（122/128）
            package helper OK

known boundary
            L2–L6 **未 CLOSED**（下一门 = L2–L6 验收收尾）
            未改动 Socratic / durable 写入语义 / §164 仪器
            未新增自动 closure / 自动 Goal / 新存储
```

> Learning State-1 L1 authority 永久为 merge commit `0de80751` / exact-head CI `37763976833`。此后 main 上的 docs-only 记录提交只是该记录的载体，**不表示新 SHA 跑过验证**。

**Deep-3T authority（合同冻结基线）：**
```text
exact-main  **1514bbf76031dfeca2cb03e9c52adf5d149cd724**
            （Deep-2 CLOSED 的 exact-main；Deep-3T / Deep-3 合同已基于它核对接口）
```

**Deep-3 implementation MERGED（CLOSED 待 exact-main CI）**

```text
merge commit   **e5382659b0aa1deca9954702b108aa51ef745e93**
PR             #194（expected head f6f1ab8e）
exact-head CI  37654811749 SUCCESS
exact-main CI  37656689912 **cancelled**
              reason = superseded by a later docs-only main push
              NOT a product/test failure
              （取消时代码门已全过：pytest / ruff / mypy / mypy baseline /
               frontend deps / frontend test+build）

CLOSED authority （方案 A）
              **caa3e307 / 37658465809**
              iff 37658465809 completes SUCCESS
              caa3e307 differs from e5382659 only by docs
              (Deep-4A contract / PROJECT_STATUS);
              **Deep-3 production bytes are unchanged**

closed scope
            background continuation + parent finalization
            chat wrapper only wakes (never blocks on Deep)
            terminal child never re-executes
            honest research terminal -> parent completed
            transactional finalize revalidation
            durable blocked + recorded-terminal integrity + first terminal wins
            singleton reuse + runner cache reset

known boundary
            publication_authority = false
            assistant_message / pedagogy / learning untouched
```

> Deep-3 authority 以 exact-main CI 通过后的 merge commit 为准。Deep-3 CLOSED authority = `caa3e307` / CI `37658465809`（SUCCESS）。

**Deep-4A CLOSED ✅**

```text
authority   merge commit **ea73b8555b56e7f8c65000a9908fb20c9c7e216f**（squash）
            PR #197（expected head 08a27510）
exact-head CI  **37751620983** SUCCESS（G4A-51 门）
exact-main push CI 37753888528（push @ ea73b855；写入本状态时 in progress，
            与既有模式一致，可能被本 docs-only status push 取代）

head note   原候选 head 03f344f4；因 GitHub 对 pull_request 使用 head 分支的
            workflow 文件，旧 CI 一直用 /dev/null 打包命令而失败；
            将 origin/main（含 #198 ci.yml 修复）merge 进分支 → 08a27510。
            08a27510 与 03f344f4 产品树逐字节相同，仅 .github/workflows/ci.yml +1/−1。
            原语义审计 PASS 与 13/13 mutation 证据继续适用于未变化的产品代码；
            用户裁定不需要为新 SHA 重跑 L3。

closed scope
            audited publication candidate（audited-but-not-approved）
            publication_authority = false
            0 model / 0 network calls；不修改 answer
            PUBLICATION 第三 trigger stage
            unit-safe synthesis（EvidencePayloadUnit / effective_units / per-unit locator）
            layered validator（blocked 只需 bounded reason + 无 result；
            audited 绑定 owner.child_run_id == result.child_run_id + source/result digest 相等）
            真实多线程 C5/C6/C7 竞态
            runtime 0-model / 0-socket gate
            G4A-1…G4A-51 | mutation authority 13/13 PASS

known boundary
            仅“审计通过的发布候选”，未获发布批准
            assistant_message / pedagogy / learning_state 不变
```

> Deep-4A authority 永久为 merge commit `ea73b855` / exact-head CI `37751620983`。此后 main 上的 docs-only closeout 提交只是该记录的载体，**不表示新 SHA 跑过验证**；按 `AGENTS.md` §4.5 / §10.4，docs-only 变更不需要重跑 L3 或 full suite。

**Deep-3T CLOSED ✅**

```text
authority   **823265ae113c0f488e0e8d2d0a448c6079b80884**

validation  exact-main push CI **37642664449** SUCCESS
            ordinary full pytest PASS | ruff PASS | expanded mypy PASS
            mypy baseline PASS | frontend test/build PASS
            browser Golden Journeys PASS | real-stack browser gates PASS
            required outcomes PASS

closed scope
            durable-state-backed Deep trigger (no new queue table)
            ARM crash window recoverable
            pending Deep recoverable
            keyset paging so the whole durable queue stays reachable
            absent != malformed (deep_terminal null is not absent)
            immediate startup scan | 15s periodic rescan | non-blocking wake
            single worker | bounded shutdown | callback exception isolation
            G3T-1…G3T-23 | mutation authority PASS

known boundary
            production inert (worker not started, callbacks not wired)
            Deep still not activated

known limitation (not a closure blocker)
            no starvation-freedom guarantee when front-of-order work items
            never change durable state; revisit with a scheduler/fairness
            contract if a real backlog appears
```

> Deep-3T authority 永久为 `823265ae` / CI `37642664449`。此后 main 上的 docs-only closeout 提交只是该记录的载体，**不表示新 SHA 跑过验证**。

**Deep-2 CLOSED ✅**

```text
authority   **1514bbf76031dfeca2cb03e9c52adf5d149cd724**

validation  exact-main push CI **37628909373** SUCCESS
            ordinary full pytest PASS
            ruff PASS | expanded mypy PASS | mypy baseline PASS
            browser Golden Journeys PASS | real-stack browser gates PASS
            required outcomes PASS

closed scope
            Deep-1 child → existing ActiveResearchRuntimeExecutor
            atomic execution + active Claim Engine attach
            S6 fail-closed / no legacy downgrade
            Deep absolute wall clock + crash resume
            Standard seed → normal assessment / ranking
            LOCAL MATERIALIZE
            0 network / 0 reads_used for seed reuse
            char-budget accounting
            content_available reread suppression
            B1–B7 + exception taxonomy
            G2-1…G2-42

known boundary
            parent deep_terminal remains pending
            publication_authority = false
            no automatic ChatService continuation
            no parent finalization
            no synthesis / publication cutover
```

> Deep-2 authority 永久为 `1514bbf7` / CI `37628909373`。此后 main 上的 docs-only closeout 提交只是该记录的载体，**不表示新 SHA 跑过验证**；按 `AGENTS.md` §4.5 / §10.4，docs-only 变更不需要重跑 L3 或 full suite。

**Deep-2 seam authority（合同冻结基线）：**
```text
exact-main  **41e2d6f9132b0e72b3cf058d913c304f9c066ea0**
            （Deep-1 closeout 的 docs-only 后继；合同已基于该 exact-main 重新核对实际接口）
```

**Deep-1 authority（永久不变）：**
```text
e5c63c03c9ac77b273f2bfc158111ac676e9bc42 / CI 37599443309
```

**Standard authority（永久不变）：**
```text
c48a1ac313e59ab0104364db519340f1460e84dc / L3 37514856913
```

**Deep-1 CLOSED ✅**

```text
authority   main / e5c63c03c9ac77b273f2bfc158111ac676e9bc42

merge       PR #187
            expected implementation head  2cba839e46073efabd04ba127b3559a142efc6ee
            merge commit                 e5c63c03c9ac77b273f2bfc158111ac676e9bc42

validation  exact-main push CI 37599443309 SUCCESS
            ordinary full pytest PASS
            ruff PASS | expanded mypy PASS | mypy baseline PASS
            browser Golden Journeys PASS | real-stack browser gates PASS

closed scope
            Standard → Deep handoff
            durable seed
            deterministic child
            retry / integrity addendum
            G1–G15 PASS；G14a–G14g PASS

known boundary
            publication_authority = false
            Deep child remains pending / inert
            no active runtime execution
            no Deep-2 activation

next single slice (COMPLETED)
            Deep-2 exact-main implementation-seam audit (done)
            → detailed Deep-2 contract frozen in docs/DEEP_2_CONTRACT.md
```

> Deep-1 authority 永久为 `e5c63c03` / CI `37599443309`。此后 main 上的 docs-only closeout 提交只是该记录的载体，**不表示新 SHA 跑过验证**；按 `AGENTS.md` §4.5 / §10.4，docs-only 变更不需要重跑 L3 或 full suite。

**Deep 路线（冻结）：** Deep **不重新实现深度研究引擎**。仓库现有 `ActiveResearchRuntimeExecutor`（含多波次 gap research、Evidence Gain、per-claim/per-gap saturation、8-wave ceiling、Evidence Gate、预算尾保留、持久化 cursor、attempt marker、崩溃恢复、stop gate）就是 Deep 的执行核心。Deep 的工作量是**把 Standard 的成果可信地送进已有研究引擎**，因此拆为 Deep-1（handoff + seed + 生产 inert，**已 CLOSED**）→ Deep-2（激活 active runtime + budget + resume）→ Deep-3（自动 continuation + fail-safe）→ Deep-4（synthesis projection + cutover + Deep phase L3）。

**Standard closure authority（唯一权威）：**

```text
authority SHA     c48a1ac313e59ab0104364db519340f1460e84dc   ← exact main
L3 authority run  37514856913（ci-l3, workflow_dispatch）
L3 result         3866 passed / 6 skipped in 385.94s
L3 前置           l3_preflight PASS @ 同一 exact-main；duplicate-skip guard success
exact-main push CI 37512787764 success
```

**权威表述（不得改写）：** Standard phase CLOSED **at `c48a1ac3`**。此后 main 上的 docs-only closure record 提交**只是该记录的载体**，不表示新 SHA 跑过 L3；按 `AGENTS.md` §4.5 / §10.4，docs-only 变更不需要新的 L3。

**已 CLOSED 的三个 slice：**

| Slice | PR | merge commit | 范围 |
| --- | --- | --- | --- |
| Standard-2 | #180 | `62f0e7bf` | 持久化研究计划 + 可恢复执行循环；输出 artifact |
| Standard-3 | #182 | `964a848f` | 逐事实机械绑定、来源身份、冲突裁决；publication_authority 恒 false |
| Standard-4 implementation | #184 | `cee6aefb` | Lookup → Standard 自动 continuation（未接线生产） |
| Standard activation | #185 | `c48a1ac3` | production composition OFF → ON（本刀即最终 candidate） |

**生产形态（已生效）：** `get_chat_service()` → `StandardContinuationChatService`；Lookup 的 `resolve_web_tools` 与 Standard 的 `gateway` 是**同一个 web agent 对象**，共享同一 RuntimeRepository；无第二 gateway、无第二层 cache、无 feature flag。Standard 语义（admission / deadline / lease / exactly-once / binding / fail-safe）未因接线改动。

**Standard 边界（冻结，不再调整）：** `usable/read_backed/relevant` ≠ claim support ≠ publication authority；自动 continuation 只产出内部证据状态，**不修改 assistant_message、pedagogy、learning_state**；continuation 崩溃时已完成的 Lookup 答案照常返回。

**CI 纪律（已冻结并实测）：** `AGENTS.md` §14 分层验证；`tools/ci_scope.py` 是 browser/frontend/impact-set 路由的**唯一权威**（workflow 不得按 event 类型重新推导）。standard 类别 → `standard_research_loop` fast path；`learning-backend`（如 `runtime_repository.py`）无 mapping → 普通 full pytest，**普通 full pytest 不是 L3**。正式 L3 只能由 `ci-l3.yml` 显式触发一次，且跑在 exact-main。

**本机主 worktree：** `C:/Users/Zhang/Desktop/study agent` 位于 main，但 `.mcp.json`、`docs/PROJECT_STATUS.md`、`frontend/package.json`、`frontend/package-lock.json` 有既存修改，保留原样，不用远端 main 覆盖。施工 worktree 位于 `D:/study-agent-validation/`。

**冻结路线：**

1. ~~Standard-2~~、~~Standard-3~~、~~Standard-4 implementation~~、~~activation~~：**全部 CLOSED**。
2. **Deep（Deep-1 / Deep-2 / Deep-3T / Deep-3 / Deep-4A 全部 CLOSED；Deep-4B NO-GO；当前 = Learning State-1 L2–L6 验收收尾）**：多轮重写、Evidence Gain、saturation、长预算与 interruption/resume；UI 继续独立后置。合同见 [`DEEP_1_CONTRACT.md`](DEEP_1_CONTRACT.md)，已冻结四件事：Standard → Deep 升级条件、Deep 独立预算（`DEEP_V1_BUDGET`）、如何复用 Standard 已有 evidence 而不重读（durable seed + 二次 hash 校验）、stop / saturation / interruption-resume 定义（全部复用现有 authority）。

**状态口径：** `Standard = CLOSED ✅`；`Lookup` 保持其既有已验收状态；`Deep-1 / Deep-2 / Deep-3T / Deep-3 / Deep-4A = CLOSED ✅`；`Deep-4B = NO-GO`；`Learning State-1 L1 = CLOSED ✅`（authority `0de80751`）；`Learning State-1 L2–L6 = 未 CLOSED`（下一门 = 验收收尾）；`UI = 后置`（独立交互合同另开一 PR）。

## 0A. 冻结研究路线

```text
Lookup
  → VERIFIED / SAFE_ABSTAIN / pending ESCALATE_STANDARD
Standard（CLOSED）
  → 多源补全 / 双方比较 / 冲突处理；已由 production runtime 自动消费
Deep（Deep-1 / Deep-2 / Deep-3T / Deep-3 / Deep-4A CLOSED；Deep-4B NO-GO）
  → plan / gap / Evidence Gain / saturation / interruption-resume
  → 复用现有 ActiveResearchRuntimeExecutor；不新建第二套研究引擎
```

共享原则：**模型决定“去哪找、找什么”；程序决定“你到底找到了什么”。** `usable/read_backed/relevant` 不等于 claim support；claim support 不等于 publication authority。

## 0B. 仓库与施工纪律

- 一个 feature slice 尽量整块完成、一次验证、少提交；只在阶段门需要权威 exact-head 证据时触发 CI。
- push/PR 之后只认当前 exact head；旧 HEAD 绿灯不能替代新 HEAD。
- 生产候选只有在 CI、最终审查与 expected-head 一致时才允许合并；merge 与 CLOSED 是不同门。
- UI、研究与其他项目保持独立 bounded slice，禁止为赶门把无关改动混入。

## 2026-10-11 RP-1 证据归档安全验收（#204）

**2026-10-11 #204 归档与安全修复候选：** 归档 [原A/B与UI证据](evidence/rp1/2026-10-09/README.md) 的409原文件/4,842,111字节保持原始SHA；96规划、原6回答+续18回答、合并24答卷/映射/封存评分和22张UI截图仅作证据保存。133个固定Git/校验值逐条精确登记，原Linux报告与本地扫描无剩余，18负控/41 CI outcome测试PASS，扫描插件/排除规则/强制门未放宽。当前重新合入main `5155f107fae23fb19ce7d857745075b5b6a21bc2`，只解决交接docs冲突；须新head CI与最终安全审阅，RP-1/Deep-4B/B-Search资格不变。**唯一下一slice为现有PR合并收口**，下方历史NEXT不构成新功能授权。
