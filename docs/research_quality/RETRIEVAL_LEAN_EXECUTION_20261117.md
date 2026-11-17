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
