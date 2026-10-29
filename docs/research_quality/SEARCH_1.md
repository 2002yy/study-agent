# Search-1：真实检索 A/B/C 对照（31 题，2026-10-29）

> 目的：用真实网络检索回答「E2 到底比当前生产检索好多少，好在哪里」。
> 不调用任何模型；一次采集，离线回放；原始快照保留，可复核。

## 结论（先看这五条）

1. **生产检索（A）在 31 题里只有 1 题的首条结果是答案页**，其余首条是官网首页或词典页。
   Bing 优先的合并（B）同样是 1/31——Bing 的首条和 SearXNG 的首条基本是同一批首页/词典页。
2. **真正的差距来自 DuckDuckGo 自己的排序**：只用 DDG 的结果、完全不加任何重排（D），首条答案页就有 **30/31**。
3. **重排（C_prod / C_bigram）在首条质量上没有增益**：C_prod 也是 30/31，C_bigram 28/31，
   而且各出现一次明显退化（N13 官方 release notes 被换成安装教程；N12 非官方 React 仓库被推上首位）。
   上一轮记录的「E2 7/10」主要来自「能取到 DDG 的那些行」，不是重排本身——那一轮的 E1 只截取前 6 条，
   恰好全是 Bing 的结果，所以重排看起来像功臣。
4. **现有 Hit@3/Hit@6 规则不足以判断好坏**：同样 12 条池子随机抽 6 条，命中率就有 **96%**（宽规则）/
   **56%**（严规则）。因此本报告以人工 top-1 审计为主指标，关键词指标只作辅助，并明确标注其饱和。
5. **DDG 必须走代理**：不设 `WEB_DUCKDUCKGO_PROXY` 时 31/31 不可达（`URLError: timed out`）；
   设置后 30/31 成功，代价是合并臂 P50 从 3.51 s 升到 4.65 s、P95 从 4.03 s 升到 6.77 s。

## 方法

| 项 | 值 |
| --- | --- |
| 题集 | `tests/fixtures/provider_routing/search_1_queries_v1.json`，31 题（复用 10 题冻结集 + 21 题新增） |
| 分类 | game 6、software_version 5、chinese_tech 5、github_project 5、fact 4、docs 3、ai_releases 1、hardware 1、ml_research 1 |
| 采集 | 每題 3 次真实检索：生产配置（fallback）、仅 Bing、仅 DDG；每引擎 top 6 |
| 采集环境 | SearXNG 容器 `study-agent-searxng`（127.0.0.1:8080）；DDG 经 `http://127.0.0.1:7890` 代理 |
| 快照 | `docs/research_quality/SEARCH_1_CAPTURE.json`（31 题 × 3 模式 = 93 次请求，363 条池内结果） |
| 回放 | `docs/research_quality/SEARCH_1_REPLAY.json`（离线，无模型、无网络） |
| 审计 | `docs/research_quality/SEARCH_1_AUDIT.json`（人工 top-1 判定，31 题 × 5 臂） |
| 评估规则 | 沿用多字符锚点 + focus 词规则；另跑随机对照证明其饱和度 |

### 臂定义

| 臂 | 检索 | 用途 |
| --- | --- | --- |
| A | 生产 fallback：SearXNG → Bing → DDG | 当前基线（本次 31/31 由 SearXNG 回答） |
| B | 合并 + 去重，Bing 池在前，不重排 | 合并不重排的覆盖收益 |
| D | 合并 + 去重，DDG 池在前，不重排 | 分离「引擎自身排序」与「重排」 |
| C_prod | 合并 + 去重 + 生产 `_rank_merged`（按计划查询打分） | E2 现状 |
| C_bigram | 合并 + 去重 + 查询 n-gram 覆盖重排（候选算法） | 候选算法 |

B / C / D / C_bigram 使用**同一份原始快照**，所以覆盖差异只可能来自合并，排序差异只可能来自重排。

### 为什么不用 Hit@6 作主指标

同一 12 条池子、随机取 6 条：

| 规则 | 随机命中率 | A | B | D | C_prod | C_bigram |
| --- | --- | --- | --- | --- | --- | --- |
| 宽规则（现用：≥2 锚点，或 ≥1 锚点+focus） | **0.96** | 8/31 | 11/31 | 31/31 | 31/31 | 30/31 |
| 严规则（≥3 锚点，或 ≥2 锚点+focus） | **0.56** | 2/31 | 3/31 | — | — | 20/31 |

宽规则的随机基线已经 96%：题集里绝大多数查询的实体词（星铁、Python、Docker…）在任意池子里都会出现，
「命中」不再代表「找到了答案」。严规则对只有 1 个锚点的题（A05/N12/N13/N18）结构上不可能通过。
因此下面的主指标是**人工首条判定**。

## 主结果：人工审计首条结果（31 题）

| 臂 | answer（能回答） | topic_only（只有主题，答不了） | wrong（无关/词典/镜像） | answer 率 |
| --- | ---: | ---: | ---: | ---: |
| A 生产 fallback | 1 | 17 | 13 | **3.2%** |
| B 合并（Bing 优先，不重排） | 1 | 17 | 13 | **3.2%** |
| D 合并（DDG 优先，不重排） | 30 | 1 | 0 | **96.8%** |
| C_prod 合并 + 生产重排 | 30 | 0 | 1 | **96.8%** |
| C_bigram 合并 + 候选重排 | 28 | 1 | 2 | **90.3%** |

A 唯一答对的是 N07（vLLM 仓库地址——首条正好是仓库主页）。A 的 13 个 wrong 里，**11 个是
百度百科对单个汉字/单词的词条**（星、崩、异、轻、黑、世界、2025 年、open…），另 2 个是完全无关页面
（astral.fan 镜像站、税务页面）。A 与 B 的首条在 30/31 题上完全相同——SearXNG 的首条和 Bing 首条是同一批页面。

### 分解：收益来自哪一步

| 比较 | 变化 |
| --- | --- |
| A → B（加上 Bing 池、Bing 优先） | 1 → 1 答对；首条几乎不变（SearXNG 的首条与 Bing 首条一致） |
| B → D（把 DDG 池放到最前） | 1 → 30 答对 |
| D → C_prod（再加生产重排） | 30 → 30，且 22/31 的首条被改写 |
| D → C_bigram | 30 → 28（N08、N12、N13 退化） |

也就是说：**在这批题上，重排没有带来首条质量增益，只是把 DDG 已经排好的结果重新排了一遍，并引入两次退化。**
C 的 MRR 0.974 高于 D 的 0.883，但那套规则和「按查询词覆盖重排」高度同源，不能作为独立证据。

### 重排的具体退化

| 题 | DDG 首条 | 重排首条 | 问题 |
| --- | --- | --- | --- |
| N13 PostgreSQL 最新主版本 | `postgresql.org/docs/release/`（官方 release notes） | `releasebot.io` 汇总页 / `aliyun` 安装教程 | 用二手汇总替换一手官方文档 |
| N12 React 最新稳定版 | `react.dev/versions`（官方） | `github.com/react/react/releases`（非官方仓库） | 查询词覆盖无法区分官方/镜像 |
| N08 Ollama 量化格式 | DDG 该题失败，池中只有 Bing | `ollama.com/download/windows` | 下载页不是量化文档 |

共同点：**查询词覆盖只衡量「像不像这个问题」，不衡量「是不是一手来源」。**

## 其他指标

| 指标 | A | 合并臂（B/C/D/C_bigram 相同） |
| --- | --- | --- |
| 延迟 P50 | 3.51 s | 4.65 s |
| 延迟 P95 | 4.03 s | 6.77 s |
| 平均提供商调用 | 1.0 | 2.0 |
| 提供商失败 | 0/31 | DDG 1/31（N08） |
| 池内结果 | 6 | 12（其中 177 条是 DDG 独有） |
| 首条可读率（6 s 超时） | **15/31（48%）** | C_bigram 21/31（68%） |

首条读取失败原因（A）：百度百科 403（8）、缓存空条目（4）、网络失败（3）、后端全失败（1）。
两次读取实测的波动：A 14→15/31，C_bigram 20→21/31（403/429/超时会漂移），所以这组数字是量级证据，不是精确值。
这说明「找到了但读不到」是 A 的第二个独立问题：**词典页既不能回答，也读不出来。**

按分类的宽规则 Hit@6（仅辅助，受饱和度限制）：

| 分类 | n | A | B | C_prod | C_bigram |
| --- | ---: | ---: | ---: | ---: | ---: |
| game | 6 | 1 | 1 | 6 | 6 |
| chinese_tech | 5 | 2 | 3 | 5 | 5 |
| software_version | 5 | 3 | 3 | 5 | 4 |
| github_project | 5 | 1 | 3 | 5 | 5 |
| fact | 4 | 0 | 0 | 4 | 4 |
| docs | 3 | 1 | 1 | 3 | 3 |
| ai_releases / hardware / ml_research | 各 1 | 0 | 0 | 3 | 3 |

## 上一轮 7/10 该怎么解释

`PROVIDER_ROUTING_1.md` 里 E1（合并去重）是 2/10、E2（合并+重排）是 7/10，
当时的 E1 只取前 6 条，而合并顺序是 Bing 在前——E1 的窗口里根本没有 DDG 的行。
所以 E2 的「提升」至少有一大半是把 DDG 的结果纳入窗口，而不是重排本身。
本轮的 D 臂（DDG 优先、不重排）把这件事直接测出来了：**不重排也能到 30/31。**

## 局限（必须一起读）

- 31 题、一次网络快照（2026-10-29）、一个网络环境；不能据此claim 统计显著。
- 人工 top-1 审计是单人、未盲评的判断；它区分「首页 vs 答案页」，但不验证答案数值是否正确。
- 未验证最终回答质量：本轮只测「检索给了什么」，没测「模型读到后答得对不对」。
- DDG 经本地代理，代理质量、限流（N08 的失败、读取时的 429）都影响结论。
- SearXNG 在该网络下对中文实体查询返回单字词典页；这可能是引擎/分词问题，不是重排能修的。
- 宽/严规则都只是代理指标；本报告不把它们当作质量结论。

## 下一刀（可离线复测的最小改动）

按证据，优先级应是**先改「结果来源与顺序」，再谈重排**：

1. **交错合并（F_interleave）**：DDG/Bing 交替取（ddg1, bing1, ddg2, bing2…），保留各引擎原序。
   同一快照上首条与 DDG 完全一致（31/31），因此首条答案率仍是 30/31，同时第二位起有 Bing 覆盖；
   关键词规则下 Hit@3 29/31、Hit@6 30/31、MRR 0.856，与 D 基本持平。
2. **边界页降权**：把站点根路径和词典/百科域（`baike.baidu.com`、`zdic` 等）降到末尾。
   这条只应在「首条是首页/词典页」时触发，避免 N13 那类「官方文档被教程替换」。
3. **中文查询写法**：对实体做短语化/去歧义（例如把「星铁 千冶·刃 遗器」当一个短语块），
   目标是把 A 池里的单字词典页从源头去掉——这是采集侧的收益，重排拿不到。
4. 之后再重跑本套 31 题，比较 F_interleave + 边界降权 vs D，并保持同一份快照判据。

## 复现

```powershell
# 采集（真实网络；需要 SearXNG 容器与 DDG 代理）
$env:WEB_ENABLE_SEARXNG="true"; $env:SEARXNG_BASE_URL="http://127.0.0.1:8080"
$env:SEARXNG_ALLOW_LOOPBACK="true"; $env:WEB_ENABLE_BING_RSS="true"
$env:WEB_ENABLE_DUCKDUCKGO="true"; $env:WEB_DUCKDUCKGO_PROXY="http://127.0.0.1:7890"
$env:NO_PROXY="127.0.0.1,localhost"
python tools/run_provider_routing_replay.py --capture `
  --queries tests/fixtures/provider_routing/search_1_queries_v1.json `
  --limit 6 --output docs/research_quality/SEARCH_1_CAPTURE.json

# 离线回放（无网络、无模型）
python tools/run_provider_routing_replay.py `
  --input docs/research_quality/SEARCH_1_CAPTURE.json `
  --queries tests/fixtures/provider_routing/search_1_queries_v1.json `
  --limit 6 --output docs/research_quality/SEARCH_1_REPLAY.json
```

回放会把采集快照与题集绑定（版本 + 指纹 + case id），题集或锚点被改动会直接拒绝。
