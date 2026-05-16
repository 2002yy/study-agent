# Study Agent v0.7.7 release notes

> 模块拆分收口版。wechat.py 从 ~1243 行拆为 6 个独立模块，保留兼容层，无功能变更。

---

## 1. 模块拆分总览

旧 `src/wechat.py`（~1243 行）拆为 6 个文件：

| 模块 | 职责 | 行数 |
|---|---|---|
| `src/wechat.py` | 兼容层 + 群聊生命周期、互动回复、开场生成、搜索摘要 | ~540 |
| `src/wechat_format.py` | 纯文本/格式化工具（角色块解析、兜底文案） | ~95 |
| `src/news/link_resolver.py` | Google News 跳转链接解析 | ~90 |
| `src/news/article_fetcher.py` | 正文抓取 + DNS/IP 安全校验 | ~180 |
| `src/news/rss_fetcher.py` | RSS 多源抓取 + 去重 + 排序 + 缓存 | ~280 |
| `src/news/digest.py` | 摘要生成 + 来源块格式化 | ~150 |

## 2. `src.wechat` 仍作为兼容层

- `from src.wechat import fetch_news_items` 等依然可用
- 所有对外接口通过 `# noqa: F401` re-export 保持向后兼容
- `wechat_service.py` 等上层调用方**无需修改**

## 3. RSS 阶段不再逐条 resolve 链接

- `_fetch_rss_items_from_url()` 中 `resolved_link = ""`
- `fetch_news_items(query_text, max_items, resolve_top_n=5)`：
  1. 多源拉取（Google News / Bing News / RSSHub 国内源）
  2. 排序 → 去重 → 截断
  3. 仅对存活条目中前 `resolve_top_n` 条执行 `resolve_news_link()`
- 新增 `resolve_top_n` 参数，便于测试中断言调用次数

## 4. 后续计划（本轮暂停）

- `wechat_store`：群聊文件 I/O、state 管理、archive
- `wechat_generation`：opening、interactive reply、digest discussion
- 以上暂缓拆分，先稳定当前拆分点

---

## 兼容性

- 无新增依赖
- 所有 107 项测试通过
- `test_resolve_news_link_called_only_after_dedup` 保证 resolve 次数 ≤ resolve_top_n
- `.claude/` 已加入 `.gitignore`
