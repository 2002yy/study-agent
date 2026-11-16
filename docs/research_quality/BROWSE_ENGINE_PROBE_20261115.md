# Browse 搜索站点小样本实测（2026-11-15）

## 结论与选择依据

**保留 Google 为默认 Browse 搜索；Brave、Bing 作为可手动切换的候选；DuckDuckGo 暂不推荐作为 Browse 默认站点。** 不增加自动逐站轮询，也不改变生产默认的 SearXNG 优先路径。

理由是**同一浏览器、同一查询**的实测可用性、可直接引用的目标网址及前排结果相关度，而非单凭站点知名度或静态 HTML 返回 200。

| 站点 | 官方文档英文题 | 中文社区配队题 | 本轮观察 / 裁定 |
| --- | --- | --- | --- |
| Google | 提取 10 条；SQLite 官方 WAL 文档第 1 | 提取 7 条；TapTap 4.6 当期攻略第 1 | **保留默认**；中文页曾在首次立即提取时为 0，稍后页面渲染完成才提取成功 |
| Brave | 提取 14 条；官方 WAL 文档第 1 | 提取 20 条；TapTap 4.6 当期攻略第 1 | **保留手动候选**；标题实际是 `.search-snippet-title`，不是 `h3` |
| Bing | 提取 10 条；官方 WAL 文档第 1 | 提取 10 条；TapTap 4.6 当期攻略第 1 | **保留手动候选**；Edge 中从 `www.bing.com` 跳到 `cn.bing.com`；中文前排还混有旧版攻略 |
| DuckDuckGo HTML | 人机图片挑战；0 条可用结果 | 因前一题要求人机操作，未继续 | **不推荐默认**；不得自动完成验证或绕过挑战 |

## 条件、样本与可复核链接

- **真实浏览器**：用户已连接的 Edge 扩展；按网页实际 DOM 提取，不是模拟浏览器、离线回放或匿名 HTTP 请求。共两题、四个站点；DuckDuckGo 只试第一题。
- 英文题：`SQLite WAL concurrent writers site:sqlite.org`。三个可用站点的首条均指向 [SQLite WAL 官方文档](https://www.sqlite.org/wal.html)。
- 中文题：`星穹铁道 虚构叙事 配队 推荐 当前期`。三个可用站点首条均指向 [TapTap 4.6 攻略](https://www.taptap.cn/moment/861319174629099829)。中文前排结果仍有旧版本内容，**排第一不代表答案已核实**。
- 搜索结果数量指页面中指定选择器匹配的条目，**不是**真实可阅读页面数，也不是完整相关性评分。搜索有个性化、地区、动态加载与反爬影响，不能据此推断长期成功率。
- **对照条件**：之前独立的匿名 HTTP 检索八题中，现有 DDG HTML 路径仅 2/8 成功、6/8 遭遇反爬；Bing RSS 仅 1/8 返回结果。这些与上述**真实浏览器路径不是同一接入方式**，不可混算成功率。
- **尚未证明**：本执行环境没有配对的 `browse` CLI，因此没有跑通 `src/web/browse_search.py` → CLI → 页面 → 工具调用的完整链路。单元测试证明结构与错误处理，不代替该端到端验收。

## 落地：只保留一个开关

```env
WEB_SEARCH_STRATEGY=browser_first
WEB_BROWSE_SEARCH_ENGINE=google
```

`WEB_BROWSE_SEARCH_ENGINE` 可取 `google`、`brave`、`bing`、`duckduckgo`；不设置时沿用 Google。它**只控制现有的单个 Browse 入口**，不创建额外的回退链；遭遇人机挑战按既有策略立即停下。

在用户本机已配对 Browse 的环境，以冻结题集复核：

```powershell
python tools/probe_browse_engines.py --case-ids A01,A05
```

比较时至少记录每站 ①成功/挑战/超时，②结果数量及目标网址，③首条是否对应问题，④来源能否被 `web_read` 真正读到。只有真实使用多次验证后，才考虑改变默认策略。

## 2026-11-15 合并到站点池

本记录的证据（Brave 标题在 .search-snippet-title、Bing 会从 www.bing.com 跳到 cn.bing.com 并把部分出站链接包进 /ck/a、DuckDuckGo HTML 走人机校验）已并入 src/web/browse_search.py 的单引擎适配器：

- search_browse(query, limit, timeout, engine=...)，引擎表 _ENGINES 保存 endpoint/选择器/标签；WEB_BROWSE_SEARCH_ENGINE 只影响未显式指定引擎的调用。
- Bing /ck/a?u=a1... 在引用前解开并重新做公网校验；跳转出引擎结果页即视为不可信。
- 四个通用引擎改为 site_pool 的 dapter，由 rowse_sites 策略按问题选择，不再有第二套独立入口。
- 2026-11-15 复测（同一问题）：Google 5 条、Bing 5 条、Brave 5 条有效结果；DuckDuckGo 在 25 秒超时下返回 rowse:human_action_required，因此保持默认关闭。
