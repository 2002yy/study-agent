# Study Agent v0.7.6 release notes

> 工程安全与新闻链路收口版。

---

## 1. 加固 `.gitignore` 与打包排除规则

- 新增 `.env.*`、`*.env`、`*.env.*` 模式，确保所有环境变量文件不被纳入版本控制
- 保留 `!.env.example` 为唯一例外

## 2. 修复侧栏 HTML 动态内容转义

- `_section()` 和 `_mini_state()` 中动态拼接的内容（label / value）增加 `html.escape()`
- 全项目 `unsafe_allow_html=True` 检查：`wechat_bubble.py`、`status_bar.py`、`chat_panel.py` 已正确使用 `html.escape()`；`sidebar.py` 补上

## 3. 重构新闻抓取链路

- **RSS 阶段不再 `resolve_news_link()`**：`_fetch_rss_items_from_url()` 只记录原始 `link`，不提前解析跳转
- **先 dedupe/trim，再 resolve 前 5 条**：`fetch_news_items()` 在 `_fetch_query_news_items()` 返回后，只对存活条目调用 `resolve_news_link()`
- 避免在 RSS 解析阶段对大量已淘汰条目做无意义的 HTTP 解析

## 4. 补强 URL 安全边界

- 新增 `_check_dns_target_safe(hostname)`：对非 IP 字面量的 hostname 做 DNS 解析，检查目标 IP 是否为私有/回环/链路本地/组播等不安全地址
- `_is_fetchable_article_url()` 中对非 IP 字面量 host 自动调用 DNS 校验
- `fetch_article_text_with_method()` 通过 `_is_fetchable_article_url()` 获得两层保护

## 5. 修正测试与增强 CI

- **无效 monkeypatch**：`test_enrich_news_items_falls_back_when_article_unavailable` 原来 patch 了 `fetch_article_text`，但被测试函数实际调用 `fetch_article_text_with_method` → patch 目标修正
- **新增性能测试**：`test_resolve_news_link_called_only_after_dedup` 验证 resolve 调用次数不超过存活条目数
- **CI 新增**：
  - 打包验证（`tools/package_project_helper.py`）
  - `detect-secrets` 密钥扫描
  - mypy 范围从 3 个文件扩大至全部 `src/`

---

## 验证

```
107 passed
ruff check . — all checks passed
```
