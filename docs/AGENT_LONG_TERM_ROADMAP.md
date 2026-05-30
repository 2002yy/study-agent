# Study Agent 长期规划路线图

本文档记录 Study Agent 的长期功能与技术扩展方向。目标不是盲目堆功能，而是围绕“可信信息链路、学习辅助、项目上下文、工程化交付”逐层增强。

当前优先级原则：

1. 先保证信息可信，再追求更多搜索源。
2. 先保证默认安全、本地优先，再接外部服务。
3. 每个新能力都必须配套测试、配置说明和可回退路径。
4. Agent 输出要能解释“依据来自哪里”，不能只给结论。

---

## 0. 总体分层

Study Agent 的能力分三层：

```text
基础可信链路层
→ 学习与项目智能层
→ 工程化与体验层
```

### 0.1 基础可信链路层

负责解决：

```text
能否找到正确网页
→ 能否解析真实链接
→ 能否读到正文
→ 能否去重
→ 能否判断来源可靠性
→ 能否保留证据链
→ 失败后能否安全降级
```

现有新闻/联网链路已经形成：

```text
search providers
→ resolve
→ canonicalize
→ domain policy
→ dedup
→ reader backends
→ digest
→ discuss
→ trace
```

### 0.2 学习与项目智能层

负责解决：

```text
用户当前在学什么
→ 项目做到哪一步
→ 哪些问题反复出现
→ 哪些内容应该写入长期记忆
→ 下次应该从哪里继续
```

### 0.3 工程化与体验层

负责解决：

```text
配置是否生效
→ 测试是否覆盖
→ 失败如何定位
→ UI 如何展示链路状态
→ GitHub 如何规范协作
```

---

## 1. P0：可信信息链路继续补强

这是当前最重要方向。Web Agent 的核心不是“能联网”，而是“能说明自己基于什么信息作答”。

### 1.1 Redirect Resolver / 重定向解析

必要性：

很多搜索结果不是原文链接，而是中转链接：

```text
news.google.com/...
bing.com/news/...
redirect?url=...
?q=https%3A%2F%2F...
```

如果不解析真实链接，会导致：

1. 正文抓取失败，只能看标题。
2. 多条结果其实是同一篇文章，却无法去重。
3. 无法判断真实来源域名。
4. source trace 显示中转链接，不利于验证。
5. domain policy 无法判断“官方文档 / GitHub / 搬运站 / 登录页”。

长期目标：

```text
所有外部搜索结果都先经过 resolve_news_link_metadata
每一跳 redirect 都做 URL 安全检查
最终 source trace 同时保留 original_link 和 resolved_link
```

验收标准：

- Google News / Bing News 中转链接能解析到真实链接。
- 重复中转链接能归并到同一 canonical_url。
- 解析失败时仍能 fail-soft，不阻塞整轮搜索。
- source block 能显示原始链接和真实链接。

---

### 1.2 Canonical URL Dedup / 规范化去重

必要性：

同一篇文章可能有多个 URL：

```text
https://example.com/article?id=1&utm_source=google
https://example.com/article?id=1&utm_campaign=rss
https://news.google.com/redirect?url=...
```

如果不规范化：

1. 模型会重复读同一篇文章。
2. 摘要会重复引用。
3. token 浪费。
4. 看起来来源很多，其实只有一个来源。

长期目标：

```text
raw URL
→ resolved URL
→ canonical URL
→ canonical dedup
```

验收标准：

- `utm_* / fbclid / gclid / spm / ref` 等跟踪参数被移除。
- 有意义 query 参数保留。
- canonical_url 相同的文章只保留一条。
- 没有 canonical_url 时用标题 fallback 去重。

---

### 1.3 Domain Policy / 域名策略

必要性：

不同查询应该优先不同来源。

技术查询应该优先：

```text
官方文档
GitHub
StackOverflow
ReadTheDocs
arXiv
Hugging Face
Microsoft Learn
Godot docs
Python docs
```

新闻查询应该优先：

```text
原始媒体
官方公告
高可信新闻源
直接发布页面
```

应该降权或过滤：

```text
登录页
账号页
OAuth 页面
广告页
聚合页
低质量搬运站
```

长期目标：

```text
query intent
→ domain scoring
→ hard block unsafe/auth pages
→ soft keep unknown domains
```

验收标准：

- 技术查询优先官方/项目/社区高质量来源。
- 未知域名默认不硬删，只是低优先级。
- 登录/账号/auth/OAuth 页面硬过滤。
- 每条结果记录 domain_policy metadata。

---

### 1.4 Reader Backend / 正文阅读器

必要性：

只看标题不够可靠。Agent 必须尽量读取正文，并记录读取方式。

当前理想顺序：

```text
local reader
→ Firecrawl-compatible fallback, if enabled
→ Jina Reader fallback, if enabled
```

默认原则：

```text
默认只走本地 trafilatura/readability/HTMLParser
Firecrawl 默认关闭
Jina 默认关闭
外部 reader 必须显式配置
```

长期目标：

```text
HTMLReader
PDFReader
MarkdownReader
DocxReader
GitHubReader
```

统一输出：

```json
{
  "text": "...",
  "method": "local_trafilatura",
  "source_url": "...",
  "quality_score": 0.87,
  "sections": []
}
```

验收标准：

- 能显示 `正文已读｜本地 trafilatura / 本地 readability-lxml / 本地 HTMLParser / Firecrawl / Jina Reader`。
- 本地 reader 失败后才尝试外部 fallback。
- 外部 reader 默认不调用。
- 非公开 HTTP(S)、localhost、file://、私网 IP 不会进入外部 reader。

---

### 1.5 Source Trace / 证据链追踪

必要性：

Agent 不能只输出“总结”，还要能说明：

```text
这句话来自哪篇文章
有没有读到正文
来源域名是什么
链接是否经过重定向
正文读取方法是什么
```

长期目标：

```text
每条结论
→ 关联 source ids
→ 标记 evidence level
→ 标记 confidence
```

建议结构：

```json
{
  "claim": "Godot 4.x 改进了导出流程",
  "sources": [1, 3],
  "confidence": "high",
  "evidence_type": "article_body"
}
```

证据等级建议：

```text
article_body：已读正文
official_title：官方标题但未读正文
source_snippet：搜索摘要
title_only：只有标题
inferred：模型推断，需要谨慎
```

验收标准：

- Digest 中每个重要结论能关联 source id。
- 标题-only 结论不能写成确定事实。
- source block 展示 reader method、resolved_url、domain_policy。

---

### 1.6 反幻觉约束

必要性：

联网不等于可信。标题、摘要、正文证据的可信程度不同。

Prompt 规则：

```text
没有正文证据时，只能说“标题显示/来源显示”。
不能把搜索摘要当原文事实。
不能把多个标题合成过度确定结论。
涉及时间、价格、版本、法律、健康等变化信息必须保守表达。
```

错误示例：

```text
OpenAI 已经发布 X。
```

更稳表达：

```text
检索结果标题显示 OpenAI 相关 X 信息，但当前未读取正文，需进一步确认。
```

验收标准：

- digest prompt 明确区分 body evidence 与 title-only evidence。
- group discussion 不得扩大 source 证据范围。
- UI/source block 中能看到哪些文章只读到标题。

---

## 2. P1：搜索能力扩展

### 2.1 Query Rewriter / 查询改写

必要性：

用户自然语言查询往往不适合直接搜索。

例：

```text
openai 语音模型怎么样
```

可改写为：

```text
OpenAI voice model latest
OpenAI realtime audio model
OpenAI speech-to-speech model
OpenAI API audio model documentation
```

长期目标：

```text
user query
→ intent detection
→ 3-5 search queries
→ source-specific search
→ dedup after canonicalization
```

验收标准：

- 每轮保留 original_query 和 rewritten_queries。
- 技术查询至少包含官方文档方向。
- 新闻查询加入时间限制。
- 改写失败时回退原 query。

---

### 2.2 Search Intent Classifier / 搜索意图分类

建议分类：

```text
tech_debug：技术报错
tech_docs：技术文档
news：新闻
academic：论文/学术
product：产品/价格/配置
project_context：用户项目相关
general：普通查询
```

不同分类对应不同策略：

```text
tech_debug → docs/GitHub/StackOverflow 优先
tech_docs → 官方文档优先
news → 新闻源/官方公告优先
academic → arXiv/论文源优先
product → 官网/pricing/changelog 优先
```

验收标准：

- intent 写入 search trace。
- domain policy 根据 intent 采用不同权重。
- UI 可显示当前搜索模式。

---

### 2.3 时间过滤

必要性：

新闻、模型版本、API、价格、法规都强依赖时间。

长期目标：

```text
自动识别 latest/today/recent/current/现在/最新
→ 加入时间窗口
→ source trace 显示发布时间
→ digest 区分最新信息与背景资料
```

验收标准：

- 查询“最新”时优先近 7/30 天。
- 历史资料不会冒充当前信息。
- 结果中保留 published_at 和解析状态。

---

## 3. P1：阅读质量扩展

### 3.1 Reader Quality Score

不是读到正文就一定可靠。需要质量评分。

建议指标：

```text
正文长度
标题匹配度
查询词覆盖度
广告/登录噪声比例
重复段落比例
语言匹配度
正文结构完整度
```

建议输出：

```json
{
  "reader_quality_score": 0.82,
  "reader_warnings": ["short_text", "low_query_overlap"]
}
```

验收标准：

- 低质量正文不直接作为高置信证据。
- digest 优先使用高质量正文。
- source trace 显示 reader warnings。

---

### 3.2 Relevant Chunk Selection / 相关段落选择

当前按 max_chars 截断不够精细。长期应做：

```text
正文
→ 分段
→ query relevance scoring
→ 取最相关段落
→ 保留上下文窗口
→ 再送 LLM
```

验收标准：

- 长文不会只取开头无关内容。
- 每篇文章 token 使用更稳定。
- digest 能引用与查询直接相关的段落。

---

### 3.3 文档读取扩展

学习 Agent 必须逐步支持：

```text
PDF
Markdown
Docx
GitHub README
代码文件
课程文档
论文
```

长期目标：

```text
DocumentReader interface
→ HTML/PDF/Markdown/Docx/GitHub readers
→ unified document chunks
→ source trace
```

验收标准：

- 不同文档格式输出统一 chunk schema。
- 每个 chunk 保留 source、section、page/line 信息。
- 支持后续 RAG 或项目问答。

---

## 4. P2：学习 Agent 必要功能

### 4.1 长期记忆分层

记忆不能乱写，需要分层管理。

建议分层：

```text
用户长期目标
当前学习主题
掌握情况
薄弱点
最近任务
偏好的解释风格
项目状态
反复出现的问题
```

写入原则：

```text
自动提出候选
用户确认后写入
可撤回
可查看
可按项目隔离
```

验收标准：

- 每轮学习结束可生成 memory candidates。
- 用户确认后才写入长期记忆。
- 记忆文件中区分事实、偏好、项目状态。

---

### 4.2 学习计划与复盘

Agent 应该支持：

```text
今日学习目标
本轮学习总结
遗留问题
下次继续点
复习题
实践任务
```

验收标准：

- “下课/结束本轮”可触发复盘。
- 复盘能写入 session log。
- 下次打开能恢复继续点。

---

### 4.3 错题 / Bug 知识库

对开发学习非常重要。

建议记录结构：

```json
{
  "project": "study-agent",
  "error": "...",
  "symptom": "...",
  "root_cause": "...",
  "fix": "...",
  "verification": "...",
  "related_files": []
}
```

验收标准：

- 遇到报错后可一键沉淀为 bug note。
- 相似报错可检索历史解决方案。
- 每条 bug note 包含验证方式。

---

### 4.4 项目上下文管理

用户经常同时开发多个项目，Agent 必须知道当前上下文。

建议记录：

```text
当前项目
当前版本
上一步改动
下一步计划
设计目标
暂缓项
已知 bug
验证命令
```

验收标准：

- 每个项目有独立 handoff 文档。
- 下一轮能从 handoff 继续，不依赖聊天记录。
- 每次改代码后自动更新“当前状态”。

---

## 5. P2：工具调用与任务执行

### 5.1 GitHub 工作流规范化

当前可以直接 commit main，适合快速迭代。长期建议：

```text
feature branch
→ PR
→ CI
→ review
→ merge
```

需要支持：

```text
自动开 branch
自动提交 PR
自动写 changelog
自动生成测试清单
自动检查 issue
```

验收标准：

- 重要改动不直接写 main。
- PR 描述包含改动、风险、测试。
- CI 失败时能读取日志并定位。

---

### 5.2 自动测试入口

每次改完代码，Agent 应输出固定格式：

```text
改了哪些文件
为什么改
如何验证
预期输出
失败时怎么定位
```

建议长期维护：

```text
docs/TESTING.md
docs/CHANGELOG.md
docs/AI_HANDOFF_CURRENT.md
```

验收标准：

- 每个 feature 有对应测试。
- 不适合自动测试的功能有手动验收标准。
- 测试命令写入文档。

---

### 5.3 Config Check / 配置检查器

当前搜索和 reader 开关已经变多，必须有配置诊断。

建议新增：

```bash
python -m src.news.config_check
```

目标输出：

```text
RSS: available
SearXNG: disabled / OK / failed
Firecrawl: disabled / OK / failed
Jina: disabled / OK
URL policy: OK
```

验收标准：

- 不需要真正跑完整新闻流程就能判断配置是否生效。
- SearXNG JSON disabled / 403 能明确提示。
- Firecrawl base URL 缺失能明确提示。
- 输出可复制给 Agent 继续诊断。

这是下一阶段最高优先级。

---

## 6. P2：安全与可靠性

### 6.1 SSRF 防护

Web Agent 必须持续强化 URL 安全。

需要覆盖：

```text
禁止 file://
禁止 localhost
禁止 loopback IP
禁止 private IP
禁止 link-local IP
禁止 metadata IP
限制 redirect 跳数
限制下载大小
限制 timeout
校验每一跳 redirect
```

进一步目标：

```text
DNS rebinding 防护
解析 IP 与实际连接绑定
统一 URL policy module
```

验收标准：

- 所有 search/reader/fetcher 使用统一 URL 安全检查。
- 每个外部请求都有 timeout 和 max_bytes。
- unsafe URL 有测试覆盖。

---

### 6.2 成本与性能控制

需要长期保留：

```text
max articles
max chars per article
max tokens per digest
performance mode
cache TTL
失败缓存
并发限制
```

验收标准：

- 新闻流程不会无限抓取。
- 外部 reader 失败不会反复重试。
- 大文章不会超 token。
- UI 可显示耗时和读取数量。

---

### 6.3 可观测性

建议新增日志：

```text
logs/news_pipeline_YYYYMMDD.jsonl
```

每轮记录：

```json
{
  "query": "...",
  "search_sources": ["rss", "searxng"],
  "resolved_count": 6,
  "read_count": 3,
  "reader_methods": ["local_trafilatura", "firecrawl"],
  "warnings": []
}
```

验收标准：

- 能快速定位“搜不到 / 读不到 / 去重过度 / reader 失败”。
- 日志不记录敏感 API key。
- 日志可用于 UI 诊断面板。

---

## 7. P3：体验层功能

### 7.1 UI 来源状态展示

UI 应显示：

```text
检索到 N 条
成功解析 N 条
成功读取正文 N 条
标题-only N 条
SearXNG: OK / disabled / failed
Firecrawl: OK / disabled / failed
Jina: OK / disabled / failed
```

验收标准：

- 用户能看懂 Agent 是否真的读了正文。
- 失败状态不是静默消失。
- source block 与 UI 状态一致。

---

### 7.2 一键重试

建议按钮：

```text
重新解析链接
只读官方来源
开启 Firecrawl 重读失败文章
开启 Jina 重读失败文章
只保留正文已读来源
```

验收标准：

- 用户可针对失败环节重试，不必重跑全流程。
- 重试不会破坏已有 source trace。

---

### 7.3 模式切换

建议模式：

```text
快速模式：标题 + 少量正文
严谨模式：多源交叉验证
技术模式：官方文档/GitHub 优先
论文模式：arXiv/论文源优先
低成本模式：不读正文，只给线索
```

验收标准：

- 模式会影响 search source、domain policy、reader budget、digest prompt。
- UI 明确显示当前模式。

---

## 8. 推荐推进顺序

### Phase 6：Web Pipeline Config Check + Diagnostics

最高优先级。

新增：

```bash
python -m src.news.config_check
```

输出：

```text
RSS: available
SearXNG: disabled / OK / failed
Firecrawl: disabled / OK / failed
Jina: disabled / OK
URL policy: OK
```

配套测试：

```text
tests/test_news_config_check.py
```

---

### Phase 7：Evidence Trace / Claim-to-source

目标：

```text
digest 中每条核心结论能关联 source id
```

改动范围：

```text
src/news/digest.py
source block formatter
wechat discussion prompt
```

---

### Phase 8：Anti-hallucination Digest Prompt

目标：

```text
标题-only 不写成确定事实
正文证据和标题证据分级表达
```

---

### Phase 9：Query Rewriter + Intent Classifier

目标：

```text
用户 query → 多 query → intent-aware domain policy
```

---

### Phase 10：Reader Quality Score + Relevant Chunk Selection

目标：

```text
读到正文后评估质量
长文只送相关段落
```

---

### Phase 11：Learning Memory + Bug Knowledge Base

目标：

```text
学习状态、项目状态、错误解决方案长期沉淀
```

---

## 9. 当前阶段状态

```text
✅ Phase 0：规划文档
✅ Phase 1：Redirect Resolver + Canonical Dedup
✅ Phase 2：Domain Policy scoring/filtering
✅ Phase 3：Reader backend interface + optional Jina fallback
✅ Phase 4：Optional SearXNG provider
✅ Phase 5：Optional self-hosted Firecrawl-compatible adapter
⬜ Phase 6：Web Pipeline Config Check + Diagnostics
⬜ Phase 7：Evidence Trace / Claim-to-source
⬜ Phase 8：Anti-hallucination Digest Prompt
⬜ Phase 9：Query Rewriter + Intent Classifier
⬜ Phase 10：Reader Quality Score + Relevant Chunk Selection
⬜ Phase 11：Learning Memory + Bug Knowledge Base
```

---

## 10. 每轮开发的固定交付要求

后续每一轮都要尽量满足：

```text
1. 代码改动
2. 测试或手动验收标准
3. 配置说明
4. 文档更新
5. 回退路径
6. 风险说明
```

如果功能不适合自动化测试，必须写清楚：

```text
手动验证步骤
预期现象
失败时定位方向
```

---

## 11. 本地拉取

更新后本地执行：

```bash
git pull
```

查看本文档：

```text
docs/AGENT_LONG_TERM_ROADMAP.md
```

相关文档：

```text
docs/NEWS_PIPELINE.md
docs/WEB_SEARCH_SETUP.md
```
