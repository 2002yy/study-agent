# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-14  
> 当前已合并能力基线：PR #28，G10-C2.3 版本变化的结构影响  
> 当前稳定化：状态真值、mypy 硬门禁、ask 模式显式联网同意；下一功能切片为 G10-C2.4

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。G10 已具备可恢复 ResearchRun、commit-pinned GitHub 快照、四语言结构图、模块/re-export/overload 语义、单符号影响分析、Git 历史对象、PR/issue/CI 联合研究，以及初版跨版本 hunk-to-symbol 影响分析。**

## 2. 已完成

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
6. 输出：
   - `added`：只存在于新版本；
   - `removed`：只存在于旧版本；
   - `modified`：同路径唯一配对且 hunk 相交；
   - `moved`：唯一配对但路径变化；
   - `ambiguous`：任一侧存在多个候选，不猜。
7. 比较 signature，单独返回 `signature_changed`。
8. removed symbol 在旧图执行 impact；added/modified/moved 在新图执行 impact。
9. 聚合 affected files、related tests 和 missing-test symbols。
10. missing-test 仅是静态映射信号，不代表测试一定缺失或无覆盖。

明确 uncertainty：

- bounded snapshot 未包含 changed file；
- patch 缺失或被截断，退化为 whole-file symbol fallback；
- old/new symbol 无法唯一配对；
- symbol budget 耗尽；
- parser/index 不可用。

存在上述情况时返回 `provider_status=partial`，不把不完整分析伪装成完整结果。

模型工具/API：

- `github_change_impact`
- `POST /github-change-impact`

```env
GITHUB_CHANGE_IMPACT_MAX_FILES=20
GITHUB_CHANGE_IMPACT_MAX_SYMBOLS=100
GITHUB_CHANGE_IMPACT_MAX_PATCH_CHARS=160000
```

### CI 与外发策略稳定化

- pytest 失败时上传 `pytest-log`；
- 前端失败时上传 `frontend-log`；
- detect-secrets 使用 `continue-on-error -> 上传 JSON 报告 -> enforce`；
- expanded mypy 不再允许软失败，类型错误会阻止合并；
- `web_policy=ask` 只接受显式 `web_consent` 或内部一次性 consent marker；普通 `web_context` 文本不会隐式授权联网；
- 报告文件使用普通可见路径，避免 artifact 忽略隐藏文件；
- 失败报告保留 7 天。

## 3. 还差什么

| 能力 | 状态 | 主要缺口 |
|---|---|---|
| 广域网页搜索 | 基础完成 | 聊天工具循环整体关联 durable ResearchRun |
| cancel/retry/resume | 基础完成 | 异步请求级取消、统一超时、实时阶段事件 |
| 网页读取 | 基础完成 | PDF、动态页面、登录状态页面 |
| GitHub repo/tree/blob/raw | 基础完成 | submodule、LFS、超大文件 |
| 持久化仓库快照 | 基础完成 | manifest 增量刷新、过期清理、磁盘统计 |
| 本地代码搜索 | 初版完成 | embedding 融合与真实仓库评测集 |
| Tree-sitter / 模块语义 | 初版完成 | 更多语言、package-manager exports、动态派发 |
| LSP | 适配边界完成 | 实际服务器生命周期、workspace trust、超时和缓存 |
| 单符号影响 | 初版完成 | 数据流、配置影响、风险分层 |
| Git ref/commit/compare | 基础完成 | 多页 commit/files、超大 compare、持久化缓存 |
| blame | 基础完成 | Token 授权体验、超大文件和 Provider 替代方案 |
| PR / review | 初版完成 | 全分页、cross-fork、review pagination、持久化缓存 |
| issue | 初版完成 | release、linked PR、全 timeline、项目字段 |
| checks / jobs / logs | 初版完成 | artifacts、rerun attempt、超大日志分段、持久化缓存 |
| 跨版本结构影响 | 初版完成 | rename inference、AST edit、跨文件移动、真实仓库评测 |
| TaskContract 单一真值 | 未完成 | 当前 route、evaluation、pedagogy 仍可能重复分类，需要单次判定后全链传递 |
| PR review context | 未完成 | PR + change impact + checks/reviews 的单一证据包 |
| 本地 checkout | 未完成 | clone/fetch/checkout 和 worktree 隔离 |
| 测试与构建 | 未完成 | 受控环境、命令预算、日志和回滚 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要、仅本地模式 |

## 4. 下一代码顺序

### 稳定化后续：TaskContract 单次判定

1. 在本轮 preparation 起点只生成一次 TaskContract。
2. route、pedagogy evaluation、pedagogy plan、RAG、Web 和 closure 只消费该合同，不自行重算。
3. 增加用户显式 task override，并持久化到 route snapshot。
4. 回归覆盖 active learning、临时 research、quick answer 和显式 project execution。

### G10-C2.4：Source-backed PR review context

1. 输入 PR number，读取 immutable base/head、reviews、checks 和 jobs。
2. 以 PR base/head 调用 `github_change_impact`。
3. 将 inline review thread 映射到 file/hunk/symbol。
4. 将失败 job/step 与 changed files、tests 和 symbols 做保守关联。
5. 输出证据覆盖率、unresolved threads、affected tests 和 uncertainty。
6. 不自动给出“正确/错误” verdict；只生成可审查的 review context。
7. 增加真实仓库 golden set 与 precision/recall 指标。
8. 模型工具：`github_pr_review_context`。

### G10-C2 后续补齐

1. REST/GraphQL 多页游标和全局总预算。
2. release、artifact metadata 和按需下载。
3. cross-fork PR head repository/ref 解析。
4. work-item/checks/logs/change-impact 持久化缓存与过期清理。
5. 日志按时间/步骤定位，而不只读取有界尾部。

### G10-D：可执行仓库代理

1. 受控临时目录 checkout。
2. 只读环境和命令白名单。
3. 运行 test、lint、build。
4. 可写 worktree、diff、回归和回滚。
5. 增量更新、缓存清理和磁盘预算。

## 5. 当前验证

PR #28 最终 GitHub Actions CI #634，代码 head `68a0eefd2e0ad68b3dda43e77e12235184894a3b`，合并后主线 commit `a343a7f897db92f7f0424af8d46cf94d1559c503`：

- pytest：685 passed；
- Ruff：passed；
- package helper：passed；
- detect-secrets：passed；
- detect-secrets report artifact：passed；
- expanded mypy：passed；
- frontend Vitest：passed；
- TypeScript project build：passed；
- Vite production build：passed。

新增回归覆盖：

- hunk old/new 行区间映射；
- modified 与 added symbol 分类；
- signature change；
- old/new commit-pinned SymbolIdentity；
- 上游 affected files 和 related tests；
- missing-test signal；
- changed file 未进入 snapshot 时的 partial/uncertainty；
- API 预算传递；
- persistent gateway 上限裁剪；
- 模型工具 schema、dispatch 和 unavailable 语义；
- ResearchRun、GitHub history/work items、Tree-sitter、模块语义和单符号 impact 不退化。

本稳定化切片新增显式 ask consent 回归，并将 expanded mypy 升级为合并硬门禁；其最终 CI 结果以对应 PR 为准。

CI 失败时上传 `pytest-log`、`frontend-log` 和 `detect-secrets-report` artifacts。

## 6. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
