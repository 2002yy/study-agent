# Study Agent 当前状态

> **唯一进度入口：当前权威能力、验收边界与下一门。**
> **最近一次状态验收基线：2026-10-27 / `4cbcefe2efddb986d71deb1bf5f7d5dff5c571cf`（#289 合并提交）。**
> 本行是那一日期**已核验的基线**，不是“当前 main”。main 此后继续前进不使本节失效，也不构成重写本文件的理由；下表每行的资格以该行自身记录的 head 与 run 为准。
> 产品定义：**Study Agent 是体验接近 GPT-6 Chat 的智能聊天与研究 Agent。自然聊天、自主研究、持续交互、智能 UI、统一多模态、工具执行是六项通用核心能力；长期学习与教学是其上的专业场景。**
> **部署边界：仅支持可信环境下的单用户部署。** 多会话并发安全不等于多用户安全；多用户身份与数据隔离是独立立项，尚未实现。

本文件只保留当前快照、明确阻断和唯一下一门，不再不断追加每次 CI、诊断与其他项目日志。整理前的交接内容没有删除，而是**完整保存在以下两份历史快照**：

- [2026-10-24 当前 main 整理前完整正文](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-24.md)：原 `docs/PROJECT_STATUS.md` blob `38439199c16dba836945890b2987496aa2667e71`（999 行）。包括 2026-10-24 AR 候选、测试及各阶段原始交接，其旧日期的“尚未合并”只属于当时历史状态。
- [2026-10-23 旧 #282 草稿归档](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-23.md)：原 blob `f067534fa01a68de234eeaea0dc2216dc0462cf3`（520 行）。更早历史见 [2026-10-06 归档](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md) 与 Git 提交。

## 0. Current Handoff（cold-start 入口）

> **当前采用产品能力快速交付：A线M4-C3评测执行链路与B线M4-D增量修改原型并行，范围见§0B。
> main `95e2bbc6` / CI `41847418702` 已success，A/B已交付；授权的首次真实12题已完成，下一片M4-C4。**

### 2026-11-06 M4-G媒介选择提示首片

branch codex/interactive-medium-planning-20261105，base aa161e82，独立工作树
D:/study-agent-validation/interactive-medium-planning-20261105。
现有INTERACTIVE_CONTEXT增加按任务选择文字/静态图/交互/动画/Three的指导，尊重用户明确选择，
定义参数范围、数学与业务不变量、初始输入/预期输出/边界案例，以及实际验证证据边界。
复用瞬时packAnswerUiContext入口与自由HTML协议。owner=orchestration-contract；P2 Static Loop。
命名人工影响集m4g-medium-guidance为frontend/src/features/answer-ui下interactivePrompt.test.ts、
answerUiProtocol.test.ts、controlledThree.test.tsx、InteractiveDocument.test.tsx、AnswerCardView.test.tsx，
共41 PASS；tsc、Ruff、diff-check PASS。首条vitest命令附带不存在的interactiveRuntime.test.ts，
实际收集3文件15项；随后补直接消费者2文件26项，以上只记录真实收集数。
动态模型比较、浏览器验收、本地L3未运行，没有付费调用。当前仅确认提示到发送上下文的接线及协议兼容，
模型是否正确选择媒介仍待授权真实任务评测。下一片：为固定任务补媒介选择与不变量的真实评测证据。
审阅修复将文档输出、参数及已有界面修改指令明确限定到可视化文档选择，纯文字直接Markdown回答。
补充纯文字请求/协议回归，最新直接3文件16 PASS、tsc/diff-check PASS，真实模型遵循情况尚未测量。


### 2026-11-06 远端候选继续收口

#347合并main f756889c的CI42052429417已确认success。
#348修复d37d53be已推送：Three回放失败来自未覆盖的防抖状态PUT，精确fixture并等待真实
状态保存后定向浏览器6 PASS/18.3s、tsc/diff-check PASS；此前全套配置teardown依赖其他
journey产物，改用既有M4C定向配置。新提交CI尚未取得完成证据，保持待合并。
M4-E已创建#349，base为Three分支，已吸收d37d53be形成137546ea；对应CI42173118280
单次观察pending。前述本地证据仍按各自范围记录；本轮仅合入已验证测试fixture。
M4-G独立分支已推送0a1d42eb，41项提示/协议影响集与tsc通过；审阅要求将旧无条件输出
study-ui指令改成媒介选择后的条件分支，修订中。无付费模型调用或质量比较。
下一门：M4-G修订后独立PR；#348/#349在后续明确收口时按精确提交检查CI与审阅后合并。

### 2026-11-05 合并本地技能并行推进后续

#347 head6ee2e91d，CI42003552747全部成功，增量8b25fce2..6ee2e91d独立审阅无阻断，
已合main f756889cd96c3ae2380086d291f832c63e9d3ce0。main CI42052429417单次观察in_progress。
#348已改base main；head5f655073的CI42004634483浏览器3项Three React回放失败，暂不合并，隔离诊断中。
M4-E追加b75c9c6c桌面/手机真实React双沙箱发送回归2 PASS，API为受控fixture，无模型调用。
验证身份发送、网络失败同文重发、取消后普通发送；单文件浏览器运行跳过依赖全套产物的
全局teardown，保留setup。会话切换仅单元证据。65a62fcb关闭活动回答期间修复草稿的文本队列/
steering入口，取消后普通队列恢复；ChatPanel/API 62 PASS、tsc/diff-check PASS。
前一候选5f655073..aa161e82只读审阅未发现正常发送/预算路径阻断，指出的队列边界已由上述回归修复。
M4-E候选待远端CI/最终审阅；M4-G另工作树基于已提交aa161e82开始离线媒介选择指导切片。
不轮询CI，不新增付费调用，不借旧提交绿灯给新提交。
下一门：推送M4-E并开独立PR，修复#348浏览器失败，M4-G离线验证后独立推送。

### 2026-11-05 M4-E发送链路快速并行收口

branch codex/interactive-repair-feedback-20261105；基线7ffae8c3已推送。
本轮用户授权高速并行、可提交片立即推远程、不等CI；前后端独立提交，未执行合并。
后端8d738ae9绑定本会话保存源码、版本/hash/能力声明，prepare/生成/重试经同一账本限额，
无既有费用配置或未知源码时拒绝；HTTP只接受身份字段，拒绝传入HTML或额度覆盖。
前端a336a362/a18c421d绑定修复草稿与当前会话，网络失败同文重发保留身份，
取消、切换会话或发送其他内容清除；复用版本提示与取消操作。
owner=orchestration-contract/UI；Static Loop。命名interactive_repair影响集249 PASS/138s，
最终服务补充回归15 PASS；mypy118/128新增0、Ruff/diff-check PASS；前端直接集87 PASS、tsc PASS。
日志保留D:/study-agent-validation/m4e-repair-evidence-20261105/。
本轮未运行L2/L3、浏览器实测或动态模型比较，没有付费调用；工程候选不授予产品质量/合并资格。
首次Git schannel握手失败，单次http.sslBackend=openssl推送成功，未改全局配置。
下一片：浏览器正式修复发送与失败恢复验收，再按精确候选执行审阅/合并门禁；不轮询CI。

### 2026-11-05 用户纠正CI等待方式；继续M4-E证据反馈

用户明确要求CI只查一次，goal持续运行应先推进后续，不能自动续轮询；永久规则已更新AGENTS §7。
当前branch codex/interactive-repair-feedback-20261105，基于Three候选及已提交skills覆盖注册修复。
Three分支已同步6ee2e91d修复skills前端目录漏注册CI覆盖（登记真实browser spec，非豁免）；
注册/路由98 PASS，之后不再轮询相关CI。

后续M4-E前端已实现用户触发排版测量：字体/控件宽高/横向溢出，经原双sandbox桥回报checkId、
元素ID、实测值、阈值；不因缺测量或未发现这三类问题宣称任务正确。可生成保留旧功能/版本/能力/
参数的修复草稿，点击只填输入框，不自动调用模型。真实app两视口2 PASS，测量与独立DOM读数一致，
生成草稿发送次数0；formatter6单元、组件/能力相邻合计26 PASS，tsc通过。
请求级修复次数/费用guard已并行实现和验证中，仍未接最终修复发送，当前不能宣称人民币上限已生效。
下一片：绑定本线程保存源码身份、官方修复发送字段及真实计价guard，完成后集中做一次CI/审阅收口。
无新增付费模型调用，不扩全局环境额度，不建立第二套账本。

### 2026-11-05 合并收口中的实际状态

#346精确head53c1b4a的CI41986434543五项全绿，审阅线程已解决，已合main8d6ad64a，
main树与审阅head完全一致；main CI41989085126已观察in_progress，不借PR绿灯宣称main验证结束。
#347已改基main；新增审阅发现prepare失败丢技能选择，已在a3d16e90修复pending身份，
普通/Policy保留原IDs、停用拒绝和空父禁止新增均有回归（技能34 PASS、相邻聊天/策略95 PASS）。
认证恢复的Skill旧错误提示也已修，17项单元与原真实栈双视口2项通过。该head CI41989282906进行中。
#348已显式合入这些修复，不使用前片未提交状态。合入后的前端全套716 PASS/130文件，
最后技能/历史/导出直接集34 PASS。两个导出HTML已在独立HTTP服务实际打开、调参、播放暂停并读取
WebGL几何像素，2 PASS；产物保留m4f-artifacts-responsive-20261105，不依赖Vite/后端应用。
目标仍未完成：待#347/#348精确候选CI/审阅及顺序main合并，最后main资格核验后关闭长期目标。

### 2026-11-05 用户明确开启长期深度工作：M4-F宿主Three.js

当前回到原路线，用户明确要求持续深度推进Three.js等能力；不是宣称M4-D/E/G全阶段已完成。
工作branch codex/controlled-three-20261105，基线本地Skill已提交8b25fce2。
前端按capabilities:["three"]显式启用本地锁版Three.js，仅在需要时加载，注入最内隔离沙箱的THREE；
不放宽CSP或允许模型加载第三方脚本。前端实现由incremental_patch负责；root负责能力字段在历史/恢复/
局部补丁中的保留、可操作3D与动态过程样例、浏览器隔离/画面检查和生成提示接线。
并行收口#346浏览器失败：日志只见桌面/手机旧label“上下文深度”断言，实际已改“个人记忆读取范围”；
eval_runner在独立context-candidate工作树修正并复验。#347另补开发服务/skills代理。
当前禁止宣称Three.js能力已交付；后续按实测与准确CI更新。没有新付费授权或模型调用。
后端已增加capabilities:["three"]严格验证与历史、旧版恢复、局部补丁保留，未知能力拒绝；
相同HTML但能力声明不同的旧版本视为冲突，避免恢复错误宿主环境。对应影响集68 PASS/19.26s。
宿主实现f7fe32d2已完成并显式合入前片代理/测试修复63f15f7f。
固定Three.js0.187.0，按声明懒加载并仅在最内sandbox执行；生成提示已接线。
真实runtime双视口2例+React产品入口4例共6 PASS；前端713 PASS、审阅空数组修复后13项直接回归通过；
后端相邻历史/恢复/评测208 PASS，mypy118/128新增0。当前正在提交整片候选，CI/审阅/合main尚未完成。
详细边界与自包含产物见[M4-F宿主能力](M4F_CONTROLLED_THREE.md)，没有新增付费模型调用。

### 2026-11-05 本地Skill导入与本轮使用

用户明确选择“先做本地技能导入与使用”，记忆复用现有面板/MemoryService。
本片branch codex/local-skills-20261105，基于明确已提交f527b06a（前片PR #346，非兄弟WIP）。
后续显式合入前片审阅修复67442d95；合并后技能/聊天研究/群聊新闻直接影响集48 PASS，未依赖未提交WIP。
独立文本store与认证API支持SKILL.md导入、列表、启停、删除；新装默认停用。
设置页可粘贴/上传、启用和选择“下条消息使用”，只将ID随下一次单聊发出，不改写用户问题；
普通与Policy生成均按启用store取正文，瞬时拼入本轮指令，不写长期conversation_instruction。
不选不注入，重试/续写锁定父回合的选择；停用/未知ID、禁止本地资料的云端策略在路由前拒绝。
Policy包含skill_context与数量审计，route只记ID/名称/哈希；原费用与工具权限不变。
不执行脚本、下载依赖或额外模型调用；本地私有store已Git忽略。入口与边界见[本地Skill](LOCAL_SKILLS.md)。

验证：后端生命周期/策略/记忆/认证/安装影响集352 PASS；审阅发现空技能父回合的retry可新增技能，
已修复并经普通/Policy实际retry与原注入、隔离、云端禁止及HTTP请求桥接9项最终回归通过。
前端128文件708 PASS、tsc/build通过；桌面/手机安装→启用→选用→实际发送2 PASS，
触控布局修正后2 PASS，手机截图目视PASS；src mypy118/128、新增0，Ruff/diff-check通过。
存储API测试覆盖认证、原子写失败保留原文件及限额；浏览器为受控API fixture，实际模型请求另由离线fake证明。
本批没有真实模型调用，不宣称模型已遵循或受益于技能；GitHub安装/自动匹配不在首版。
下一门：当前片与前片按各自精确HEAD CI和审阅顺序收口；后续付费复测需新授权。

### 2026-11-04 模型、记忆范围与旧速度档解耦

#345已按精确head83b82f05的CI41859344676全绿及当前审阅收口合main，merge f18cabda；
合并树与审阅head完全一致，main CI41862356230已观察queued，不借PR绿灯宣称main验证完成。
本片从该main继续，branch codex/task-model-context-20261104。

owner=orchestration-contract/UI。自动模型只按任务路由规则选择，手动模型选择继续优先；
旧fast/standard/deep不再强制flash/pro或决定记忆读取范围。单聊历史统一最近30条消息，
不再按旧档位只留8/18/30。为避免额外模型路由调用，旧fast下禁止LLM路由的兼容门暂保留。
记忆范围独立保存context_mode，设置页明确显示读取内容，支持none（不读个人记忆），
切换范围不改模型、输出额度或performance_mode；聊天与Policy路径、旧helper均读取独立默认。
修复none/未知范围原先回退读取archive的缺陷：不读文件，也不向模型拼入任何已有记忆文本。
保留显式已知范围与历史字段，未迁移数据库，没有新增付费调用。

验证：后端聊天/设置/策略/记忆及路由影响集341 PASS/137.30s；前端126文件703 PASS，tsc通过；
桌面/手机设置保存→刷新→none/pro聊天请求2 PASS，手机截图目视PASS；src mypy118/128、新增0，Ruff/diff-check通过。
浏览器保存回读用受控API fixture，真实后端设置往返另由TestClient测试覆盖。独立前后端增量审阅CLEAN。
外部审阅2个有效P2已在同片修复：完整记忆范围/旧deep速度档不再触发deep_requested，
显式深度研究仍由原请求文本/专用研究入口解析；普通/Policy保存deep范围的21项直接回归通过。
新闻摘要、讨论、群聊开场的模型解析器也去除旧速度覆盖，显式模型优先，auto保留原flash默认；
3真实入口×3模型选择×3旧档及相邻影响集46 PASS。未改变新闻输出预算或自动增加调用。
用户随后明确选择“先做本地技能导入与使用”，下一片复用现有MemoryPanel/MemoryService，
实现SKILL.md文本导入、启停和本轮选用；不执行技能脚本，不增加模型调用。

### 2026-11-04 按任务分配输出额度，逐步淘汰两套旧分档

用户明确确认“两套都逐步淘汰，按任务分配额度”。本片去除“简单/普通/复杂交互”分档，
明确创建或修改交互统一16384 tokens；普通文字统一8192，快/标准/深度不再决定用户答案长度。
保留旧模式参数、已有会话与模型/上下文选择的兼容；内部claim binding单独≤1600，
避免结构化辅助任务跟着用户答案扩额。去除3500/6000/9000旧交互档与700/1100/1600文字档。
保留文字/交互任务区分、发送前按实际额度计价预留、共享费用门与零自动重试；
未新增付费调用，不宣称扩大额度已实测解决所有截断。继续使用同一PR #345。
后续淘汰旧模式的模型/上下文分流与界面选项需按产品行为逐步迁移，不删除历史状态字段。
当前预算生命周期+评测影响集295 PASS/123.56s；src mypy118/128、新增0，Ruff/diff-check通过；
UI未再改动，复用前一提交的693项前端测试与4次浏览器回放。独立增量审阅CLEAN。

### 2026-11-04 M4-C4：扩大交互额度与源码恢复

用户追问后明确要求扩大上限：普通interactive输出档由6000升至9000 tokens，沿用既有
9000硬档；简单单滑块3500、普通文字原档不变，零自动重试和原共享费用门不变。
真实首批6000额度、原文与评分保持冻结；当前离线prepare输出当前产品9000预算，不回写V1清单。
本批owner=orchestration-contract/UI：修复能力提示中解析器不接受的中文示例id，强调正确协议、
完整闭合与全部文字/控件尺寸；不新增HTML字符数目标，不用压缩替代完整功能。
普通html完整文档/截断文档明确显示“源码尚未运行”，折叠保留原文，提供生成界面草稿按钮；
点击仅填写输入框，仍需用户发送，不会自动调用模型。普通代码片段、嵌套示例与已有效组件保持原行为。

本批沿用PR #345，从结果交接升级为“真实缺陷修复+结果记录”完整交付片，最终head以PR恢复。
原始M01/P01回答纳入离线回归，旧生产4 FAIL负控，新前端125文件693 PASS、tsc/build通过；
真实两样本×桌面/手机4次回放通过，重载、草稿和无横溢出验证完成，手机截图目视PASS。
预算变更既有interactive_budget_lifecycle+评测影响集295 PASS/137.31s；Ruff通过，
变更Python模块mypy零错，历史V1清单未改，最终SHA/CI绑定本PR当前HEAD。
未新增模型调用，真实批次费用仍¥4.761542预留；未宣称9000额度或提示修改已提升实测成功率。
下一片：在用户新授权的少量复测中验证M01/P01；没有新授权时继续离线补最直接的缺失观测。

### 2026-11-04 首次真实12题已完成；A/B已合main

PR [#344](https://github.com/2002yy/study-agent/pull/344) 已合并，main `95e2bbc6`，
与最终审阅head `c641ec34` 树完全一致；PR CI `41847109906`、main CI `41847418702` 均success。
中断恢复审阅项已修复并解决；当前能力包括真实请求评测链路和固定页面增量修改/失败回退原型。
合并执行偏差：`gh pr merge --auto` 在CI结束前直接合并，不能将auto当等待门禁；之后两份精确CI已绿。
后续合并须先显式确认当前HEAD检查完成再调用merge，不以该命令代替门禁。

用户已在本次聊天明确授权deepseek-flash固定12题、零重试、单次≤¥1/本批≤¥12/共享≤¥30。
当天重新核验官方价格、共享余额与原账本后，实际12次发送、12份原始回答；10份产品协议HTML、
20份双视口页面/截图。本批预留¥4.761542，共享累计¥13.392368/¥30，剩余¥16.607632。
按响应usage与峰值价估算¥0.3292984，不是提供商账单，不释放历史预留。

自动结果：**0确定通过、4确定失败、8 indeterminate**；成功率未知，上下界0–66.67%。
M01输出截断且返回普通html代码块，P01正常结束但也返回普通html代码块，均不能作为产品交互组件；
J01/A01字号不达标。10份可抽取页面双视口均0运行错误；缺失题族观测不当成模型错误。
完整报告、逐题限制和下一片见 [首次评测结果](M4C3_FIRST_RESULTS_2026-11-04.md)。
原始证据与授权/交付回执保存在 `D:/study-agent-validation/m4c3-generation-paid-20261104/`。

**唯一下一片：M4-C4修生成协议遵循与截断处理，以本批原始响应建立静态复现，范围内完成一个可用修复。**
不调高冻结本批预算、不改写原输出或历史评分；下一次付费复测另行授权。
M4-D模型接入仍需同批局部修改/完整重建比较；当前原型没有证明通用修改成功率。

### 2026-11-04 A/B能力整片交付：评测执行器 + 增量修改原型

本批从已全绿main `5d4d8381` 新建 `codex/m4-eval-and-patch-20261104`，按用户最终决定并行开发，
普通实现/本地修复不再逐条请示。开发纪律已写AGENTS §15，当前双线范围取代旧顺序，见§0B。

**成果A（P1/P2，owner=orchestration）：** `tools/m4c3_run.py` 实际走ChatService→llm_client→
SDK完整请求计价→共享账本同事务批次预留→单次HTTP发送。固定12题，重试0，每题固定key；
付费需显式flag+匹配授权JSON，并强制原共享账本/实验、12次/单次¥1/本批¥12/共享¥30；拒绝陈旧价格。
保存原始请求/响应、回答/HTML、finish/model/usage、耗时及保守预留；`--browser` 自动产出两视口截图、
运行错误、观测与scores.json。无证据保持indeterminate；首次成功率与上下界分列，构造响应不算模型成绩。
完整入口与授权模板见 [M4-C3执行说明](M4C3_GENERATION_EVAL_PLAN.md)。

已实际执行12题完整假HTTP链路，12请求=12预留，24份真实产品沙箱页面/截图；
`D:/study-agent-validation/m4c3-full-pipeline-envfixed-20261104/`，fake_http、12 indeterminate，
real_model_quality_data=false。临时账本构造预留¥4.761542不是真实费用，未动真实账本。
固定普通/flash/fast/nahida、无历史/RAG/个人记忆、settlement assembly关闭；未声称覆盖可选assembly-on。
官方价格公开映射DeepSeek-V4.1-Flash-1017，峰值输入¥2/输出¥8每百万tokens；为兼容既有账本不可变指纹，
预留仍用更保守的¥9/¥27。来源与当天快照见 `config/m4c3_pricing_20261104.json`；执行前仍核实并取得费用授权。

**成果B（P2，owner=orchestration/UI）：** `src/interactive_patch.py` 按组件id/revision/源码SHA定位，
精确唯一锚点局部替换，原子构造临时版本，拒绝过期/歧义/重叠/越界/整文替换。
`py -3.12 -m tools.interactive_patch_demo --out <新目录>` 一次验证V1、增加Double x控件的V2、
破坏计算的V3，三版本×1280/390六次真实沙箱回归；V2保留旧计算/Reset且新控件可用，V3拒绝，活动版仍V2。
产物 `D:/study-agent-validation/m4d-patch-final-20261104/`，手机截图目视PASS。
这是核心API与固定页面的侧车版本原型；不写生产用户数据库、不切换默认策略。见 [原型边界](M4D_INCREMENTAL_PROTOTYPE.md)。

**验证**：联合Python影响集97 PASS；随后仅修改唯一锚点重叠歧义与付费账本绑定，直接影响集另验；
最终直接影响集25 PASS、评分汇总最后7 PASS；A两视口12题演练与B六页面原型均完成，tsc/Ruff/format通过。
新增4文件mypy零错，src基线118/128、新增0；变更范围secret扫描0项。日志 `D:/study-agent-validation/m4-ab-*`。
一次Windows子进程缺少SYSTEMDRIVE/PROGRAMDATA导致IME写出字面量目录，已补标准路径环境并重验，
生成物保留到 `D:/study-agent-validation/m4c3-generated-systemdrive-20261104/`；浏览器不继承模型凭据。
PR #344首候选 `e401c575` 的CI `41818186700` 五项全绿，两线交叉审阅未发现阻断。
外部审阅发现中断重放目录无法恢复，已在同一PR修复：保留已完成视口报告，归档未完成尝试后继续，
不重发模型请求。真实中断恢复演练确认完整报告字节不变、残留截图保留、批次恢复完成、模型调用0；
恢复回归3 PASS/2无语料跳过、tsc通过。最终SHA/CI以PR当前HEAD及合并回执恢复；保持用户根目录WIP。

**唯一真实阻塞**：付费授权尚未给出。工程门禁与合并收口后，申请deepseek-flash 12次首次生成、
单次保守预留≤¥1/本批≤¥12/沿用共享¥30；获准后直接执行并报告真实结果，再决定下一轮生成/修改改进。
本批真实模型调用0，无真实成功率或ChatGPT对照结论。

### 2026-11-04 用户授权：逐层合入 main

用户明确要求“快速推进”并“一直推进到分支合并入main”。本轮授权工程集成，取代此前
“保持Draft/暂不合并”的执行限制；不授权付费调用，也不把工程合并说成真实生成质量验收。
集成顺序为 **#338 → #343（原预算分支）→ #339 → #340 → #341 → #342**。
采用merge commit保留各层祖先关系，逐层核对main合并树与该层已验证HEAD的树一致；
每层复用自己的精确HEAD CI，补当前范围审阅，不将后一层绿灯借给前一层。

已完成#338，merge `a5ada82ec8e190e149782212545516fb3304530f`；预算候选已补建#343，
固定head `5d39ce3b`。#339/#340/#341原head的五项CI全绿；本段所在#342新head需独立CI。
集成核对发现#342原先只基于#341的2ca73a1c，漏了后续f04ea68d状态保存串行化修复；
现已显式合入f04ea68d，3文件自动合并无冲突，相关前端61 PASS、tsc通过，完整CI绑定新HEAD。
#338/#343/#339/#340/#341现已顺序合main，分别为a5ada82e/11f270ca/245300fb/f2301345/323ae0e5，
每层main树均与各自已验head完全一致。#342候选cf96f331的CI41801683258五项全绿后，
最后复核收到3条有效P2审阅：J01两个阶段需读取实测引用、隐藏/无描边箭头不得作为证据、
SVG text与small/pre/code字号不得漏测。已在同批修复，并保留旧代码2单元+9浏览器失败负控。
J01题意/数值/阈值不变，只修证据来源；HS02改为真实画错指向而非只改声明，仍检出目标故障。
修复后前端124文件/689 PASS、tsc PASS；浏览器72 PASS后仅旧断言（文字对但图错仍应通过）
失败，修正为实测图错fail后单项通过；12参考/24故障/缺证据负控不变。真实原文复核另存
`D:/study-agent-validation/m4c3-raw-review-fixed-20261104/`。新head重新绑定CI，不借cf96f331绿灯。
当前审阅及合并回执 `D:/study-agent-validation/m4-integration-review-receipt-20261104.md`；
执行者审阅与外部批准区分记录，没有把空review列表冒充外部批准。

本段随#342合入main后，工程集成状态以GitHub六个PR的mergeCommit与main实际包含关系恢复，
最终main SHA/CI回执保存在 `D:/study-agent-validation/m4-main-integration-receipt-20261104.json`。
若#342尚未合并，下一动作继续上述链；合并完成后下一开发片仍是M4-C3完整请求的假传输核验与
计价/预留/单次发送绑定，之后单独申请真实评测费用。M4-D不提前启动。

### 2026-11-04 M4-C3 第二批：真实原文重放与批次费用边界

基线 `bd3bf1c26e28b83876884f4c18af28394e6a6b87` 的 pull_request CI
[41786784266](https://github.com/2002yy/study-agent/actions/runs/41786784266) 已失败：
classify/frontend/browser成功，backend仅secrets失败（pytest及mypy baseline通过）。
12个提示词SHA被熵扫描识别；本批将字段统一为既有规则识别的input_sha256，保留原提示词和哈希，
未改workflow或放宽安全门；变更范围扫描0项。新HEAD仍须独立CI，不能借旧绿灯。

- `tools/m4c3_export.py` 从显式数据库只读导出原始HTML，支持多个库、内容去重、全新目录；
  不注入桥接桩/样式，不猜题。task-map显式映射冻结题实例，旧原始模型输出与参考页/负控不混计。
- `rawReplay.ts/spec.ts` 在真实产品清洗/CSP/沙箱内按1280×800、390×844重放，核对源哈希、
  导出原始观测/判据/错误/截图。J01复用语义定位，支持Page/Frame；未支持题族保持indeterminate，
  非冻结实例unjudged并保留运行/可用性结果。观察器定位异常单列，不冒充模型运行错误。
- 复用既有调查的两个数据库，9份真实原文×2视口=18次重放，0运行错误；J01 r1/r2/r4任务检查
  全确定通过，r3箭头错误fail、一致性indeterminate；两视口9/9均因13px字体fail。
  其余5份不是冻结题实例，未计入12题成绩。证据 `D:/study-agent-validation/m4c3-raw-batch2-20261104/`。
- `tools/m4c3_budget.py` 在既有账本的同一BEGIN IMMEDIATE预留事务内加固定12次/单次¥1/
  本批¥12/共享¥30限制；固定题目key跨重启拒绝重发。11次后两连接争抢最后名额只有一个成功，
  共享余额、子费用、cap变更与非正整数金额拒绝均有离线回归。无schema/产品src变更。

**验证**：Python L1（prepare/export/budget + interactive_history/interactive_budget/
spend_ledger_persistence）**85 PASS/32.79s**；后续元数据更新与去重断言prepare/export **8 PASS**；
浏览器rawReplay/semantic/sandboxViewport **10 PASS/13.3s**（含18次真实重放）；tsc、工具mypy
3文件0错误、Ruff/format、diff-check通过。无L2/L3触发，不重复全量。费用模块只在临时测试库预留，
真实共享账本0次新增预留，模型调用0，无ChatGPT对照，结果为engineering-only。

分支仍 `codex/m4c-acceptance-core-20261104`，工作树
`D:/study-agent-validation/intelligent-ui-budget-lifecycle-20261103`，基线bd3bf1c2；候选SHA以本段提交恢复。
提交前仅本批清单内文件变更、无旁支WIP；新HEAD提交/推送/CI回执另记，#342不合并、不转Ready。
日志 `D:/study-agent-validation/m4c3-batch2-*`；原始导出与双视口报告已落盘，可冷启动重放。

**唯一下一片**：用假传输冻结12题完整产品出站请求（模型/参数/档位/输入/结束原因），
将保守计价、上述批次预留与单次发送绑定验证；再核验供应商版本/现价并准备最终费用授权。
目前费用模块尚未接入真实发送链路，不代表付费执行已就绪；12次/单次¥1/本批¥12提案仍未授权。

### 2026-11-04 M4-C3 离线准备批次（付费未执行）

已只读核验 `ed9c598d22af7d447a6f4388380555ad3e42b9e5` 的 pull_request CI
[41698749484](https://github.com/2002yy/study-agent/actions/runs/41698749484)：
classify/frontend/backend/browser/test **5/5 SUCCESS**；旧 fcd4347e 的 41698131420 cancelled。
#342 仍 Draft，base 为 `codex/interactive-state-snapshots-20261103`；未合并。

新增 [M4-C3 评测计划](M4C3_GENERATION_EVAL_PLAN.md)、[12题冻结输入](M4C3_PROMPTS_V1.json)
与 `tools/m4c3_prepare.py`：离线输出提示词/哈希/预算，12题均为interactive/6000 tokens；
共享账本只读事务核验23条预留、¥8.630826/¥30，余额¥21.369174，未新增预留。
工具缺账本不创建、cap不一致拒绝、输出已存在不覆盖，始终paid_authorized=false，无发送代码。
源码核验修正随机性方案为实际默认temperature=0.7、top_p/seed不发送，不将环境变量冒充已生效参数。

沙箱测量不再只能固定900px：新增显式1280×800/390×844探针，检查内层实际宽度；
响应式页通过，900px页面在390px内正确报告溢出。原默认尺寸保留；桌面参考/故障判定不变。
新增 `playwright.m4c-offline.config.ts` 只收集acceptance影响集；完整浏览器配置的Golden Journey
收尾校验不变。首次误用完整配置跑子集时2项测试通过但收尾缺success manifest，已改用专用入口；
另一次准备命令从frontend目录调用根工具失败，改正cwd后通过，均未改产品源码掩盖失败。

**L0/L1**：Python影响集（prepare + interactive_budget + spend_ledger_persistence）40 PASS；
冻结清单最后措辞更新后prepare 6 PASS；前端model 45 + InteractiveDocument 15 PASS；
浏览器sandboxViewport/sandboxParity/sandboxJudgment **4 PASS/36.5s**，内含12/12参考、24/24故障、
3/3缺证据负控，parity无行为差异；tsc、Ruff/format、工具mypy（0错误）、diff-check通过。
未改src，未放宽src mypy baseline；本批是评测基础设施局部改动，无L2/L3触发，无本地L3。
日志/快照：`D:/study-agent-validation/m4c3-*-20261104.*`；既有用户根工作树未改。

分支 `codex/m4c-acceptance-core-20261104`，工作树
`D:/study-agent-validation/intelligent-ui-budget-lifecycle-20261103`；基线ed9c598d，候选SHA由本段提交恢复。
本批仅上述8文件，提交前无其他脏改；提交后预期tracked clean。#342保持Draft，不合并；
推送后的新HEAD CI单次观察另见回执，ed9c598d绿灯不授予新HEAD。
0次模型调用、无ChatGPT对照、无真实生成质量结论；提案12次/单次¥1/本批¥12尚未授权。

**唯一下一片**：补真实原始文档的沙箱重放入口（两视口；不支持的布局保持indeterminate），
随后离线冻结完整产品请求并绑定调用次数/费用子限额；单独授权后才运行M4-C3，不启动M4-D。
真实输出适配器不足是观测能力缺口，不要求付费前能判所有布局；不能用参考页data属性代替真实语义。

### 2026-11-04 后续片：沙箱内完整判定

按评审要求，把“直接渲染 vs 沙箱观察一致”推进到“沙箱内能否正确判定”：

- `sandboxJudgment.spec.ts` 在真实产品沙箱内重新取证据并执行完整判定；
- 直接矩阵、故障目录、沙箱判定共用 `taskObservers.ts`，避免观察路径漂移；
- **12/12 正确参考页**无失败、无 `indeterminate`；**24/24 HTML 故障**目标检查 `fail`；
  **3/3 缺证据负控**保持 `indeterminate`（P01 刻度歧义、主导色块、无证据页）；
- P01 在沙箱内同样检查 0、π/2、π 三相位，9 项全确定；
- 动画故障（HR06/HV04）按运行时错误与暂停性质判定，不要求逐帧像素相等；
- `13.33px` vs `14px` 只记在 `environment_differences`，不记为行为差异；9 份真实文档的
  **13px 仍是 `usability-font = fail`**，门槛未降低。

测试用 `frontend/public/m4c-harness.html` 提供同源空白页，避免加载应用/API 噪音；动态导入的
仍是产品自己的 `interactiveRuntime.ts`。

**验证**：e2e **95 passed / 27 skipped**；前端单元 124 文件 / 686 PASS；tsc PASS；
Ruff / diff-check PASS；**0 次模型调用**。

**CI**：`1af8ebe7` 的 run `41695015435` 中 classify / frontend / browser 已 green，backend
仍在运行；本片新 HEAD 需重新跑完整门禁后才能宣称全绿。

**唯一下一片**：等待本片精确 HEAD 全绿。三项前置满足后，建议按 **12 题各一次首次生成**、
固定模型版本/预算档/随机性做小规模评测；调用次数、单次上限和总预算另行由用户授权。

### 2026-11-04 后续片：P01 三相位 + 真实沙箱 + 通用可用性

按评审裁定完成的离线收口：

1. **P01 三相位**：冻结题补齐 0、π/2、π 三个相位的独立画面观测与声明一致性检查；数值判据
   读取 `observed`，不再由页面自报。新增负控：半幅画面、π 处错误、两套对称刻度（歧义）、
   主导色块过大（不是运动标记）——后两者返回 `indeterminate`。P01 参考页 9 项检查全部确定。
2. **真实沙箱等价性**：`sandboxParity.spec.ts` 用 `makeInteractiveDocument` → 外层 sandbox
   iframe → 内层隔离 iframe 跑 12 参考页 + 24 故障 + 1 状态页，共 **39 case**。行为差异 **0**；
   37 例 `same`，2 例动画画布未做像素比较，1 例仅环境字号差异（explorer 13.33 vs 14）。
3. **通用可用性**：`judgeUsability` 对每份文档统一检查字号 ≥14px、控件 ≥40px、无横向溢出。
   9 份真实文档全部因 **13px** 触发 `usability-font = fail`，不再漏报。
4. **跨领域调查**：`tools/interactive_replay_survey.py` 扫描 **214 个 SQLite 库**，按内容去重
   得到 **9 份真实文档**：J01 4、P01 相关 1（A=40px）、库存 4；**没有** A02/D01/M02/N01 等
   其他冻结题的真实样本。样本缺口如实保留，未用参考 HTML 冒充模型成绩。
5. **证据可追溯**：重放报告 schema `m4c-replay-report-v3`，每例保存 `source_sha256`、截图、
   操作步骤、各阶段 `declared`/`observed`/标记/刻度；沙箱报告同样保存源码哈希、步骤、
   两侧证据与截图。

**结果**：9 份真实文档 0 运行错误；J01 4 份任务检查自动判定率仍为 **19/20 = 95%**（r3 箭头
缺陷仍被检出）；通用字号门禁 9/9 失败（13px）。**0 次模型调用**。

证据：`D:/study-agent-validation/m4c-real-doc-survey-20261104/survey.json`、
`D:/study-agent-validation/m4c-real-docs-20261104/`、
`D:/study-agent-validation/m4c-sandbox-parity-20261104/parity.json`。

**验证**：e2e **94 passed / 26 skipped**；桌面观察器 54 项；前端单元 124 文件 / 686 PASS；
tsc PASS；Ruff / diff-check PASS。无后端/schema 改动，不触发 L2/L3。

**CI**：上一精确 HEAD `7e66e711` 的 run `41688484234` **5/5 全绿**（classify/frontend/backend/
browser/test）。本片新 HEAD 需重新跑完整门禁后才能宣称全绿。

**唯一下一片**：等待本片精确 HEAD 的远端门禁；三项前置（精确 HEAD 全绿、真实沙箱通过、
P01 三相位判据完整）满足后，才讨论受预算限制的真实生成实验（需单独授权）。

### 2026-11-04 后续片：M4-C Canvas 像素→坐标

在同一分支继续。观察器现在从画布像素里提取两类证据：主导饱和色区域的质心作为标记位置，
围绕静止位置对称的高竖线作为振幅刻度；`adapters.ts` 的 `positionFromCanvas` 用“刻度跨度 =
页面声明振幅”把像素位移换算成任务单位。页面声明 2 但标记只到一半时 `evidence-consistent`
判 `fail`；没有振幅刻度时仍 `indeterminate`。

参考矩阵随之收口：P01 使用确定性的相位页（相位滑块、播放/暂停、振幅刻度），J01 改为
共享/重新指向两阶段页；矩阵现在断言 **0 个 `indeterminate`**，12/12 参考页的全部检查可判定。
同时修正 J01 参考适配器的语义：从“箭头条数”改为“箭头目标对象编号”，并把 picture-lies
参考页改成“文字说 2、箭头仍指向对象 1”，使反例真正验证编号而不是条数。

**验证**：e2e **85 passed / 25 skipped**（桌面观察器 50 项含 12 题矩阵 + 24 故障 + 5 个新增
Canvas 测试；手机 26 项；语义定位 8；真实重放 1）；前端单元 124 文件 / 686 PASS；tsc PASS；
重放报告仍为 **19/20 = 95%**，r3 箭头缺陷仍被检出。无后端/schema 改动，不触发 L2/L3。
0 次模型调用。

**边界**：像素映射只处理“单标记 + 对称振幅刻度”的画布；真实弹簧文档 A=40px 仍不按 P01
判定，只测播放/暂停。固定题集的真实生成评测仍需单独费用授权。

**唯一下一片**：把语义定位/画布映射扩展到更多真实文档族，或在授权后做固定题集真实生成评测。

### 2026-11-04 后续片：M4-C 真实文档语义定位

在同一分支继续。新增 `frontend/e2e/acceptance/semantic.ts`：按钮文字驱动步骤、节点标签识别
变量/对象、箭头端点与包围盒几何确定指向关系；`semanticFixtures.ts` + `semantic.spec.ts` 用
SVG 节点、正确 HTML 节点、缺 `position` 的 HTML 节点三种布局做确定性回归。
`replay.spec.ts` 改为“只有确实是冻结题实例的文档才按题判定”。

**结果**（证据 `D:/study-agent-validation/m4c-replay-20261104/report.json`，schema v2）：
7 份真实文档 0 运行错误、最小字号 13px、0 溢出；4 份 `cache-ref-canvas` 按 J01 判定，
任务检查自动判定率 **19/20 = 95%**（上一版 5/25 = 20%）。r1/r2/r4 五项全确定通过；
r3 的 `.obj` 缺 `position:absolute`，箭头终点距目标 119.3px，被判 fail，独立一致性保持
`indeterminate`——与用户 r4 提示描述的缺陷一致；该缺陷是真实文档自带的，不是注入。

**映射修正**：`spring_phase_lab` 不再按 P01 判定。它同公式但 A=40px，冻结 P01 要求 π/2 时
位置为 2；按 P01 判会把它变成假失败。只测通用行为：播放后画布变化、暂停后不变，均 pass。
2 份库存实验不是冻结题实例，只测通用层。

**验证**：e2e **79 passed / 25 skipped**（12 题矩阵 + 24 HTML 故障 + 4 语义定位 × 2 viewport +
1 真实重放）；前端单元 124 文件 / 686 PASS；tsc PASS。无后端/schema 改动，不触发 L2/L3。
0 次模型调用。重放测试在未设置 `M4C_REPLAY_DIR` 时于测试体内跳过，不在模块加载时读取
`index.json`——上一版在常规 e2e 中触发了 `ENOENT: index.json`，已修复。

**唯一下一片**：P01 的 Canvas 像素→坐标映射（当前只证明“变化/不变”），或把语义定位扩展到
更多真实文档族；固定题集的真实生成评测仍需单独费用授权。

### 2026-11-04 后续片：M4-C 离线重放基线

在 M4-C 分支 `codex/m4c-acceptance-core-20261104` 继续。新增
`tools/interactive_replay_export.py`（从 runtime.db 导出真实交互文档，附 `window.studyUI` 桥接
桩）与 `frontend/e2e/acceptance/replay.spec.ts`（逐份运行、采集、判定、写报告）。
用已保存会话导出 **7 份真实界面**（4 份 `cache-ref-canvas` 映射 J01、1 份 `spring_phase_lab`
映射 P01、2 份库存实验无冻结题目），证据在 `D:/study-agent-validation/m4c-replay-20261104/`。

**结果**：7/7 无运行错误；最小字号 13px；0 横向溢出；任务检查自动判定率 **5/25 = 20%**
（只有运行层可确定，任务语义全部 `indeterminate`，未被算作通过或失败）。无模型调用。

**解读**：真实页面没有参考页的结构化证据属性，判定器正确地拒绝下结论；要把判定率提高，
需要语义定位（按标题、文本、控件、几何识别对象与数值），而不是依赖测试属性。13px 字号低于
验收规则的 14px，但 J01/P01 无字号检查，因此未计失败——这是产品事实，记录不改规格。

**唯一下一片**：语义定位适配器（先用这 7 份真实文档验证能定位多少对象/数值），提高自动判定
覆盖率；之后才谈固定题集的真实生成评测（需单独授权）。

### 2026-11-04 后续片：M4-C2c HTML 级故障整链

在 M4-C 分支 `codex/m4c-acceptance-core-20261104` 继续，未改动其他分支。新增
`frontend/e2e/acceptance/htmlFaults.ts`：24 个故障直接注入真实参考 HTML（运行 8、状态 8、
视觉/可用性 8），走“加载页面 → 采集 → 判定”整链，断言目标检查失败。桌面 **35 项**
（11 观察器 + 24 故障）通过；手机跑 11 项观察器、24 项故障按设计跳过，合计
**46 passed / 24 skipped**。

**覆盖边界**：参考实现只有 J01、M01、P01（另有 M02/A02 可用性页），24 个故障集中在这几个
任务，不是“12 题 × 24 故障”的完整矩阵；其余 9 题缺参考实现与适配器，真实模型输出只能
`indeterminate`，不得算通过。Canvas 仍只证明“变了/没变”，未做像素到坐标的数学映射。

**静态证据**：前端单元 **124 文件 / 686 PASS**；e2e **70 passed / 24 skipped**（含 12 题参考
矩阵与 24 个 HTML 级故障）；tsc 与构建 PASS。无后端/schema 改动，不触发 L2/L3。
**0 次模型调用**。

**唯一下一片**：把 24 个 HTML 级故障扩展到全部 12 题，并用已保存的真实回答离线重放，
量首次成功率与自动判定覆盖率；真实生成评测需单独授权。

### 2026-11-04 后续片：M4-C2b Canvas 实际画面采集

在 M4-C 分支 `codex/m4c-acceptance-core-20261104` 继续，未改动其他分支。观察器新增
Canvas 采样：每个画布取 8×8 网格 RGBA；被污染或读取失败时**不返回像素**，判定转为
`indeterminate`，不会被当成“没有错误”。新增 4 份 Canvas 参考页（动画、暂停失灵、输入联动、
画布冻结），浏览器检查从 7 项增至 **11 项**，桌面/手机 **22 PASS**。

真实页面已验证：动画画布前后不同、暂停后相同；暂停失灵的页面 `canvas-same` 失败；输入联动的
画布会变化、画布冻结的页面 `canvas-differs` 失败。Canvas 仍只证明“变了 / 没变”，尚未把像素
映射回坐标验证 `x=2sin(φ)` 这类数学关系；只有 J01 一个任务适配器。

**静态证据**：前端单元 **124 文件 / 686 PASS**；观察器 11 项 × 2 视口 **22 PASS**；tsc 与构建
PASS。无后端/schema 改动，不触发 L2/L3。**0 次模型调用**。

**唯一下一片**：其余 11 题适配器与 12 份参考实现 + 24 个 HTML 级故障（C2c），再离线重放
已保存回答建立基线；真实生成评测需单独授权。

### 2026-11-04 后续片：M4-C2a 真实页面观察器

用户要求先做“能独立证明界面正确”的观察器，不接自动修复、不发起付费生成。本片在 M4-C 判定
分支 `codex/m4c-acceptance-core-20261104`（`2d25b699`）上继续，未改动其他分支。

**结果（P2，owner=verification）**：新增 `frontend/e2e/acceptance/`：真实 Chromium 观察器
（运行错误、可见文字、页面声明数值、SVG 用户坐标、字号、控件尺寸、横向溢出）、J01 任务适配器
（从箭头拓扑独立数出对象数）、6 份参考页与 7 项浏览器检查，桌面与手机两个视口各跑一遍。
正确页的运行/箭头/一致性检查通过；箭头错位在几何层失败；文字正确但图少一条箭头时，声明检查
通过而 `cross-check` 失败；运行错误被捕获；无证据页返回 `indeterminate`；12px 字号与横向溢出
分别被可用性检查发现。真实页面结果，不是手写观察。

**边界（不可夸大）**：只有 J01 一个适配器；参考页用 `data-acceptance-declared` 提供“声明值”，
真实模型输出没有该属性，需后续用语义/几何启发式定位，定位不到必须 `indeterminate`。
Canvas 采集、其余 11 题适配器、12 份参考实现与 24 个 HTML 级故障仍属下一片。

**静态证据**：前端完整 **124 文件 / 686 PASS**；观察器 7 项 × 桌面/手机 **14 PASS**；tsc 与
构建 PASS。本片为前端与 e2e 新增，无后端/schema 改动，不触发 L2/L3。**0 次模型调用**。

**全量 pytest**：已确认上一轮 20 个失败中 18 个为并发进程干扰、2 个为“脏工作树”守卫，干净
head 重跑全部通过；新的全量在 `f04ea68d` 启动，后端代码与当前 head 相同（`src tests` 无差异），
结果出来单独汇报。

**唯一下一片**：Canvas/SVG 全量采集与其余 11 题适配器，然后 12 份参考实现 + 24 个 HTML 级故障；
真实生成评测需单独授权。

### 2026-11-04 后续片：M4-C 冻结题集与离线判定核心

用户冻结 M4-C 范围为 12 题 / 8 领域，并要求先建离线检测器、不发起付费生成。本片从状态快照
分支 `codex/interactive-state-snapshots-20261103`（`2ca73a1c`）新建栈式分支
`codex/m4c-acceptance-core-20261104`。main、#338、预算分支、#339、#340、#341 均未改动。

**结果（P2，owner=verification）**：新增 `frontend/src/acceptance/`：12 题冻结规格、四层判定器
（运行/状态/几何/可用性）、24 个已知故障（运行 8、状态 8、几何与可用性 8）与 40 项断言。
判定器对 12 题正确样本全部 pass 且无 `indeterminate`；24 个故障各自只在目标检查上 fail，
不牵连其它检查；空观察被判为 `indeterminate` 而不是 pass。题目与容差记录在
[M4-C 验收](M4C_ACCEPTANCE.md)。

**边界（不可夸大）**：故障样本作用在“观察”上，不是渲染后的 HTML；浏览器抽取器与 12 份参考
实现尚未实现。因此本片只证明**判定逻辑**能区分正确/错误/证据不足，不证明已能判断真实模型输出。

**审查修复（用户复核）**：①所有判定数字先过 `Number.isFinite`：缺失→`indeterminate`，
读到 `NaN`/`Infinity`/负包围盒→`fail`；②每题新增 `cross-check`，页面声明值必须与检查器
独立观测值一致，只有文字正确而画布/几何无法核对时返回 `indeterminate`，不再把模型自报当证据；
③明确 `canvas-differs` 只证明“发生了预期变化”，不证明变化符合数学关系，后者缺证据即
`indeterminate`。

**静态证据**：前端完整 **124 文件 / 686 PASS**（判定器 45 项断言，含 5 项非有限值/证据来源负控），
tsc 与构建 PASS。本片为纯前端新增模块，无后端、schema 或持久化改动，不触发 L2/L3。
**0 次模型调用**，账本仍 ¥8.63/¥30。

**唯一下一片**：浏览器观察器 + 12 份参考实现 + 24 个 HTML 级故障，验证“抽取 + 判定”整链；
之后用已保存真实回答离线重放建立基线；真实生成评测需单独授权。

### 2026-11-04 后续片：交互状态快照与显式恢复

用户选定“新增快照表 + 显式按钮恢复”。本片从源码恢复分支
`codex/interactive-version-restore-20261103`（`6c64617a`）新建栈式分支
`codex/interactive-state-snapshots-20261103`。main、#338、预算分支、#339 与 #340 均未改动。

**结果（P2，owner=orchestration/persistence + UI）**：新增迁移 31
`interactive_state_snapshots`，按 `(thread_id, component_id, revision)` 保存各版本的状态快照
（revision、state_json、updated_at），不存源码。宿主新增
`PUT/GET /sessions/{id}/interactive-state[/{component_id}?revision=N]`，只接受 JSON 对象、
序列化 ≤4000 字符、component id 与前端协议一致、revision 1–999；未知会话与无快照明确 404。
前端在用户操作后（跳过界面首次发布的初始状态）防抖保存；卡片在**快照 revision 与当前卡片
一致**时提供「恢复上次状态」，不一致时明确拒绝并说明原因。生成界面通过新增的
`window.studyUI.onRestore(handler)` 接收快照；未实现该钩子的版本会得到确定性提示，
不静默失败。恢复要等界面回报状态才确认。未做自动恢复、操作日志或跨版本状态迁移。

**提交**：实现与测试提交随后记录；文档提交在末。推送后以源码恢复分支为基线建立草稿 PR。

**审查修复（用户复核）**：①旧逻辑只在“值不等于初始值”时保存，用户改成 12 再改回 5 会在
800ms 后仍写入 12；现改为“首次发布=初始状态，之后每次发布都是操作”，并取消未到期保存、
以最新值重新计时。②重置只重建 iframe，不清待保存任务与初始标记；现在重置会取消保存、
重置标记并递增代际号，旧代际的迟到保存被丢弃。③快照键从 `(thread, component)` 改为
`(thread, component, revision)`：操作旧版本不再覆盖新版本进度，读取时必须指明 revision。
④恢复增加回执：界面回报一次状态才显示“已恢复”，超时或未实现钩子都明确提示。
⑤写入串行化：同一时刻只有一个保存请求在途，更新的值排队等待；旧请求晚到也不能覆盖
更新的值（不再只依赖定时器取消）。

**静态证据**：`tests/test_interactive_state.py` **12 PASS**（保存/读取、各版本互不覆盖、
跨会话隔离、超限、非对象、路由 404/422/指定版本）；`tests/test_spend_settlement.py` 的 schema
断言改为跟随 `SCHEMA_VERSION`，**53 PASS**；schema 相关影响集 **139 PASS**；前端完整
**123 文件 / 642 PASS**，tsc 与构建 PASS；Ruff PASS；mypy **118/128，新增 0**。迁移 31 属
持久化 schema 变更：本机全量 6925 项 pytest 单机约 3 小时，本片未在本地跑完；全量证据以
PR 的 backend 作业在精确 head 上的 pytest 为准，CI 未绿前不得称为已交付。

**动态证据**：**0 次模型调用**，账本仍 ¥8.63/¥30。未做真实刷新后恢复的浏览器端到端。

**边界**：快照不解释操作过程；不同 revision 的状态不能迁移；模型输出的界面若未实现
`onRestore`，只能从初始状态重来（这是显式失败，不是假装恢复成功）。

**唯一下一片**：M4-C 自动验收闭环。题集已冻结为 **12 题 / 8 领域**（J01、J02、A01、A02、
D01、D02、C01、M01、M02、P01、S01、N01），判据分运行、数学/状态、几何/视觉、响应四层；
先构建离线检测器与 24 个故障样本，**不做付费生成、不开放自动修复**。真实评测的调用次数与
账本上限需另行授权。Three.js/3D、联网数据分析暂不进入第一版。

### 2026-11-03 后续片：从保存的旧版本恢复源码

用户选定“旧版本卡片上的「以此版本为基础继续」”，并要求确定性的版本管理：源码定位、权限、
状态和提交顺序交给程序。本片从历史压缩分支
`codex/interactive-history-compression-20261103`（`b7a0629e`）新建栈式分支
`codex/interactive-version-restore-20261103`，工作树
`D:/study-agent-validation/intelligent-ui-budget-lifecycle-20261103`。main、#338、预算分支和
#339 均未改动。

**结果（P2，owner=orchestration/versioning + UI）**：新增 `src/interactive_restore.py`。
前端在每张生成界面上提供「以此版本为基础继续」，只提交 `id + revision`（一次性，发送/取消/
切换会话即清除，不进入对话正文）。后端在该会话**所有已完成轮次**中定位该版本，校验协议字段、
会话归属与源码唯一性；命中后把源码作为有界上下文块注入本轮，并令派生版本 =
该 id 的最大 revision + 1（V1→V4，不会与已有 V2/V3 冲突）。失败分 `not_found` / `conflict` /
`revision_exhausted`：模型收到“不得凭摘要、记忆或其它版本重建”的明确指令，前端同时按
`route.interactive_restore` 显示确定性错误，不依赖模型自觉。派生关系写入现有
`route_snapshot`，不新增表、不改协议、不改已保存回答。

**提交**：`9e4ca96d` 实现、前后端测试与命名 L1；随后仅文档提交。推送后以历史压缩分支
`codex/interactive-history-compression-20261103` 为基线建立草稿 PR；远端门禁结果以该 PR 的
精确 head 为准，不以本文档代替。

**静态证据**：`tests/test_interactive_restore.py` **23 PASS**（跨全部轮次定位、V1→V4 派生、
同 id 同 revision 冲突、副本去重、未完成轮次不算、跨会话不可见、版本耗尽、失败块禁止重建、
记录不含源码、请求体只有身份）；服务级回归证明 V1 源码确实进入提供商消息、V2/V3 不在、
`expected_new_revision=4`、`route.interactive_restore` 记录正确且存储回答未被改写。
影响集（restore + history + chat_service + turn_context + attachment binding + lifecycle e2e +
stream cancellation + API + routes + stage policy）**189 PASS**；前端完整 **123 文件 / 634 PASS**，
tsc 与构建 PASS；Ruff PASS；mypy **118/128，新增 0**。

**动态证据**：**0 次模型调用**，共享账本仍为 ¥8.63/¥30。本片只证明定位、注入、派生与失败反馈的
程序行为；没有验证模型拿到旧源码后的实际修改质量，也没有真实浏览器端到端点击。

**边界**：未做局部 HTML 补丁、跨会话恢复、探索状态持久化或“从旧版派生”的数据库级关系表；
`route_snapshot` 记录的是本轮意图与派生目标，不是对模型输出的强制改写（模型若输错 revision，
仍由协议校验和后续冲突检测暴露）。

**集成顺序（用户已定）**：#338 → 预算分支 → #339 → 本片。每层仍各自过门禁；若前层使用
Squash Merge，重放后续分支时必须核对差异，避免把已合并内容再次带入 PR。

**唯一下一片**：旧版本恢复的真实端到端与修改质量验证（可用现有付费预算，需再次显式授权），
随后再做“只修改局部代码”。

### 2026-11-03 后续片：模型输入中的旧界面版本压缩

用户要求下一片只做“完整历史不变 → 模型输入按版本压缩 → 当前源码与状态保真 → 验证成本和修改正确率”，
并明确**不**同时引入局部代码补丁或新 UI 协议。本片从预算/生命周期分支
`codex/intelligent-ui-budget-lifecycle-20261103`（`5d39ce3b`）新建栈式分支
`codex/interactive-history-compression-20261103`，工作树
`D:/study-agent-validation/intelligent-ui-budget-lifecycle-20261103`。原 #338 未改动，
预算分支未被改写，main 未变。

**结果（P2，owner=orchestration/context）**：新增独立模块 `src/interactive_history.py`，
并在 `build_messages` 拼接历史前调用一次，普通与策略聊天共用入口。只处理助手消息中完整闭合、
字段与前端协议一致的 `type=interactive` 块；同一 id 中**早于**目标 revision 的版本换成
“id + revision + title + summary + 源码未提供”的摘要，目标版本与**更新的**版本源码都逐字保留；
正文、用户原话、其它组件、未闭合或解析失败的块一律原样保留。目标组件由
“继续探索「标题」（版本 N）”或显式 id 决定，且必须唯一：多组件、同标题不同 id、
指定版本不在窗口内时都不压缩，所以不会把“最后一段 HTML”误当成当前界面。普通代码围栏里的
`study-ui` 示例按文档跳过，不当成运行中的组件。摘要不推测旧版修复了什么；需要旧版源码时
摘要明确写出应从已保存会话恢复。解析兼容 CRLF/LF 但不改写存储；摘要比源码还长时放弃替换；
异常时返回原历史。未声明 `【自由交互界面 v1】` 的请求不压缩。

**提交**：`387309bd` 实现、测试与命名 L1；`d0028bf5` 文档；其后的审查修复提交见
`git log`。未推送、无 PR/CI（修复后按审阅意见另立基线）。

**静态证据**：新增 `tests/test_interactive_history.py` **31 PASS**（含 CRLF、坏 JSON、未闭合围栏、
嵌套普通代码围栏、两个 id、同标题同版本不同 id、按钮指定旧版本（更新的版本保留）、幂等、
摘要过大回退、只改副本不碰存储、前端会拒绝的字段与超长块），并加一条服务级回归
证明提供商实际收到的就是压缩后的历史（旧版 HTML 不在、当前版在、用户原话在）；命名 L1
`interactive_history_compression` 影响集 **144 PASS**；Ruff PASS；mypy
**118/128，新增 0**（`config/mypy_baseline.json` 门禁通过）。按 AGENTS.md §4，无共享核心模型、
持久化 schema 或发布权改动，本片不触发 L2/L3。

**动态证据（本片无模型调用）**：离线工具 `tools/interactive_history_report.py` 读取已保存真实会话，
不读真实响应也不发起请求。`intelligent-ui-20261103/runtime.db` 中
`chat_946d4b0a…`（同一 `cache-ref-canvas` 的 v1–v4）：第 4 轮 24514→10278 字符，第 3 轮 15522→8562；
两次可压缩轮次合计 40036→18840（**−52.9%**），用户消息逐字一致、当前源码逐字存在。
另一真实会话 `chat_0f6b490c…` 同对话出现两个 id，工具如实报告无明确选择并**不压缩**。
报告在 `D:/study-agent-validation/interactive-history-stage1-20261103/`。这是成本与保真对照，
**不是**修改成功率；小规模真实调用对比尚未执行，共享账本未新增预留（仍 ¥8.63/¥30）。

**审查修复**：用户复核指出三处边界并已修：①重新打开 V2 时不再把 V3 当作“被 V2 替代”而压缩，
只有 `revision < 目标` 才删源码；②同标题不同 id（或同版本不同 id）一律判为
`ambiguous_target`/`ambiguous_multiple_ids`，不再用 `max()` 猜一个；③解析改为按围栏块推进，
普通代码围栏内的 `study-ui` 示例不再被当成运行组件；`_valid_block` 与前端
`parseAnswerCard` 对齐（id 正则与 64、revision 1–999、summary ≤1200、html ≤60000、整块 ≤96000）。
原断言“V3 源码会消失”的测试已按正确语义改写，而不是让生产代码迁就它。

**边界**：两个真实会话、两次可压缩轮次只是初始样本，不能据此声称生成质量提高；压缩按字符和
heuristic token 计量，不是提供商账单或真实 tokenizer 计数；未实现按需恢复旧版源码、局部补丁、
刷新恢复探索状态或后台自动验证。

**唯一下一片**：按需从已保存会话记录恢复指定旧版本源码，使“回到 V1 再改”不依赖模型记忆；
之后再做“只修改局部代码而不重新生成整个 HTML”。仍不合并 main、不改 #338。

### 2026-11-03 后续片：按任务分配 UI 预算与生成结束原因

用户提供 #338 底层复核并要求后续开发。已核实 #338 是 draft/open，远端 head
`1b29e00f658771ea2a04bfffe19ff072fb7d6dfc`，main 为 `7d7b2109`，未合并。
本片从 #338 的明确提交新建工作树 `D:/study-agent-validation/intelligent-ui-budget-lifecycle-20261103`，
分支 `codex/intelligent-ui-budget-lifecycle-20261103`。不依赖其他窗口 WIP，不改变原桌面入口。
主实现提交 `91e03e33126a7330ca3d86fcec2b607bf87c944d`；最终代码提交
`5a2874e4cb2021274e889e9bb0d6ee3c373038f8` 补充直接探索、解释并制作及修复按钮的意图识别。
其后仅交接文档，文档提交后工作树干净。

**结果（P1/P2，owner=orchestration/UI）**：普通聊天保留 700/1100/1600；明确请求简单交互
3500、一般交互及现有界面修改 6000、多面板或较长源码替换 9000。当前系统能力是必要条件，
不再单凭能力标记提高预算。采用可测试的初始规则，不额外调用模型分类；每次调用仍通过原费用门。
模型正常结束、长度上限、提供商拒绝及未知结束原因随答案传输；异常链区分超时与连接失败，
用户取消沿用已有独立事件。结果写入现有 route_snapshot，不新增表或迁移。
前端区分“达到上限”与“模型结束但格式不完整”；继续/修复只写草稿。没有终止事件的 SSE EOF
不再被当成成功。CRLF 围栏兼容修复保留嵌套代码示例不可执行的边界。

**静态证据**：主实现命名 L1 `interactive_budget_lifecycle` **263 PASS**（108.40s），
最后补充“给我一个界面 / 让我逐行执行 / 解释并制作 / 生成完整版本”意图后，预算及三种调用通路影响集 **61 PASS**。
前端完整 **123 文件 / 630 PASS**、tsc+Vite 构建 PASS；桌面/手机 CLI Playwright **18 PASS**，
含真实生成文档的调参、重置与真实 length 回执的手动继续；Ruff/diff-check PASS，mypy **118/128，新增0**。
初次 L1 262 PASS/1 FAIL 指出普通无 UI 渠道多了一条末尾系统提示，已将该提示限制在声明能力的请求，
随后 263 PASS。首轮浏览器 6 PASS/4 FAIL 源于证据文件被 Windows 写为 CRLF，揭示了围栏开头
正则不兼容；原响应 JSON 保留，修复解析后 16 PASS，新增真实长度停止案例再 2 PASS。
本片为 L0/L1 的局部预算与完成原因传输改动，无共享核心模型/持久化 schema/发布权切换，无 L2/L3。

**动态证据**：真实 DeepSeek + FastAPI（TestClient），普通/简单/多面板预算分别为 700/3500/9000，
全部 stop，耗时 4.94/6.09/8.80s；故意要求超长普通说明在 6.76s 返回 length，SSE 与持久化一致。
生成文档原样在 Chromium 桌面/手机回放。并非本片重新执行桌面启动，也没有 ChatGPT 对照。
沿用用户授权 ¥30、`D:/study-agent-validation/live-20261102/spend.db`、实验 `study-agent-live-20261102`；
本片4次调用预留 **¥1.578062**，全实验23次，累计 **¥8.630826**，余 **¥21.369174**。
这是保守预留，不是账单。请求、响应、SSE、费用快照、截图在 `D:/study-agent-validation/ui-lifecycle-evidence/`。

本片本地提交，未推送、无本片 PR/CI/合并资格；原 #338 不变。档位和意图规则只是初始策略，
少量实测不证明所有问法/模型最优。未改变 SDK 超时、研究截止时间或 iframe 就绪时限。
**唯一下一片**：压缩模型输入中的旧 UI 版本，保留当前版本源码、必要修改约束与探索状态，
用户仍能查看所有历史原文；随后处理可恢复状态与版本迁移。详见 [设计记录](INTERACTIVE_ANSWER_DESIGN.md)。

### 2026-11-03 当前片：自由生成的智能 UI

用户确认「优先自由生成与交互探索」，后续开发从 DeepSeek 收尾后的**本地 main**
`7d7b210937b96bc1769567d7d930651a8daa0bdf` 开始；远端 main
本次 fetch 仍为 `abf40b494272c547f1fe29ca15edd13c4c470e7b`。
工作树 `D:/study-agent-validation/experience-retrieval-20261101`，新分支
`codex/intelligent-ui-20261103`，实现提交 `685218e57cb309ed128f7e9ea653ff0167a4ecea`。
显示兼容修订 `9468f67c565f7a4de5466618dbd09f633111acd6` 使用 React 实例标识，
读取旧界面不再依赖安全上下文专属的 UUID API。
跨领域样例及提示修订 `7ca0a074a01936aba38df31374bd3c7ea2edc257`；启动修复及本轮代码 head
`371a9d66803537dc5dd963c76fb87bf24d04d27a`。后续交接提交仅更新文档。
原桌面源码工作树的未跟踪资料未改动。当前本地 main 未吸收本片，无 push/PR/远端 CI。

**结果**：回答中新增自由 `interactive` 文档，模型可生成 HTML/CSS/JS、SVG、Canvas；
完整块才运行，可展开/重置/停止，运行失败及未完成有修复入口，文字始终可读。
当前参数经用户点击追加到草稿；追问用现有历史生成同 id 新版，旧回答仍可操作。
不是新的一组学科模板，不新增服务端执行器、数据表、模型路由或研究发布权。
双层 opaque-origin iframe + CSP 隔离，浏览器证明父页面数据、fetch、弹窗、外部自身导航
被阻止；不把模型输出或操作状态提升为可信研究证据。详情：[设计及验收边界](INTERACTIVE_ANSWER_DESIGN.md)。

**真实失败与修复**：第一次生成在 700 tokens 处截断。已声明自由交互能力的当前 system
上下文使用至少 6000 tokens 的回答上限，同步/流式/异步流式统一；未声明能力的渠道仍用
原预算。无自动续写、额外调用，原共享支出门按新请求上限预留。动态运行器还曾漏传
前端本来会携带的聊天历史，修正后验证连续版本；失败样本与费用均保留。

**验证**：P1 owner=orchestration/output-budget；P2 owner=UI/prompt。Static Loop：
前端完整 **123 文件 / 622 PASS**，构建含 tsc PASS，CLI Playwright **46 PASS**
（桌面/手机，包括库存追问、代码执行故事与 Canvas 的八项真实回答重放）。
后端命名 `intelligent_ui` L1 **163 PASS**，
另有命名 `desktop_docker_startup` L1 **41 PASS**（启动/管理脚本 31、stage policy 10），
Ruff、diff-check PASS，mypy **118/128，新增 0**。后端第一次 44 项 401 是本机 `.env`
令牌使测试 fixture 不注入 header；改为明确 fake token/credentials 的隔离测试进程后通过，
没有改动生产鉴权或放宽测试断言。未运行 L2/L3，未授予合并或全浏览器发布资格。

**限定动态样例 PASS**：真实 FastAPI `/chat` 路由 + DeepSeek 提供商，回答在浏览器原样重放。
库存第一版锁定 5→12、可售 32→25，第二版保留参数后支付，旧版本仍可操作。
代码故事验证执行前无对象、共享引用改值、重新指向后两对象独立、前进/回退/重置；最终文字
至少 14px，SVG 箭头端点落在对应 HTML 对象框上。Canvas 验证 x=A*sin(phase)、实际像素变化、
播放/暂停/重置、减少动态效果默认暂停。真实失败包括初始对象画早了、SVG 缩字、HTML 对象框
定位遗漏；均保留原文及可复现断言，最终代码样例经历三轮追问修订，不能声称一次生成可靠率已提高。
不是模拟提供商；付费传输使用 TestClient，桌面启动另验，未跑二者同进程的付费链路或 ChatGPT 对照。
默认离线 CI 不读真实响应，也不发起模型调用。
复用 `D:/study-agent-validation/live-20261102/spend.db`、实验 `study-agent-live-20261102`
及用户原先授权 **¥30 累计上限**；本片 9 次调用预留 **¥4.453904**，全实验 19 次，
累计 **¥7.052764**，余 **¥22.947236**。均为保守预留，不是提供商账单结算。
证据、真实请求/响应、失败原文及截图位于 `D:/study-agent-validation/intelligent-ui-20261103/`。

代码提交后只余本片设计/交接文档；最终文档提交后应干净。桌面入口仍指向此工作树，
15:46 重新通过前端 5174、后端 8001、Docker/SearXNG 8080、真实搜索及 `studyctl ui --json`
的 `auth=ok`。冷启动时 PS 5.1 捕获 native stderr 提前退出，已加实进程回归并修复探测局部策略，
不改变真实操作失败策略。另有本机 Docker Secrets Engine 陈旧 socket + EFS 父目录问题：
只保留移动故障 socket 目录到 `C:/StudyAgentDockerRecovery-20261103/docker-secrets-engine-154308`，
未删除镜像/容器/卷。CLI 宿主为 PS 7，启动 PS 5 子进程需使用其自己的系统 PSModulePath；
未因此修改生产脚本。详见设计记录。此为本地开发分支运行，不是 main 合并或远端发布。
**唯一下一片**：增加数据分析交互的固定任务集，分别记录首轮成功率与追问修复率，
优先处理生成内容语义/几何错误；当前少量成功样例不能代表所有任务可靠。

### 2026-11-02 用户选定的体验/检索重构（独立本地分支）

工作树 `D:/study-agent-validation/experience-retrieval-20261101`，分支
`codex/experience-retrieval-20261101`，基线 main `abf40b49`。
搜索提交 `d61b108c` 将三套提供商调度合一，修复域名过滤阻断回退与 URL 大小写误去重；
CLI 提交 `16b94b95` 增加现有测试集的 JSON 发现入口。
检索影响集 230 PASS，CLI 445 PASS/1 SKIP，Ruff/mypy 无新增错误/diff-check PASS。
用户选择 **A+C**，生产 UI 接线保存于 `89f32288391dbb12f038362ccd081a6009863776`：
轻侧栏、居中对话、右侧资料阅读、88px/72px 角色头像；延迟内容增长跟随与手动阅读保位。
huashu-design 的内容优先/图形选择/单位来源准则已进入现有聊天临时上下文，
条形图显示完整标签与数值，可切折线/数据表，旧消息兼容。
前端全量 121 文件/610 PASS；CLI Playwright 24 PASS（桌面/手机，37.2 秒）；
后端上下文/ChatService/发布边界 58 PASS；构建含 tsc、Ruff、diff-check PASS。
桌面/375px 截图视觉 PASS，320px 无页面横向溢出；无真实模型或设备资格。
代码提交后工作树干净；此后的改动仅为本交接记录，最终 HEAD 由 Git 读取。
后续按用户四点反馈完成角色与教学片：`df6d93d1` 接入三角色的具体语言纹理、
共用生动教学/第一性原理指南，修复费曼直答退出及“不要直接回答”误判；
`bc867a93` 将角色入口改成可见名称，角色面板展示头像与风格，保留草稿和手动选择。
该片增量基线 `8b426b24`；`teaching_voice` CLI 212 PASS（85.12 秒），前端 610 PASS，
后续设置文案调整关联 97 PASS，浏览器 32 PASS，构建/Ruff/mypy 124/128 新增 0。
详见 [角色与教学交接](TEACHING_EXPERIENCE.md)。UI 静态视觉 PASS；
真实模型的角色辨识度、自然语言与教学效果仍未做动态比较，不能据此宣称质量提升。
用户随后修正三种方法的思想定义，增量基线 `63102dfc113953e1d0eea4bdae0b333500b1dac6`，
实现提交 `aa3d27d8ade3a162ab609c9b3567e1406fa3a996`：第一性原理从基础重建推导、
苏格拉底引导自主发现、费曼重清晰与严谨，三者灵活协同；同步实际消息、模式文案与设置说明。
去掉互动配额、单一认知动作、费曼强制复述与苏格拉底问号数量判失败；明确等待/直答仍有效。
费曼不再凭长度/关键词推断掌握，复用当前输入的既有评价回执；学习证据及项目执行门保持。
P2 owner=orchestration-prompt/UI，Static Loop：CLI `teaching_voice` 231 PASS（88.11 秒），
最终自动模式文案/项目提示边界修订及补充负例后，直接影响集 124 PASS（43.76 秒）；
前端设置/教学标签 22 PASS，构建含 tsc、Ruff、mypy 118/128 新增 0、diff-check PASS。
运行 L0+L1；未改共享数据模型、存储格式或生产执行权，未运行 L2/L3。
以上为本地源码验证，CLI 回执标记 `uncommitted_source=true`，不能借用其旧 HEAD 声称精确提交 CI。
代码提交后仅余教学说明/交接修改；文档收口提交后应干净，最终 HEAD 由 Git 读取。
本地实现与验证见 [交付记录](EXPERIENCE_RETRIEVAL_REFACTOR.md)，
未 push/PR/merge，无本次付费动态运行或远端资格，原桌面工作区未改动。
**唯一下一片：将此本地分支作为集成候选，按各片提交边界准备增量 PR 评审与所需远端门禁。**
这段只记录本工作树，不能当成 main 已交付。

### 2026-11-03 桌面启动链修复 + 首次真实模型验收（同分支续接）

工作树同上，分支 `codex/experience-retrieval-20261101`，起始 HEAD
`e885c863d29bf8093d80e9709d87e0f631612dc6`；本轮改动未提交前现场已备份到
`D:/study-agent-validation/_wip-backup-20261102/`（patch + 三个未跟踪文件）。
用户授权的本轮真实调用上限为 **¥30 累计**，实际使用见下。

**P1 桌面启动链（此前从未跑通，三处真实缺陷）**
1. `tools/manage-searxng.ps1` 为 UTF-8 无 BOM 且含中文：Windows PowerShell 5.1 按 ANSI
   解析，实测 6 处语法错误（`Try 语句缺少 Catch 或 Finally`），Docker/SearXNG 编排整体失效。
   补 BOM 后 0 错误；新增测试要求含非 ASCII 的 `tools/*.ps1` 必须带 BOM。
2. 该 manager 只接受挂载本仓库 `settings.yml` 的容器，多检出场景直接把启动打成失败。
   改为“内容相同（SHA256）即复用”，内容不同仍拒绝；旧的路径断言同时弱化。
3. 启动器存在两个可观测缺陷：`-Install` 缺失时前端依赖检查会掩盖半装好的 `.venv`
   （已拆分 Python/前端安装门），以及日志用嵌套隐藏 PowerShell 中转导致可诊断性差。
   改为直接启动 `uvicorn` / `vite` 真实进程，回执 `started_process_ids` 记真实 PID，
   并新增 `tools/stop-study-agent.ps1`（按回执端口 + 进程指纹收敛，绝不触碰 Docker）。

实机验收（真实桌面入口 `C:\Users\Zhang\Desktop\study-agent-launcher.ps1`，默认端口 8001/5174）：
Docker 引擎 29.9.2 → 固定 digest SearXNG 健康 → 后端 `/health` → 前端标题校验 →
回执与 `logs/launcher/*.log` 落盘 → 重复启动零新增进程（幂等）→ 停止后端口全释放、
SearXNG 容器仍在运行。

**P3 首次真实模型验收（`tools/studyctl.py live check`，DeepSeek 官方端点）**
首两次运行为工具自身缺陷（`.ps1` 被当 Win32 程序执行 → WinError 193；spend 账本未
`initialize()`），均在模型调用前失败，**花费 ¥0**；修好后第三次为端口占用自检拦截（同样 ¥0）。
最终 `checks-20261102-235918.json`：**PASS 10/10**，10 次调用，`reserved=2,598,860 µ`，
即 **¥2.60 / ¥30，余 ¥27.40**。覆盖桌面+Docker、401 访问控制、三角色、费曼追问、
附件、SearXNG 检索、持久化。

**P1 附件真实缺陷（本轮唯一功能性修复）**
真实链路下模型回答“看不到任何附件内容”。根因：附件正文只经本地 RAG 检索进入提示，
`rag_enabled=false` 的普通轮次里 `attachment_material` 仅用于发布判定，从未进入模型上下文。
`chat_service.attachment_context_block()` 现把绑定附件的解码文本作为独立上下文块注入
（单附件 4000 字符、整块 12000 字符上限），基础与策略两条链路都调用。
修复后同一用例回答 “当前库存 37 件 / 锁定 5 件 / 可售 32 件”，`attachment_values` PASS。

**P2 冗余与视觉**
清理：死变量 `$rootQuoted/$pythonQuoted`、服务启动的 PowerShell 中转层、Python 安装与
前端 `node_modules` 的错误耦合；62 条被后续规则覆盖的 CSS 声明清零（随 A+C 接线一并提交）。
界面延续 Codex 风格的浅色中性化（`--content-width` 840、去绿色强调、去顶部重复元信息），
顶部栏只留标题与动作，任务契约改由 `WorkspaceActions` 单独承载。
两处旧测试仍在断言已删除的顶部元信息，已改为断言新契约（保持“不泄露原始会话 ID”）。

验证（L0+L1）：附件 43 PASS、聊天/策略/发布/教学影响集 157 PASS、启动与 SearXNG 及
CLI 34 PASS；前端 610/610 通过（含 `tsc -b` + vite build）、桌面/手机 Playwright 32/32；
Ruff 全绿、`git diff --check` 干净。**未运行 L2/L3，未 push/PR/merge。**
真实模型证据只证明“链路可跑通、附件可读、三角色风格可区分”，**不构成回答质量优于其他产品的结论**。

**下一执行片**：把本分支整理成可评审的增量 PR（先启动链、再附件、再 UI），并补齐
`Test-FrontendIdentity` 标题与语言不一致的独立 P2；桌面入口默认指向主仓库而非本工作树，
合并前不得用双击结果代表本分支能力。

### 2026-11-03 收尾：依赖预置、桌面入口、刻晴、本地合并 main

**依赖预置**：本工作树 `.venv` 首次安装被 `files.pythonhosted.org` 读超时（≈10 kB/s）拖死；
改用清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 约一分钟装完全部固定版本，
`requirements.txt` 一行未改。现在**无参数双击**即可启动，不再需要 `-PythonExecutable`。

**桌面入口**：`C:\Users\Zhang\Desktop\study-agent-launcher.ps1` 默认 `-ProjectRoot` 由
`$PSScriptRoot\study agent` 改为本工作树（备份 `study-agent-launcher.bak-20261103-001121.ps1`）；
另加 `C:\Users\Zhang\Desktop\Study Agent.cmd`——`.ps1` 双击默认是编辑而非运行，`.cmd` 才是真正可双击的入口。
令牌经 URL fragment 交给页面：fragment 不进服务器、不进 Referer，页面加载后立即 `replaceState` 抹掉。
内置浏览器与终端用 `tools\studyctl.py ui` 现算同一个地址并先探一次 `/sessions`；
默认打码（`#token=***`），`--show-token` 才输出完整地址，`--open` 在服务端会拒绝时直接 exit 4、不打开坏页面。

**刻晴同级优化**：`build_role_prompt` 本来就为每个角色选取「11. 语言纹理」，只有
`roles/keqing.md` 缺这一节，所以她的提示是四人中唯一没有具体措辞的。补入短句先落判断、
给依据的纹理与三条措辞参照，并把「收束」从唯一职能改为强项；角色说明改为
「直接清醒，砍到下一步」。`test_vivid_teaching` 的参数集补入 keqing，三种模式共 51 PASS。

**本地合并**：`git switch main` 后 `git merge --ff-only codex/experience-retrieval-20261101`，
本地 main 由 `65a58eac` 快进到 `d1bcfbb8`，工作树干净；合并后针对性影响集 96 PASS、
前端 610 PASS，并从桌面 `.cmd` 无参数复验启动成功。
**未 push、未开 PR、未跑远端 CI**：主线仍只在本地，远端 `origin/main` 仍是 `abf40b49`。

**工作树清理**：移除 `frontend/dist`、`playwright-report`、`test-results`、`tsconfig.tsbuildinfo`、
`.pytest_cache`、`.ruff_cache`、`.mypy_cache` 与 23 个 `__pycache__`；保留 `.venv`、
`node_modules`、`.env`、`infra/searxng/.env.local`、`logs/`、`backups/`、`chat/`（运行所需与用户数据）。



### 验收基线与未验收能力分开记录

| 方向 | 已证实进入 main | 尚未取得的资格 |
| --- | --- | --- |
| **CL-M3 生产接线（S2 批次）** | [#288](https://github.com/2002yy/study-agent/pull/288) 已合并为 `5b0acbb7656e113ab8737b4e4e633aaee21a4bcf`。精确 PR HEAD `3ab26f83` 的 PR CI #40300791096 全绿（全量 pytest 6343 passed、ruff、mypy 基线、前端、Golden Journeys、real-stack 均 success）；25 条评审线程在逐条核对代码与回归测试后全部收口。 | 合并提交的 main CI（#40310609353）实际为 **failure**：`Install Playwright browsers` 在 40 分钟上限处超时（托管 runner 的 apt 镜像过慢），随后两个浏览器步骤被 `if:` 跳过，汇总门禁如实变红——**当时 main 的浏览器门禁并未真正执行**。该缺陷已由容器化解决（browser 作业改用固定 digest 的 Playwright 镜像，浏览器预装、不再 `--with-deps`，见 `docs/CI_BROWSER_CONTAINER_PLAN.md`），并在 main 上验证为绿：run `40473062649`（`346e2547`）与 run `40484965012`（`c8359685`）。**工程合并不等于产品 GO**。全量 L3 未在该批次单独记录（CI 已执行同一测试集合）。 |
| **访问控制（S1，已合并）** | [#289](https://github.com/2002yy/study-agent/pull/289) 已合并为 `4cbcefe2`。精确 PR HEAD `959f4252` 的 PR CI [40486213770](https://github.com/2002yy/study-agent/actions/runs/40486213770) 五作业全绿（`classify`/`backend`/`frontend`/`browser`/`test` 均 success；Golden Journeys 79 passed、real-stack 24 passed）。能力边界：`STUDY_AGENT_API_TOKEN` 未配置时拒绝所有私有请求；前端改为运行时输入令牌（localStorage），不写入构建产物；锁定状态有明确提示并在保存后自动重载；启动器不再以 `VITE_` 变量把令牌交给前端开发服务器。Windows 启动链哨兵为**本地动态验收**（A 正常脚本 0 泄露且 `/sessions` 401、B 回退旧 `VITE_` 注入时探针在 10 个应用模块检出哨兵、C 去掉安全断言时门禁以 exit 1 如实失败、D UI 输入令牌 401→200），证据见 PR 评论 `6438275491` 与 `D:\study-agent-validation\artifacts\s1-windows-sentinel-2026-10-27\`。 | 哨兵的 **CI 自动化仍是开放项**：现有证据是本地动态验收，不是常设门禁。启动器 `Test-FrontendIdentity` 仍按英文标题 `<title>Study Agent Console</title>` 检查，而实际标题是「学习助手 · 学习工作台」，健康服务会被误判为启动失败（独立 P2，未在本批次修复）。多用户身份、数据归属与配额隔离**尚未实现**。 |
| **多用户隔离** | — | 需要身份、`chat_threads` 等表的归属字段、按用户过滤的查询边界、记忆/附件/研究任务与费用配额隔离。当前版本明确**不是**多用户系统。 |
| **并发稳定性** | 同一会话单操作（CAS）、同一研究任务租约与代际、陈旧写入版本校验、研究事件全局递增序号。 | 聊天操作 300 秒过期回收**没有续租**，多进程同时运行时长任务可能被误判；全局设置读改写存在并发丢更新窗口；搜索线程池超时后线程不能强制终止。均为已确认、待修问题。 |
| **费用、存储与附件** | 保守预留、重复请求拒绝、结算观测与适配器隔离（默认关闭）。 | 账本仍有结算能力边界；付费调用开关保持 OFF，真实调用费用未验证。 |
| **验证** | 精确 HEAD 上的普通 CI 可复现；测试集合与 L3 相同（仓库无 `testpaths`/`addopts`）。 | 普通 CI 不等于 L3 记录；L3 额外提供的是干净检出与精确 SHA 的出处保证。真实模型的动态质量仍未验证。 |

### 当前主线：回答链路质量（P0，2026-10-30 起）

Search-1/Search-2 全部合并（#309–#314，main `340b512d` 含 #314），检索侧不再继续做实验设施。

| 项 | 状态 |
| --- | --- |
| 题集 | Search-2 冻结十题 `tests/fixtures/provider_routing/search_2_fact_checks_v1.json` |
| 方法 | 真实产品两段式：`WebLookupService.lookup()` 产出 run，再由 `ChatService.start_turn/generate` 用该 run 回答；两臂只差 `WEB_SEARCH_STRATEGY` |
| 预算 | 预算目标 45 次／≤¥10，但跨进程硬门未达标；留存记录 **42 次、¥2.40 预留口径**，无自动重试 |
| 结果 | 有答案 10/10 vs 9/10；人工正确 8/10 vs 8/10；含引用 2/10 vs 6/10；相关度均值 0.34 vs 0.55；研究中位 7.8 s vs 9.1 s |
| 报告 | `docs/research_quality/ANSWER_AB.md` 与 `docs/research_quality/answer_ab/` 原始证据；一次性付费 harness 未保留（跨进程硬预算未达标） |
| 结论 | DDG-first 的检索优势确实传到答案层（引用与版本正确性），但正确率未提升；两处 P1 都在答案链路，不在检索 |
| 下一门 | **P1-A 研究意图轮次确定性拒答**（工具已读到正文仍 `answer_generation_calls=0`）与 **P1-B `completed` 但正文为空**；先写负控，再改判定 |

Runtime-1B 四臂运行器（PR #308）按用户决定**暂缓**，不合并；`warnings()` 并发修复同列 P2。

### 唯一下一门：S2 并发与暴露面收口（暂停，等待单独授权）

1. **S1（CLOSED，2026-10-27）**：无令牌一律 401；前端运行时令牌；本地配置方法写进 README；E2E 用真实浏览器验证令牌路径。已合并为 `4cbcefe2`，精确 head 五作业 CI 全绿；剩余开放项只有哨兵 CI 自动化与启动器标题检查（见上表）。
2. **S2（未启动、未授权）**：聊天操作增加 `active_operation_heartbeat_at` 续租、回收改为原子条件更新且只针对心跳过期、旧记录按明确回退规则处理；该切片含迁移，需要一次完整 L3。**当前没有对应 PR，也没有合并授权**，main 仍按 300 秒直接回收。
3. **[#293](https://github.com/2002yy/study-agent/pull/293)（独立搜索可靠性修复，未合并）**：`web:` 让 DuckDuckGo 提供商真正返回结果（POST 表单 + 作用域代理），只触及 `.env.example`、`src/web/tool_gateway.py` 与对应测试。它与 S2 并发续租**无关**，保持开放、未合并、未授权。
4. **S3**：研究取消时序先写负控测试，只有真实复现“取消后仍发起付费调用”才修改生产逻辑。
5. **S4/S5**：全局设置并发、搜索资源回收，保留方案不改代码。
6. **S6**：多用户隔离独立立项。

### 并发与多用户边界（2026-10-26 远端静态审查）

静态审查确认的问题与当前处置：未认证放行（S1 已合并 `4cbcefe2`）、`chat_threads` 无归属字段（S6）、300 秒误恢复（S2 待授权）、设置读改写竞态（S4）、线程池超时不可终止（S5）、研究取消层间空窗（S3 先测）。
已有保护不可忽略：单会话操作 CAS、研究任务租约与代际、陈旧写入版本校验、事件全局序号。

### 状态更新纪律

- `main`、PR、独立工作树各自标注；CI 只能绑定**本轮精确 HEAD**。合并完成和产品 CLOSED 是两回事。
- 本文件记录**验收基线**，不追随 main 的最新 SHA：main 前进不需要重写头部，只有当某项能力或其证据变化时才更新对应行，并在该行写明新的 head/run。
- 本文件只维护状态表及唯一下一门；逐次测试、CI 与候选取证留在 PR/历史归档，不能用旧句子覆盖新的事实。
- **模型负责语义、规划与研究/回答策略；程序负责真实读取、工具执行、状态、费用上限与发布资格。** 静态知识与动态事件使用不同证据合同。
- #282 只允许文档及历史归档变化，禁止擅自改 src/tests/workflow、开启模型或运行全量 L3。

## 0A. 冻结研究路线

```text
Lookup → VERIFIED / SAFE_ABSTAIN / pending ESCALATE_STANDARD
Standard（CLOSED）→ 多源补全、比较与冲突；现有生产 runtime 消费
Deep（Deep-1/2/3T/3/4A CLOSED；Deep-4B NO-GO）
  → plan / gap / Evidence Gain / saturation / interruption-resume
  → 复用 ActiveResearchRuntimeExecutor，禁止第二套研究引擎
```

`usable/read_backed/relevant` ≠ claim support ≠ publication authority。各历史结论按其**记录日期**理解，最新状态以当前 main、精确 CI 和本节为准。

## 0B. M4 双线并行与整片交付（2026-11-04 用户最终决定）

**本决定取代此前“M4-C3结束后才启动M4-D”的顺序限制。** 开发/验证节奏的永久规则见AGENTS §15；
本节记录当前授权范围。普通实现细节由执行者处理，不逐步暂停征询；费用、重要架构、数据风险和产品方向变化另行决策。

```text
已完成：M4-C离线验收 + 六层集成至main（#338/#343/#339/#340/#341/#342）
  ├─ A线：M4-C3真实请求→计价→共享预留→单次发送→原始回答/HTML/截图/运行错误/评分
  │       → 独立费用授权 → 12题首次生成 → M4-C4按真实数据改进
  └─ B线：M4-D D1定位/源码哈希 → D2有边界补丁 → D3原子应用/冲突拒绝/回退 → D4浏览器回归
          （先用固定HTML与构造修改验证，不增加模型费用；实际默认策略等待A线数据和完整重建比较）
两线完成可用能力后按整片PR审阅、必要CI、合入main；不为完善所有检测推迟真实样本采集。
  → M4-E 受控自动修复
  → M4-F 图形能力扩展
  → M4-G 智能界面编排
```

**M4-C3 决策树。** 12 题各一次首次生成后，按真实数据选下一步，不预设结论：

| 观察 | 下一步 |
| --- | --- |
| A. 首次成功率低 | 先修提示词、生成协议、预算分配与生成后验证 |
| B. 成功率较高，但修改易破坏原功能 | 将已有M4-D原型与模型修改接线，并比较完整重建 |
| C. 界面正确，但检测器频繁 `indeterminate` | 优先扩展真实页面观察器，不能算模型失败 |

**M4-D 增量修改（D1–D4基础设施已授权立即推进）。** 默认策略与真实模型接入依据M4-C3数据决定，目标是让局部修改可被
证明优于完整重建：

```text
读取已保存完整源码
 → 定位用户要改的功能
 → 生成有边界的修改
 → 检查原版本与修改位置
 → 应用到临时版本
 → 浏览器自动验收
 → 成功保存为新版本 / 失败保留旧版本
```

三个目标：减少 token、降低回归、可靠回退。**必须**与“完整重建”在同一批真实修改任务上比较
成功率、成本和耗时，再决定默认策略；不允许预设局部修改一定更好。

**M4-E 受控修复（P1）。** 把 M4-C 的具体证据交给模型，而不是“画错了”：检查 id、元素 id、
实测距离、允许误差、所属版本。修复后重跑原判据；初期由用户触发，设修复次数与费用上限，
不默认自动重试。

**M4-F 图形扩展（P1）。** 再投入 Three.js / WebGL。Three.js 作为宿主提供的受控执行能力，
不允许生成代码任意从网络加载第三方脚本。优先 3D 空间交互、动态过程模拟、数据驱动可视化，
但不能退化成固定模板选择器。

**M4-G 智能界面编排（P2）。** 判断问题是否值得生成交互、选静态图/流程图/动画/3D、确定可调
参数与必须保证的数学/业务约束、设计可验证的结果，而不是让模型一律输出 HTML。

**集成现状。** #338、#343（预算）、#339、#340、#341、#342已全部合入main，精确main CI全绿。
后续每个完整能力按当前base审阅与差异验证，最终必要CI全绿再合并，不重跑已闭合的旧集成。

**费用门禁。** M4-C3 真实生成评测必须另行批准调用次数、单次费用上限与总预算；当前账本
¥8.63 / ¥30 不变。本记录不授权任何付费调用。
