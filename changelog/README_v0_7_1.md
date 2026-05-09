# Study Agent v0.7.1 检查包说明

> 当前版本仍属于自用检查包，不是正式对外发布版。  
> 本阶段重点是继续收口微信群联网搜索质量，降低“旧新闻误判为最新”“标题推断像读过全文”“来源块过长影响聊天体验”等问题。

---

## 1. 当前阶段定位

`v0.7.1` 是在 `v0.7.0` 基础上的继续收口版，重点不再是把联网入口做出来，而是把以下体验拉稳：

1. 搜索结果默认优先近 90 天；
2. 旧新闻只在结果不足时回填；
3. Google News 中转链接优先解析到原文；
4. 正文提取升级为三层回退；
5. 来源块压缩显示，减少群聊占屏；
6. 摘要 prompt 明确正文可用性边界；
7. 侧栏状态、memory 文本与当前打包文档保持一致。

---

## 2. 本阶段关键变化

### 2.1 时间可信度增强

- 搜索结果展示时间改为 `YYYY-MM-DD HH:MM`
- 结果项新增 `published_timestamp`
- 去重与裁剪逻辑不再只是“近期优先排序”，而是：
  - 先保留近 90 天结果
  - 不足时再回填较旧条目

这样用户搜索“最新”时，不会轻易被几个月前甚至更久的新闻混淆。

### 2.2 正文提取升级为三层链路

当前正文提取顺序：

1. `trafilatura`
2. `readability-lxml`
3. 项目内置 `HTMLParser` fallback

并保留现有边界：

- 最多尝试读取页面文本：`5` 条
- 单条页面文本最大保留：`5000` 字
- 单篇请求超时：`8` 秒
- 单篇 HTML 最大读取：`350KB`
- 缓存 TTL：`30` 分钟
- 缓存上限：`32` 条

### 2.3 正文读取候选优先级泛化

页面文本读取候选用 `_article_fetch_priority()` 排序，**不再写死 OpenAI / 语音 / audio 等专题关键词**，改为通用优先规则：

| 规则 | 权重（越低越优先） |
|---|---|
| 中转链接（Google News / Bing News） | +60（大幅降权） |
| 官方/一级域名（openai.com、github.com、python.org 等） | −15 |
| 可信技术媒体（infoq、36kr、dev.to 等） | −10 |
| 标题匹配 query 关键词 | −8/词（上限 −24） |
| 近期文章（2024-2026） | −5 |

同时 `enrich_news_items_with_article_text()` 和调用方加入了 `query_text` 透传，确保搜 `Godot 4.6` 时按“Godot/4.6”匹配，不会偏到音频关键词上。

### 2.4 来源块继续压缩

群聊中的来源块现在改为：

- 短标题
- `来源｜时间｜状态`
- 仅显示域名

例如：

```text
【联网检索】
查询：openai最新语音模型

1. OpenAI 发布新一代实时语音模型...
   来源：OpenAI｜2026-05-08 09:22｜正文已读｜trafilatura
   链接：openai.com
```

完整链接仍保留在内部字段，但不会再用长 URL 挤占群聊正文。

### 2.5 摘要边界继续收紧

摘要前会显式告知模型：

- 本轮总共有多少条结果
- 多少条读到了页面文本
- 多少条只能依赖标题、来源和时间

---

### 2.6 版本身份统一

`v0.7.1` 之前仓库存在三套版本号：包名 `v0.6.9`、计划文档 `v0.7.0`、memory 文档 `v0.7.1`，导致左侧栏“版本”与“当前阶段”不同步。

本轮已将以下文件全部统一为 `v0.7.1`，并在 `memory/current_focus.md` 中登记了**版本同步文件清单**（13 个文件），后续改版本号时逐项对照即可：

- `src/mode_manager.py`（current_version / next_version 默认值）
- `memory/internal_state.md`
- `memory/summary.md`
- `memory/current_focus.md`
- `memory/progress.md`
- `memory/agent.md`
- `PROJECT_PLAN.md`
- `USER_GUIDE.md`
- `COMPREHENSIVE_PROJECT.md`
- `FUTURE.md`
- `README_internal_modes.md`
- `README.md`

### 2.7 `.env.example` 与 `USER_GUIDE.md` 配置对齐

此前 `.env.example` 和 `USER_GUIDE.md` 里的模型配置不一致：

| 字段 | `.env.example`（旧） | `USER_GUIDE.md`（旧） |
|---|---|---|
| `OPENAI_BASE_URL` | `/v1` | *无 `/v1`* |
| `MODEL_FLASH_NAME` | `deepseek-v4-flash` | `deepseek-chat` |
| `MODEL_PRO_NAME` | `deepseek-v4-pro` | `deepseek-chat` |
| `DEFAULT_MODEL_PROFILE` | `pro` | `flash` |

现已统一为：

```text
OPENAI_BASE_URL=https://api.deepseek.com/v1
MODEL_FLASH_NAME=deepseek-v4-flash
MODEL_PRO_NAME=deepseek-v4-pro
DEFAULT_MODEL_PROFILE=pro
```

并明确 **`.env.example` 是唯一准配置**，`USER_GUIDE.md` 仅做镜像引用。

---

## 3. 侧栏与文档状态同步（已收口）

左侧栏“版本 / 当前阶段”现在从 `mode_manager.py` 统一读取 `v0.7.1`，与以下文档一致：

- `memory/summary.md`
- `memory/current_focus.md`（内含版本同步文件清单）
- `memory/progress.md`
- `memory/agent.md`

本次检查包已消除 `v0.6.9` / `v0.7.0` / `v0.7.1` 三套身份并存的问题。

---

## 4. 建议检查命令

```powershell
python -m compileall -q .
python -m pytest -q
powershell -ExecutionPolicy Bypass -File .\tools\package_project.ps1
streamlit run app.py
```

---

## 5. 本阶段重点观察项

1. `openai最新语音模型` 是否仍混入过多旧新闻；
2. 来源块是否明显更短、更易读；
3. 正文已读状态是否能稳定显示提取器方法；
4. 没有正文时，摘要是否仍保持保守边界；
5. UI 左侧栏的“当前阶段 / 当前任务”是否已同步为 `v0.7.1` 话术。
