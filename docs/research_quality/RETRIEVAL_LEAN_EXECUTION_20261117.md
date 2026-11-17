# 2026-11-17 检索收口与项目减负：可复核执行记录

> **性质**：一次有日期的执行证据，不是新的长期状态表。当前权威状态仍以 `docs/PROJECT_STATUS.md` 为准；PR、CI 与提交均需按各自精确 SHA 复核。

## 用户裁定与不做事项

- 连续执行：#368 中文社区定向浏览器 → #369 免费覆盖率探针 → #370 DeepSeek Search/Fetch 预接入 → 项目减负 → 真实质量比较与发布链路收口。
- **真实浏览器的中文社区覆盖是必须保留的能力**，四道普通查询中搜索结果重合不能用来否定它。
- DeepSeek 独立搜索和网页抓取保持默认关闭；没有持久、跨 worker 的共享支出上限和新的费用授权前，**不得做付费探针或启用默认路由**。
- 没有运行真实模型、真实收费 Search/Fetch 或声称端到端质量提升；不删除历史证据或用户数据。

## 已观察的工程事实与修复

| 范围 | 观察与裁定 | 可复核证据 |
| --- | --- | --- |
| #365、#366 | 已入远端 `main@cf62add5`，分别提供默认关闭的双通道诊断和正文驱动缺口检索 | 合并提交 `494c1024`、`cf62add5` |
| #368 | 旧 head `da874f72` 的 CI `43933826559` 成功，但审阅发现米游社窄 facet 丢失游戏名会误入 `/sr/search` | PR 审阅线程 `PRRT_kwDOSYWoX864FPwg` |
| #368 修复 | 以 `SiteProfile.search_variants` 为唯一映射，保留原问题中的游戏名；回归覆盖原神、绝区零、崩坏三、未定事件簿 | 新 head `54195b661203d6a97068a5983fac3bbba26837a0`，精确树 `59d36e5b`；11 个无需 pytest fixture 的 facet 测试函数 PASS；CI 待验证 |
| #369 | 免费、两通道并发，报告真正新增的 URL 和普通正文读取是否成功；不将搜索命中冒充证据 | PR #369（叠在 #368 旧 head 上，后续必须更新基线） |
| #370 | 官方收费 Search/Fetch 接入两重关断，不能仅因可调用就认定比浏览器好 | PR #370；`WEB_DEEPSEEK_{SEARCH,FETCH}_ENABLED=false`、对应 `MAX_REQUESTS=0` |
| #370 安全补强 | 扩大对签名/授权类 URL 的拒绝范围，包含 OAuth code、session、凭据参数、片段和畸形 URL；不会将它们发送给外部 Fetch | 新 head `45708999df56c5802a6fffaf91df327f342e6d61`，精确树 `7920d3f8`；5 种新增 URL 负控通过；CI 待验证 |

## 减负：已执行的安全工作树整理

整理前共有 **12** 个 Git 工作树，主工作树含 **5 处用户未提交修改**，均未触碰。

- 完整检查各工作树 `git status --porcelain`；以下七个历史工作树均无未提交/未跟踪文件，对应阶段的功能已合入远端主线：
  `pr357-merge`、`pr360-merge`、`pr361-merge`、`pr362-coverage`、`pr363-official-index`、`pr364-searxng-errors`、`study-agent-simple`。
- 已使用 `git worktree remove <精确目录>` 移除上述七个**干净工作树目录**，未删除 Git 分支、提交或用户数据；需要时可通过保留的分支重新建立工作树。
- 整理后保留 **5** 个：`study-agent`（用户修改未动）、`pr368-gap-channel`、`pr369-community-probe`、`pr370-deepseek-search`、本次减负记录分支。

## 减负：静态结构审计，不预设结论

检查时项目约有 14.9 万行 Python 生产代码、15.1 万行 Python 测试代码；`active_research_runtime.py` 约 7,453 行、`web_lookup_service.py` 约 3,013 行、`chat_service.py` 约 2,589 行。`PROJECT_STATUS.md` 在近期功能分支上已约 1,474 行，冷启动入口重新膨胀。

检查 `active_research_runtime.py` 的已有读取调度逻辑和 `web_lookup_service.py` 的已读 URL 判断，**项目已经存在读去重控制**。因此本轮不新增第二套缓存；下一步应从真实 trace 衡量同一 URL 的重复读取、搜索结果重叠、站点独有贡献和阶段耗时，只有确认重复开销才改生产逻辑。

### 下一组独立、可撤销的减负切片

1. **交接文档**：在 #368/#369/#370 的交接条目进入 `main` 后，将历史当前状态按原文归档，主 `PROJECT_STATUS.md` 压缩成 150–250 行的现状入口；稳定规则仍只放 `AGENTS.md`/`PRODUCT_ITERATION_POLICY.md`，不另建长期 ROADMAP。
2. **检索成本**：复用 #369 测试和既有 `site_outcomes.new_results`，测量每通道有效增量、正文可读率、中位/P95、超时和重复读取；无质量对照前不裁剪社区浏览器。
3. **大模块**：先识别可独立抽取的无状态计算/诊断，再以现有测试保护做小批量移动；暂不碰运行状态机、持久化和对外契约。
4. **发布可靠性**：离线回放已有真实失败样本，先修会让用户得不到有效最终答案的缺陷；真实模型比较及额度仍须重新授权。

## 验证与严格边界

- 本次新增的修复使用 `compileall`、`git diff --check` 与不依赖 pytest 的定向负控，已记录具体结果。当前执行环境缺少 pytest/Ruff/mypy，不能把这些说成完整 L1/L3 门禁。
- #368、#370 新 head 推送后 CI 的首查没有返回运行记录；**合并以实际新 head 完整 CI 与审阅为准**，不能借用前一提交的绿灯。
- 专门的安全差异扫描技能配置参考文件不可读，已进行人工精确差异审查；不能称安全专用扫描完成。
- 未合并或未完成的事项不得写为已交付产品质量改善；当新的 `main` 确认后，在 `PROJECT_STATUS.md` 更新唯一下一门。

## 2026-11-17 收口补记（准确到 PR 头提交与合并提交）

> 此节只记录最终工程收口，不更改上文初次审计当时的观察状态；详细代码变更留在精确 PR，后续现状以 `docs/PROJECT_STATUS.md` 为准。

| PR | 精确审阅/CI | 合并入 main 的提交 | 处置 |
| --- | --- | --- | --- |
| [#368](https://github.com/2002yy/study-agent/pull/368) | 米游社路由 P2 修复；精确提交 CI 通过 | `5f146a67945a6b3d5fca36a3989f5017ddde5ca7` | 中文社区浏览器保留 |
| [#369](https://github.com/2002yy/study-agent/pull/369) | head `9456271e`；CI `44034118706` 成功；搜索策略 P2 修复并解决 | `faf1a94b02a1b903bbc8365ae19cf80f3b114374` | 免费探针、禁用付费 Search/Fetch 的负控；真实站点尚未跑 |
| [#370](https://github.com/2002yy/study-agent/pull/370) | head `12b550c7`；CI `44031322548` 成功；敏感 Fetch URL 安全 P1 已修 | `6a1c880ec045f5599e61bfeaccdffa687d1e3243` | 官方工具默认关闭；不做收费调用 |
| [#371](https://github.com/2002yy/study-agent/pull/371) | 静态记录 PR、精确 CI 成功 | `e06b882e752b777bda29a6b7efca52b799508740` | 原日期报告保留 |
| [#373](https://github.com/2002yy/study-agent/pull/373) | CI `44030559637` 成功；离线 AST 一致及 3 项纯单测 | `92af59377d0abe6ff5161ae0d29bc95ff1f2de21` | `active_research_runtime.py` 7,453→7,167 行 |
| [#374](https://github.com/2002yy/study-agent/pull/374) | head `b0659185`；CI `44032955744` 成功；AST 一致及 4 项纯单测 | `e5d4f037e30550440908adea0eabdfbfc3ccd1d0` | `web_lookup_service.py` 3,013→2,739 行 |
| [#375](https://github.com/2002yy/study-agent/pull/375) | head `b8b39e11`；CI `44032951521` 成功；AST 一致及 5 项纯单测 | `8fe57bc5f81586af6b9d01c2a8ff28b21604154c` | `chat_service.py` 2,589→2,361 行 |
| [#376](https://github.com/2002yy/study-agent/pull/376) | head `ce97add6`；CI `44033439005` 成功；审查 P2 门禁漏登已修；67/67 原测试函数 AST 不变 | `fb5272504f0de13bd71e8ec4c76a835627d65199` | `test_active_research_runtime.py` 5,934→5,458 行；新测试进入三项影响集 |

### 减负真正取得的收益与未取得的收益

- **已取得**：四个单文件分别减少 286、274、228、476 行；阅读职责更集中，跨文件导入兼容、原测试函数逻辑不改；移除七个已合并、没有用户修改的历史工作树。
- **不能宣称**：代码总行数减少（职责模块、导入和测试反而略增）、产品答案质量提高、真实社区来源覆盖改善、真实 DeepSeek Search/Fetch 可付费安全启用、完成专项安全扫描。
- **测试成本实测**：588 个 `test_*.py`、150,637 行、约 5,917 个 AST 定义；相同函数体仅 9 组、10 个额外定义，不能误删大部分测试。#373 后端 CI `7,347 passed、21 skipped`，耗时 `1,376.13s`。根因更偏向全量触发频率，须用明确影响集 + 保留完整 L3 的方式降成本。
- **保留状态**：用户原工作树的三处修改及两处新增文件未由本轮提交/覆盖；最新一次可执行环境的 `git status --short` 核对仍是原五项。最后整理文档阶段执行容器不可用，剩余临时工作树清理延期，不能宣称已移除；均为独立工作树，不能使用强制清理。
- **唯一下一产品实验**：在用户原部署环境以零模型调用跑 #369 真实社区覆盖探针，记录独有且正文可读的 URL、P50/P95 和失败；收费测试须有新授权和持久跨进程额度控制。

## 核心执行方法继续拆解：状态归属与闭包依赖（2026-11-17）

本节是 P3 架构切片的可恢复清单，不改变上面的产品实验和收费授权边界。

- #382、#383、#384、#385 已进入 `main@383e6440`。四个精确 HEAD 的 CI 分别为 `44074227494`、`44074756787`、`44075417217`、`44077179183`，全部成功。#385 冻结了模型请求前的持久 inflight 标记、阶段检查点和候选/读取/时间预算单调性；崩溃恢复及费用预留/结算负控保留。
- [#386](https://github.com/2002yy/study-agent/pull/386) 将有序检查点封装为 `ActiveRuntimeCheckpointContext`，尤其保留准备期间出错时已更新的局部状态；精确 HEAD CI `44080509512` 成功，已合并 `df6f2a7e`。[#388](https://github.com/2002yy/study-agent/pull/388) 以 `ActiveResearchResultBuffers` 显式持有同一组可变列表；精确 HEAD CI `44080750573` 成功，已合并 `0e72901d`。[#387](https://github.com/2002yy/study-agent/pull/387) 在同文件共用 40 处初始化，精确 HEAD CI `44079893336` 成功、已合并 `315b07a1`。合并主线 CI 仍须独立核查。

| 共享状态 | 写入者及风险 | 已有或预定的责任边界 |
| --- | --- | --- |
| `state`（研究图与预算） | 模型规划、追加要求、提取/门禁和预算刷新；不得与恢复游标形成不同检查点 | #385 契约；#386 检查点执行上下文 |
| `cursor`（波次、调用审计、失败、读取结果） | 每阶段可重绑定；请求前 inflight 与语义结果的持久化顺序不可改 | 研究恢复/模型尝试契约 + #386 |
| `context`（研究上下文、追加要求、诊断） | 仓储可能 CAS 合并并发 steering；写完需取回持久上下文 | #386 回填责任 |
| `query_attempts / selected_sources / rejected_sources / warnings` | 入口初始化后只原地增补，无重绑定；终态发布必须用同一组数据 | #388 结果缓冲区 |
| `timing_ledger / phase_started / breaker` | 可变观测和运行期健康状态；不能借拆分改变超时与重试策略 | #391 计时上下文、#393 观测函数、下一片读取尝试上下文 |
| `candidate_id` 等循环临时值 | 旧 `schedule_read(url)` 捕获外层当前候选，调用者看不出作用目标 | #390 已实现 `schedule_read(candidate_id, url)` |
| `run_id / operation_id / elapsed` | 一次执行内固定的身份和单调时间基线 | 明确作为执行上下文输入，不重置崩溃计时 |

职责边界按实际写入权归位；表中“仍在执行器”的部分是**明确保留**，不能仅因新增一个模块就宣称彻底拆完：

| 职责 | 已有明确所有者 | 尚需继续收口的隐式依赖 |
| --- | --- | --- |
| 研究状态与恢复 | `ActiveRuntimeCheckpointContext` 组织检查点，执行器负责真实 `state`/`cursor` 的重绑定与持久写回 | 请求前 inflight 顺序、恢复 CAS 回填和阶段转换仍在执行器，受 #385 冻结契约约束 |
| 检索与读取调度 | #390 显式候选身份；#394 的 `ActiveReadAttemptContext` 负责单次读取结果与派生观测 | 预调度闭包和波次推进仍在执行器；不能把可重绑定 `cursor` 缓存在上下文 |
| 模型调用与预算 | 执行器拥有供应商调用和结算；#392 纯函数只加工政策审计 | 请求开始/完成回调与预算占用仍紧邻持久检查点，不在本次拆开 |
| 证据整理与发布 | `ActiveResearchResultBuffers` 持有同组列表；证据投影模块只生成数据 | 终态门禁、选择发布和仓储写回仍由执行器排序 |
| 诊断与性能观测 | `RuntimePhaseTiming` 拥有阶段计时；#393 独立读取耗时/健康统计；#394 收拢尝试诊断 | 观察必须在读取结果游标写回之后，不能改变时钟采样次数或超时决策 |

读取调度先显式传入候选身份：旧 `schedule_read` 自由变量包含 `candidate_id`，新签名从实参接收，避免未来跨候选复用此闭包时误用上一轮循环值。接着将预调度和读取链两处相同的“每候选已尝试后端”逻辑统一为 `scheduler.attempted_read_backends(outcomes, candidate_id)`；从两处外围闭包读取 `cursor` 的重复计算，变为显式传入持久读取结果和候选身份的一个纯函数。保留遇到顺序去重、跳过空后端、跨候选隔离及读取阶段决策。新增隔离负控；此片不改读写账本、计费和发布。

### 后续结构片收口与正在执行的边界

| 结构片 | 状态、可复核静态证据 | 责任变化及非目标 |
| --- | --- | --- |
| [#390](https://github.com/2002yy/study-agent/pull/390) | 合并 `96ac38b654658c80e6da4445766b75c4610b5db3`，精确 HEAD CI `44086183784` 成功 | 读取候选身份显式化；不调整读取调度策略 |
| [#391](https://github.com/2002yy/study-agent/pull/391) | HEAD `9f1a8c7f753d783a0acb9eba4159273796db3023` 的 CI `44089619882` 成功，合并 `6e7e6c53f2e8535233e9e69d9c462172b1716e96` | `RuntimePhaseTiming` 拥有阶段起始字典和计时账本，`end` 显式接收**当前**上下文，防止恢复/追加要求后旧引用写入；不修改超时判定 |
| [#392](https://github.com/2002yy/study-agent/pull/392) | 旧 HEAD `025969de` 的 CI 后端失败、日志 404；重基后 HEAD `c45b8287` 的 CI `44106896286` 五项成功，已合并 `cfe9ca16c584e282b9624eebb17b58fd475c76ef` | `updated_model_policy_audits` 只负责原形状、顺序、100 条上限的纯投影；模型准入、网络调用与计费责任仍留原位置 |
| [#393](https://github.com/2002yy/study-agent/pull/393) | HEAD `271010c377037dd3c09ea842cb2d7e26bc2eec61` 的 CI `44100349280` 五项成功，合并 `5bcfc8a0e0166936ab1223ee4a38c9e134a7b7fd` | `_record_read_timing` 与 `_record_backend_health` AST 主体原样迁出，旧入口仍可导入；不修改读调度和预算 |
| [#394](https://github.com/2002yy/study-agent/pull/394) | HEAD `7f7dbf7a` CI `44108108094` 五项成功；#392 合入后核实主线 tree `7db0fd9d` 与原验收基线一致，改为 main 后合并 `b6c98f9daf0a9ee1484a1f9562ae7bdca92ed075` | `ActiveReadAttemptContext` 显式传入当前游标/上下文；32 处重复恢复游标解码收口 |

#392 先合并、核对主线树与 #394 验收时基线一致、再合并 #394 的顺序已执行。执行方法里的 `state`、`cursor`、`context` 仍属不同生命周期：**不能**为了减少一层闭包而将重绑定游标固化为旧对象，也不能越过请求前 inflight 持久化；后续拆分继续遵守此门禁。

### 读取尝试上下文：已合并的恢复注意事项

- 诊断独立片 #393 已在精确 HEAD CI 全绿后合并，读取耗时与后端健康记录迁入 `research_runtime_read_observability.py`；原执行器的同名入口仍可导入。
- 已合并 #394 的 `ActiveReadAttemptContext` 管理每次真实读取尝试的游标结果、断路器健康、读取耗时与升级诊断。`context` 和 `cursor` **每次调用都从当前执行现场显式传入**，上下文对象只持有本次运行固定的断路器及诊断记录器。
- 特意拆成 `cursor = append_outcome(...)` 然后 `observe_step(...)` 两步：如果诊断阶段失败，执行器仍保留已经产生的内存游标结果；合并为一个返回值的函数会悄悄改变该异常时序。升级读取仍仅在真正发起 Wigolo 时调用研究时钟，避免统计动作改变耗时预算；记录 invocation_id 必须先于追加 attempt 行。
- `_record_escalation_diagnostics` 的 AST 主体与原实现完全一致；新增真实尝试的成功/失败游标、诊断失败、后端健康、时钟调用次数与升级 invocation/attempt 顺序负控。原先暂存组合树相关离线 **279 passed**；重新组织提交后六个主要影响文件 **124 passed（141.37s）**、Ruff 和 diff-check 通过，精确 HEAD CI `44108108094` 五项成功。全量 L3、真实浏览器产品质量对照和付费模型 **not_run**。
- 测试共用既有 `_candidate()` 造景辅助，4 个新增测试并入同一读取诊断测试文件，避免为相同候选构造再建一个重复辅助。
- 继续检查 `test_active_research_runtime.py` 的恢复游标读取，发现 **32** 处可统一的三行 `ResearchRuntimeCursor.from_dict(run.research_context[...])`，改用一处 `_cursor_from_run(run)`；旧 `_a2e_cursor` 重复包装亦已归并。直接传递原始字典、模拟中断游标的两处特殊构造保持原写法。测试文件净减少约 **60 行**；静态核对 **63/63 个测试函数、481/481 条 `assert`** 没有删减。此变更属于场景搭建与重复解码的合并，不改变测试断言和场景输入。

## 2026-11-18 续记：读取准入与真实尝试分开

新主线 `b6c98f9daf0a9ee1484a1f9562ae7bdca92ed075`（#394 后）已核实；#392、#394 精确 HEAD CI 都是五项成功，且 #394 验收时的基线树与 #392 合并后的主线树完全一致。这一结论只涉及代码兼容性，不替代产品动态回放。

下一批清理 `execute()` 中唯一的预调度闭包 `schedule_read`。它同时捕获**当前** `cursor.read_outcomes`、`context`、断路器和剩余研究窗口；未来若要独立修改检索/读取调度，开发者还得理解恢复与预算的重绑定时机。新边界是 `schedule_active_research_read`：由调用方显式传入当前候选、URL、读取历史、研究上下文、断路器、既有后端顺序及剩余时间回调。保留这些冻结条件：

1. 每个候选独立计算已经真实尝试的后端；其他候选不能消耗本候选读槽，legacy 空后端仍不计入。
2. 仍先收集尝试历史，再取剩余时间；不提前/额外采样单调时钟，不改变准入决定、超时、网络行为。
3. 只记录现有 `read_scheduling` 数据形状，最多 60 条；未真正读取时不产生 `read_outcomes`，不会修改模型预算或发布。
4. 调用方继续拥有当前 `cursor` 和 `context`，调度模块只执行一次判断与诊断投影；结果仍交给原调用点处理。

这是继 #394 后的独立静态片。除代码审查、定向离线测试和精确 HEAD CI 外，不声称真实社区覆盖率或答案质量变化。

### 下一组诊断归属：研究窗口（待 #395 先收口）

执行器中 `record_research_window`、`record_research_window_skip` 的实际共享对象是当前 `context`、`state.budget.hard_timeout_seconds` 和研究时钟。前者还在记录后紧接 `checkpoint()`，**不能**把检查点职责塞进诊断模块。暂存下一组设计为 `ResearchWindowDiagnostics`：

- 每次由调用点给出当前 `context` 和 `hard_seconds`；固定末尾预留秒数由运行期诊断对象持有，决不缓存可能被持久化回填替换的上下文。
- `record_end` 只生成旧形状的 `research_window`，必须调用 `elapsed()` **两次**，并由执行器在其返回后继续原顺序 `checkpoint()`；该方法本身不持久化。
- `record_skip(context, key)` 只累计 `research_window_skips`，旧值非 dict 时重建；不构造读取尝试或改变断路器健康。
- `research_seconds_left`、研究窗耗尽准入和 `ensure_budget` 保留原表达式，不在这一片重算、收紧或延长研究时限。

本片作为独立于 #395 读取准入模块的后一批，需冻结回归与自己的精确 HEAD CI；两片仅共享主运行器的不同闭包区域，**不得在前片未验收时提前合并后一片**。
