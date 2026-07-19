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

Chroma 同步会删除 replacement index 中不存在的 ID，避免删除或重建后残留可检索旧 chunk。必需 vector stage 失败时保留旧 active index，并将 durable RagRun 记录为 `partial_success`；local、vector、activation 阶段分别保存诊断信息。

## 2. Document revisions and upload validation

`document_id` 对 source path 保持稳定，`revision_id` 标识具体 normalized content/parser revision。同一路径上传变化版本时替换 active revision 和 chunks，而不是让多个版本同时进入 active index。

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
- FastAPI RagRun query/upload/rebuild 和文档生命周期接口；
- React 来源与知识库界面；
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

CI 始终上传 `rag-quality-baseline` artifact。当前 baseline 为 `record_only`：不以分数阈值阻断合并，但 corpus 使用 SHA-256 fingerprint，且 `tests/fixtures/rag_eval/baseline_v1_summary.json` 保存首版摘要。算法或 corpus 变化导致指标变化时，必须显式更新 snapshot，避免不同题集被悄悄当成同一基线比较。

## 6. Module map

| Module | Responsibility |
|---|---|
| `src/rag/loader.py` | 加载并标准化支持的本地文件 |
| `src/rag/chunker.py` | 生成可追溯 chunks |
| `src/rag/index.py` | 构建、保存、加载和检索本地 index |
| `src/rag/embeddings.py` | embedding provider contract 与实现 |
| `src/rag/backends.py` | vector backend contract 与 adapter |
| `src/rag/query_plan.py` | pedagogy-aware private query planning |
| `src/rag/eval.py` | 检索质量、scenario 与 stale-source 评测 |
| `src/rag/answer_eval.py` | 回答可信度与引用支持评测 |
| `src/application/rag_service.py` | RagRun application orchestration |
| `src/repositories/rag_repository.py` | durable RagRun 和 index-state persistence |
| `src/api/routes/rag_routes.py` | FastAPI adapter |
| `frontend/src/features/rag/*` | React controller 与展示层 |

## 7. Invariants

1. 删除或重建后的旧 chunk 不得从任何 active backend 返回。
2. 必需阶段失败不得激活新 index version。
3. 同一 source path 只有一个 active revision。
4. `local_hash` 不得被描述为生产语义 embedding。
5. 检索证据默认私有，只有 disclosure policy 允许的完整 evidence unit 进入模型回答。
6. RAG 候选、采用证据和 UI 引用计数必须保持一致。
7. 运行状态、错误和部分成功必须进入 durable RagRun，不用普通日志替代产品状态。
8. deterministic baseline 的 corpus fingerprint 或 snapshot 指标变化必须显式进入代码审查，不能静默覆盖。
