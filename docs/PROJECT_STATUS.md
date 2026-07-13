# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-13  
> 当前主线：`b9504efd0b6cd4599406cb4ac63a21d00cb2b54d`（PR #26 已合并）  
> 当前开发：PR #27，G10-C2.2 PR / issue / CI 联合研究

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。G10 已具备可恢复的广域 ResearchRun、commit-pinned GitHub 快照、混合代码搜索、四语言 Tree-sitter 图、模块/re-export/overload 语义、影响分析、Git 历史对象，以及初版 PR、issue、checks、workflow jobs 和脱敏 CI 日志研究。**

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
- tree 与 blob 均按 immutable commit SHA 读取。
- 源码 URL 固定到 commit SHA，不使用可移动 branch URL。
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

### 本地代码搜索、结构理解与影响分析

- path / symbol / snake_case / CamelCase。
- BM25 风格词法检索和 exact phrase。
- SHA、URL、语言、行区间和 score breakdown。
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

`EvidenceRef` 包含：

- repository；
- requested ref；
- resolved commit SHA；
- tree SHA；
- path / file SHA；
- symbol / kind；
- start/end line。

`SymbolIdentity` 进一步加入 language、kind、qualified name、signature 和稳定 ID。相同 commit/tree snapshot 内身份稳定；版本变化时身份变化。

### 模块、re-export、overload 与 LSP 边界

已合并 PR #25：

- `ModuleIdentity`；
- TypeScript/JavaScript barrel 与 `export ... from`；
- Python package root、绝对导入和 `__init__.py` re-export；
- Java package + class identity；
- 显式 import/re-export 链优先于全局同名猜测；
- 无上下文的同名符号保持 ambiguous；
- `OverloadGroup`；
- 模块限定查询和参数数量消歧；
- `LspAdapter` / `NullLspAdapter` / callback adapter；
- 请求路径不会自行启动语言服务器或 shell 子进程；
- deterministic golden set：resolution、impact 和 test mapping 指标。

### Git ref、commit、compare、diff 与 blame

已合并 PR #26：

- 默认 branch、branch、tag、annotated tag、完整 SHA 和短 SHA；
- `resolved / ambiguous / not_found / unavailable`；
- branch 与 tag 同名但指向不同 commit 时返回 ambiguous；
- annotated tag 有界 peel；
- resolved type/name、aliases、commit SHA、tree SHA；
- commit message、parents、author、committer、stats 和 verification；
- compare 前分别解析 base/head 到 commit SHA；
- ahead/behind、merge base、bounded commit 列表；
- changed files、previous filename、bounded patch 和 unified diff hunks；
- GraphQL blame 行区间裁剪；
- 无 GitHub Token 时明确返回 `github_blame_requires_token`。

模型工具/API：

- `github_ref` / `POST /github-ref`
- `github_commit` / `POST /github-commit`
- `github_compare` / `POST /github-compare`
- `github_blame` / `POST /github-blame`

```env
GITHUB_HISTORY_CACHE_TTL_SECONDS=300
GITHUB_COMPARE_MAX_FILES=100
GITHUB_COMPARE_MAX_PATCH_CHARS=120000
GITHUB_BLAME_MAX_LINES=500
```

### Pull request 联合研究

PR #27 已实现：

- PR title、body、state、draft、mergeability、labels 和 reviewer；
- base/head ref、repository 和 immutable commit SHA；
- base/head commit metadata；
- changed files、rename、additions/deletions、bounded patch 和 diff hunks；
- review submissions；
- inline review comments 与普通 issue comments；
- Token 可用时读取 GraphQL review threads；
- 保留 thread 的 resolved、outdated、path、line 和 comment；
- 可选联接 head commit 的 checks、workflow runs、jobs 和 steps；
- 任一非核心 Provider 失败时保留主体结果并返回 `provider_status=partial`。

模型工具/API：

- `github_pr`
- `POST /github-pr`

### Issue 联合研究

- issue / pull-request-shaped issue 类型区分；
- title、body、state、state reason、labels、assignees 和 milestone；
- bounded comments；
- bounded timeline events；
- referenced commit、rename 和 label 事件；
- 聚合 `linked_commit_shas`，不根据文本猜测关联关系。

模型工具/API：

- `github_issue`
- `POST /github-issue`

### Checks、workflow jobs 与 CI 日志

- 先将 branch/tag 固定到 immutable commit SHA；
- check-runs、GitHub App、output summary 和 annotation count；
- workflow runs、event、attempt、head branch/head SHA；
- jobs、runner、labels、step status 和 conclusion；
- 多来源不可用与“没有结果”分开表达；
- CI 日志只接受具体 job ID；
- 只返回有界日志尾部；
- 去除 ANSI 控制序列；
- 对 Bearer/token、GitHub token、OpenAI 风格 key、常见 secret 赋值和 `add-mask` 做脱敏；
- 日志始终作为不可信外部证据，不作为指令。

模型工具/API：

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

### CI 诊断改进

- pytest 失败时上传 `pytest-log`；
- 前端失败时上传 `frontend-log`；
- detect-secrets 使用 `continue-on-error -> 上传报告 -> enforce`；
- secrets 报告以 `detect-secrets-report.json` 保存，避免隐藏文件被 artifact 上传忽略；
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
| 影响范围分析 | 初版完成 | diff hunk 到 SymbolIdentity、数据流、配置影响、风险分层 |
| Git ref/commit/compare | 基础完成 | 多页 commit/files、超大 compare、持久化缓存 |
| blame | 基础完成 | Token 授权体验、超大文件和 Provider 替代方案 |
| PR / review | 初版完成 | 全分页、cross-fork 细节、review pagination、持久化缓存 |
| issue | 初版完成 | release、linked PR、全 timeline、项目字段 |
| checks / jobs / logs | 初版完成 | artifacts、rerun attempt、超大日志分段、持久化缓存 |
| 版本变化结构影响 | 未完成 | hunk -> old/new SymbolIdentity、变更符号和测试缺口 |
| 本地 checkout | 未完成 | clone/fetch/checkout 和 worktree 隔离 |
| 测试与构建 | 未完成 | 受控环境、命令预算、日志和回滚 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要、仅本地模式 |

## 4. 下一代码顺序

### G10-C2.3：版本变化的结构影响

1. 将 compare/PR hunk 映射到旧 commit 和新 commit 的源码行区间。
2. 解析两侧快照，生成 old/new `SymbolIdentity`。
3. 输出 added / removed / modified / moved symbols。
4. 对变更符号执行 bounded impact slice。
5. 聚合相关测试、缺失测试和不确定性。
6. 生成 source-backed PR review context，不自动判定代码正确。
7. 模型工具：`github_change_impact`。

### G10-C2.2 后续补齐

1. REST/GraphQL 多页游标和全局总预算。
2. release、artifact metadata 和按需下载。
3. cross-fork PR 的 head repository/ref 解析。
4. work-item/checks/logs 持久化缓存与过期清理。
5. 日志按时间/步骤定位，而不只读取有界尾部。

### G10-D：可执行仓库代理

1. 受控临时目录 checkout。
2. 只读环境和命令白名单。
3. 运行 test、lint、build。
4. 可写 worktree、diff、回归和回滚。
5. 增量更新、缓存清理和磁盘预算。

## 5. 当前验证

PR #27 GitHub Actions CI #618，代码 head `f92fbd17731472974dc25ee61b4835b96c75b49c`：

- pytest：679 passed；
- Ruff：passed；
- package helper：passed；
- detect-secrets：passed；
- detect-secrets report artifact：passed；
- expanded mypy：passed；
- frontend Vitest：passed；
- TypeScript project build：passed；
- Vite production build：passed。

新增回归覆盖：

- PR base/head commit identity、files、patch、hunks 和预算；
- review submission、inline comment、普通 comment 和 unresolved thread；
- issue comments、events 和 linked commit SHA；
- checks/workflow runs/jobs/steps 聚合；
- 两个 Provider 同时失败时的 unavailable 语义；
- CI 日志最小窗口、尾部裁剪、ANSI 清理和凭据脱敏；
- FastAPI 预算传递和 404 状态映射；
- persistent gateway 与四个模型工具；
- ResearchRun、快照、Git 历史、Tree-sitter、模块语义和影响分析不退化。

CI 失败时上传 `pytest-log`、`frontend-log` 和 `detect-secrets-report` artifacts。

## 6. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
