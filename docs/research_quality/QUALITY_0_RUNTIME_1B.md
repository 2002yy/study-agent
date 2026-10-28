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
| `providers_attempted` | 实际尝试的引擎，含被环境开关关闭的（后者同时记 `provider_disabled` 错误） |
| `provider_counts` | 每个引擎返回的原始行数 |
| `merged_count` | 合并前总行数 |
| `duplicate_count` | 被去重掉的 URL 数（同一 URL 被两个引擎返回算 1 条） |
| `ranked_urls` | 重排后的最终顺序 |

这些字段从 `_search_single` 经 `search_exact` 一路传到 `search_detailed`，所以运行器在真实调用链上就能拿到证据，而不需要额外埋点。

## 离线证据

`tests/test_web_search_strategy.py`（9 条）：

- 默认策略仍是 `fallback`；未知策略被拒绝；
- **fallback 行为未变**：Bing 有结果时 DuckDuckGo 不被调用，且不出现 merge 字段；
- merge 在第一个引擎有结果时仍查第二个；
- 重复计数、`provider_counts`、重排顺序（更相关的第二引擎结果排到第一）；
- 单引擎失败仍合并另一个，并保留错误；
- 环境开关关闭某引擎时记录 `provider_disabled`，不假装查过；
- trace 能到达 `search_detailed`（变体级 API）。

影响集：`tests/test_web_search_strategy.py` + 10 个 gateway/search/web_lookup 套件 = **80 passed**；`ruff` clean；`mypy` 改动文件无新增错误。

## 非范围（后续切片）

- 四臂运行器本身（`chatgpt` / `current` / `candidate` / `model_direct`）；
- `SendBudget` 三层 scope 与运行器的实际接线；
- 次数耗尽异常从真实聊天入口穿透到运行器的链路级测试；
- 任何真实模型调用或付费执行。
