# 平台 API 读取探测（2026-11-25）

每个平台只做薄读取：复用 `src/web/platform_readers.py` 的 host 分发与网关，
不新增工具、站点池条目或独立读取系统。所有探测免费，无付费模型调用。

## Hugging Face

实现：`huggingface` 分发，`method=huggingface_api`。

- URL 形态：`/{owner}/{name}`（模型）、`/datasets/{owner}/{name}`、`/spaces/{owner}/{name}`；
  `papers`、`blog`、`docs` 等保留路径交回普通读取。
- 元数据：`/api/{kind}/{repo}`，取 `pipeline_tag`、`library_name`、许可证（`cardData.license`
  或 `license:` 标签）、下载量、likes、gated/private、创建/修改时间、文件数、标签。
- 模型卡：`/{kind}/{repo}/raw/main/README.md`，截断 20k。
- 讨论：`/api/{kind}/{repo}/discussions?p=0`，取总数与前 5 条标题/评论数；失败不影响主读取。
- 所有请求共享一个截止时间。

| 样本 | 结果 |
| --- | --- |
| `microsoft/phi-2` | 8,290 字，12.6 s；license mit，186,898 downloads，3,540 likes；卡片已含 |
| `datasets/rajpurkar/squad` | 8,570 字，11.1 s；license cc-by-sa-4.0；讨论 21 |
| `Qwen/Qwen3-8B` | 17,481 字，10.4 s；license apache-2.0；讨论 43 |

边界：

- 只读公开仓库；gated/private 仓库的 API 拒绝按 `platform_failed` 返回，由普通读取/Browse 回退。
- 讨论是可选上下文；该请求失败时结果里不写 `discussions`，不把“没取到”写成 0。
- 不下载权重、不读数据集内容，只取元数据与模型卡。
- 没有新增站点池条目；发现仍走现有搜索引擎。

网关实测：`method=huggingface_api`，证据链 `source=huggingface_api`。

## Lobsters

实现：`lobsters` 分发，`method=lobsters_api`。一次请求 `/s/{id}.json`
同时拿到故事、标签、正文和带 `depth` 的评论列表；不额外抓页面。

- 内容：标题、外链、分数、评论数、标签、提交者与时间、`description_plain`。
- 评论：按 `depth` 缩进，最多 40 条、深度 6；跳过已删除/被审核的评论；
  每条截断 1,200 字。

| 样本 | 结果 |
| --- | --- |
| 当前 hottest 第 1 条 | 3,751 字，10 条评论，5.0 s |
| 当前 hottest 第 2 条 | 469 字，2 条评论，3.6 s |

边界：

- 只识别 `/s/{short_id}`；其余路径交回普通读取。
- 评论是扁平的 `depth` 列表，按顺序渲染，不重建父子树。
- 不访问登录态内容；删除/审核评论不参与证据。

网关实测：`method=lobsters_api`，证据链 `source=lobsters_api`。
