# Study Agent 当前状态

> **唯一当前状态入口**  
> 更新日期：2026-07-13  
> 当前实现基线：`1287c609080ee5b4dd36611829d098fa5e7ff937`

本文件只回答三个问题：**现在做到哪里、还差什么、下一步做什么**。其他文档不再重复维护进度；架构、专项需求和历史实现记录只作为附录。

## 1. 当前阶段

Study Agent 已完成主要架构迁移和第一轮高风险正确性整改，当前处于：

> **基础架构基本完成；G10 已具备广域网页搜索、来源评估、正文读取、GitHub 仓库/目录/源码读取和有预算的跨文件仓库快照。下一阶段是把这些能力升级为可取消、可恢复、可连续追问的正式研究代理。**

主运行架构是 React + FastAPI + SQLite。Chat/Session、GroupThread、NewsRun、ToolRun、MemoryRun、RAG/KnowledgeBase、WebLookupRun、Workspace Runtime 和 PedagogyEvalRun 已有明确 owner。

## 2. 已完成

### 2.1 架构与学习状态

- Chat、RAG、记忆、联网查询和教学评估使用服务端持久化状态。
- `PedagogyEvalRun` 接入真实完成事务；Provider 或解析失败不能静默推进学习阶段。
- 实时和刷新恢复都能读取逐轮 route、RAG、pedagogy evidence。
- 恢复时优先使用 committed learning state，只采纳 completed turn 的阶段轨迹。

### 2.2 会话与交互正确性

- 新建会话不再自动归档旧会话。
- 普通会话切换只取消 chat scope，不再默认 `cancelAll()`。
- Enter 发送、Shift+Enter 换行、中文输入法组合态防误发送。
- Assistant 复制只复制正文；角色头像使用装饰语义，避免重复朗读。
- 删除长期知识文档需要明确确认。

### 2.3 任务契约和外发策略

- 已识别 quick answer、research、learn、explain back、project execution、conversation、organize。
- 临时 research、quick answer 和 conversation 默认不推进 confirmed points、阶段或缺口。
- 联网支持关闭、每次询问、自动。
- 云端上下文可限制为仅当前问题、最近对话或允许本地资料片段。
- 紧凑型号名称支持确定性归一化和查询变体；查询注入当前 UTC 日期。
- 空结果和 Provider 不可用不再等同于“实体不存在”。

### 2.4 G10：广域网页研究

- 手动 WebLookupRun 已从新闻/RSS 专用网关切换到通用网页搜索网关。
- 通用搜索支持自建 SearXNG，默认可降级到 DuckDuckGo HTML。
- 模型工具支持 `web_search`、`web_read`，默认最多 5 轮、硬上限 8 轮。
- 模型可以执行多次聚焦搜索、比较来源、读取最相关页面，再进入最终回答。
- 搜索结果经过确定性 SourceAssessment：标题、URL、域名、来源类型、相关性、直接性、时效信息、重复和拒绝原因。
- 无效 URL、缺少来源标识和重复结果不会进入最终引用。
- ResearchRun 已持久化 research context、query attempts、selected/rejected sources、provider status、stop reason 和 evidence confidence。

### 2.5 G10：网页正文读取和 durable stage

- WebLookupRun 真实经过 `searching -> assessing -> reading -> synthesizing -> completed`。
- 只自动读取 `worth_reading=true` 的来源。
- 默认最多读取 3 个来源；每来源默认 6000 字符，整轮默认 16000 字符。
- 读取成功、失败、跳过、使用字符数和预算写入 `research_context.read_summary`。
- 每个 selected source 保存自己的 `read` 结果，刷新后仍可恢复。
- 某个来源读取失败不会丢弃已完成搜索和其他读取结果；Run 以 partial 语义完成。
- 已读正文摘要进入 source block；外部内容显式标记为不可信证据，而不是系统指令。

### 2.6 GitHub 仓库和源码读取

- 支持直接读取：
  - GitHub 仓库根目录；
  - README 和仓库元数据；
  - `tree` 目录；
  - `blob` 源码文件；
  - `raw.githubusercontent.com` 原始文件；
  - GitHub Contents API URL。
- 用户直接粘贴 GitHub URL 时跳过通用搜索引擎，直接进入来源评估和读取。
- 公共仓库无需 Token；可选 `GITHUB_TOKEN` / `GH_TOKEN` 用于提高限额和读取获授权仓库。
- `github_search`：
  - 可用时调用 GitHub code search；
  - 否则降级为 recursive tree/path 搜索；
  - 返回文件路径后可继续 `web_read` 读取源码。
- `github_snapshot`：
  - 获取一个明确 ref 的递归仓库树；
  - 按研究问题对源码路径排序；
  - 拉取一组相关文本 blob，支持跨文件分析；
  - 默认最多 24 个文件、每文件 12000 字符、总计 120000 字符；
  - 排除 `node_modules`、vendor、dist、build、generated、缓存、二进制、minified 和锁文件；
  - 保存 ref、tree SHA、文件 SHA、路径、截断状态、读取失败和预算使用。
- 模型提示词已区分：
  - 单文件问题使用 repository root / github_search / web_read；
  - 架构、调用链、调试等跨文件问题使用 github_snapshot。

### 2.7 测试覆盖

已增加不依赖真实网络的回归：

- GitHub repo/tree/blob/raw/API URL 解析；
- 仓库根目录、README、目录和源码读取；
- 无 Token 时的 recursive tree/path 降级；
- pasted GitHub URL 跳过搜索引擎；
- 通用搜索适配器；
- 网页/GitHub 读取成功、部分失败和预算耗尽；
- durable selected source read 恢复；
- GitHub snapshot 文件排序、目录排除、文件数和字符预算；
- WebToolAgent 对 github_search/github_snapshot 的工具分发。

### 2.8 过渡式课后整理

- after-session preview API 已存在。
- “整理学习”可生成 MemoryRun 候选并打开确认抽屉。
- MemoryRun 仍保持预览、用户确认和安全写入边界。

这仍是过渡实现，不代表正式学习闭环已经完成。

## 3. 当前联网能力边界

当前已经接近“研究型联网工具”，但还不是完整 Codex 式仓库代理。

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 多轮广域网页搜索 | 已完成基础 | 最多 8 轮工具规划，支持多查询和多来源 |
| 普通网页正文读取 | 已完成基础 | 本地 reader + 可选 Firecrawl/Jina 降级 |
| GitHub 单仓库/目录/文件读取 | 已完成 | GitHub API/raw，公共仓库无需 Token |
| GitHub 路径/代码搜索 | 部分完成 | code search 或树路径降级；无 Token 时不是全文内容搜索 |
| 跨文件仓库快照 | 已完成基础 | 按查询选择和拉取一组源码，受预算限制 |
| 整仓本地 checkout | 未完成 | 尚未执行真正 `git clone/fetch/checkout` |
| 跨文件语义索引 | 未完成 | 快照尚未进入临时 BM25/vector/code-symbol 索引 |
| Git 历史、commit、branch、tag | 未完成 | 尚无正式工具合同和恢复记录 |
| PR、diff、review、issue | 未完成 | 尚未接入研究工具链 |
| 调用图、符号定义/引用 | 未完成 | 尚无语言解析器或 tree-sitter/LSP 层 |
| 执行仓库测试和代码 | 未完成 | 当前只读，不运行远程仓库代码 |
| 持久化模型研究工具循环 | 部分完成 | WebLookupRun 可恢复；聊天中的 WebToolTrace 仍主要随 turn 保存 |
| 取消、重试、继续 | 未完成 | 研究内部读取尚未接入完整 cancellation/resume |
| 连续追问复用仓库 | 未完成 | 后续问题还不能稳定复用同一 snapshot/index |
| 私有仓库显式授权 UI | 未完成 | 环境变量 Token 可用，但缺逐仓库确认和外发摘要 |

## 4. 还需要做什么

### P0：先封住当前实现的正确性

1. 在完整仓库环境运行 pytest、Ruff、前端测试和生产构建。
2. 用真实公网验收 SearXNG/DuckDuckGo、普通网页、GitHub API 限额和错误降级。
3. 验证源码中的 prompt injection 不会被当作系统指令。
4. 验证大文件、二进制、超大目录、truncated tree、404/403/429 和超时。
5. 验证不同 Provider 是否都支持 5–8 轮 function calling。

### G10-A：正式可恢复 ResearchRun

1. 将聊天中的搜索/读取/snapshot 工具调用也关联到 durable ResearchRun。
2. 保存每个阶段开始时间、预算消耗、错误、停止原因和 partial result。
3. 加入 cancel endpoint 和取消传播。
4. 加入 retry/resume：从 failed/partial stage 继续，不重新支付已完成搜索和读取成本。
5. 支持连续追问复用上一 ResearchRun 的来源、页面和仓库 snapshot。

### G10-B：真正的仓库级代码研究

1. 新增 GitHubRepoSnapshot 实体：repository、ref、commit SHA、tree SHA、file manifest、版本和过期策略。
2. 对 snapshot 建立临时 BM25 + 可选 embedding 索引。
3. 增加代码专用分块：文件、类、函数、配置段和测试用例。
4. 增加 symbol/definition/reference 解析，优先考虑 tree-sitter；必要时接 LSP。
5. 支持按路径、符号、文本和语义混合检索。
6. 支持逐步扩大范围，而不是每次重新拉 24 个文件。
7. 支持依赖文件、入口文件、测试文件和调用方自动扩展。

### G10-C：Git 与 GitHub 工作对象

1. branch/tag/commit 列表和固定 ref。
2. commit detail、compare、diff 和 blame。
3. PR metadata、changed files、patch、review comments 和 CI 状态。
4. issue、release、README、docs 和配置文件联合研究。
5. 给每个结论记录 file path、ref、SHA 和行区间。

### G10-D：达到 Codex 式“可执行仓库代理”还需

1. 在受控临时目录真正 clone/fetch/checkout 仓库。
2. 明确只读/可写权限和分支边界。
3. 沙箱运行依赖安装、测试、lint、build 和有限命令。
4. 修改前后 diff、回归验证和失败回滚。
5. Token、私有源码和构建日志的脱敏与外发策略。
6. 大仓库增量更新、缓存、清理和磁盘预算。

这部分不应直接塞入当前 WebLookupService，而应成为独立的 `RepositoryResearchService` / `RepositoryRun`，但复用 G10 的证据、预算、取消和恢复协议。

## 5. 下一执行顺序

1. **当前实现全量测试与修复。**
2. **ResearchRun cancellation + retry/resume。**
3. **GitHubRepoSnapshot 持久化和连续追问复用。**
4. **仓库临时混合索引与代码分块。**
5. **commit/diff/PR/issue 工具。**
6. **受控本地 clone 和只读测试执行。**
7. G1 LearningClosureRun。
8. G2/G3 正式学习结束状态。
9. G4/G6 会话语义和恢复卡。
10. G5/G7/G8/G17 产品体验收敛。

## 6. 推荐默认配置

普通日常研究：

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

更深的源码审计可临时提高到 40–60 个文件，但不建议取消上限。所谓“自由大范围搜索”应理解为**模型可以自主选择搜索、阅读和扩展路径**，而不是无预算地抓取整个互联网或任意大型仓库。

## 7. 文档体系

日常只看两份：

1. [`PROJECT_STATUS.md`](PROJECT_STATUS.md)：唯一当前状态和下一步。
2. [`README.md`](README.md)：所有文档的分类导航。

其他文件只作为稳定技术参考、设计规范或历史记录。

## 8. 验证状态

- 新增了广域搜索、GitHub reader、durable reading 和 repository snapshot 的离线 pytest 回归。
- CI 工作流会运行 pytest、Ruff、detect-secrets、mypy、前端测试和生产构建。
- 当前 GitHub 连接仍未返回这些 push commit 的 workflow/check 状态，本文件不宣称远程 CI 已通过。
- 当前执行环境无法从容器拉取完整仓库运行全量测试；需要以仓库 Actions 或本地完整环境结果为准。

## 9. 维护规则

1. 当前进度、下一步和完成状态只更新本文件。
2. 架构文档只描述 owner、边界和稳定不变量，不维护产品进度表。
3. spec 只描述目标设计，不写“当前已完成”。
4. plan 完成后转为历史实现记录，不继续作为当前执行入口。
5. 每个代码切片必须同步更新本文件。
6. 不再创建新的 `STATUS / ROADMAP / NEXT_PHASE / AUDIT` 并列状态文档。
