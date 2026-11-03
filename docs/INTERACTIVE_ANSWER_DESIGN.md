# GPT-6 Chat 更新拆解与 Study Agent 应用

## 2026-11-03 后续：模型输入中的旧界面版本压缩

目标只有一个：同一次实验里连续修改界面时，不再把 V1、V2 的完整 HTML 一起送进模型。
压缩只改**发给模型的副本**；前端消息、数据库历史、原回答都保持原样，用户仍能查看和操作旧版本。

判定与保留规则：

| 规则 | 行为 |
| --- | --- |
| 只处理助手消息里完整闭合的 `study-ui` JSON，且 `type=interactive`、`id`、`revision>=1`、`html` 非空 | 其它内容（用户粘贴的 HTML、普通示例、图表、未闭合或坏 JSON）原样保留 |
| 当前编辑对象由「继续探索「标题」（版本 N）」或显式 id 确定 | 多个组件且没有明确选择时不压缩，报告 `ambiguous_multiple_ids` |
| 同一 id 的其它 revision 换成摘要 | 只保留原有的 id、revision、title、summary 和“源码未提供”的状态 |
| 压缩后不比原文短 | 放弃替换，避免摘要比源码还贵 |
| 解析失败/异常 | 返回原历史，不改写 |

摘要不得推测旧版“修复了什么”。没有可靠变更说明时，只写确定字段；正文解释和用户原话完整保留。
摘要里明确写出“需要旧版源码时应从已保存的会话记录恢复”，这是本片对“没有源码就明说”的兜底，
按需恢复旧版本仍留到下一片。解析同时接受 CRLF 与 LF，只影响读取，不改写存储格式。

压缩由独立模块 `src/interactive_history.py` 完成，`build_messages` 在拼接历史前调用一次，
因此普通聊天与策略聊天共用同一入口；未声明 `【自由交互界面 v1】` 的请求不压缩。

第一阶段的离线对照（不调用模型）使用已保存的真实会话：

| 真实会话 | 轮次 | 原字符 | 压缩后 | 结果 |
| --- | --- | --- | --- | --- |
| `chat_946d4b0a…`（`cache-ref-canvas` v1–v4） | 第 4 轮 | 24514 | 10278 | V1、V2 变摘要，V3 完整 |
| 同上 | 第 3 轮 | 15522 | 8562 | V1 变摘要，V2 完整 |

两次可压缩轮次合计 40036 → 18840 字符（−52.9%），用户消息逐字一致、当前版本源码逐字存在。
另一真实会话 `chat_0f6b490c…` 在同一对话里出现了两个 id，工具如实报告“无明确选择/无替代版本”，
没有压缩——这正是“不能假设最后一段 HTML 就是当前界面”的边界，而不是解析失败。
这是成本与保真对照，不是修改成功率；第二阶段的小规模真实调用尚未执行。

本片不引入局部代码补丁、新 UI 协议、数据库迁移或前端改动。

## 2026-11-03 后续：任务预算与生成生命周期

用户针对 #338 (`1b29e00f`) 的复核选定“先预算/生成生命周期，再状态/版本”。本节替代下文
历史实现“只要系统能力开启就给至少6000”的预算策略。保留原 study-ui 协议和双层沙箱。

| 当前任务 | 输出上限（tokens） |
| --- | --- |
| 普通说明、明确只要文字 | 原 fast/standard/deep：700/1100/1600 |
| 简单交互，如一个滑块 | 3500 |
| 一般交互、当前界面修改、直接逐步探索 | 6000 |
| 多面板或较长当前源码的完整替换 | 9000 |

只有当前系统声明 UI 能力时才选择交互档。依据本轮用户要求及最近助手界面的修改上下文，
不因旧系统能力在用户引文中出现而扩权。普通解释、显式不要界面优先；复杂任务提示先给可运行核心。
这些规则是可回归的初始启发式，不是模型语义分类器，也不是经过大样本优化的预算。
没有新增分类调用、自动继续或提高重试次数；预算作为 route.output_budget 可检查，费用门仍按真实 ceiling 预留。

`llm_client` 的同步、同步流、异步流均增加可选的单次完成通知，原 str/token 迭代器接口不变。
仅观察回答调用，引用绑定不混入；usage-only 空 choices 块可正常跳过。finish_reason 只保留白名单，
缺失为 unknown，不能靠收到若干字符猜测正常结束。超时通过原异常类型/因果链识别，迟到完成通知
不能覆盖已记录的 timeout。状态保存在现有 route_snapshot，HTTP 响应 route 与 SSE done/error 带回。
取消仍使用已有 cancelled 事件和持久化 turn 状态，不自动重发。

前端把提供商结束结果、格式完整性和 iframe 执行失败分开处理：正常 stop 但坏格式说明格式不完整；
length 显示达到上限；错误/超时保留部分内容；用户点击继续/修复只添加草稿。网络 EOF 没有 done/cancelled
时按断线处理，不伪装成完成。历史无元信息的回答继续以 unknown 展示，不推断旧输出为何不完整。
CRLF 与 LF 围栏等价，嵌套普通代码示例仍不执行。

真实验收覆盖 700/3500/9000 的提供商接受、三次 stop 和一次 length、同步/流式结束原因及库存交互。
离线验证另覆盖缺失 finish_reason、content_filter、超时异常链、旧回应格式、持久化/刷新与手动恢复。
详细结果、提交范围、费用和下一片由 PROJECT_STATUS.md 当前交接持有。所有真实回放需显式指定
`INTERACTIVE_BUDGET_REPLAY_DIR`，测试不发出模型请求，标准 CI 默认跳过外部证据。

这片没有实现大 HTML 历史压缩、刷新恢复探索状态、增量代码补丁、后台自动验证/修复或 CPU 硬配额；
也不把 9000 改成统一预算，不改网络超时、研究剩余时间或 8 秒 iframe 初始化检查。

## 2026-11-03：自由生成与交互探索

用户确认本轮重点为「符合，优先自由生成与交互探索」，并明确 SVG、Canvas、HTML
均可使用、最终效果优先。本节取代下文历史版本中“仅预设模板、不支持模型 HTML/JS”
的能力限制；旧组件及原有研究证据发布边界保留。当前交接见 PROJECT_STATUS.md。

新增 `study-ui` 中的 `interactive` 对象：`id`、`revision`、`title`、`summary`、`html`。
模型提供自包含 HTML/CSS/JavaScript，可以自行组织 DOM、SVG、Canvas 和交互逻辑。
图形、参数、解释可共享一份状态，不再需要为每个学科预写实验模板。
最多四个组件，文档最多 60000 字符、编码后的单块最多 96000 字符；旧类型仍为 24000。

- 完整关闭的块才运行；流式追加正文不重建画布或丢失参数。失败或未完成时保留正文、
  说明与可读恢复入口，不执行残缺代码，不自动追加付费调用。
- 用户可以展开、重置、停止；源码与当前状态可查看。刷新从原始参数恢复。
- `window.studyUI.setState({...})` 发布至多 4000 字符的 JSON 状态；没有显式状态时捕获
  有 name/id 的普通控件。点击“带着当前状态继续问”才追加到草稿，由用户编辑、发送。
  它不是长期记忆或研究核验结论，也不替用户调用工具。
- 追问由现有聊天历史携带原内容，模型返回同 id、递增 revision 的完整新版。
  新旧版本各在自己的回答中保持可操作；本片不做跨消息覆盖或版本合并。

**执行边界**：生成内容运行在两层 `sandbox="allow-scripts"`、无同源权限的 iframe 中。
内层 CSP 限制资源、网络、表单和子 frame；外层为应用持有的固定文档，以 `frame-src 'none'`
阻止内层通过导航绕开自身 CSP。外层只转发已知类型、来自内层 window 的消息，宿主再次
校验 source、opaque origin、channel 和大小。没有宿主数据下发，没有 API/文件/存储桥。
源码先经 inert template 解析；模型脚本从不进入应用 DOM。能力不包含外部依赖、联网、
文件处理、任意工具执行或可靠的 CPU 配额；浏览器不是通用代码运行服务。
依据：[iframe sandbox](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)、
[CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy)、
[postMessage](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage)。实际隔离验收为 Chromium 桌面/手机，非全浏览器资格。

**真实发现与修复**：旧 fast 预算只有 700 tokens，第一次实际调用在 HTML 中途截断。
当前系统提示声明 `【自由交互界面 v1】` 时，回答输出上限至少 6000 tokens；普通未声明该能力的
渠道保留旧预算。同步、流式、异步流式三条回答通路统一处理，引用绑定通路不改。
费用仍由同一共享账本按实际请求上限预留；无新增规划调用、自动重试、绕过预算或发布门。

**验证入口**：`npm test`、`npm run build`、`npm run test:experience`；后端命名 L1 为
`intelligent_ui`。`interactive-document.spec.ts` 验证 DOM/SVG/Canvas、草稿、刷新、错误、
窄屏及隔离；`interactive-live-replay.spec.ts` 仅在指定 `INTERACTIVE_LIVE_REPLAY_DIR` 时
重放已存真实回答，绝不调用提供商，默认跳过。`interactive-cross-domain-replay.spec.ts`
以同一方式重放代码故事与 Canvas，当前默认读取 response-7（代码）及 response-4（Canvas）。
现有 CLI、API 和 SSE 不新增传输格式。

本轮真实证据位于 `D:/study-agent-validation/intelligent-ui-20261103/`：真实 `/chat` 路由
经 TestClient 调用 DeepSeek，浏览器再重放原始回答。第一版滑块从 5 改为 12 后可售 32→25；
第二版保留 37/12/25 并增加支付操作。付费调用传输与桌面启动验收分开，未跑同进程全链路，
也没有 ChatGPT 对照。
动态运行器曾漏传前端原本会传的 `chat_history`，导致新版 ID 漂移、围栏变成 json；失败原文
保存在 `followup-without-history/`。补齐真实请求形状后复验，协议仍只认 study-ui，未放宽解析。
成本包含失败尝试，始终使用先前 ¥30 共享账本；具体余额与验证结果由当前交接记录。

### 跨学科动态证据与局限（2026-11-03 下午）

| 样例 | 独立检查 | 结果 |
| --- | --- | --- |
| Java 引用故事 | 执行前无实例；a/b 共用实例；b 改指新实例后旧值保留；回退/重置；字号和 SVG 端点 | 最终 response-7 PASS，桌面/手机共两项 |
| Canvas 振子 | x=A*sin(phase) 的数值、调参后的画布像素、播放/暂停/重置、减少动态效果 | response-4 PASS，桌面/手机共两项 |

代码样例原 response-3 在 step=0 就绘制对象；response-5 修正语义，但 SVG 字体在双列
缩成约 9px。response-6 改为 HTML 标签后漏了对象框绝对定位，箭头指向空白。
最终 response-7 统一坐标后通过；用旧 response-6 重放同一几何断言，箭头偏差 **248px**，
明确失败（`cross-domain-geometry-negative.log`）。新断言同时检查端点横向距离与落在对象高度内，
不以文本正确冒充图形正确；局部横向滚动保留窄屏文字尺寸，页面没有横向溢出。

这些样例验证自由运行与追问修复能力，不证明模型首轮生成质量稳定。全局提示补充了初始状态
真实性及缩放后字号要求；response-5/6 的请求读取了旧导出提示，但用户追问明确包含修复要求，
不得把它们算作新提示独立提升质量的 A/B 证据。当前 CLI 导出提示已改为本地 TypeScript 转译，
不再依赖浏览器预览服务是否运行。所有 input/response/live-N 文件均保留原始内容与预算快照。

### 桌面启动与恢复证据

本片另修复一个实际冷启动阻断：Windows PowerShell 5.1 在上层收集函数输出时，会把 Docker
尚未运行的 stderr 转成终止异常，使 `Start-DockerIfNeeded` 来不及启动 Docker Desktop。
仅在两个只读存在性探测内设置局部 Continue 策略，仍用退出码判断；真正 Docker 操作继续
检查失败并停止。`desktop_docker_startup` 包含真实 PS 5/7 子进程、daemon/container 的正反样例、
调用者错误策略不泄漏及启动身份合同，共 41 PASS。脚本保留 UTF-8 BOM，PS 解析零错误。

本机 Docker 自身也因 Secrets Engine 的陈旧 `engine.sock` 无法重命名而退出。
原父目录 `AppData/Local` 带 EFS 属性，同父目录备份和空目录解密均被系统拒绝；未删除 socket。
停止本次启动的 Docker 进程后，验证同盘明确源/目标路径，将完整故障目录保留移入未加密的
`C:/StudyAgentDockerRecovery-20261103/docker-secrets-engine-154308`，随后从原桌面脚本恢复 Docker。
现有 SearXNG 与 retained 容器仍在，镜像及 volume 未改动。没有系统重置、WSL 全局关闭或数据清理。
恢复时创建但未使用的空目录 `C:/Users/Zhang/AppData/Local/study-agent-docker-recovery-20261103-154243`
因自动审批拦截清理而保留；不影响运行。恢复收据为证据目录内的 `startup-recovery.json`。

PS 7 的 `Start-Process` 还会把其模块路径原样传给 PS 5，导致 Get-FileHash 自动加载失败；
验收运行器为 PS 5 子进程显式设置 Windows 系统 PSModulePath，生产脚本无需为运行器环境改动。
`accepted-start.stdout.log` 记录前后端身份、Docker 搜索与真实返回；`studyctl ui --json` 为 auth=ok。
最终桌面入口 `C:/Users/Zhang/Desktop/Study Agent.cmd` 默认启动本开发工作树，未使用 SkipSearXNG。

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
