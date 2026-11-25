# 学术资料读取探测（2026-11-26）

第三批薄适配：一次一个公开 API，复用 `platform_readers.py` 与网关。
所有探测免费，无付费模型调用。

## 能读什么

| 来源 | method | 内容 |
| --- | --- | --- |
| `doi.org` / `dx.doi.org` | `crossref_api` / `datacite_api` | 标题、DOI、作者、发表日期、期刊、类型、许可证、出版商链接、摘要、开放获取位置 |
| `openalex.org/works/W…` | `openalex_api` | 作者、日期、期刊、引用数、参考文献 ID、摘要（由倒排索引重建）、OA 链接 |
| `arxiv.org/abs|pdf/…` | `arxiv_api` | 标题、作者、首次发布/更新日期、摘要、PDF 链接 |
| `zenodo.org/records/…` | `zenodo_api` | 标题、DOI、作者、日期、类型、许可证、描述、文件清单（不下载） |

## 关键区分

每条结果都显式标注：

- `[abstract] … (abstract only; the full text was not read)` —— 摘要不等于读过全文。
- `[full text] not read by this adapter` —— 适配器只取元数据/摘要。
- `[open access] … (not read)` / `[files] … not downloaded` —— 链接和文件存在，不等于内容进入证据。
- Unpaywall 只在配置 `UNPAYWALL_EMAIL` 时查询；未配置时输出 `not checked`，不假装已核验。

## 实测

| 样本 | 结果 |
| --- | --- |
| `doi.org/10.1038/nature12373` | `crossref_api`，506 字，2.4 s |
| OpenAlex `W2159974629` | `openalex_api`，690 字，2.4 s |
| `arxiv.org/abs/1706.03762` | `arxiv_api`，1,521 字，1.9 s |
| 最新 Zenodo 记录 | `zenodo_api`，419 字，2.6 s |

## 边界

- Crossref 404 时回退 DataCite（数据集 DOI）；两者都失败才报 `platform_empty`。
- arXiv 只读 Atom 元数据与摘要，不解析 PDF。
- OpenAlex 摘要来自倒排索引重建，可能与原文标点略有差异。
- 不绕过出版商登录/付费墙；不自动递归下载 PDF。
- 不新增搜索适配器；arXiv 已有站点池条目，其余通过通用搜索发现。
