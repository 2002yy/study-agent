# Study Agent v0.7.2 代码质量收口说明

> 当前版本仍属于自用检查包，不是正式对外发布版。  
> 本阶段重点是对项目做全量代码扫描与优化收口，修复已有 Bug，改善性能和架构。

---

## 1. 当前阶段定位

`v0.7.2` 是在 `v0.7.1` 基础上的代码质量收口版，重点不在功能增量，而是：

1. 修复已发现的 4 个 Bug（含 1 个测试失败、2 个 stale 数据、1 个统计错误）
2. 性能优化（缓存落盘重复读取、YAML 重复解析、diff 算法）
3. 架构改善（常量去重、代码栅栏清理抽公共、文章提取模块独立）
4. Streamlit 反模式修复（fragment 内完整 rerun → scope=fragment）
5. 错误处理增强（关键路径裸 except 加日志、after_session 崩溃保护）
6. 依赖清理

---

## 2. 本阶段关键变化

### 2.1 Bug 修复（P0）

- **测试版本断言 stale**：`test_runtime_version_is_synced_to_v069` 断言 `v0.6.9`，实际已是 `v0.7.1`，改名为 `test_runtime_version_is_synced` 并更新断言值
- **欢迎页硬编码版本**：`chat_panel.py:131` 写死 `v0.6.2 响应速度优化`，改为 `load_runtime_modes().current_version` 动态读取
- **LLM Router 用量统计**：`model_stats.py:109` 无论用 flash 还是 pro 都记录为 flash，修复为接收 `model_profile` 参数
- **死代码删除**：`src/ui/main_panel.py` 从未被调用，已删除

### 2.2 性能优化（P1）

- **`load_runtime_modes()` 缓存**：`src/mode_manager.py` 加 `@st.cache_data(ttl=30)`，同一渲染周期内只读一次文件（之前每次渲染被调用 5+ 次）
- **YAML 路由重复解析**：`router.py` 中 `load_routing_config()` 读一次 YAML，`_match()` 又读一次。修复为 `_match()` 接受预加载 rules 参数，避免重复 I/O
- **diff 算法优化**：`memory_tools.py` diff 从 O(n×m) 嵌套循环改为 set 集合运算

### 2.3 架构改善（P1）

- **公共常量抽取**：`ROLE_LABELS`/`MODE_LABELS`/`MODEL_LABELS` 等原本在 `sidebar.py`/`status_bar.py`/`chat_panel.py`/`wechat_panel.py` 四份文件中重复定义，统一到 `src/constants.py`
- **代码栅栏清理工具**：`strip_code_fences()` 原本在 `llm_router.py`/`after_session.py`/`wechat_memory.py` 三处重复实现，抽取到 `src/text_utils.py`
- **文章提取模块独立**：`wechat.py` 中 `ArticleTextExtractor` 类及 `_extract_article_text_*` 系列函数迁移到 `src/news/article_extractor.py`，`wechat.py` 保留向后兼容的 re-export

### 2.4 Streamlit 反模式修复（P1）

- **wechat_panel fragment 内 rerun**：`wechat_panel.py` 中 8 处 `st.rerun()` 改为 `st.rerun(scope="fragment")`，避免完整页面重刷
- **sidebar fragment 内 rerun**：`sidebar.py` 中 6 处 `st.rerun()` 改为 `st.rerun(scope="fragment")`

### 2.5 错误处理增强（P2）

- **公共日志模块**：新建 `src/log_utils.py`，统一 `logging.getLogger("study_agent")`
- **`after_session.py` 崩溃保护**：LLM 调用加 try/except，失败时返回友好提示而非崩溃
- **关键路径日志**：`router.py`（YAML 加载失败、LLM 路由失败）、`llm_router.py`（chat 失败、JSON 解析失败）、`config.py`（reload 失败）均从静默吞异常改为 WARNING 日志

### 2.6 依赖清理（P2）

- `requirements.txt` 移除 `pytest>=8.0,<9`（应只在 `requirements-dev.txt` 中）

---

## 3. 新增文件清单

| 文件 | 用途 |
|------|------|
| `src/constants.py` | 公共常量字典（ROLE/MODE/MODEL/PERF/ATMOS/ENTRY/WECHAT labels & icons） |
| `src/text_utils.py` | 文本工具（`strip_code_fences`） |
| `src/log_utils.py` | 公共日志 logger |
| `src/news/__init__.py` | news 子包 |
| `src/news/article_extractor.py` | 文章正文提取（HTMLParser + trafilatura + readability 三层回退） |

| 删除文件 | 原因 |
|----------|------|
| `src/ui/main_panel.py` | 死代码，从未被调用 |

---

## 4. 建议检查命令

```powershell
python -m compileall -q .
python -m pytest -q
streamlit run app.py
```

---

## 5. 测试结果

本次改动后全量测试：**72 passed, 0 failed**。
