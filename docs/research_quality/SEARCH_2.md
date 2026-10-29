# Search-2：D2（DDG 优先回退）接入生产检索入口

> 目的：把 Search-1 的结论真正接到产品入口，并回答四个问题：
> 首条是否相关 → 网页能否读取 → 读到的正文是否含所需事实 → 需要多少时间。
> 不调用任何模型；只有 10 题，属于方向性验证，不是统计结论。

## 改了什么

`src/web/tool_gateway.py` 新增策略 `ddg_first`（D2）：

- 先查 DuckDuckGo；只有它返回空时才查 Bing；
- 不查 SearXNG（Search-1 中它的首条最差：1/31 答案页）；
- 保留 deadline / provider timeout、`provider_errors`、`providers_attempted`、`provider_counts`；
- 新增 `fallback_used` 字段，随 `search_strategy` 一起进入 trace，调用方能看出这次是否真的回退了；
- 新增 `WEB_SEARCH_STRATEGY` 环境变量选择策略，**默认仍是 `fallback`**，非法值在构造时直接报错；
- `GeneralWebGateway(search_strategy=...)` 显式传入时优先于环境变量。

## 探针（10 题，真实网络）

题集 `tests/fixtures/provider_routing/search_2_fact_checks_v1.json`；每题固定 `expect_all`（必须出现的词）
与 `expect_any_group`（每组至少出现一个）。同一进程内相同 URL 只读一次，避免把「缓存导致的第二次失败」算成读取率。

| 指标 | fallback（生产） | ddg_first（D2） |
| --- | ---: | ---: |
| 检索成功 | 10/10 | 10/10 |
| 提供商调用（10 题合计） | 10 | 10 |
| 首条与问题相关（人工） | 2/10 | **10/10** |
| 首条可读取（6 s） | 7/10 | **8/10** |
| 首条含所需事实词 | 1/10 | **6/10** |
| 检索延迟 P50 | 2.74 s | 4.52 s |
| 检索延迟 P95 | 4.03 s | 6.49 s |

本题集上 D2 没有触发回退（10/10 由 DDG 回答），符合「一次请求」的设计目标。

### 逐题

| 题 | fallback 首条 | D2 首条 | D2 读取 | D2 事实词 |
| --- | --- | --- | --- | --- |
| B01 千冶·刃遗器 | 星（百度百科单字） | bilibili 千冶刃攻略 | ✅ | ✅ |
| N02 FastAPI 会话 | FastAPI 官网首页 | CSDN 依赖注入实战 | ✅ | ✅ |
| N05 VACUUM FULL | PostgreSQL 官网首页 | 掘金 VACUUM vs VACUUM FULL | ✅ | ✅ |
| N07 vLLM release | GitHub 仓库页 | GitHub Releases 页 | ✅ | ❌ 见下 |
| N09 uv vs pip | astral.fan（镜像站） | uv 文档 Resolution | ✅ | ✅ |
| N11 Node LTS | Node.js 官网首页 | Node.js 24.11.0 (LTS) 发布页 | ✅ | ❌ 见下 |
| N13 PostgreSQL 版本 | PostgreSQL 官网首页 | PostgreSQL Release Notes | ✅ | ✅ |
| N16 游戏科学总部 | 黑（百度百科单字） | 中文维基「游戏科学」 | ❌ 连接被重置 | ❌ |
| N17 诺贝尔物理学奖 | 2025年（百度百科） | 百度百科「2025年诺贝尔物理学奖」 | ❌ 403 | ❌ |
| N19 SQLite WAL | SQLite 首页 | SQLite 官方 WAL 文档 | ✅ | ✅ |

### 3 个未通过的读取/事实，原因不同

1. **N07：读取成功但拿不到 release**。`GitHubSourceReader` 把 `/releases` 当成仓库读取，返回
   `kind=repository`（描述 + readme + 目录项），因此正文里没有 release 列表。这是**读取器覆盖范围**问题，
   不是检索排序问题。
2. **N11：页面正确但事实词规则没命中**。页面是 Node.js 24.11.0 (LTS) 发布页，正文 5731 字符却没有
   字面量 `version` / `版本`。说明「词表匹配」会漏掉语义正确但措辞不同的页面——事实校验需要更细的判据。
3. **N16 / N17：网络层面读不到**（维基连接被重置、百度百科 403）。这类失败与检索策略无关，
   但会直接让用户拿不到答案，属于独立的读取可靠性问题。

对照：fallback 的 N13 被判「含事实词」——但那是 PostgreSQL 官网首页，只是同时出现了 `release` 和 `version`。
**这正说明词表判据会把「有词」误当「有答案」**，所以本表把人工相关性单列，不把 fact_ok 当答案正确率。

## 结论

- D2 在真实生产入口上复现了 Search-1 的方向：首条从「官网首页/单字词典」变成「能回答问题的具体页面」（2/10 → 10/10）。
- 一次请求即可，本题集没有回退；延迟比 fallback 高约 1.8 s（P50），因为 DDG 走代理本身更慢。
- 读取率只是小幅提升（7/10 → 8/10）；真正的下一步瓶颈已经转移到**读取与内容提取**：
  GitHub release 页、被 403/重置的站点、以及词表无法表达的事实判据。
- 生产默认未改。要启用需要在部署环境设置 `WEB_SEARCH_STRATEGY=ddg_first`，并确认 DDG 的代理可用；
  DDG 不可达时会自动回退 Bing，但那时首条质量会退回本表 fallback 的水平。

## 局限

- 10 题、单次运行、单网络环境；不主张统计显著。
- 「首条相关」是人工判断（看标题/URL），未盲评。
- 「含所需事实」是词表命中，不等于答案正确；N13 的反例已经说明它会误判。
- 读取结果有网络波动（403 / 连接重置 / 超时），两次运行的读取率会变动。

## 下一步（按瓶颈排序）

1. **GitHub release 读取**：`/releases` 目前读成仓库元数据，导致「最新 release」这类问题永远缺事实。
2. **读取缓存负结果**：`article_fetcher` 首次失败会把空条目写入 TTL 缓存，后续重试返回
   `empty_cache_entry`，把一次瞬时失败放大成持续失败（Search-1 已记录，建议单独立项）。
3. **事实判据**：用「答案形态」而不是词表（版本号正则、日期、专有名词/机构名），减少 N11 这类漏判。
4. 之后再考虑边界页降权与中文实体查询写法；它们属于检索侧，本轮已经不是主要瓶颈。
