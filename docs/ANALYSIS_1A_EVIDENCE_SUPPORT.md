# Analysis-1A：claim 级证据定位与语义支持（设计合同，暂不实现）

> 目的：让 Study Agent 在**保持证据可核验**的前提下，能够用改写、归纳和推理回答问题，
> 而不是只能逐句复述来源。
>
> 本文只冻结接口与判定责任，不含实现代码。

## 1. 现状与问题

`#321` 把普通网页读取的自动支持资格收紧为**完整来源原句逐字等价**。
这个选择对发布安全是正确的：它只证明"页面这样写过"，不宣称语义蕴含。
代价是：合理的改写、归纳、跨句合并，都会因为"不是原句"被拒绝。

真正缺的不是"更聪明的句子匹配"，而是三层能力的分离：

| 责任 | 谁来做 | 能授予什么 |
| --- | --- | --- |
| 证据**定位**（claim → 正文片段） | 程序 + 模型候选 | 无（只是候选） |
| 出处**核验**（片段确实来自本轮读取的正文） | 程序（哈希/位置/身份） | 仅"原文存在" |
| **语义支持判断**（支持/反对/不足） | 模型 + 确定性 gate | 支持资格（在出处核验之后） |
| **发布资格** | 现有 binder + 发布校验 | 能否回答 |

不能把任何一层的结果直接当成事实被证明。

## 2. 数据契约

### 2.1 候选片段（定位层的输出，未经核验）

```jsonc
{
  "claim_id": "claim_…",            // 答案分段产生的确定性 claim id
  "claim_text": "利润下降的主要原因是研发投入增加",
  "evidence_id": "tool_read_1",     // 本回合真实来源 id
  "url": "https://…",
  "read_id": "read_…",              // read_evidence 的读取身份
  "content_sha256": "…",            // 当次读取正文哈希
  "span_start": 1204,
  "span_end": 1290,
  "span_text": "研发费用增加导致净利润下降"
}
```

定位层可以给出多条候选；它**不**判断支持与否。

### 2.2 出处核验结果（程序，确定性）

```jsonc
{
  "candidate": { … },
  "verified": true,
  "reason": ""                       // 或 span_not_in_body / hash_mismatch /
                                     // read_identity_mismatch / url_mismatch /
                                     // span_out_of_bounds
}
```

规则（全部必须成立）：

1. `evidence_id` 属于本回合 `research_evidence_refs`；
2. 该来源在 `read_evidence` 中有 `status=read` 的记录，且 `content_sha256`
   与本回合保存的正文一致；
3. `span_text` 是**该正文**的子串，且 `[span_start, span_end)` 与实际位置一致；
4. URL / 读取身份未被替换或截断（来源身份与正文身份同源）。

核验只回答"这段原文确实存在"，**不**授予支持资格。

### 2.3 语义判断（模型，逐 claim）

```jsonc
{
  "claim_id": "claim_…",
  "candidate_id": "…",               // 指向上面已核验的片段
  "verdict": "supports | contradicts | insufficient",
  "evidence_span": "研发费用增加导致净利润下降",  // 必须是已核验片段内的原文
  "reason": "一句话，说明支持/反对的具体关系"
}
```

约束：

- 每个 factual claim 必须至少有一个判断；没有判断 = `insufficient`；
- `evidence_span` 必须落在已核验片段内，否则该判断作废；
- `contradicts` 优先于 `supports`：同一 claim 有一个已核验的反对片段时，不得按"已支持"发布；
- 多个来源相互矛盾且都通过核验 → 该 claim 记 `unresolved_conflict`，不得作为确定结论发布。

### 2.4 进入现有 binder 的行

只有 `provenance.verified == true` **且** `verdict == supports` 的片段才允许生成支持行：

```jsonc
{
  "evidence_id": "tool_read_1",
  "claim_id": "…",
  "title": "…",
  "url": "…",
  "relation": "supports",
  "strength": 0.7,
  "locator": "span:1204-1290",
  "anchored_spans": ["研发费用增加导致净利润下降"],
  "grounding_text": "研发费用增加导致净利润下降"   // 只放被核验的片段，不是整页
}
```

`grounding_text` 是有意收窄的：binder 的既有检查仍会执行，但只在**已核验片段**上执行，
不再依赖整页词面重合。

原有"完整原句等价"规则保留给没有经过 Analysis-1A 流程的路径（未核验的行、旧回合、
或模型未给出可核验片段的判断）。这条规则是**降级路径**，不是唯一路径。

## 3. 责任边界（不变量）

1. **模型判断 ≠ 事实证明**：`supports` 只说明"该片段支持该 claim"，不说明来源本身正确。
2. **没有核验片段就没有支持资格**：定位层给出再多候选，未通过 2.2 就不进入 2.4。
3. **反对优先**：任何已核验的 `contradicts` 阻止该 claim 作为肯定结论发布。
4. **矛盾不合并**：两个已核验来源结论相反 → `unresolved_conflict`，不发布一致结论。
5. **不重建系统**：定位复用已保存正文（`read_evidence`），判断复用
   `claim_evidence_assessment` / `evidence_binding` / `evidence_gate`，
   发布复用 `answer_claim_binder` + 发布校验 + `research_evidence_refs`。
6. **不新增研究 Agent、不新增第二套引用评分器**。

## 4. 与现有模块的接口

| 层 | 复用 | 新增的只有 |
| --- | --- | --- |
| 定位 | `read_evidence.normalize_read_result` 保存的正文与哈希 | claim → span 的候选选择（确定性窗口 + 可选模型候选） |
| 出处核验 | `read_evidence` 的读取身份/哈希；`research_evidence_refs` 的 id 归属 | 一个确定性校验函数与错误码 |
| 语义判断 | `claim_evidence_assessment` 的判断契约；`evidence_gate` 的阈值 | 把 verdict 落成 gate 可消费的 link |
| 发布 | `answer_claim_binder`（行结构不变）、发布校验、`evidence_snapshot` | 行里带核验片段与 locator |
| 展示 | B1/B2 的 `citation_links` / `citation_status` | 无 |

## 5. 实现切片（每片独立 PR、独立负控）

| 切片 | 内容 | 负控要点 |
| --- | --- | --- |
| **A1** | 出处核验器：片段 + 哈希 + 读取身份 + 来源归属 | 片段不在正文、哈希不符、来源不在本回合 refs、区间越界 → 全部拒绝 |
| **A2** | claim 级定位：从已读正文为每个 factual claim 选候选片段 | 只提到主题、没有回答事实 → 无候选；同一页为两条 claim 分别定位 |
| **A3** | 判断 → binder 行：`supports` + 已核验片段才生成行 | 反对片段不得生成支持行；改写可过、方向互换不可过 |
| **A4** | 接入发布链并度量 | 证据不足仍拒绝；矛盾来源不发布一致结论 |

每片都要有：先红后绿的负控、静态可复现、零付费（除 A3 的判断可在已有付费准入下、
明确预算后小规模执行）。

## 6. 第一轮验收（不新建大题库）

用已保存的正文构造 7 类对照：

| # | 类型 | 预期 |
| --- | --- | --- |
| 1 | 来源原句与 claim 完全一致 | 允许 |
| 2 | 语义一致、表达不同（改写/归纳） | 应允许 |
| 3 | A 收购 B，claim 写成 B 收购 A | 拒绝 |
| 4 | 收入增长，claim 写成收入下降 | 拒绝 |
| 5 | 正文只提到相关主题、未回答事实 | 拒绝（证据不足） |
| 6 | 引用片段不在实际读取正文中 | 拒绝（出处核验失败） |
| 7 | 两个来源相互矛盾 | 不得作为一致结论发布 |

**指标（必须一起看）**：

- **支持判断准确率** = 判断正确的 claim 数 / 被判断的 claim 数；
- **充分证据通过率** = 有充分证据时被允许发布的回答数 / 该类回答总数。

只降拒答率、或只提准确率，都不算进步。

## 7. 非范围

- 不重写 `bind_answer_claims` 的判定逻辑（只喂给它更可信的输入）
- 不改检索与读取预算
- 不引入新的引用数据结构和第二套评分器
- 不覆盖 Deep 档的 claim-engine 路径（它已有 Evidence Gate）
- 不在本设计内做付费对照实验；需要时单独给预算
