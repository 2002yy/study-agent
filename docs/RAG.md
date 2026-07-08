# RAG MVP

## Index activation and consistency

RAG writes use a versioned activation protocol:

1. acquire the SQLite `rag_index_states` lease with the expected active version;
2. build a staging candidate;
3. synchronize the configured vector backend;
4. atomically replace the local active index only after required stages pass;
5. activate the staging version in SQLite.

Chroma synchronization removes IDs that are not present in the replacement
index, so delete and rebuild cannot leave retrievable stale chunks. A required
vector-stage failure preserves the previous active index and completes the
durable RagRun as `partial_success`, with separate local, vector and activation
stage diagnostics.

## Document revisions and upload validation

`document_id` is stable for a source path, while `revision_id` identifies a
specific normalized-content/parser revision. Appending a changed version of the
same source replaces its document and chunks instead of leaving both revisions
active.

Upload validation runs before files are persisted. It enforces per-file and
aggregate limits, extension/MIME agreement, UTF-8 text, PDF signatures, DOCX
ZIP structure and an uncompressed archive ceiling.

## Pedagogy-aware query planning

Single-chat retrieval uses `RetrievalQueryPlan`. The private query combines the
current learning objective and unresolved gap with meaningful user input. A
reply such as “不知道” therefore does not erase the retrieval topic. The raw
input, protocol, knowledge kind and private query remain available in the turn
RAG snapshot for diagnosis.

`local_hash` remains deterministic for tests and offline fallback, but is
explicitly reported as non-semantic and is not a production embedding profile.

## Status

Current status: **MVP implemented with a local-first retrieval path, configurable embeddings and an optional Chroma adapter**.

Implemented:

- Local document loading for `.md`, `.markdown`, `.txt`, `.docx` and `.pdf`
- Text normalization and empty-document rejection
- PDF parsing through `pypdf`, with file-size, page-count, extracted-text and encrypted-file guards
- Source-traceable chunking with file path, title and line range
- Local keyword retrieval with BM25 scoring
- Deterministic local hash-vector retrieval prototype
- Hybrid retrieval that fuses BM25 and local-vector rankings with reciprocal-rank fusion
- CJK bigram matching for simple Chinese queries
- Persisted JSON index under `logs/rag_index.json` by default
- Citation-first context formatting for later LLM calls
- Streamlit retrieval panel for uploads, local paths, indexing, querying and citation preview
- Optional single-chat and WeChat interactive reply injection through the `用于聊天回答` toggle
- UI source blocks for retrieved file paths, line ranges, scores and matched terms
- FastAPI endpoints: `GET /health`, `POST /rag`, `POST /rag/index`, `POST /rag/query`, `GET /rag/status`, `POST /rag/upload`, `POST /rag/local-knowledge`, `GET /tools`, `POST /tools/{tool_name}/preview`, `POST /tools/{tool_name}/call`, `GET /workflows/runs`, `GET /workflows/runs/{run_id}`
- Streamlit knowledge/debug panel with index summary, document rows, chunk preview and score breakdowns
- Optional vector backend interface with local fallback and Chroma adapter
- Configurable embedding providers: deterministic `local_hash` by default, OpenAI-compatible embeddings when explicitly configured
- Controlled local-knowledge retrieval tool with intent gating, deterministic query rewrite and explicit not-found behavior

Not implemented yet:

- FAISS, pgvector or managed vector stores
- Production-grade embedding evaluation, relevance tuning and re-index migration tooling
- Automatic injection into every generation path; current injection covers single chat and WeChat interactive replies, but not news discussion or after-session feedback

## Module Map

| Module | Responsibility |
|---|---|
| `src/rag/loader.py` | Load supported local files into normalized `RagDocument` objects |
| `src/rag/chunker.py` | Split documents into line-traceable `RagChunk` objects |
| `src/rag/index.py` | Build, save, load and search a local JSON RAG index |
| `src/rag/embeddings.py` | Embedding provider contract, local hash provider and OpenAI-compatible provider |
| `src/rag/backends.py` | Vector backend contract, local backend and environment-driven backend selection |
| `src/rag/chroma_backend.py` | Optional Chroma persistent backend adapter |
| `src/rag/vector.py` | Deterministic local vector prototype and hybrid retrieval |
| `src/rag/eval.py` | LLM-free retrieval quality evaluation over gold query fixtures |
| `src/rag/service.py` | Application-facing helpers for indexing, querying and context formatting |
| `src/rag/schema.py` | Dataclasses for documents, chunks, indexes and search results |
| `src/tools/local_knowledge.py` | Controlled retrieval boundary for agentic local knowledge use |
| `src/tools/registry.py` | Allowlisted typed tool registry with preview, call and workflow audit support |
| `src/workflows/store.py` | Local JSONL workflow run/event persistence for tool and frontend timelines |
| `src/api.py` | FastAPI health, chat, memory, session, RAG, tool and workflow endpoints |

## Data Flow

```text
local files
  -> load_document / load_documents
  -> chunk_document / chunk_documents
  -> build_rag_index
  -> save_rag_index
  -> query_documents
  -> build_rag_context
  -> optional controlled local-knowledge tool
  -> optional single-chat / WeChat interactive prompt injection or FastAPI response
  -> frontend-facing chat / memory / session API flow
```

## Retrieval Behavior

The default mode is `hybrid`: BM25 sparse retrieval plus deterministic local hash-vector similarity fused with reciprocal-rank fusion (RRF). This is a retrieval prototype, not a semantic embedding model. English-like tokens are lowercased words with trailing punctuation stripped. Chinese text is indexed as longer CJK spans plus overlapping two-character terms, so a query such as `向量` can match a longer phrase such as `向量检索`.

Supported retrieval modes:

- `lexical`: BM25 sparse term scoring
- `vector`: deterministic local hash-vector cosine similarity
- `hybrid`: BM25 and local-vector rankings fused with RRF
- `backend_vector`: configured vector backend; defaults to local and can use the optional Chroma adapter with configured embeddings

Each result keeps:

- `source_path`
- `title`
- `chunk_index`
- `start_line` / `end_line`
- `score`
- `matched_terms`

This keeps the answer path auditable before the project adds model-generated answers on top.

## Example

```python
from src.rag import build_rag_context, index_documents, query_documents

index_documents(["memory/current_focus.md", "docs/TECH_STACK.md"])
results = query_documents("model routing and context tiers", top_k=3, retrieval_mode="hybrid")
context = build_rag_context(results)
```

The resulting context is formatted as numbered source blocks:

```text
[1] TECH_STACK (docs/TECH_STACK.md:L86-L106, score=3.250)
...
```

## Testing

Regression coverage lives in `tests/test_rag.py` and verifies:

- Markdown loading and metadata
- `.docx` loading through `python-docx`
- PDF extraction and safety limits
- Source line ranges in chunks
- Build/save/load/query behavior
- Chinese CJK bigram matching
- Local hash-vector and hybrid retrieval behavior
- Citation formatting and context budget behavior
- Streamlit RAG panel helpers for uploaded filenames and local path parsing
- FastAPI `/health`, `/rag`, `/rag/index`, `/rag/query`, `/rag/status`, `/rag/upload` and `/rag/local-knowledge`
- FastAPI `/chat`, `/memory/preview`, `/memory/commit`, `/sessions` and `/sessions/{session_id}/flush`
- FastAPI `/tools`, `/tools/{tool_name}/preview`, `/tools/{tool_name}/call`, `/workflows/runs` and `/workflows/runs/{run_id}`
- Prompt injection behavior for cited RAG context
- Controlled local-knowledge tool behavior for skip / found / not-found / rewrite

`tests/test_rag_eval.py` adds a small gold fixture suite under `tests/fixtures/rag_eval/` and verifies:

- Eval case loading from JSON
- Source hit rate
- `recall@k`
- Mean reciprocal rank
- Empty-result and miss accounting
- Unknown retrieval mode rejection

`tests/test_eval_quality_gates.py` adds the first broader P8.4 quality-gate fixtures under `tests/fixtures/evals/` and verifies:

- Answer grounding citation and unsupported-claim rules
- Controlled local-knowledge tool routing decisions
- Workflow event status transitions and failure metadata
- Memory write permission safety across runtime modes
- URL safety and domain-policy regression cases

`tests/test_workflow_tool_registry.py` adds the first P8.5 execution-foundation checks and verifies:

- Workflow JSONL run/event persistence and listing
- Default allowlisted tool registry metadata
- Unknown tool arguments are blocked before execution
- `retrieve_local_knowledge` tool calls write workflow audit events

P4-B adds API/query diagnostics:

- Retrieval mode, `top_k`, `min_score` and tokenized query terms
- Candidate count and returned result count
- Per-stage candidate count, scored count and elapsed milliseconds
- Per-result rank, chunk id, source path, matched terms and score breakdown
- Retrieval post-processing diagnostics for metadata filters, exact duplicate
  suppression and per-source diversity limits
- Optional one-query evaluation when `/rag/query` receives `expected_sources`

P4-C / P6 adds Streamlit inspection controls:

- Current index path, document count and chunk count
- Indexed document table with file type, size, mtime, hash prefix and chunk count
- Chunk preview table with line range, character count and source path
- Retrieval controls for mode, `top_k`, `min_score` and debug visibility
- Score-breakdown table for retrieved chunks

P5 adds the first vector-backend abstraction:

- `EmbeddingProvider` protocol plus `LocalHashEmbeddingProvider` and `OpenAIEmbeddingProvider`
- `VectorBackend` protocol plus `LocalVectorBackend`
- `RAG_VECTOR_BACKEND=local|chroma`
- `RAG_EMBEDDING_PROVIDER=local_hash|openai`, `RAG_EMBEDDING_MODEL`, `RAG_EMBEDDING_DIMENSIONS`, `RAG_EMBEDDING_API_KEY`, `RAG_EMBEDDING_BASE_URL`
- Optional `ChromaVectorBackend` using lazy `chromadb` import, `PersistentClient`, collection `upsert` and vector query
- `tests/test_rag_backends.py` verifies local backend behavior, embedding environment config, OpenAI-compatible embedding batching and Chroma fake-client upsert/query behavior

## Next Steps

### P4: Retrieval Quality Loop

Goal: prove retrieval quality before expanding the stack.

- [x] Add a small gold fixture set with queries, expected sources and expected terms.
- [x] Track `recall@k`, mean reciprocal rank, source hit rate and empty-result rate.
- [x] Surface retrieval debug data in tests and API responses before adding more UI polish.
- [x] Add a Streamlit source/debug panel for inspecting score breakdowns.
- [x] Upgrade sparse retrieval from TF-IDF-style scoring to BM25.
- [x] Replace fixed hybrid cross-score weighting with RRF.
- [x] Record local retrieval-stage candidate counts and latency in debug output.
- [x] Add exact duplicate suppression, metadata filters and per-source diversity limits.
- [x] Record backend-vector query latency when callers use the traced query path.
- Keep the first evaluation layer LLM-free so CI can catch retrieval regressions deterministically.

### P5: Real Embedding Backend

Goal: replace the local hash-vector prototype with optional real embeddings without breaking local-first defaults.

- [x] Extract an embedding-provider and vector-backend contract.
- [x] Keep JSON + lexical / hybrid retrieval as the zero-infrastructure fallback.
- [x] Add an optional Chroma adapter with lazy import and fake-client tests.
- [x] Make vector backend selection explicit through config.
- [x] Add a production embedding provider path; current default remains `local_hash`, while OpenAI-compatible embeddings require explicit env/API configuration.

### P6: Knowledge UI

Goal: turn the Streamlit expander into a usable knowledge panel.

- [x] List indexed documents with chunk count, mtime, hash and status.
- [x] Add query debugging controls for mode, `top_k`, threshold and score preview.
- [x] Add source preview with title, path, page or line range and matched terms.
- [ ] Add per-chat RAG scope selection instead of one global toggle only.

### P7: Agentic RAG

Goal: let the model retrieve when it needs evidence instead of always pre-retrieving.

- [x] Add a `retrieve_local_knowledge(query)` tool boundary.
- [x] Route retrieval only for knowledge-grounded questions through deterministic intent gating.
- [x] Allow deterministic query rewrite and second-pass retrieval when first-pass evidence is weak.
- [x] Require explicit "not found in local knowledge" behavior when no source is retrieved.
- [x] Expose the same boundary through `POST /rag/local-knowledge` for the React frontend.
- [ ] Add LLM tool-calling / function-calling integration; current implementation is controlled pre-generation retrieval, not free-form tool use.

### P8: Service API Foundation

Goal: expose the current local-first capabilities through stable API boundaries and keep the React frontend aligned with those contracts.

- [x] Add RAG status and upload endpoints for index inspection and rebuilds.
- [x] Add a non-streaming `/chat` endpoint that reuses model routing, role prompts, memory bundles, local-knowledge retrieval and session logging.
- [x] Add memory preview / commit endpoints with the same runtime write-mode guard as the Streamlit UI.
- [x] Add session listing and force-flush endpoints for local session inspection.
- [x] Add controlled tool preview / call endpoints and workflow run read endpoints.
- [x] Add optional local API token gate and explicit CORS origin allowlist for local/LAN deployments.
- [ ] Add streaming chat and frontend-oriented error envelopes before public or broader LAN deployment.
