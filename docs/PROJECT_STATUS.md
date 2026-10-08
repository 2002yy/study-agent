# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-10-08（Deep-4A CLOSED；Deep 阶段除 4B 外全部 CLOSED）
> 产品定义：**Study Agent 是长期保持“正在学什么、已经确认什么、还不会什么、下一步是什么”的个人学习工作台。**

本文件只维护当前权威状态、可复核边界和唯一下一门。2026-10-06 本次收敛前的完整状态原样归档到 [`archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)；更早历史继续由既有 archive 与 Git 历史持有。

## 0. Current Handoff（cold-start 入口）

**2026-10-08 最新用户裁定：B线继续独立推进RP-1（覆盖下方“须等#201才施工”）：** 工作树 `D:/study-agent-validation/reading-notebook-ui`、branch `codex/reading-notebook-ui`，本刀基线head `ec02590f`（共同研究main766c0b67，复用UI精修e1a24697）；不操作#201远端门，也不合入Learning State-1。完成只读投影/恢复、SSE、身份与版本隔离、审计/发布隔离的R1–R5修复：区分run事件与turn快照，用既有ChatTurn.updated_at防审计回退；SSE不取消进行中的恢复请求，新工作可重启已停止的跟踪；拒绝别名block身份；未知状态与原型键安全兜底；真实旧版Deep按后端research_mode呈现，计数仅采用观测记录，不用未仪表化默认0。前端466/build PASS、最终命名L2 258 PASS（102.31s）、mypy122/baseline128 NEW0、Ruff/diff-check PASS；最终浏览器79 PASS（2.1m）、真实React/FastAPI/SQLite交互14 PASS（49.8s），桌面/手机截图已视觉核对；21文件范围增量自审无未解决本地finding；候选head由Git与rp1-closeout-state.json恢复，未push/未开RP PR，结果目录 `D:/study-agent-validation/reading-notebook-ui-evidence/rp1-*`。R6真实HTTP/SSE五个样本及SQLite原始状态保留，现有来源新代码只读重投影5/5、DB字节不变；TTFP4.797–11.125s为单次观测，TTUV仍null，不授予速度SLO。带扩展措辞的样本因requested_claim_plan_unavailable停止，合法FastAPI两字段样本仍因no_verified_relevant_source未进入Standard；同步旧版Deep不冒充现代后台Deep链。**RP-1整体NO-GO / R6 NOT CLOSED**，不扩大引擎/证据资格或发布权限以取得绿灯。唯一后续slice：取得真实合格Standard→后台Deep进入与恢复样本，补TTUV/操作证据后才封R6并执行新候选L3/远端门；没有把旧UI的4142后端结果授予本RP候选。原main及A线dirty未动，#201仍归独立交付。

**2026-10-08 #201 合并前收尾（用户指定先完成，再继续 RP-1）：** UI worktree `D:/study-agent-validation/ui-main-integration` 已 fast-forward 到远端生产 head `366c9594b2bd8a7afd1eee226867979c688737ba`，保留独立未提交 RP-1。图片许可修复覆盖 Markdown 与 study-ui，当前 head 前端 456 PASS、build PASS、完整浏览器 77 PASS；真实 API 浏览器14 PASS、#200 组合候选相邻回归77 PASS（85.72s），完整记录见 `D:/study-agent-validation/reading-notebook-ui-evidence/pr201-366c-*.log`。旧 CI `37764419949` 的失败定位为 Playwright 系统依赖从 Ubuntu Azure 镜像下载超时约20分钟，浏览器验收未执行；其余门（后端4142/6 skip、frontend、Ruff、mypy baseline）通过。相同 head 已启动该失败 run 的 attempt 2，一次观察为 queued，不能视为 green。用户授权的独立 `@codex review` 已发到 #201 comment6059011576，服务已确认当前审查 head366c959。当前远端 main `0de807513e758bac3ab6d10a35be3e1320772552`（#200已合入）；merge-tree无冲突，隔离组合候选841f4493仅用于相邻学习/阅读/聊天回归，不是生产交付SHA。UI PR clean，原main四项dirty保持不变。**唯一下一门：** 本地验收已完成，结果索引pr201-closeout-state.json；后续turn检查既知run/current-head review；green且无未解决finding后expected-head Squash merge，再验证exact-main CI；未完成前不得称REMOTE GO或开始RP-1实施。RP-1仍在本worktree等待，冻结R1–R6合同与现有未提交成果保留，不授予R6资格。

**B线 Research Presentation-1施工检查点（未CLOSED）：** 独立worktree `D:/study-agent-validation/reading-notebook-ui`，branch `codex/reading-notebook-ui`，仅负责B；共同研究基线 `766c0b67442bfbbc4b8fc63e4acd00757c0062bb`。完整保留原UI及d48091d5模型选择工具提交，原UI最新精修已通过独立draft [PR #201](https://github.com/2002yy/study-agent/pull/201) 推送为 `e1a24697f1fad1546614fd81123bc56db90cdca4`（CI run37761697236一次观察为in_progress）。本分支同步其精修用于现有预览，不把未提交研究协议送入#201。冻结合同见RESEARCH_PRESENTATION_1_CONTRACT.md。

**B施工范围与证据：** 已加只读研究投影/恢复GET、兼容SSE research_presentation、来源与支持/审计隔离、稳定run版本/turn/session隔离、EOF无terminal错误处理。Deep审计复用validate_recorded_publication；波次/阶段复用load_runtime_cursor；未知Standard读取数保持null。Deep候选正文/模型价格不进入投影，原whole-answer gate和学习判定不改。新基线后端69 PASS；增加游标负控并修正测试位置后，投影/Standard绑定/Deep执行65 PASS，Ruff PASS。前端460 PASS/build PASS是同步本轮精修前的证据；完整R1–R6最终门尚未执行，R6真实三层案例/延迟仍待完成，不能以模拟浏览器或12次Flash教学pilot宣布研究GO。旧main15c的后端L3约35%因基线变化中止，不算通过。当前研究feature文件未提交/未推送、现有UI整合与其分离；唯一下一slice：验证同步精修后的R1–R5恢复/真实状态投影，再完成R6真实研究验收。Deep-4B仍NO-GO，不自动改正式答案。

**2026-10-08 B线：先接入已完成UI（验收中）：** 用户要求之前前端改动尽快接入。独立worktree `D:/study-agent-validation/ui-main-integration`、branch `codex/ui-main-integration`；基线 main `766c0b67442bfbbc4b8fc63e4acd00757c0062bb`，复用现有UI head `511f21286e9fc7545dbacaac831945bf2470af00`，保留原提交历史。包含阅读并排/对话居中、纸白蓝灰及设备字体偏好、四角色最新版头像、内部角色设置、框内紧凑自增高输入框、右上资料开关、可记忆拖动宽度、只读正文/PDF与引用定位，以及已完成的教学交互组件。Learning State-1和尚未提交的Research Presentation-1均不混入此PR；研究协议/真实三层R6继续由原reading-notebook-ui分支负责。

**精修与新基线本地证据（LOCAL UI GO / 合并门未关闭）：** 联网提示收成默认折叠的12px说明，实页桌面50px/手机54px高，原策略说明仍可键盘展开；左栏去掉重复资料标题、副说明、零计数和空会话冗长提示，统一列表/底部对齐及字号。frontend 453 PASS，完整浏览器77 PASS（含手机/窄屏/Firefox/WebKit），真实React/FastAPI/SQLite交互14 PASS，阅读/附件/引用/流式影响集82 PASS，tsc+Vite build与Ruff PASS；mypy无新增错误（122/128，消除6条既有错误）。当前自审无未解决范围内问题。UI整合生产起点 `f60c27e576a8c2d2460d7747f1fee7f4d504b5d4` 的L3预检PASS，完整后端回归仍运行，不能报full PASS；后续精修仅前端和浏览器用例，不变更后端/后端测试。最终head由Git恢复；CI、独立最终review和合并主线门待完成，不能借旧CI宣告REMOTE GO。主目录既有dirty保留；A线独立worktree不动。Deep-4B仍NO-GO，教学模拟组件不形成研究发布权限。

**失败与恢复证据：** 首次real-stack 11/14，两个旧“更多开始方式”定位和手机未开导航的整理入口过期；更新入口保留所有取消/同run重试/学习提交断言。第二次13/14，原测试把完整可见token误当durable commit；增加等待真实turn-end状态后14/14。精修后的首轮浏览器75/77仅底部字号旧13px断言过期；统一为12px后77/77，提示条新增高度/折叠/键盘展开断言。日志及1440/390截图留在 `D:/study-agent-validation/reading-notebook-ui-evidence/ui-integration-*` 和 `ui-refined-final-*`。唯一下一门：固定UI PR head、记录一次exact-head CI、完成L3与独立最终review后才合并；Research Presentation-1的R6不作为此UI PR的虚假已完成项。

**当前执行权：Deep 阶段收尾 / 学习主线开启。** Deep-4A implementation 已合并并 CLOSED；**Deep 阶段除 Deep-4B 外全部 CLOSED**。Deep-4B（automatic publication）= **NO-GO**（无 qualified semantic judge）。下一刀 = **Learning State-1**（学习状态 bounded contract）；同时用户已指示先冻结一份独立的 **Intelligent UI × Lookup/Standard/Deep 交互合同**，**两条线不得混入同一个 PR**。

**Current Action：**
```text
Deep-4A is merged and CLOSED (authority ea73b855).
Deep-4B automatic publication is NO-GO until a qualified semantic judge exists.
Next slice = Learning State-1 bounded contract (L1–L6).
Next slice (parallel track, separate PR) = Intelligent UI × Lookup/Standard/Deep interaction contract.
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
2. **Deep（Deep-1 / Deep-2 / Deep-3T / Deep-3 / Deep-4A 全部 CLOSED；Deep-4B NO-GO；当前 = Learning State-1）**：多轮重写、Evidence Gain、saturation、长预算与 interruption/resume；UI 继续独立后置。合同见 [`DEEP_1_CONTRACT.md`](DEEP_1_CONTRACT.md)，已冻结四件事：Standard → Deep 升级条件、Deep 独立预算（`DEEP_V1_BUDGET`）、如何复用 Standard 已有 evidence 而不重读（durable seed + 二次 hash 校验）、stop / saturation / interruption-resume 定义（全部复用现有 authority）。

**状态口径：** `Standard = CLOSED ✅`；`Lookup` 保持其既有已验收状态；`Deep-1 / Deep-2 / Deep-3T / Deep-3 / Deep-4A = CLOSED ✅`；`Deep-4B = NO-GO`；下一刀 = `Learning State-1`（学习状态 bounded contract，L1–L6）；`UI = 后置`（独立交互合同另开一 PR）。

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
