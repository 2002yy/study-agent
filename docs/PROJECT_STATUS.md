# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-13  
> 当前主线：`da9e9f65252a52bcb81f0bf302fa6f84a98a1fe4`（PR #23 已合并）  
> 当前开发：PR #24，G10-C1.3 语义消歧与影响范围

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。G10 已具备可取消、可重试、可恢复的广域 ResearchRun、持久化 GitHub 快照、本地混合代码检索、统一 EvidenceRef、四语言 Tree-sitter 仓库图，以及可解释的 SymbolIdentity、同名消歧、实现关系和 bounded impact slice。**

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
- 查询和来源读取后写 checkpoint。
- 保存查询尝试、采用/拒绝来源、读取结果、预算、错误和停止原因。
- 支持 retry / resume / cancel / get / list。
- operation ownership + version CAS 阻止旧请求覆盖新结果。
- 搜索词变化时创建新 Run，不拿旧主题 Run 重试。
- `status` 表示流程是否完成；`provider_status` 表示证据完整度。

当前取消属于协作式取消。同步请求正在等待响应时，需要返回或超时后才能进入取消分支，但取消后不会再提交 completed 结果。

### 持久化 GitHubRepoSnapshot

- 支持 repository、README、tree、blob、raw 和 Contents API URL。
- 保存 repo、ref、tree SHA、file SHA、路径、源码、失败和预算。
- exact query 在 TTL 内复用；后续问题优先复用已有快照。
- 服务重启后从 SQLite 恢复并重建代码、结构和语义索引。

```env
GITHUB_SNAPSHOT_CACHE_TTL_SECONDS=1800
GITHUB_SNAPSHOT_FOLLOWUP_MAX_FILES=12
GITHUB_SNAPSHOT_MAX_FILES=24
GITHUB_SNAPSHOT_MAX_FILE_CHARS=12000
GITHUB_SNAPSHOT_MAX_TOTAL_CHARS=120000
```

### 本地代码混合索引

`GitHubCodeIndex` 已实现：

- path / symbol；
- snake_case / CamelCase；
- BM25 风格词法检索；
- exact phrase；
- SHA、URL、语言、行区间和 score breakdown。

生产 `github_search` 优先查持久化快照；无本地命中时再使用远端搜索和 tree fallback。

### 统一结构化证据

`EvidenceRef` 固定包含：

- repository / ref / tree SHA；
- path / file SHA；
- symbol / kind；
- start/end line。

`SymbolIdentity` 进一步加入：

- language；
- kind；
- qualified name；
- signature；
- 由版本、文件和符号字段生成的稳定 ID。

相同 snapshot 的身份稳定；tree SHA 或文件版本变化时身份改变。

### Tree-sitter 仓库图

PR #23 已合并：

- 固定 Python、JavaScript、TypeScript/TSX、Java grammar wheel；
- 请求期间不下载 grammar；
- definitions / imports / calls / constructors / inheritance；
- Python 与 JS/TS 相对 import；
- Java dotted package import；
- `tsconfig.json` / `jsconfig.json` 的 `baseUrl` 和 `paths`；
- callers / callees / hierarchy / related files；
- source 与 target EvidenceRef；
- grammar 失败时保留旧 AST / fallback。

生产接入：

- 模型工具：`github_structure`；
- API：`POST /github-repo-structure`。

### 语义消歧与影响范围

PR #24 已实现：

- 同名符号返回 `resolved / ambiguous / unresolved`，不静默选择第一项；
- 候选评分记录可解释原因；
- 使用 exact qualified name、terminal name、same file、import path、kind、arity、receiver name 和 receiver type hint；
- 保守提取 Python/TypeScript/Java 字段、参数和构造注入类型；
- 调用边附带 target symbol ID、resolution status 和候选；
- class/interface implementation；
- method override；
- 向上 callers、向下 callees 和实现关系的 bounded BFS；
- 关联测试文件映射；
- depth / max files / max edges 预算；
- 预算触顶明确 `truncated=true`；
- 没有调用边的叶子符号仍保留自身定义文件。

生产接入：

- `github_structure` 增加 resolution、symbol identities、implementations 和 semantic stats；
- 模型工具：`github_impact`；
- API：`POST /github-repo-impact`。

### PR #21 接入结果

PR #21 未整体合并，因为旧分支会覆盖当前来源评估、正文读取、快照和索引实现。已选择性接入：

- `/research-runs` 兼容路由；
- create-before-search；
- retry / resume / cancel；
- 同查询复用规则；
- 服务端取消；
- 前端阶段展示；
- 组合边界测试。

## 3. 还差什么

| 能力 | 状态 | 主要缺口 |
|---|---|---|
| 广域网页搜索 | 基础完成 | 聊天工具循环整体关联 durable ResearchRun |
| cancel/retry/resume | 基础完成 | 异步请求级取消、统一超时、实时阶段事件 |
| 网页读取 | 基础完成 | PDF、动态页面、会话状态页面 |
| GitHub repo/tree/blob/raw | 基础完成 | branch 歧义、submodule、LFS、超大文件 |
| 持久化仓库快照 | 基础完成 | manifest 增量刷新、过期清理、磁盘统计 |
| 本地代码搜索 | 初版完成 | embedding 融合与评测集 |
| Tree-sitter 图 | 初版完成 | 更多语言、完整 package-manager 解析 |
| 语义消歧 | 初版完成 | re-export、overload、动态派发、LSP 类型信息 |
| reference | 基础完成 | LSP 语义引用，排除注释和字符串误命中 |
| 影响范围分析 | 初版完成 | 数据流、配置影响、风险分层、真实仓库评测 |
| Git 历史对象 | 未完成 | branch/tag/commit/compare/diff/blame |
| PR/issue/CI | 未完成 | changed files、patch、review、workflow logs |
| 本地 checkout | 未完成 | clone/fetch/checkout 和工作树隔离 |
| 测试与构建 | 未完成 | 受控运行环境、命令预算、日志和回滚 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要、仅本地模式 |

## 4. 下一代码顺序

### G10-C1.4：模块身份与语义质量

1. TypeScript `export ... from` / barrel re-export 图。
2. Python package root、`__init__.py` re-export 和绝对导入身份。
3. Java package + class + method identity，处理同名类。
4. 函数参数数量、类型和 overload 候选分组。
5. 可选 LSP adapter：definition/reference/type information；不可用时保持 Tree-sitter fallback。
6. 小型 golden set，统计 resolved / ambiguous / unresolved、错误解析率和 impact recall。

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

PR #24 GitHub Actions CI #557：

- pytest：653 passed；
- Ruff：passed；
- package helper：passed；
- detect-secrets：passed；
- expanded mypy：passed；
- frontend Vitest：passed；
- TypeScript project build：passed；
- Vite production build：passed。

新增回归覆盖：

- 三个同名方法保持 ambiguous；
- receiver type 将调用解析到正确实现；
- SymbolIdentity 稳定性和 tree version 变化；
- class implementation 和 method override；
- 向上影响链和关联测试；
- 影响预算与 truncation；
- 叶子符号根文件保留；
- API、模型工具和持久化 gateway；
- PR #21、ResearchRun、快照、混合检索和 Tree-sitter 图回归不退化。

CI 在失败时上传 `pytest-log` 和 `frontend-log` artifacts。

## 6. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
