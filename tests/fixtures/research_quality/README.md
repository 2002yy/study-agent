# Research Quality Eval Fixtures（RQCE-P0-C1 冻结格式 / C2 交付陷阱题）

> 格式由 RQCE-P0-C1 冻结；**20 个陷阱 case 已由 RQCE-P0-C2 交付**：
> `frozen_trap_cases.json`（10 个 frozen，含合成 corpus）+
> `live_trap_cases.json`（10 个 live metadata-only）。
> 本目录不得存放 live web 抓取内容；corpus 全部为合成测试数据。
> P0-C5 已将 live metadata 改为真实、可长期复核的公开问题；真实运行只把
> bounded provider/search/read metadata 写到
> `docs/research_quality/P0_LIVE_OBSERVATION.json`，不把网页正文写回 fixture。

## 文件格式

每个 fixture 文件是一个 JSON 对象，带强制 `schema_version`：

```json
{
  "schema_version": "research-quality-eval-v1",
  "cases": [ ... ]
}
```

- `schema_version` 必须精确等于 `research-quality-eval-v1`；不匹配即 fail-closed 拒绝。
- `cases` 必须是列表；case `id` 在文件内唯一。
- 加载入口：`src.evals.research_quality.load_research_quality_eval_cases(path)`。

## Case 结构

```json
{
  "id": "trap-01",
  "category": "secondary_only",
  "mode": "frozen",
  "gold": { ... },
  "corpus": [ ... ]
}
```

- `category`：冻结 10 类陷阱之一（见下）。
- `mode`：`frozen`（含 corpus，可离线重放）或 `live`（只有 metadata，跑真实 web）。
  - `frozen` 必须至少 1 个 corpus 文档；`live` 必须 0 个。

## Gold 合同（8 字段）

Gold 不写固定文章，只描述"正确闭环需要什么"：

| 字段 | 类型 | 约束 |
|---|---|---|
| `question` | string | 非空，<=2000 字符 |
| `critical_surfaces` | string[] | 非空，去重排序，<=12 项 |
| `expected_claims` | object[] | 非空；`{surface, kind, priority}`，surface 去重 |
| `required_source_roles` | string[] | 非空；5 个冻结角色子集：`primary` / `authoritative_secondary` / `independent_secondary` / `community` / `aggregator` |
| `primary_exists` | bool | 必填 |
| `known_conflicts` | object[] | 可选；`{description, surfaces}` |
| `freshness_requirement` | object | 可选；`{max_age_days, requires_dated_evidence}` 至少一项有效 |
| `forbidden_closure_conditions` | string[] | 可选；7 个冻结条件（见下） |

`expected_claims.kind`：`research_question` / `hypothesis` / `factual` / `analytical`；
`priority`：`critical` / `major` / `context`（与 A1 合同一致）。

### 冻结的 7 个 forbidden_closure_conditions

| 条件 | 语义 |
|---|---|
| `primary_not_read` | primary 未成功正文读取即闭环 |
| `independent_sources_below_minimum` | 独立来源簇低于最小值 |
| `conflict_unresolved` | 已知冲突未解决即闭环 |
| `freshness_unmet` | 新鲜度不满足 |
| `snippet_only_evidence` | 仅 snippet/candidate 证据闭环 |
| `extraction_failed` | 读取/抽取失败仍闭环 |
| `question_unverifiable` | 问题不可验证（仅限 `unanswerable_unverifiable` 类） |

## 冻结的 10 类陷阱（RQCE-P0-C2 使用）

`secondary_only` / `duplicate_source` / `old_primary` / `conflicting_primary` /
`no_primary_exists` / `community_opinion` / `numerical_original_source` /
`causal_competing_explanations` / `simple_factual` / `unanswerable_unverifiable`

## 类别交叉校验（schema 层强制）

- `no_primary_exists` => `primary_exists=false` 且 `required_source_roles` 不得含 `primary`。
- `unanswerable_unverifiable` <=> `forbidden_closure_conditions` 含 `question_unverifiable`（双向）。
- `conflicting_primary` => `known_conflicts` 至少 1 条。
- `old_primary` => 必须声明 `freshness_requirement`。

## Corpus 文档结构（frozen 模式）

```json
{
  "doc_id": "doc-a1",
  "url": "https://example.test/release-notes",
  "title": "Official release notes",
  "source_role": "primary",
  "cluster_id": "cluster-official",
  "published_at": "2026-01-15",
  "content": "..."
}
```

- `cluster_id` 表示独立性家族：同 cluster 的多个 URL 视为同一独立来源簇
  （`duplicate_source` 类依赖此字段模拟转载/镜像）。
- `published_at` 可选；必须是 ISO-8601 日期（`YYYY-MM-DD`）。
- `content` 非空、<=100000 字符；url/title 为模拟环境文本，不做网络访问。
- corpus 保持文件内声明顺序（有序环境定义，不排序）。

## 边界（C1/C2 冻结）

- 本 schema 不含 runner、metrics、live web 访问或任何 WebLookupService 集成。
- `to_dict/from_dict` JSON-safe round-trip；未知字段、未知枚举、重复 ID 均拒绝。
- C2 的 live case 只是 metadata 定义；真实 live web 运行属 RQCE-P0-C3/C4。
- P0-C5 的 live observation 不调用模型、不生成 shadow decision；semantic
  claim/evidence projection 必须另过 external-model authorization gate。

## Browser Bakeoff Manifest（P2-A3-0 冻结，schema `browser-bakeoff-manifest-v1`）

> `browser_bakeoff_manifest.json` 是 P2-A3 browser backend 对照实验的**合同**，
> 不是评测 corpus。它由 `src/web/research/browser_bakeoff.py` 生成并校验；
> 手写容易与合同漂移，因此**修改合同后必须重新生成**。

- 顶层字段：`schema_version` / `bakeoff_version` / `frozen_at` /
  `candidate_backends`（必须精确等于 `["wigolo_browser", "crawl4ai"]`）/
  `budget`（必须精确等于统一预算）/ `provenance_requirements` / `classes`。
- `classes` 必须**恰好**是 6 个冻结类，顺序固定：`static_control` /
  `js_shell` / `spa_delayed_render` / `anti_bot` / `session_required` /
  `document_heavy`。
- 每个类必须声明 `capability_demand`（⊆ 冻结能力词表，且等于合同）、
  `expected_routing`（∈ 冻结 action 词表）、`expect_browser_call`、
  `success_definition`（等于合同）、以及 ≥1 个 `targets`。
- `targets[].kind` ∈ `public_url` | `synthetic_local`；url 必须 `http(s)://` 且全局唯一。
- **static control guard**：`static_control.expect_browser_call` 必须为 `false`。
  BrowserBackend 不仅要证明"能救复杂页"，还要证明"routing 不叫它时不启动"。
- 统一预算**复用** A2 冻结常量（`HTTP_MIN_HARD_SECONDS_DEFAULT` /
  `HTTP_RUN_ENVELOPE_DEFAULT` / `EFFECTIVE_TIMEOUT_FLOOR_SECONDS` /
  `WIGOLO_FETCH_MAX_CHARS`），不重述字面量，保证两侧候选拿到同样的预算。
- 加载入口：`src.web.research.browser_bakeoff.load_browser_bakeoff_manifest(path)`；
  任何违反（schema、预算、能力词表、类集合、control guard、重复 url）均
  fail-closed 抛 `BrowserBakeoffContractError`，不做部分接受。
- 边界：本 manifest 不含 runner、不安装任何 backend、不进入 production chain。
  `crawl4ai` 在 A3-0 期间**未安装、未注册**。
