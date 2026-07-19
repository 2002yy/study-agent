# Study Agent RAG 技术参考

> **文档类别：稳定技术参考，不是当前进度入口。**  
> 当前项目状态、缺口和下一步统一查看 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。

本文描述 RAG 的技术边界、数据一致性和模块责任。只有检索架构、索引协议或稳定能力发生变化时更新。

## 1. Index activation and consistency

RAG 写入使用版本化激活协议：

1. 使用 expected active version 获取 SQLite `rag_index_states` 写入租约；
2. 构建 staging candidate；
3. 同步配置的 vector backend；
4. 只有必需阶段通过后才原子替换本地 active index；
5. 在 SQLite 中激活 staging version。

Chroma 同步会删除 replacement index 中不存在的 ID，避免删除、重建或证据资格变化后残留可检索旧 chunk。必需 vector stage 失败时保留旧 active index，并将 durable RagRun 记录为 `partial_success`；local、vector、activation 阶段分别保存诊断信息。

## 2. Document revisions, evidence eligibility and upload validation

`document_id` 对 source path 保持稳定，`revision_id` 标识具体 normalized content/parser revision。同一路径上传变化版本时替换该 document 的当前 revision 和 chunks，而不是让同一路径的多个 revision 同时进入 index。

跨文档的“新旧关系”与 revision 是两个不同概念。知识资料额外拥有 evidence eligibility：

- `active`：普通检索、rerank 和回答证据可以使用；
- `superseded`：资料保留用于历史和审计，但普通学习回答不得使用；可选记录 `superseded_by_document_id`；
- `excluded`：用户主动保留但排除，不参与普通学习回答。

普通检索在 BM25、local vector、hybrid 和 reranker **之前**构造 active-only retrieval view。这样 inactive 资料不会影响 BM25 document frequency、候选集合或排序。backend-vector 返回值还必须按当前 active chunk ID 做防御性过滤，避免外部向量后端短暂不同步时重新泄漏旧证据。

向量同步同样只接收 active-only view；因此资料从 `active` 改为 `superseded / excluded` 后，对应 chunk 必须从普通 active vector collection 移除。资格变更复用 index staging / vector sync / activation 协议，不能绕过 durable index state 直接改 JSON。

同一路径上传新 revision 时继承已有 evidence eligibility，避免用户明确排除的资料因为内容更新自动重新参与回答。旧格式 index 缺少资格字段时按 `active` 读取，保证升级兼容。

文件持久化前执行上传校验：

- 单文件和批量总大小；
- extension/MIME 一致性；
- UTF-8 文本；
- PDF signature、页数、提取文本和加密状态；
- DOCX ZIP structure；
- archive expansion ceiling。

## 3. Pedagogy-aware query planning

单聊检索使用 `RetrievalQueryPlan`。private query 组合：

- 当前学习目标；
- unresolved gap；
- 有意义的用户输入；
- protocol；
- knowledge kind。

因此用户回答“我不知道”不会擦除检索主题。raw input、private query 和教学上下文保存在 turn RAG snapshot 中，用于恢复和诊断。

`local_hash` 只用于确定性测试和离线 fallback；它在 API 元数据中明确标记为非语义检索，不属于生产 embedding profile。

## 4. Stable capability boundary

当前稳定能力包括：

- `.md`、`.markdown`、`.txt`、`.docx`、`.pdf` 加载；
- 文本标准化和空文档拒绝；
- 带 source path、title 和 line range 的可追溯 chunk；
- stable document/revision identity；
- `active / superseded / excluded` evidence eligibility 与 active-only retrieval；
- BM25 lexical retrieval；
- deterministic local hash-vector fallback；
- 使用 reciprocal-rank fusion 的 hybrid retrieval；
- CJK bigram matching；
- 默认持久化 JSON index；
- citation-first context formatting；
- 可选 Chroma adapter；
- OpenAI-compatible embedding provider；
- duplicate suppression、source diversity、metadata filters；
- latency/candidate accounting；
- optional local reranker；
- source precision/recall、MRR、source-level nDCG、stale-source leakage 和 scenario 分组评测；
- answerability/refusal、citation precision/recall、claim support、groundedness 和 stale-revision answer evaluation；
- FastAPI RagRun query/upload/rebuild、文档生命周期和 evidence-status 接口；
- React 来源与资料资格管理界面；
- 受控 local-knowledge tool。

以下属于后续增强，不在本技术参考中维护进度：

- parser/normalizer/structural chunker 的完整领域拆分；
- heading/list/table/page-aware chunk；
- Docling/MinerU/OCR profile；
- parent/child chunks 和 section path；
- external reranker provider；
- pgvector、Milvus、FAISS 或 managed vector store；
- 临时附件与长期知识库完整产品语义。

这些项目的当前状态以 `PROJECT_STATUS.md` 为准。

## 5. Quality evaluation contract

RAG 质量评测复用同一套 `src/rag/eval.py` 检索评测域，不另建平行指标系统。K1 的确定性本地 corpus 同时包含干净查询、改写、多来源、相似主题干扰、旧版本和不可回答问题。

检索层分别记录：

- source hit rate；
- source precision@K / recall@K；
- MRR；
- source-level nDCG；
- forbidden / stale source leakage；
- unanswerable non-empty retrieval rate；
- 按 scenario 分组的同口径指标。

source-level nDCG 只在某个来源第一次出现时给予 relevance gain。重复 chunk 仍占据实际排名位置，因此会降低后续相关来源的排名质量，但不会重复增加同一来源的 gain。

回答层由 `src/rag/answer_eval.py` 分开评估：

- answerability / refusal correctness；
- citation precision / recall；
- required claim coverage；
- claim support rate；
- groundedness；
- required source coverage；
- stale revision / forbidden-source leakage。

确定性 CI baseline 使用检索片段拼成 extractive lower bound，只验证评测合同、检索证据和失败暴露链路，**不得解释为生产模型真实回答质量**。真实模型或 Provider replay 必须单独标识运行来源、模型配置和成本。

运行：

```bash
python tools/run_rag_quality_baseline.py --output rag-quality-baseline.json
```

CI 始终上传 `rag-quality-baseline` artifact。当前 baseline 为 `record_only`：不以分数阈值阻断合并，但 corpus 使用 SHA-256 fingerprint，并由 checked-in baseline snapshot 固定当前语料、资格 manifest 和关键指标。算法、corpus 或 evidence manifest 变化导致指标变化时，必须显式更新 snapshot，避免不同证据集合被悄悄当成同一基线比较。

## 6. Module map

| Module | Responsibility |
|---|---|
| `src/rag/loader.py` | 加载并标准化支持的本地文件 |
| `src/rag/chunker.py` | 生成可追溯 chunks，并传播 document evidence eligibility |
| `src/rag/index.py` | 构建、保存、加载和检索本地 index |
| `src/rag/embeddings.py` | embedding provider contract 与实现 |
| `src/rag/backends.py` | vector backend contract 与 adapter |
| `src/rag/query_plan.py` | pedagogy-aware private query planning |
| `src/rag/eval.py` | 检索质量、scenario 与 stale-source 评测 |
| `src/rag/answer_eval.py` | 回答可信度与引用支持评测 |
| `src/application/rag_service.py` | RagRun application orchestration |
| `src/repositories/rag_repository.py` | durable RagRun 和 index-state persistence |
| `src/api/routes/rag_routes.py` | FastAPI adapter |
| `frontend/src/features/rag/*` | React controller 与资料/来源展示层 |

## 7. Invariants

1. 删除、重建或资格变更后的非 active chunk 不得从任何普通 active retrieval backend 返回。
2. 必需阶段失败不得激活新 index version。
3. 同一 source path 只有一个当前 revision；revision 替换不得自动重置该 document 的 evidence eligibility。
4. 普通学习检索只能使用 `active` evidence；`superseded / excluded` 只能保留用于历史、管理或显式诊断。
5. backend-vector 返回值必须再次受当前 active chunk identity 约束，不能信任外部 backend 的旧状态。
6. `local_hash` 不得被描述为生产语义 embedding。
7. 检索证据默认私有，只有 disclosure policy 允许的完整 evidence unit 进入模型回答。
8. RAG 候选、采用证据和 UI 引用计数必须保持一致。
9. 运行状态、错误和部分成功必须进入 durable RagRun，不用普通日志替代产品状态。
10. deterministic baseline 的 corpus fingerprint 或 snapshot 指标变化必须显式进入代码审查，不能静默覆盖。
