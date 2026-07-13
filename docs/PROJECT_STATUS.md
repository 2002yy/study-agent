# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-13  
> 当前主线：`3b73554fe2ef65d0c71cd0d73884e1f5ffb4adf6`（PR #25 已合并）  
> 当前开发：PR #26，G10-C2.1 固定版本与 Git 历史对象

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。G10 已具备可恢复的广域 ResearchRun、持久化 GitHub 快照、混合代码搜索、四语言 Tree-sitter 图、模块/re-export/overload 语义、影响分析，以及 commit-pinned 的 ref、commit、compare、diff 和 blame 研究。**

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

### 持久化 GitHubRepoSnapshot

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

### 本地代码搜索与结构理解

- path / symbol / snake_case / CamelCase。
- BM25 风格词法检索和 exact phrase。
- SHA、URL、语言、行区间和 score breakdown。
- Python、JavaScript、TypeScript/TSX、Java 固定 Tree-sitter grammar。
- definitions / imports / calls / constructors / inheritance。
- callers / callees / hierarchy / implementations / related files。
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

### Git ref 与 commit identity

PR #26 已实现：

- 默认 branch、branch、tag、annotated tag、完整 SHA 和短 SHA；
- `resolved / ambiguous / not_found / unavailable`；
- branch 与 tag 同名但指向不同 commit 时返回 ambiguous；
- annotated tag 有界 peel；
- resolved type/name、aliases、commit SHA、tree SHA；
- commit message、parents、author、committer、stats 和 URL；
- signature verification 状态与原因；
- commit 文件和 bounded patch。

模型工具/API：

- `github_ref` / `POST /github-ref`
- `github_commit` / `POST /github-commit`

### Compare、diff 与 blame

- compare 前分别解析 base/head 到 commit SHA；
- ahead/behind、merge base、bounded commit 列表；
- changed files、status、additions/deletions、previous filename；
- 总文件数和总 patch 字符预算；
- patch truncation 明确可见；
- unified diff hunk 映射 old/new line range；
- GraphQL blame 行区间裁剪；
- blame EvidenceRef 固定 queried commit SHA；
- 无 GitHub Token 时返回 `github_blame_requires_token`，不伪造结果。

模型工具/API：

- `github_compare` / `POST /github-compare`
- `github_blame` / `POST /github-blame`

```env
GITHUB_HISTORY_CACHE_TTL_SECONDS=300
GITHUB_COMPARE_MAX_FILES=100
GITHUB_COMPARE_MAX_PATCH_CHARS=120000
GITHUB_BLAME_MAX_LINES=500
```

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
| Git ref/commit/compare | 基础完成 | 分页、超大 compare、commit 缓存持久化 |
| blame | 基础完成 | Token 授权体验、分页/超大文件、Provider 替代方案 |
| PR/issue/CI | 未完成 | metadata、review threads、checks、jobs、logs、artifacts |
| 本地 checkout | 未完成 | clone/fetch/checkout 和 worktree 隔离 |
| 测试与构建 | 未完成 | 受控环境、命令预算、日志和回滚 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要、仅本地模式 |

## 4. 下一代码顺序

### G10-C2.2：PR / issue / CI 联合研究

1. PR metadata、base/head resolved commit 和 changed files。
2. patch/hunk 与 SymbolIdentity、impact files 和 test mapping 结合。
3. review submissions、inline threads、resolved/unresolved 状态。
4. issue、release、关联 PR/commit/docs。
5. checks、workflow runs、job steps、失败日志和 artifacts。
6. 有界日志读取、脱敏、缓存和 Provider failure semantics。
7. 模型工具：`github_pr`、`github_issue`、`github_checks`、`github_ci_logs`。

### G10-C2.3：版本变化的结构影响

1. 将 compare hunk 映射到旧/新 SymbolIdentity。
2. 输出 added / removed / modified / moved symbols。
3. 对变更符号执行 bounded impact slice。
4. 汇总相关测试与缺失测试。
5. 生成 source-backed PR review context，不自动判定代码正确。

### G10-D：可执行仓库代理

1. 受控临时目录 checkout。
2. 只读环境和命令白名单。
3. 运行 test、lint、build。
4. 可写 worktree、diff、回归和回滚。
5. 增量更新、缓存清理和磁盘预算。

## 5. 当前验证

PR #26 GitHub Actions CI #596：

- pytest：671 passed；
- Ruff：passed；
- package helper：passed；
- detect-secrets：passed；
- expanded mypy：passed；
- frontend Vitest：passed；
- TypeScript project build：passed；
- Vite production build：passed。

新增回归覆盖：

- default branch 固定 commit；
- branch/tag 同名歧义；
- annotated tag peel；
- commit metadata 和 verification；
- compare 文件/patch 预算与 diff hunks；
- 无 Token blame 与 GraphQL blame 裁剪；
- commit-pinned snapshot、URL、缓存和嵌套 EvidenceRef；
- FastAPI 状态码语义；
- persistent gateway 与四个模型工具；
- ResearchRun、快照、混合检索、Tree-sitter、模块语义和影响分析不退化。

CI 失败时上传 `pytest-log` 和 `frontend-log` artifacts。

## 6. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
