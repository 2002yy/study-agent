# Browse 搜索站点小样本实测（2026-11-15）

> **历史观测记录，非当前运行手册。** 2026-11-19 已退役只用于本报告
> 小样本重放的 `tools/probe_browse_engines.py`；下方事实保留用于追溯。
> 现行 Browse 搜索通过 `src/web/browse_search.py` 与站点池的生产入口执行，
> 仍需在有授权的真实浏览器环境单独验收，不能以这份旧样本替代。

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

后续若要重新比较站点，应经现行 Browse 搜索入口（而非已经退役的固定
两题探测器）分别记录 ①成功/挑战/超时，②结果数量及目标网址，
③首条是否对应问题，④来源能否被 `web_read` 真正读到。
只有真实使用多次验证后，才考虑改变默认策略。

## 2026-11-15 合并到站点池

本记录的证据（Brave 标题在 .search-snippet-title、Bing 会从 www.bing.com 跳到 cn.bing.com 并把部分出站链接包进 /ck/a、DuckDuckGo HTML 走人机校验）已并入 src/web/browse_search.py 的单引擎适配器：

- search_browse(query, limit, timeout, engine=...)，引擎表 _ENGINES 保存 endpoint/选择器/标签；WEB_BROWSE_SEARCH_ENGINE 只影响未显式指定引擎的调用。
- Bing /ck/a?u=a1... 在引用前解开并重新做公网校验；跳转出引擎结果页即视为不可信。
- 四个通用引擎改为 site_pool 的 dapter，由 rowse_sites 策略按问题选择，不再有第二套独立入口。
- 2026-11-15 复测（同一问题）：Google 5 条、Bing 5 条、Brave 5 条有效结果；DuckDuckGo 在 25 秒超时下返回 rowse:human_action_required，因此保持默认关闭。

## 2026-11-25 复测（browse 0.1.5，Edge 登录态）

- **执行器缺陷**：browse 0.1.5 的 execute 沙箱没有 `URL` 全局，引擎脚本里的
  `new URL(...)` 抛 `ReferenceError`，整条引擎搜索失败（`browse:execution_failed`）。
  通用站点脚本不受影响，因为它的 URL 解析在 `page.evaluate` 里、跑在页面侧。
  修复：引擎脚本改为 `page.evaluate(() => ({origin, pathname}))` 后比较。
- **实测**（同一台机器、已登录 Edge，各 1 次）：
  | 目标 | 耗时 | 结果 |
  | --- | --- | --- |
  | Google | 3.4 s | 有效，前两条为 sqlite.org 官方页 |
  | Bing | 2.7 s | 有效 |
  | 知乎（`needs_login=True`） | 4.8 s | 10 条 question 链接，登录态可用 |
  | B站（公开搜索） | 4.6 s | 40 条视频链接 |
  | DuckDuckGo | 19 s | `browse:human_action_required`，维持关闭 |
  | Brave | 2.8 s | 结果链接全是 `search.brave.com/go/v1#<token>`，真实 URL 不在 DOM |

- **Brave 裁定（已实现解析）**：`/go/v1#` 是跟踪跳转，真实地址不在 DOM。现在改为在
  新标签页逐条打开包装链接、等 URL 离开 `/go/` 后取最终地址，再走公网校验；
  解析失败的条目仍丢弃，包装 URL 永远不会被当引用发布。
  代价实测：3 条结果 18.2 s（约 6 s/条），所以 Brave 只适合手动候选，不应进入默认轮询。
- **稳定性**：Google 偶发 `Detached while handling command`（标签页被 relay 断开），
  同一秒重试即恢复；属基础设施抖动，不是站点拦截，遇到时重试一次即可。
- 单元测试 11 passed，Ruff 通过；本次改 `src/web/browse_search.py`、对应测试与本文档。

### 免费通道实测（2026-11-25，Edge 登录态，各 1 次）

| 通道 | 耗时 | 有效结果 | 状态 / 失败原因 |
| --- | ---: | ---: | --- |
| Google | 7.3 s | 3 | ok |
| Bing | 2.1 s | 0 | `browse:no_results`；页面返回空白（title/body 为空），非登录墙、非验证码，按规则不重试 |
| Brave | 29.9 s | 3 | ok；3 条 `/go/` 包装链接逐条解析，共用一次剩余预算（上限 3 条） |
| 知乎（需登录） | 4.3 s | 3（页面 10） | ok |
| 米游社 | 3.8 s | 3（页面 17） | ok；`/sr/search` + 文章卡片选择器 |

默认路由核对（Brave 已改为 opt-in，不在任何默认路线）：

- `SQLite WAL 并发写入怎么选` → google, reddit, hn
- `原神 配队 推荐` → miyoushe, bilibili, reddit
- `Python 报错 traceback` → stackoverflow, github, google

重试规则：只对 `Detached while handling command` / 标签页断开这类传输故障重试一次；
登录墙、人机验证、权限错误、取消、预算耗尽、正常零结果都不重试。
