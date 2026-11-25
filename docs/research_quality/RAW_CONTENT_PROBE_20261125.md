# 原始资料读取探测（2026-11-26）

第一批通用读取：非文章载荷在 `web_read` 内直接渲染，不新增工具。
所有探测免费，无付费模型调用。

## 能读什么

| 类型 | 处理 | method |
| --- | --- | --- |
| Markdown / RST / TXT | 保留原文，超预算加截断标记 | `raw_markdown` / `raw_rst` / `raw_text` |
| CSV / TSV | 标准 `csv` 解析，输出 Markdown 表，引号内逗号不切分 | `table_text` |
| JSON | 能放下时美化；放不下时给深度受限的结构摘要，不做字节截断 | `json_text` |
| JSONL / NDJSON | 逐行解析，报告总行数、解析数、无效行与截断 | `jsonl_text` |
| HTML 表格 | 正文提取后旁路输出 `[tables]` Markdown 表 | 沿用 `local_*` |
| XML | 有界原文输出，供后续 RSS/Atom 解析 | `raw_xml` |

类型识别同时看 Content-Type、URL 后缀和内容开头（HTML 嗅探）。

## 实测（真实 URL，经网关）

| 样本 | 结果 |
| --- | --- |
| `raw.githubusercontent.com/plotly/datasets/master/iris.csv` | `table_text`，1,719 字，表头与行列完整 |
| `api.github.com/repos/psf/requests` | `json_text`，6,671 字 JSON 给结构摘要，未做字节截断 |
| `w3schools.com/html/html_tables.asp` | `local_trafilatura`，3,468 字，含 `[tables]` 与 Markdown 表 |
| `raw.githubusercontent.com/psf/requests/main/README.md` | 本次 HTTP 传输超时，Browse 回退读到 1,500 字，标题与链接结构保留 |

## 表格规则

- 表头、单位、行列一一对应，直接输出 Markdown 表。
- 合并单元格（`colspan`/`rowspan`）**不强行转换**，标注 `table N skipped: merged cells`。
- 行数/列数超限、列数不齐时写明 `showing X of Y rows`、`ragged rows padded`。
- 表格同时保留在正文之后，不依赖 trafilatura 是否保留表格结构。

## 边界

- 只走现有安全传输、解压上限与共享超时；没有新建下载路径。
- JSON 超限时返回结构摘要，不返回半个对象。
- EPUB 与图片仍按 `non_text_resource` 失败；PDF 见下一节。
- 本机 `raw.githubusercontent.com` 的 HTTP 传输间歇超时，Browse 回退可用；读取方法会如实标注。
- 不新增站点池条目、不递归抓取、不调用付费模型。

## 最后一批：PDF、目录、章节、字幕、播客（2026-11-26）

| 能力 | 实现 | method |
| --- | --- | --- |
| PDF 全文 | `pypdf` 提取纯文本，最多 20 页、下载上限 12 MB | `pdf_text` |
| 文档目录 | HTML `h1`–`h3` + 锚点，输出 `[toc]` | 沿用 `local_*` |
| 章节定位 | URL 片段 `#id` 只读该标题及其后续内容 | `section_text` |
| 字幕 | SRT / VTT / ASS 解析，保留时间戳 | `subtitle_text` |
| 播客 RSS | 条目附 `audio=` 与 `transcript=` 链接，不自动转写 | `feed_text` |

### 实测

| 样本 | 结果 |
| --- | --- |
| `arxiv.org/pdf/1706.03762` | `pdf_text`，15 页全部提取，1.7 s |
| `docs.python.org/3/library/asyncio.html` | `local_trafilatura` + `[toc]`，3.1 s |
| 带 `#asyncio.run` 的同一页面 | 锚点未命中时明确写 `section not found; returned the whole page`，不静默 |

### 边界

- PDF 只保留纯文本；表格、图片、公式版式不保留。扫描件无文本层时返回 `pdf_unreadable`。
- 章节定位依赖页面自身锚点；没有锚点时回退整页并标注。
- 字幕只解析文本与时间戳；样式、定位、卡拉 OK 效果忽略。
- 播客只给音频/文字稿链接，不自动下载或转写。
- 独立音频转写需要 SenseVoice 运行时，作为下一小批单独实现。

