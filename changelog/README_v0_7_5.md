# Study Agent v0.7.5 release notes

> 文档同步收口 + 代码清理 + 小修。

---

## 1. 版本同步收口（v0.7.3 → v0.7.4）

v0.7.4 发布后版本字段未在所有文件中同步。本次补齐：

- `memory/summary.md` / `memory/progress.md` / `memory/agent.md` — 当前阶段与版本历史
- `memory/current_focus.md` — 优先任务描述与"不要误动" guardrail
- `memory/index.md` — release_note 路径
- `PROJECT_PLAN.md` / `FUTURE.md` — 新增 v0.7.4 完成章节，v0.7.5 目标
- `COMPREHENSIVE_PROJECT.md` / `USER_GUIDE.md` / `README_internal_modes.md` — 版本引用

## 2. 死代码清理

- 删除 `src/llm_client.py` 中 `chat_stream()` 死代码（无调用方的空包装）
- 消除 `memory.py` / `wechat.py` 中重复的 `_file_signature()` 定义，抽取到 `text_utils.py`
- 合并 `memory.py` / `context_builder.py` 中重复的 `CONTEXT_FILE_GROUPS` / `MEMORY_SELECTION` 配置字典

## 3. 修复与优化

- **YAML 同步 I/O 优化**：`load_runtime_modes()` 不再每次读 3 个 MD 视图文件，改为通过 YAML mtime canary 仅在变更时检查
- **`_display_*` 辅助函数合并**：4 个重复模式的函数合并为通用 `_display(key, value)`
- **`st.rerun()` fallback 去重**：`_rerun_wechat_fragment` / `_rerun_app` 统一为单函数
- **缓存清理函数合并**：`_prune_news_cache` / `_prune_article_cache` 提取为共用 `_prune_cache()`

---

## 验证

```
108 passed
ruff check . — all checks passed
```
