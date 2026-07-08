# Study Agent Next-Phase Plan

This document is the execution source of truth after Architecture V2 and
Workspace Runtime convergence. It records plans only; an item is not complete
until code, tests, documentation and remote CI prove it.

Updated: 2026-07-01

## Progress

Completed on 2026-07-02:

- Chroma replacement writes remove chunk IDs absent from the candidate index.
- SQLite `rag_index_states` owns active/staging versions and an
  expected-version write lease.
- Required vector-stage failure skips activation, preserves the old active
  index and records the RagRun as `partial_success`.
- Local, vector and activation stages are reported separately.
- Stable document identity is separated from content-derived revision identity;
  re-uploading the same source replaces its active revision.
- Uploads enforce batch/file limits, supported MIME types, UTF-8 text, PDF
  signatures, DOCX structure and archive expansion limits before persistence.
- Chat retrieval builds a private `RetrievalQueryPlan` from the learning
  objective, unresolved gap, protocol and current input.
- `local_hash` status/config metadata identifies it as non-semantic
  `test_fallback`.

The Phase 0 correctness gate is complete. Phase 1 Pedagogy Evaluation is the
next implementation slice; RAG retrieval-quality work remains Phase 2.

## Planning principles

- Preserve the server-owned `RagRun`, explainable retrieval and pedagogy
  evidence-disclosure architecture.
- Fix correctness and consistency before adding retrieval features.
- Do not persist learner mastery until semantic evaluation is reliable.
- Borrow boundaries from RAGFlow, LlamaIndex, Haystack and Dify; do not replace
  the current architecture by importing an entire framework.
- `local_hash` is deterministic test/fallback retrieval, not production
  semantic embedding.
- GraphRAG remains optional and must not replace the base chunk-RAG pipeline.

## Execution order

### Phase 0 — RAG correctness gate

These defects can return deleted knowledge or report false success, so they
precede quality enhancements and Learner Model persistence.

1. Make dense-index rebuild/delete remove stale Chroma chunks.
2. Introduce staging and active `IndexVersion`; validate document, chunk and
   embedding counts before atomic activation.
3. Represent local/dense/sparse/activation stage status and support
   `partial_success` where appropriate.
4. Add an index write lease or expected-version compare-and-swap.
5. Separate stable `KnowledgeDocument` identity from `DocumentRevision` and
   content hash.
6. Validate aggregate upload size, per-file size, MIME/magic bytes and
   encrypted/unsafe files.
7. Add `RetrievalQueryPlan` using learning objective, unresolved gap, protocol
   and knowledge kind—not only the latest user sentence.
8. Mark `local_hash` as test/fallback-only in API metadata, settings and docs.

Acceptance:

- Deleted/rebuilt documents cannot be retrieved from any backend.
- A failed required index stage cannot activate a new version.
- Concurrent rebuild/delete operations have deterministic ownership.
- “不知道” in a guided learning turn still produces a useful private query
  from pedagogy state.

### Phase 1 — Pedagogy Evaluation vertical slice (complete)

1. Attach `PedagogyEvalRun` to the real chat-turn completion pipeline.
2. Add SQLite schema, repository and service ownership.
3. Implement deterministic-first evaluation with semantic evaluation only for
   ambiguous claims.
4. Add a structured semantic evaluator adapter returning claims, correct
   points, gaps, misconceptions, reasoning completeness, transfer readiness,
   confidence and evidence references.
5. Require evidence-grounded thresholds before advancing protocol state.
6. Add golden dialogues and teaching-quality evaluation for Socratic, Feynman,
   Project and Direct modes.
7. Record evaluator version, prompt/schema version, evidence IDs and final
   decision for replay.

Acceptance:

- Turn, pedagogy state and evaluation record commit atomically.
- Provider failure cannot silently advance learner state.
- Golden suites cover correct reasoning, plausible misconceptions, paraphrase,
  counterexamples, missing conditions and evidence leakage.

Implementation status (2026-07-02):

- `PedagogyEvalRun` is evaluated from the real learner turn before planning and
  is committed with the completed `ChatTurn` and `ChatThread.learning_state` in
  one SQLite transaction.
- Schema version 13 owns replayable evaluator, prompt and result-schema
  versions, evidence IDs, confidence, reasons and the final decision.
- Deterministic checks reject known cases without model cost. Ambiguous claims
  use the strict-JSON semantic adapter; provider or parse failure becomes
  `needs_semantic_review` and cannot advance transfer/complete/deliver states.
- `tests/fixtures/evals/pedagogy_dialogues.json` covers Direct, Socratic,
  Feynman and Project exchanges, including the acceptance cases above.

### Phase 2 — RAG retrieval quality

Current status: BM25 sparse retrieval, RRF hybrid fusion, retrieval-stage debug
metrics, exact duplicate suppression, per-source diversity limits, metadata
filters, explicit embedding profiles and an optional local reranker are
implemented. The remaining work should focus on external reranker providers and
larger retrieval-quality evaluation.

1. [x] Add a production multilingual Chinese/English embedding profile.
2. [x] Upgrade sparse retrieval to BM25.
3. [x] Replace fixed cross-score weighting with reciprocal-rank fusion.
4. [x] Add an optional reranker with explicit latency/cost budgets.
5. [x] Add duplicate suppression, source diversity and metadata filters.
6. [x] Record candidate count and latency for local lexical/vector retrieval stages.
7. [x] Extend candidate count and latency accounting to backend-vector query runs.
8. [x] Extend candidate count and latency accounting to reranker stages.
9. [ ] Add an external reranker provider only after expanding the eval corpus.

Acceptance:

- The same evaluation corpus compares lexical, dense, hybrid and reranked
  profiles.
- Quality changes must show Recall/MRR/nDCG gains without violating latency and
  cost budgets.

### Phase 3 — Ingestion and KnowledgeBase domain

1. Separate `Parser`, `DocumentNormalizer`, `StructuralChunker`,
   `MetadataExtractor` and index writers.
2. Add Markdown heading-aware chunks; DOCX headings/lists/tables; PDF page
   structure and failure localization.
3. Add optional Docling/MinerU and demand-triggered OCR profiles.
4. Introduce parent/child chunks, section paths and token budgets.
5. Add chunk preview and parser diagnostics.
6. Formalize `KnowledgeBase`, `KnowledgeDocument`, `DocumentRevision`,
   `Chunk`, `IndexVersion`, `IngestionRun`, `RetrievalRun`,
   `RetrievalProfile` and `EmbeddingProfile`.

### Phase 4 — API/product completion

1. Add `/after-session/preview` and `/after-session/commit` with preview/commit
   consistency and memory safety.
2. Add `/stats` and `/stats/reset` with explicit destructive confirmation.
3. Add `/health/full` for provider, parser and index diagnostics.

### Phase 5 — Learner Model

Start only after Phase 1 evaluation is stable on the golden corpus.

Minimum entities:

- `ConceptMastery`
- `Misconception`
- `LearningEvidence`
- `LearningEvent`

Mastery changes must cite committed evaluation/evidence records. Rule-only or
low-confidence judgments must never become durable mastery.

### Phase 6 — Evaluation expansion

Add:

- nDCG@K
- evidence precision
- duplicate chunk rate
- source diversity
- citation correctness
- context answerability
- faithfulness
- retrieval/rerank latency
- embedding cost
- stale-index consistency

Maintain representative corpora for networking, Java backend, Python/RAG,
academic papers and project documentation.

### Phase 7 — Legacy retirement

1. Remove remaining production dependencies on the `src.api` compatibility
   shim, migrate old tests/clients, then delete frozen exports.
2. Remove Streamlit after the after-session flow and remaining diagnostics are
   available in React/FastAPI.
3. Update README, architecture, migration and testing documents in the same
   change.

### Phase 8 — Optional advanced retrieval

Consider Concept Graph/GraphRAG only after the base RAG evaluation gates are
stable. Use it as an additional retrieval path for cross-document concepts and
global synthesis, never as a replacement for evidence-traceable chunk RAG.

## Immediate next slice

When implementation resumes, start with Phase 0 items 1–4:

1. reproduce stale Chroma retrieval after delete/rebuild;
2. define versioned staging/activation contracts;
3. model partial stage status;
4. add concurrency and rollback tests before changing the implementation.
