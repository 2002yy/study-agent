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

### 读取链测试造景去重（待前两批收口）

`test_active_research_runtime.py` 中 `_cutover_service` 与 `_a2e_service` 曾各自构造同一种 `ActiveResearchGateway`、模型网关和执行器，只在是否指定检索后端上有区别；现在将检索后端设为 `_cutover_service` 的可选输入，A2e 端到端测试复用同一构造入口。`_cutover_run` 继续保留场景名称与原始参数，但内部复用 `_pending_active_run`，不重新复制 `WebLookupRun` 的 pending/planned 字段。重复的 `_a2e_sources` 与 `_breaker_sources` 投影合并为后者，保持 `Mapping` 过滤和浅字典复制不变。

此片**只改测试代码**，保留所有测试、断言、固定 URL、断路器配置、升级读环境与账本检查；不改生产检索、读取消费、恢复、模型预算或发布。定向 `test_active_research_runtime.py` **84/84 passed**、Ruff 与 diff-check 通过；依赖的 #395、#396 均未满足合并门禁前，该片仅作为堆叠草稿验收，不能提前合入 main。

## 2026-11-18 依赖收口与模型政策上下文

[#395](https://github.com/2002yy/study-agent/pull/395)、[#396](https://github.com/2002yy/study-agent/pull/396)、[#397](https://github.com/2002yy/study-agent/pull/397) 已按序完成**各自原 HEAD** CI（`44125608541`、`44126675280`、`44127618845`，均成功）和人工复核，分别合并 `bd7fd5dc`、`30c27cf2`、`4f46684d`。每合并一项均重新拉取 main 并比对 tree，依次等于先前验收基线 `9d96107b`、`02c395cf`、`7044d37f`；两处堆叠 PR 均在其父 PR 合并、同树核实后才改基线和合并。三个 PR 的静态通过不代表真实研究质量提升，真实付费调用 **0**。

下一独立片的模型政策审计曾在 `execute()` 中通过 `model_allowed` 闭包读取当前 `context`、`self.policy_check` 和 `self.utc_now`。运行期的新 `RuntimeModelPolicyContext` 只持有后两项稳定依赖；每次检查以参数接收**当前上下文**，仍严格遵守 `policy_check` → `utc_now` → 更新 `claim_engine_policy_audits` 的原时序。任何政策检查或时钟异常都不能提前改写审计；审计仍保留旧字典形状、顺序和 100 条上限。执行器中的薄包装继续保留原先每个模型准入点的调用位置。

**特别不改**：`on_model_started` 的 `ensure_active` → `ensure_budget` → `begin_model_attempt` → `checkpoint`；`on_model_finished` 的 `finish_model_attempt` → `ensure_active` 且没有即时检查点；真实费用 `reserve_call` 仍在模型网关里、发生在请求前检查点之后。模型“成功后、语义结果持久化前”崩溃必须依旧通过中断未知尝试恢复，不能把完成审计独立提前落盘。

### 持久故障行的投影边界（独立后一片，依赖模型政策片）

执行器原 `_append_failure` 同时捕获**可重绑定**的 `cursor`、`context` 来生成故障身份，再使用 `replace(cursor, failures=append_runtime_failure(...))`。新 `with_appended_runtime_failure(cursor, context, ...)` 将当前两项作为明确输入，返回替换后的新游标；调用点依旧只在原时序将返回值赋给 `cursor`，没有新增检查点、恢复、模型结算或发布操作。

保留 `attempt_id or f"run-attempt:{context['run_attempt']}"` 原有**惰性**求值：显式 attempt_id 存在时不应访问缺失的 `run_attempt`；反之缺失时照旧抛 `KeyError` 而不改变输入游标。已有 `runtime_failure_id`/`runtime_failure_id_unattached`、`build_runtime_failure`、`append_runtime_failure` 三处身份与幂等去重权威保持原样。新增直测包括当前上下文跨恢复、同一尝试重复插入幂等、显式 attempt 短路及缺失上下文失败；不得因为纯函数迁移而更改历史故障 ID。

### 模型调用前后回调的显式执行上下文（独立后一片）

原 `on_model_started`/`on_model_finished` 两个闭包共享并重绑定 `cursor`，同时要求取消/硬预算准入、检查点在严格时机触发。`ActiveModelAttemptContext` 以注入的 `current_cursor`/`set_cursor` 接口取得**实时**游标；执行器仍拥有实际游标变量和 `checkpoint()` 实现。新对象不缓存游标，也不接管供应商请求或实际费用账本。

时序原样冻结：

1. 请求开始：`ensure_active` → `ensure_budget` → 读取当前游标 → `begin_model_attempt` → 更新内存游标 → **调用旧 checkpoint** → 网关后续才可 `reserve_call` 和发请求。
2. 请求完成：读取当前游标 → `finish_model_attempt` → 更新内存游标 → `ensure_active`；**这里仍不 checkpoint**。成功解析的语义结果由原调用点负责下一次持久化。
3. 预算拒绝前不能更新游标；开始阶段检查点抛异常时，内存中的 inflight 不得丢失；完成阶段在取消检查抛异常时，已追加的内存 audit 不得被回退。游标被恢复/其他操作重绑定后必须读取最新值。

新增直接负控依次验证以上五种情况。真实 `reserve_call` 在 `model_gateway.py` 的原位置不动；本批不声称解决跨进程预算或真实模型回答质量问题。依赖前面的模型政策与故障投影片按序验收后才可并入主线。

### 2026-11-18：#398 收口与读取站点专家上下文

[#398](https://github.com/2002yy/study-agent/pull/398) 原 HEAD `25ae27cdb05e3b2f5d334e65a8a2b06594473137` 对应 CI `44135910377` 成功；审阅无线程阻断，按预期 HEAD 合并 `b4ae42918e2494db9e858d28c8944fff6e5a3fee`。拉取 `main` 后 tree `69154167ec64d92a8a6255c78448d623e525955f` 与原验收树一致。#399、#400 的 CI 在此轮首次回看仍在运行，继续保留草稿并禁止越级合并。

下一小片读取站点的 `read_site_hint_route`、`specialist_chain_run`、`record_read_site_specialist` 与 `execute()` 内唯一专家调用闭包，归入 `research_runtime_read_site.py`：`ActiveReadSiteContext` 只持有当前研究窗口的剩余硬预算**回调**，每次 `try_specialist(context, candidate, source_limit)` 均接收当前可被 checkpoint/steering 回填的上下文，绝不缓存旧映射。默认读取链仍是唯一兜底执行权威；只有显式提示且专家返回可用正文时才短路；无提示不访问预算时钟、不写多余专家诊断，失败或未满足提示仍回落原链。`active_research_runtime.py` 保留旧路由/记录/链标准化导出，避免已有测试和外部调用破坏。

此片不迁移检索调度、真实读取尝试或恢复/费用账本；已有端到端 selector 测试继续覆盖真实默认链，新增直接负控仅检查**无提示不调用**、跨上下文/候选与时间变化、不可用专家回退及记录形状。待本地定向测试和精确 PR HEAD CI 取得结果后再记录最终门禁，不把静态验收当真实浏览器、模型或检索产品质量验证。

### 2026-11-18：故障投影和模型尝试生命周期收口

[#399](https://github.com/2002yy/study-agent/pull/399) 精确 HEAD `b676659bc94783a36e064f38f685900a6d1e0094`，CI `44136804289` 成功、审阅无阻断，#398 合入主线并同树核验后改 base 为 main，再合并 `f2666db8d2e80503fe1f18d1a881fe168674ae67`；主线 tree `618e987fb9b4807062bc84f9046788e6d3321001` 与 #399 验收树一致。

[#400](https://github.com/2002yy/study-agent/pull/400) 精确 HEAD `b505fb3f0f62c9b58611aff86f3c5a84c58b206c`，CI `44138134273` 成功、审阅无阻断，#399 合入主线并同树核验后改 base 为 main，再合并 `9abe320d7361d2ee96d8046b5312088fed2b2714`；主线 tree `8e9fef3e4e9f304693133a60353e447bff3f54a8` 与 #400 验收树一致。这两片只形成静态工程证据，不宣称动态质量提升，真实付费调用 0。

[#401](https://github.com/2002yy/study-agent/pull/401) 已以 HEAD `4d01a31247864ab8c2f3cadb9b1a50d7fb365df1` 和 tree `50211070e7f2384af3dd20c59ae15ebc8eb61090` 创建草稿；本地影响集 108 passed，测试造景去重后 15 passed、Ruff/diff-check 通过，人工复核无阻断线程。CI `44140163266` 本次回看仍在运行；#400 合并后主线树与其验收父树一致，已重定基线为 main。未取得本 HEAD CI 成功前不能合并。

### 证据终态发布参数归属（独立后一片）

执行器内正常波次结算、硬预算耗尽和有证据的异常结束，各自重复拼装 `repository.complete()` 的 `items`、`source_block`、`warnings`、四组共享缓冲区、当前上下文、停止结果字段。新 `ActiveResearchPublisher` 只持有一次运行固定的仓储、run/operation 身份和 `ActiveResearchResultBuffers`，发布时**显式接收当前 `context` 和 `ResearchStopDecision`**；不缓存可能被 checkpoint/CAS 回填替换的研究上下文。

保留每种调用路径**原先**的检查点和停止门禁时机：正常路径在完成游标检查点之后发布，预算异常路径在原窗口诊断/检查点之后发布，有证据异常路径先写原故障 checkpoint（若失败允许旧容错）再发布部分结果。无证据失败仍走执行器自己的 `repository.fail`。内部参数求值仍按 `eligible items → evidence brief formatting → warning dedupe`；异常路径的 `_evidence_brief(state,None,...)` 必须在 eligible 投影之后计算，预算异常仍按 `state.evidence` 选择显式 confidence，不能被 canonical stop decision 的 `partial` 覆盖。负控对照正常、预算和异常三类发布以及不完整简报不得终态写入。此片不涉及真实模型、预算结算、来源质量判断或前端发布策略。

### 2026-11-18：#401 验收合并与停止信号投影

[#401](https://github.com/2002yy/study-agent/pull/401) 精确 HEAD `4d01a31247864ab8c2f3cadb9b1a50d7fb365df1` 的 CI `44140163266` 已成功；无阻断审阅，依精确提交合并 `8f5a2ff0cb5c7a3d746bb5abf940b224df330cd0`。拉取后主线 tree `50211070e7f2384af3dd20c59ae15ebc8eb61090` 与原验收树一致。该片无真实模型或联网读取，静态结论不外推为浏览器产品质量。

[#402](https://github.com/2002yy/study-agent/pull/402) 发布上下文 HEAD `a7d67a074149a30bb802249c4c82c61f82e9defd` 的 CI `44141917095` 最近一次观察仍在运行；#401 同树合并后已改为 main 基线，仍是草稿，**不得跳过精确 HEAD CI 就合并**。

后继独立片收窄至 `settle_completed_wave` 中的停止信号推导，不改 `ResearchStopGate` 决策优先级、不移动 steering 合并/迟到标记检查点，也不移动波次推进和最终发布检查点：

- `completed_wave_stop_signal(state, cursor, context, gate, actionable_gaps, hard_exhausted, wave_exhausted)` 是无写入的投影；`_ordered_gaps(state)` 仍由执行器选出，与检索计划相同的可行动范围，纯上下文缺口不延长主动波次。
- 原本连续的 `open_gap_claims → critical/conflict 额外批次 → saturation → 当前 durable late-steering` 顺序不变。普通 claim 连续两批无增益饱和，critical/冲突 claim 允许第三批；恢复后的当前 `context` 可否决基于旧图计算的 gate pass。
- 执行器仍唯一持有当前游标重绑定、硬预算计时、`ResearchStopGate.evaluate`、`checkpoint` 和 `publisher.complete`。新模块既不查询时钟也不推导费用，不能将晚到 steering 的结算改为一次调用期间的局部返回值。
- 新增独立投影测试复用一处研究状态和信号搭建，覆盖普通/关键/冲突阈值、不可行动上下文缺口、恢复后的迟到 steering 和证据/波次标志；既有运行器/停止门禁回归继续作为分层约束。

本片本地定向离线回归：新投影、停止门禁、主动研究运行器及费用边界共 **133 passed（102.63s）**，Ruff 与 diff-check 通过。未执行全量 L3、真实浏览器或付费模型调用；精确远端 CI 留给本片自己的 HEAD 验收。

### 2026-11-18：跨窗口合并顺序与研究上下文联合片

远端主线核实 `f9332655`。正在收口的独立 PR：#404 研究运行器测试工厂（精确 CI `44146778208` 成功）、#405 预算时钟（`44149454756` 成功）、#406 旧新闻兼容层/测试删除（`44150453199` 成功）；#407 旧探针删除、#408 API 兼容桥删除在本轮唯一一次观察仍处于 CI 运行中，不能宣称成功。五片都以相同主线为基线，**均未合并**。

合并路线：

1. **#405 优先**：研究运行器模型/检索窗口的预算时钟是结构片的直接父依赖；完成审阅与精确 HEAD CI 后先合入主线。不能因本地组合测试通过跳过自己的门禁。
2. **#404、#406、#407、#408 独立收口**：#404 只改运行器测试场景，#406–#408 的生产/测试路径与本窗口研究运行器改动没有重叠；后续各自解决 `docs/PROJECT_STATUS.md` 并发修改，在最新 main 上重新核对后合并。#407/#408 必须等待各自精确 CI 完成及审阅，无权由本窗口抢先合并。
3. **本窗口联合上下文 PR**：以 #405 远端 HEAD `dec1dd3d` 为基线，包含 steering/波次结算的五个代码及测试文件和两份新增交接记录；只读/不覆盖另一窗口的改动。#405 合并后先把 PR 基线切到 main，再取 #404/#406–#408 最新合并结果检查文档冲突及运行器测试，完成自己的精确 CI 和审阅后才能合并。

执行期共享可变状态仍由研究执行器拥有：`state/cursor/context` 每次传给 `ActiveWaveSettlementSnapshot`，检查点前后通过同一适配显式回填，成功/异常都不留下失同步副本；`ActiveResearchSteeringContext` 每次接受当前上下文，不缓存恢复前的引用。测试仅新增必要的上下文时序负控，复用运行器已有的模型费用、指令迟到、崩溃恢复和停止门禁案例；不新建同套全流程场景。**冻结保证**：`ensure_active → steering refresh → budget/wave check → late/apply → checkpoint → stop gate → cursor → checkpoint → publish`；模型请求前 inflight、完成后审计以及真实 `reserve_call` 权威均不移动。

### 下一批已记录：读取调度与当前状态传递（待实施）

本批先完成 `ResearchBudgetClock`/`TimingLedger` 的观测辅助边界及 `ActiveResearchResultBuffers` 的实时证据身份投影；二者是 #409 后的独立堆叠片，**不是读取调度重写**。下列范围仅立项，不计作本批完成：

1. 先从现有执行器读取入口标注 `state/cursor/context` 的唯一持有者、检查点回填位置、读取候选及诊断/计时的消费点；避免从恢复前捕获的闭包取得旧上下文。
2. 把相互依赖的候选预调度、读取链选择、后端健康、尝试历史和当前预算窗口整理为**一次读取调度上下文**。它接收当前快照和明确回调，不另起第二套读取链或持久化权威。
3. 分批迁出剩余闭包：先迁只读投影与后端选择，再迁实际读取调用边界；每片保留原 `ACTIVE_READER_CHAIN`、读取名额、断路器/重试/兜底和当前上下文时序。
4. 测试只保留能区分恢复后上下文、预算耗尽、读取失败兜底的最小负控；复用既有读取测试场景，不重复搭一整套研究/模型/发布流程。#404 和另一窗口功能删减各自独立收口。

**必须冻结**：检查点顺序、CAS 恢复后 `state/cursor/context` 的重新绑定、模型请求前 inflight、真实 `reserve_call`/最终结算，以及有证据发布门禁。本片无真实模型或付费浏览器调用；静态验证不代表动态产品质量。

### 2026-11-18：读取调度上下文第一片（本地候选）

- **基线**：从 `main@f7531d19` 单独开工；#405、#409、#420、#422 的预算时钟、steering、波次结算、实时证据缓冲已在主线。#404 的测试工厂和其他窗口的功能删减不属于此片。
- **唯一状态持有者**：`execute()` 仍持有可重新绑定的 `state/cursor/context`。`checkpoint()` 内部从持久仓储重取 `context`；读取候选从当前 `cursor` 解码；读取名额、字符、停止原因和 `read_outcomes` 继续由运行器更新。
- **新边界**：`ActiveReadDispatchContext` 只绑定一次运行稳定的断路器、后端顺序和研究剩余时间回调。`schedule()` 显式接收当前候选、历史结果和 `context`，读取链在真正派发前再次以当前 `read_outcomes` 取得该候选的后端尝试历史，断路器健康也经上下文查询。绝不保存恢复前的 `cursor/context` 引用。
- **冻结且未迁移**：`ACTIVE_READER_CHAIN`、专家读取失败后的默认链、原始 `run_chain` 和真实后端执行器均仍是权威；候选读名额、硬预算、失败记录、逐尝试外部标记、检查点时序、模型 inflight/费用及证据发布均未变。静态回归需覆盖恢复后上下文变化、候选隔离、断路器关闭/开启和真实读取链，不能用新增的纯单测替代运行器用例。
- **本地静态证据**：调度模块新增恢复后重绑定和断路器边界检查；运行器、读取站点、链单一权威、预算时钟、波次结算、模型尝试和研究恢复的组合影响集 **169 passed**。最终断言微调后调度单测复核 **6 passed**；`ruff check src tests tools`、`git diff --check` 通过。首次 mypy 在原父基线下报告 118/128 既有错误、**0 项新增**；不将这些静态证据冒充真实模型、检索或浏览器验收。
- **下一独立片**：待这片审阅合并后，再把 `read_chain_executors` 与默认链派发整理进同一上下文；注入当前网关读取函数及时间源，保留 `build_read_chain_executors`/`run_chain` 单一实现权威，迁移时同步调整脆弱的源码字符串测试为有意义的行为约束。真正的检查点与费用写入仍由原执行器所有。

### 2026-11-18：读取链执行上下文（依赖 #434，独立候选）

- **父基线**：#434 的已验证读取预调度上下文（本地 tree `79671e5d`），与远端 #434 HEAD `5ff7b4b4` 同树；#434 的精确 HEAD CI 尚在运行时，本片只在独立工作树实施，不提前把依赖片当作 main。
- **实际拆分**：`ActiveReadExecutionContext` 持有本次运行稳定的网关、真实 `gateway_read`、硬预算时间回调、预调度上下文、专家入口及注入的共享执行器工厂/读取链函数；每次 `run_candidate()` 都显式接收当前候选、研究 `context`、历史 `read_outcomes`、读取字符上限和外部尝试序号。原执行器内 `read_chain_executors` 闭包和专家/默认链分支迁到此对象。
- **权威不变**：调用仍落在原 `build_read_chain_executors`、`run_chain` 和 `ActiveReadSiteContext.try_specialist`。专家有可用内容才短路，无提示或不可用仍走默认链；执行函数只返回 `ChainRun` 和实际步骤，不追加永久读取结果、不写预算或检查点。所有后端开始/完成标记、诊断记录、故障去重、来源写入、阶段检查点与停止发布仍在原循环并保持原相对顺序。
- **定向负控**：用轻量替身验证专家先于默认链、可用专家短路、共享执行器工厂只在默认链调用、候选历史和当前上下文跨调用不缓存；把单一权威的字符串匹配测试改为代码结构检查和行为测试，不重造研究状态/数据库/模型运行场景。
- **本地验证**：读取执行上下文、共享链权威、站点选择与调度定向 **29 passed**；`p2-a-retrieval-stack` 阶段门 **467 passed、4 skipped**（98.62 秒）；后续执行边界和阶段策略复核 **18 passed**。`ruff check src tests tools`、`git diff --check` 通过；mypy 当前 115、允许基线 125，**0 项新增错误**。尚无本片远端精确 HEAD CI 和动态浏览器/模型验收。
- **后续方向（本片之后）**：继续把只负责记录的读取链度量整理到现有读取观测模块，保持每次真实后端尝试先进入游标、再写诊断的顺序；评估已有测试造景的调用方后再删重。任何持久化/预算权威迁移另起冻结契约与 PR。
