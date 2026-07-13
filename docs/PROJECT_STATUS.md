# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-13  
> 当前实现基线：`196531e1ccf9416a9a6f325dd88b91d7411bb6f5`（PR #22）

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。G10 已具备可取消、可重试、可恢复的广域 ResearchRun；GitHub 仓库快照已经持久化并支持连续追问复用；生产代码研究现已具备 path + symbol + BM25 + exact 混合搜索，以及初版 definition/reference/import 结构化证据。**

## 2. 已完成

### 基础正确性

- committed learning state 是恢复真值，只采纳 completed turn。
- 临时 research、quick answer、conversation 不推进长期学习状态。
- 新建会话不自动归档；会话切换只取消 chat scope。
- 联网支持关闭、每次询问、自动；外发上下文范围进入真实请求路径。
- 空结果、Provider 不可用和“确认不存在”严格区分。

### 广域网页研究

- 通用搜索支持 SearXNG，并可降级到 DuckDuckGo HTML。
- 模型可调用 `web_search`、`web_read`、`github_search`、`github_snapshot`、`github_structure`。
- 默认最多 5 轮工具规划，硬上限 8 轮。
- SourceAssessment 会过滤无效 URL、无来源标识和重复结果。
- 页面和源码按外部证据处理，不作为系统指令。

### 可恢复 ResearchRun

阶段：

```text
planned
-> searching
-> assessing
-> reading
-> synthesizing
-> completed | partial | failed | cancelled
```

- 先创建 Run，再访问外部 Provider。
- 每个查询变体和来源读取后写 checkpoint。
- 保存查询尝试、采用/拒绝来源、读取结果、预算、错误和停止原因。
- `retry` 可从失败状态重新搜索。
- `resume` 根据 candidate、assessment 和 read 状态选择恢复点。
- 已成功读取的来源不会重复读取。
- operation ownership + version CAS 阻止旧请求覆盖新结果。
- API：create / search / retry / resume / cancel / get / list。
- 前端显示 planned/searching/assessing/reading/synthesizing，并提供停止、重试和继续。
- 兼容 `/research-runs` 和旧 one-shot API。
- 搜索词变化时创建新 Run；不会拿旧主题的 Run 重试。

状态语义已经分层：

- `status=completed` 表示研究流程已正常完成；
- `provider_status=partial` 表示结果可用，但部分来源读取失败；
- 历史 Provider 失败保留在 query attempts 中，不会永久降级后续成功重试。

当前取消属于协作式取消：在查询、来源读取和阶段提交之间生效。正在等待响应的同步请求需要在返回或超时后才能进入取消分支，但不会再提交 completed 结果。

### GitHub 仓库和源码

支持仓库根目录、README、tree、blob、raw URL 和 Contents API URL。用户直接粘贴 GitHub URL 时会直接读取。GitHub code search 不可用时会降级到 tree/path 或 bounded snapshot。

### 持久化 GitHubRepoSnapshot

- 使用独立 `GitHubSnapshotRepository/Service`，底层复用版本化 `rag_runs`，kind 为 `github_repo_snapshot`。
- 保存 repo、ref、tree SHA、file SHA、路径、源码、失败和预算。
- exact query 在 TTL 内直接复用。
- 后续问题先在上一份快照中筛选相关文件；不足时再刷新。
- 服务重启后可从 SQLite 恢复并重建代码索引。
- API：create / list / get。

默认缓存和预算：

```env
GITHUB_SNAPSHOT_CACHE_TTL_SECONDS=1800
GITHUB_SNAPSHOT_FOLLOWUP_MAX_FILES=12
GITHUB_SNAPSHOT_MAX_FILES=24
GITHUB_SNAPSHOT_MAX_FILE_CHARS=12000
GITHUB_SNAPSHOT_MAX_TOTAL_CHARS=120000
```

### 本地代码混合索引

初版 `GitHubCodeIndex` 已实现：

- 文件路径匹配；
- 常见代码声明的符号提取；
- snake_case 和 CamelCase 拆词；
- BM25 风格词法检索；
- 精确短语加权；
- 文件、SHA、URL、语言、symbol、行区间和 score breakdown。

生产 `github_search` 优先查询持久化快照的本地混合索引；无本地命中时再使用远端搜索和 tree fallback。

### 结构化代码证据

初版 `RepositoryStructureIndex` 已实现：

- 统一 `EvidenceRef`：repository、ref、tree SHA、file SHA、path、symbol、start/end line、kind；
- Python 使用标准库 AST 提取 class、function、method、import/from import；
- JavaScript / TypeScript 使用保守声明、import/export/require fallback；
- 解析常见 Python 与 JS/TS 相对导入，并关联到快照内目标文件；
- definition 查询；
- reference 文本定位；
- related files 扩展；
- parse error、语言、符号数、import 数和解析统计；
- 本地混合搜索结果附带 EvidenceRef、重叠 definition 和 import；
- API：`POST /github-repo-structure`；
- 模型工具：`github_structure`。

该合同是 parser-agnostic 的；后续 tree-sitter / LSP 可替换底层解析，不改变 API 消费方。

### PR #21 接入结果

PR #21 不整体合并，因为其旧分支会覆盖当前来源评估、正文读取、快照持久化和混合索引。已选择性接入：

- `/research-runs` 兼容路由；
- create-before-search；
- retry/resume/cancel；
- 同查询才能复用旧 Run；
- 服务端取消；
- 前端阶段展示；
- 组合边界测试。

PR #21 保持关闭且未合并，当前实现以 PR #22 / main 增强版为准。

## 3. 还差什么

| 能力 | 状态 | 主要缺口 |
|---|---|---|
| 广域网页搜索 | 基础完成 | 聊天工具循环尚未整体关联一个 durable ResearchRun |
| cancel/retry/resume | 基础完成 | 异步请求级取消、统一超时和实时阶段事件 |
| 网页读取 | 基础完成 | PDF、动态页面和需要会话状态的页面 |
| GitHub repo/tree/blob/raw | 基础完成 | branch 名歧义、submodule、LFS、超大文件 |
| 持久化仓库快照 | 基础完成 | manifest 增量刷新、过期清理和磁盘统计 |
| 本地代码搜索 | 初版完成 | embedding 检索、结果融合和评测集 |
| 定义与引用 | 初版完成 | tree-sitter / LSP、语义引用、调用图、继承图 |
| import/export 图 | 初版完成 | package/tsconfig/alias 解析和跨语言依赖 |
| Git 历史对象 | 未完成 | branch/tag/commit/compare/diff/blame |
| PR/issue/CI | 未完成 | changed files、patch、review、workflow logs |
| 本地 checkout | 未完成 | clone/fetch/checkout 和工作树隔离 |
| 测试与构建 | 未完成 | 受控运行环境、命令预算、日志和回滚 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要和仅本地模式 |

## 4. 下一代码顺序

### G10-C1.1：结构化代码理解增强

1. tree-sitter 解析 Python、TypeScript/JavaScript，替换正则 fallback。
2. definition/reference 语义消歧。
3. function/method call graph、class inheritance、import/export graph。
4. 自动扩展入口文件、实现文件、调用方和测试文件。
5. package.json、tsconfig paths、Python package root 的模块解析。
6. 建立小型代码检索与调用链评测集。

### G10-C2：GitHub 工作对象

1. branch/tag/commit 固定 ref。
2. compare、diff、blame。
3. PR、changed files、patch、review comments、CI。
4. issue、release、docs 联合研究。

### G10-D：可执行仓库代理

1. 受控临时目录 checkout。
2. 只读运行环境和命令白名单。
3. 运行测试、lint、build。
4. 可写工作树、diff、回归和回滚。
5. 增量更新、缓存清理和磁盘预算。

这些能力应进入独立 `RepositoryResearchService / RepositoryRun / SandboxRun`，复用现有证据、预算、取消和恢复协议。

## 5. 当前验证

PR #22 的 GitHub Actions CI 已验证：

- pytest：638 passed；
- Ruff：passed；
- package helper：passed；
- detect-secrets：passed；
- expanded mypy：passed；
- frontend Vitest：34 files / 115 tests passed；
- TypeScript project build：passed；
- Vite production build：passed。

新增回归覆盖：

- Run 先持久化后搜索；
- Provider 失败后跨 repository restart 重试；
- 读取中取消并保留 checkpoint；
- resume 不重复搜索和已成功读取来源；
- stale operation 不能写回；
- 部分来源失败与流程完成状态分离；
- 历史 Provider 失败不污染成功重试；
- PR #21 前端组合边界；
- 快照 exact cache、follow-up subset、force refresh 和重启恢复；
- path/symbol/BM25/exact 排序；
- Python AST class/function/method/import；
- JS/TS 声明与 import/export/require；
- Python 与 JS/TS 相对导入解析；
- definition/reference/related files；
- EvidenceRef 的 path/ref/tree SHA/file SHA/行区间；
- API 与模型 `github_structure` 工具分发；
- 生产 gateway 使用持久化结构索引。

CI 现会在失败时上传 `pytest-log` 和 `frontend-log` artifacts，避免只能看到 Actions 日志开头而无法定位尾部断言。

## 6. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
