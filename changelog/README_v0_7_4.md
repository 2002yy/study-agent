# Study Agent v0.7.4 release notes

> 工程体验收口：自动化版本管理、LLM 配置透明化、来源可信度 UI。

---

## 1. 自动化版本 bump 工具

- 新增 `tools/bump_version.py`
- 用法：`python tools/bump_version.py v0.7.5`
- 自动读取 `config/runtime_state.yaml` 的 current/next，计算新 next，同步更新 7 个文件：
  - `config/runtime_state.yaml`
  - `memory/internal_state.md` / `memory/index.md`
  - `src/mode_manager.py`
  - `tests/test_packaging_guards.py` / `tests/test_mode_manager_yaml.py`
  - `README.md`（仅 next 版本号，历史条目不碰）
- 从此告别"Release 是 x.y.z 但运行态还写 x.y.z-1"

## 2. LLM 客户端配置文档化

- `.env.example` 从 7 行扩展至 50 行
- 覆盖所有 5 个 provider：DeepSeek / OpenRouter / SiliconFlow / Local / OpenAI
- 每个 provider 的 env var 模式化：`{PROVIDER}_API_KEY`, `_BASE_URL`, `_MODEL_FLASH_NAME`, `_MODEL_PRO_NAME`
- 全局默认值：`LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_MAX_TOKENS`
- 任务级覆盖：`LLM_ROUTER_MAX_TOKENS=240`, `AFTER_SESSION_MAX_TOKENS=1200`
- `README.md` 环境配置节重写为 4 小节：Provider 选择 / 全局默认值 / 任务级覆盖 / 解析链

## 3. NewsRoundResult 结果对象化

- `NewsRoundResult` 新增 4 个字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_block` | `str` | 格式化来源块文本 |
| `article_coverage` | `dict` | 结构化覆盖率（total/with_text/title_only/unresolved_transit/failed_fetch） |
| `elapsed_ms` | `int` | 整轮耗时 |
| `warnings` | `list[str]` | 可读警告 |

- 新增 `_compute_article_coverage()` 按 `article_status` 分类统计
- 新增 `_collect_warnings()` 生成可展示的覆盖率警告

## 4. UI 来源可信度展示

- `_render_news_digest()` 增强：
  - 覆盖率条（绿色 >=50% / 红色 <50%）：`:green[正文覆盖率 8/10 (80%)] | 耗时 2340ms`
  - `st.warning` 逐条展示警告：
    - `只有 3/10 条读到正文，7 条为标题级线索`
    - `2 条 Google News 原文链接未解析`
  - 条目图标区分：📄 已读正文 / 📰 仅标题
- `_run_news_round()` 将 `article_coverage` / `warnings` / `elapsed_ms` / `source_block` 写入 session_state

## 5. 版本同步收口

- 统一将 current 设为 `v0.7.3`，next 设为 `v0.7.4`
- 同步涉及 15 个文件：runtime_state、memory/、src/、tests/、README 等所有文档

---

## 验证

```
108 passed
ruff check . — all checks passed
```
