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

1. `answer_validation_audit` 存在，且 `phases.answer_claim_binding.outcome == "passed"`；
2. `answer_claim_snapshot.status == "validated"`；
3. **published == candidate**：`audit.candidate_answer_sha256 == audit.learner_answer_sha256`，且审计必须针对当前持久化的 `assistant_message` 归一化；不得直接信任客户端快照
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
- `citation_status = "unverified"`：来源已有可用读取或被选中，但没有进入本次已发布回答的绑定；它**不**表示回答已经核实该来源，也不自动表示 `selected` 就是本轮读取；
- `citation_status = "none"`：只是候选（搜索命中、未读取）。

旧回合**若客户端收到缺失的 `citation_status` 字段**，前端一律按 `none` 展示，尤其不得由 `selected` 或 `pedagogy.evidence_ids` 猜测引用。服务端读取旧的持久化回合时，可以使用原有且通过重新规范化的 `answer_claim_snapshot`、`answer_validation_audit`、`research_evidence_refs` **重算已发布引用**（不要求数据迁移）；只要缺少任一发布或来源资格就返回 `none`。服务端重算不等于允许前端自行推断。

## 4. UI 展示契约

| 区块 | 数据来源 | 允许展示 |
| --- | --- | --- |
| 已核验引用（"回答采用的证据"） | `citation_status == "cited"` | 只显示这些；标题、域名、链接、可读取正文 |
| 已读取／已选中但未引用 | `lifecycle_status in {read, selected}` 且未被引用 | 根据独立生命周期显示"已读取，未用于本次结论"或"已选中，未用于本次结论"；不可将 selected 自动标记为已读取 |
| 候选来源 | `lifecycle_status == "candidate"` | 只在诊断面板，默认折叠 |

禁止：同一来源同时出现在"引用"和"未采用"；发布被拒时仍显示"采用"。
标签文案固定为：**已核验引用 / 已读取 / 已选中 / 候选**，不允许用"来源""参考"等模糊词代替。

## 5. 直接负控（前端 + 契约测试）

1. **成功发布且有引用**：passed + validated + published==candidate → 该来源 `cited`，
   且出现在"已核验引用"区。
2. **绑定失败无已核验引用**：`phases.answer_claim_binding.outcome == "rejected"` →
   `citation_links == []`，任何来源都不是 `cited`；"引用"区为空。
3. **仅选中不能冒充引用**：来源 `lifecycle_status == "selected"` 但不在 `claim_links` →
   `unverified`，只在"已读取／已选中但未引用"区，文案依据独立生命周期确定。
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
- **官方确定性字段发布的独立路径**：`official_field_publication.status=field_backed` 与 `assertion_refs[]` 不是 `answer_claim_binding` 的结果，本版 B1–B3 不把它强行解释成 binder 引用，也不得对其展示虚假的"已核验引用"。官方字段引用如何同屏展示须在实现前明确归属（可复用原始官方链接，不重做评分），不能用通用缺失判断误称官方字段无来源。
