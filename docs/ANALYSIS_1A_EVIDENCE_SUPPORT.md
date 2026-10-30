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
2. 该来源在本轮保留的读取记录中有 `status=read`，其 `read_id` 与 URL 对应同一次读取；
   **按实际持久化范围**核对内容哈希：现有 `read_evidence` 的 `excerpt_sha256`
   是读取正文**前 3000 字摘录**的哈希，并非任意完整正文的哈希。A1 必须明确
   候选片段定位的权威正文与哈希采用同一可访问、已保存的字节范围；不得用
   12k 正文的偏移量去核验 3k 摘录哈希，也不得假设每种读取工具都保存全文；
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

### 2.4 语义支持如何进入现有 binder（必须先取得服务端资格）

**旧设计的关键错误**：`answer_claim_binder._supported_confidence()` 对任何非空
`grounding_text` 都先执行 `claim_grounded_in_text()` 的**完整原句匹配**；
即便 `relation="supports"`、`strength="strong"`，仅将 `grounding_text` 缩成片段，
仍会拒绝合法改写。**因此不能声称「行结构不改、只换输入即可让改写通过」。**

现有 binder 已有两种真实路径，A3 必须明确选择并保留来源资格：

1. **普通 inline 读取（未获 claim 级资格）**：仍携带非空 `grounding_text`，
   沿用 #321 的完整来源原句等价检查，不授予改写支持权。
2. **经过 claim 级核验、语义支持与冲突门禁的行**：由**服务端**根据
   `read_id/evidence_id/claim_id/片段位置/哈希/verdict` 建立只读的资格记录，
   且仅在同一 claim 没有任何已核验反对/未决冲突、Gate 允许发布时才投影；
   复用现有 `research_binding_rows` 的「上游已核验正向关系」约定，
   将 `grounding_text=""` 交给 binder 既有 `_positive_support_confidence()` 分支。
   **不能直接相信模型输出的 `supports` 标签**，也不能把读取成功标成 strong。

只读投影的示例（此处**不是**模型可直接提交的行）：

```jsonc
{
  "evidence_id": "tool_read_1",
  "claim_id": "…",                  // 必须与实际待发布事实对应
  "title": "…",
  "url": "…",
  "relation": "supports",
  "strength": "0.7",               // binder 的 strength 字段是字符串
  "locator": "span:1204-1290",
  "anchored_spans": ["研发费用增加导致净利润下降"],
  "grounding_text": ""             // 仅在已取得服务端 claim 级资格后允许为空
}
```

资格记录仍需在服务端审计中保留经核验的原文、读取身份和哈希，**不能因为给
binder 的 `grounding_text` 为空就失去可复查性**。A3 先独立验证
「原文存在 → 语义 verdict → 反对/冲突门禁 → 授权行」的连贯链路；
无资格或资格缺失时只能走第 1 条严格回退，不能给模型提供冒充已核验的标签。

该方式保留 binder 的现有判定逻辑，但需要在 A3 明确建立**可信上游资格投影**，
不是复制模型的三分类判断为最终支持权。A3 没完成以前，**不允许改写型发布**。

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
| 发布 | `answer_claim_binder._positive_support_confidence` 的可信上游行、原句回退、发布校验 | A3 建立服务端 claim 级资格投影；`grounding_text` 的空/非空必须与资格对应 |
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

- 不重写 `bind_answer_claims` 的判定逻辑；A3 必须完成可信上游资格投影，并证明只有真实核验后的正向关系才能进入不走原句匹配的分支
- 不改检索与读取预算
- 不引入新的引用数据结构和第二套评分器
- 不覆盖 Deep 档的 claim-engine 路径（它已有 Evidence Gate）
- 不在本设计内做付费对照实验；需要时单独给预算
