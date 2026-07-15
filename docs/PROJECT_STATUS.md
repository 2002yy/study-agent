# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-15  
> 当前能力基线：PR #43 已合并，核心学习产品 G1–G8 已形成可信状态、结构化恢复、可整理、准确导航、聚焦主界面与窄屏完整可用闭环
> 当前代码切片：将聊天工具循环统一关联 durable ResearchRun，并继续补齐请求级取消与恢复

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。核心学习主链已具备单一持久化 TaskContract、LearningClosureRun、结构化证据总结、线程级 summary status、可信四态学习状态、语义化会话导航、结构化恢复卡、聚焦后的一级操作与窄屏完整可用界面；聊天联网工具循环正在接入带 thread/turn owner 的 durable ResearchRun。G10 同时已具备可恢复 ResearchRun、commit-pinned GitHub 快照、四语言结构图、模块/re-export/overload 语义、单符号影响分析、Git 历史对象、PR/issue/CI 联合研究、跨版本 hunk-to-symbol 影响分析、source-backed PR review context，以及初版 REST/GraphQL 分页、共享请求预算和 cross-fork PR 证据归属。**

## 2. 已完成

### 核心学习产品 G1–G8

1. **G1 LearningClosureRun**：学习整理拥有 durable owner、正式状态机、source hash 幂等、retry/cancel/resume 和 MemoryRun 关联；刷新后可恢复，research 不会被错误写成学习总结。
2. **G2 结构化总结输入**：只使用 committed LearningState、最终 PedagogyEvalRun、证据引用、受预算限制的最近对话和冻结记忆上下文；失败/中断回合不能伪装成已掌握，候选保存来源、置信度和评估引用。
3. **G3 summary status**：确认写入后形成 `summarized / needs_update / not_summarized` 真值；新完成回合才重新开放整理；设置变化和失败回合不会误触发；提供“继续当前 / 归档并新建”，从不自动归档。
4. **G4 会话导航语义化**：会话列表统一展示 title、objective/research summary、recent preview、task intent、phase/gap、summary status 和 updated_at；自动标题与手动标题分离；支持搜索和按时间/状态/任务分组；旧会话兼容。
5. **G5 学习状态去伪精化**：主 UI 只读取 committed truth 与正式 PedagogyEvalRun 四态；committed/attempted 分离，非学习任务不再伪装成长期掌握进度，也不再用启发式百分比制造虚假精度。
6. **G6 结构化恢复卡**：新用户提供快速问答、系统学习、联网研究、项目推进和上传资料五类入口；返回用户按 committed task/goal、确认点或已披露来源、缺口和下一步恢复；interrupted turn 支持继续、重试和 durable abandon，放弃后刷新不会再次复活。
7. **G7 UI 聚焦收敛**：一级操作收敛到当前任务收束、上传、会话和 More；检索、来源、设置与低频工作区下沉但保持可达；普通态不再暴露 memory 文件名、run/step/session ID、route code 和低层 Provider 参数。
8. **G8 窄屏完整可用**：顶部操作、More、输入、会话与抽屉在窄屏、触控和非 hover 环境完整可达；知识库开发代理与关闭后焦点恢复已通过浏览器验收。

正式学习闭环当前已经可以走通：

```text
明确目标
-> 教学推进
-> 证据追溯
-> 理解验证
-> 结构化整理
-> 用户确认记忆
-> 标记本次已整理
-> 新内容出现后重新开放整理
-> 下次按语义会话准确恢复
```

### 可恢复 ResearchRun

```text
planned
-> searching
-> assessing
-> reading
-> synthesizing
-> completed | partial | failed | cancelled
```

- 先创建 Run，再访问外部 Provider。
- 查询和来源读取后写 checkpoint。
- 保存查询尝试、采用/拒绝来源、读取结果、预算、错误和停止原因。
- 支持 retry / resume / cancel / get / list。
- operation ownership + version CAS 阻止旧请求覆盖新结果。
- `status` 表示流程状态；`provider_status` 表示证据完整度。

当前取消属于协作式取消。同步网络请求需要返回或超时后才能进入取消分支，但取消后不会提交 completed 结果。

### Commit-pinned GitHubRepoSnapshot

- 支持 repository、README、tree、blob、raw 和 Contents API URL。
- 保存 requested ref、resolved commit SHA、tree SHA、file SHA、源码、失败和预算。
- tree、blob 和源码 URL 均固定到 immutable commit SHA。
- exact query 在 TTL 内复用；后续问题优先复用已有快照。
- 旧版无 commit SHA 的缓存自动失效并重新生成。
- 服务重启后从 SQLite 恢复代码、结构和语义索引。

```env
GITHUB_SNAPSHOT_CACHE_TTL_SECONDS=1800
GITHUB_SNAPSHOT_FOLLOWUP_MAX_FILES=12
GITHUB_SNAPSHOT_MAX_FILES=24
GITHUB_SNAPSHOT_MAX_FILE_CHARS=12000
GITHUB_SNAPSHOT_MAX_TOTAL_CHARS=120000
```

### 本地代码搜索、结构理解与单符号影响

- path / symbol / snake_case / CamelCase。
- BM25 风格词法检索和 exact phrase。
- Python、JavaScript、TypeScript/TSX、Java 固定 Tree-sitter grammar。
- definitions / imports / calls / constructors / inheritance。
- callers / callees / hierarchy / implementations / related files。
- bounded upstream/downstream impact、相关文件和测试映射。
- grammar 失败时保留 AST/正则 fallback。

生产工具：

- `github_search`
- `github_snapshot`
- `github_structure`
- `github_impact`

### 结构化证据和身份

`EvidenceRef` 包含 repository、requested ref、resolved commit SHA、tree SHA、path、file SHA、symbol、kind 和行区间。

`SymbolIdentity` 进一步加入 language、kind、qualified name、signature 和稳定 ID。相同 commit/tree snapshot 内身份稳定；版本变化时身份变化。

### 模块、re-export、overload 与 LSP 边界

已合并 PR #25：

- `ModuleIdentity`；
- TypeScript/JavaScript barrel 与 `export ... from`；
- Python package root、绝对导入和 `__init__.py` re-export；
- Java package + class identity；
- 显式 import/re-export 链优先于全局同名猜测；
- 无上下文的同名符号保持 ambiguous；
- `OverloadGroup` 和模块限定查询；
- `LspAdapter` / `NullLspAdapter` / callback adapter；
- 请求路径不会自行启动语言服务器或 shell 子进程；
- deterministic resolution / impact / test-mapping golden set。

### Git ref、commit、compare、diff 与 blame

已合并 PR #26：

- 默认 branch、branch、tag、annotated tag、完整 SHA 和短 SHA；
- `resolved / ambiguous / not_found / unavailable`；
- branch 与 tag 同名冲突时不猜；
- annotated tag 有界 peel；
- commit tree、parents、author、committer、stats 和 verification；
- compare 前固定 base/head commit SHA；
- ahead/behind、merge base、bounded commits/files/patch；
- unified diff old/new hunk 行区间；
- Token-gated GraphQL blame；
- 无 Token 时明确返回 unavailable。

模型工具/API：

- `github_ref` / `POST /github-ref`
- `github_commit` / `POST /github-commit`
- `github_compare` / `POST /github-compare`
- `github_blame` / `POST /github-blame`

### PR、issue、checks 与 CI 日志

已合并 PR #27：

- PR metadata、immutable base/head commit、changed files、patch 和 hunks；
- review submissions、inline comments、普通 comments；
- Token 可用时读取 review threads 的 resolved/outdated 状态；
- issue metadata、comments、events 和 linked commit SHA；
- check-runs、workflow runs、jobs、runner、steps 和 conclusion；
- CI 日志只接受具体 job ID，返回有界尾部；
- 去除 ANSI，并对常见 token/key/secret 形态和 `add-mask` 脱敏；
- 部分 Provider 失败时保留主体结果并返回 `provider_status=partial`。

模型工具/API：

- `github_pr` / `POST /github-pr`
- `github_issue` / `POST /github-issue`
- `github_checks` / `POST /github-checks`
- `github_ci_logs` / `POST /github-ci-logs`

```env
GITHUB_WORK_ITEM_CACHE_TTL_SECONDS=300
GITHUB_PR_MAX_FILES=50
GITHUB_PR_MAX_PATCH_CHARS=120000
GITHUB_ITEM_MAX_COMMENTS=100
GITHUB_PR_MAX_REVIEWS=100
GITHUB_ISSUE_MAX_EVENTS=100
GITHUB_CHECKS_MAX_RUNS=20
GITHUB_CHECKS_MAX_CHECKS=100
GITHUB_CHECKS_MAX_JOBS=100
GITHUB_CI_LOG_MAX_CHARS=40000
GITHUB_CI_LOG_MAX_LINES=400
```

### 跨版本 hunk-to-symbol 影响

PR #28 已实现：

1. 通过现有 history service 固定 base/head commit SHA。
2. 对两侧建立 bounded commit-pinned snapshot。
3. 将 compare hunk 的 old/new 行区间映射到 Tree-sitter symbols。
4. 为两侧符号生成稳定 old/new `SymbolIdentity`。
5. 按 language + kind + qualified name 保守配对。
6. 输出 added / removed / modified / moved / ambiguous。
7. 比较 signature，单独返回 `signature_changed`。
8. removed symbol 在旧图执行 impact；其他变化在新图执行 impact。
9. 聚合 affected files、related tests 和 missing-test symbols。
10. missing-test 仅是静态映射信号，不代表测试一定缺失或无覆盖。

存在 bounded snapshot、patch、symbol 配对、预算或 parser/index 不完整时返回 `provider_status=partial`，不把不完整分析伪装成完整结果。

模型工具/API：

- `github_change_impact`
- `POST /github-change-impact`

### Source-backed PR review context

PR #31 已完成 G10-C2.4 初版：

1. 读取 PR metadata、immutable base/head SHA、files/hunks、review submissions、inline comments、review threads、checks 和 jobs。
2. 使用固定后的 base/head SHA 调用现有 `github_change_impact`，不按移动分支名分析。
3. 将每条 review location 分别映射到 changed file、diff hunk 和 changed symbol。
4. 唯一包含符号返回 mapped；多个同跨度候选返回 ambiguous，不猜测。
5. unresolved review threads 单独聚合，并统计 hunk/symbol 覆盖率。
6. 失败 check/job/step 只在名称、路径或 token 有证据时关联 affected tests、files 和 symbols。
7. 泛化 test job 最多以 low confidence 关联已有 affected tests；无法关联时保留 uncertainty。
8. 输出 immutable ref、changed-file impact、review-hunk、review-symbol、failed-job association 五类 evidence coverage。
9. Provider partial、patch 截断、review thread 不可用、位置不明确和 CI 无法关联均显式降低完整度。
10. 固定返回 `verdict.status=not_generated`，不自动给出 approve/reject、正确/错误或是否存在 bug 的结论。
11. 组合层已拆为 orchestration、review mapping、CI association 和 evaluation，避免继续扩大单个 GitHub 巨型服务。
12. 已加入 deterministic precision/recall/F1 evaluator 和首批 checked-in curated replay labels。

当前 evaluator 和 labels 是初始评测基础，不等同于已经完成跨仓库、真实 Provider 重放的代表性评测。

模型工具/API：

- `github_pr_review_context`
- `POST /github-pr-review-context`

### GitHub Provider 分页、共享预算与 cross-fork 取证

PR #32 已完成 G10-C2 第一轮 Provider 硬化：

1. REST 多页读取已覆盖 PR files、reviews、inline comments、issue comments、issue events、check-runs、workflow runs 和 workflow jobs。
2. GraphQL review threads 使用 `pageInfo.hasNextPage/endCursor` 逐页读取。
3. 每个集合同时受 item budget 与 page budget 限制；组合 PR 请求另有共享 REST/GraphQL request budget。
4. PR metadata、各集合、review threads、checks/jobs，以及实际 base/head 仓库的 immutable commit detail 均计入同一个 PR request budget。
5. 达到 item/page/request budget 或后续 Provider 失败时保留已取得证据，并输出 `stop_reason`、`truncated`、`provider_count` 和 `provider_status=partial`。
6. API 与 `github_pr_review_context` 模型工具可显式设置 `max_provider_requests` 和 `max_pages_per_collection`。
7. cross-fork PR 明确保存 base/head repository、repository URL 与 immutable SHA；head commit detail 从 fork 仓库读取。
8. checks 首先按目标 PR 仓库取证；不可用时可回退到实际 head/fork 仓库，并记录 `checks_repository`。
9. 当前同仓库 change-impact owner 不能安全组合两个仓库的源码图，因此 cross-fork PR review context 不伪造语义影响，而是返回 `cross_repository_change_impact_not_supported` uncertainty。
10. review thread 内的 comments 当前每个 thread 最多读取 100 条；若 Provider 仍有后续页则显式标记 `comments_truncated`，尚未实现嵌套 comment cursor。
11. 独立 `github_checks` 的 ref 解析仍由 Git history owner 在集合预算前完成；集合预算覆盖 check-runs、workflow runs 和 jobs，不应解释为跨 owner 的绝对全局预算。
12. 分页实现已拆为 provider pagination、base/GraphQL、checks/jobs、PR/fork 和 issue facade 五个模块；最大新增生产模块 485 行，未保留首稿 1086 行巨型服务。

```env
GITHUB_PROVIDER_MAX_REQUESTS=24
GITHUB_PROVIDER_MAX_PAGES_PER_COLLECTION=10
GITHUB_PROVIDER_PAGE_SIZE=100
```

### CI 与外发策略稳定化

- pytest、前端、detect-secrets 和 mypy 均先保留诊断 artifact，再执行独立门禁；
- expanded mypy 采用增量基线门禁；任何新增或扩大的错误会阻止合并；
- `web_policy=ask` 只接受显式 `web_consent` 或内部一次性 consent marker；普通 `web_context` 文本不会隐式授权联网；
- 报告保留 7 天。

### TaskContract 单一真值

PR #30 已完成主链收口：

1. 新 Turn 在读取线程学习状态后只判定一次 TaskContract。
2. 优先级固定为：显式 override > 明确文本意图 > active learning 继承 > quick-answer 安全默认。
3. 路由快照、外发策略、教学评估、教学计划、RAG/Web 选择与 pedagogy snapshot 使用同一合同。
4. continuation 与 retry 优先恢复原 Turn/父 Turn 的持久化合同。
5. `POST /chat` 与 `POST /chat/stream` 接受受限枚举 `task_intent`。
6. 前端只展示服务端持久化合同，不再根据 `learning_state` 二次推断。

当前显式 override 已接入主界面按 Turn 一次性选择；发送后自动清空，retry/continuation 不继承新的 override。

## 3. 还差什么

| 能力 | 状态 | 主要缺口 |
|---|---|---|
| LearningClosureRun | 已完成 | G1 durable 状态机、幂等、恢复、retry/cancel 已合并 |
| 结构化总结与 summary status | 已完成 | G2–G3 已合并，后续只需随产品验证继续收敛 |
| 会话语义导航 | 已完成 | G4 已合并，已支持标题、目标/研究摘要、阶段/缺口、状态、搜索和分组 |
| 学习状态去伪精化 | 已完成 | G5：可信四态、committed/attempted 分离、非学习结果状态已合并 |
| 结构化恢复卡 | 已完成 | G6：新老用户恢复入口、继续这里/新主题、partial/interrupted 恢复与 durable abandon 已合并 |
| UI 聚焦收敛 | 已完成 | G7：一级动作收敛、普通态内部 memory/run/route/provider 标识降噪已合并 |
| 窄屏完整可用 | 已完成 | G8：顶部操作、More 菜单、输入、会话与各类抽屉的触控/非 hover/安全区验收已合并 |
| 广域网页搜索 | 本切片推进 | 聊天工具循环已创建带 thread/turn owner 的 durable ResearchRun，并回写工具 trace 与 `run_id`；还需请求级取消和恢复 |
| cancel/retry/resume | 基础完成 | 聊天工具 ResearchRun 的异步请求级取消、统一超时、实时阶段事件与恢复 |
| 网页读取 | 基础完成 | PDF、动态页面、登录状态页面 |
| GitHub repo/tree/blob/raw | 基础完成 | submodule、LFS、超大文件 |
| 持久化仓库快照 | 基础完成 | manifest 增量刷新、过期清理、磁盘统计 |
| 本地代码搜索 | 初版完成 | embedding 融合与真实仓库评测集 |
| Tree-sitter / 模块语义 | 初版完成 | 更多语言、package-manager exports、动态派发 |
| LSP | 适配边界完成 | 实际服务器生命周期、workspace trust、超时和缓存 |
| 单符号影响 | 初版完成 | 数据流、配置影响、风险分层 |
| Git ref/commit/compare | 基础完成 | 多页 commit/files、超大 compare、持久化缓存 |
| blame | 基础完成 | Token 授权体验、超大文件和 Provider 替代方案 |
| PR / review | 分页基础完成 | nested review comment cursor、持久化缓存、cross-fork 语义影响 |
| issue | 分页基础完成 | release、linked PR、完整 timeline、项目字段、持久化缓存 |
| checks / jobs / logs | 分页基础完成 | ref-resolution 预算统一、artifacts、rerun attempt、日志分段、持久化缓存 |
| 跨版本结构影响 | 初版完成 | rename inference、AST edit、跨文件移动、cross-repository 图、真实仓库评测 |
| PR review context | 初版完成 | cross-fork 语义影响、持久化缓存、多仓库真实 replay corpus |
| 全量 mypy 零错误 | 未完成 | 增量门禁已阻止新增，后续应按模块逐步归零 |
| TaskContract UI override | 已完成 | 按 Turn 一次性选择已接入；发送后清空，retry/continuation 不继承新 Turn override |
| 本地 checkout | 未完成 | clone/fetch/checkout 和 worktree 隔离 |
| 测试与构建 | 未完成 | 受控环境、命令预算、日志和回滚 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要、仅本地模式 |

## 4. 下一代码顺序

### 核心学习产品优先

1. **聊天工具 ResearchRun 请求级控制**：在 thread/turn owner 与工具 trace 持久化基础上，补齐异步请求级取消、统一超时和失败恢复。
2. **聊天研究阶段事件**：让前端通过正式 `run_id` 读取实时阶段、失败原因与可恢复操作，而不是依赖一次性响应 trace。

### G10-C2 持久化缓存

1. 为 work-item、checks、change-impact 和 review-context 定义稳定 cache key 与 schema version。
2. 使用 SQLite 保存 payload、immutable refs、provider status、预算、创建时间和过期时间。
3. 区分 complete / partial / failed cache 的复用规则，失败或超预算结果不得长期污染。
4. 增加 TTL、按 repository/kind 清理、磁盘统计和 cache manifest。
5. 服务重启后复用 immutable 证据；移动 ref 必须重新解析后再决定是否命中。
6. 增加 migration、兼容恢复、过期清理和并发写入回归。

### G10-C2 后续 Provider 补齐

1. review thread 内 comments 的嵌套 cursor。
2. checks ref resolution 与集合请求的跨 owner 预算合同。
3. cross-fork base/head 双仓库 snapshot 与 change-impact 图。
4. release、artifact metadata 和按需下载。
5. CI 日志按 run attempt、job、step 和时间窗口定位，而不只读取尾部。
6. 扩充真实多仓库 replay corpus，分别报告 symbol mapping 与 CI association precision/recall。

### G10-D：可执行仓库代理

1. 受控临时目录 checkout。
2. 只读环境和命令白名单。
3. 运行 test、lint、build。
4. 可写 worktree、diff、回归和回滚。
5. 增量更新、缓存清理和磁盘预算。

## 5. 当前验证

核心学习产品最近完整门禁：

- PR #37（G2）：最新 head 完整 pytest、Ruff、package helper、detect-secrets、expanded mypy、frontend Vitest、TypeScript build、Vite production build 全部通过后合并。
- PR #38（G3）：最新 head CI Run #915 完整通过后合并。
- PR #39（G4）：最新 head `9896272b678723677aabba6f9d1b523d244e5c17`，CI Run #947 完整通过后合并；前端 139 个测试、TypeScript build 和 Vite production build 均通过。
- PR #40（G5）：已合并，可信四态与 committed/attempted 边界进入主线。
- PR #41（G6）：最终 head `f04dc4c16cf8a936d4871e45b027bdff7de4af78`，CI Run #994 完整通过后合并；pytest、Ruff、package helper、detect-secrets、expanded mypy、153 个前端测试、TypeScript build 和 Vite production build 全部通过。
- PR #42（G7）：最终 head `eb61f0cbd27ee9fe51a65fadabf358470f43d094`，CI Run #1015 完整通过后合并；pytest、Ruff、package helper、detect-secrets、expanded mypy、159 个前端测试、TypeScript build 和 Vite production build 全部通过。
- PR #43（G8）：最终 head `f78b9b1` 的两条 CI 均通过后合并，merge commit `6e1d107`；本地 1440 / 760 / 430 px 浏览器验收覆盖 More 菜单、设置抽屉、滚动锁、关闭后焦点恢复与知识库开发代理。
- 当前聊天 ResearchRun owner 切片：目标测试 17 passed，完整 pytest 756 passed，Ruff 全量通过，前端 47 个测试文件 / 164 个测试及 TypeScript/Vite build 通过；等待本切片远程 CI 复核。

PR #31 功能代码验证：

- pytest：711 passed；
- Ruff、package helper、detect-secrets、expanded mypy 增量门禁：passed；
- frontend Vitest、TypeScript build 和 Vite production build：passed。

PR #32 功能代码验证使用 GitHub Actions CI #742，代码 head `d28bb4461716340738ae3d629a90da72b9b630de`：

- pytest：719 passed；
- Ruff：passed；
- package helper：passed；
- detect-secrets：passed；
- expanded mypy 增量门禁：passed；
- frontend Vitest、TypeScript build 和 Vite production build：passed。

GitHub Provider 分页切片回归覆盖：

- REST 多页合并和额外一条 truncation 探测；
- Provider 后续页失败仍保留已取得 evidence；
- page budget 与 request budget 耗尽不伪装成 complete；
- GraphQL review-thread cursor 传递；
- workflow jobs 跨页合并；
- cross-fork head commit 从实际 fork 仓库读取；
- checks 从目标仓库失败后回退到 fork 仓库；
- PR base/head immutable commit detail 计入共享请求预算；
- API 和模型工具预算范围校验；
- cross-fork change-impact 限制转为显式 uncertainty；
- 旧 API、工具 dispatch、mypy 和前端回归保持通过。

## 6. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
