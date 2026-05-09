# Study Agent v0.7.0 检查包说明

> 当前版本仍属于自用检查包，不是正式对外发布版。  
> 本版本重点是把微信群联网检索能力从“能查新闻”推进到“可输入主题、可尝试读取页面文本、可追溯来源、可降级运行”的阶段，同时继续收口打包安全、运行体验与状态稳定性。

---

## 1. 版本目标

v0.7.0 主要围绕微信群联网能力与工程稳定性继续推进，重点包括：

1. 微信群支持用户输入查询词进行联网检索。
2. 联网检索支持尝试读取页面文本。
3. 页面文本读取失败时自动降级为标题、来源、时间摘要。
4. 搜索来源写入群聊记录，便于后续回看与追溯。
5. 搜索能力从单一 Google News 扩展为多源聚合。
6. 增强页面读取安全边界，避免访问本地或私有地址。
7. 排除替换文件夹等非运行产物，保持检查包干净。
8. 继续保留 v0.6.x 的打包安全、写盘稳定和刷新体验优化。

---

## 2. 本版本核心改动

### 2.1 微信群联网检索进入 v0.7 阶段

此前微信群主要支持固定入口：

```text
聊最近新闻
```

其底层默认查询较固定：

```text
最新新闻 when:1d
```

v0.7.0 中，微信群已经支持用户主动输入查询内容，例如：

```text
OpenAI 最近进展
Godot 4.6
RTX 5050 笔记本
国内 AI 芯片
美联储 利率
某个技术名词
```

当前真实流程：

```text
用户输入查询词
↓
多源 RSS 聚合搜索
  - Google News
  - Bing News
  - 部分国内 RSSHub 新闻源
↓
提取标题、来源、发布时间和链接
↓
可选：尝试读取前几篇页面文本
↓
生成搜索摘要
↓
生成微信群讨论
↓
将来源块和群聊讨论写入群聊记录
```

当前能力定位：

```text
轻量新闻 / 资讯检索
```

它不是完整网页搜索引擎，也不是全文爬虫系统。

### 2.2 新增页面文本增强层

v0.7.0 在原来的标题摘要基础上加入“页面文本增强”：

```text
RSS 搜索结果
↓
尝试读取前几篇页面文本
↓
读到页面文本：用页面文本增强摘要
读不到页面文本：回退到标题、来源和时间
```

该功能通过以下函数实现：

```text
fetch_article_text()
enrich_news_items_with_article_text()
ArticleTextExtractor
```

当前真实页面读取边界：

```text
最多读取前 5 篇
单篇请求 timeout = 8 秒
单篇 HTML 最大读取 350KB
单篇页面文本最多保留 5000 字
页面读取结果缓存 30 分钟
页面缓存上限 32 条
页面读取失败不会中断整轮群聊
```

这保证了“尝试读取页面文本”是增强能力，而不是硬依赖。

### 2.3 页面读取失败自动降级

新闻站点可能存在：

```text
反爬
跳转页
JS 动态加载
付费墙
地区限制
页面混入导航栏
连接超时
```

因此 v0.7.0 的设计是：

```text
页面文本能读到 → 用页面文本增强摘要
页面文本读不到 → 使用标题、来源、发布时间和链接谨慎总结
```

不会出现：

```text
某篇页面读取失败
↓
整轮联网搜索失败
```

每条搜索结果会带有状态，例如：

```text
已读取到页面文本
正文不可用，使用标题与来源
未读取正文，仅使用标题与来源
```

### 2.4 摘要 prompt 增强事实边界

由于搜索结果不一定都有页面文本，v0.7.0 对摘要 prompt 做了边界收紧：

```text
优先依据页面文本摘录总结；
没有页面文本摘录的条目，只能基于标题、来源和时间谨慎概括；
不要假装读取了没有提供的正文；
不要补充搜索结果中没有的信息；
信息不足时要说明边界。
```

这避免模型在只有标题时过度发挥，也让联网摘要更可信。

### 2.5 搜索来源写入群聊记录

此前搜索来源主要保存在：

```text
st.session_state.wechat_news_items
st.session_state.wechat_news_digest
```

页面刷新或重启后，群聊讨论仍在，但来源可能丢失。

v0.7.0 中新增来源块写入：

```text
format_news_source_block()
append_system_group_note()
```

搜索后会在群聊记录中写入类似内容：

```text
【联网检索】
查询：OpenAI 最近进展
1. 标题 | 来源 | 时间 | 正文状态
   链接
```

当前真实代码中，来源块最多写入 10 条搜索结果。

### 2.6 系统来源块避免内容粘连

`append_system_group_note()` 已调整为独立段落写入，避免来源块直接粘在上一条群聊内容后面。

```text
如果群聊文件已有内容
↓
先补空行
↓
再写入【联网检索】来源块
```

这样 `chat/wechat_group.md` 的结构更清楚，也更方便后续解析和人工查看。

### 2.7 搜索结果条数与页面读取策略

当前真实代码中：

| 项目 | 当前值 |
|------|--------|
| 最大新闻条数 | 10 |
| 最多读取页面文本条数 | 5 |
| 单条页面文本最大长度 | 5000 |

这意味着系统会先尽量抓够 10 条新闻结果，再只对其中前 5 条尝试读取页面文本。

### 2.8 普通“聊最近新闻”与自定义搜索的当前状态

UI 中目前有两个入口：

| 入口 | 当前行为 |
|------|---------|
| 聊最近新闻 | 直接拉起默认查询，并按当前代码尝试读取页面文本 |
| 联网查点什么 | 用户输入查询，并可手动选择是否尝试读取页面文本 |

需要注意：

当前真实代码里，“聊最近新闻”仍然传入 `read_articles=True`，所以它并不是真正的“纯轻量模式”。  
这仍是后续可继续优化的点。

### 2.9 页面读取 URL 安全增强

v0.7.0 对 `_is_fetchable_article_url()` 进行了增强，使用 `ipaddress` 进行判断，避免访问本地地址、私有地址或特殊地址。

拦截范围包括：

```text
localhost
127.0.0.1
0.0.0.0
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
169.254.0.0/16
loopback
private
link-local
reserved
unspecified
multicast
IPv6 local / loopback
```

当前页面读取主要使用 RSS 返回的链接，风险较低，但这层限制为后续扩展“用户直接输入 URL”提前打基础。

### 2.10 页面编码解码增强

部分中文站点不是 UTF-8，而可能是：

```text
GBK
GB2312
GB18030
```

v0.7.0 中新增 `_decode_html_payload()`：

```text
优先从 Content-Type 解析 charset
有声明时：声明编码 → utf-8 → gb18030
无声明时：gb18030 → utf-8
只有解码结果非空时才算成功
```

这让部分中文网页的页面文本提取更稳。

### 2.11 打包排除替换文件夹

此前检查包中曾误带入：

```text
article_text_replacement_files_v069/
```

其中包含旧替换文件，容易造成维护混淆：

```text
包里出现两份 wechat.py / wechat_panel.py
↓
不知道哪个才是正式运行文件
```

v0.7.0 在打包 helper 中增加排除规则：

```python
if parts_lower and parts_lower[0].startswith("article_text_replacement_files"):
    return True
```

避免替换文件夹、临时修复包、辅助替换目录进入检查包。

---

## 3. 延续的 v0.6.x 工程收口

### 3.1 打包安全继续保留

当前打包脚本继续排除：

```text
.env
.env.*
logs/
backups/
exports/
chat/archive/
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.tmp
.docx
.zip
dist/
build/
release/
article_text_replacement_files*
```

并继续检查：

```text
zip 内部路径是否统一为 /
是否包含疑似真实 API Key
是否误带运行时产物
是否误带替换文件夹
```

### 3.2 safe_writer 写入稳定性继续保留

继续保留：

```text
唯一 tmp 文件
replace retry
finally 清理 tmp
backup_file read retry
```

并且 `session_logger` 当前也已经改为通过 `safe_write_text()` 落盘，减少 Windows 文件锁问题。

### 3.3 LLM client 支持配置刷新后重建

继续保留：

```text
_client_signature
reset_client()
```

`reload_config()` 后会重置 cached client，确保 `.env` 变化后下一次调用使用新的：

```text
OPENAI_API_KEY
OPENAI_BASE_URL
```

### 3.4 wechat_state 批量写入

继续保留：

```text
_write_keyvalues(path, updates)
```

减少多字段状态更新时的重复写盘，降低按钮卡顿和文件锁风险。

### 3.5 健康检查无副作用

`health_check.py` 继续遵循：

```text
只检查，不创建目录
向上寻找最近存在的父目录判断可写性
```

避免用户只是点健康检查就生成 `logs/` 或 `backups/`。

### 3.6 刷新体验策略继续保留

继续区分：

```text
_rerun_wechat_fragment()
_rerun_app()
```

当前原则：

| 操作 | 刷新方式 | 说明 |
|------|---------|------|
| 刷新群聊 | fragment rerun | 只刷新群聊区域 |
| 发送普通消息 | fragment rerun | 主要影响当前群聊 |
| 引用到记忆候选 | fragment rerun | 当前面板内反馈即可 |
| 标记已读 | full app rerun | 影响未读数量和状态栏 |
| 新群聊 | full app rerun | 影响全局群聊状态 |
| 生成群聊开场 | full app rerun | 影响群聊是否开始 |
| 聊最近新闻 | full app rerun | 写入群聊并影响全局状态 |
| 联网查点什么 | full app rerun | 写入群聊并影响全局状态 |

同时继续使用：

```text
_queue_wechat_notice()
_render_wechat_notice()
```

避免成功提示在 rerun 后消失。

---

## 4. 本版本主要涉及文件

### 4.1 微信群联网与页面读取

```text
src/wechat.py
src/ui/wechat_panel.py
```

主要改动：

1. 支持 `query_text` 搜索。
2. 支持多源 RSS 聚合。
3. 支持尝试读取页面文本。
4. 页面读取失败自动降级。
5. 搜索来源块写入群聊记录。
6. 搜索表单增加“尝试读取正文”开关。
7. 摘要 prompt 增强事实边界。
8. 搜索条数扩展到 10，页面文本读取前 5 条。

### 4.2 打包与安全

```text
tools/package_project.ps1
tools/package_project_helper.py
```

主要改动：

1. 排除 `article_text_replacement_files*`。
2. 保留 `.tmp` / `.env.*` / `exports` / `chat/archive` / `docx` 排除。
3. 保留 API Key 扫描。
4. 保留 zip entry 正斜杠检查。
5. 保留后置 zip 内容安全检查。

### 4.3 文件写入与状态

```text
src/safe_writer.py
src/mode_manager.py
src/session_logger.py
```

当前状态：

1. `safe_writer` 继续负责安全写入。
2. `mode_manager` 批量写入状态。
3. `session_logger` 延迟创建日志目录。
4. `session_logger.flush_current_session()` 和 `save()` 均已走安全写入路径。

### 4.4 配置、缓存与健康检查

```text
src/config.py
src/llm_client.py
src/health_check.py
```

当前状态：

1. `reload_config` 重置 LLM client。
2. `llm_client` 根据配置签名复用或重建 client。
3. `health_check` 不创建运行目录。

---

## 5. 当前测试状态

建议检查命令：

```powershell
python -m compileall -q .
python -m pytest -q
```

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
9. 不包含 `article_text_replacement_files*`
10. 不包含疑似真实 API Key

---

## 6. 建议新增或保留的测试

当前建议继续覆盖：

1. `article_text_replacement_files*` 不进入打包。
2. `append_system_group_note()` 写入前有独立分段。
3. `_is_fetchable_article_url()` 拒绝 localhost / 私有地址。
4. `_decode_html_payload()` 支持声明编码与 fallback。
5. `fetch_article_text()` 读取失败返回空字符串。
6. `enrich_news_items_with_article_text()` 在页面不可用时降级。
7. `enrich_news_items_with_article_text()` 只读取前 5 条页面文本。
8. `_fetch_query_news_items()` 会多源合并、去重并受 `max_items` 限制。
9. `format_news_source_block()` 包含查询词、来源、正文状态。
10. `fetch_news_items()` 按 query 缓存。
11. 版本状态与 `v0.7.0` 文档保持同步。

---

## 7. 当前不作为阻塞项的问题

当前仍是自用检查包，不是正式发布版。以下内容只记录为正式发布前整理项，不作为当前阻塞：

1. 是否清空 `chat/wechat_group.md`
2. 是否重置 `chat/wechat_state.md`
3. 是否清空当前群聊内容
4. `relationship_mode` 是否回到正式默认值
5. 初始聊天状态是否完全空白
6. 是否删除所有本地运行痕迹

---

## 8. 当前仍需观察的问题

### 8.1 页面文本提取质量

当前页面读取使用标准库 `HTMLParser`，优点是：

```text
不新增依赖
打包简单
部署轻
```

缺点是：

```text
页面文本提取不如专业库准确
可能混入导航、广告、版权信息、推荐阅读
部分 JS 动态网页读不到正文
```

后续如果需要提升质量，可以考虑：

```text
beautifulsoup4
readability-lxml
trafilatura
```

### 8.2 Google News 链接不一定是原文页

Google News RSS 的链接有时可能是：

```text
中转链接
跳转链接
聚合页
consent 页面
```

当前已通过“页面读取失败降级”兜底，状态文案也已改为“已读取到页面文本”，不再暗示一定拿到真正原文页。

### 8.3 搜索可信度与引用展示

v0.7.0 已经将来源块写入群聊记录。后续可进一步增强：

1. 在 UI 中折叠展示来源
2. 在群聊气泡中将链接渲染为可点击
3. 明确标注“基于标题”还是“基于页面文本摘录”
4. 允许用户点击查看本轮搜索来源
5. 支持清理搜索缓存

### 8.4 搜索按钮重复点击

联网搜索涉及网络请求和 LLM 调用。当前已增加简单 running lock，但后续仍可以继续考虑：

1. 搜索按钮 cooldown
2. 上次搜索结果复用
3. 网络失败时提供本地 fallback 话题
4. 更细粒度的 loading / cancellation 体验

### 8.5 文件写入锁

Windows 文件锁问题已经通过多层方式降低：

```text
safe_writer retry
tmp 清理
backup read retry
批量写入
打包排除 tmp
```

但无法完全消除。后续如果仍然偶发，可以继续考虑：

1. 测试环境和真实 `chat/memory` 目录隔离
2. 状态写入节流
3. 减少 Markdown 文件高频写入
4. 运行时状态迁移到 JSON 或 sqlite

---

## 9. v0.7.0 阶段总结

v0.7.0 的核心意义是：  
微信群从“固定新闻话题”升级为“可输入主题的联网资讯讨论”，并进一步支持“尝试读取页面文本”的增强摘要能力。

本版本完成：

1. 微信群支持用户输入查询词进行联网检索。
2. 搜索结果可尝试读取页面文本。
3. 页面读取失败时自动降级。
4. 搜索来源写入群聊记录，便于回看。
5. 摘要 prompt 明确事实边界，避免假装阅读全文。
6. URL 安全检查增强，阻止本地/私有地址访问。
7. 页面编码解码增强，兼容更多中文站点。
8. 打包排除替换文件夹和非运行产物。
9. 延续 `safe_writer`、`mode_manager`、`llm_client`、`health_check` 等工程收口。

当前版本适合作为 v0.7.0 自用检查包继续测试。

---

## 10. 下一阶段建议

下一阶段可以暂定为：

```text
v0.7.1：联网搜索质量与引用体验增强
```

建议重点：

1. 搜索来源在 UI 中更清晰展示
2. 链接支持点击打开
3. 搜索结果页面文本质量继续优化
4. 搜索按钮增加 cooldown 或更细的运行态管理
5. 搜索失败时提供 fallback 话题
6. 测试环境与真实 `chat/memory` 目录隔离
7. 继续观察 Streamlit rerun 体验
8. 正式发布前再处理初始状态清理
