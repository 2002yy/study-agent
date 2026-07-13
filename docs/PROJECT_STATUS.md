# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-13  
> 当前主线：`00afa47152e767022342b4e4027587ce9c0d6c47`（PR #22 已合并）  
> 当前开发：PR #23，G10-C1.2 Tree-sitter 仓库图

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。G10 已具备可取消、可重试、可恢复的广域 ResearchRun、持久化 GitHub 快照、本地混合代码检索、统一 EvidenceRef，以及 Python / JavaScript / TypeScript / Java 的 Tree-sitter 调用图与继承图。**

## 2. 已完成

### 基础正确性

- committed learning state 是恢复真值，只采纳 completed turn。
- 临时 research、quick answer、conversation 不推进长期学习状态。
- 新建会话不自动归档；会话切换只取消 chat scope。
- 联网支持关闭、每次询问、自动；外发上下文范围进入真实请求路径。
- 空结果、Provider 不可用和“确认不存在”严格区分。

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
- 每个查询变体和来源读取后写 checkpoint。
- 保存查询尝试、采用/拒绝来源、读取结果、预算、错误和停止原因。
- `retry` 可从失败状态重新搜索。
- `resume` 根据 candidate、assessment 和 read 状态选择恢复点。
- 已成功读取的来源不会重复读取。
- operation ownership + version CAS 阻止旧请求覆盖新结果。
- API：create / search / retry / resume / cancel / get / list。
- 兼容 `/research-runs` 和旧 one-shot API。
- 搜索词变化时创建新 Run，不拿旧主题 Run 重试。

状态语义已经分层：

- `status=completed` 表示研究流程已正常完成；
- `provider_status=partial` 表示结果可用，但部分来源读取失败；
- 历史 Provider 失败保留在 query attempts 中，不永久降级后续成功重试。

当前取消属于协作式取消：在查询、来源读取和阶段提交之间生效。同步 Provider 正在等待响应时，需要返回或超时后才能进入取消分支，但不会再提交 completed 结果。

### 持久化 GitHubRepoSnapshot

- 支持 repository、README、tree、blob、raw 和 Contents API URL。
- 使用独立 `GitHubSnapshotRepository/Service`，底层复用版本化 `rag_runs`。
- 保存 repo、ref、tree SHA、file SHA、路径、源码、失败和预算。
- exact query 在 TTL 内复用。
- 后续问题优先筛选已有快照文件；不足时再刷新。
- 服务重启后从 SQLite 恢复并重建索引。
- API：create / list / get。

```env
GITHUB_SNAPSHOT_CACHE_TTL_SECONDS=1800
GITHUB_SNAPSHOT_FOLLOWUP_MAX_FILES=12
GITHUB_SNAPSHOT_MAX_FILES=24
GITHUB_SNAPSHOT_MAX_FILE_CHARS=12000
GITHUB_SNAPSHOT_MAX_TOTAL_CHARS=120000
```

### 本地代码混合索引

`GitHubCodeIndex` 已实现：

- path 匹配；
- symbol 匹配；
- snake_case / CamelCase 拆词；
- BM25 风格词法检索；
- exact phrase 加权；
- 文件、SHA、URL、语言、symbol、行区间和 score breakdown。

生产 `github_search` 优先查询持久化快照的本地混合索引；无本地命中时再使用远端搜索和 tree fallback。

### 统一结构化证据

`EvidenceRef` 固定包含：

- repository；
- ref；
- tree SHA；
- path；
- file SHA；
- symbol；
- start/end line；
- kind。

API 和模型工具不依赖具体 parser，底层可以升级而不破坏消费方。

### Tree-sitter 仓库图

PR #23 已实现：

- 固定 `py-tree-sitter` 与 Python、JavaScript、TypeScript/TSX、Java grammar wheel；
- 请求期间不下载 grammar；
- Python class/function/method/import/call/inheritance；
- JavaScript / TypeScript class/function/method/interface/type/enum/import/export/require/call/constructor/inheritance；
- Java class/interface/enum/record/method/constructor/import/call/inheritance；
- 语法树含 error node 时保留可用结果并记录 parse error；
- grammar 加载失败时保留旧 Python AST / JS-TS fallback；
- Python 与 JS/TS 相对 import；
- Java dotted package import；
- `tsconfig.json` / `jsconfig.json` 的 `baseUrl` 和 `paths` alias；
- 同文件、import 目标、唯一仓库符号三级调用消歧；
- callers、callees、hierarchy、related files；
- source EvidenceRef 与 target EvidenceRef；
- call / inheritance resolution 统计；
- graph index 按 snapshot identity 缓存。

生产接入：

- 模型工具：`github_structure`；
- API：`POST /github-repo-structure`；
- 返回 definitions、references、callers、callees、hierarchy、related files、stats。

### PR #21 接入结果

PR #21 不整体合并，因为旧分支会覆盖来源评估、正文读取、快照持久化和混合索引。已选择性接入：

- `/research-runs` 兼容路由；
- create-before-search；
- retry / resume / cancel；
- 同查询才能复用旧 Run；
- 服务端取消；
- 前端阶段展示；
- 组合边界测试。

当前实现以已合并 PR #22 和 PR #23 增强版为准。

## 3. 还差什么

| 能力 | 状态 | 主要缺口 |
|---|---|---|
| 广域网页搜索 | 基础完成 | 聊天工具循环整体关联 durable ResearchRun |
| cancel/retry/resume | 基础完成 | 异步请求级取消、统一超时、实时阶段事件 |
| 网页读取 | 基础完成 | PDF、动态页面、会话状态页面 |
| GitHub repo/tree/blob/raw | 基础完成 | branch 歧义、submodule、LFS、超大文件 |
| 持久化仓库快照 | 基础完成 | manifest 增量刷新、过期清理、磁盘统计 |
| 本地代码搜索 | 初版完成 | embedding 融合与评测集 |
| Tree-sitter 定义/import | 初版完成 | 更多语言与 package-manager 解析 |
| 调用图与继承图 | 初版完成 | 类型驱动消歧、重载、动态派发、跨模块 re-export |
| reference | 基础完成 | LSP 级语义引用，排除注释和字符串误命中 |
| 影响范围分析 | 未完成 | 双向调用链、测试映射、风险分层 |
| Git 历史对象 | 未完成 | branch/tag/commit/compare/diff/blame |
| PR/issue/CI | 未完成 | changed files、patch、review、workflow logs |
| 本地 checkout | 未完成 | clone/fetch/checkout 和工作树隔离 |
| 测试与构建 | 未完成 | 受控运行环境、命令预算、日志和回滚 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要、仅本地模式 |

## 4. 下一代码顺序

### G10-C1.3：语义消歧与影响范围

1. 建立 symbol identity：module + qualified name + kind + signature。
2. 解析 TypeScript re-export、Python package root、Java package/class identity。
3. 用 import alias、receiver/type hint 和继承关系提高调用目标精度。
4. 输出向上 callers、向下 callees、实现类和相关测试的 bounded impact slice。
5. 建立小型调用链 golden set，统计 resolved / ambiguous / unresolved。

### G10-C2：GitHub 工作对象

1. branch/tag/commit 固定 ref。
2. compare、diff、blame。
3. PR、changed files、patch、review comments、CI。
4. issue、release、docs 联合研究。

### G10-D：可执行仓库代理

1. 受控临时目录 checkout。
2. 只读运行环境和命令白名单。
3. 运行 test、lint、build。
4. 可写工作树、diff、回归和回滚。
5. 增量更新、缓存清理和磁盘预算。

## 5. 当前验证

PR #23 GitHub Actions CI #534：

- pytest：642 passed；
- Ruff：passed；
- package helper：passed；
- detect-secrets：passed；
- expanded mypy：passed；
- frontend Vitest：115 passed；
- TypeScript project build：passed；
- Vite production build：passed。

新增回归覆盖：

- Python 方法调用和继承目标解析；
- TypeScript `paths` alias 与调用目标解析；
- Java 继承、构造调用和方法调用；
- caller/callee source 与 target EvidenceRef；
- graph stats 与 fallback stats；
- 持久化 gateway 的 graph 调用；
- FastAPI graph evidence 返回；
- 旧结构化索引和 ResearchRun 回归不退化。

CI 在失败时上传 `pytest-log` 和 `frontend-log` artifacts，保留尾部断言和构建错误。

## 6. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
