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

**静态证据**：`tests/test_interactive_state.py` **12 PASS**（保存/读取、各版本互不覆盖、
跨会话隔离、超限、非对象、路由 404/422/指定版本）；`tests/test_spend_settlement.py` 的 schema
断言改为跟随 `SCHEMA_VERSION`，**53 PASS**；schema 相关影响集 **139 PASS**；前端完整
**123 文件 / 641 PASS**，tsc 与构建 PASS；Ruff PASS；mypy **118/128，新增 0**。迁移 31 属
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
