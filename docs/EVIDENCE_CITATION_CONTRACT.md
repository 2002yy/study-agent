# 引用展示契约（设计，暂不合入）

> 目标：让"回答采用的证据"只显示**服务端确认、且随最终发布答案一起成立**的引用，
> 并把"已读取 / 已选中 / 已核验引用"三种状态分开。不新增引用评分器。

## 1. 现状与问题

`frontend/src/features/evidence/EvidenceTrail.tsx:154-156`：

```ts
const adoptedRefs = evidenceRefs.filter(
  (ref) => ref.status === "selected" || supportedIds.has(ref.id),
);
```

这一段被展示为"回答采用的证据"，但：

- `selected` 只说明来源被选中，不说明最终回答引用了它，更不说明事实成立；
- `supportedIds` 来自 `pedagogy.evidence_ids`，与答案声明绑定无关；
- 发布校验失败（binder 拒绝、一致性检查失败、预算耗尽）时，页面仍可能展示
  "采用"，因为来源状态与发布结果没有绑定。

后端其实已经有权威数据：

| 数据 | 位置 | 含义 |
| --- | --- | --- |
| `answer_claim_snapshot` | 回合 `rag_snapshot` | `status`（validated/rejected）+ `claim_links[]`（claim_id/evidence_id/support_type/confidence） |
| `answer_validation_audit` | 回合 `rag_snapshot` | 生成与绑定的分阶段结果，含 candidate/learner 答案哈希 |
| `research_evidence_refs` | 回合 `rag_snapshot` | 服务端记录的、通过绑定的来源行（evidence_id/title/url/cluster） |
| `evidence_snapshot.refs[]` | 回合 `rag` | 前端已消费的来源清单（lifecycle_status、selection_reason） |

## 2. 权威规则（必须先满足，才允许显示"引用"）

一条来源只有同时满足以下全部条件，才可标记为**已核验引用**：

1. `answer_validation_audit` 存在，且 `answer_claim_binding.outcome == "passed"`；
2. `answer_claim_snapshot.status == "validated"`；
3. **published == candidate**：`audit.candidate_answer_sha256 == audit.learner_answer_sha256`
   （一致性检查或任何后置拒绝会改变 learner 答案，此时引用必须消失）；
4. 该来源的 `evidence_id` 出现在 `claim_links` 中，且
   `support_type ∈ {direct_support, indirect_support}`、`confidence >= 0.7`；
5. 该 `evidence_id` 同时出现在 `research_evidence_refs` 中（服务端记录，不是前端推测）。

任何一条不满足 → 该来源最多是"已读取"或"已选中"，不得出现在"引用"区。

**不得**用 `answer_claim_snapshot.status == "validated"` 单独判断：快照在绑定阶段产生，
一致性检查与发布可以在其后拒绝。

## 3. 数据契约（服务端产出，前端只读）

在回合 `rag` 中新增/明确两个字段（均由服务端计算，前端不做判定）：

```jsonc
{
  "citation_links": [                      // 仅当规则 1-3 全部成立时才非空
    {"evidence_id": "tool_read_1", "claim_id": "…", "confidence": 0.7}
  ],
  "evidence_snapshot": {
    "schema_version": "evidence-snapshot-v1",
    "refs": [
      {
        "id": "tool_read_1",
        "lifecycle_status": "selected",    // 读取生命周期：read/selected/rejected
        "citation_status": "cited"         // 新增：cited / unverified / none
      }
    ]
  }
}
```

- `citation_status = "cited"` 只能由第 2 节规则产生；
- `citation_status = "unverified"`：来源被读取/选中，但没进入已发布答案的绑定；
- `citation_status = "none"`：只是候选（搜索命中、未读取）。

旧回合（没有该字段）一律按 `none` 处理，不推断。

## 4. UI 展示契约

| 区块 | 数据来源 | 允许展示 |
| --- | --- | --- |
| 已核验引用（"回答采用的证据"） | `citation_status == "cited"` | 只显示这些；标题、域名、链接、可读取正文 |
| 已读取但未引用 | `lifecycle_status in {read, selected}` 且未被引用 | 明确写"已读取，未用于本次结论" |
| 候选来源 | `lifecycle_status == "candidate"` | 只在诊断面板，默认折叠 |

禁止：同一来源同时出现在"引用"和"未采用"；发布被拒时仍显示"采用"。
标签文案固定为：**已核验引用 / 已读取 / 已选中 / 候选**，不允许用"来源""参考"等模糊词代替。

## 5. 直接负控（前端 + 契约测试）

1. **成功发布且有引用**：passed + validated + published==candidate → 该来源 `cited`，
   且出现在"已核验引用"区。
2. **绑定失败无已核验引用**：`answer_claim_binding.outcome == "rejected"` →
   `citation_links == []`，任何来源都不是 `cited`；"引用"区为空。
3. **仅选中不能冒充引用**：来源 `lifecycle_status == "selected"` 但不在 `claim_links` →
   `unverified`，只在"已读取但未引用"区。
4. **引用 ID 不存在不能伪造**：`claim_links` 指向的 `evidence_id` 不在 refs / 
   `research_evidence_refs` 中 → 该链接被丢弃（服务端拒绝构建 payload），UI 不渲染悬空引用。
5. **后置拒绝**：一致性检查把 learner 答案换成弃答文案 → `citation_links == []`。

后端负控放在 `tests/test_answer_publication_gate.py` 附近；前端负控放在
`frontend/src/features/evidence/` 现有测试文件，沿用其 fixture。

## 6. 实施切片（每片独立 PR）

| 切片 | 内容 | 依赖 |
| --- | --- | --- |
| B1 | 服务端在回合 `rag` 暴露 `citation_links` 与 `refs[].citation_status`，规则集中在 `src/domain/evidence.py` | 无（复用现有快照与审计） |
| B2 | 前端按第 4 节分区与标签渲染；删除 `adoptedRefs` 的 `selected` 兜底 | B1 |
| B3 | 旧回合兼容：无字段 → `none`，并补一条回归 | B1 |

B1 不改变发布逻辑，只读取已经持久化的结果；B2 不改后端契约。

## 7. 非范围

- 不做引用评分器、不做新的证据检索；
- 不改 `bind_answer_claims` 的判定（#321 负责支持资格）；
- 不覆盖"未发布但有读取"的文案改版（属于 #321 后续）。
