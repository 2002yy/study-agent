# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-10-18（补充要求显示它实际改了什么：只认创建者、不复述原问题；下一刀改为助手增量回复）
> 产品定义：**Study Agent 是体验接近 GPT-6 Chat 的智能聊天与研究 Agent。自然聊天、自主研究、持续交互、智能 UI、统一多模态、工具执行是六项通用核心能力；长期学习与教学是其上的专业场景。**

本文件只维护当前权威状态、可复核边界和唯一下一门。2026-10-06 本次收敛前的完整状态原样归档到 [`archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)；更早历史继续由既有 archive 与 Git 历史持有。

## 0. Current Handoff（cold-start 入口）

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
**2026-10-19 CI 失败归因与 secrets 白名单修复（集成分支，本地提交）** #234/#238 的 exact-head CI 在门禁步失败，失败项为 `secrets` 与 `browser_e2e`（main 的两次 push 运行均 success，故属本分支内容）。归因结论：**两项都不是 IA-1A 的两个提交引入的**。

**`secrets`（detect-secrets）**：命中 `docs/evidence/real-acceptance-2026/scenarios.json` 第 6 行 `"candidate_head": "06e96286d98d76c38018ff972460f42528479723"`（Hex High Entropy String，熵 3.59 > 阈值 3.0）。该值经 `git cat-file -t` 验证为**本仓库真实存在的 commit 对象**（`chore(git): treat the acceptance evidence pack as binary fixtures`），且报告里的 `hashed_secret` 正是该值的 SHA-1。该文件在 `0c818515`（IA-1A 基线）与 `370e9026`（候选）**逐字节相同**（`git diff --quiet` 退出码 0），且由前置提交 `a80c1659` 引入 → **不是 IA-1A 新引入**。修复：在 CI 的 `--exclude-lines` 里**按字段名**补 `candidate_head`（与既有 `head_sha`/`base_sha` 同一约定），并新增负控断言任意 40-hex 字段（`head`/`target_commit`/`api_key`/`token`）与大写十六进制**仍被拦**（`tests/test_ci_detect_secrets_allowlist.py`）。

**`browser_e2e`**：`frontend/e2e/chat-role-settings.spec.ts` 的布局断言 `panelBox.y + panelBox.height <= inputBox.y` 在 desktop-chromium 上 4 条全失败。**两个 HEAD 本地重跑（同一 CI 配置 `playwright.config.ts`，`--project=desktop-chromium`）都失败同样 4 条** → 按既定判据「两边失败 ⇒ 共同祖先问题」。结合 main 的 CI 通过，可定位为**本分支 40 个前置提交中的某个**（基线 `0c818515` 已含这 40 个、不含 IA-1A 的 2 个）。该 spec 在两个 HEAD 上内容一致，`ChatPanel.tsx`(+119)/`answerUi.css`(+10) 才是 IA-1A 的差异 → 但 IA-1A 的 2 个提交**不在失败区间内**。**未修复**：需在 40 个前置提交上做二分定位（下一步）。

**诚实边界**：本地无法复现 CI 的 secrets 命中（本地扫描在两个 HEAD 上 residual 均为 0，插件直查该文件也不报），因此 secrets 的归因依据是**文件内容逐字节相同 + 值经验证为真实 commit**，不是本地复现；CI 报告（artifact `ci-diagnostics/detect-secrets-report.json`）是命中的直接证据。

**2026-10-18 IA-1A 终态诚实报告（最后一刻接受的补充必须被明确告知，本地未提交，覆盖下方所有 IA-1A 记录数字）** 复审认可前一轮三项修复，但指出一个产品一致性问题：P1 测试证明补充记录与回复没丢，却没证明**最终答案是否明确告知该要求没有执行**；“未生成模型分析”与“未纳入最终研究结果”不是一回事。本轮只做这一件事，另附一项非阻断一致性收口。**未提交、未推送、未开 PR、未触发 CI、未运行 L3、未跑付费样本、未做费用账本。**

**修复（全部发生在终态写入内部，基于合并后的上下文）**：仓储新增 `_unexecuted_supplements(context)`（判定条件与既有语义一致：`executed_in_round is None`）与常量 `UNEXECUTED_SUPPLEMENT_WARNING = "本轮研究结果未包含部分追加要求（已接受但未执行）；请排队下一轮继续。"`。`complete()` 每次 CAS 尝试都基于**合并后的**上下文判定：存在未执行补充时，状态由 `completed` 降为 `partial`（诚实状态），并把该警告写入 run 的 `warnings`（去重）；`_freeze_replies_for_terminal()` 同时给这些补充的回复打上 `result_state="not_included"`（新增 `mark_result_not_included()`，走 `advance_content` 递增版本）。服务端原先基于执行器**旧快照**的 `unapplied` 判断与重复告警已删除，判定与文案只有一处来源（仓储），避免旧快照漏报。

**前端（数据库 → 界面）**：`ChatResearchReply` 新增 `result_state?: "not_included"`；`replyStatusNote()` 优先返回更强、更可执行的说明“本轮研究结果未包含此要求（已接受，未执行）；可排队下一轮继续”（优先于“本轮未生成模型分析”）；`ChatResearchRecovery` 新增渲染 run 的 `warnings`（原样展示、不做摘要），与任何 API 消费方看到的是同一句话。

**非阻断一致性收口**：后端此前允许 `superseded` 回复继续更新正文，前端却冻结整条回复。现统一为“失效后正文不可变”：durable `superseded` 时，incoming 非 `superseded` 记 `superseded_reopen`，incoming 也是 `superseded` 但内容不同则记 `superseded_immutable`，两种情况都保留 durable，两层规则一致。

**负控（数据库 → 用户界面）**：`test_a_supplement_accepted_before_completion_survives_it` 现同时断言 `status == "partial"`、`UNEXECUTED_SUPPLEMENT_WARNING in completed.warnings`、每条回复 `result_state == "not_included"`，以及 SSE 投影同样携带该字段；`test_a_steer_accepted_before_the_terminal_write_is_frozen_by_it` 断言 `closed_run_status == "partial"` 与警告存在；前端 `researchReplies.test.ts`、`ChatPanel.test.tsx`（回复块渲染该说明）、`ChatResearchRecovery.test.tsx`（渲染持久化警告行）各一条。另为 `ChatResearchRecovery.test.tsx` 补 `afterEach(cleanup)`，修掉测试间 DOM 泄漏（新断言暴露的既有测试卫生问题）。

**验证（本轮重跑，最终候选）**：L1 `incremental_answer_1`（11 文件）**106 PASS / 39.57s**；前端 `npm test` **115 files / 553 tests PASS**；`tsc -b` 0 错、`vite build` PASS；浏览器四视口 **4 PASS / 16.2s**；Ruff PASS；mypy **current=122 / baseline=128 / resolved=6（NEW0）**；`git diff --check` PASS。

**仍未做**：真实模型样本与延迟分布、持久化费用账本、L3/CI。**已知相邻问题（仅记录）**：前端全量单测存在负载敏感 flake（`ReadingWorkspace.test.tsx` 的 scrollTop 断言），单独运行 6/6 通过，不在本候选范围。**下一刀**：本轮通过后先做独立实验 ID 的持久化预算账本，再跑三条真实样本。

**2026-10-18 IA-1A 复审三点收口（superseded 单向 / 终态补充历史 / 跨轮次计时，本地未提交，覆盖下方所有 IA-1A 记录数字）** 复审 NO-GO 后只做三项：防止 `superseded → open`、验证终态补充记录不丢失、过滤跨轮次计时事件。**未提交、未推送、未开 PR、未触发 CI、未运行 L3、未跑付费样本、未做费用账本**。

**P0 `superseded` 被旧执行器重新打开（已复现→已修）**：复审给出的最小复现（durable `superseded` v3 / 新状态 incoming `open` v3）在本工作树得到同样结果 `open` v4（走 `same_version_race` 分支重新编号放行），违反 `open → superseded` 不可逆。修法：`merge_steering_replies()` 在**任何研究状态/版本比较之前**先保护 durable 的 `superseded`——incoming 不是 `superseded` 即拒绝，并记录 `last_conflict.reason="superseded_reopen"`（可审计），生命周期权威不再被更新的研究轮次覆盖。修复后同一复现输出 `superseded` v3 + `superseded_reopen`。负控：`tests/test_reply_persistence_consistency.py::test_a_superseded_reply_is_never_reopened_by_a_stale_executor`（先持久化纠正，再让持旧快照的执行器 `checkpoint`，回读数据库与 SSE 投影都必须仍是 `superseded`）。

**P1 终态写入可能丢掉最后一刻接受的补充历史（已证实→已修）**：复审指出 `complete()` 只合并 `conversation_queue` 与 `steering_replies`，未合并 `deep["steering"]`。**已用真实数据库路径证实**：先做一次 checkpoint 并捕获执行器旧快照 → `service.steer` 接受第二个补充 → 用旧快照 `complete()`，修复前数据库中 `deep["steering"]` 只剩 1 条（补充历史被旧副本覆盖），修复后为 2 条。修法：`complete()` 与 `fail()` 都改用与 `checkpoint` 相同的合并链（`merge_active_steering_context` → `merge_deep_steering_context` → `merge_queued_followups` → `merge_steering_replies`），并保留有界 CAS 重试（`fail()` 同样加上重试）。负控三条（完成/失败/取消）：新 id 必须同时存在于 `deep["steering"]` 与 `steering_replies`，回复一律 `closed` + `run_terminal`，`closed_run_status` 分别为 `completed`/`failed`/`cancelled`，未覆盖的补充标 `not_generated`。

**P2 新计时窗口仍接收旧轮次回复事件（已修）**：`researchTiming.ts` 新增 `inWindow()`，`replies`、`reply_visible`、`answer_visible` 三类事件统一按 `target_turn_id` 过滤；`target_turn_id === null`（本会话尚未 send，例如恢复的会话）不过滤，且此口径已写入注释。负控：新 send 后旧 run 的 `replies`/`reply_visible` 迟到事件被拒（`marks`/`visible` 保持为空），当前 run 事件正常进入；恢复会话（target 为 null）三类事件仍被观测。

**审查包说明修正**：上一版 `ia1a-FIXES-b1b5.md` 的“先应用全量补丁再应用窄补丁”是错的（全量补丁已包含窄补丁内容）。正确用法：**从 base `0c818515` 起只应用全量补丁**；或**从 B1–B7 修复前的候选起只应用对应窄补丁**。本版说明已按此改正。

**验证（本轮重跑，最终候选）**：L1 `incremental_answer_1`（11 文件）**106 PASS / 41.92s**；前端 `npm test` **115 files / 550 tests PASS**；`tsc -b` 0 错、`vite build` PASS；浏览器四视口 **4 PASS / 11.0s**；Ruff PASS；mypy **current=122 / baseline=128 / resolved=6（NEW0）**；`git diff --check` PASS。窄范围差异见 `D:/study-agent-validation/ia1a-fixes-superseded-terminal-timing.patch`。

**已知相邻问题（未修，超出本轮范围）**：前端全量单测存在**负载敏感 flake**——`src/features/reading/ReadingWorkspace.test.tsx > notebook reading navigation > locates only headings in the loaded window without another read` 在整套并行运行时偶发失败（`body.scrollTop` 期望 77 实得 0），单独运行该文件 6/6 通过；该文件不在本候选改动范围内，按范围纪律仅记录不修。

**仍未做**：真实模型样本与延迟分布、持久化费用账本、L3/CI。**下一刀**：本轮三点通过后，先做独立实验 ID 的持久化预算账本（原子累计、重启不清零、并发不超额），再跑三条真实样本。

**2026-10-18 IA-1A 审查阻断修复（B1–B5，本地未提交，覆盖下方所有 IA-1A 记录的数字）** 审查裁定 NO-GO 后按 B1–B5 收口。branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base/HEAD `0c8185151f694926941d3e5801f65f1df72fc65c`（**仍无新 commit**）；**未推送、未开 PR、未触发 CI、未运行 L3、未跑付费样本**。

**B1（P0）失效标记被合并器丢弃**：`mark_additions_stale`/`supersede_affected` 只增 `content_version` 而不更新 `based_on_version`，研究状态不变时合并器判 `stale_base` 并拒绝，导致“旧判断已过时”的更新落不了盘。新增 `advance_content(reply, now=...)`：任何**状态变更**都同时写入 `content_version+1` 与 `based_on_version=原版本`，使合法失效写入通过 CAS 校验，而陈旧写入方仍会被拒（`based_on < durable.content_version`）。`mark_analysis_not_covered`/`close_replies` 同样走该路径。**仓储级负控**（`tests/test_reply_persistence_consistency.py`，新）：走真实 `checkpoint` 合并链与 `_deep_update_steering_replies`，回读数据库断言 `stale is True` / `lifecycle == superseded` 且无 `last_conflict`，并断言 SSE 投影同样可见。

**B2（P0）终态冻结不在同一次原子转移内**：原先执行器先 `_close_steering_replies(...)` + `persist()`，再 `complete()`/`fail()`，存在“回复已宣称结束、run 行仍是 running”的窗口。现冻结移入终态写入本身：仓储新增 `_freeze_replies_for_terminal(context, run_id=..., run_status=...)`，在 `complete()`/`fail()`/`finish_cancel()` 的**同一次 UPDATE** 内完成（含“本轮未生成模型分析”的标记），`run_status` 取**实际写入的终态**（`completed`/`partial`/`failed`/`cancelled`，不再是仍为 running 的旧行）；`complete()` 改为有界重试：每次重新读行、合并 durable 的 `steering_replies`、冻结、再按版本 CAS 提交，因此终态写入既不会丢弃并发追加的回复，也不会在 CAS 失败时留下冻结。服务端 `_close_steering_replies` 与其 logger 已删除（`close_replies`/`mark_analysis_not_covered` 导入一并清理）。负控：终态前 checkpoint 后回复仍为 `open`、完成后才 `closed`+`run_terminal`+`closed_run_status=completed`；CAS 持续失败时不落冻结且 run 仍 `running`；失败路径 `closed_run_status=failed`。

**B3（P1）对 durable `closed` 无条件信任**：`prior_closed` 现要求 `lifecycle_closed_by == "run_terminal"`；无来源的 `closed` 可被合法更新覆盖，权威冻结仍然优先。负控：非法 `executor` 关闭被合法更新取代、权威关闭仍胜出（`test_reply_terminal_freeze.py::test_an_illegitimate_durable_close_is_not_kept`）。

**B4（P1）可见计时被上一轮污染**：`ResearchTimingState` 增加 `target_turn_id`；新增 `run_start` 事件（每次 send 开新观测窗并清空旧标记）；`answer_visible` 只在 turnId 与目标轮次一致时生效；`ChatPanel` 的 `AnswerVisibilityProbe` 仅对**当前观测轮次**的已完成答案挂载（新增 `answerTurnId` 由 controller 透传）。负控：旧轮次答案上报被拒、`run_start` 清空历史标记、非目标轮次不挂探针。

**B5（P1）G1 后到会擦除 G2 证据来源**：`apply_analysis` 在已有 G2 时不再改写 `content_state`（证据 provenance），改为把 G1 的 `{round,notes,revision}` 存入独立的 `analysis_provenance`；`content_fingerprint` 纳入该字段。负控：G2 的 `content_state`/`citations`/`text` 在 G1 后到后保持不变。

**B6（P2）投影与前端对无来源关闭不一致**：`reply_projection(active=False)` 现显式写入 `lifecycle_closed_by="run_terminal"`（来源是权威 run 行）；前端 `mergeResearchReplies` 统一规则——首次恢复遇到无来源 `closed` 显示为 `open`（内容不丢、不误标冻结），合并路径仍完全忽略裸关闭声明。负控双向覆盖。

**B7（P2）“可见”语义**：发布态新增 `visibility_source: "rendered_after_frame"`，明确该指标是“提交后第一帧”的渲染观测，**不等于**读者在滚动区域内真正读到；浏览器断言同步校验该字段。

**验证（本轮重跑，最终候选）**：L1 `incremental_answer_1`（现 11 文件，已登记新负控）**102 PASS / 35.44s**；前端 `npm test` **115 files / 548 tests PASS**；`tsc -b` 0 错、`vite build` PASS；浏览器四视口 **4 PASS / 10.9s**；Ruff PASS；mypy **current=122 / baseline=128 / resolved=6（NEW0）**；`git diff --check` PASS。窄范围修复差异 `D:/study-agent-validation/ia1a-fixes-b1b5.patch`（16 文件，+643/−129），已在冻结候选的干净工作树上 `git apply --check` 通过。

**仍未做**：真实模型样本与延迟分布（未批准）、持久化费用账本（审查通过后再做）、L3/CI。**下一刀**：审查通过后做独立实验 ID 的持久化预算账本（原子累计、重启不清零、并发不超额），再跑三条真实样本。

**2026-10-18 IA-1A 审阅后修复轮（本地未提交，覆盖下方两条 IA-1A 记录的验证数字）** branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base `0c818515`；本轮**未提交、未推送、未开 PR、未触发 CI、未运行 L3、未新增付费模型调用**，改动全部留在工作区待审阅。审阅给出的 6 项必须修复已全部落地。

**① 显示计时改为“按内容态”上报（原缺陷：回执渲染被当成模型分析）**：`frontend/src/features/web-lookup/researchTiming.ts` 重写为 `visible: ReplyVisibleMark[]`，键为 `reply_id@content_version:stage`（`visibleKey`/`visibleStageAt`/`firstVisibleAt`），首次观测为准、重放事件不得前移或后移；`leadBeforeAnswer`（对 `answer_done_ms`）与 `analysisLeadBeforeAnswer`（G1，仅 `stage="analysis"`）/`evidenceLeadBeforeAnswer`（G2）分离，**没有 G1 就是 `null`，绝不用 G2 顶替**。`chatController.ts` 的 `onReplyRendered` 删除，改为 `onReplyVisible(reply, at)` + `onAnswerVisible(turnId)`；**答案可见时间不再由 `done` 事件后下一帧推断**，改由真正渲染答案的组件上报。`ChatPanel.tsx` 抽出 `ResearchReplyBlock`（挂载即按当前内容态上报）与 `AnswerVisibilityProbe`（仅在“已完成且有正文”的助手气泡内挂载）。

**② 研究级回复按精确轮次绑定（原缺陷：绑到“最后一条助手消息”）**：删除 `lastAssistantIndex`，改为 `message.turnId === reply.turn_id` 定位归属；无归属（该轮尚无消息）时进入尾部兜底区块，不冒充其他轮次。`frontend/src/features/web-lookup/researchReplies.ts` 客户端合并修正：**接受后端驱动的 `open → superseded`**（版本 `>=` 即生效，这是失效而非“更新内容”）、权威冻结（`lifecycle_closed_by === "run_terminal"`）在同版本也生效、**无 provenance 的 `closed` 声明继续被忽略**、已冻结不被重开。

**③ 终态权威写入（后端）**：`src/application/web_lookup_service.py` 的 `_close_steering_replies` 改为**显式传入即将写入的终态**（`run_status="partial"|"completed"`、失败路径 `"failed"`）；此前它读 `self.get(run_id).status`，而该行此刻仍是 `running`，导致 `closed_run_status` 记录错误——属真实 provenance 缺陷，已修。冻结失败不再静默 `return`，改为 `_LOGGER.warning(..., exc_info=True)`（新增模块级 `_LOGGER`）。

**验证（本轮全部重跑，最终候选）**：L1 `incremental_answer_1`（10 文件）**94 PASS / 35.03s**；`tests/test_reply_terminal_freeze.py` **7 PASS**（新增不变量：取消/失败/完成三条终态路径都写入 `lifecycle_closed_by="run_terminal"` 且 `closed_run_status` 分别等于 `cancelled`/`failed`/`completed`；无 provenance 或 `lifecycle_closed_by="executor"` 的 `closed` 声明完全无效；`close_replies` 会升版本且不重复盖章）；前端 `npm test`（= `vitest run src`）**115 files / 544 tests PASS**；`tsc -b` 0 错误、`vite build` PASS；浏览器 `playwright.conversation.config.ts` 桌面/手机/窄屏/平板 **4 PASS / 12.0s**（断言已改为新模型：回执与 G1 是不同内容态、`receipt < analysis < answer_visible`、G1/G2 lead 分别 > 0）；Ruff PASS；mypy 基线 **current=122 / baseline=128 / resolved=6（NEW0）**；`git diff --check` PASS。

**本轮失败样本与根因（均为测试侧或已修）**：⑴ e2e 断言仍读旧形状 `mark.analysis_ms`，属测试未随生产 API 更新，已改为新模型断言；⑵ 出现 React “unique key” 警告——`key` 原先在 `replyBlock` 内部的 `<article>` 上，抽成组件后需落在组件调用处，已修；⑶ 我新加的绑定测试断言 `closest("article")` 命中的是回复块自身的 `<article>`（假失败），改为以 `.message` 为轮次容器，产品行为本身正确。**注意**：裸 `npx vitest run` 会把 `e2e/*.spec.ts` 当作 24 个失败套件，正确命令是 `npm test`（`vitest run src`），此前记录的前端数字差异源于此。

**边界与风险（不因本轮修复而改变）**：G1 仍来自既有 `revise` 调用（本轮结束才产出），**不承诺 3–5 秒内出现模型分析**，也不得把“回执很快出现”宣传为“已实现快速智能分析”；G2 只证明“引用来自已读材料”，不等于论证成立；`AnswerVisibilityProbe` 仍是“下一帧”近似，不是 paint 保证。费用裁定未执行：`src/llm_spend_guard.py` 的 `_reserved_cny` 是**模块级全局**，进程重启即清零，因此“三个样本共 ¥10 硬上限”必须在同一进程内完成（或先把账本持久化），实际样本运行仍待批准。**下一刀**：按批准方案在同进程内跑三条可追踪样本，采集四项延迟与“G1/G2 是否早于 G4”，样本不足只报原始值。

**2026-10-18 IA-1A 验收：三项风险修复 + 浏览器单时钟计时（本地未提交，覆盖下方 IA-1A 段）。** 用户裁定「保留未提交、批准设计测量方案、允许有限本地修复」，本轮**未提交、未推送、未触发 CI、未运行 L3、未新增付费模型调用**。三项风险检查结果：①**同版本冲突语义已修正**——原先“冲突后把写入方内容改到下一版本”会让陈旧执行器仅凭版本号覆盖更新内容；现改为**以研究状态为准**（`content_state = {round, notes, revision}`，即该内容由哪一轮、多少条笔记、哪个 interim revision 派生），旧状态永远不得覆盖，同状态同版本冲突保留**首次成功原子写**，只有更新的研究状态才以不冲突版本发布（`steering_replies.merge_steering_replies` + `state_key`）。②**终态冻结落盘**——`finish_cancel`（取消）与深研失败路径现在在同一原子写内 `close_replies`；成功/部分完成路径在最终 persist 前关闭；`checkpoint` 只接受 `status='running'`，取消/失败/完成后旧执行器根本无法写入；`pending`（已接受未启动）仍为活跃态、**不会**被误判终态（负控已覆盖）。③**G1/G2 是否早于 G4 已可测量**——新增浏览器单时钟标记（`researchTiming.ts`：submit/receipt/analysis/evidence/answer 全部取 `performance.now()`，首次观测为准），并给出 `leadBeforeAnswer`/`analysisLeadBeforeAnswer`，迟到即为 null、不伪造“边研究边回答”。

验证（本轮重跑）：L1 `incremental_answer_1` **82 PASS / 32.49s**（新增 `tests/test_reply_terminal_freeze.py` 5 PASS：pending 非终态、取消落盘冻结且拒绝迟到 checkpoint、失败冻结、完成冻结、迟到 open 快照不得重开）；`test_steering_replies.py` + `test_steering_reply_merge.py` **19 PASS**（含“陈旧写入方不得靠高版本提升旧分析”“同状态同版本保留首次写”“更新状态以不冲突版本发布”）；前端 **170 PASS / 23 files**（含 `researchTiming.test.ts` 4 PASS：单时钟记录、重复事件不移动更早观测、迟到即 null）；浏览器四视口 **4 PASS / 13.6s**，新增断言用 `window.__studyAgentTimings` 证明「回执 < 模型分析 < 最终答案」的顺序（fixture 时间线，非真实模型证据）；Ruff PASS、mypy 基线门 **122/128 resolved=6（NEW0）**、`git diff --check` PASS、`tsc -b && vite build` PASS。

**交付物**：审阅用补丁 `D:/study-agent-validation/ia1a-20261018.patch`（24 文件，2269 insertions / 15 deletions，含 9 个新增文件；`git apply --stat` 校验通过）。**未做**：真实模型样本与延迟分布（需另行批准费用）、IA-1B 快速分析调用、active claim-engine 接入。**下一刀**：按已批准方案跑三个领域各一条可追踪样本（Photoshop 自动化编辑、游戏攻略补充、编程问题补充），采集四项延迟与“G1/G2 是否早于 G4”，样本不足只报原始值。

**2026-10-18 IA-1A：阶段性助手回复（本地未提交，覆盖下方旧 NEXT）。** branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base `0c818515`。用户裁定 Rev.2「有条件 GO，批准 IA-1A 最小实现」，并给出四项强制实现合同 A–D；本轮**未提交、未推送、未开 PR、未启动 L3、未新增付费模型调用**。改动 6 个新文件 + 14 个修改文件：`src/web/research/steering_replies.py`（新）、`tests/test_steering_replies.py`（新）、`tests/test_steering_reply_merge.py`（新）、`tests/test_incremental_answer.py`（新）、`frontend/src/features/web-lookup/researchReplies.ts`（新）、`researchReplies.test.ts`（新）；改 `deep_planner.py`、`interim_analysis.py`、`web_lookup_service.py`、`web_lookup_repository.py`、`chat_routes.py`、`types.ts`、`chatController.ts`、`ChatPanel.tsx`、`ChatPanel.test.tsx`、`WorkspaceView.tsx`、`answerUi.css`、`conversation-continuous.spec.ts`、`test_deep_planner_production.py`、`stage_gates.json`。

**实现（对应合同 A–D）**：A 失效规则——`interim_revision` 变化不再等于整条回复失效：新增条件只把旧判断标 `stale`（“尚未覆盖后续新增的条件”）且保持 `open`，只有 `corrections` 里被替换的旧术语命中、或引用材料失效才 `superseded`；研究终态由权威 run 状态决定 `closed`（投影派生 + 落盘冻结双保险）。B 并发一致性——回复存 `context["steering_replies"]`，`checkpoint` 合并链新增 `merge_steering_replies`（同 `reply_id`：版本大者胜；**同版本不同内容判为冲突**，durable 保版本、写入方改到下一版本，绝不用 `updated_at` 静默决胜；终态冻结优先于版本）；`append_steering` 与回执回复在**同一次原子写**内完成，CAS 耗尽改为明确可重试的并发冲突错误，不再冒充“研究已停止”。C G1 模型合同——`revise` 新增结构化 `steering_understandings`（`steering_id/changed_focus/reason_to_check/questions_to_verify`），服务端校验字段、长度、真实补充 ID 并拒绝“已验证/已确认/verified”等断言口吻；上下文改为优先喂入**尚未被理解**的补充（上限 4），未被覆盖的补充在终态显式标 `not_generated`（“本轮未生成模型分析”），不静默丢弃。D G2 来源归属——`attribute_analysis` 要求**每一条**引用都来自该补充创建的任务、且读取轮次 ≥ 该补充进入计划的轮次；不满足则归入研究级回复（`<run_id>:research`，`scope=research`）。前端：补充级回复绑定到对应补充消息，研究级回复绑定 run（原助手气泡只留简洁状态）；引用沿用 `safeLinkUrl` 校验，`content_version` 严格递增、终态冻结。

**验证**：命名 L1 `incremental_answer_1`（写入 `tests/stage_gates.json`）**75 PASS / 27.61s**；并发与不丢写负控 `test_steering_reply_merge.py` **5 PASS**（同一次写内落盘回执、陈旧执行器 checkpoint 不得擦除新回复、同 `request_id` 幂等、非运行态与冲突区分、同版本冲突改号）；投影与失效 `test_steering_replies.py` **12 PASS**；端到端 `test_incremental_answer.py` **2 PASS**（4 条补充全部有回复且无静默丢弃、补充前材料只能进研究级回复、补充后材料才可归属、回复文本不进入 `source_block`）；前端 **166 PASS / 22 files**（含回复渲染、`javascript:` 来源不成链接、同版本终态冻结、晚到事件不覆盖新内容）；浏览器 `playwright.conversation.config.ts` 桌面/手机/窄屏/平板 **4 PASS / 10.5s**，截图 `frontend/test-results/conversation-continuous/*/continuous-research.png`（补充消息下出现“初步分析/已收到补充”）与 `interim-analysis.png`（研究级“阶段性判断 · 有来源，尚非结论”＋引用）；Ruff PASS、`git diff --check` PASS、mypy 基线门 **current=122 / baseline=128 / resolved=6（NEW0）**，日志 `D:/study-agent-validation/ia1a-mypy.log`；`tsc -b && vite build` PASS。

**边界与风险**：G1 仍来自既有 `revise`（本轮结束才产出），**不承诺 3–5 秒内出现模型分析**，也**不得**把“首条回执很快出现”宣传为“已实现快速智能分析”；本轮**未做延迟测量**（首条可见回执/首次模型分析/首次有来源分析/最终答案的中位数与 P95 仍待补，样本不足须注明）。G2 仍只证明“引用来自已读材料”，不等于论证成立。active claim-engine 未接入（`steering_replies` 仅在 Deep 路径产生，字段形状两条路径一致，便于后续接入）；取消路径依赖投影派生 `closed`，未落盘冻结。**下一刀 IA-1B**：先补真实延迟测量（含 Photoshop 自动化编辑、游戏攻略补充、编程问题补充三类样本），再据结果决定是否引入可取消、有预算、与研究并行的受控快速分析调用；普通新问题的直接回答/边答边查/深入研究分流仍属后续阶段。

**2026-10-18 最新片：补充要求显示“它实际改了什么”（本地 commit，未合并/未推送；覆盖下方旧 NEXT）。** branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base `4b8fd6ad`，本片代码提交 **`873315d4`** `feat(research): expose durable steering effects in chat progress`（11 个文件：`src/web/research/research_interaction.py`、`tests/test_research_interaction.py`、`tests/stage_gates.json`、`frontend/src/types.ts`、`frontend/src/features/single-chat/ChatPanel.tsx`、`frontend/src/features/single-chat/ChatPanel.test.tsx`、`frontend/src/features/chat/chatController.ts`、`frontend/src/features/answer-ui/answerUiProtocol.ts`、`frontend/src/features/answer-ui/answerUi.css`、`frontend/e2e/conversation-continuous.spec.ts`，另含本状态文档）。用户反馈：截图里“再考虑 Agent 自动编辑”下面只有一行回执、其余留白，看不出第二句话是否被当成决策依据。本片把补充回执从“状态标签”扩成“状态 + 实际效果”，**纯展示投影，无新模型/工具调用，不写计划、不授予证据或答案权威，不改 schema/预算/Gate**。

实现（含审阅后的事实边界修正）：`src/web/research/research_interaction.py` 新增 `_steering_effects()`——只从 durable 事实投影。`questions` 为 plan 任务中 `steering_ids` 命中该补充 id 的项（≤2、去重、各 ≤160 字），且**只有创建者（`steering_ids[0] == entry_id`）才标记 `created=true`**；仅被追加 id 的既有核查恒为 `created=false`，绝不冒充“新增”。`created=true` 时显示文本用 `_steering_question_text()` 去掉 planner 的“；新增研究目标：”拼接前缀，只显示该补充真正加的目标（不再复述原问题）；`created=false` 时原样显示完整核查问题。`sources` 为已读摘录中 `question` 与这些核查完全相等者（≤2，仅 title/url），只表示关联材料，不表示支持。未进计划的补充**不产生 effects 字段**（空投影即诚实答案）；`superseded/cancelled` 任务与旧术语修正过的问题不计入；沿用既有 `deep_steering_status()`，`executing` 仍只在 run 活跃时出现。前端：`types.ts` 两处类型补 `effects`；`answerUiProtocol.ts` 新增 `safeLinkUrl()`（仅 http/https、无凭据、无控制字符，否则回落纯文本，不生成可点击链接）；`ChatPanel.tsx` 按 `created` 渲染“新增核查：/本次补充涉及的核查：”，来源行为“关联已读材料（尚非结论）：”；`answerUi.css` 用 `.message-body .research-steering-*`（提高特异性，覆盖既有 `.message-body span{display:inline-flex}`）保证三行竖排、非加粗；`chatController.ts` 三处（乐观追加 / SSE 合并 / 恢复）透传 `effects`。

验证：命名 L1 `research_steering_effects`（写入 `tests/stage_gates.json`）**94 PASS / 1 SKIP / 39.18s**；`test_research_interaction.py` 自身 **17 PASS**（含：未进计划无 effects、`created` 只认创建者、correction 追加到既有任务不称新增、去重与 160 字/2 条上限、effects 只含 text/created 与 title/url 无权威字段）；前端 `ChatPanel.test.tsx` + answer-ui 组 **61 PASS / 26 in ChatPanel**（含既有核查不得称新增、`javascript:` 来源不生成链接）；`tsc -b && vite build` PASS；浏览器 `playwright.conversation.config.ts` 桌面/手机/窄屏/平板 **4 PASS / 10.4s**（截图 `frontend/test-results/conversation-continuous/*/continuous-research.png`：三行竖排、只显示补充自己的目标）；Ruff PASS、`git diff --check` PASS、mypy 基线门 **current=122 / baseline=128 / resolved=6（NEW0）**，日志 `D:/study-agent-validation/steering-effects-mypy.log`。零 L3、无新 CI、未推送/未创建 PR/未合并。

**边界**：effects 是“服务端从计划与已读材料投影出的展示事实”，不等于论证成立或推荐正确；引用存在性检查仍不是 entailment 判定。当前只覆盖 Deep（active claim-engine 补充仍只有状态，不虚构 effects）。**下一刀（用户已调整优先级，不再是补 active 展示）**：补充要求 → 助手自己的**增量回复** → 后台研究继续 → 新发现逐步更新。要分清两层：进度信息（本 commit 的成果）与分析内容（为什么这项补充改变了原问题、目前能判断什么、还需验证什么）。补充消息继续作为用户消息存在，但助手需要一条**独立且可持续更新**的回复，而不是把研究状态都挂在原助手气泡下。3～5 秒可作为初步交互目标，但不得为赶时间生成无依据结论。真实付费验收仍按既有预算授权边界。

**2026-10-18 最新片：有出处的阶段性判断 + UI 留白（本地，未合并；覆盖下方旧 NEXT）。** branch `codex/research-interim-analysis-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base **`15302f84b2a774c37d51c34e406f91bc0b8a5a0e`**；本段所在 Git 提交即实现 head，审阅仅 base 后增量。复用 Deep 原有 revise 调用生成可选归纳，不新增调用/预算/执行器。要求先给具体发现、差别或有条件建议，说明对用户的意义；不能形成有用判断时返回 null，不用“继续核对”凑分析。服务端限制正文400字、1–3条引用，引用必须匹配已读材料 ID 与原文；checkpoint 在最终综合前保存。展示重新核对成功读取/资格/重定向及当前 steering revision；新补充、失效正文会撤回过时判断。保持原文段落，无独立持久化 schema 改动，不改变正式答案/Gate 权威。

用户指出“毫无结论、AI味、仍然堆积”后，本片改为直接展示判断正文：有判断即收起开场计划/查询计数/重复标题，原文和过程合为一个默认折叠入口，阶段性边界说明移入其中；段间留白，无新增卡框。头像仍桌面96px、手机80px。脚本浏览器场景移除每次 steer 无条件发送的过程套话和未请求计算，计算覆盖移到明确请求数字比较的排队问题；这些是 mock 修正，不冒称生产模型已执行。

验证：命名 L1 `research_interim_analysis` **99 PASS / 1 SKIP / 35.40s**；最后补段落保留后，自身+生产 planner+已读来源模块 **34 PASS / 10.88s**，未重复全量。前端上一版影响集62 PASS，本次反馈修复最终直接影响集 **32 PASS**，TypeScript/Vite build PASS；最终320/390/768/1440px浏览器 **4 PASS / 10.5s**（同SSE连续追加/排队失败重试、附件身份、出处折叠、查询行撤下、计算按需、原头像尺寸），人工查看390px截图判断正文与来源入口留白通过。Ruff PASS、mypy **122/128 NEW0**、diff-check PASS。Ruff首次误从frontend目录运行导致tests/tools路径不存在，已改repo根目录通过，非代码失败。日志 `D:/study-agent-validation/interim-analysis-{impact,final-focused,frontend,build,browser,mypy}.log`；截图 `frontend/test-results/conversation-continuous/*/interim-analysis.png`。本片零 L3；无新 CI/推送/PR/合并/部署，提交后预期干净，主目录不改。

**边界与下一刀：** 引用存在性检查不等于论证成立/推荐正确；全部离线 fake 模型/工具与真实 SQLite/HTTP/SSE，不授予真实研究质量 GO。当前只覆盖 Deep；Standard 的增量判断仍未接通。下一执行片：用用户问题与阶段性判断组成小型内容验收集，核查“具体结论/证据适配/有用后果/无套话”，再决定是否扩展 Standard；真实付费验收沿用既有预算授权边界。

**2026-10-18 最新片：已读资料按真实研究问题分组（本地，未合并；覆盖下方旧NEXT）。** branch `codex/research-question-groups-20261018`，worktree `D:/study-agent-validation/chat-steer-attachments`，base **`e167c6657306f3986f4ca96210f14443bb6ce231`**；本段所在Git提交即修复head，审阅仅base后的增量。改善六项能力中的搜索分析/边研究边交互：从既有Deep plan/notes/成功读取正文只读投影问题归属，最多3条摘录优先覆盖不同问题，避免比较题被单侧较多来源淹没；同网页可服务不同问题、身份不冲突。按全部合格读取材料计算`reading_gaps`，不把展示上限误作缺资料；done状态不能制造已读材料，纠正/取消的旧问题不再当作来源或缺口。UI沿用无外框分组与一条低强调的“暂无正文”提示，第二侧资料到达后撤掉对应提示、保留第一侧且不重复。旧事件可省略新增字段，显式空快照清除过期项，低版本/跨run隔离保持。

验证：命名L1 `research_question_groups` **76 PASS / 1 SKIP / 30.35s**；新增展示上限负控后仅自身模块复验 **18 PASS / 4.60s**（未声称整个命名集重跑）；前端影响集 **60 PASS**；320/390/768/1440px focused浏览器 **4 PASS / 10.9s**，覆盖单侧缺资料→双侧出现/缺口消失/原资料不重复及附件补充/排队链路；build/Ruff/diff-check PASS，mypy122/128 NEW0。日志 `D:/study-agent-validation/question-groups-{backend,cap-check,frontend,browser,build,mypy}.log`，截图仍在既有conversation目录。只新增展示字段与投影，不写研究计划/证据资格/答案token，不新增模型或工具调用、不改schema/cursor/预算；未动头像与上一片布局，桌面96px/手机80px约束保持。无L3、新CI、推送/PR/合并/部署；提交后工作树干净。

**唯一下一片：有来源的阶段性归纳。** 本片仍是组织原文材料，不等于模型已生成阶段性综合答案。下一片先复用已有模型综合/复核输出，接通研究中可阅读的归纳与其出处；不以更多过程标签替代内容，不增建独立研究状态机，不提前授予正式答案/研究质量GO。学习与教学仍为六项通用能力之上的专业场景。

**2026-10-18 当前片：保持大头像比例的聊天UI收简（本地，未合并）。** 分支 `codex/chat-ui-restraint-20261018`，工作树 `D:/study-agent-validation/chat-steer-attachments`，base **`a9efb72212c40b84a86bdc4a4165d98ef3ba2140`**；提交由本段所在Git提交恢复，审阅只看该base之后。**用户明确约束：角色头像不能缩成小消息图标；桌面保持既有96px，手机保持既有80px及相对视觉比例。不得为了留白而缩小头像。** 原截图灰头像来自 `frontend/e2e/api-fixture.ts` 返回灰圆SVG，真实资源 `assets/avatars/nahida.png` 正常；测试改用真实512px图片，浏览器断言图片加载与原有外框尺寸。

本片去掉助手正文气泡框和装饰尖角，用户消息仅留轻底色；研究状态合并一行、原文/结论边界文案收短；输入区改为上方文字、下方附件/方式/操作，同一入口保留研究调整与排队（原双按钮改为原生选择控件）。空输入不展示无用的追加按钮；通常说明保留给读屏，非冗余常驻标签。修复附件选择按钮被通用20px宽度覆盖而挤没文件名的问题。320px失败重试暴露底部错误提示遮挡发送按钮，已将操作错误提示移到顶部并修正窄屏宽度，未绕过错误或取消重试检查。

验证：前端相关组件/聊天控制器 **56 PASS**，全局提示 **3 PASS**；最终focused浏览器 **4 PASS / 10.0s**（320/390/768/1440px、真实头像80/96px、附件名可见、输入区<170px、键盘Tab、附加/排队失败重试/恢复选择/原SSE不中断/手动发送）；TypeScript/Vite build、Ruff、diff-check PASS。头像尺寸首次断言误测图片内框（78/94px），已改为检查原80/96px外框，未更改头像尺寸或放宽容差。未改后端/预算/Gate，不重跑上一片后端影响集及mypy；本轮零L3，无新CI、未推送/PR/合并/部署。日志 `D:/study-agent-validation/chat-ui-restraint-{unit,notices,final-browser,build}.log`；截图在 `frontend/test-results/conversation-continuous/*/research-opening.png`。提交后工作树干净。

**唯一下一片：阶段性资料按问题维度组织。** 保持当前UI与头像约束，在现有已读摘录上区分比较题的两侧/已知与缺口，让用户先获得有用内容；模型综合的阶段性答案仍未完成，不把摘录冒称已验证答案。不扩张学习系统，不重复全量回归。

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
