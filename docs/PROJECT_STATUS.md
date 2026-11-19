# Study Agent 当前状态

> **唯一冷启动/交接入口。** 本文保留已核实的现状、开放阻断和下一执行片；细节证据在 [2026-11-17 收口记录](research_quality/RETRIEVAL_LEAN_EXECUTION_20261117.md)、对应 PR、精确提交 CI 和 Git 历史。稳定规则以 [AGENTS.md](../AGENTS.md)、[产品迭代规则](PRODUCT_ITERATION_POLICY.md) 为准。
>
> **产品目标**：体验接近 ChatGPT 的通用聊天与研究 Agent，覆盖自然聊天、自主研究、持续交互、智能 UI、多模态和工具执行；教学是专业场景。**部署仍限可信环境的单用户**；多用户身份/数据/费用隔离未实现。

## 0. Current Handoff（2026-11-19，冷启动）

### P1 SSE 终态正文与界面一致性（2026-11-19，独立静态片）

- **等级/归属**：P1 预防性修复，UI/传输发布契约；未从真实用户
  任务轨迹归因，故仅为 `static / engineering-only`。假 SSE 负控先红：
  ① 服务端 `done.reply` 已发布修订答案，但前端请求层仍返回先前 token 草稿；
  ② 服务端 `cancelled.partial` 是持久化部分正文，但浏览器没收到 token
  时，请求层返回空串且聊天控制器在取消回调后再次清空已恢复的内容；
  ③ 服务端明确发布空正文时，控制器的 `||` 回退会重新显示未发布草稿。
- **实施**：独立分支 `codex/p1-sse-final-authority-20261119`，基线
  `main@c6e8e6c4af37fd4731d109da584b2914015cbb7c`。SSE `done.reply`
  以服务端最终正文为权威返回值，`cancelled.partial` 以服务端持久化部分为
  权威；控制器保留已结算的取消状态和恢复卡，使用 `null` 区分“没有终态”
  与“终态明确为空”，拒绝草稿回流。仅改前端传输与控制器、相应测试；
  不改后端生成/存储、研究证据门、成本或模型调用。
- **证据/限制**：四项终态负控及相邻影响集与 TS/Vite 构建见对应 PR；
  默认 Playwright 用例尝试时缺少所需 Chromium，系统 Chromium 又因执行
  环境拒绝创建 socket 而退出，故真实浏览器可见性 `not_run`，需要在
  具备浏览器权限的 CI/人工环境再验；真实模型、搜索、付费比较 `not_run`，
  预算授权 `not_applicable`，不据此宣称实际用户体验已验证。
- **主线重新整合**：基于 `main@3ac77fd6` 将 #522 重挂；唯一冲突为本
  交接文档，保留主线检查点修复记录和当前 SSE 契约记录，未改变实现范围。
  前端相邻影响集 **95 passed / 7 files**，TS/Vite 生产构建、全仓 Ruff、
  差异检查与 mypy 基线 **115/125（无新增）**通过；新 HEAD 的远端 CI
  仍须独立验收，不能复用旧提交结果。
- **进一步主线整合**：上一 HEAD `3ee86fb8` 的 CI `44491085376` 已
  成功，但 `main` 又加入模型审计与失败终态发布改动；以 `main@82399918`
  重新挂载 #522，只保留其前端传输、控制器与测试修改。冲突仅为本交接
  文档，已保留研究终态发布记录；新 HEAD 仍需独立 CI 和审阅验收。
- **本轮终态补强**：已核对正式后端的 `finish_cancelled_turn`：SSE
  `cancelled.partial` 只包含本次生成的可发布后缀，续写时会与此前已保存
  的前缀一起持久化。浏览器旧实现却优先拿临时 token 充当恢复正文，
  即使服务端保存为空也残留未发布草稿。三条负控（临时 token 与服务端
  partial 不一致、服务端明确空 partial、续写时前缀 + 服务端后缀）
  先失败后修复；恢复与可见正文现在均从服务端部分正文构造，临时 token
  只用于执行中的预览。属于 P1 静态交付一致性，不宣称实际模型体验已验证。
- **当前整合**：基于 `main@bab64534` 保留 #479 选源观测、#481
  已合并交接记录，唯一冲突仍为本状态文件；#522 前端修复与新增负控
  一起进入精确候选，需在新的 HEAD 上重新跑 CI 才可合并。
- **2026-11-19 收口进度**：上一精确 HEAD `a23c3bba` 的 CI
  `44504307978` 成功、无审阅阻断；随后主线合入 #523 与 #521。
  现重新整合至 `main@77caf8b6`，唯一冲突是本交接标题，保留主线
  附件材料与可读性契约，不改变本 PR 前端 SSE 生产代码；新的精确
  HEAD 必须重新跑 CI，不能沿用上一绿色结果。
- **下一独立片**：#522 与 #524 完成合并后，用 Fake Provider 核验
  附件进入模型入参与用户界面最终交付的完整链路；真实模型和搜索
  需独立授权与预算上限。

### P1 本轮附件真正进入模型请求（2026-11-19，独立静态片）

- **等级/归属**：P1，编排契约与附件读取层；无本轮真实用户失败轨迹。
  静态负控复现：① 未开视觉识别的图片为 `ready`，选中后却没有可读内容；
  ② 已就绪文档的临时索引丢失，选中后仍被接受；③ 消息绑定 5 份附件，
  原读取默认只取前 4 份，模型看不到第五份；④ 入口验证通过后附件绑定
  或正文失效，以及重试绑定内容哈希变化，可能不被检测到。
- **本片**：`codex/p1-attachment-visible-material-20261119`，基线
  `main@e5ec70059d35c9e209768d8461b2440ece6da83c`。消息/研究队列/
  研究 steering 选择必须有实际可读的索引内容，否则返回可解释的冲突并阻止提交；
  聊天进入模型/研究工具前再检查已保存的 ID 与内容哈希，并复用同一份
  快照到提示词和研究工具。每条消息最多 10 份的全部已选内容按 12,000
  字符总预算公平节选，不再默默丢失第五份；明确标示截断以及图片描述不等于原图。
  原有存储 `ready` 状态不改：它只证明上传/存储完成，不保证模型可读取。
- **证据边界**：负控旧行为先红后绿，假模型实际入参逐份包含五个附件的标记；
  本地离线 Ruff、相关 L1、mypy 基线和 diff 范围核验见对应 PR。
  未调用付费模型、视觉 API 或真实浏览器，**不宣称真实图片理解或用户任务已成功**。
  不含前端“已就绪”徽标语义调整和完整 SSE 可视化验收。
- **2026-11-19 主线重挂**：主线推进到 `main@3ac77fd6ca2f33c34f639d84993dd6c07361236a`
  （#514 检查点回绑），原 #521 的唯一冲突是本节与 #514 的交接标题。
  两条现状均保留，附件与研究运行期生产代码无语义冲突；更新候选
  在 13 个直接影响模块 **141 passed**，全库 Ruff、差异检查和 mypy
  **115/125（无新增）**通过。新远端 HEAD 须独立通过精确提交 CI，
  上一 SHA 的结果不能替代；真实模型与浏览器 `not_run`。
- **失败 CI 修复与新主线整合**：旧 HEAD `be5f4769` 的 CI `44490460070`
  完成 **6769 passed / 1 failed**；失败只在历史 D1 持久化测试将附件引用
  当作可读取正文，触发新验证器正确拒绝。已在该测试夹具补充与引用哈希
  一致的可读取材料，保留生产 fail-closed 逻辑与负控；受影响后端测试
  **52 passed**。再次整合 `main@82399918` 时仅交接文档有冲突，保留
  主线终态发布记录；Ruff、差异检查、mypy **115/125** 通过。
  浏览器和动态模型调用 `not_run`，新精确 HEAD CI 尚待独立验证。
- **主线收口（2026-11-19）**：原精确 HEAD `41c46fc4` 的 CI
  `44499999149` **success**，无审阅阻断；主线已合入 #479 和 #523，
  此次重挂到 `main@2ae50fc7`。冲突仅涉及本交接章节，保留附件 UI
  可读性与研究观测记录，不改变后端材料验证行为。新的精确 HEAD
  须重新 CI 验收，不能复用旧绿色结果。
- **下一独立片**：#521 合并后，以 Fake Provider 验证“上传→选择→发送→
  模型实际收到全部可读材料→界面显示发布答案”；真实付费模型、视觉和
  搜索需要另外授权，不把离线证明当作动态产品结论。

### P1 附件保存状态与消息可读性分离（2026-11-19，独立静态片）

- **等级/归属**：P1 防止用户把不可用文件当成已交给模型的附件；
  `UI / attachment-readability contract`，仅由服务处理记录与离线
  负控证明，未归因于真实用户轨迹，标记为 `static / engineering-only`。
  基线 `main@c6e8e6c4af37fd4731d109da584b2914015cbb7c`，独立分支
  `codex/p1-attachment-readability-ui-20261119`，不叠加未合并的 #521/#522。
- **证据与修复**：服务端对未启用云端图片理解的图片会写入
  `status=ready`（保存/流程结束）及 `indexing.retrievable=false`
  （无可用正文）。原 Composer 只检验 `ready`，会显示“已就绪”、
  允许手动选中并在上传后自动选入消息。现在只接受末次 indexing
  明确 `completed + retrievable=true` 的附件；无记录时保守拒绝。
  上传混合可用/不可用文件只选可用项，刷新时移除已有不可读选择，
  保留并发上传期间其它有效选择；图片显示“已保存·未识别”并提示
  开启云端图片理解后重新上传。来源面板共用状态判定，不再展示
  不可读正文的阅读入口；文件大小提示在刷新后不被清除。
- **静态门禁**：先红的负控覆盖未识别图片自动/手动选择、混合上传、
  历史选择清理与来源面板不可读正文；重挂 `main@b677d74c` 后的
  前端相邻影响集 **71 passed / 7 files**，TypeScript/Vite 构建、
  全仓 Ruff、`git diff --check` 和 mypy 基线 **115/125（零新增）**通过。
  重挂时唯一冲突为本交接文档，保留主线的模型审计/检查点记录；
  新精确 HEAD 的 CI 仍须独立验收，不能沿用旧提交通过结果。
  真实浏览器、真实图片模型、搜索或付费动态对比 `not_run`，不得据此
  宣称用户任务端到端完成。
- **失败浏览器 CI 修复与新主线整合**：旧 HEAD `2d5c0f59` 的 CI
  `44496632775` 仅在连续研究会话的桌面/移动 Chromium 用例失败：
  `notes.txt` 测试夹具虽为 `ready`，却没有 completed/retrievable 的
  indexing 记录，新 UI 因此正确地拒绝自动选中。已仅修复夹具，
  不放宽生产可读性门。重新整合 `main@82399918`，唯一冲突仍为交接
  文档；相邻前端测试 **71 passed / 7 files**，TS/Vite 构建、Ruff、
  差异检查和 mypy **115/125** 通过。Playwright 用例清单已解析，
  真正浏览器执行仍须在新精确 HEAD 的 CI 重新验收。
- **合并收口重挂**：修复夹具后的 HEAD `c94f8f5f`，CI `44499994030`
  已成功且审阅线程为空。主线随后合入 #479（`main@bab64534`），
  因交接标题冲突无法直接合并；本次保留主线 #479 诊断与 #481 已合并
  记录，仅将 #523 的原 UI/测试增量重挂，新精确 HEAD 必须重新 CI 验收。
- **下一独立片**：待 #521 的服务端选中正文契约验收合入后，使用
  假 Provider 做“上传 → 选中 → 发送 → 模型可见材料”的离线跨层负控；
  同时审计原会话切换与队列发送期间的附件选择隔离，不开付费 API。

### 2026-11-19 读取候选测试搭建去重（#517 最新主线候选）

- `tests/research_read_candidate_factory.py` 合并读取调度、执行、投影测试内三份重复的 `CandidatePoolItem` 构造；保留 ID、URL、标题和来源场景原值，不改生产检索、读取、恢复、检查点或预算。
- #479 精确 HEAD `9086a708`、CI `44499513153` 成功且无审阅阻断，已合并 `main@bab64534`。#517 在 `main@77caf8b6` 上的精确 HEAD `fe1fcbf8`、CI `44511142471` 已全绿且无审阅阻断；随后 #522/#525 推进主线至 `main@56e2f23e`，使原 PR 再次无法合并。本次重挂保留主线 P1 附件/SSE/真实服务栈回归交接与代码，仅迁移测试去重增量；须按新精确 HEAD 独立验收。读取/选源影响集 **37 passed**，此前跨恢复、检查点、模型预算、发布、选源和读取组合影响集 **151 passed**，Ruff、差异检查通过。`priority=P3`，`loop=static`，`owner=orchestration-contract`，`dynamic_evidence=not_run`，`budget_authorization=not_applicable`。下一步精确 CI、审阅无阻断后合并 #517；此后只按明确耦合收益开启下一小片。

### 2026-11-19 选源窗口诊断职责整合（#479 已合并）

- #481 精确 HEAD `b1f2729b` 的 CI `44497014870` 全绿、无审阅阻断，已 squash 合并到 `main@82399918`。#479 基于这条主线重新挂载；`research_selection_observability.record_selection_authority()` 接管选源输入指纹、候选变化数、排除状态变化、独立的开始/结束时钟采样与最近 40 条记录。`active_research_runtime` 仍负责模型准入、选源、退化与实时 context 回读；不转移检索策略或模型预算所有权。
- 专项负控覆盖连续波次输入变化、两个独立计时采样以及损坏历史记录后的 40 条上限。本地相同代码组合影响集 **112 passed**、Ruff 和差异检查通过，mypy **115/125** 无新增。此批 `priority=P3`、`loop=static`、`owner=orchestration-observability`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`；精确 HEAD `9086a708`、CI `44499513153` 成功，已合并 `main@bab64534`。

### 2026-11-19 失败终态发布上下文整合（#481 已合并）

- 旧 #481 在当前 #512—#515 整合树上重新实现：`ActiveResearchPublisher.fail` 统一持有无证据终态的 repository 调用，三处规划失败与异常无证据路径不再传递四个共享结果列表。`_terminal_unavailable` 从当前结果缓冲区读取证据 ID，仍在原位附加游标、Claim Engine 状态、执行 Stop Gate，再发布；检查点、模型计费、恢复格式、读取策略均不变。
- 新负控固定恢复后 `research_context`、实时查询尝试列表、操作租约与失败原因；本批属于 `priority=P3`、`loop=static`、`owner=orchestration-contract`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`。精确 HEAD `b1f2729b` 的 CI `44497014870` 成功，已合并 `main@82399918`。

### 2026-11-19 模型尝试实时状态绑定（重新验收候选）

- 在检查点顺序、游标、持久化上下文、波次交接与检查点回绑的最新组合上重挂模型审计绑定；必须以新精确 HEAD 的 CI 验收，不沿用旧提交的结果。

### 2026-11-19 检查点准备回绑单一持有（重新验收候选）

- #510 已在主线，因此本批只保留 `live.bind_prepared_checkpoint` 对 `prepare_and_persist` 的回绑：移除多余内部函数，保证准备抛异常时 state/context 同时回绑。原 #514 的双父合并历史不再重复带入已合并的 #510 内容；新树需精确 HEAD CI。

### 2026-11-19 波次绑定重挂检查点整合树（重新验收候选）

- 将 #513 的波次交接绑定协议重挂在已更新的 #512 上。保留 #510 的检查点顺序和 #511/#512 的单一运行期状态所有权；此候选需要新的精确 HEAD CI，不能沿用旧的绿色结果。

### 2026-11-19 持久化上下文所有权与检查点顺序重新整合（重新验收候选）

- 基于已合并 #510 的 `main@a63e9440` 和重新挂载的 #511，重新应用 #512。冲突点为检查点内的 `nonlocal context`，统一回绑 `live.state/live.context`，但保留 `ActiveRuntimeCheckpointContext.prepare_and_persist` 的准备、回绑、持久化顺序。该候选需独立精确 HEAD CI。

### 2026-11-19 游标单一持有与检查点整合（重新验收候选）

- #510 已以精确 HEAD `36a377e4`、CI `44375838320` 成功验收并合入 `main@a63e9440`。#511 原 HEAD `3d361a39` 的 CI 已成功，但因主线推进产生冲突，基于当前 `main@a63e9440` 重新应用游标所有权变更；恢复与检查点的现有实现保持 #510 语义，重新验证精确 HEAD 后才允许合并。

### 2026-11-19 检查点准备与持久化顺序封装（已合并）

- 后续本地补强：检查点专项测试共用统一构造器，新增成功路径顺序负控，明确 `bind_prepared` 必须先于仓库 `checkpoint`；检查点、实时状态、波次结算和守卫专项集 **10 passed**，未触及生产代码。此补强仍属于未推送的同一候选，不能代替 L3 或远端 CI。
- 基于上一状态单一持有候选 `e13960c8`，分支 `codex/research-cursor-context-20261119`。将主动执行器检查点内的 `prepare → finally 回绑状态/上下文 → persist` 提取为 `ActiveRuntimeCheckpointContext.prepare_and_persist`，明确准备异常后仍回绑已投影的内存值，同时禁止失败后继续持久化；执行器仍唯一持有实时状态、游标和持久化上下文，后两者不作双份镜像。
- 专属负控冻结 Claim Engine 序列化异常时预算投影与游标上下文保留、仓库不写入；检查点、实时状态、波次结算、守卫与主动执行影响集 **93 passed**，Ruff、差异检查及 mypy 基线 **115/125（无新增）**通过。全量 L3 已启动但观察到首 1% 用时较长，为避免无界后台执行而中断，**尚未通过**；远端精确提交 CI 待验收。真实搜索、付费模型与动态比较 `not_run`，预算授权 `not_applicable`。属 P3 / static / orchestration-contract / engineering-only。下一片在主线整合后处理游标、持久化上下文的单一所有权，不在本片同时迁移。
### 2026-11-19 模型审计与实时状态绑定（独立叠加候选，待验证）

- `ActiveModelAttemptContext.for_live_values(live, ...)` 以最小 `LiveModelAttemptValues` 协议统一绑定当次研究的实时状态/游标；执行器不再分别拼接三个状态读取/回写回调。新负控覆盖恢复后状态替换的预算检查、检查点后波次游标替换时审计写回最新游标。
- **冻结契约**：开始审计仍按 `ensure_active → ensure_budget(current_state) → begin_model_attempt → checkpoint`，结束审计仍只在内存完成并在 `ensure_active` 后交还控制；模型网关、真实调用次数、超时预算采样、结算和后续语义检查点均不变。影响集 **104 passed**，Ruff、差异检查及 mypy 基线 **115/125** 通过。本片 P3 / static / orchestration-contract / engineering-only；真实模型/搜索 `not_run`，预算授权 `not_applicable`。依赖前述整合候选，不能直接合并主线。

### 2026-11-19 检查点顺序与实时状态持有者整合演练（本地，待验证）

- 将 #510 检查点 `prepare_and_persist` 与 #511—#513 的 `ActiveRuntimeLiveValues` 在独立演练分支组合。冲突点是旧 #510 的 `nonlocal context` 绑定闭包；改为 `live.bind_prepared_checkpoint` 绑定方法，保证准备阶段异常时仍先回绑最新 state/context，不重引入双重上下文所有权。整合影响集 **123 passed**，Ruff、差异检查及 mypy 基线 **115/125** 通过；真实模型和检索 `not_run`，本地 L3 `not_run`。该演练不代表任何现有 PR 已合并，也不替代精确远端 HEAD CI。

### 2026-11-19 波次交接绑定协议（叠加候选，待验证）

- 在 #512 的上下文单一持有之后，`ActiveWaveSettlementHandoff.for_live_values()` 显式接受仅含 `state/cursor/context` 的 `LiveWaveValues` 协议，负责捕获和回绑快照；`execute()` 不再定义 `bind_wave_snapshot` 内部函数或快照捕获 lambda。测试使用真实 `ActiveRuntimeLiveValues` 构建波次场景，删除测试自己维护的重复绑定逻辑。
- **冻结契约**：`settle()` 的 `try/finally` 回绑、检查点失败后的最新投影回读、steering 处理与发布顺序保持不变；没有更改持久化格式、预算/模型调用、检索策略。本片属 P3 / static / orchestration-contract / engineering-only；真实模型与搜索 `not_run`，预算授权 `not_applicable`。此片是叠加 PR，必须等前序 #511/#512 验收后再重挂主线。

### 2026-11-19 持久化上下文单一持有（叠加候选，待验证）

- 在游标单一持有候选之上，分支 `codex/research-context-single-owner-20261119` 将一次 `execute()` 的持久化 `research_context` 交由同一 `ActiveRuntimeLiveValues.context` 持有；不留与其并行的局部字典。Deep 预检、游标恢复、steering 刷新、规划、检索/读取、模型回调、证据整理和波次交接通过该持有者读取当前上下文。
- **冻结契约**：检查点仍是 `prepare → finally 回绑 state/context → persist → 持久化 context 回读`；波次交接仍一次性回绑 state/cursor/context；模型尝试、预算结算、证据发布、Deep 预检和持久化结构均不增删动作。负控覆盖检查点/波次替换后回调读取最新字典、不同执行默认上下文隔离。本片属 P3 / static / orchestration-contract / engineering-only；动态模型与真实搜索 `not_run`，预算授权 `not_applicable`。
- 此片依赖游标候选；检查点顺序独立 PR #510 尚未整合时，不在本片同时改变检查点实现。验证结果以本分支精确 HEAD 和后续 PR CI 为准。

### 2026-11-19 运行期游标单一持有（当前独立候选）

- 基于 #508 已合并的 `main@455e1105`，分支 `codex/research-cursor-single-owner-20261119`；与仍待 CI 的检查点顺序 PR #510 分开，不提前合并两批语义。`ActiveRuntimeLiveValues` 除 `ResearchState` 外开始唯一持有 `ResearchRuntimeCursor`：执行器内的游标赋值、恢复后替换、外部调用审计、读取观测、模型回调、波次结算与检查点都使用 `live.cursor`；移除专为模型回调回写外围游标而存在的 `set_model_cursor` 闭包。
- **冻结契约**：持久化 `context` 仍只在执行器持有；不复制游标到其他可变持有者。两次中断尝试恢复、模型开始与完成审计、查询开始与结束、波次交接与检查点的位置和次数不变；`ResearchRuntimeCursor` 持久化结构与预算结算不变。新负控覆盖模型/读取回调跨游标替换读取最新值，以及不同运行不共享默认游标。真实检索、付费模型和动态比对 `not_run`。属于 P3 / static / orchestration-contract / engineering-only；整合及 CI 以候选精确 HEAD 为准。

### 2026-11-19 检查点准备与持久化顺序封装（当前候选）

- 后续本地补强：检查点专项测试共用统一构造器，新增成功路径顺序负控，明确 `bind_prepared` 必须先于仓库 `checkpoint`；检查点、实时状态、波次结算和守卫专项集 **10 passed**，未触及生产代码。此补强仍属于未推送的同一候选，不能代替 L3 或远端 CI。
- 基于上一状态单一持有候选 `e13960c8`，分支 `codex/research-cursor-context-20261119`。将主动执行器检查点内的 `prepare → finally 回绑状态/上下文 → persist` 提取为 `ActiveRuntimeCheckpointContext.prepare_and_persist`，明确准备异常后仍回绑已投影的内存值，同时禁止失败后继续持久化；执行器仍唯一持有实时状态、游标和持久化上下文，后两者不作双份镜像。
- 专属负控冻结 Claim Engine 序列化异常时预算投影与游标上下文保留、仓库不写入；检查点、实时状态、波次结算、守卫与主动执行影响集 **93 passed**，Ruff、差异检查及 mypy 基线 **115/125（无新增）**通过。全量 L3 已启动但观察到首 1% 用时较长，为避免无界后台执行而中断，**尚未通过**；远端精确提交 CI 待验收。真实搜索、付费模型与动态比较 `not_run`，预算授权 `not_applicable`。属 P3 / static / orchestration-contract / engineering-only。下一片在主线整合后处理游标、持久化上下文的单一所有权，不在本片同时迁移。

### 2026-11-19 研究状态单一持有（新独立候选）

- #495 的精确 HEAD `cd85309d`、CI `44359098528` 成功，已合并 `main@5c695ff8`；#502 的精确 HEAD `e7d2ebf1`、CI `44361647146` 全部成功、审阅线程为空，已合并 `main@47c8f041`。本片基于这两项收口后的主线，职责属 **P3 / static / orchestration-contract / engineering-only**，付费模型、真实搜索及动态产品比对 `not_run`，预算授权 `not_applicable`。
- `ActiveRuntimeLiveValues` 成为一次主动研究执行中 `ResearchState` 的唯一可变持有者。`execute()` 里的 86 处状态引用统一由 `live.state` 读取；规划、检查点准备、steering、预算刷新、证据投影和波次交接产生的新状态均写回该持有者。预算时钟和模型准入绑定持有者方法，跨检查点/恢复回绑后读到的始终是同一份实时状态。
- **冻结顺序与语义**：检查点仍先准备投影、即使序列化失败也先回绑局部状态/上下文，再持久化；模型尝试的开始审计→检查点→调用、完成计费/游标更新与后续检查点原位保留；波次完成、窗口观测、超时分支的诊断→检查点顺序不变。无持久化格式变更、无额外预算采样、检索/读取、证据发布或模型调用次数变更。`cursor` 和持久化 `context` **暂留执行方法局部变量**，不在本片复制进持有者；后续分别迁移单一所有权。
- 专属负控冻结「状态替换后，预算时钟与模型守卫同时读取恢复后的硬时限」；主动执行、Deep、检查点和恢复影响集 **156 passed / 1 skipped**，Ruff、差异检查及 mypy 基线 **115/125，无新增错误**通过。**全量 L3 与精确远端 HEAD CI 待验收**；不据此宣称产品体验改善。

### 2026-11-19 读取观测实时绑定（已合并）

- #493 的精确 HEAD `cee81a55`、CI `44351248954` 成功并合入 `main@083a0172`；#494 的重挂 HEAD `ee05454e`、CI `44357775209` 成功并合入 `main@cf54cc59`。#495 模型预算状态绑定提交 `cd85309d`、CI `44359098528` 成功合入 `main@5c695ff8`；本片 #502 的精确 HEAD `e7d2ebf1`、CI `44361647146` 全绿，已合入 `main@47c8f041`。
- 新增短生命周期依赖的 `ActiveReadObservationContext`，统一绑定生产读取器需要的最新 `context`、`cursor.wave_index`、相位开始/结束及重试耗时钩子。保留当前值读取回调，且在 `phase_end` 时重新获取可能已被检查点替换的 `context`；观测对象没有修改研究状态、游标、读取重试策略、预算或持久化的权限。
- 两条专属测试共享同一时钟/游标/上下文造景，冻结「相位开始之后上下文被替换，计时仍写入最新上下文」和「波次索引变化、重试计数仍读取最新游标/同一账本」。基于已合并 #494 的主线，生产读取语义、计时、主动执行与恢复整合影响集 **134 passed**，Ruff、差异检查和候选精确 HEAD CI 均通过。**P3 / static / retrieval+orchestration / engineering-only**，付费搜索及模型 `not_run`。

### 2026-11-19 搜索单次执行上下文（已合并）

- #490 已通过精确 HEAD CI `44347405572` 并合入 `main@56ebfd6f`；#493 的整合树已完成精确提交验收并合并，#494 的检索执行独立片以重挂提交 `ee05454e`、CI `44357775209` 成功并合入 `main@cf54cc59`。
- 从主动执行器的逐查询 `search_exact` 闭包抽出短生命周期 `ActiveSearchQueryExecution`；它显式接受本次查询的 `context/cursor/claim_id`、预算时钟、网关和相位计时器，持有该次 provider audit。旧的搜索发现顺序号、最新定向提示解析、可信线索提示提取都移入同一检索/观测模块；旧 `_lead_hints_for_claim` 通过执行器导入兼容现有测试及调用方。
- 冻结边界：`begin_external_attempt → checkpoint → search`、`finally finish_external_attempt → checkpoint`、查询结果归档后再次 `checkpoint` 不变。搜索超时计算仍取当次实时剩余硬预算且保留最终化预留；`last_search_audit → 搜索发现诊断 → phase_timing.end` 顺序不变。上下文不写回持久化、不结算预算，也不发布证据；搜索异常仍由候选池映射为 unavailable。
- 新测试共享搜索场景搭建，覆盖成功时实时截止时间/审计/发现序号/相位计数，以及异常时相位关闭且不伪造审计；影响集 **115 passed**。属 **P3 / static / orchestration+retrieval / engineering-only**；动态搜索与付费模型 `not_run`，预算授权 `not_applicable`。

### 2026-11-19 研究结构整合收口（以精确提交为准）

- #488（研究窗口检查点顺序）CI `44344609900` 成功，合并 `main@caefa350`；#489（执行守卫与实时预算）CI `44345569048` 成功，合并 `main@51da57f2`。两项均已确认无审阅线程，使用精确 PR HEAD 保护合并。
- #490（证据身份实时投影）与 #493（波次状态交接）在同一执行器上有交叠。基于 `main@51da57f2` 依次整合二者，修复 `gain_history` 恢复路径的一处冲突：必须先执行 `ResearchWindowDiagnostics.record_end`、再 `checkpoint()`、最后 `wave_handoff.settle(...)`，不能因替换旧 `settle_wave` 丢掉窗口检查点。合并演练 **96 passed**，Ruff/差异检查通过；该结果仅证明本地整合树，不替代远端精确提交 CI。
- #490 后续 CI `44347405572` 成功并按 HEAD 保护合入 `main@56ebfd6f`；#493 整合树 `cee81a55` 的 CI `44351248954` 成功、审阅线程为空，按 HEAD 保护合入 `main@083a0172`。真实搜索、模型、付费动态测试未运行。

### 2026-11-19 研究窗口检查点顺序显式化（独立候选）

- 基线 `main@739d74f7`，分支 `codex/research-context-next-20261119`。将 `execute()` 内四个 `record_research_window` 闭包调用展开为显式的 `ResearchWindowDiagnostics.record_end(context, hard_seconds=state.budget.hard_timeout_seconds, elapsed=elapsed, exhausted=...)`，随后按原位置调用 `checkpoint()`。诊断仍由专属上下文写入，检查点仍由原执行器控制；观察时钟每次仍取样两次，预算耗尽分支原有的后续额外检查点仍保留。
- 不触及恢复游标、费用预留及结算、状态序列化、模型请求或发布权威；不进行真实搜索/付费调用。下一片聚焦执行器的其他隐式共享变量，优先做具备对应回归用例的窄范围切分；本候选测试与提交状态以实际执行记录为准。
### 未接线的配置缓存与性能日志工具退役（2026-11-19，独立减负片）

- 旧 `src/config.py` 的 `get_config/validate/reload_config` 及模块级缓存没有
  现行调用方；生产 `src/llm_client.py` 已直接从 provider 环境配置读取并以
  凭据、端点和重试配置签名自动刷新缓存。旧 `reset_client()` 唯一调用方
  是 `src/config.py`，其专项测试只检查源码字符串是否存在。
- 旧 `src/perf.py` 的 `PerfTracker/PerfMetrics/write_perf_log` 同样没有
  生产、脚本、CI 或测试调用方；现行性能观测由研究运行器及独立诊断
  模块承担。本片成组移除两个孤立模块、旧重置函数和源码存在性测试，
  用现行同步/异步 Provider 客户端行为测试直接验证凭据变化后的缓存更新。
  Ruff 全库及 `git diff --check` 通过，配置/Provider/会话/打包影响集
  **127 passed**。不更改生产 Provider 调用、真实预算或研究检查点语义，
  且不发起真实模型 API；L3 未运行。
### 未接线的旧 Discovery 适配器退役（2026-11-19，独立减负片）

- `src/web/research/discovery.py` 持有一套历史 `DiscoveryRequest/Hit/Batch`、
  `DiscoveryProvider` 和未注册的 `LegacyDiscoveryAdapter`；全仓生产、测试、
  CLI、路由及注册机制都没有导入它或其符号。正式检索已经使用
  `src/web/research/retrieval_backends.py` 的独立 `DiscoveryRequest` 契约。
- 整个旧模块删除，不增加同名重导出、兼容 shim 或只验证删除结果的测试；
  现行检索、浏览器、查询预算、状态恢复和证据发布契约均不变。
  本片为 P3 离线工程减负：Ruff 全库通过，检索后端/主动研究适配器/
  诊断观测/主动研究运行器影响集 **129 passed**，`git diff --check` 通过。
  不声称提高检索质量，也不发起付费 API 调用；L3 未运行。

### 2026-11-19 模型尝试实时预算状态绑定（独立候选）

- #493 的精确 HEAD `cee81a55`、CI `44351248954` 已成功并合入 `main@083a0172`。#494 搜索执行上下文以相同文件树重新挂到此主线，精确 HEAD `ee05454e` 正在等待新 CI `44357775209`；上一 HEAD 的绿色 CI 不替代本次重挂后的验证。
- `ActiveModelAttemptContext` 现在显式接收 `current_state()` 和 `ensure_budget(state)`，而非隐藏了当前状态读取的无参预算回调。模型网关触发开始回调时，顺序仍为：检查当前操作有效性 → 读取最新 `ResearchState` 并按原硬预算规则验证 → 写入 inflight 模型尝试 → durable checkpoint → 真正发送。模型结束仍只更新内存审计，等语义结果的原检查点一起入库。
- 共享既有模型尝试造景 `_callbacks`，增加检查点/恢复重新绑定后的预算状态身份负控；不改变尝试次数、成本预留/结算、恢复游标、模型网关路由或任何持久化格式。L1 影响集 **108 passed**，Ruff、差异检查通过；mypy **115/125，无新增**。**P3 / static / orchestration+model / engineering-only**；动态搜索、模型和付费调用 `not_run`，预算授权 `not_applicable`。独立 PR 和精确提交 CI 以远端状态为准。

### F2 历史双读取器配对实验退役（独立片）

- `tools/run_f2_paired.py` 对固定六类本地页面重复运行旧 default/Crawl4AI
  采样，是 §143-B 阶段的手工表征实验；无生产、前端、CI/阶段门或其它当前
  资格工具调用。连同只验证其报告逻辑的 `tests/test_f2_paired_harness.py`
  一并退役。**保留**供当前 Crawl4AI 集成测试使用的
  `tools/f2_paired_fixture_server.py`；`tests/test_reader_task_request.py`
  的可选真实环境操作员测试直接指向共享夹具，并将以前从实验脚本导入且
  未撤销的 SSRF 放宽补丁改为 pytest `monkeypatch` 生命周期内的局部放宽。
  生产读取链、安全策略、升级后端、请求契约和历史结果档案不变；不进行外部读取。

### Search-to-Answer-1 历史检索层基线退役（独立减负片）

- 旧 `tools/run_search_to_answer_baseline.py` 只在 2026-10-28 的冻结题库上测量
  搜索和前两个结果的技术读取，不测最终回答、证据判断或多轮研究。实际使用者
  仅是专属 `tests/test_search_to_answer_baseline.py`；生产、前端、其它工具与 CI
  无调用，并且存在独立的当前搜索阶段门覆盖。成组移除该工具、专项测试、仅供
  它们使用的 `tests/fixtures/search_to_answer/baseline_v1.json`，同时从
  `tests/stage_gates.json` 的 `search_flow` 注册中摘除。旧评测报告保留为历史
  档案并注明不可从现行 HEAD 运行；正式 `GeneralWebGateway`、研究路由、
  搜索回退/读取/恢复/预算和当前搜索测试一律不动。无联网或付费测试调用。
### 2026-11-19 波次状态快照回写上下文（独立候选）

- 基线 `main@739d74f7`，分支 `codex/research-wave-state-handoff-20261119`。新增 `ActiveWaveSettlementHandoff`，明确从运行器捕获 `state/cursor/context` 快照、结算后（含异常）将快照写回实时状态，以及检查点执行失败时将内存中部分更新重新交还给结算快照。移除原 `settle_wave` 内部函数，将两个结算入口交给上下文；运行器仅保留一处显式 `bind_wave_snapshot` 写入接口。
- 原 `settle_completed_wave` 函数仍直接调用 `checkpoint()`，因此指标 `checkpoint_timing.caller` 保持现有标签；检查点、预算结算、恢复、波次决策和发布顺序不变。新增异常路径与原调用方标签负控，两条异常测试共享同一运行快照构造，避免重复造景；不调用外部检索或付费模型。#488–#490 各自为独立待审 PR，不混入本候选。

### 旧 HTTP 研究入口退役（待精确提交验收）

- `codex/retire-web-lookup-compat-20261118`：仓内唯一实际使用旧
  `POST /web-lookup-runs` 的真实验收脚本 `tools/studyctl_live.py`
  已迁至正式 `POST /research-runs` 创建、再用 `POST /research-runs/{id}/search`
  执行。完整退役四条 `/web-lookup-runs` 兼容路由、其无用转发函数、
  `NewsLookupRequest` 模型及旧入口专项测试；正式研究恢复测试补足
  `/research-runs` 读取/列表覆盖。`docs/TECH_STACK.md` 的现行调用说明同步迁移。
  **保留**供评测及业务继续调用的 `WebLookupService.lookup()`，研究持久化、
  恢复和预算逻辑不变。本项尚未进行真实服务/付费检索验收；合并状态以对应 PR 为准。

### 2026-11-19 研究检查点证据身份投影（独立候选）

- 分支 `codex/research-checkpoint-live-evidence-20261119`，基线 `main@739d74f7`。`ActiveRuntimeCheckpointContext.prepare()` 使用自身已有的 `results` 和 `run_id`，从当前结果缓冲区直接计算证据 ID；移除只服务该检查点的 `known_evidence_ids` 外部回调传参。波次结算上下文也直接持有结果缓冲区和运行 ID，以现有结算位置生成最新证据 ID。两处回调改为显式依赖后，证据身份仍由单一结果缓冲区投影。
- 新增专属检查点测试、波次结算测试，覆盖两次准备之间结果变化、预算时间重新取样，以及结算上下文创建后新增证据的读取。阶段、预算、游标、Claim Engine 状态与诊断指标的原检查点顺序不变；不修改恢复模式、波次停机决策、持久数据格式和费用语义。前一阶段的 `#488` / `#489` 尚属独立 PR，不并入本片；CI/合并情况以精确提交为准。

### 当前研究结构收口（精确合并）

- **2026-11-18 新收口**：故障游标显式更新 [#454](https://github.com/2002yy/study-agent/pull/454) 的 HEAD `691000e7`、精确 CI `44296684690` 成功，审阅线程为空，已用预期 HEAD 保护合并 `main@4bb5a6bd`。原 17 处故障写入不再经由捕获当前游标的内层闭包；失败标识、去重、恢复与检查点位置不变。
- **预算片已合并**：[#457](https://github.com/2002yy/study-agent/pull/457) HEAD `42850d71`，精确 CI `44301137902` 成功，审阅线程为空，按预期 HEAD 合并 `main@7aa32510`。`execute()` 不再通过捕获 `state/cursor` 的 `update_budget` 闭包更新四处预算；三个读取路径和预算耗尽分支仍各自原位取样、检查点，`reserve_call`、恢复和费用结算不变。整合影响集 **137 passed**、阶段门 **458 passed/4 skipped**、mypy **115/125**。
- **测试造景去重**：[#458](https://github.com/2002yy/study-agent/pull/458) HEAD `bc071bf7`，独立删除 `_cutover_service` 的重复构造，净减 **37 行**，原完整主动研究运行器 **84 passed**；精确 PR CI `44302192557` 最近观察仍在运行，不提前当作已合并。
- **下一独立候选**：`codex/research-window-explicit-state-20261118`（原远端提交 `78e61a80`）；四个 `record_research_window` 调用显式传入当前 `state/context`，保留原诊断→检查点、两次耗时取样及预算/发布权威。已无冲突整合 `main@7aa32510`，本地影响集 **93 passed**、Ruff/diff-check、mypy **115/125** 通过；远端精确 PR CI 尚未执行。
- 本轮核验主线：`main@f7531d19f7716198d97b6c78ea5dcbca7f229e0b`（tree `3e428c04cde38b92d7faafc6d9bde063de7d3f7c`）；这是交接时刻快照，下一窗口仍须重新读取最新主线。
- 研究预算时钟 [#405](https://github.com/2002yy/study-agent/pull/405)：HEAD `8ba1b995`、精确 CI `44161777666` 成功，合并 `3ea013b6`。
- 当前 steering/波次结算 [#409](https://github.com/2002yy/study-agent/pull/409)：HEAD `ff6375a0`、精确 CI `44161971315` 成功，合并 `486bcf78`。
- 当前研究窗口/计时观测 [#420](https://github.com/2002yy/study-agent/pull/420)：HEAD `2d71a79d`、精确 CI `44162132016` 成功，合并 `7cbe6a94`。
- 共享证据结果缓冲区 [#422](https://github.com/2002yy/study-agent/pull/422)：HEAD `878e37d7`、精确 CI `44162348067` 成功，合并 `f7531d19`。
- 四片已依次对齐父分支、核对无冲突的主线合并树，并按预期 HEAD 保护成功合入。**合并后的最新 main CI 仍待独立确认**，不能把 PR 头提交的绿色 CI 冒充主线绿色。动态浏览器、真实模型及付费调用未运行。

### 2026-11-19 研究执行守卫上下文（独立候选）

- 以 `main@739d74f7` 为基线，分支 `codex/research-execution-guard-20261119`。新增 `ActiveResearchExecutionGuard`：取消检查固定使用当前 `run_id/operation_id` 查询仓库，硬预算检查显式接收当前 `ResearchState`，避免持有已被检查点/恢复替换的旧预算。执行器去掉两个捕获外围变量的 `ensure_active`、`ensure_budget` 内部函数；内部模型尝试仍以回调使用最新 `state`，其余五处预算准入显式传 `state`。
- 守卫不改变恢复游标、预算入账、计时样本、模型开始检查点或发布操作；保留既有异常类别及原导出。专项测试覆盖取消实时检查和恢复后预算上限变化，完整回归结果以本候选精确提交为准。#488 另属研究窗口诊断与检查点顺序片，不与本片混合。

### 历史减负候选快照（部分已合入，以下不是当前待办）

#### 历史召回/候选供应商资格工具整链退役（2026-11-19，独立片）

- 旧 §44A/§44C 研究阶段的“已知目标召回审计 → Brave API 资格评估 / URL 提案
  候选替代方案资格评估”未进入生产执行链；三套脚本只被彼此依赖及专属测试
  引用。现行代码、阶段门、CI、活跃文档均无调用方，旧决策背景保存在
  `docs/archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`。
- 删除 `run_recall_target_audit.py`、`run_brave_qualification.py`、
  `run_url_proposal_qualification.py` 及三份同名专项测试。旧冻结参数不再作为
  产品门槛维护；不补适配层、别名或空测试。正式 `research_url_proposal`、
  Browse 搜索和通用质量门不变。离线影响集 **112 passed**，Ruff 与差异检查
  通过；未执行 Brave API、DeepSeek、真实浏览器或其它付费请求。

#### CL-1D-1 单步会话实验编排器退役（2026-11-19，独立片）

- `run_conversation_step` 只由单步专项和旧 follow-up 集成测试调用；
  正式 `DeepSeekConversationService.start` 直接组合 `run_conversation_loop`，
  并由 `ConversationLoopSession` 管理流。删除旧 `conversation_action_step.py`、
  177 行专项测试及 follow-up 中重复的模型→工具→再决策→答复用例；
  同步移除阶段门 **16 处**无效注册、`tools/ci_scope.py` 的旧命名范围及
  合同测试，更新历史设计文档。保留正式 bounded-loop 的观察、暂停/取消、
  费用准入、终态及恢复测试，**不保留**兼容空壳。
- `TurnLifecycle` 仍涉及未来生产宿主/费用结算边界，不因未接入而删除。
  原定向 **288 passed**、会话 L1 **482 passed**、Ruff、diff-check、
  mypy 基线 **115/125**；未调用模型或付费 API。

- **2026-11-18 RQ1-C 成对归因实验链退役（独立片）**：
  `codex/retire-rq1c-paired-attribution-20261118`。旧 `run_paired_attribution.py`
  只调度同阶段 `run_rq1c_calibration.py` 和
  `run_environment_fingerprint.py`，三套工具没有现行应用、CI、阶段门或
  其他工具调用；旧产物仅供诊断，**不是**正式资格证据。连同唯一专属
  `test_paired_attribution.py`（20 个历史测试）整链删除，净减 **1,941 行**。
  保留正式 `run_rq1c_bounded_qualification`、冻结 holdout 清单、阶段门、
  成本/预算及相关现行测试；不改变生产搜索、研究恢复或预算决策。

- **2026-11-19 RQ1-C 无调用方 guard 二次转发模块退役（独立片）**：
  `tools/run_rq1c_bounded_qualification_guard.py` 只把正式预算守卫及资格
  实现的符号重新导出，重复提供 `main()`，没有活跃代码、测试、CI、
  阶段门或操作文档调用。该兼容壳已删除，不增补空桩、别名或专项测试；
  正式 `run_rq1c_bounded_qualification.py`、预算类型、8 次调用上限、
  硬截止、前置守卫和真实付费 API 权限边界不变。原影响集 **54 passed**；
  本片未执行付费资格实验，精确提交的更新验收以对应 PR 为准。

- **2026-11-18 旧 B-Search 离线目录实验退役（独立片）**：
  OPML 导入工具、静态信源目录、Top-K 目录召回模块及其专项测试只连接
  `tools/run_research_tool_agent.py` 手动实验入口，无生产请求、现行 CI、
  阶段门或用户任务调用方。成组退役该工具链、目录配置和专属测试；
  将唯一被当前 `entry_selection` 使用的中英文分词逻辑移入正式相关性模块，
  以现行准入测试继续覆盖连续中文的二元分词。`research_tool_agent` 本体、
  `research_shadow_seam`、页面准入/证据门、恢复和计费逻辑均保留。
  本次只做离线静态减负，不发起模型、搜索或付费调用。

- **2026-11-18 旧 §44B 提供商归因实验退役（独立片）**：
  `run_provider_attribution.py` 的旧三提供商归因/地区化判定仅由本身的
  专项测试调用，无生产路由、当前 CI/阶段门或在用执行入口；成组移除
  工具及其测试。Brave 资格工具先解除从旧实验导入两个字符串检查函数的
  隐式依赖，直接在自身定义并由现行 Brave 测试覆盖深层路径/CJK 统计。
  不修改实际搜索路由、资格门槛和预算/恢复契约；不运行外部搜索。

- **2026-11-18 付费样本演示入口退役（独立片）**：
  `tools/run_sample_research.py` 的 `--execute` 分支实际上只打印指导文本，
  不发起 Chat/研究请求；仓内没有真实调用方、CI 配置或专属测试。删除这一
  已失去执行价值的示例工具及其独占的 `LLM_SAMPLE_PAID_RUN_CONFIRMED`
  约定。**保留**独立的 `tools/precheck_sample_budget.py`、
  `tests/test_spend_boundary_controls.py` 和生产预算账本/真实验收流程，
  因为它们仍承担有效的费用安全检查；历史文档的原始文件清单不追溯修改。

- **2026-11-18 虚假跨层测试清理（独立片）**：两项 Python 测试
  名为“前端刷新竞态”和“部分接口失败保留旧状态”，实际只重复请求
  `/health`，既未制造竞态也未触发接口失败。移除这些误导性的
  旧专项测试，改由 `frontend/src/api.test.ts` 直接验证旧响应晚到
  不覆盖新结果，以及 RAG 状态暂时失败时保留前次有效快照并显示错误。
  同时删除允许缺少 CORS 响应头仍通过的伪跨层检查；真正的开发环境
  默认允许来源与预检响应已有 `test_cors_policy.py`、`test_api.py` 覆盖。
  此外删除未经注入搜索桩、会意外调用真实检索服务的新闻安全模式专项测试
  （安全模式持久化已由 `test_news_service.py` 覆盖），以及仅断言后端返回
  搜索词、却声称验证前端按钮失效的旧测试；保留能实证正文传入摘要的链路检查。
  另删除手工创建却没有撤销补丁、可能污染后续用例的群聊会话标记专项检查：
  对应标记和群聊隔离已由 `test_wechat_service.py`、`test_api.py` 分别覆盖。
  只调整测试与交接，不更改运行时；验证状态以对应 PR 为准。

- **2026-11-18 交互历史阶段一报告脚本退役（独立片）**：
  `tools/interactive_history_report.py` 是仅需手工指定 SQLite 库的阶段一
  压缩前后比较脚本，库内无其它调用方、CI 配置、专属测试或发布依赖。
  删除该一次性报告入口；保留正式聊天上下文使用的
  `src/interactive_history.py` 及 `tests/test_interactive_history.py`，
  继续检查用户原文保留、版本来源和历史压缩契约。

- **2026-11-18 M4-D 一次性补丁演示退役（独立片）**：确认
  `tools/interactive_patch_demo.py` 只作为历史手工演示入口使用，
  `frontend/e2e/acceptance/incrementalPatch.spec.ts` 只在设置
  `M4D_PATCH_DEMO_DIR` 时执行；生产代码、现行 CI 和正式 UI 均无调用。
  整组删除演示运行器及其专属浏览器用例，把原先误从演示工具导入的
  测试构造函数移入 `tests/test_interactive_patch.py`。
  **当时**保留 `src/interactive_patch.py`、恢复契约以及增量修改/能力继承的
  单元测试。后续证实补丁核心 `prepare_patch/PatchCandidate/TextEdit` 仅由
  两份测试调用，未接入正式 API、会话、前端、CLI 或阶段门；本独立片删除
  原型模块与整份专属测试，Three 能力测试改为直接覆盖正式
  `interactive_history` → `interactive_restore` 的版本恢复和冲突语义，
  并在历史原型文档中撤销过时演示命令。保留正式恢复、版本识别、Three
  沙箱加载及其测试；不补兼容空壳。原离线影响集 **82 passed**、Ruff、
  diff-check、mypy 基线 **115/125** 通过；未执行付费 API。

- **2026-11-18 M4-C3 历史实验闭环退役（独立片）**：
  11 月 4 日固定批次已有原始结果和费用回执，今天的产品/CI 不再调用当时的
  付费样本执行器与一次性数据调查工具。成组移除 M4-C3 的五个执行/预算/导出
  脚本、五个专项测试、两个配置、冻结提示清单和已过时的执行说明；
  同时退役旧 SQLite 大范围扫描/导出工具及其一次性浏览器重放用例。
  保留 `docs/M4C3_FIRST_RESULTS_2026-11-04.md` 历史评测事实、
  `frontend/e2e/fixtures/m4c3-first` 的原始失败样本及正式源码恢复测试，
  保留沙箱双视口语义/Three 按需加载用例。真实预算闸门、
  `src/interactive_history.py` 和生成/发布路径不变；无付费调用。

- **2026-11-18 M4-C 候选轨迹离线审计退役（独立片）**：
  `tools/audit_tool_agent_candidates.py` 仅消费旧运行记录生成供人工查看的
  `m4c-tool-agent-candidate-audit-v1` 报告；全库没有正式业务、CI、阶段门或
  其他工具调用它，只有 `tests/test_tool_agent_candidate_audit.py` 检查其输出。
  成组删除这个阶段性报告器和全部专属测试。保留生产运行时真正生成的
  `candidate_trace`、`candidate_audit` 观测字段和现行 Web Tool Agent 测试；
  旧集成收口文档中对应的历史文件列表不追溯篡改。

- **2026-11-18 旧记忆接口与专项测试退役（独立片）**：以
  `main@d879a4af79d99521129f361e07866cedc3fa0064` 为基线。
  前端现行记忆操作已由 `POST /memory-runs` → `POST /memory-runs/{id}/commit`
  承担，仓库内已确认旧 `POST /memory/preview`、`POST /memory/commit` 无生产调用方；
  移除两条兼容路由、旧响应模型、前端无调用封装及其专项测试。
  将剩余的预览格式、非法目标、重复替换、只读模式拒写负控集中到
  `tests/test_memory_run.py` 的正式运行流程，保留运行记录、哈希冻结、权限与恢复契约。
  静态验证与精确提交 CI/合并状态须以对应 PR 为准；无付费模型调用。

- **2026-11-18 RAG 索引旧接口退役（独立片）**：基线
  `main@95fdbe964990eab6329c7e36c244b416eea0afb3`，候选分支
  `codex/retire-rag-index-compat-20261118`。核实前端、工具和 CI 无
  `POST /rag/index` 调用，正式入口是 `POST /rag-runs/index`；删除旧
  同步响应转换适配，8 处测试调用统一改用正式接口。保留仍被前端使用的
  `/rag/upload`、`RagIndexResponse` 和 `/rag` 代理前缀。L1 **57 passed**、
  Ruff 和差异检查通过；无模型调用。精确 HEAD CI/审查及合并状态见对应 PR。

- **2026-11-19 无调用方的研究匹配/调度包装函数退役**：
  `facet_coverage._contains` 和 `scheduler._lead_is_schedulable` 都没有生产、
  工具、测试或阶段门引用，分别是旧的全词匹配和线索调度包装，直接删除，
  不增加空测试、适配或配置。现行 `_pattern/_term_positions`、
  `is_schedulable_lead` 与 `plan_read_wave` 不变。另有 `_prose_score` 疑似死代码，
  但扩展测试的 `test_goal_evidence.py::test_agent_records_evidence_per_goal_and_keeps_records_apart`
  在未改动的主线上已有失败，因此不在此片混删相关证据路径或失败测试。
  原匹配/调度/读取影响集 **84 passed**，Ruff、差异检查与 mypy 基线
  **115/125** 通过；无真实搜索或付费调用。

- 上轮历史减负收口：[#449](https://github.com/2002yy/study-agent/pull/449)
  精确 CI 成功，合并 `32ed94f5`；[#450](https://github.com/2002yy/study-agent/pull/450)
  精确 CI 成功，合并 `92243d58`；[#452](https://github.com/2002yy/study-agent/pull/452)
  精确 CI 成功，合并 `34c02510`。三片删除旧实验执行器及专项测试、合并重复
  的抽屉入口测试、退役 `POST /rag` 根路径别名及其测试；只作为离线工程减负，
  不代表动态检索质量改善。

- **2026-11-18 旧提供商路由实验退役片（独立于研究运行器重构）**：基线
  `main@ee0f7c284c4074d9334efc4f13ce955325a59b0a`，工作分支
  `codex/retire-orphan-tools-20261118`。移除无生产、CI、阶段门调用方的
  `tools/run_provider_routing_replay.py` 与专属 `tests/test_provider_routing_replay.py`，
  不再维护旧 E0–E3 历史重放策略；留存历史数据/报告及当时供 Browse 搜索探针使用的
  `qp1c_queries_v1.json`（探针后于 2026-11-19 退役）。局部检索影响集 **27 passed**；Ruff 通过，
  无模型/API 费用。此项仅为离线工程清理，不代表检索效果变化或动态验收。
  PR #449 已通过精确提交 CI 并合并；不影响独立研究运行器重构片。

- **2026-11-19 旧 Browse 四站点小样本探针退役（独立片）**：
  `tools/probe_browse_engines.py` 只对 QP1-C 的 A01/A05 两题手工循环
  Google、DuckDuckGo、Bing、Brave 打印 URL，没有生产、CI、测试、
  阶段门或其它工具调用方。删除孤立脚本及旧复测命令，但保留历史
  `BROWSE_ENGINE_PROBE_20261115.md` 观测和 `qp1c_queries_v1.json`
  题集来源；正式 Browse 路由、站点选择、SSRF、人机验证终止规则不动。
  离线 Browse/站点池/搜索策略/工具网关影响集 **60 passed**，无真实
  浏览器或付费 API。新精确提交 CI 以本片对应 PR 验收为准。

- #406：移除无前端调用方的新闻运行客户端兼容接口及对应历史测试，约净减 530 行。
- **2026-11-19 微信旧兼容门面退役（独立减负片）**：`src/wechat.py`
  是历史拆分后没有正式生产/路由/CLI 调用方的转发 facade，仓内仅有
  经门面导入的行为测试和 `test_wechat_decoupling.py` 源码存在性检查。
  成组删除门面及其专属架构测试；新闻正文、去重、群聊状态的有效测试
  直接导入现行 `wechat_state/generator/format` 和新闻模块，并在临时目录
  隔离群聊状态。同步修正打包必需文件清单，防止废弃模块误当依赖。
  正式聊天、微信及新闻的业务/费用契约不变；无真实模型或浏览器调用。
- #407：移除 17 份只供历史阶段使用的单次实验脚本及配套专项测试，净减约 4,495 行。
- **2026-11-18 匿名平台探测实验退役（独立片）**：原
  `qualify_anonymous_platforms.py` 只对四个固定公网 URL 发一次匿名 HTTP
  请求，结果始终标为 `qualified=false`，既未接入产品，也无法证明
  视频/站点读取能力。移除脚本、其两类专项模拟测试及阶段门中的旧条目；
  `discovery_platform_contracts_v1` 仍执行正式的来源搜索、来源评估和
  Web Tool Agent 测试。不改平台接入、真实浏览器读取或鉴权流程，
  不发公网请求。
- **2026-11-18 无调用的会话手动落盘链路退役（独立片）**：前端已用
  SQLite 会话列表/详情和正式归档流程，没有 `flushSession` 调用；同步移除
  `POST /sessions/{id}/flush`、后端 `SessionService.flush_session`、
  仅服务该入口的当前 Markdown 导出方法，以及无人引用的前端
  `loadSessions`/`loadRagStatus` 快捷封装。原先以手动落盘制造旧镜像的测试
  改为直接构造历史镜像，继续验证归档清理、失败恢复和清理失败保留归档，
  不删旧版文件导入器，也不改变 SQLite 会话和归档的产品契约。
- **2026-11-19 旧 session logger 镜像整体退役（独立片）**：
  正式聊天与恢复由 SQLite `ChatThread/ChatTurn`、`SessionService`、
  `LegacySessionImporter` 承担。`src/session_logger.py` 的 `log/flush/save`
  从未填充正式会话 `_state`，`src/session_store.py` 只服务这个旧镜像；
  微信群读取最近单聊和写入旧 `wechat_interactive` 标记没有真实上游。
  同步删除两模块、专属 flush 测试、只检查其源码结构的打包断言、
  过时微信状态桩及重复列表用例。历史 Markdown 导入/恢复测试改为
  直接构造旧快照，保留正式 SQLite、学习记忆和预算/恢复行为。
  原离线影响集 **128 passed**、扩展会话/微信 **170 passed**、
  学习记忆 **28 passed**；Ruff、差异检查及 mypy 基线 **115/125**
  通过。无真实模型或付费搜索。
- 本轮独立片：移除 `src.api` 的旧测试打桩重导出和生产 `_api()` 回绕桥接；实际调用改向模块所有者，测试与真实测试入口同步迁移，并让两项微信正文安全测试不再依赖真实域名解析。保留 `from src.api import app` 公共入口；不删除持久数据、恢复和费用约束。此条是本地待提交状态，不代表 CI 通过或已合并。

上述候选都基于同一主线快照开展，合并前须逐个核对最新主线、差异和文档重叠；另一个窗口的研究运行器职责拆分不得与这些减负片混写。

### 研究运行器职责拆分续片（2026-11-18）

- #466 检索库存读取诊断的最新上下文修复已合并 `bf9d39ca`；#470 Tier-2 提议诊断的最新上下文修复，精确 PR CI `44316133679` 成功，已合并 `209f50f7`。
- 基于最新 `main@32ab17cf`，候选选择器显式接收 `live_context`，在模型调用后的上下文回填上记录选择诊断和编排调用次数；保持原候选集兜底、恢复检查点与预算结算时序不变。受测候选 `9d43b667`：161 项影响测试通过，Ruff、mypy 既有基线通过；新 PR / CI 待收口，非真实模型验收。
- 下一独立片：梳理选择诊断记录构造与性能采样的所有者，继续缩短大运行器；先冻结重复调用时的输入变化统计、计时采样顺序与环形记录上限，再迁移纯投影。不得混入新闻/API 清理。

### 权威基线（按精确 SHA 核实）

- 历史基线：`main@265bd4eaa438dafce84bde31eb9535ac17fefc32`（#406 合并后，tree `52147fdb1b0b366dd5ed7bf4e0d713f33c37028a`）；#403 的已验收父树为 `37be116f`。最新研究结构主线见上方当前研究结构收口；**新会话须重新获取最新 main**。
- **研究发布**：#360 已将 `simple` 设为默认：检索、读取正文、生成、检查引用属于已读 URL，再无损发布；`strict` 显式保留旧逐段校验。简单模式**不提供逐条事实已核实**的保证。历史 q9 曾一次完整输出（50.31 秒，3,173 字符），**不能据此认定跨题质量达标**。
- **检索**：#365 双通道与 #366 基于已读正文的缺口查询已入主线；双通道默认关闭。#368 中文社区浏览器在 `main@5f146a67` 合并，修复米游社游戏分区路由。#369 免费覆盖探针见下文；**搜索发现的 URL 不等于正文已读、可以引用的证据**。
- **DeepSeek 官方 Search / Fetch**：#370 于 `main@6a1c880e` 合并，仅预接入。两套 `ENABLED=false`、`MAX_REQUESTS=0` 独立默认关断；敏感 URL 和危险跳转不得发送至外部 Fetch。**未授权真实计费调用，未启用生产路由**。
- **交互 UI**：M4-A/B/C 与后续修复、Three、媒介选择能力已有静态交付；真实模型挑选媒介和自动修复成功率尚无动态验收结论。

### 本轮交付与验证（Static Loop；不冒充产品动态验收）

| PR | 已实施工作 | 精确证据 |
| --- | --- | --- |
| [#368](https://github.com/2002yy/study-agent/pull/368) | 中文站点浏览器及米游社分区修复 | 合并 `5f146a67`；PR 审阅/精确 CI 已收口 |
| [#369](https://github.com/2002yy/study-agent/pull/369) | 免费社区覆盖探针：fast / 浏览器增量 URL、实际读取、失败诊断，禁止继承错误搜索策略，付费开关开启时拒绝执行 | HEAD `9456271e`；合并 `faf1a94b`；CI `44034118706` 成功；审阅 P2 已修复 |
| [#370](https://github.com/2002yy/study-agent/pull/370) | 官方 Search/Fetch 双重默认关闭、安全校验、离线负控 | 合并 `6a1c880e`；精确 PR CI `44031322548` 成功 |
| [#371](https://github.com/2002yy/study-agent/pull/371) | 有日期、可复核的执行审计与工作树整理 | 合并 `e06b882e` |
| [#373](https://github.com/2002yy/study-agent/pull/373) | 研究运行器纯证据投影函数抽离：`active_research_runtime.py` 7,453→7,167 行 | 合并 `92af5937`；CI `44030559637` 成功；AST 函数体一致 |
| [#374](https://github.com/2002yy/study-agent/pull/374) | 网页读取证据与预算纯函数抽离：`web_lookup_service.py` 3,013→2,739 行 | 合并 `e5d4f037`；CI `44032955744` 成功；AST 一致 |
| [#375](https://github.com/2002yy/study-agent/pull/375) | 聊天研究发布策略抽离：`chat_service.py` 2,589→2,361 行 | 合并 `8fe57bc5`；CI `44032951521` 成功；AST 一致 |
| [#376](https://github.com/2002yy/study-agent/pull/376) | 读取调度纯测试独立成模块：`test_active_research_runtime.py` 5,934→5,458 行 | 合并 `fb527250`；CI `44033439005` 成功；67/67 顶层测试 AST 保留；补齐三项阶段门禁登记 |
| [#382](https://github.com/2002yy/study-agent/pull/382)–[#384](https://github.com/2002yy/study-agent/pull/384) | steering 状态投影、模型尝试预算判定归位；读取计划测试净删重 126 行 | 已合并；精确 HEAD CI `44074227494` / `44074756787` / `44075417217` 成功 |
| [#385](https://github.com/2002yy/study-agent/pull/385) | 冻结模型 inflight、阶段检查点及预算单调契约，保留崩溃恢复与费用结算负控 | 已合并 `383e6440`；精确 HEAD CI `44077179183` 成功 |
| [#390](https://github.com/2002yy/study-agent/pull/390) | 读取调度显式传入候选身份，后端尝试历史统一计算 | 已合并 `96ac38b6`；精确 HEAD CI `44086183784` 成功 |
| [#391](https://github.com/2002yy/study-agent/pull/391) | 阶段计时上下文拥有可变计时状态，替代执行闭包 | 已合并 `6e7e6c53`；HEAD `9f1a8c7f`，精确 CI `44089619882` 成功 |
| [#393](https://github.com/2002yy/study-agent/pull/393) | 读取诊断/后端健康记录迁出大运行器，保留旧导入入口 | 已合并 `5bcfc8a0`；HEAD `271010c3`，精确 CI `44100349280` 五项全绿 |
| [#392](https://github.com/2002yy/study-agent/pull/392) | 模型政策审计纯投影独立化，保留请求前持久化和预算结算原顺序 | 已合并 `cfe9ca16`；HEAD `c45b8287`，精确 CI `44106896286` 五项全绿 |
| [#394](https://github.com/2002yy/study-agent/pull/394) | 读取尝试游标/诊断上下文显式化、测试恢复游标重复解码去重 32 处 | 已合并 `b6c98f9d`；HEAD `7f7dbf7a`，精确 CI `44108108094` 五项全绿；#392 合并后同树验收 |
| [#395](https://github.com/2002yy/study-agent/pull/395) | 将读取预调度闭包迁为显式传入当前候选、游标历史、上下文、断路器和研究时钟的函数 | HEAD `f4c63a26`；精确 CI `44125608541` 成功，合并 `bd7fd5dc`；合并后 tree `9d96107b` 与验收树一致 |
| [#396](https://github.com/2002yy/study-agent/pull/396) | 研究窗口诊断独立化；保留两次时间采样和记录后检查点顺序，不改预算准入 | HEAD `bcd8d697`；精确 CI `44126675280` 成功，合并 `30c27cf2`；合并后 tree `02c395cf` 与验收树一致 |
| [#397](https://github.com/2002yy/study-agent/pull/397) | 读取链测试共用服务/运行记录/来源投影，净减 45 行，生产代码不变 | HEAD `8e781a64`；精确 CI `44127618845` 成功，合并 `4f46684d`；合并后 tree `7044d37f` 与验收树一致 |
| [#398](https://github.com/2002yy/study-agent/pull/398) | 模型准入政策以当前 `context` 显式入参；不变回调封装为 `RuntimeModelPolicyContext` | HEAD `25ae27cd`；精确 CI `44135910377` 成功，合并 `b4ae4291`；合并后 tree `69154167` 与验收树一致 |
| [#399](https://github.com/2002yy/study-agent/pull/399) | 故障记录显式读取当前游标/上下文，保持尝试 ID 与去重 | HEAD `b676659b`；精确 CI `44136804289` 成功，合并 `f2666db8`；合并后 tree `618e987f` 与验收树一致 |
| [#400](https://github.com/2002yy/study-agent/pull/400) | 模型尝试回调归入 `ActiveModelAttemptContext`，锁定开始检查点、费用前时序及完成后内存审计 | HEAD `b505fb3f`；精确 CI `44138134273` 成功，合并 `9abe320d`；合并后 tree `8e9fef3e` 与验收树一致 |
| [#401](https://github.com/2002yy/study-agent/pull/401) | 专家读取的路由、预算窗口与来源诊断归入 `ActiveReadSiteContext`；保持默认读取链为兜底 | HEAD `4d01a312`；精确 CI `44140163266` 成功，合并 `8f5a2ff0`；合并后 tree `50211070` 与验收树一致 |
| [#402](https://github.com/2002yy/study-agent/pull/402) | 三类有证据终态统一由 `ActiveResearchPublisher` 接收当前上下文和停止结果；检查点仍在执行器 | HEAD `a7d67a07`；精确 CI `44141917095` 成功，合并 `ef99b162`；合并后 tree `66a33f5f` 与验收树一致 |
| [#403](https://github.com/2002yy/study-agent/pull/403) | 波次结束停止信号纯投影：当前缺口、饱和阈值、恢复后迟到 steering，`ResearchStopGate` 仍独占裁决 | HEAD `3271c810`；133 passed、精确 CI `44145248671` 成功；合并 `f9332655`、tree `37be116f` 与验收树一致 |
| [#404](https://github.com/2002yy/study-agent/pull/404) | 共用切换/普通研究测试工厂，保留升级网关对象身份 | HEAD `ab298385`；84 passed；精确 CI `44146778208` 成功；待独立审阅及合并 |
| [#405](https://github.com/2002yy/study-agent/pull/405) | 独立研究预算时钟、Deep 恢复基线和窗口超时 | 原 HEAD `dec1dd3d`；精确 CI `44149454756` 成功；本次仅处理与 #406 文档冲突，合并修复后的新 HEAD 须重新验收 |
| [#406](https://github.com/2002yy/study-agent/pull/406) | 移除旧新闻前端包装与历史冗余测试 | 精确 CI `44150453199` 成功；已合入 `main@265bd4ea`，保留现存服务端持久化/API |

**当前结构片**：[#387](https://github.com/2002yy/study-agent/pull/387) 的 40 处测试初始化删重已合并 `main@315b07a1`，原 63 个测试函数与 474 条断言保持、84 passed，精确 PR CI `44079893336` 成功；[#386](https://github.com/2002yy/study-agent/pull/386) 将有序检查点封装为执行上下文，精确 HEAD CI `44080509512` 成功、合并 `df6f2a7e`；[#388](https://github.com/2002yy/study-agent/pull/388) 将结果缓冲区显式化，精确 HEAD CI `44080750573` 成功、合并 `0e72901d`。这些是各 PR 头提交的验证，不冒充合并主线后的独立 CI。重复的 #389 已关闭，未入主线。

这四项大文件工作是**职责拆分、单文件认知负担下降**，绝非宣称全库代码行数下降：新模块、测试和导入使合计行数略有增加。没有删除故障、恢复、权限、计费等关键回归。

### 测试与执行成本的量化基线

- 历史结构审计约 **588** 个 `tests/test_*.py` 文件、**5,917** 个测试函数定义；到 `main@f9332655` 增至 **601** 个文件，#406 合并后减至 **597**。预算时钟片（#406 合并前）同口径实测 `src/**/*.py` **149,719 行**、`tests/**/*.py` **152,805 行**，测试/主体约 **1.02:1**；这一数字是历史快照，不冒充当前主线。全仓结构相同的测试函数只发现 9 组、10 个额外定义，**不能仅凭测试行数与主体接近就机械批量删除**。
- #373 的一次完整后端 CI：**7,347 passed、21 skipped、1,376.13 秒**（约 22 分 56 秒）；单个最慢测试约 5.13 秒。主要负担是对小变更触发整套回归，不是个别慢用例。
- `tools/ci_scope.py` 目前只对 `developer-cli`、`conversation-decision`、`standard` 类别登记精准影响集；通用 `learning-backend`、新增纯研究模块仍常走全量。后续应按**明确文件→直接引用测试→下层契约测试**新增影响集，保留 L3 主线/发布门和未知路径保守兜底；不能靠跳过覆盖换速度。
- **2026-11-18 第一批删重（#406 已合入）**：删除无人调用的 6 个 NewsRun 前端包装、配套类型、旧工作台形状测试以及 v0.3 过时冒烟测试；净减 **530 行**、4 个后端和 1 个前端测试文件。保留新闻持久化/API 和当前研究路径；精确 HEAD `cfa14169` 的 CI `44150453199` 五项全绿，已合入 `main@265bd4ea`。
- 该片的本地前端依赖曾因离线缓存缺失而未安装，故本机 Vitest 不构成验证；完整远端 CI 已补齐，且没有发起付费模型或真实浏览器调用。
- **2026-11-18 同一不变量的跨层重复测试收口（独立片）**：
  三个模块原样重复查询 SQLite `sqlite_master`，只断言没有 `deep_` 表；
  保留 `tests/test_deep_trigger.py` 中的数据库负控，删除另两处没有额外造景的
  同义断言。默认读取器链的静态元组断言散落在三处，保留
  `tests/test_crawl4ai_specialist_integration.py` 更完整的专用读取器隔离检查，
  删除另外两处同义断言及不再使用的导入。仅减测试重复，没有降低真实功能门、
  调用预算或恢复保护；正式行为未变。
- **2026-11-19 旧课后 Markdown 更新警告器退役**：
  `src/update_validator.py::validate_updates` 只由
  `tests/test_after_session.py` 的四条专属断言调用；正式课后生成、学习闭环、
  API、工具与阶段门并未接线。函数仅返回提醒，并不拒绝内容，旧测试名
  所称的情绪/隐私/版本“拒绝”从未是产品保证。删除它及四个无效专项测试，
  不迁移启发式提示至正式链，也不削弱现有外部数据保护。保留正在调用的
  `after_session` 解析生成、`safe_writer`、学习闭环及预算安全测试。
  原影响集 **46 passed**，Ruff、差异检查、mypy **115/125**；无模型费用。
- **另一独立清理片（待 PR）**：退役不再被生产、CI、现有工具或当前评测调用的旧网页重试特征统计、学习状态临时方案对照、S1/S2 阶段观察，以及重试统计专属测试。共 4 文件，原始约 639 行；不触碰实际网页读取器、持久学习模型、计费安全和故障恢复用例。旧实验结论仍可从 Git 历史或归档文档查看。
- **后继学习状态实验链（依赖上一片先合并）**：完整移除早期 §164/165/168 的下一步、误解、持续对话、阶段 D 取样、影子采集和 S1/S2 真实观察六份单次脚本；其中唯一跨脚本调用源 `run_phase2_rollout_observation` 已在上一片删除。生产 `learner_state_durable_adapter`、`learner_state_shadow_seam`、持久学习状态及相关测试不动，仅更新说明中对已退役脚本的提及。此片独立验证，不能将未完成的 CI 视为通过。

### 2026-11-18 旧 Wigolo 浏览器对比运行器退役（独立片）

- 早期 A3 的 `tools/run_browser_bakeoff.py` 只有其专属
  `tests/test_browser_bakeoff_harness.py` 调用，不参与现行检索、Crawl4AI
  资格评测或 CI 执行。退役整组脚本和历史联调测试，并移除阶段门中这份
  旧专项测试的两处重复引用；旧测试的浏览器是否升级/壁垒分类行为现由
  `test_chain_executor.py`、`test_progressive_routing.py` 与当时的
  `test_wigolo_browser_executor.py` 验证（后者已在后续独立片退役，
  现行共享安全不变量迁至 `test_browser_honesty.py`）。Crawl4AI cohort v2 **仍调用**
  `browser_bakeoff.py` 的结果构造/校验与旧 manifest，故保留该模块、
  manifest 和共用 fixture 服务，将原专项测试中不可替代的结果真实性负控
  合并进 `test_browser_bakeoff_contract.py`。不修改真实浏览器读取逻辑，
  不执行外部浏览器或付费模型调用。

- **2026-11-19 未注册 Wigolo 后端整体退役（独立片）**：现行
  `ACTIVE_READER_CHAIN`、API、研究执行器、正式 Crawl4AI 专家读取及工具
  均未实例化 `WigoloBrowserBackendExecutor`。删除明确标注 production-inert 的
  `wigolo_browser_executor.py` 及其独占 451 行测试；阶段门两处引用替换为
  正式浏览器链使用的 `test_browser_honesty.py`，冻结壁垒分类、受限前缀
  与故障真实性负控。保留 Crawl4AI/默认读取链、预算恢复、安全开关，
  及仍被结果契约使用的 bakeoff manifest/能力词表。原定向
  **188 passed / 1 skipped**、L2 **414 passed / 4 skipped**，Ruff、
  diff-check、mypy **115/125**；无真实浏览器或付费模型调用。
- 同轮审计发现 `conversation_action_step` 仅被旧集成测试使用，但其仍挂
  大量会话阶段门，须独立重建 bounded-loop 覆盖后退役；
  `ResearchMemoryService` 承担已建持久化契约、`backup_manager` 涉及 `.bak`
  恢复，均不因“无直接导入”而机械删除。

### 2026-11-18 历史诊断脚本退役（独立清理片）

- 代码提交 `ef29cab8`（分支 `codex/retire-oneoff-probes-20261118`，基于 `main@f9332655`）：**17 个文件、4,501 行移除**，含 F2 早期定点延迟/账本脚本，以及 RQ1C 历史实验的答复生成、时间线、推理政策、冻结 A/B、断言形状、选择器格式探针。删除脚本时同步删除其 **6 个专属测试文件、36 个测试函数**。
- 逐个检索生产实现、CI、门禁、测试、前端和配置，没有留下直接引用；共享的 `run_f2_paired`、当前研究/发布功能、真实任务测量工具及历史结果文件保留。代码在 Git 历史中可恢复。
- 验证：`pytest tests --collect-only` **7,420 tests collected**，未出现缺失模块导入；保留的 F2/发布测试 **64 passed**，Ruff 和 `git diff --check` 通过。**不宣称全量 L3、产品效果或动态实验通过**；PR 精确 CI 与审查尚待完成。
- **后继独立清理片（依赖上批先合并）**：删除 5 份旧的选择器/Agent 循环实验工具及 5 份专属测试；这些工具只通过彼此和配套测试互相引用，未接入生产运行器、当前测试门禁、前端、配置或持续集成。唯一额外依赖 `run_selector_schema_probe.py` 已在上批删除，因此两片须按依赖顺序合并。只保留 Git 历史和旧报告，不再维护无产品调用方的第二套模型选择器原型。

### 2026-11-18 §37B 候选来源报告器退役（独立片）

- `tools/run_selection_provenance.py` 是 §37B 评测阶段的离线报告格式转换器，
  用当时双人标注的 `likely_target` 统计首个候选丢失位置；除专属的
  `tests/test_selection_provenance_tool.py` 外，没有生产、CI、阶段门或工具调用方。
  一并删除报告器及四项报告格式测试，避免为旧实验的 JSON 输出继续维护接口。
  **不删除** `src/web/research/selection_trace.py`，也不改变运行时的
  `selection_trace` 字段或候选筛选、调度与读取的正式测试。

### 2026-11-18 无调用方网站池测速器退役（独立片）

- `tools/bench_site_pool.py` 只含固定 12 题和浏览器站点池的单次测速输出；
  全库无生产、CI、阶段门、其它工具或测试调用，也无专项配置和测试。
  移除该无维护价值的外部浏览器实验入口，不触及在用的
  `src/web/site_pool.py`、真实检索路由及其回归测试。未实际运行外部浏览器。

### 安全边界与工作树

- **Quality-0 预演运行器退役候选**：旧 `quality_0_arms` 是仅由自身测试调用的未接线四臂运行器；其计划预演脚本、两组专属测试、预演配置和旧操作文档一并移除。仍保留 20 题离线质量评测、评分脚本、文件资产，以及实际被模型支出门禁引用的 `send_budget`、`llm_spend_guard` 和负控。此变更须通过独立 PR 的精确 CI，不代表当前主线已清理。

- 本轮**0 次真实付费模型、DeepSeek Search/Fetch 调用**；各 CI 使用离线测试，不代表已做真实站点浏览器或动态答案质量对照。
- #371 曾确认 12 个工作树中的七个历史阶段目录干净并移除，Git 分支/提交保留；**用户原工作树五处未提交修改保持原样**（`.env.example`、`src/web/browse_search.py`、`tests/test_browse_search.py` 及两份新增文件）。收尾用精确路径复核并仅移除干净临时工作树。
- 专项安全扫描技能配置不可读，本批以精确差异人工审查、CI 与负控替代，**不宣称专项安全扫描通过**。历史 #367 是被 #371 取代后关闭的重复文档 PR。

### 当前仍开放的工作（按优先级）

| 优先级/归属 | 问题 | 最小下一步 |
| --- | --- | --- |
| P0 / 费用与安全 | DeepSeek Search/Fetch 没有持久跨进程共享费用账本；不得启用 | 新用户授权额度后先接费用准入和多 worker 负控，再考虑带费验收 |
| P1 / 研究最终答案 | 部分真实用户题虽搜索成功，最终答案完整性与引用有效性仍缺跨题验证 | 用已存真实失败轨迹做零费回放；新的真实模型对照单独获预算 |
| P1 / 普通聊天/多模态 | 多轮、图片真正理解、取消/恢复、用户可见终态仍需实际供应商/设备验收 | 选一条真实任务做完整动态端到端，不把模拟测试当用户成功 |
| P2 / 中文社区与延迟 | 实际增量、正文可读率及 P50/P95 未在当前部署环境回放 | 用 #369 工具跑零模型调用探针，区分命中与可用证据；保留社区浏览器能力 |
| P2 / 维护成本 | 大文件第一轮职责拆分完成，但仍有大文件、测试夹具重复与全量 CI 约 23 分钟 | 小范围分析影响集、夹具公共化的实益，逐片拆分，保持全量 L3 门 |
| 待立项 / 部署并发 | 操作心跳续租、设置丢更新、超时线程回收、多用户隔离尚不完整 | 单独设计并发/数据完整性门，不能在清理 PR 中顺手重写 |

### 唯一下一执行片

**已合并的读取边界**：[#434](https://github.com/2002yy/study-agent/pull/434) 将读取准入、实时后端历史和断路器健康归入 `ActiveReadDispatchContext`，精确 HEAD `5ff7b4b4`、CI `44263823378` 成功，合并 `008dc2c1`。[#437](https://github.com/2002yy/study-agent/pull/437) 将专家/默认链派发归入 `ActiveReadExecutionContext`，精确 HEAD `884dc459`、CI `44267030564` 成功，审查没有阻断，合并 `b3350fd2`。两片均保持 `execute()` 对恢复状态、游标、检查点和实际费用的唯一写入权威；无真实付费调用。

**已合并读取投影片**：[#443](https://github.com/2002yy/study-agent/pull/443)，HEAD `4f522e26`，精确 CI `44276778323` 成功、机器人审查无发现，预期 HEAD 保护合并至 `main@b613c96c`。该片把读链单来源投影迁到 `project_read_chain`，纯路由诊断归入读取观测模块；合并前同主线的读取栈回归 **467 passed / 4 skipped**，mypy 基线 **115/125** 通过。真实尝试、失败、读额度、恢复、费用、来源 upsert 与检查点顺序均不动。

**已合并读取历史片**：[#447](https://github.com/2002yy/study-agent/pull/447) HEAD `65deabb9`，精确 CI `44284842449` 成功、机器人审查无发现，预期 HEAD 保护合并至 `main@7da66efb`。将三处 `reads` 快照合并为 `_record_read_history(context, current_outcomes)`，仅真实链结束时额外写 `candidate_resolution`；主线隔离整合影响集 **101 passed**（78.73 秒），此前独立候选 mypy 基线 **115/125**。实时读取历史、检查点及预算结算时序保持不变。

**已合并原子路由诊断片**：[#451](https://github.com/2002yy/study-agent/pull/451) HEAD `cecb9775`，精确 PR CI `44289328844` 成功，审查无未解决线程，预期 HEAD 保护合并至 `main@95fdbe96`。原执行器仍独占 `route_missing_atomic_claims`、`extraction_targets/routed_pairs` 与每次检查点；“决定路由后”和“真实提取后”的两个指标写入移至读取观测模块，保留每项 60 条上限、既有字段及顺序，未改变实际 claim 支持关系。在当时最新主线复核读取栈 **458 passed、4 skipped**、定向 **19 passed**，mypy 仍为 **115/125**；无模型/付费调用。

**共享可变状态边界**：① `execute()` 仍唯一持有、在恢复检查点后重新绑定 `state/cursor/context`；② `ActiveReadDispatchContext`/`ActiveReadExecutionContext` 只留运行期稳定依赖，当前候选和读取历史逐次显式传入；③ 读链投影只返回结果；④ `selected_sources` 在实际提取后由执行器更新；⑤ 观测函数只在调用时写当前 `context.metrics`，不持有旧快照；⑥ 模型 inflight、`reserve_call` 及最终结算、证据发布均由原权威负责。

**历史 read-plan v1 加载器退役（2026-11-19，独立片）**：主动研究运行器中
`_load_read_plan` 与唯一专用的 `_read_plan_entries` 曾将旧版单列表计划转换为
v2 双列表，但在仓内运行、恢复、测试及阶段门已无调用方。二者成组删除，不留
兼容空壳。**保留**现行 `claim_engine_read_plan` 字段、
`ACTIVE_RESEARCH_READ_PLAN_KEY`、活动计划和持久化恢复契约，不修改 schema，
也不声称删除实际数据库迁移能力。原影响集 **96 passed**，Ruff、差异检查、
mypy 基线 **115/125** 通过；真实检索和模型 `not_run`。

**后继故障记录显式游标片（本地独立候选）**：基于 `main@95fdbe96`，直接在 17 个故障分支调用已经存在的 `with_appended_runtime_failure(cursor, context, ...)` 并显式绑定返回游标，移除 `execute()` 内捕获 `cursor/context` 的 `_append_failure` 闭包。未更改已有纯投影函数、失败 ID/去重、异常处理、检查点、恢复、预算或发布代码。冻结契约的基础运行器与故障投影回归 **87 passed**，预算时钟/模型尝试/失败契约/结算/steering **37 passed**；读取栈阶段门 **458 passed、4 skipped**（107.59 秒），全库 Ruff、diff-check 与 mypy 基线（115/125）通过。新候选精确 HEAD CI 另行验收，当前绝不冒充已合并。

**唯一下一收口动作**：完成上述候选的读取栈阶段门、差异范围核对与精确 HEAD CI，审阅通过后独立合并；之后再按真实测试调用方清理重复造景，不重新建立模型、恢复或发布权威。#404 测试造景由另一窗口处理；原 #369 零模型社区覆盖探针仍待真实浏览器与 SearXNG 验证，不构成当前结构片动态 PASS。

## 0A. 已冻结研究路线（摘要）

`Lookup → VERIFIED / SAFE_ABSTAIN / ESCALATE_STANDARD`；Standard 的多源/比较/冲突和 Deep 的计划/缺口/收益/暂停恢复复用既有 `ActiveResearchRuntimeExecutor`，不另起第二套研究引擎。`usable/read_backed/relevant` 不能等同逐条 claim 支持；默认 `simple` 只验证引用 URL 属于已读来源，不标逐条 verified。

## 0B. M4 智能 UI 决策（摘要）

保留 M4-C 测量链路及 M4-D 增量修改基础；M4-E 受控修复须带版本/源码哈希及明确错误判据，失败保留旧版本；M4-F Three/WebGL 在受控沙箱执行，禁止加载任意第三方脚本；M4-G 根据问题选文字、静图、动画、交互或 3D。默认局部修改、修复成功率和媒介选择质量需真实任务验证。

## 历史原文与追踪

- **2026-11-19 无调用方的游标/新鲜度辅助函数退役**：
  `src/web/research/runtime.py::_counter_mapping` 与
  `src/web/github_freshness.py::_payload_compact` 均无生产、工具、测试、
  CI、阶段门调用，也非动态入口，直接删除，不保留空壳或测试/配置。
  正式 `ResearchRuntimeCursor.from_dict` 的 v1/v2 游标格式和逐字段校验、
  GitHub 新鲜度缓存及主/辅证据与漂移判断均不变。原游标恢复和快照
  影响集 **74 passed**，Ruff、差异检查、mypy 基线 **115/125** 通过；
  真实远程 GitHub 请求及付费模型 `not_run`。

- **压缩前原始 1,466 行**：[`main@cf62add5/docs/PROJECT_STATUS.md`](https://github.com/2002yy/study-agent/blob/cf62add59d4a35e9a2060cbeafc68be1572ad570/docs/PROJECT_STATUS.md)，原始记录完整存于 Git 历史。
- [2026-10-24 999 行归档](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-24.md)、[2026-10-23 旧档](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-23.md)、[2026-10-06 旧档](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)。
- 2026-11-17 完整执行链以本文件上方 PR/CI、[有日期执行记录](research_quality/RETRIEVAL_LEAN_EXECUTION_20261117.md)、各 PR 讨论及可还原的提交历史复核。
