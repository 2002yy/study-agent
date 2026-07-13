# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-13  
> 当前主线：`606fe4360afd71d687d2fb9c987d3553d56d803e`（PR #24 已合并）  
> 当前开发：PR #25，G10-C1.4 模块身份、re-export、overload 与可选 LSP

这里只回答：**做到哪里、还差什么、下一步做什么**。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。G10 已具备可取消、可恢复的广域 ResearchRun、持久化 GitHub 快照、本地混合代码检索、四语言 Tree-sitter 仓库图、稳定 EvidenceRef/SymbolIdentity、语义消歧、影响范围，以及模块身份与跨文件 re-export 解析。**

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

`EvidenceRef` 固定包含：repository、ref、tree SHA、path、file SHA、symbol、kind、start/end line。

`SymbolIdentity` 进一步加入 language、kind、qualified name、signature 和稳定 ID。相同 snapshot 的身份稳定；tree SHA 或文件版本变化时身份改变。

### Tree-sitter 仓库图

已合并 PR #23：

- 固定 Python、JavaScript、TypeScript/TSX、Java grammar wheel；
- 请求期间不下载 grammar；
- definitions / imports / calls / constructors / inheritance；
- Python 与 JS/TS 相对 import；
- Java dotted package import；
- `tsconfig.json` / `jsconfig.json` 的 `baseUrl` 和 `paths`；
- callers / callees / hierarchy / related files；
- source 与 target EvidenceRef；
- grammar 失败时保留旧 AST / fallback。

生产接入：模型工具 `github_structure`，API `POST /github-repo-structure`。

### 语义消歧与影响范围

已合并 PR #24：

- 同名符号返回 `resolved / ambiguous / unresolved`，不静默选择第一项；
- 候选评分记录可解释原因；
- 使用 exact qualified name、terminal name、same file、import path、kind、arity、receiver name 和 receiver type hint；
- 保守提取 Python/TypeScript/Java 字段、参数和构造注入类型；
- 调用边附带 target symbol ID、resolution status 和候选；
- class/interface implementation 和 method override；
- 向上 callers、向下 callees 和实现关系的 bounded BFS；
- 关联测试文件映射；
- depth / max files / max edges 预算；
- 预算触顶明确 `truncated=true`；
- 没有调用边的叶子符号仍保留自身定义文件。

生产接入：模型工具 `github_impact`，API `POST /github-repo-impact`。

### 模块身份与 re-export 语义

PR #25 已实现：

- 版本化 `ModuleIdentity`：repository / ref / tree SHA / path / file SHA / language / module name；
- TypeScript/JavaScript `export { ... } from` 和 `export * from` 图；
- Python package root、绝对导入和 `__init__.py` re-export 图；
- 本地 bare-module 与 package-root 解析；
- Java package + class 模块身份；
- 显式 import/re-export 链优先于全局同名猜测；
- 多模块同名顶层符号在没有上下文时保持 ambiguous；
- 模块限定查询，例如 `com.beta.UserService.load`；
- `OverloadGroup` 按 module + parent + name + kind + signatures 分组；
- 无签名时 overload 保持 ambiguous；
- 可用参数数量选择唯一 overload，例如 `load(String,int)`；
- 结构结果返回 modules、exports、overload groups 和 module-qualified name。

### 可选 LSP 边界

- 新增 `LspAdapter` Protocol；
- 默认 `NullLspAdapter` 明确返回 unavailable；
- `CallbackLspAdapter` 可接外部管理的 definition/reference/type-information 客户端；
- API 请求路径不会自行启动语言服务器或 shell 子进程；
- Tree-sitter/static 分析始终是可用 fallback；
- 结构结果显示 LSP provider、availability、definition、references 和 type information。

### 结构质量 golden set

新增确定性评测器，输出：

- resolved accuracy；
- ambiguous recall；
- unresolved recall；
- overall resolution accuracy；
- impact-file recall；
- test-mapping recall；
- 每个 case 的实际/预期对照。

当前固定混合 fixture 覆盖 TypeScript barrel、Python package re-export、Java package 同名类、Java overload、影响文件和测试映射。

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
| 本地代码搜索 | 初版完成 | embedding 融合与真实仓库评测集 |
| Tree-sitter 图 | 初版完成 | 更多语言与完整 package-manager 解析 |
| 模块/re-export | 初版完成 | npm package exports、Python namespace package、复杂 barrel 循环 |
| overload | 初版完成 | 参数类型兼容、泛型、继承重载和动态派发 |
| LSP | 适配边界完成 | 实际语言服务器生命周期、workspace trust、超时和缓存 |
| reference | 基础完成 | LSP 语义引用，排除注释和字符串误命中 |
| 影响范围分析 | 初版完成 | 数据流、配置影响、风险分层、真实仓库评测 |
| Git 历史对象 | 未完成 | branch/tag/commit/compare/diff/blame |
| PR/issue/CI | 未完成 | changed files、patch、review、workflow logs |
| 本地 checkout | 未完成 | clone/fetch/checkout 和工作树隔离 |
| 测试与构建 | 未完成 | 受控运行环境、命令预算、日志和回滚 |
| 私有仓库体验 | 未完成 | 逐仓库确认、凭据管理、外发摘要、仅本地模式 |

## 4. 下一代码顺序

### G10-C2.1：固定版本与 Git 历史对象

1. branch / tag / commit ref 解析与歧义处理。
2. 所有源码证据固定 resolved commit SHA，而不只保存可移动 branch 名。
3. commit metadata、tree SHA、parent、author/committer 和 verification。
4. compare 与文件级 diff/patch。
5. blame 行区间与 EvidenceRef 对齐。
6. Git 对象查询预算、缓存和 Provider 失败语义。

### G10-C2.2：PR / issue / CI 联合研究

1. PR metadata、changed files、patch 和 review threads。
2. issue、release 和关联文档。
3. GitHub Actions checks、job steps、失败日志和 artifact。
4. 将 PR diff 与结构化影响分析、相关测试映射结合。

### G10-D：可执行仓库代理

1. 受控临时目录 checkout。
2. 只读运行环境和命令白名单。
3. 运行 test、lint、build。
4. 可写工作树、diff、回归和回滚。
5. 增量更新、缓存清理和磁盘预算。

## 5. 当前验证

PR #25 GitHub Actions CI #573：

- pytest：660 passed；
- Ruff：passed；
- package helper：passed；
- detect-secrets：passed；
- expanded mypy：passed；
- frontend Vitest：passed；
- TypeScript project build：passed；
- Vite production build：passed。

新增回归覆盖：

- TS barrel re-export 修复同名调用目标；
- Python package-root / `__init__.py` re-export；
- Java package 同名类消歧；
- overload 无签名保持 ambiguous；
- overload 按参数数量解析；
- ModuleIdentity / ExportEdge / OverloadGroup 稳定数据；
- Null LSP 和 callback LSP；
- resolution / impact / test mapping 质量指标；
- PR #21、ResearchRun、快照、混合检索、Tree-sitter 图和语义影响回归不退化。

CI 在失败时上传 `pytest-log` 和 `frontend-log` artifacts。

## 6. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
