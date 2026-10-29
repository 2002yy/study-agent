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

## N07 端到端验收（2026-10-29）

问题：**「vLLM 最新版本是什么，什么时候发布？」** 全程真实网络，无模型调用。

| 步骤 | 结果 |
| --- | --- |
| `search_exact`（merge 策略） | 4.05–6.14 s，6 条结果中第 3 条是 `github.com/vllm-project/vllm/releases` |
| `read(url, timeout=20)` | **成功**，12.86–15.88 s，`kind=releases`，`latest=v0.32.0`，日期 `2026-10-18` |
| 交叉核对 `/releases` 列表 | `latest_stable=v0.32.0`，与上一步一致 |
| `read(url, timeout=6)` | **明确失败**：`github_read_timeout`，不再是「10 秒后悄悄成功」 |

明细：`docs/research_quality/SEARCH_2_N07_ACCEPTANCE.json`。

## 版本语义（review 5700500890 修正）

| URL | 之前 | 现在 |
| --- | --- | --- |
| `/releases/latest` | 取列表第一条当最新 | 调 `/releases/latest`（GitHub 排除预发布与草稿），输出 `Latest stable release:` |
| `/releases` | 第一条无条件称 latest | 输出 `Newest release:` 与 `Latest stable release:`，预发布行标 `[prerelease]`；无稳定版时明确说明 |
| `/releases/tag/<tag>` | 称该 tag 为 latest | 输出 `Requested release: <tag>`，不再声称最新 |

## 读取预算（review 5700500890 修正）

- `GeneralWebGateway.read()` 现在把传入的 timeout 作为**整次读取**的预算：GitHub 分支直接使用它，不再先花一轮 official-metadata 探测；
- `GitHubSourceReader.read(..., timeout=...)` → 每次请求的 socket 超时用剩余预算，并且**每 64 KiB 读块后检查截止时间**，所以慢速流式响应也会在预算耗尽时中止；
- 超时 → `github_read_timeout`；GitHub 限流 → `github_rate_limited`（403 + `X-RateLimit-Remaining: 0`，或 429）。

残留限制（必须如实说明）：urllib 的 socket 超时只约束单次操作，实测 6 s 预算在 8.5 s 才被切断。
这是「一个读块的最长等待」造成的，不是预算没有生效：结果已经是明确失败，而不是迟到的成功。

## 验证

- `pytest tests/test_github_release_reading.py tests/test_github_research_tools.py tests/test_direct_github_lookup.py tests/test_github_snapshot.py` → 17 passed
- `ruff check` → clean
- 真实读取：vLLM / uv 两个仓库（见上表）

## 局限

- release 正文只保留 tag/日期/名称，没有抓 release notes 全文；「这次改了什么」仍需读 notes 页。
- 列表只取最近 5 条（`per_page=5`），更早的 tag 需要 `/releases/tag/<tag>`。
- 延迟数据来自单一网络环境，不能外推。
