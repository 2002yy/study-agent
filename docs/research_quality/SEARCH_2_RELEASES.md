# Search-2 读取层：GitHub `/releases` 现在真的读 release

> Search-2 探针里 N07（「vLLM 最新 release 是什么」）检索首条已经是 GitHub Releases 页，
> 但读取返回 `kind=repository`（描述 + README + 文件列表），正文里没有 tag、没有日期、没有 release 列表。
> 结果就是「找对了页，仍然答不出」。

## 问题

`parse_github_url()` 把所有 `github.com/{owner}/{repo}/...` 的未知路径都归为 `repository`，
`/releases` 因此走 `_read_repository()`。`GitHubSourceReader` 只区分 file / directory / content，
没有 release 概念。

## 改动

`src/web/github_reader.py`：

1. 新增 release 目标：`/releases`（列表）、`/releases/latest`、`/releases/tag/<tag>`；
   `GitHubTarget` 增加 `tag` 字段（默认空串，向后兼容）。
2. 新增 `_read_releases()`：
   - 列表：`GET /repos/{owner}/{repo}/releases?per_page=5`，取 tag / name / 发布时间 / 是否预发布 / 链接；
   - 指定 tag：`GET /repos/{owner}/{repo}/releases/tags/{tag}`；
   - 输出可读正文：逐条 tag + 日期，末行显式给出 `Latest release: <tag>`；
   - 无 release 时返回 `ok=True` 且正文说明「has no published releases」，不再退回仓库元数据。
3. `read()` 增加 `kind == "releases"` 分派。

刻意**没有**加第二套 HTML/Atom 解析：本机 `github.com` 与 `api.github.com` 都在 6–24 s 量级，
换解析器并不会把延迟降下来，只会多一条维护路径。

## 实测

| 读取 | 结果 | 延迟 |
| --- | --- | --- |
| `github.com/vllm-project/vllm/releases` | `latest=v0.32.0`，5 条 release，含 2026-10-18 | 10.2 / 12.0 s |
| `github.com/astral-sh/uv/releases` | `latest=0.13.6`，含 2026-10-27 | 16.5 s（timeout=10 失败）/ 24.1 s（timeout=20 成功） |

N07 的事实词检查现在能通过（正文含 `vllm`、`release`、`v0.`、`Latest release`）。

**但这暴露了一个新的真实问题**：本机访问 GitHub API 需要 10–24 s，而 Search-2 探针和部分研究路径只给 6–10 s。
也就是说「读取器能读出 release」与「在预算内读出 release」是两件事。可行的处理（另行决定）：
配置 `GITHUB_TOKEN`（提高限额；延迟未必改善）、给 GitHub 读取单独的预算、或对 release 读取使用更短超时 + 明确失败码。

## 验证

- `pytest tests/test_github_release_reading.py tests/test_github_research_tools.py tests/test_direct_github_lookup.py tests/test_github_snapshot.py` → 17 passed
- `ruff check` → clean
- 真实读取：vLLM / uv 两个仓库（见上表）

## 局限

- release 正文只保留 tag/日期/名称，没有抓 release notes 全文；「这次改了什么」仍需读 notes 页。
- 列表只取最近 5 条（`per_page=5`），更早的 tag 需要 `/releases/tag/<tag>`。
- 延迟数据来自单一网络环境，不能外推。
