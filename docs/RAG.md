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

## 4. Evidence sufficiency and refusal boundary

**检索到相关内容不等于证据足以回答问题。** 普通 local-knowledge 流程在 retrieval 与 answer evidence 之间增加独立 `EvidenceSufficiencyDecision`：

- `supported`：证据足以进入普通回答支持；
- `uncertain`：存在相关资料，但覆盖不足以形成可信的资料支持结论；
- `insufficient`：有高置信信号表明当前 active corpus 缺少回答该问题所需的关键证据。

确定性门控当前记录 informative query terms、covered/missing terms、active corpus 中完全缺失的 terms、IDF-weighted coverage、distinctive coverage、显式 hard anchors、来源数和 top score。

拒答策略刻意采用**高精度**而不是“看到缺词就拒答”：

- 普通自然语言改写词缺失不能直接视为资料缺口；
- `GPU`、`OCR`、`CUDA` 等显式 acronym-like hard anchors 在 active corpus 中缺失，是更强的 unsupported-answer 信号；
- 查询几乎没有任何概念被证据覆盖时，也可判定为不足；
- CJK 查询使用 bigram 级特征，不能把整句连续汉字误当成一个必然缺失的巨大 token。

当状态为 `uncertain / insufficient` 时，原始候选仍保存在 debug 供诊断，但普通 `results` 和 `sources` 为空，不能成为引用。模型只收到私有 retrieval constraint，明确不能把相似资料冒充为用户资料支持；constraint 本身永远不能作为用户可见 citation/evidence unit。

当前 K1 corpus 上的门控指标仍属于 `record_only`。即使小样本上 answerable supported rate 和 unanswerable block rate 达到 1.0，也不能直接升级为长期不可回退阈值，必须继续用更大真实语料和真实模型 replay 验证泛化。

## 5. Adaptive multi-source coverage

复合学习问题不能简单地“每个来源只取一个 chunk”，也不能为了多样性随机塞入更多来源。K1d 使用**非回退的自适应来源覆盖**：

1. 先执行普通 top-K 检索；
2. 保留普通 top-K 中已经出现的所有唯一来源；
3. 只删除同一来源占据的重复槽位；
4. 对明确的复合问题提取有限 facet；
5. 只有 facet 的 champion 来源尚未出现时，才使用重复槽位补充该来源。

因此 K1d 的硬约束是：**adaptive path 不得丢失 raw top-K 已召回的唯一来源。** 普通单来源问题不启用该策略，保持原排序行为。

当前确定性 K1 合同要求：

- multi-source recall@K `>= 0.9`；
- multi-source precision@K `>= 0.7`；
- adaptive overall recall 不得低于 raw Hybrid recall；
- answerable supported rate 与 unanswerable block rate 不得回退；
- forbidden / stale source leakage 保持为 0。

这些阈值约束当前 fixture 上的回归，不代表更大真实语料已经证明同样性能。

## 6. Real-provider answer replay contract

确定性 extractive lower bound 只能验证检索和评测合同，不能代表真实模型回答质量。K1e 因此单独定义 real-provider replay：

- 复用 Study Agent 现有 Provider owner 和模型档位，不创建平行的 Provider 配置体系；
- 使用同一 K1 corpus、evidence manifest、local-knowledge 检索、K1b 资格过滤、K1c sufficiency 和 K1d adaptive coverage；
- 默认只回放 answer-quality gold cases，检索层继续由完整 K1 retrieval suite 负责；
- 报告记录 corpus fingerprint、prompt-template fingerprint、case prompt fingerprint、Provider profile、model name、endpoint fingerprint、latency 和 Provider 返回的 token usage；
- 原始 API key 和 raw endpoint 不得写入报告；
- raw replay artifact 默认写入 gitignored `output/`，不能无审查进入版本库。

provenance 不能由任意测试对象自行声明。只有生产 `OpenAICompatibleReplayProvider` adapter 才能被 runner 标记为 `real_provider`；其他实现即使伪造同名字符串，也只能记录为 `synthetic_test`。

真实 Provider 不可用时必须显式记录 `provider_unavailable` 或 `partial_failure`，不得生成或补齐伪造质量分数。当前 harness 是否已具备、某次真实 replay 是否已实际执行，属于进度信息，以 `PROJECT_STATUS.md` 为准。

## 7. Stable capability boundary

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
- evidence sufficiency / refusal boundary；
- non-regressive adaptive multi-source coverage；
- real-provider replay harness 与 provenance schema；
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

## 8. Quality evaluation contract

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

证据充分性层单独记录：

- answerability accuracy；
- answerable supported rate；
- unanswerable block rate；
- supported / uncertain / insufficient 分布；
- 每个 case 的决策 reason、coverage 和 anchor diagnostics。

回答层由 `src/rag/answer_eval.py` 分开评估：

- answerability / refusal correctness；
- citation precision / recall；
- required claim coverage；
- claim support rate；
- groundedness；
- required source coverage；
- stale revision / forbidden-source leakage。

确定性 CI baseline 使用检索片段拼成 extractive lower bound，只验证评测合同、检索证据和失败暴露链路；只有 sufficiency=`supported` 才构造该 lower-bound answer。**不得解释为生产模型真实回答质量**。

确定性基线运行：

```bash
python tools/run_rag_quality_baseline.py --output rag-quality-baseline.json
```

真实 Provider replay 运行：

```bash
python tools/run_rag_provider_replay.py \
  --provider-profile <profile> \
  --model-profile pro
```

真实 replay 的默认原始报告位于 `output/rag-provider-replay.json`。只有实际 Provider 调用成功且报告 `status=completed` 时，才能讨论该次模型质量；`synthetic_test`、`provider_unavailable` 和 `partial_failure` 都不能被描述成完成的真实模型 benchmark。

CI 始终上传 `rag-quality-baseline` artifact。确定性 baseline 继续使用 corpus SHA-256 fingerprint 和 checked-in snapshot 固定语料、资格 manifest、门控结果和关键指标；K1d 另有不可回退质量合同。算法、corpus 或 evidence manifest 变化导致指标变化时，必须显式更新 snapshot，避免不同证据集合被悄悄当成同一基线比较。

## 9. Module map

| Module | Responsibility |
|---|---|
| `src/rag/loader.py` | 加载并标准化支持的本地文件 |
| `src/rag/chunker.py` | 生成可追溯 chunks，并传播 document evidence eligibility |
| `src/rag/index.py` | 构建、保存、加载和检索本地 index |
| `src/rag/embeddings.py` | embedding provider contract 与实现 |
| `src/rag/backends.py` | vector backend contract 与 adapter |
| `src/rag/query_plan.py` | pedagogy-aware private query planning |
| `src/rag/sufficiency.py` | retrieval 后的 evidence sufficiency / refusal 决策 |
| `src/rag/source_coverage.py` | 复合问题的非回退 adaptive multi-source coverage |
| `src/rag/eval.py` | 检索质量、scenario 与 stale-source 评测 |
| `src/rag/answer_eval.py` | 回答可信度与引用支持评测 |
| `src/rag/provider_replay.py` | real/synthetic provenance、Provider replay 与 usage/latency 报告 |
| `src/application/rag_service.py` | RagRun application orchestration |
| `src/repositories/rag_repository.py` | durable RagRun 和 index-state persistence |
| `src/api/routes/rag_routes.py` | FastAPI adapter |
| `frontend/src/features/rag/*` | React controller 与资料/来源展示层 |

## 10. Invariants

1. 删除、重建或资格变更后的非 active chunk 不得从任何普通 active retrieval backend 返回。
2. 必需阶段失败不得激活新 index version。
3. 同一 source path 只有一个当前 revision；revision 替换不得自动重置该 document 的 evidence eligibility。
4. 普通学习检索只能使用 `active` evidence；`superseded / excluded` 只能保留用于历史、管理或显式诊断。
5. backend-vector 返回值必须再次受当前 active chunk identity 约束，不能信任外部 backend 的旧状态。
6. `uncertain / insufficient` retrieval candidate 只能保留在 debug，不能作为普通 answer evidence 或用户 citation。
7. retrieval constraint 只用于模型私有规划，不得被披露成来源。
8. adaptive source coverage 不得丢失 raw top-K 已召回的唯一来源。
9. `local_hash` 不得被描述为生产语义 embedding。
10. 检索证据默认私有，只有 disclosure policy 允许的完整 evidence unit 进入模型回答。
11. RAG 候选、采用证据和 UI 引用计数必须保持一致。
12. 运行状态、错误和部分成功必须进入 durable RagRun，不用普通日志替代产品状态。
13. deterministic baseline 的 corpus fingerprint、sufficiency summary 或 snapshot 指标变化必须显式进入代码审查，不能静默覆盖。
14. synthetic replay 无论对象如何自报，都不得标记为 completed real-provider benchmark。
15. real-provider report 不得持久化 API key 或 raw endpoint；未完成调用不得补造质量分数。
