# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-17
> 当前能力基线：PR #47 已合并，核心学习产品 G1–G8、聊天 ResearchRun 恢复/取消/EvidenceTrail 闭环、G10-C2 cross-fork Provider 取证及 G10-C3a 前两批 replay 已进入 `main`
> 当前代码切片：G10-C3a 第三小批已发布为 Draft PR #48，新增 Pydantic/JUnit 5/pytest 失败 CI replay，当前 7 仓库/8 case；下一步继续扩到 24–30 case，并补 rename/delete、Provider 截断、缓存复放与可独立标注的失败测试正例

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。核心学习主链已具备单一持久化 TaskContract、LearningClosureRun、结构化证据总结、线程级 summary status、可信四态学习状态、语义化会话导航、结构化恢复卡、聚焦后的一级操作与窄屏完整可用界面；聊天联网工具循环已接入带 thread/turn owner 的 durable ResearchRun、请求级取消、正式恢复入口、准备阶段实时事件，以及恢复来源与 EvidenceTrail 的同 Run 可信归属。G10 同时已具备可恢复 ResearchRun、commit-pinned GitHub 快照、四语言结构图、模块/re-export/overload 语义、单符号影响分析、Git 历史对象、PR/issue/CI 联合研究、跨版本 hunk-to-symbol 影响分析、source-backed PR review context，以及 REST/GraphQL 分页、共享请求预算、cross-fork PR 证据归属和 base/head 双仓库 change-impact。**

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

```env
WEB_TOOL_REQUEST_TIMEOUT_SECONDS=45
```

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
9. cross-fork PR review context 复用 PR 已取得的 immutable comparison：base/head 分别从实际目标仓库与 fork 仓库按 SHA 建 snapshot，再组合 change-impact；结果、symbol identity、snapshot evidence 与缓存身份均保留两侧 repository 归属。
10. review thread 内 comments 已实现每线程独立 cursor，并保留逐线程 provider count、截断与 stop reason；外层与嵌套 GraphQL 请求共用同一请求预算。
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
| 广域网页搜索 | 本切片推进 | 聊天工具循环已创建带 thread/turn owner 的 durable ResearchRun，并回写工具 trace 与 `run_id`；准备阶段通过同一 `run_id` 推送版本化阶段/失败事件，失败/取消 Run 已接入正式恢复入口 |
| cancel/retry/resume | 本切片推进 | 浏览器预分配 Turn owner，停止时请求 durable ResearchRun 取消；失败/取消可重试或继续；恢复来源进入下一轮后旧恢复卡退出，服务端校验 source block 并将同一 `run_id` 写入 EvidenceTrail；还需真实浏览器验收 |
| 网页读取 | 基础完成 | PDF、动态页面、登录状态页面 |
| GitHub repo/tree/blob/raw | 基础完成 | submodule、LFS、超大文件 |
| 持久化仓库快照 | 基础完成 | manifest 增量刷新、过期清理、磁盘统计 |
| 本地代码搜索 | 初版完成 | embedding 融合与真实仓库评测集 |
| Tree-sitter / 模块语义 | 初版完成 | 更多语言、package-manager exports、动态派发 |
| LSP | 适配边界完成 | 实际服务器生命周期、workspace trust、超时和缓存 |
| 单符号影响 | 初版完成 | 数据流、配置影响、风险分层 |
| Git ref/commit/compare | 基础完成 | 多页 commit/files、超大 compare、持久化缓存 |
| blame | 基础完成 | Token 授权体验、超大文件和 Provider 替代方案 |
| PR / review | 分页增强完成 | 原始 work-item 持久化、真实多仓库 replay corpus |
| issue | 分页基础完成 | release、linked PR、完整 timeline、项目字段、持久化缓存 |
| checks / jobs / logs | 分页基础完成 | ref-resolution 预算统一、artifacts、rerun attempt、日志分段、持久化缓存 |
| 跨版本结构影响 | 双仓库图完成 | rename inference、AST edit、跨文件移动、真实仓库评测 |
| PR review context | 双仓库取证完成 | 多仓库真实 replay corpus、symbol/CI association 质量指标 |
| RAG 索引一致性 | 基础完成 | server-owned RagRun、staging/active version、CAS 写租约、失败不激活、Chroma stale 清理已完成；还缺可恢复的逐文档摄取队列和 parser/chunker manifest |
| RAG 检索质量 | 初版完成 | BM25、向量、RRF hybrid、metadata filter、来源限额、可选 reranker 与 explainable debug 已完成；当前仅 6 条干净 fixture，缺真实学习语料与困难负例 |
| RAG 文档理解 | 基础完成 | Markdown/TXT/DOCX/PDF 纯文本摄取可用；缺标题/章节/表格/页区块等结构化解析、切块预览和扫描件/OCR 降级说明 |
| RAG 回答可信度 | 未完成 | 已有 citation-first context 和来源行号；缺回答级 citation precision/recall、groundedness、answerability/refusal 与 stale revision 评测 |
| KnowledgeBase 治理 | 初版完成 | 文档列表、稳定 document/revision identity、删除与索引版本已完成；缺 collection/scope、active revision、完整文档/聚焦检索策略和增量同步 |
| 全量 mypy 零错误 | 未完成 | 增量门禁已阻止新增，后续应按模块逐步归零 |
| TaskContract UI override | 已完成 | 按 Turn 一次性选择已接入；发送后清空，retry/continuation 不继承新 Turn override |
| 本地 checkout | 未完成 | clone/fetch/checkout 和 worktree 隔离 |
| 测试与构建 | 未完成 | 受控环境、命令预算、日志和回滚 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要、仅本地模式 |

## 4. 下一代码顺序

### 核心学习产品优先

1. **聊天研究浏览器验收已闭环**：刷新恢复、进入下一轮、旧卡退出与同一 ResearchRun 的 EvidenceTrail 已通过；真实慢查询已覆盖 planned/searching/reading/synthesizing/completed，停止会取消 chat-owned Run，失败卡可正式重试。取消后旧实时进度遮住 cancelled 终态的缺口已修复并补回归。

### G10-C2 持久化缓存

1. **已完成基础设施**：统一 v1 cache key/schema，可承载 work-item、checks、change-impact 和 review-context。
2. **已完成 SQLite repository**：保存 payload、immutable refs、provider status、预算、创建时间和过期时间。
3. **已完成复用规则**：complete 使用配置 TTL，partial 最长 60 秒，failed 不写入持久缓存。
4. **已完成运维原语**：TTL、按 repository/kind 过期清理、磁盘统计和 cache manifest。
5. **已完成三类生产接入**：checks 与 change-impact 在移动 ref 先解析为 commit SHA 后支持跨服务重启复用；review-context 还将当前 files/reviews/review threads/checks 证据指纹纳入 key，base/head 不变但评论或 CI 变化时也不会误命中。PR/issue 原始 work-item 仍保持内存缓存。
6. **已完成首轮回归**：schema v16 migration、跨重启恢复、过期、partial/failed、并发 upsert、manifest/stats 与移动 work-item 不持久化均有测试。

### G10-C2 后续 Provider 补齐

1. **已完成 review thread 嵌套分页**：thread comments 跟随独立 cursor，保留每线程分页、provider count、截断与 stop reason，并与外层 REST/GraphQL 共用总请求预算。
2. **已完成 checks 跨 owner 合同**：fork PR 的 head SHA 优先在 head repository 查询，按剩余共享预算回退 base repository；结果记录候选仓库、尝试顺序、请求消耗与最终证据仓库。
3. **已完成 cross-fork 双仓库 change-impact**：直接消费 PR 的 immutable files/hunks，base/head 分别按实际 repository URL 与 commit SHA 建 snapshot；缓存 key 同时绑定两侧 repository 与 SHA，同 SHA 不同 fork 不会串用结果，snapshot 失败继续以 repository-aware uncertainty 降级。
4. release、artifact metadata 和按需下载。
5. CI 日志按 run attempt、job、step 和时间窗口定位，而不只读取尾部。
6. 扩充真实多仓库 replay corpus，分别报告 symbol mapping 与 CI association precision/recall。

### G10-D：可执行仓库代理

1. 受控临时目录 checkout。
2. 只读环境和命令白名单。
3. 运行 test、lint、build。
4. 可写 worktree、diff、回归和回滚。
5. 增量更新、缓存清理和磁盘预算。

### 2026-07-17 开源对照审计：GitHub 仓库代理

对照 [OpenHands](https://github.com/OpenHands/OpenHands)、[SWE-agent](https://github.com/SWE-agent/SWE-agent)、[aider](https://github.com/Aider-AI/aider) 和 [Continue](https://github.com/continuedev/continue) 后，当前判断如下：

1. **现有优势应保留**：immutable commit、cross-fork repository 归属、Provider 分页/共享预算、partial/uncertainty 降级和 EvidenceTrail，比通用代码代理更接近审计级只读取证。
2. **最高优先级缺口是真实评测，不是更多接口**：当前 curated review-context label 很小，尚不能证明 symbol mapping、CI association 和 change-impact 在真实多仓库上的代表性质量。SWE-agent 的 benchmark/replay 与 aider 的长期代码编辑评测说明，执行能力扩张前必须先有不可回退的质量基线。
3. **执行边界尚未建立**：当前 snapshot 明确不是 checkout；尚无受控工作目录、sandbox adapter、命令 schema、输出预算、进程/网络/磁盘限制和重启清理。OpenHands 将命令/文件动作放进独立 sandbox 并返回结构化 observation；该边界应先于任何可写代理。
4. **任务意图不能替代执行授权**：TaskContract 继续负责学习/研究/项目目标；另建 `ExecutionPolicy` 负责 `allow / ask / exclude`。参考 Continue，读取默认允许，写入、安装依赖、联网命令和 shell 默认询问；headless 中无法确认的动作拒绝执行。
5. **模式需要明确分层**：只读取证、只读 checkout、受控 test/lint/build、可写 worktree 是四个不同能力层，不应通过一个“项目模式”一次性全部开放。

#### G10 推荐门禁与顺序

1. **G10-C3a 真实 replay harness**：至少 6 个公开仓库、24–30 个 immutable case，覆盖 Python/TypeScript/Java、普通 PR、cross-fork、rename/delete、CI 失败和 Provider 截断；分别报告 symbol mapping 与 CI association precision/recall/F1、coverage、partial rate、请求数、延迟和缓存命中率。
   - **第一小批已完成**：新增 schema v1 manifest、immutable base/head SHA 校验、context 路径边界、唯一 case ID、语言/场景/provenance 元数据、确定性 CLI，以及 symbol/CI 微观与宏观指标、Provider status/partial/request/latency/cache 汇总。
   - PR #28/#30 已迁移为 2 个 `curated_unit_seed`；报告固定显示 `provider_replay_cases=0`，不会把人工单元样例伪装成真实 Provider replay。下一批仍需采集跨仓库、跨语言真实 context，达到代表性目标前不启用质量门禁。
   - **第二小批已完成录制与本地基线**：新增生产路径录制器，只保存 immutable source、symbol/CI 映射、change-impact label candidates、Provider 预算与覆盖元数据，不保存评论正文、完整源码或令牌；manifest 会校验 recording 的 repository/PR/base/head 与声明完全一致。
   - Flask #3709、Vite #144、Gson #705 形成 3 个真实 Provider replay，覆盖 Python/TypeScript/Java、2 个 cross-fork、历史 review line 丢失、unresolved thread、removed target 和 ambiguous mapping。gold label 由 GitHub diff hunk 与完整 immutable head 文件独立复核，不复制 Provider 预测。
   - **第三小批已完成本地录制与独立标注**：新增 Pydantic #13275、JUnit 5 #5295、pytest #13987，覆盖 2 个普通 PR、1 个 cross-fork、Rust outdated review target、resolved 非代码 review，以及 lint/build/test-matrix 失败。三案共保留 35 个具名失败 job；失败步骤与改动测试之间没有可证实关联，gold `ci_test_paths` 均为空，用作“不得臆造测试关联”的真实负控。Pydantic Rust review 独立定位到 `ModelFieldsValidator.validate_json_by_iteration`，当前符号解析不支持 Rust，因此作为明确 false-negative 记录。
   - 真实 replay 暴露并修复两项取证缺口：cross-fork 来源仓库返回 0 checks 时现在继续回退基仓库；压缩录制器现在保存实际 `job + failed_steps`，不再错误读取不存在的 `check` 字段。两项均有回归测试。
   - 当前 corpus 为 7 仓库/8 case，其中 6 个 Provider replay 全部 partial；整体 partial rate 0.75、平均 8.75 次请求/126.6 秒。聚合 symbol mapping precision 0.25 / recall 0.1429 / F1 0.1819；CI micro F1 虽为 1.0，但真实新增案例都是负控，尚不能证明失败测试正例的关联质量。
   - 当前结果仍只作为失败基线：已达到仓库数下限，但仍缺 16–22 个 case，以及 rename/delete、Provider 截断、缓存复放和失败测试正例；达到 24–30 case 前不设置不可回退阈值，也不进入 RAG-K1。
2. **G10-C3b Provider 证据补齐**：release、artifact metadata/按需下载，以及按 run attempt -> job -> step -> 时间窗口读取日志；所有新结果继续携带 repository、commit SHA、provider status 和 stop reason。
3. **G10-D0 只读 RepositoryWorkspaceRun**：受控临时目录、immutable checkout、Docker sandbox 优先、显式不安全的 process fallback、取消/恢复/过期清理和资源预算；只允许 list/read/search/diff。
4. **G10-D1 确定性命令执行**：仓库配置映射为结构化 `CommandSpec`，只开放声明过的 test/lint/build；保存 stdout/stderr、exit code、timeout、耗时和 artifact，不接受模型拼接任意 shell。
5. **G10-D2 可写 worktree**：独立 worktree、写前基线、写后 diff/回归、一键回滚，禁止直接修改主 checkout；完成前不开放私有仓库自动执行。

### 2026-07-17 开源对照审计：RAG / 知识学习

对照 [RAGFlow](https://github.com/infiniflow/ragflow)、[Khoj](https://github.com/khoj-ai/khoj)、[AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) 和 [Open WebUI](https://github.com/open-webui/open-webui) 后，当前实现不是“缺 RAG”，而是已经具备可信运行骨架、尚未形成可信质量闭环。

#### 已有能力与差距

1. **索引一致性是现有强项**：server-owned RagRun、稳定 document/revision ID、staging/active version、CAS 写租约、vector stage 失败不激活、append 替换旧 revision、删除与 Chroma stale 清理已经落地；不应重做旧路线图中的这些项目。
2. **检索链路已过 MVP**：已有 BM25、local/backend vector、RRF hybrid、metadata filter、单来源 chunk 上限、重复文本抑制、可选 reranker、分阶段耗时和 score breakdown。短期不应以“再接一个 vector DB”作为质量工作替代品。
3. **评测规模不足**：当前 checked-in corpus 只有 6 条干净查询，且预期全部命中；没有长文档、噪声 PDF/DOCX、中英混合、同名主题、多来源拼接、矛盾/过期资料、不可回答问题和 stale revision case，也没有 production embedding 的可选 replay。
4. **只评检索，不评最终回答**：现有指标覆盖 source hit、Recall@K、MRR、nDCG 和 empty rate，但没有 citation precision/recall、引用片段是否支持具体 claim、groundedness、answerability/refusal、遗漏关键来源和旧 revision 泄漏。
5. **摄取仍是纯文本级**：DOCX 只读 paragraph，PDF 依赖 pypdf 文本抽取并以页标记拼接；切块主要按空行和字符预算，未保留 heading/table/list/page block 等结构。RAGFlow 的结构化文档理解、模板化切块和 chunk 可视化说明，应先提升“输入质量”，再考虑 GraphRAG。
6. **切块缺少产品化可见性**：没有 parser/chunker profile、最小 chunk 合并策略、chunk preview、解析警告与人工排除。Open WebUI 对过小 chunk 合并、完整文档与聚焦检索的分离说明，这些能力比继续增加固定 `max_chars` 参数更有产品价值。
7. **知识作用域仍偏单索引**：已有 metadata filter 和文档列表，但缺显式 collection/workspace scope、active revision、按学习目标选择知识集合，以及“完整文档 / focused retrieval / tools-only”策略。AnythingLLM 的 workspace/thread 文档作用域与整文上下文回退、Khoj 的自定义知识代理提供了可参考的产品边界。
8. **摄取运行缺少逐文档恢复体验**：请求内有 RagRun 和 stage，但上传仍是同步完成后返回；缺逐文档 queue/status、失败单项重试、跨页面继续观察与后台恢复。AnythingLLM 的逐文档 embedding 进度和可离开页面队列是更成熟的交互基线。
9. **学习产品的差异化仍成立**：`RetrievalQueryPlan` 已能结合 objective、gap 和 pedagogy protocol 构造私有检索 query，回答上下文也保留引用；下一步应把检索证据用于“验证理解和暴露缺口”，而不是复制通用知识库聊天界面。

#### RAG 推荐门禁与顺序

1. **RAG-K1 真实学习语料质量基线，作为 PR #45 后的核心产品第一优先级**：至少 12 份真实文档、30–40 个查询，覆盖 Markdown/PDF/DOCX、中英混合、长文、重复/矛盾/过时版本、多来源问题和不可回答问题。保留 deterministic local 子集，并提供显式联网/付费的 production embedding replay。
2. **RAG-K1 同时补回答级评测**：除 Recall/MRR/nDCG 外，新增 citation precision/recall、claim support、groundedness、answerability/refusal、source diversity、stale revision leakage、端到端延迟和 embedding/rerank 成本；第一轮只记录基线，之后才设置不可回退门禁。
3. **RAG-K2 结构化摄取与切块**：引入 `ParserResult -> DocumentBlock -> Chunk`，保留 page/heading/paragraph/table/list identity、parser/chunker version 和 warnings；提供 Markdown heading、prose、PDF page/layout 等策略 profile、最小 chunk 合并与 chunk preview。扫描件/OCR 和多模态解析作为可选 adapter，失败必须显式降级，不能伪装为完整解析。
4. **RAG-K3 KnowledgeBase domain**：增加 collection/scope、active revision、逐文档状态与重试、索引 manifest/磁盘统计；明确 `full_document / focused_retrieval / tools_only` 三种上下文策略，并由 TaskContract、文档长度、模型 context budget 与用户选择共同决定。
5. **RAG-K4 教学可信闭环**：把 citation validation、已掌握点/当前缺口、证据披露级别和 follow-up query rewrite 接入 PedagogyTurnPlan；验证“不知道”等弱输入、跨轮指代和多跳学习问题是否检索到正确证据且不过度泄露答案。
6. **RAG-K5 增量同步与外部连接器后置**：先完成本地文件 refresh/watch、content hash 去重和删除传播，再考虑 Notion/Drive/网页同步。GraphRAG、重型分布式检索、全量 OCR/多模态和更多 vector DB 均后置，除非 K1 评测证明它们解决了真实失败。

### 统一下一阶段顺序

1. **已完成**：PR #45、PR #46 与 PR #47 已合并；G10-C3a 基础 harness、curated seed 隔离及前两批真实跨语言 Provider replay 已落地。
2. **本切片推进**：当前本地 7 仓库/8 case；继续以小批次补真实多仓库 Provider replay，达到 24–30 case 前只记录基线、不宣称代表性质量。
3. G10-C3a 达到最低 corpus 覆盖后，回到核心学习产品，连续完成 RAG-K1 retrieval + answer faithfulness 基线和 RAG-K2 结构化摄取。
4. 根据 K1 数据决定是否先做 RAG-K3，或补 G10-C3b release/artifact/日志定位。
5. 只有上述只读质量门禁稳定后，才进入 G10-D0；G10-D2 可写代理、私有仓库自动执行、GraphRAG 和重型连接器继续后置。

## 5. 当前验证

核心学习产品最近完整门禁：

- PR #37（G2）：最新 head 完整 pytest、Ruff、package helper、detect-secrets、expanded mypy、frontend Vitest、TypeScript build、Vite production build 全部通过后合并。
- PR #38（G3）：最新 head CI Run #915 完整通过后合并。
- PR #39（G4）：最新 head `9896272b678723677aabba6f9d1b523d244e5c17`，CI Run #947 完整通过后合并；前端 139 个测试、TypeScript build 和 Vite production build 均通过。
- PR #40（G5）：已合并，可信四态与 committed/attempted 边界进入主线。
- PR #41（G6）：最终 head `f04dc4c16cf8a936d4871e45b027bdff7de4af78`，CI Run #994 完整通过后合并；pytest、Ruff、package helper、detect-secrets、expanded mypy、153 个前端测试、TypeScript build 和 Vite production build 全部通过。
- PR #42（G7）：最终 head `eb61f0cbd27ee9fe51a65fadabf358470f43d094`，CI Run #1015 完整通过后合并；pytest、Ruff、package helper、detect-secrets、expanded mypy、159 个前端测试、TypeScript build 和 Vite production build 全部通过。
- PR #43（G8）：最终 head `f78b9b1` 的两条 CI 均通过后合并，merge commit `6e1d107`；本地 1440 / 760 / 430 px 浏览器验收覆盖 More 菜单、设置抽屉、滚动锁、关闭后焦点恢复与知识库开发代理。
- PR #44（聊天 ResearchRun owner）：目标测试 17 passed，完整 pytest 756 passed，Ruff 全量通过，前端 47 个测试文件 / 164 个测试及 TypeScript/Vite build 通过；head `256dac4` 的 push 与 pull_request CI 均通过。
- 当前请求级取消/超时工作树：Chat/API/Policy/Persistent/WebTool 相关后端 68 passed，Ruff 全量通过，前端 47 个测试文件 / 165 个测试通过，TypeScript 与 Vite production build 通过；完整 pytest 在本地 10 分钟门限内未结束，因此尚未记为全量通过。
- 当前失败恢复入口工作树：前端 48 个测试文件 / 167 个测试通过，TypeScript 与 Vite production build 通过；failed/cancelled chat-owned ResearchRun、停止前 Run 创建竞态和独立 standalone run 隔离均有回归覆盖。
- 当前实时阶段事件工作树：ResearchRun/Chat/API 相关后端 67 passed，Ruff 增量通过；前端 48 个测试文件 / 169 个测试通过，TypeScript 与 Vite production build 通过；准备阶段正式 `run_id` 事件早于 session 事件、终态完整 Run 刷新和实时进度卡均有回归覆盖。
- 当前恢复回答闭环工作树：Chat/API/Policy/ResearchRun 相关后端 63 passed，Ruff 增量通过；前端 49 个测试文件 / 172 个测试通过，TypeScript 与 Vite production build 通过；服务端 Run/source block 匹配校验、下一轮一次性消费、旧恢复卡退出、持久化 EvidenceTrail 同 Run 归属和 `/research-runs` 开发代理均有回归覆盖。
- 当前浏览器恢复路径：Playwright 验证 `/research-runs` 开发代理 200、恢复卡可见、请求携带服务端匹配的 `web_context_run_id`、回答后旧卡退出、EvidenceTrail 显示并展开“恢复研究来源”；headed 会话首次启动失败后使用无界面 Chromium 完成 DOM/请求验收。
- 当前聊天研究浏览器补充验收：真实浏览器按时间检查 planned/searching/reading/synthesizing/completed；停止生成确认 owner cancel 请求、`已停止生成` 与 cancelled 终态，失败卡确认 `重试研究` 后进入恢复态。恢复后的 Playwright daemon 再启动超时，但刷新恢复路径已有前序 DOM/请求验收和专项回归覆盖。
- 当前 G10-C2 持久化缓存切片：Provider cache schema v1 / SQLite schema v16 已落地；缓存与 migration 专项 21 passed，Ruff 增量通过；checks 只在解析到 immutable commit SHA 后跨重启复用，移动 work-item 不会直接命中持久缓存。
- 当前 G10-C2 第二切片：change-impact 每次先 compare 重解析 base/head，再按双 SHA 与完整预算复用；review-context 每次先取得 PR 证据，再按双 SHA、review/CI 证据指纹与预算复用。缓存/API/Provider 专项 32 passed，评论证据变化失效与跨重启命中均有回归。
- 当前 Provider 分页/跨 owner 切片：review thread comments 嵌套 cursor、共享预算耗尽、fork head checks 优先与 base fallback 均有回归；相关 review/provider 专项 15 passed，Ruff 增量通过。
- 当前 cross-fork change-impact 切片：PR review context 不再返回 unsupported，而是复用 commit-pinned PR comparison 生成 base/head 双仓库源码图；双仓库 snapshot 路由、repository 归属、同 SHA 不同 fork 缓存隔离与 review-context 接线均有回归。聚焦测试 11 passed，GitHub 专项 94 passed，全量 pytest 777 passed，Ruff 全量通过；expanded mypy 当前 126 个既有错误，低于 127 基线且无新增。
- 当前 G10-C3a replay harness 第一小批：PR #28/#30 的 immutable SHA 与 curated context 已进入 schema v1 manifest；CLI 两次输出字节级一致，明确报告 1 个仓库、2 个 seed、0 个 Provider replay。原有独立 golden JSON 已删除，manifest 成为唯一 label 真值；评测/replay 聚焦 7 passed，GitHub 专项 97 passed，全量 pytest 781 passed，Ruff 全量通过，新增模块目标 mypy 通过。因 C 盘空间不足，全量 pytest 的临时目录改到 D 盘后通过。
- 当前 G10-C3a 第二小批：录制器/manifest/replay/evaluation 聚焦 12 passed，GitHub 专项 97 passed，全量 pytest 786 passed，前端 49 files/172 tests 与生产构建通过，Ruff 全量与 package/secret scan 通过，新录制模块与 CLI 使用 `--follow-imports=skip` 目标 mypy 通过；真实基线为 4 仓库/5 case、3 个 Provider replay、partial rate 0.6、symbol F1 0.20。远端 CI 门禁待本分支发布后确认。
- 当前 G10-C3a 第三小批（PR #48）：新增 3 个失败 CI 真实 replay、35 个具名失败 job 负控，并补 cross-fork 空 checks 回退和录制器 job/step 完整性回归；当前基线为 7 仓库/8 case、6 个 Provider replay、partial rate 0.75、symbol F1 0.1819。聚焦回归 18 passed、GitHub 专项 99 passed、全量 pytest 788 passed，前端 49 files/172 tests 与生产构建通过，Ruff 全量、目标 mypy、package helper（893 files）和 detect-secrets 均通过；同 SHA 的 PR CI 通过，push CI 首次因 PyPI 镜像缺少 `altair==6.1.0` 失败，原 run 重试后全绿。

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
- cross-fork base/head 从各自仓库按 immutable SHA 建 snapshot，并组合 repository-aware change-impact；
- 旧 API、工具 dispatch、mypy 和前端回归保持通过。

## 6. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
