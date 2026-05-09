# Study Agent v0.6.9 检查包说明

> 当前版本仍属于自用检查包，不是正式对外发布版。  
> 本版本重点是在 v0.6.8 的安全、性能、写盘稳定性基础上，继续扩展微信群的联网检索能力，并进一步收口打包、刷新、状态同步和慢操作体验。

---

## 1. 版本目标

v0.6.9 主要围绕以下方向推进：

1. 为微信群增加"用户输入查什么"的联网检索入口；
2. 将原有"聊最近新闻"从固定新闻查询扩展为可复用的通用资讯搜索链路；
3. 保留 Google News RSS 作为轻量联网入口，不额外引入新依赖；
4. 优化新闻/搜索缓存，避免重复请求；
5. 继续强化打包安全、临时文件排除、状态写入稳定性；
6. 继续改善按钮刷新体验和慢操作提示；
7. 更新测试，覆盖打包、缓存、LLM client、状态写入、微信群搜索等关键链路。

---

## 2. 本版本核心改动

### 2.1 微信群新增"联网查点什么"入口

此前微信群只支持固定入口：

```text
聊最近新闻
```

该按钮内部查询的是固定关键词：

```
最新新闻 when:1d
```

v0.6.9 新增了一个用户可输入查询词的联网检索入口，例如：

- OpenAI 最近进展
- Godot 4.6
- RTX 5050 笔记本
- 遥感变化检测 最新论文
- 新加坡 AI 产业
- 某个技术名词

基本流程：

```
用户输入查询词
↓
Google News RSS 搜索
↓
提取标题、来源、时间、链接
↓
生成搜索摘要
↓
生成微信群讨论
↓
写入群聊
↓
刷新群聊与状态
```

这个功能当前定位为：

> 轻量资讯/新闻检索

不是完整网页搜索引擎，也不是浏览器爬虫。
它适合作为学习 Agent 的第一版联网查询能力。

### 2.2 fetch_latest_news_items() 扩展为通用查询函数

此前新闻抓取函数只支持固定查询：

```python
fetch_latest_news_items(max_items=5)
```

v0.6.9 新增通用函数：

```python
fetch_news_items(query_text: str = "最新新闻 when:1d", max_items: int = 5)
```

旧函数继续保留：

```python
def fetch_latest_news_items(max_items: int = 5) -> list[dict]:
    return fetch_news_items("最新新闻 when:1d", max_items=max_items)
```

这样可以兼容旧的"聊最近新闻"按钮，同时支持新的用户输入搜索。

### 2.3 新闻缓存改为按 query 缓存

此前新闻缓存是单一缓存：

```python
_NEWS_CACHE: tuple[float, list[dict]] | None = None
```

如果引入用户自定义查询，这种缓存会导致不同查询之间互相污染。

v0.6.9 改为按查询词缓存：

```python
_NEWS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_NEWS_CACHE_TTL = 600
```

缓存 key：

```python
cache_key = f"{query_text}|{max_items}"
```

效果：

- 同一个查询词 10 分钟内重复搜索 → 复用 RSS 结果 → 减少网络请求和等待时间
- 不同查询词 → 分别缓存 → 不会互相串结果

### 2.4 _run_news_round() 支持 query_text

此前 `_run_news_round()` 只能组织"最近新闻"群聊。

v0.6.9 中扩展为：

```python
def _run_news_round(progress=None, query_text: str = "最新新闻 when:1d"):
    ...
```

这样旧调用仍然兼容：

```python
_run_news_round(lambda msg: status.info(msg))
```

新增搜索调用可以传入：

```python
_run_news_round(lambda msg: status.info(msg), query_text=query)
```

这个签名设计避免了大面积改旧按钮逻辑。

### 2.5 搜索/新闻慢操作保留分阶段提示

联网检索和新闻群聊会经历多个慢步骤：

1. 搜索资讯
2. 整理摘要
3. 生成群聊讨论
4. 写入群聊

v0.6.9 延续分阶段提示：

- 正在搜索：xxx
- 正在整理搜索摘要...
- 正在生成群聊讨论...
- 正在写入群聊...

用户点击按钮后不会只看到一个长时间 spinner，等待感更明确。

### 2.6 搜索失败增加友好提示

联网搜索可能失败的原因包括：

- 网络不可用
- 代理/VPN 不稳定
- RSS 源无法访问
- 搜索结果数量不足
- LLM 调用失败

v0.6.9 中搜索按钮和新闻按钮继续使用：

```python
try:
    ...
except Exception as exc:
    st.warning(...)
```

失败时不会直接抛出红色堆栈，而是显示用户可读提示。

---

## 3. 延续的 v0.6.8 工程收口

### 3.1 打包排除 .tmp

v0.6.8 已发现 `.tmp` 临时文件可能残留。
v0.6.9 继续保留 `.tmp` 排除规则：

```python
if suffix_lower in (".pyc", ".pyo", ".bak", ".tmp"):
    return True
```

避免以下文件进入检查包：

- `chat/wechat_state.md.xxxxx.tmp`
- `memory/internal_state.md.tmp`

### 3.2 打包排除运行产物

当前打包脚本应排除：

- `.env`
- `.env.*`
- `logs/`
- `backups/`
- `exports/`
- `chat/archive/`
- `__pycache__/`
- `.pytest_cache/`
- `.ruff_cache/`
- `.mypy_cache/`
- `.tmp`
- `.docx`
- `.zip`
- `dist/`
- `build/`
- `release/`

其中 `exports/` 已纳入排除范围，避免导出的报告进入检查包。

### 3.3 打包后置检查增强

除了 `should_exclude()` 的前置排除，打包完成后还会检查 zip 内容，防止未来规则回退。

后置检查包括：

- 反斜杠路径
- `.env` / `.env.*`
- `chat/archive`
- `.tmp`
- `logs/`
- `backups/`
- `exports/`

如果发现异常内容，会直接报错退出。

### 3.4 safe_writer 写入稳定性增强

`safe_writer.py` 继续保留：

- 唯一 tmp 文件
- replace retry
- finally 清理 tmp

并进一步加强备份读取：

```python
_read_bytes_with_retry(path)
```

这样可以降低 Windows 下文件被短暂占用导致的：

```
PermissionError: [WinError 5] 拒绝访问
```

### 3.5 LLM client 支持配置刷新后重建

`src/llm_client.py` 保留：

- `_client_signature`
- `reset_client()`

`src/config.py` 的 `reload_config()` 会尝试调用：

```python
reset_client()
```

这样用户修改 `.env` 后点击"强制刷新"，下一次 LLM 请求会使用新的：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`

### 3.6 wechat_state 多字段更新批量写入

`src/mode_manager.py` 保留：

```python
_write_keyvalues(path, updates)
```

减少多字段状态更新时的重复写盘。

例如：

```python
update_wechat_join_state(...)
```

现在只进行一次文件写入，而不是三次。

### 3.7 健康检查无副作用

`src/health_check.py` 中 `_check_writable()` 保持只读检查：

- 不创建 `logs/`
- 不创建 `backups/`
- 向上寻找最近存在的父目录判断可写性

健康检查不再污染项目目录。

---

## 4. 刷新体验策略

v0.6.9 继续沿用：

- `_rerun_wechat_fragment()`
- `_rerun_app()`

当前原则：

| 操作 | 刷新方式 | 说明 |
|------|---------|------|
| 刷新群聊 | fragment rerun | 只刷新群聊区域 |
| 发送普通消息 | fragment rerun | 主要影响当前群聊内容 |
| 引用到记忆候选 | fragment rerun | 当前面板内反馈即可 |
| 标记已读 | full app rerun | 会影响顶部未读数量与侧栏 |
| 新群聊 | full app rerun | 会影响全局群聊状态 |
| 生成群聊开场 | full app rerun | 会影响是否已入群、群聊状态 |
| 聊最近新闻 | full app rerun | 会写入群聊并影响全局状态 |
| 联网查点什么 | full app rerun | 会写入群聊并影响全局状态 |

同时继续使用 notice queue：

- `_queue_wechat_notice()`
- `_render_wechat_notice()`

避免成功提示在 rerun 后消失。

---

## 5. 本版本主要涉及文件

### 5.1 微信群联网与搜索

- `src/wechat.py`
- `src/ui/wechat_panel.py`

主要改动：

1. 新增 `fetch_news_items(query_text, max_items)`
2. `fetch_latest_news_items` 保留为兼容包装
3. 新闻缓存改为按 query 缓存
4. `_run_news_round` 支持 `query_text`
5. 微信群面板新增用户输入搜索入口
6. 搜索按钮增加分阶段提示和异常兜底

### 5.2 打包与安全

- `tools/package_project.ps1`
- `tools/package_project_helper.py`

主要改动：

1. 排除 `.tmp`
2. 排除 `exports/`
3. 排除 `.env` / `.env.*`
4. 排除 `chat/archive`
5. 排除 `.docx`
6. 后置检查 env/tmp/runtime output
7. zip entry 统一使用 `/`
8. 保留 API Key 扫描

### 5.3 文件写入与状态

- `src/safe_writer.py`
- `src/mode_manager.py`
- `src/session_logger.py`

主要改动：

1. safe_writer 增强 Windows 文件锁 retry
2. safe_writer finally 清理 tmp
3. backup_file 读取原文件时增加 retry
4. mode_manager 批量写入 wechat_state
5. session_logger 延迟创建 logs 目录
6. session_logger.save 走 safe_write_text

### 5.4 配置与缓存

- `src/config.py`
- `src/llm_client.py`
- `src/health_check.py`

主要改动：

1. reload_config 重置 LLM client
2. llm_client 使用配置签名判断是否复用 client
3. health_check 不创建目录
4. health_check 可写判断更准确

### 5.5 UI 与体验

- `src/ui/sidebar.py`
- `src/ui/status_bar.py`
- `src/ui/wechat_panel.py`

主要改动：

1. 强制刷新会清 memory cache
2. 侧栏查看未读会切换到微信群入口
3. 清空未读使用 sidebar_notice
4. 状态栏部分按钮使用 fragment rerun
5. 微信群搜索与新闻按钮使用分阶段提示

---

## 6. 当前测试状态

建议检查命令：

```bash
python -m compileall -q .
python -m pytest -q
```

当前预期：

- `compileall` 通过
- `pytest` 全部通过

建议打包检查：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\package_project.ps1
```

打包结果应满足：

1. zip 内部路径统一为 `/`
2. 不包含 `.env` / `.env.*`
3. 不包含 `logs` / `backups` / `exports`
4. 不包含 `chat/archive`
5. 不包含 `__pycache__` / `.pytest_cache` / `.ruff_cache`
6. 不包含 `.tmp`
7. 不包含 `.docx`
8. 不包含嵌套 zip
9. 不包含疑似真实 API Key

---

## 7. 建议新增或保留的测试

当前建议测试覆盖：

1. `.tmp` 文件不会进入打包
2. `exports/` 不会进入打包
3. `.env.*` 大小写变体不会进入打包
4. `chat/archive` 不会进入打包
5. llm_client 支持 `reset_client`
6. `reload_config` 会重置 cached client
7. `update_wechat_join_state` 使用批量写入
8. `session_logger.init_session` 不创建 logs 目录
9. sidebar 强制刷新会清 memory cache
10. `fetch_news_items` 支持 `query_text`
11. 新闻缓存按 query 区分
12. `_run_news_round` 支持 `query_text` 且兼容旧调用

---

## 8. 当前不作为阻塞项的问题

当前仍是自用检查包，不是正式发布版。
以下内容只记录为正式发布前整理项，不作为当前阻塞：

1. 是否清空 `chat/wechat_group.md`
2. 是否重置 `chat/wechat_state.md`
3. 是否清空当前群聊内容
4. `relationship_mode` 是否回到正式默认值
5. 初始聊天状态是否完全空白
6. 是否删除所有本地运行痕迹

---

## 9. 当前仍需观察的问题

### 9.1 联网搜索能力边界

当前联网能力基于 Google News RSS，因此更适合：

- 新闻
- 资讯
- 近期动态
- 技术事件
- 产品发布
- 公司进展

不适合直接替代完整网页搜索，例如：

- 任意网页全文读取
- 复杂资料比对
- PDF/论文全文解析
- 电商价格实时比价
- 论坛多页爬取

后续如需增强，可以考虑：

1. 增加通用搜索 API
2. 增加网页正文提取
3. 增加搜索结果来源展示
4. 增加引用链接展示
5. 增加搜索结果缓存与历史记录

### 9.2 搜索结果可信度

Google News RSS 返回的是新闻条目。
当前群聊讨论由 LLM 基于标题、来源、时间、链接整理生成。
后续需要注意：

1. LLM 可能过度概括标题信息
2. RSS 标题不等于完整事实
3. 搜索结果来源质量不完全一致
4. 链接目前主要作为记录，不一定完整展示给用户

后续可考虑在群聊中加入：

- 来源列表
- 原始链接
- 发布时间
- "仅基于搜索标题整理"的提醒

### 9.3 Windows 文件锁

v0.6.9 已经通过以下方式降低风险：

1. safe_writer replace retry
2. backup_file read retry
3. finally 清理 tmp
4. mode_manager 批量写入
5. 打包排除 tmp

但 Windows 文件锁无法完全消除。
如果仍然偶发，可以考虑：

1. 测试使用临时目录隔离 chat/memory
2. 状态写入节流
3. 减少 Markdown 状态文件高频写入
4. 运行时状态迁移到 JSON 或 sqlite

### 9.4 Streamlit rerun 体验

当前已经通过以下方式缓解：

1. `wechat_panel` fragment
2. sidebar form
3. fragment rerun 与 app rerun 拆分
4. notice queue
5. 微信群读取缓存
6. 气泡 HTML 渲染缓存
7. 新闻/搜索分阶段提示

后续仍可观察：

1. 全局 rerun 是否仍有明显闪动
2. 搜索按钮是否需要防重复点击
3. 新闻/搜索是否需要 cooldown
4. 状态栏是否需要进一步拆 fragment

---

## 10. v0.6.9 阶段总结

v0.6.9 的核心意义是：
在原有微信群学习陪伴基础上，引入轻量联网资讯检索能力，让群聊可以围绕用户输入的话题展开讨论。

本版本完成：

1. 微信群支持用户输入查询词进行联网检索
2. 原"聊最近新闻"链路升级为可复用搜索链路
3. 新闻缓存按 query 区分，避免搜索结果串用
4. `_run_news_round` 支持 `query_text`，同时兼容旧调用
5. 搜索按钮支持分阶段提示和异常兜底
6. 打包继续排除 tmp、exports、env、docx、archive 等风险内容
7. safe_writer、mode_manager、llm_client、health_check 继续稳定性收口
8. 测试继续覆盖安全、性能与打包防回归点

当前版本适合作为 v0.6.9 自用检查包继续测试。

---

## 11. 下一阶段建议

下一阶段可以暂定为：

**v0.7.0：联网搜索体验与状态隔离增强**

建议重点：

1. 搜索结果在群聊中展示来源与链接
2. 搜索结果缓存可视化或可清理
3. 搜索按钮增加防重复点击或 cooldown
4. 新闻/搜索失败时提供本地 fallback 话题
5. 测试环境与真实 chat/memory 目录隔离
6. 进一步降低状态文件写入频率
7. 正式发布前再处理初始状态清理
