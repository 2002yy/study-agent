# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-10-11（多窗口现有结果合并收口；学习/研究资格边界不变）
> 产品定义：**Study Agent 是长期保持“正在学什么、已经确认什么、还不会什么、下一步是什么”的个人学习工作台。**

本文件只维护当前权威状态、可复核边界和唯一下一门。2026-10-06 本次收敛前的完整状态原样归档到 [`archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)；更早历史继续由既有 archive 与 Git 历史持有。

## 0. Current Handoff（cold-start 入口）

**2026-10-19 #239 重绑发布main。** #236在bbcef47d81150cca08f29e0bfdd84f052a3f0bea / CI39221498204 SUCCESS / 无未解决finding后expected-head合入main9684aa829c6b5cc4e8d70ff4754ecb4302557043；前mainafa54501 CI39221117547 SUCCESS。本#239旧2bcb4e4c / CI39219767478 SUCCESS且重放身份finding已解决，现吸收发布main，交接与impact冲突保留双方、followup生产逻辑不变；整合共享影响集conversation_decision_1b 223 PASS/118.69s，mypy122/128 NEW0、Ruff/diff-check PASS后推送并将base改main，旧绿灯不授予新head。本轮累计观察/阶段回复另在独立分支推进。

**2026-10-19 #239 审阅修复 / 观察重放身份。** finding4311370434有效：原hash包含整个previous，调用方重建旧上下文可使同一工具事件重新取得模型准入。现仅以不可变source request_id + USE_TOOL阶段派生后续身份（一个已准入提议最多一次工具阶段），不纳入证据/额度/能力、提议措辞或结果正文。新增5项SQLite重开负控覆盖这些重建变化，命名L1 conversation_observation_followup 182 PASS/49.08s。旧head756a6e22 / CI39217176655 SUCCESS不授予修复后head；推送后一次绑定CI并解决已修finding。修复将显式带入自身#240/#242及第三片CI路由，不依赖其他窗口WIP。


**2026-10-19 CL-1D-2：有界工具观察回填（当前独立小片）。** branch `codex/conversation-observation-followup-20261019` / worktree `D:/study-agent-validation/conversation-observation-followup-20261019`，显式固定base为自身#236冻结head `2ce7dbe7c0cdd7e8a3d07422464727a0bd9cb179`；未取其他窗口WIP。#232已expected-head合入main `9e36b9359f4224735c30d163ff9e105932bc1eea`，根main已ff同步，4个外部IA-1A未跟踪ZIP完整保留；其main CI39215516784在后台。#233整合main后head224cae0664b35a40f1e115e3f44d7ecb1239e0be / CI39215954538；#235修复版本回执finding并整合main后headf42095445331b1666e0f2087153629e9b1a44e02 / CI39216114150；#236吸收修复后head2ce7dbe7 / CI39216194104；上述最新CI快照in_progress，均不借旧绿灯合并。#235 finding4307918994已解决，本地共享影响集164 PASS；#236影响集134 PASS。

新增 `decide_after_tool_observation` 与纯投影 `tool_followup_context`：仅接受同一请求、成功且确定的USE_TOOL观察及经校验的原提议；服务端必须已记录至少一次工具消耗，换题/改历史/改研究快照拒绝。观察以单独JSON消息标记unverified，原证据摘要/用户意图保持原样；固定系统说明不插入观察内容。序列化观察包上限8000字符，超限拒绝而不悄悄截断。额外两条消息的准确字符数先经过原DecisionAdmission准入，再提交注入式模型；沿用原超时/取消/迟到/提议校验与no-retry。观察身份稳定派生为新request_id，证据或预算刷新不能给同一观察换身份重试；兼容进程预算和已合并SQLite账本，不存工具正文。宿主可用公开投影执行下一提议，本函数不自动执行或发布。

验证：新增22项自身测试PASS，包括scripted模型→本地实际加法→观察回填→下一决策→宿主执行回答，及SQLite重开去重/完整提示计费、原证据保留、提示数据与指令分离、转义后包体超限、旧身份/未消费额度/换题拒绝、取消与超时；只证明控制流和消息边界，不证明真实模型智能或抗注入质量。命名L1 conversation_observation_followup含step/dispatch/runner/admission/decision/阶段策略，最终 **177 PASS / 47.97s**。Ruff/format、mypy122/128 NEW0、diff-check PASS；无SDK/付费模型、无生产路由、无业务schema或前端变更，无本地L3。候选SHA由本段所属Git提交恢复；下一动作独立stacked PR并一次绑定exact-head CI。唯一后续片CL-1D-3：有界多步事件流与终止原因，继续由总决策/动作预算约束，不引入生产发布权威。

**2026-10-19 本轮三片与main整合收口（#236当前候选）。** #233已在224cae06 / CI39215954538 SUCCESS后合main5ead630f，其exact-main CI39217839722 SUCCESS；#235已在5566aa4d7c2c1968b9f82bd57cbc277d7a6a1d7b / CI39219048419 SUCCESS / 版本回执finding已解决后expected-head合main `afa5450143ca8a569d621487d2d3b00d415a9565`，push CI39221117547后台in_progress，根main已ff同步、4个外部ZIP保留。当前#236已吸收该发布main，add/add冲突实质仅AsyncIterator→AsyncGenerator两个注解，保留正确可关闭类型；交接/impact冲突保留双方。对main差异仍仅原单步编排6文件，未引入其他窗口WIP；整合后conversation_decision_1b 196 PASS/51.22s、mypy122/128 NEW0、Ruff/format/diff-check PASS；候选SHA由本段所属提交恢复，需绑定新exact-head CI，旧2ce7dbe7绿灯不授予新head。PR base改main。

本轮新增三片均已推送：#240有界多步流，最终head778d0003174c8cde39e8f130455831505386d399 / CI39220080887，命名L1 215 PASS/67.23s；#242单次消费/运行回执，最终head827b81adfc6562c6403bc68c90c9431cda68768c / CI39220756792，L1 223 PASS/65.38s；#244精确CI路径/完整消费者，heade05e39e16307af47a2933df8164c5860b1f598d2 / CI39221109190，L1 132 PASS/34.88s。三项CI最后快照in_progress，未合并或上线。#239重放身份finding4311370434已修且解决，head2bcb4e4c13128c8090403240c9370fcd944a00c5 / CI39219767478 / L1 182 PASS；#240工具后STEER finding4311446891和#242终态close_error finding4311507599也已修并解决，修复完整进入后续片。各review修复只复验对应影响集，没有机械跑本地L3。完整真实模型/累计观察/生产聊天/付费工具联动仍未验收。唯一下一功能片：基于自身#244冻结结果做有界累计工具观察与阶段回复输入；同步按新head CI/审阅逐片合并，不等后台CI才开发。

**2026-10-19 #236 修复集成。** 原head0f715a27 / CI39148846133 SUCCESS；因父片#235 finding4307918994已修，现显式吸收自身冻结修复5186abb9与已发布main9e36b935。冲突仅交接与impact列表，保留step和admission两项测试；step生产逻辑不变。单步/分发/决策/runner影响集134 PASS/36.92s；最终吸收f4209544仅同步父片文档，生产树与受测8a04a571一致，未重复测试。最新head需独立CI；旧绿灯不授予新head。本分支仍基于自身#235，不依赖其他窗口WIP。下一片有界观察回填独立推进。


**2026-10-19 CL-1D-1：受控单步编排（当前独立小片）。** branch `codex/conversation-action-step-20261019` / worktree `D:/study-agent-validation/conversation-action-step-20261019`，显式固定 base 为自身 #235 head `bcdaa4b77933551702849ab383cd3cbe15b76993`；未依赖其他窗口 WIP。新增 `run_conversation_step`，一次受控决策 → 提议事件 → 动作观察流，共用总时限；消费者暂停计入时限，关闭外层流会关闭分发流，决策失败不调用动作、换题拒绝旧动作、取消传播到正在执行的适配器。观察保留原 attempted/outcome_unknown，不自动重试、开启下一决策或授予证据/答案权威。无生产聊天/SDK/付费调用接线。

命名 L1 `conversation_action_step` **127 PASS / 33.91s**（新增14项 + 分发/决策/runner/阶段策略）；Ruff/format PASS，mypy122/128 NEW0。类型门先发现 aclosing 不接受仅声明 AsyncIterator 的分发 API，已将其注解收紧为真实 AsyncGenerator，明确可关闭协议，运行行为不变；未放宽 baseline。共享 legacy1b 添加此消费者。无本地 L3、无 UI 变更。最终候选 SHA 由本段所属 Git 提交恢复；待独立 stacked PR/一次 exact-head CI，#235 合并后调整 base main。当前仅验证 scripted 模型和本地工具的控制流，不宣称真实模型质量或产品上线。唯一下一片 CL-1D-2：有界观察回填到后续决策，区分未验证工具输出与已验证证据，并保留提示预算和新决策身份。
**2026-10-19 #235 main集成更新。** #233在exact head224cae06 / CI39215954538 SUCCESS后合入main5ead630fd902360ddff0f5694fbf4f3ddad74140；#235自己的f4209544 / CI39216114150 SUCCESS且版本回执finding已解决，但当前main交接冲突。保留双方交接后吸收已发布context投影，dispatch生产树不变，共享影响集conversation_decision_1b 182 PASS/62.04s覆盖新main消费者后再推送；新head绑定一次CI，不借旧绿灯。自身后续#236/#239/#240与session切片继续独立后台开发，不将其他窗口WIP混入。


**2026-10-19 #235 审阅修复 / 自身版本回执。** finding4307918994 指出成功STEER更新研究版本后被误判过期；新增仅可信handler返回的 SteeringObservation(observation,research_after)，要求同一run且版本前进，并与执行完成时精确研究快照匹配，用户消息/历史/请求仍不得变化。无回执、并发再次推进版本、换题、跨run、旧版本和非steer携回执均拒绝；不是直接允许任意研究版本变化。handler必须在自身事务中取得回执，不能事后读取其他写入者的最新版本冒充。观察仍没有生产applied/证据权威。

本片修复命名L1 conversation_action_dispatch 120 PASS/28.29s，mypy122/128 NEW0；随后合入已发布main9e36b935（#232），保留交接冲突双方，重跑共享影响集conversation_decision_1b 164 PASS/49.02s，覆盖runner/持久准入消费者。候选head由本段所在提交恢复；旧bcdaa4b7 CI39148186998 SUCCESS不授予新head，提交后绑定一次CI并解决已修finding。#236原0f715a27 CI39148846133 SUCCESS，需吸收本修复再更新head；不借旧CI、不等后台CI才开发。下一功能片仍为有界观察回填，独立分支。

**2026-10-19 CL-1D：独立动作分发与观察（本分支当前片）。** #231 已在 head04371329 / CI `39146013970 SUCCESS` / 无未解决 finding 后 expected-head 合并，main `5d4da728162bc974d62d3def40718c78211d5483`。#232 已通过旧05993443 CI，但新 main 仅本交接冲突，保留双方后整合并补 legacy 快速门的 admission 测试，最新 head `58a2f4ae` 已推送，本地命名门137 PASS；#233 已接受 partial-reply finding4307851812，v1 对当前非空 assistant_message 明确拒绝，保留既有 ChatService 续答路径；整合新main并补共享快速门context测试，最新本地候选 `2e44f344`，命名门151 PASS。新 head 均需各自 CI，不借旧绿灯。没有为这些切片/修复再跑本地全量。

当前 branch `codex/conversation-action-dispatch-20261019` / worktree `D:/study-agent-validation/conversation-action-dispatch-20261019`，独立 base 为上述 main，不依赖 #232/#233 或其他窗口 WIP。新增 async generator `dispatch_conversation_action`：仅调用注册的服务端 handler，answer_then_research 先发 answer 观察，再运行 use_tool；每阶段启动前校验当前上下文/研究版本/能力，原子进程内 claim 防重复并限制工具槽。关闭流/取消/期限已过不继续下一阶段；异常脱敏、attempted/outcome_unknown 真实分开，迟到观察丢弃，预算/证据因自身工具变化不误作换题。观察没有 Evidence Gate/正式答案/转向 applied 权威；真实工具权限、参数、费用、持久租约仍由 handler/后续接线负责。

命名 L1 `conversation_action_dispatch` **113 PASS / 34.66s**（自身 + decision + runner + stage policy）；包含 fixture 决策→先答→本地实际求和→观察回传→fixture 决策再回答、单路由、并发重复、预算/能力、调度竞态、用户换题/关闭流、外部与适配器取消、超时吞取消/迟到、无效观察等负控。共享 `conversation_decision_1b` 也登记本新消费者，避免将来共享代码快速门漏测；manifest 键放在独立锚点减少并行 JSON 冲突。Ruff/format、mypy122/128 NEW0、diff-check PASS。无 SDK/付费调用、生产入口/工具权威切换、业务 schema 或前端改动，无本地 L3。候选 SHA 以本段所属 Git 提交恢复。下一动作：提交独立 PR/绑定一次 CI，然后 CL-1D-1 受控单步编排与观察回填；不等待后台 CI 才开发，不以本片称完整 Agent 已上线。

**2026-10-19 #233 集成更新。** #232 在 exact head58a2f4ae / CI39147888463 SUCCESS / finding已解决后 expected-head 合并，main9e36b9359f4224735c30d163ff9e105932bc1eea；main CI39215516784已后台启动。#233 原head2e44f344 / CI39147924617 SUCCESS，但新main交接文档冲突；本片保留双方交接并合入已发布的持久准入实现，生产context投影不变。整合后共享影响集conversation_decision_1b 155 PASS/45.58s、Ruff/diff-check PASS，随后推送；新head需独立CI，不借旧绿灯。没有为文档整合机械跑L3。

**2026-10-19 #233 续答边界修复与 main 集成（覆盖旧可接受 streaming 的无条件表述）。** 接受审阅 finding `4307851812`：ChatService 的 continuation 会复用当前 turn 并保留部分 assistant_message，而 v1 DecisionContext 没有独立的当前 partial-reply 槽。当前投影对非空当前 assistant_message 明确拒绝，不把部分回复静默丢弃或伪装成已完成历史；pending/streaming 两项负控通过。只限制尚未接生产的决策投影，不修改现有 ChatService 的重试/继续功能。支持完整续答的上下文合同仍待独立设计，不冒称已实现。

同步 #231 已合并 main `5d4da728162bc974d62d3def40718c78211d5483`，仅冲突本交接，保留双方记录；共享 `conversation_decision_1b` 补当前 context 测试，防止未来共享模型变更漏掉该消费者。最终命名 L1 `conversation_decision_context`（含相邻 router/task）**151 PASS / 80.41s**，Ruff/format、mypy122/128 NEW0、diff-check PASS；无本地全量。旧 head `2ad75cec` 的 CI 不授予新候选。新 head 由本段所属提交恢复；修复后推送并 resolve finding，绑定一次新 CI。动作分发在独立 main 基线工作树推进，不依赖本片未合并成果。

**2026-10-19 CL-1C-2a：服务端对话快照 → 决策输入（本片覆盖旧 NEXT）。** #230 已在 exact head f706、CI `39143921500 SUCCESS`、审阅 finding 解决后 expected-head 合并，main `0236160e378c0272d7dd9e582e08c12d3ac65fda`；主目录 ff-only 同步且 tracked clean，三个未跟踪 IA-1A 审阅 ZIP 原样保留。exact-main CI `39145457669` 已绑定 0236160e，最后快照运行中，未称 main CI 通过。#231 已重绑 main / ready，head `04371329d94a71bb36160170334888d8f89f1aaf`，同树本地 102 PASS；#232 修复既有空库被接管的问题后重绑 main，head `059934433a755e37770aaf156b46e8b59aa90fdf`，114 PASS，finding `4307789596` 已 resolve。两次 retarget 后无新 head CI，经确认无 run 后各 close/reopen 一次，仅触发缺失的当前候选验证：#231 `39146013970`、#232 `39146011883`（pull_request），已绑定各自新 SHA；不借用旧绿灯、不轮询等候。

当前 branch `codex/conversation-decision-context-20261019` / worktree `D:/study-agent-validation/conversation-decision-context-20261019`，独立 base 为上述 main，不依赖 #231/#232 或其他窗口 WIP。新增 `context_from_chat_snapshots`：会话/turn/operation 所有权、活动/取消状态、当前 turn 的一致快照、跨会话历史与研究归属校验；历史只含前六个 completed 轮次，request_id 稳定绑定服务端身份。该模块只读、无 I/O，不改变业务 schema、聊天入口、外部数据披露、工具执行或证据权威；它不负责多次 DB 读取的原子性，生产调用者仍需一致快照和执行前复核。

本片 L1 `conversation_decision_context` **126 PASS / 37.15s**（自身 + decision + runner + chat_service + stage policy），含真实 SQLite 的落库/reload/不写回、跨会话、过期/取消、重复/不一致当前轮次、历史上限、重试身份隔离等负控。Ruff/format PASS，mypy122/128 NEW0，diff-check PASS；无 L3、无付费调用。候选 SHA 以本段所属提交恢复。下一动作：提交独立候选并开 PR/绑定一次 CI；随后 CL-1C-2b 先定义货币费用与原子读取/提供商适配的边界，后台 CI 不阻塞开发。整个 GPT-like 对话循环与真实模型选择质量尚未验收。
**2026-10-19 #232 合入新 main 的集成候选。** #231 在 head `04371329` / pull_request CI `39146013970 SUCCESS` / 当前审阅无未解决 finding 后 expected-head 合并，main 为 `5d4da728162bc974d62d3def40718c78211d5483`。#232 旧 head `05993443` 的 CI `39146011883 SUCCESS` 与所有权 finding 已解决；与新 main 的唯一合并冲突为本文件，已保留双方交接。本次未改生产源文件，补齐 legacy `conversation_decision_1b` 对新 admission 调用方测试的覆盖，避免以后共享 runner 快速 CI 漏测。该命名集 **137 PASS / 71.06s**；此前自身影响集114的证据保留为同源证据。无本地全量。合并提交 SHA 由本段所属提交恢复，需新 exact-head CI，不将旧 05993443 绿灯授予新 head。#233 正处理续答 partial reply 的审阅边界；独立动作分发分支已开始，后台 CI 不阻塞开发。

**2026-10-19 合并与增量审阅收口（覆盖下方 #230 待合并及空库所有权记录）。** [#230](https://github.com/2002yy/study-agent/pull/230) 已于精确 head `f706db8ce072027d72764f387329599711647d52`、pull_request CI `39143921500 SUCCESS`、无未解决审阅 finding 后 expected-head squash 合并，main 为 `0236160e378c0272d7dd9e582e08c12d3ac65fda`；本地主目录已 ff-only 同步，保留三个未跟踪 IA-1A 审阅 ZIP，tracked clean。exact-main push CI `39145457669` 已绑定 0236160e，快照 in_progress；未借 PR 绿灯称 main CI 已通过。#231 已重绑 main，head `04371329d94a71bb36160170334888d8f89f1aaf`，3 文件，ready for review；与旧 4ba7b6ad 整树相同，保留 102 PASS 的同树本地证据，旧远端 CI 不授予新 head。

#232 审阅 finding `4307789596` 接受并修复：原实现会初始化预先存在的空 SQLite 文件；现在只允许本调用通过 O_EXCL 独占新建的文件初始化，已有文件先以 read-only URI 核验完整所有权/额度，拿写锁后再核对一次；零字节空文件与合法空 SQLite 均负控证明原字节不变。初始化中断遗留无所有权文件只会 fail closed，不自动删除/接管。修复后的命名 L1 **114 PASS / 34.14s**，Ruff/format、mypy122/128 NEW0、diff-check PASS；无本地全量、无真实付费调用。当前候选应将本片单独重绑上述 main 后推送，完成该 finding 的解决记录；提交 SHA 以本段所属提交恢复，不把旧 #232 head 59b62753 的 CI 借给新 head。下一执行片：CL-1C-2 的持久货币费用/请求身份合同与可注入边界，保持生产路由不变；后台 CI 不阻塞下一片开发。

**2026-10-19 CL-1C-1：不等待 CI 的独立调用准入片（覆盖本分支旧 NEXT）。** 用户明确“不等 CI，接着做后续小分支拆分或功能分支开发”，并要求写入 Codex 记忆；已新增记忆更新 note，未改动既有 MEMORY.md。#230 保持冻结 head `f706db8ce072027d72764f387329599711647d52` / run `39143921500` 后台执行；CI 四精确路径路由已独立开为 draft [#231](https://github.com/2002yy/study-agent/pull/231)，head `4ba7b6ad`，本地 102 PASS。当前新 branch `codex/conversation-decision-admission-20261019`，worktree `D:/study-agent-validation/conversation-decision-admission-20261019`，base f706，不依赖 #231 或其他工作树 WIP。

本片新增 `conversation_decision_admission.py`：独立自有 SQLite 文件、固定额度合同、BEGIN IMMEDIATE 原子预留、request 幂等、跨实例/进程重启保留预留、并发限额、拒绝业务数据库（负控核验原库 SHA256/行不变）；不保存提示正文/模型响应/凭据，不退款、不自动重置。runner 改为可注入准入协议，存储异常/未知返回统一 admission_unavailable，模型不执行。现有进程内 DecisionBudget 保持兼容。此为次数/字符/token 台账，不冒称货币费用，未改变业务 SQLite schema/cursor，未接 SDK/真实付费模型或切换生产路由。

验证：命名 L1 `conversation_decision_admission`（自身 + runner + decision + stage policy）**112 PASS / 28.93s**；含真实 SQLite、独立 Python 进程重启、并发/锁失败、非法准入、provider 失败后重启仍不重复请求。Ruff/format、mypy122/128 NEW0、diff-check PASS；完整候选 detect-secrets **0 finding**。候选 SHA 由本片提交恢复。无本地 L3，未等待/轮询 CI。下一动作：提交此独立候选，绑定 draft PR 的 f706 基线；#230 通过门后 expected-head 合并并将后续片重绑 main；CL-1C-2 另行定义持久货币费用与生产接线。
**2026-10-19 CI-CL：敏捷开发的精确影响集路由（独立后续片，本地候选）。** #230 修复 head `f706db8ce072027d72764f387329599711647d52` 已推送，pull_request CI `39143921500` 已绑定该 SHA，快照仍 in_progress；本片不修改该 PR head。新 branch `codex/conversation-decision-ci-scope-20261019`，worktree `D:/study-agent-validation/conversation-decision-ci-scope-20261019`，base f706；仅 `tools/ci_scope.py` 与 `tests/test_ci_scope.py` 新增对两个 conversation_decision 模块及各自测试四个精确路径的分类，映射既有 `conversation_decision_1b`。其他同前缀新路径、混入 CI 工具/共享模型/SQLite/Standard/前端/资格门/未知路径时仍回退，未把整个 application 或 learning-backend 粗略缩小。manifest/docs 随片注册仍沿用既有规则，资格门要求不被删除。聚焦影响集（ci_scope/workflow_routing/ci_outcomes/stage_gates_policy）**102 PASS / 24.49s**，Ruff/diff-check PASS；本片不跑 L3、不修改 workflow 或执行器。增量本地审阅无新增阻断 finding。下一动作：等 #230 按 expected-head 合并，再将本片移植到新 main，以独立范围开 PR/绑定 CI，不把尚未合并的功能算成本片新改动。

**2026-10-19 敏捷交付裁定 / #230 审阅修复（覆盖旧“再跑最终 L3”要求）。** 用户明确要求“不要每一次都全量，一边把功能分支合入 main，一边敏捷开发”。本分支后续 bounded slice / 小范围审阅修复默认 L0+命名 L1，子阶段 L2；不因每次提交或准备合并机械重跑本地 L3，真正生产权威切换/共享持久合同等强制触发仍按 AGENTS.md。原本地 L3 已停止且未重新启动；未声称本地全量通过。#230 的 head `8fd5c227bc8785213c1efa49667417a89f9bb919` 已获 pull_request CI **39141623936 SUCCESS**（pytest/secrets/mypy/required outcomes 均 PASS），但审阅 finding `4307618012` 指出 transport 自行 CancelledError 会冒充调用者取消。现已区分 `asyncio.current_task().cancelling()`：调用者取消仍传播，适配器自取消返回受控 provider_error/unknown，预留不退且不自动重试；新增负控证明当前调用者未被取消与重复请求不重发。新候选命名 L1 **116 PASS**，mypy122/128 NEW0、Ruff/format/diff-check PASS；只复验影响集，未跑全量。新 head 由本段所属提交恢复，旧 CI 不授予新 head。唯一下一动作：绑定新 exact-head CI，解决该已修 finding 后 expected-head 合并 #230；整条产品线仍按成熟度报告 NO-GO。随后独立补对话决策四个精确路径的 CI 命名影响集映射，避免既有 classifier 未注册而自动回退全量；不把全 learning-backend 笼统缩成小集。

**2026-10-18 CL-1B 最终审阅修复 / PR #230（覆盖下方候选证据）。** 完整候选审阅发现：当前上下文读取或事件循环排队耗尽时限后仍可能进入 transport。现于准入前与 transport 启动前检查同一截止时间，传给 transport 的 timeout 缩为剩余时限；两项负控证明截止已过不提交模型。命名 L1 最终 **115 PASS / 29.66s**；Ruff/format/mypy122/128 NEW0 PASS；按 CI 同配置的完整候选 detect-secrets 扫描 **0 finding**（只认既有精确证据身份白名单，未放宽规则）。此前 `0d14e34d8c23ab47777cf593ee4b272ab20467fe` 的本地 L3 在约 3% 主动停止，不借给修复后候选；保留旧部分日志，不称通过。PR [#230](https://github.com/2002yy/study-agent/pull/230) 的旧 head CI `39140892253`（pull_request）同样不得用于新候选。新的 head 以本段所属 Git 提交恢复，提交后需重新 preflight 与一次最终 L3，并绑定新 exact-head CI。完整增量审阅覆盖两个新模块、测试、manifest 与 docs；上述截止问题已修，未见其他阻断 finding（本次为本地自审，不冒称外部批准）。产品线 98 文件仍 NO-GO；当前合并范围仅 8 文件。

**2026-10-18 CL-1B：受控模型决策调用，独立 main 合并候选（覆盖本分支旧 NEXT）。** 用户授权“本分支内实现受控模型决策调用，成功实现即合并 main”，并要求评估整条产品线能否一起合入。已评估冻结产品 head `0c818515` 的 98 文件：真实验收 A 仍 FAIL、最终 head 无 PR/CI，旧 L3 不覆盖后续生产变更，故整线 NO-GO，详见 [PRODUCT_LINE_MATURITY_20261018.md](PRODUCT_LINE_MATURITY_20261018.md)。保留原线于 `codex/conversation-agent-loop-product-base-20261018`；当前 branch `codex/conversation-agent-loop-20261018` 已将自身提交移植到 exact main base `335fc9b7875b848f202122362f2e0f8b5a9db0ee`，不带入产品线 schema/UI/工具/费用代码，也不依赖其他窗口 WIP。候选 head 以本段所在 Git 提交恢复。

新增 `conversation_decision_runner.py`：单次异步可注入模型调用、调用/提示字符/输出 token 原子准入、request 去重、有限等待、取消保留预留、迟到结果丢弃、严格响应解析与最新上下文校验、异常脱敏。上下文容器限制为不可变快照。仅返回动作提议；不执行工具、不切换生产聊天路由、不新增 SDK 或真实付费调用。进程内 budget 不冒充持久人民币费用台账；真实提供商接线与持久费用/重启幂等另属 CL-1C。用户授权的合并范围为本独立候选，非整个产品线。

本地 L1 `conversation_decision_1b` **113 PASS / 30.44s**（含真实 loopback HTTP 传输，以及超时吞取消、迟到、外部取消、并发限额、重复请求、无效 JSON/重复键、过期上下文、上下文读取失败）。全仓 Ruff、新文件 format-check PASS；mypy **122/128 NEW0**。验证日志 `D:/study-agent-validation/conversation-agent-loop-1b-mypy.log`。初始 Git fetch 的 schannel 连接异常，改为命令级 openssl 后成功，未更改 Git 全局配置。合并前需干净候选 preflight、完整回归、最终增量审阅与 exact-head CI；尚未宣称合并。下一动作：提交本候选，检查完整 diff 范围，跑所需最终门并 expected-head 合并。CL-1C 在合并完成后另开片。

**2026-10-18 CL-1A：对话行动合同独立推进（覆盖下方 CL-0/IA-1A 依赖与旧 NEXT）。** 用户要求“新工作树不要直接依赖其余开发中的工作树的结果，另选方向推进”；本分支只依赖固定已提交产品 base `0c8185151f694926941d3e5801f65f1df72fc65c` 与自身提交，不导入其他窗口 WIP、不等待其输出。branch `codex/conversation-agent-loop-20261018`，worktree `D:/study-agent-validation/conversation-agent-loop-20261018`，本片 base `494f13f10d12c3a1230834de2d85b7907ec4913d`；候选 head 由本段所属 Git 提交恢复。调整后的任务合同见 [CONVERSATION_AGENT_LOOP_PLAN.md](CONVERSATION_AGENT_LOOP_PLAN.md)。新增 `src/application/conversation_decision.py`：有界上下文/模型输入、六类行动提议、精确 envelope 校验、请求与研究版本绑定、工具能力及剩余调用预算检查。新话题可回答或用工具且保留原研究；不支持转向、非法排队、跨 run/陈旧版本、未知工具和额外执行字段被明确拒绝。仅合同/校验器，无 I/O，无生产路由切换、模型/工具执行、预算预留、状态落盘或答案权威；不是实际意图识别质量或完整对话循环验收。

**CL-1A 验证：** 命名 L1 `conversation_decision_1a`（自身 + router + task_contract + research_interaction + stage_gates_policy）**99 PASS / 29.80s**；全仓 Ruff PASS、新文件 format-check PASS、mypy baseline **122/128 NEW0**、diff-check PASS。首轮 97 PASS/2 FAIL：无 active run 的两项负控仍携带 `keep`，先触发 disposition 拒绝而非预期的 run 拒绝；仅修测试输入为 `none` 后影响集通过，无旧测试未知失败。mypy 日志 `D:/study-agent-validation/conversation-agent-loop-20261018-mypy.log`，生成缓存移至工作树外保留；本片按显式路径提交后应干净。无 L3：新增隔离合同尚未成为共享生产权威；无 UI 改动，未启动浏览器/构建。无付费调用、推送、PR、新 CI、合并或部署。**唯一下一片 CL-1B：** 在本分支接可注入、受预算/超时控制的模型决策调用，验证响应 → 提议校验与失败语义；生产接线另设门，不等待其他分支的计时或增量回复成果。

**2026-10-18 对话 Agent 循环：独立工作树与开发计划（本分支覆盖下方旧 NEXT）。** 用户确认六项通用核心能力的产品分支状态，并要求按“端到端基线 → 模型决策 → 阶段性答案 → 补充闭环 → 消息归属 → 真实联动验收”推进。任务合同见 [CONVERSATION_AGENT_LOOP_PLAN.md](CONVERSATION_AGENT_LOOP_PLAN.md)，能力表明确标注“产品开发分支、尚未合并主线”，不将已有实现等同真实验收。新 branch `codex/conversation-agent-loop-20261018`，worktree `D:/study-agent-validation/conversation-agent-loop-20261018`，产品 base `0c8185151f694926941d3e5801f65f1df72fc65c`（`codex/research-interim-analysis-20261018`），共同 main base `335fc9b7875b848f202122362f2e0f8b5a9db0ee`；当前文档提交 SHA 由本段所属 Git 提交恢复。仅新增计划与本段交接，生产代码不变。原 `chat-steer-attachments` 工作树存在未提交 IA-1A 回复/终态冻结/计时等成果，原样保留且未复制，本分支不冒称包含它们。**唯一下一片 CL-0：** 定向核对并复用 IA-1A，使用 Photoshop/开源替代品 + Agent 自动编辑补充的可控 30 秒场景建立端到端时间线，区分生成、传输、渲染和终态问题。3～5 秒为有用初步分析目标，不以回执或模板代替。当前仅文档范围与 diff-check 验证；未运行生产测试/L3，未新增付费调用，无新 CI/推送/PR/合并/部署。

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
