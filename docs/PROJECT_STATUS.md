# Study Agent 当前状态

> **唯一进度入口**  
> 更新：2026-07-13  
> 当前实现基线：`f35c14711fd1c934a0eb3ce17552738c7094ec60`

这里只回答：**做到哪里、还差什么、下一步做什么**。详细设计、架构边界和历史计划不在这里重复。

## 1. 当前阶段

> **React + FastAPI + SQLite 主架构已完成。G10 联网研究已具备广域搜索、来源筛选、网页正文读取、GitHub 仓库/目录/源码读取，以及有预算的跨文件仓库快照。下一阶段是正式的取消、恢复、连续追问和仓库索引。**

## 2. 已完成

### 基础正确性

- committed learning state 是恢复真值，只采纳 completed turn。
- 临时 research、quick answer、conversation 不推进长期学习状态。
- 新建会话不自动归档；会话切换只取消 chat scope。
- Enter、Shift+Enter、中文输入法、正文复制和头像可访问性已修。
- 联网支持关闭、每次询问、自动；云端上下文范围进入真实请求路径。
- 空结果、Provider 不可用和“确认不存在”严格区分。

### 广域网页研究

- WebLookupRun 已从新闻/RSS 专用搜索切换到通用搜索。
- 支持自建 SearXNG，并可降级到 DuckDuckGo HTML。
- 模型可自主调用 `web_search`、`web_read`，默认最多 5 轮，硬上限 8 轮。
- 支持多次聚焦搜索、比较来源、读取页面后再回答。
- SourceAssessment 会记录标题、URL、域名、来源类型、相关性、直接性、时效信息、重复和拒绝原因。
- 无效 URL、缺少来源标识和重复结果不进入最终引用。
- ResearchRun 已持久化 query attempts、selected/rejected sources、Provider 状态、停止原因和 evidence confidence。

### Durable 阅读阶段

真实阶段：

```text
searching -> assessing -> reading -> synthesizing -> completed
```

- 默认读取最多 3 个高价值来源。
- 默认每来源 6000 字符，整轮 16000 字符。
- 成功、失败、跳过、字符消耗和预算写入 durable run。
- 每个 selected source 保存自己的 `read` 结果，刷新后可恢复。
- 单个页面读取失败不会丢弃其他结果；以 partial 语义完成。
- 外部网页和源码显式标记为不可信证据，不作为系统指令。

### GitHub 单仓库与源码读取

支持：

- 仓库根目录、README、元数据；
- `tree` 目录；
- `blob` 文件；
- `raw.githubusercontent.com`；
- GitHub Contents API URL。

行为：

- 用户直接粘贴 GitHub URL 时跳过搜索引擎，直接读取。
- 公共仓库无需 Token。
- `GITHUB_TOKEN` / `GH_TOKEN` 可用于更高限额和已授权仓库。
- `github_search` 优先使用 GitHub code search；不可用、403 或限流时自动降级为 tree/path 或 bounded snapshot。
- 返回的源码链接固定到当前 ref，保留文件 SHA、路径和截断状态。

### 跨文件 GitHub 快照

模型新增 `github_snapshot` 工具，用于架构、调用链、调试和跨文件问题：

- 读取一个明确 ref 的 recursive tree；
- 根据当前问题排序相关文件；
- 拉取多份文本 blob；
- 默认最多 24 个文件、每文件 12000 字符、总计 120000 字符；
- 排除 `node_modules`、vendor、dist、build、generated、缓存、二进制、minified 和锁文件；
- 保存 repository、ref、tree SHA、file SHA、路径、失败和预算。

### 回归覆盖

已增加不依赖公网的测试：

- GitHub URL 解析；
- 仓库、README、目录、源码读取；
- pasted URL 直读；
- code search/tree/snapshot 降级；
- 网页与源码读取成功、部分失败、预算耗尽；
- durable read 恢复；
- snapshot 文件排序、排除规则、文件数和字符预算；
- 模型工具分发。

## 3. 距离 Codex 式能力还差什么

| 能力 | 状态 | 缺口 |
|---|---|---|
| 多轮广域网页搜索 | 基础完成 | 缺正式 durable planner 和追问复用 |
| 网页正文读取 | 基础完成 | 缺更强页面类型、PDF/动态页面专项处理 |
| GitHub repo/tree/blob/raw | 完成基础 | 缺 branch 名歧义、submodule、大文件专项处理 |
| GitHub 代码搜索 | 部分完成 | 无 Token 时主要是路径/快照检索，不是完整全文索引 |
| 跨文件源码快照 | 基础完成 | 尚未持久化为独立版本化实体 |
| 整仓本地 checkout | 未开始 | 尚未 `git clone/fetch/checkout` |
| 代码语义索引 | 未开始 | 缺 BM25/vector/symbol 混合索引 |
| 定义与引用关系 | 未开始 | 缺 tree-sitter/LSP 层 |
| commit、branch、tag、diff | 未开始 | 缺正式工具和证据合同 |
| PR、review、issue、CI | 未开始 | 缺 GitHub 工作对象研究链路 |
| 仓库测试和构建 | 未开始 | 当前只读，不执行远程代码 |
| cancel/retry/resume | 未开始 | 内部搜索和读取尚不能从 durable stage 继续 |
| 连续追问复用 | 未开始 | snapshot 和读取结果尚无会话级缓存/索引 |
| 私有仓库授权 UX | 未开始 | 缺逐仓库确认、外发摘要和 Token 管理界面 |

## 4. 后续实施顺序

### P0：验证当前切片

1. 完整运行 pytest、Ruff、前端测试和 production build。
2. 真实公网验收 SearXNG、DuckDuckGo、GitHub API、403/404/429、超时和 truncated tree。
3. 验证不同模型 Provider 的 5–8 轮 function calling。
4. 验证源码中的 prompt injection 不会改变系统行为。

### G10-A：正式可恢复 ResearchRun

1. 将聊天工具循环关联到 durable ResearchRun。
2. 保存阶段开始时间、预算、错误和 partial result。
3. 加 cancel endpoint 和传播。
4. retry/resume 从当前阶段继续，不重复搜索和读取。
5. 连续追问复用上一轮网页、来源和 snapshot。

### G10-B：仓库级代码研究

1. 建立版本化 `GitHubRepoSnapshot`：repo、ref、commit/tree SHA、manifest 和过期策略。
2. 对 snapshot 建临时 BM25 + 可选 embedding 索引。
3. 代码按文件、类、函数、配置段和测试用例分块。
4. 加 tree-sitter；必要时接 LSP，支持 definition/reference。
5. 支持路径、符号、文本和语义混合检索。
6. 自动扩展入口文件、依赖文件、调用方和测试文件。

### G10-C：GitHub 工作对象

1. branch/tag/commit 和固定 ref。
2. compare、diff、blame。
3. PR、changed files、patch、review comments、CI。
4. issue、release、docs 联合研究。
5. 结论引用到 path、ref、SHA 和行区间。

### G10-D：可执行仓库代理

1. 受控临时目录 clone/fetch/checkout。
2. 只读/可写权限和分支边界。
3. 沙箱运行依赖、测试、lint、build 和有限命令。
4. 修改、diff、回归、回滚。
5. 私有源码、Token、日志脱敏和外发策略。
6. 增量更新、缓存清理和磁盘预算。

该部分应成为独立 `RepositoryResearchService` / `RepositoryRun`，复用 G10 的证据、预算、取消和恢复协议，不塞回单次 WebLookupService。

## 5. 下一代码切片

1. **ResearchRun cancellation + retry/resume。**
2. **GitHubRepoSnapshot 持久化和连续追问复用。**
3. **仓库临时混合索引与代码分块。**
4. commit/diff/PR/issue。
5. 受控本地 clone 和只读测试执行。
6. 再回到 G1 LearningClosureRun。

## 6. 推荐默认预算

```env
WEB_TOOL_MAX_ROUNDS=5
WEB_TOOL_CONTEXT_MAX_CHARS=30000
WEB_RESEARCH_MAX_READS=3
WEB_RESEARCH_MAX_CHARS_PER_SOURCE=6000
WEB_RESEARCH_MAX_TOTAL_CHARS=16000
GITHUB_SNAPSHOT_MAX_FILES=24
GITHUB_SNAPSHOT_MAX_FILE_CHARS=12000
GITHUB_SNAPSHOT_MAX_TOTAL_CHARS=120000
```

“自由大范围搜索”指模型可自主决定搜索、阅读和扩大范围，不代表取消所有时间、请求、字符和安全上限。

## 7. 验证状态

- 新增测试和代码已提交到 `main`。
- GitHub Actions 应运行 pytest、Ruff、detect-secrets、mypy、前端测试和构建。
- 当前 GitHub 连接没有返回这些 push commit 的 combined status/workflow run，因此**不宣称 CI 已通过**。
- 当前执行容器无法拉取完整仓库运行全量测试，最终以仓库 Actions 或本地完整环境为准。

## 8. 文档规则

- 当前状态只更新本文件。
- 文档导航见 [`README.md`](README.md)。
- 不再新增并列的长期 STATUS / ROADMAP / NEXT_PHASE / AUDIT。
