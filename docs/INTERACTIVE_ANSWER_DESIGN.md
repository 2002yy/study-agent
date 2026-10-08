# GPT-6 Chat 更新拆解与 Study Agent 应用

核对日期：2026-10-08。实施工作区：`D:/study-agent-validation/reading-notebook-ui`，分支 `codex/reading-notebook-ui`，本批基线 `fb1d80d13126346d3fe18fa6f8b878130fc80ea4`。本文件是本批设计与接口记录；执行状态仍以 PROJECT_STATUS.md Current Handoff 为准。

## 公开机制

| 更新 | 官方披露 | 工程含义 |
| --- | --- | --- |
| 智能交互界面 | 模型学习选择内容、布局和交互；原生可流式组件库与编译器在生成过程中逐步显示界面 | 需要模型可描述的组件协议、增量解析和真正可用的组件；图片或装饰卡片本身不等于智能交互 |
| 边思考边回答 | 模型把思考与回答交错，多个部分回答持续增加有用信息，并考虑用户等待时间 | 普通 token 流只负责运输；首个有用段落能否提前出现还依赖模型和任务编排。不能把假进度或未经核验的候选当作答案 |
| 联网搜索 | 改善是否搜索的判断，以及查找能支持答案的信息；官方报告 GPT-6 Instant 搜索问题首答平均比 GPT-5.6 Instant 早44% | 首答时间和总完成时间应分开；来源相关性、权威性、时效、逐事实支持与冲突核对仍需分别验证 |

以上产品行为和架构来自 [OpenAI 官方发布](https://openai.com/index/gpt-6-for-everyone/) 与 [Intelligent UI 帮助页](https://help.openai.com/en/articles/20001598-intelligent-ui-in-chatgpt)。官方公开页没有提供内部编译器代码或可直接移植到本项目的同款组件协议。本项目以下实现是据公开机制设计的独立工程方案，不能声称复刻内部训练或获得相同速度收益。

[Responses 流式文档](https://developers.openai.com/api/docs/guides/streaming-responses)说明以事件增量传输输出；本项目已有 /chat/stream SSE，继续复用现有协议和模型配置，没有更换模型、提供商或 SDK。

## 已应用的组件层

回答仍为 Markdown；模型在确实有用时选择 `study-ui` fenced JSON，每块一个对象。只解析完整且关闭的块；前面的文字立即可读，未完成块显示简短准备状态。未知类型或坏数据保留为普通代码文本。单回答最多4块，单块24k字符、标题100字符，避免无界控件和数据。

| 类型 | 数据与行为 | 事实边界 |
| --- | --- | --- |
| plot | linear/quadratic/sine 固定公式，a/b滑块、恢复初始、采样表 | 明示数学示意；不用 eval 或任意模型脚本，调节不写学习事实 |
| chart | 同一数据可切柱状/折线，并查看完整表格，支持负数/全零 | 引用保留在相邻正文；显示组件不代表数据已核验；示例必须声明 |
| image | 真实 HTTPS 或 /assets/ 图片，可放大、打开原图、显示失败说明 | 不生成图片URL，不加载 data/file/javascript；不等同于接入图片生成服务 |
| actions | 最多4个后续问题按钮，加入当前草稿并聚焦 | 不覆盖已有草稿、不自动发送、不执行外部动作 |
| map | 明确地点坐标、地点选择，点击后加载固定 OpenStreetMap 底图，可关闭/外链打开 | 不推断坐标；底图需要第三方网络；不新增地理检索服务 |

主对话仅将助手内容解释为组件；用户和资料中的代码保持文字。组件不能提供自定义 HTML、JS、CSS、回调或外部操作。模型提供数据，应用负责校验与渲染。复制回答输出可读说明和初始数据，存储/续传保持原回答文本；刷新可重建组件，临时滑块状态不作为用户偏好持久化。

格式说明通过现有 `__STUDY_AGENT_TURN_CONTEXT_V1__` envelope 发送：`conversation_instruction` 保留用户原文，`turn_context` 承载组件说明和原Firefly示例状态。后端既有 ChatRequest validator 将临时上下文转入 scene，模型能看到，ChatThread/ChatTurn 用户偏好不保存该上下文。没有新增 API 字段、数据库列或搜索执行通路。

## 等待与研究体验

当前回答内显示真实状态：组织回答、搜索、筛选、阅读、整理、核对；研究次数和已读数来自现有 research SSE，不用虚构百分比。首个 token 到达后提示可以先阅读；完整组件到达后，在后续回答仍生成时也可使用，不因追加文字重置参数。

关键现状：`src/api/routes/chat_routes.py` 的研究支持回答在 `answer_validation_active` 时缓冲全部候选，只有 `complete_turn` 返回已核验文本才发布 token。这个边界保留。普通聊天能逐 token 出现交互组件，但本批不能让研究事实在全局核验前变成已验证结论。

要进一步实现“研究中先看到已核验的小结”，由搜索窗口建立逐段发布合同：独立可验证的事实块 + 绑定来源/支持跨度 + published/withdrawn 生命周期，再由 UI 消费。禁止直接把 selected_sources、read成功或临时摘要当作 verified。本批已验证这条缓冲边界和取消行为，但未修改其执行/发布策略。

## 直接所有者与后续接入

| 文件/符号 | 本批职责 |
| --- | --- |
| frontend/src/features/answer-ui/answerUiProtocol.ts | 类型白名单、验证、完整块解析、复制文本、临时上下文说明 |
| frontend/src/features/answer-ui/AnswerCardView.tsx | 原生交互组件与局部状态 |
| frontend/src/features/answer-ui/AnswerProgress.tsx | 真实等待/部分回答状态 |
| frontend/src/components/MarkdownMessage.tsx | 文本与组件增量呈现；默认普通Markdown模式 |
| frontend/src/features/single-chat/ChatPanel.tsx | 助手消息启用组件、草稿动作、进度与复制 |
| frontend/src/app/useLearningSessionRuntime.ts | 本轮UI上下文接入 |
| src/api/models/chat.py / src/turn_context.py / src/prompt_policies.py | 复用现有传输、持久化分离及模型上下文，不改生产代码 |

后续验收应分别记录：首个有用内容时间、完整回答时间、组件格式有效率、用户可完成任务、支持来源覆盖、失败/中断/刷新恢复。浏览器分段 SSE 样例证明前端时序和交互，不代表真实模型自动选择成功率、真实联网质量或模型原生交错思考的线上验收。

## 2026-10-08 补充：同一状态驱动的小型应用

按用户给出的三个可操作例子扩展，而非仅增加新的图表皮肤。增加 memory_lab、performance_lab、evidence_lab 三种白名单模板；模型可选择并给初始数据，实际状态转换、计算和结论由应用实现。它们仍不属于任意代码生成/执行或通用应用编译器。

- Java引用实验：连续操作改变同一份引用/对象状态，代码、局部变量、对象值、可达性和说明同步；置空后访问属性展示NullPointerException并保留状态；不可达标记为可被回收，不能称已实际GC。只建模a/b两个引用，最多12个对象，支持重置。
- 证据审查实验：严格要求mode=simulation。勾选计时样例/主观评论更新局部判断；有限正例只支持有限任务，观点不能成为测量，反例（含相等、不满足严格更快）推翻全称命题。所有数据显式虚构；不调用真实来源纳入/排除API，不改变发布结论。模型不能通过mode=verified把演示升级为真实证据。
- 性能实验：单一参数状态派生网页批次数、串行/并发时长、图表和节省比例。8/3/4/6得到38秒、18秒、约53%；并发大于页数只有一批；1页不产生并发收益。使用ceil批次公式，明示等耗时、无开销/失败重试、总结等待全部读取的假设。

`frontend/src/features/answer-ui/AnswerLabs.tsx` 是状态与计算所有者；同名unit测试和 `frontend/e2e/answer-labs.spec.ts` 验证连续操作、数学边界、观点/反例、草稿及320px布局。UI上下文说明增加三种格式，复用已有瞬时envelope，API/后端搜索/数据库契约没有改变。

开发预览：`http://127.0.0.1:5188/answer-labs.html`。`frontend/answer-labs.html` + AnswerLabsPreview.tsx + answerLabsPreview.css提供确定性可操作样例，入口受import.meta.env.DEV限制；默认生产构建不包含此预览入口。会话内组件使用同一实现；预览不发聊天/研究请求，不写用户资料，也不代表真实模型已自动生成这些实验。

第三层真实数据连接仍需服务器拥有的数据快照/来源身份/核验状态绑定，局部“假设选择”与正式纳入/撤回应分别显示。不得从模型JSON的自报标签获得真实verified状态。下一步围绕真实研究snapshot设计绑定合同，保持研究执行与正式发布由另一窗口拥有。
