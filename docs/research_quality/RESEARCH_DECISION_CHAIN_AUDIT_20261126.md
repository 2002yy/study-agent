# 研究决策链审查（2026-11-26，只读）

横向读取能力冻结后的第一份审查。目的不是再补功能，而是回答一个更实际的问题：
模型拿到这些能力后，实际能用到多少。本文只读代码与现有测试，不调用付费模型、
不改生产行为。引用位置以当前 `main`（`1f6e153e`，音频收口后）为准。

## 1. 现有三条执行链

### A. 聊天工具循环（模型自己调工具）

入口：`src/tools/persistent_web_agent.py:319` → `run_tool_loop`。

- 模型可见工具：`WEB_TOOLS` 的 15 个（`web_search`、`web_read`、13 个 GitHub 工具）
  加 `github_pr_review_context`（`persistent_web_agent.py:29`）。
- `web_read` 的 schema 已包含 `mode=video/comments/audio` 与 `audio_seconds`
  （`src/tools/web_agent.py:71`）。
- 系统提示词只讲工具用途，不含平台地图（`src/tools/web_agent.py:255`）。
- 总预算 `WEB_TOOL_TOTAL_BUDGET_SECONDS` 默认 12 秒、最多 3 轮
  （`persistent_web_agent.py:299`、`:324`）。

### B. 语义恢复（默认研究路径，模型只做规划与判定）

入口：`persistent_web_agent.py:171` → `_resolve_semantic` → `recover_public_research`。

- 模型看到平台地图（`src/web/semantic_recovery.py:365`），输出查询与可选
  `site_key`；搜索和读取由运行时执行。
- 预算：简单问题 3 次读取 / 2 次查询 / 30 秒；比较类问题 5 次读取 / 4 次查询 /
  60 秒（`src/web/research_recovery.py:79-80`）。
- 读取超时上限 8 秒（`research_recovery.py:992`）。
- 候选先经确定性 `assess_sources`，再对前 5 条做一次模型相关性判定
  （`research_recovery.py:895`、`:932-946`）。

### C. Deep 研究（多波次 Claim Engine）

入口：`persistent_web_agent.py:195` / `:395` → `research_service.execute`。

- 模型以结构化调用参与：claim 规划、候选评估、证据抽取、lead 发现、URL/域名提案；
  没有工具 schema，也不自己执行 `web_read`。
- 预算：40 候选 / 12 读取 / 8 万字符 / 180 秒（`src/application/deep_execution.py:49-57`）。
- 每次读取上限 10 秒（`src/application/active_research_runtime.py:691`）。
- 波次上限 8，停止由 Gate、饱和与预算共同决定（`src/web/research/runtime.py:95`、
  `src/application/research_stop_gate.py:120-150`）。

## 2. 六个问题的直接回答

| 问题 | 现状 |
| --- | --- |
| 模型能看到哪些信源和工具 | 聊天链看到 16 个工具但看不到平台地图；语义/Deep 链看到平台地图但没有工具 schema |
| 如何选择搜索平台 | 只有语义/Deep 的规划调用能输出 `site_key`；聊天链的 `web_search` 没有站点参数 |
| 如何选择值得读的资料 | 语义链：确定性筛选 + 前 5 条一次相关性判定；Deep：逐候选模型评估后再读 |
| 引用链接如何进入后续阅读 | 只有 Deep 的 lead 发现能回读外部 URL，最多 2 次/运行、深度 1；聊天与语义链不回读 |
| 冲突如何触发进一步研究 | Gate 能标记冲突并保留读取额度，但不保证生成反例查询 |
| 如何判断信息足够并停止 | 确定性 Gate + 饱和 + 波次上限 + 预算；预算耗尽时输出 partial，不假装完整 |

## 3. 断点与未被使用的能力

### P0-1 长读取在聊天工具链里被 12 秒总预算截断

`web_read` 暴露了 `video` 与 `audio`，网关给它们分别留了
`seconds+60` / `seconds+90` 的预算（`src/web/tool_gateway.py:504-522`），
但聊天工具循环的外层 `future.result(timeout=12)`（`persistent_web_agent.py:299`
与 `llm_client.py:701` 起）会在读取完成前返回；`execute_tool` 是同步调用，
没有单工具超时，后台线程的结果不会被模型看到。

路由让问题更严重：默认研究问题走语义链（`persistent_web_agent.py:171`），
它固定用 `timeout=min(8, ...)` 读取（`research_recovery.py:992`）；
只有 GitHub/PR 类问题才进入工具循环（`_requires_planned_tools`，
`persistent_web_agent.py:81`）。也就是说：

- 能看到 `mode=video/audio` 的链，主要服务 GitHub 问题；
- 真正会遇到播客/视频的研究问题，走的是 8 秒上限的语义链。

影响：视频、音频以及超过 8–12 秒的浏览器读取，即使 schema 可见，也基本无法
通过现有入口进入证据。现有测试只验证网关层成功，没有覆盖这两层预算。

免费复现（2026-11-26，未调用付费模型）：约 4 分钟中文语音、240 秒窗口，
8 秒预算 → `audio_timeout`（7.2 秒）；同一文件 120 秒预算 → `audio_asr`，
12 段、12.1 秒。说明 8 秒语义读取上限会在 1 分钟以上音频上直接失败。
`audio_timeout` 的显式返回是本次补上的；此前 `TimeoutExpired` 会直接抛出。

仍未动态验证：聊天工具循环的 12 秒外层超时是否会丢弃已完成的工具结果。
这需要一次不付费的假模型工具循环测试；本文只做静态判断。

### P0-2 平台地图与工具入口分属两条链

平台地图只在语义规划（`semantic_recovery.py:365`）、claim 规划
（`src/web/research/claim_planner.py:336`）和 Deep 提案
（`src/web/research/llm_proposal.py:123`）里出现。聊天工具链的系统提示
（`web_agent.py:255`）没有地图，`web_search` 也没有 `site_key` 参数。

结果：能看到新读取模式（`web_read`）的链不知道平台方向；知道平台方向的链
不使用 `web_read` 的新模式。新增读取器大多只能靠运行时自动分派碰运气。

### P1-1 确定性引用链接没有消费者

`raw_content.citation_links`（`src/news/raw_content.py:601`）在读取时生成
`[links]` 块（`src/news/article_fetcher.py:441`），但全仓搜索没有任何运行时
消费者把它变成后续候选；`domain/runtime_entities.py` 里的 `citation_links`
是回答引用，不是页面链接。

真正的引用追踪在 Deep 的 lead 发现：模型从读取内容里最多抽 5 个 URL
（`lead_discovery.py`），每轮只允许 2 次 lead 读取、深度 1
（`runtime.py:79-95`）。而且 lead 抽取只取前 6000 字符
（`lead_discovery.py:209`），`[links]` 追加在正文之后。

免费实测（2026-11-26）：

| 页面 | 读取长度 | `[links]` 位置 | 是否进入 6000 字符窗口 |
| --- | --- | --- | --- |
| docs.python.org asyncio | 5108 | 2106 | 是 |
| MDN JavaScript 导论 | 15833 | 12180 | 否 |
| PEP 8 | 20000（触顶） | 未出现 | 否 |

长页面里，确定性提取的引用链接既可能落在 6000 字符窗口之外，也可能被
`max_chars` 截掉。引用追踪因此不是“有链接就会跟”，而是依赖模型在窗口内
自己注意到并写进 `discovered_urls`。

### P1-2 章节锚点在运行时被 canonical URL 丢掉

`section_text` 依赖 URL fragment（`raw_content.py:471`），但运行时用于身份和
去重的 `canonicalize_url` 明确丢弃 fragment（`src/news/url_normalizer.py:391`）。
因此“读长文档的某一节”只在调用方直接传入带 `#id` 的 URL 时成立；搜索候选
进入运行时后通常已经失去锚点。

### P1-3 冲突能阻止停止，但不保证主动找反例

Gate 只有在同一 claim 同时存在 `supports` 与 `contradicts` 时才建立
`ConflictGap`（`src/web/research/evidence_gate.py:305`），随后：
- 停止信号把冲突 claim 当作未解决（`research_runtime_wave_stop_signal.py:37-45`）；
- 读取计划为冲突保留额度并优先冲突候选（`research_runtime_read_plan_context.py:58-70`）。

但冲突本身不会生成新的 `EvidenceGap`（`conflict_gaps` 不进入 `state.gaps`），
反例查询只在 `gap_type` 含 conflict/contradict/counter、或来源角色为社区/独立二手、
或 claim 不要求 primary 时出现（`src/web/research/gap_planner.py:335-385`）。
初始 gap 类型只有 `primary_required` / `independent_support_required` /
`support_required`（`claim_planner.py:679`）。所以要求一手来源的 claim 遇到冲突时，
运行时只会更愿意读已经搜到的候选，不会专门去搜“更正/反例”。

### P1-4 用户直接给出的 URL 不保证进入读取候选

语义链的读取候选来自两类：官方计划里的已知 URL（`official_plan`，
`src/web/research/official_resolver.py:30`）和搜索结果（`research_recovery.py:769`
之后）。聊天链也没有把用户消息里的 URL 自动变成 `web_read` 候选。

结果：用户贴一个播客 MP3、PDF 或长文档链接，默认路径不保证会直接读它，而是把
它当普通研究问题去搜索。官方源与搜索结果之外的“用户指定来源”没有独立入口。

### P2-1 读取名额比读取器更稀缺

简单问题 3 次读取、比较类 5 次；Deep 12 次。读取器数量已经很多，但一轮研究能
消化的正文数量没变。新增能力提高的是“单次读取的覆盖面”，不是“能读多少条”。
这不是 bug，但意味着继续加读取器的边际收益确实在下降。

### 已验证的修复：官方资料优先级

#663 的回归已修：已知官方源 URL 不再先走平台 API 摘要，官方页面字段优先
（`src/web/tool_gateway.py` 的平台分派保护 + `tests/test_official_source_quality.py`
的回归测试）。这类“新读取器抢占旧高质量路径”的问题是真实存在的，后续新增
分派时必须继续用同样方式锁住。

## 4. 能力与信源地图的一致性

- 平台地图现在包含平台 API、视频/评论模式与音频模式（`src/web/site_pool.py:373`）。
- `web_read` schema 包含 PDF 自动分派、目录、章节、字幕、音频与播客链接，
  但地图只描述平台，不列格式；这是有意的分工，不算不一致。
- 不一致点在“地图里的能力”和“模型当前链能调到的能力”之间：地图由规划链使用，
  格式能力由网关自动分派或聊天工具链使用，两者没有汇合。

## 5. 下一步应验证什么（仍不写功能）

1. 用假模型做一次零成本工具循环：请求 `web_read(mode="audio")`，确认 12 秒
   总预算是否真的丢弃结果，并记录实际错误/超时形态。
2. ~~用现有免费网关样本，检查语义链/Deep 链读到音频链接时是否自动分派。~~
   已完成：30 秒 WAV 在 8 秒预算内可读；约 4 分钟音频在 8 秒预算下返回
   `audio_timeout`，120 秒预算成功。PDF 已在 #664 实测。
3. 用现有证据链，检查 `[links]` 是否进入 lead 抽取的 6000 字符窗口；若没有，
   这是引用追踪的确定性断点。
4. 只有在获得付费授权后，才用 #655 的 A/B/C 实验观察模型是否真的会选择平台、
   是否会回读引用、是否会在冲突时改变结论。

## 6. 结论

读取能力已经足够丰富；真正的短板在“能力可见性”和“决策汇合”：

- 模型能看到的能力，和模型能实际完成的能力，不是同一套；
- 平台选择只存在于规划链，格式读取只存在于网关/工具链；
- 引用回读只存在于 Deep 的有限 lead 通道；
- 冲突能阻止错误收敛，但还不能主动寻找反例。

在这些断点被免费证据确认之前，不宜再增加平台、读取器或新的研究框架。

## 7. 修复进度（2026-11-26）

六个断点已按顺序修复并合并，全部是免费验证；真实模型行为仍未验证。

| 断点 | 合并 | 免费证据 |
| --- | --- | --- |
| 用户指定 URL | #667 `7e474965` | arXiv PDF 由 0 次读取变为 `pdf_text` 5999 字符；URL 先读、搜索面去掉 URL |
| 阅读预算 | #668 `c3136225` | 30 秒 WAV 8 秒失败 / 48 秒成功；4 分钟音频 8 秒 `audio_timeout` / 120 秒 12 段；假模型 12 秒丢弃、45 秒保留 |
| 平台地图与工具 | #669 `49181be2` | `web_search.site_key` 走定向路由；工具提示包含地图与读取模式 |
| 结构化引用 | #670 `a4892d69` | MDN 15833 字符 29 条 links；PEP 8 触顶仍 14 条；lead 请求收到窗口外链接 |
| 章节锚点 | #671 `13a882e8` | `#introduction` 走 `section_text`，整页走 `local_trafilatura`；缓存隔离 |
| 冲突反例 | #672 `4bf2639d` | `conflict_open=True` 时规划出 counter_evidence（含 correction），否则不生成 |

仍存在的边界：

- 聊天工具循环总预算 45 秒仍会截断超长媒体；4 MB 音频上限未变。
- 用户指定来源只覆盖消息里的 URL，不会自动发现页面中的链接（那属于 lead 机制）。
- 假模型只证明“程序允许并传得到”，不证明 DeepSeek 会主动这么做；这需要 #655 的付费实验。
- 测试里旧的读取结果替身缺少 `links` 字段，已按 `ArticleReadResult` 契约补齐，不删除测试。

下一步不再是工程扩展，而是真实研究实验；条件与预算见 `docs/PROJECT_STATUS.md` §0。
