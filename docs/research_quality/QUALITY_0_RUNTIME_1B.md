# Quality-0 Runtime-1B：E2 搜索策略接线（切片 1）

> 状态：**候选路径已实现，默认关闭，零真实调用。**
> 本切片只做「candidate 臂的搜索路径真的存在且可被证明」，四臂运行器与预算接线在后续切片。

## 为什么需要它

E2 此前只存在于离线重放工具（`tools/run_provider_routing_replay.py`）里。生产搜索是**顺序回退**：SearXNG → Bing → DuckDuckGo，第一个有结果的引擎决定答案。因此「候选臂」在真实运行时并不存在，任何对比都会退化成「同一个路径跑两次」。

本切片给 `GeneralWebGateway` 增加一个显式策略参数：

```python
GeneralWebGateway()                            # fallback（默认，与今天完全一致）
GeneralWebGateway(search_strategy="merge")     # E2：bing + ddg 同查、去重、重排
```

默认值不变是硬要求：实验路径若被顺手打开，之后所有对比都不再有意义。未知策略名直接 `ValueError`，不静默回退。

## merge 策略做什么

1. 对**同一个 query** 分别请求 `bing_rss` 与 `duckduckgo_html`（`fallback` 会在第一个成功的引擎处停止）；
2. 按 `_result_key`（URL）去重，重复计入 `duplicate_count`，不静默吸收；
3. 用生产评分器 `assess_sources` 按 relevance 重排；
4. 被评分器丢弃的结果不删除，保留原相对顺序排在末尾——否则「合并」会看起来像「排名提升」，实际是丢了某个引擎的结果。

排名信号与评估规则保持独立：这里用的是生产来源评分，不是 Hit@6 那类评估判据。

## Trace 合同

只有 merge 策略会返回这些字段，fallback 完全不出现（否则调用方会误以为两个引擎都被查过）：

| 字段 | 含义 |
| --- | --- |
| `search_strategy` | `"merge"` |
| `providers_attempted` | **实际发起调用**的引擎，在调用前一刻记录 |
| `providers_skipped` | 未调用及原因：`provider_disabled` / `search_budget_exhausted` |
| `provider_counts` | 每个实际调用的引擎返回的原始行数 |
| `merged_count` | 合并前总行数 |
| `duplicate_count` | 被去重掉的 URL 数（同一 URL 被两个引擎返回算 1 条） |
| `ranked_urls` | **对外交付**的最终顺序（域名过滤之后） |

四条真实性规则：

1. **未调用不算尝试**。环境开关关闭或搜索预算耗尽时，引擎记入 `providers_skipped`，不进入 `providers_attempted`——否则运行器会以为双引擎检索发生过。
2. **交付顺序与 trace 一致**。`site:` 域过滤之后 `ranked_urls` 重新取最终结果，不会留下调用方从未收到的 URL。
3. **变体级 trace 描述被采用的那个变体**。多查询变体时 `search_detailed` 记录 `adopted_query` 与逐变体 `merge_traces`；顶层聚合字段只来自被采用的变体。
4. **没有结果就没有聚合**。所有变体都没结果时 `adopted_query=None`、`ranked_urls=[]`，聚合字段省略，避免把失败的一次尝试呈现为本次检索的证据。

这些字段从 `_search_single` 经 `search_exact` 一路传到 `search_detailed`，所以运行器在真实调用链上就能拿到证据，而不需要额外埋点。

## 离线证据

`tests/test_web_search_strategy.py`（12 条）：

- 默认策略仍是 `fallback`；未知策略被拒绝；
- **fallback 行为未变**：Bing 有结果时 DuckDuckGo 不被调用，且不出现 merge 字段；
- merge 在第一个引擎有结果时仍查第二个；
- 重复计数、`provider_counts`、重排顺序（更相关的第二引擎结果排到第一）；
- 单引擎失败仍合并另一个，并保留错误；
- 环境开关关闭某引擎时记录 `provider_disabled`，不假装查过；
- trace 能到达 `search_detailed`（变体级 API）；
- 多变体 trace 归属、域过滤后交付顺序、无结果时不产生聚合。

影响集：`tests/test_web_search_strategy.py` + 10 个 gateway/search/web_lookup 套件 = **83 passed**；`ruff` clean；`mypy` 改动文件无新增错误。

## 切片 2：trace 到达持久化的 run

### 问题

`ResearchWebGateway.search()` 是生产研究链路的入口，它只返回结果列表。merge trace 因此死在网关之上——E2 真的执行了，但 Quality-0 在 run 记录里看不到证据。

### 改动

| 文件 | 内容 |
| --- | --- |
| `src/web/tool_gateway.py` | 新增模块级 `merge_trace(payload)`；`GeneralWebGateway._merge_trace` 改为调用它 |
| `src/web/research_gateway.py` | 新增 `search_with_trace()` 返回 `(results, trace)`；`search()` 仅作兼容包装；新增 `ResearchSearchUnavailable` 携带失败尝试的 trace |
| `src/application/web_lookup_service.py` | 用 `_gateway_search()` 一次调用同时取得结果与 trace，写入 `query_attempts[*]["search_trace"]` |
| `tests/test_research_gateway_trace.py`（新） | 11 条链路与并发契约 |

### 单点判定：什么才算 merge

`providers_attempted` 在 fallback 路径上也存在，所以「有这个字段」不能证明发生过合并。唯一判据是 `search_strategy`——`merge_trace()` 只认它，两个调用方共用同一处实现，避免两套 key 列表各自漂移。这条正是新测试抓出来的真实缺陷：按 key 白名单拷贝时，fallback 的检索被写成了 `{'providers_attempted': ['bing_rss']}`，看起来像发生过合并。

### 复审修正：证据必须绑定到产生它的那次调用

最初实现是「网关保存 `_last_trace`，服务事后调 `search_trace()` 回读」。这在共享网关上不成立：

```
A 搜索 → 网关记住 A 的 trace
B 搜索 → 覆盖为 B 的 trace
A 回读 → 拿到 B 的 ranked_urls，记进 A 的答案
```

现在是**按调用返回**：`search_with_trace()` 在同一次调用里产出 `(results, trace)`，服务层不再回读共享状态，`search_trace()` 已删除（`test_the_gateway_exposes_no_shared_trace_accessor` 防止它被加回来）。失败路径同样不经过共享状态——`ResearchSearchUnavailable.search_trace` 带着本次尝试的 trace。

这不是理论风险。用旧实现跑确定性负控脚本（A 搜索、B 搜索、再读 A 的证据）：

```
A results: ['https://alpha.example/1']
A trace read after B search: ['https://beta.example/2']
contaminated: True
```

### 五条链路契约

1. **结果与 trace 同源**。两者由同一次调用产出，不可能分属不同检索。
2. **success 与 failure 都带 trace**。失败的检索同样要能说明哪些引擎跑过——否则「provider 全挂」和「一个都没调用」在记录里长得一样。
3. **不做检索就不写 trace**。直接 GitHub 链接不是搜索。
4. **网关不保留可回读的 trace**。没有共享状态，就没有跨运行串证据的入口。
5. **没有 `search_with_trace()` 的网关照常工作**。旧适配器与测试替身只是没有该字段——缺证据好过假证据。

### 已知不对称（需在预览时记录）

`merge` 策略只查 Bing 与 DuckDuckGo，`fallback` 在 `WEB_ENABLE_SEARXNG` 打开时会先查 SearXNG。因此两臂的 provider 集合可能不同。这不是本切片的改动范围（E2 定义已冻结为 bing+ddg），但预览运行必须固定并记录 provider 环境变量，且以 trace 里的 `providers_attempted` 为实际发生的事实的准。

### 相邻问题（未在本切片修）

`ResearchWebGateway.warnings()` 仍是共享状态，服务在同一位置回读。它记录的是 provider 错误文本，不是检索证据，风险等级低于 trace；但这与本切片刚修掉的是同一种形状。修它需要动 `warnings()` 的既有调用方，另行授权。

### 离线证据

`tests/test_research_gateway_trace.py`（11 条）：merge 暴露执行细节、默认臂不声称合并、直接 GitHub 链接不产生 trace、网关无可回读访问器、A/B 顺序调用互不污染、A 在 provider 内阻塞至 B 完成后仍保留自己的 trace、失败检索携带 trace、持久化 attempt 带 trace、两个交叠 run 各自持久化自己的证据、默认臂不写该字段、无 `search_with_trace()` 的网关照常工作。

负控：旧实现脚本如上（`contaminated: True`）；旧 API 下新测试因 `search_with_trace` 不存在而全部失败。

影响集：新测试 + 11 个 gateway/search/web_lookup 套件；再加 9 个断言 `query_attempts` 的研究链路套件。

## 非范围（后续切片）

- 四臂运行器本身（`chatgpt` / `current` / `candidate` / `model_direct`）；
- `SendBudget` 三层 scope 与运行器的实际接线；
- 次数耗尽异常从真实聊天入口穿透到运行器的链路级测试；
- 任何真实模型调用或付费执行。
