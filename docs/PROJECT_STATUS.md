# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-19  
> 当前产品定义：**Study Agent 是一个能够长期保持“我正在学什么、已经确认什么、还不会什么、下一步是什么”的个人学习工作台。**  
> 当前产品边界：GitHub = 学习源码时使用的高级研究工具；RAG = 围绕自己的资料学习；Web Research = 需要外部事实时获得可信证据；Memory = 学习连续性基础设施；Workflow = 高级诊断 / 开发者模式。  
> 当前能力基线：PR #52–#54 已完成产品边界、上传到学习交接与 Golden Journey；PR #55–#58 已按 K1a→K1d 顺序完成真实困难语料基线、过时证据资格、证据充分性/拒答和非回退多来源覆盖。PR #59 正在实现 K1e real-provider answer replay harness，但**真实 Provider benchmark 尚未实际完成**。  
> 当前代码切片：**先完成并验证 K1e harness，再通过真实 Provider 调用取得可追溯回答质量结果；在没有真实 replay 证据前不把 K1 宣布为完全完成，也不提前切入 K2。之后才进入结构化摄取与切块。GitHub / G10 继续只按“是否帮助源码学习”做质量工作，不作为第二产品扩张。**

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 0. 产品方向与能力层级

所有新增能力都必须先回答一个问题：

> **它是否帮助用户更好地继续学习？**

- **GitHub** 不是第二个产品，而是学习源码时使用的高级研究工具。仓库快照、代码结构、Git 历史、PR / CI、change impact 与 review context 都必须回到源码理解和当前学习目标。
- **RAG** 不是“知识库产品”，而是围绕自己的资料学习。普通用户首先看到上传资料、围绕资料提问和查看引用，而不是索引、向量数据库、topK 或 Provider 参数。
- **Web Research** 不是“搜索引擎”，而是在需要外部事实时提供可信证据。搜索、来源筛选、阅读和 EvidenceTrail 是学习回答的证据基础设施。
- **Memory** 不是独立工作区，而是学习连续性基础设施。用户关心的是这次确认了什么、还缺什么、下次从哪里继续。
- **Workflow** 不属于普通用户主功能，只作为高级诊断 / 开发者模式存在。普通用户只需要知道任务是否进行中、是否失败、能否继续或重试。

普通用户主路径优先保持：**当前目标 / 当前任务 -> 已确认内容 -> 未解决缺口 -> 明确下一步 -> 对话输入 -> 按需出现资料、来源与恢复动作**。低频设置、实验功能和开发者诊断不得与学习主路径争夺一级注意力。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。核心学习主链已具备单一持久化 TaskContract、LearningClosureRun、结构化证据总结、线程级 summary status、可信四态学习状态、语义化会话导航、结构化恢复卡、聚焦后的一级操作与窄屏完整可用界面；聊天联网工具循环已接入带 thread/turn owner 的 durable ResearchRun、请求级取消、正式恢复入口、准备阶段实时事件，以及恢复来源与 EvidenceTrail 的同 Run 可信归属。PR #52–#54 将普通用户界面正式收敛为“学习主链 + 按需能力”。RAG-K1a–K1d 已进一步建立 12 份固定学习资料 / 30 个 retrieval case 的困难基线、active/superseded/excluded 证据资格、supported/uncertain/insufficient 充分性边界以及非回退 adaptive multi-source coverage；K1d 合并后 raw Hybrid recall@K 为 0.923077，adaptive path 为 0.942308，multi-source recall@K 从 0.8 提升到 0.9，同时 K1c 的 26/26 answerable supported、4/4 unanswerable blocked 与 stale leakage=0 保持不回退。当前 PR #59 正在建立真实 Provider 回答 replay harness 与严格 provenance；只有实际 Provider 调用成功后才形成真实模型质量结论。G10 继续保留 commit-pinned GitHub 快照、四语言结构图、Git 历史、PR/issue/CI、跨版本 change-impact 和 source-backed review context 等能力，但产品定位固定为源码学习的高级研究工具，而不是平级产品。**

## 2. 已完成

### 核心学习产品 G1–G8 + 产品收敛

1. **G1 LearningClosureRun**：学习整理拥有 durable owner、正式状态机、source hash 幂等、retry/cancel/resume 和 MemoryRun 关联；刷新后可恢复，research 不会被错误写成学习总结。
2. **G2 结构化总结输入**：只使用 committed LearningState、最终 PedagogyEvalRun、证据引用、受预算限制的最近对话和冻结记忆上下文；失败/中断回合不能伪装成已掌握，候选保存来源、置信度和评估引用。
3. **G3 summary status**：确认写入后形成 `summarized / needs_update / not_summarized` 真值；新完成回合才重新开放整理；设置变化和失败回合不会误触发；提供“继续当前 / 归档并新建”，从不自动归档。
4. **G4 会话导航语义化**：会话列表统一展示 title、objective/research summary、recent preview、task intent、phase/gap、summary status 和 updated_at；自动标题与手动标题分离；支持搜索和按时间/状态/任务分组；旧会话兼容。
5. **G5 学习状态去伪精化**：主 UI 只读取 committed truth 与正式 PedagogyEvalRun 四态；committed/attempted 分离，非学习任务不再伪装成长期掌握进度，也不再用启发式百分比制造虚假精度。
6. **G6 结构化恢复卡**：新用户提供快速问答、系统学习、联网研究、项目推进和上传资料五类入口；返回用户按 committed task/goal、确认点或已披露来源、缺口和下一步恢复；interrupted turn 支持继续、重试和 durable abandon，放弃后刷新不会再次复活。
7. **G7 UI 聚焦收敛**：一级操作收敛到当前任务收束、上传、会话和 More；检索、来源、设置与低频工作区下沉但保持可达；普通态不再暴露 memory 文件名、run/step/session ID、route code 和低层 Provider 参数。
8. **G8 窄屏完整可用**：顶部操作、More、输入、会话与抽屉在窄屏、触控和非 hover 环境完整可达；知识库开发代理与关闭后焦点恢复已通过浏览器验收。
9. **PR #52 产品边界清理**：输入区永久 TaskIntent 下拉改为按需“自动 · 当前任务” Chip；Settings 不再渲染旧式全工作区 Sidebar；More 一级只保留“资料与来源 / 学习成果 / 设置”，群聊、新闻、工具和工作流归入实验功能 / 开发者诊断。
10. **PR #53 上传到学习交接**：普通上传固定为“添加资料”；界面展示正在解析与资料已准备好；成功后直接提供“开始系统学习 / 直接提问”；重建全部资料下沉到知识管理危险操作区。
11. **PR #54 Golden Journey 流畅度门禁**：固定首次问答、系统学习、资料学习、联网研究、GitHub 源码学习五条路径，并对必需决策数、跨越 surface 数、恢复点击数、下一步可见性和普通界面内部术语建立回归合同。

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

### RAG-K1a–K1d 回答可信度基线

1. **K1a / PR #55：困难语料与三层防漂移**。固定 12 份学习资料、30 个 retrieval case 和 answer-level gold；corpus fingerprint、checked-in snapshot 与同口径指标阻止换语料伪造提升。
2. **K1b / PR #56：过时证据资格**。文档拥有 `active / superseded / excluded` 一等状态；普通 BM25、vector、hybrid、reranker 与向量同步都只消费 active evidence，旧版本 leakage 降为 0。
3. **K1c / PR #57：证据充分性与拒答**。`supported / uncertain / insufficient` 位于 retrieval 与 answer evidence 之间；候选相似不再自动等价于可回答。当前固定 corpus 上 26/26 可回答问题放行，4/4 不可回答问题阻断。
4. **K1d / PR #58：非回退多来源覆盖**。复合问题先保留 raw top-K 的全部唯一来源，只用重复来源占据的槽位补充 facet evidence；adaptive overall recall@K 0.942308，不低于 raw Hybrid 0.923077；multi-source recall@K 0.8 -> 0.9，precision@K 0.7 -> 0.733333，stale/forbidden leakage 保持 0。
5. **K1e 当前未完成真实执行**。PR #59 Draft 正在建立复用现有 LLM Provider owner 的 answer replay harness、real/synthetic provenance、latency/usage 与 prompt/corpus fingerprint；CI 只允许 synthetic 测试验证 harness，不能冒充实际模型 benchmark。

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

当前显式 override 已收敛为按需任务 Chip；默认由系统自动判断，只有用户需要纠正当前任务时才展开选择。发送后自动清空，retry/continuation 不继承新的 override。

## 3. 还差什么

| 能力 | 状态 | 主要缺口 |
|---|---|---|
| LearningClosureRun | 已完成 | G1 durable 状态机、幂等、恢复、retry/cancel 已合并 |
| 结构化总结与 summary status | 已完成 | G2–G3 已合并，后续只需随产品验证继续收敛 |
| 会话语义导航 | 已完成 | G4 已合并，已支持标题、目标/研究摘要、阶段/缺口、状态、搜索和分组 |
| 学习状态去伪精化 | 已完成 | G5：可信四态、committed/attempted 分离、非学习结果状态已合并 |
| 结构化恢复卡 | 已完成 | G6：新老用户恢复入口、继续这里/新主题、partial/interrupted 恢复与 durable abandon 已合并 |
| UI 聚焦收敛 | 已完成 | G7 + PR #52：一级动作收敛、设置与工作区解耦、普通态内部 memory/run/route/provider 标识降噪 |
| 窄屏完整可用 | 已完成 | G8：顶部操作、More 菜单、输入、会话与各类抽屉的触控/非 hover/安全区验收已合并 |
| 上传资料学习交接 | 已完成 | PR #53：解析状态、完成后开始系统学习 / 直接提问、重建危险操作区已合并 |
| Golden Journey 流畅度门禁 | 已完成 | PR #54：五条核心路径已有决策数、surface、恢复点击、下一步与内部术语回归合同 |
| 广域网页搜索 | 基础完成 | 聊天工具循环已创建带 thread/turn owner 的 durable ResearchRun，并回写工具 trace 与 `run_id`；准备阶段通过同一 `run_id` 推送版本化阶段/失败事件，失败/取消 Run 已接入正式恢复入口；后续只按学习证据价值继续增强 |
| cancel/retry/resume | 基础完成 | 刷新恢复、进入下一轮、旧卡退出与同一 ResearchRun 的 EvidenceTrail 已通过；继续补真实使用下的长任务体验 |
| 网页读取 | 基础完成 | PDF、动态页面、登录状态页面 |
| GitHub repo/tree/blob/raw | 基础完成 | submodule、LFS、超大文件；定位固定为源码学习研究能力 |
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
| RAG 检索质量 | K1a–K1d 基线完成 | 12 documents / 30 retrieval cases；raw Hybrid recall@K 0.923077，adaptive 0.942308，multi-source 0.9，stale/forbidden leakage 0；还需扩大真实学习文档规模验证泛化 |
| RAG 文档理解 | 基础完成 | Markdown/TXT/DOCX/PDF 纯文本摄取可用；下一阶段 K2 缺标题/章节/表格/页区块等结构化解析、切块预览和扫描件/OCR 降级说明 |
| RAG 回答可信度 | K1a–K1d 完成，K1e 进行中 | 已有 answer-level citation/claim/groundedness evaluator、证据资格、拒答与多来源合同；PR #59 正在建立真实 Provider replay harness，实际 Provider benchmark 尚未完成 |
| RAG Provider replay | Harness 进行中 | synthetic CI 只能验证 schema/provenance；必须实际运行真实 Provider 并取得 completed report 后，才可把 K1e 标记完成 |
| KnowledgeBase 治理 | 初版完成 | 文档列表、稳定 document/revision identity、删除、索引版本和 active/superseded/excluded 资格已完成；仍缺 collection/scope、完整文档/聚焦检索策略和增量同步 |
| 全量 mypy 零错误 | 未完成 | 增量门禁已阻止新增，后续应按模块逐步归零 |
| TaskContract UI override | 已完成 | 按需 Chip 已接入；默认自动判断，发送后清空，retry/continuation 不继承新 Turn override |
| 本地 checkout | 未完成 | clone/fetch/checkout 和 worktree 隔离；只有证明能帮助源码学习时才进入普通产品路线 |
| 测试与构建 | 未完成 | 受控环境、命令预算、日志和回滚；保持开发者/高级源码学习能力边界 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要、仅本地模式 |

## 4. 下一代码顺序

### 核心学习产品优先

1. **已完成产品收敛 PR #52–#54**：产品边界清理、上传资料到学习的完整交接、五条 Golden Journey 流畅度回归均已进入 `main`。
2. **已完成 RAG-K1a–K1d / PR #55–#58**：困难基线与防漂移、过时证据资格、证据充分性/拒答、非回退多来源覆盖已经进入 `main`，后续修改必须继续通过同一 K1 合同。
3. **当前第一优先级：RAG-K1e real-provider answer replay**。先让 PR #59 harness 全门禁收绿并合并；随后必须在真实 Provider 配置下回放固定 answer-quality gold，记录真实模型、prompt/corpus fingerprint、latency、usage、citation/claim/groundedness 与 refusal 结果。没有实际 Provider `completed` 报告时，K1e 不算完成。
4. **第二优先级：RAG-K2 结构化摄取与切块**。只有 K1e 真实 replay 形成基线后再进入；保留 heading / page / paragraph / table / list identity、parser/chunker version、warnings 和 chunk preview，让“围绕自己的资料学习”真正可信可解释。
5. **第三优先级：根据 K1/K2 数据决定 RAG-K3 KnowledgeBase scope 或源码学习侧的 G10 质量补强**。GitHub 只在能明显改善源码理解、证据质量或学习连续性时继续推进。
6. **继续禁止横向产品扩张**：Memory 保持学习连续性基础设施；Workflow 保持开发者诊断；群聊、新闻、工具保持实验功能，不再升级为平级主产品。

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
6. 扩充真实多仓库 replay corpus，分别报告 symbol mapping 与 CI association precision/recall；只作为源码学习研究质量工作，不抢占核心学习产品优先级。

### G10-D：可执行仓库代理

1. 受控临时目录 checkout。
2. 只读环境和命令白名单。
3. 运行 test、lint、build。
4. 可写 worktree、diff、回归和回滚。
5. 增量更新、缓存清理和磁盘预算。

### 2026-07-17 开源对照审计：GitHub 仓库代理

对照 [OpenHands](https://github.com/OpenHands/OpenHands)、[SWE-agent](https://github.com/SWE-agent/SWE-agent)、[aider](https://github.com/Aider-AI/aider) 和 [Continue](https://github.com/continuedev/continue) 后，当前判断如下：
