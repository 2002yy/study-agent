# Research Quality Eval Fixtures（RQCE-P0-C1 冻结格式 / C2 交付陷阱题）

> 格式由 RQCE-P0-C1 冻结；**20 个陷阱 case 已由 RQCE-P0-C2 交付**：
> `frozen_trap_cases.json`（10 个 frozen，含合成 corpus）+
> `live_trap_cases.json`（10 个 live metadata-only）。
> 本目录不得存放 live web 抓取内容；corpus 全部为合成测试数据。
> P0-C5 曾使用真实公开问题进行一次性网页观测；该历史观测脚本和报告已退役。
> 保留的 live metadata 只用于当前明确引用它的测试，不保存网页正文。

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

## Browser Bakeoff Manifest（历史归档）

P2-A3-0 的六类浏览器候选对比仅供旧资格工具使用。资格脚本、结果合同、
专属测试和冻结 manifest 已在 2026-11-19 成组退役；原始合同与实验事实保留于
Git 历史及 `docs/archive/`，不再作为当前阶段门或可运行的测试夹具。
现行浏览器安全与读取预算由 `test_browser_honesty.py`、
`test_crawl4ai_specialist_integration.py`、`test_chain_executor.py` 等直接覆盖。
