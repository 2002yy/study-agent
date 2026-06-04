# RAG MVP

## Status

Current status: **MVP implemented with a local vector prototype, not a production vector-store RAG system yet**.

Implemented:

- Local document loading for `.md`, `.markdown`, `.txt`, `.docx` and `.pdf`
- Text normalization and empty-document rejection
- PDF parsing through `pypdf`, with file-size, page-count, extracted-text and encrypted-file guards
- Source-traceable chunking with file path, title and line range
- Local keyword retrieval with TF-IDF-style scoring
- Deterministic local hash-vector retrieval prototype
- Hybrid retrieval that combines normalized lexical score with local vector similarity
- CJK bigram matching for simple Chinese queries
- Persisted JSON index under `logs/rag_index.json` by default
- Citation-first context formatting for later LLM calls
- Streamlit retrieval panel for uploads, local paths, indexing, querying and citation preview
- Optional single-chat and WeChat interactive reply injection through the `用于聊天回答` toggle
- UI source blocks for retrieved file paths, line ranges, scores and matched terms
- FastAPI endpoints: `GET /health`, `POST /rag`, `POST /rag/index`, `POST /rag/query`

Not implemented yet:

- Embedding model integration
- FAISS, pgvector or other vector stores
- Automatic injection into every generation path; current injection covers single chat and WeChat interactive replies, but not news discussion or after-session feedback

## Module Map

| Module | Responsibility |
|---|---|
| `src/rag/loader.py` | Load supported local files into normalized `RagDocument` objects |
| `src/rag/chunker.py` | Split documents into line-traceable `RagChunk` objects |
| `src/rag/index.py` | Build, save, load and search a local JSON RAG index |
| `src/rag/vector.py` | Deterministic local vector prototype and hybrid retrieval |
| `src/rag/eval.py` | LLM-free retrieval quality evaluation over gold query fixtures |
| `src/rag/service.py` | Application-facing helpers for indexing, querying and context formatting |
| `src/rag/schema.py` | Dataclasses for documents, chunks, indexes and search results |
| `src/api.py` | FastAPI health and RAG endpoints |

## Data Flow

```text
local files
  -> load_document / load_documents
  -> chunk_document / chunk_documents
  -> build_rag_index
  -> save_rag_index
  -> query_documents
  -> build_rag_context
  -> optional single-chat / WeChat interactive prompt injection or FastAPI response
```

## Retrieval Behavior

The default mode is `hybrid`: lexical scoring plus deterministic local hash-vector similarity. This is a retrieval prototype, not a semantic embedding model. English-like tokens are lowercased words with trailing punctuation stripped. Chinese text is indexed as longer CJK spans plus overlapping two-character terms, so a query such as `向量` can match a longer phrase such as `向量检索`.

Supported retrieval modes:

- `lexical`: TF-IDF-style term scoring
- `vector`: deterministic local hash-vector cosine similarity
- `hybrid`: normalized lexical score plus vector similarity

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
- FastAPI `/health`, `/rag`, `/rag/index` and `/rag/query`
- Prompt injection behavior for cited RAG context

`tests/test_rag_eval.py` adds a small gold fixture suite under `tests/fixtures/rag_eval/` and verifies:

- Eval case loading from JSON
- Source hit rate
- `recall@k`
- Mean reciprocal rank
- Empty-result and miss accounting
- Unknown retrieval mode rejection

## Next Steps

### P4: Retrieval Quality Loop

Goal: prove retrieval quality before expanding the stack.

- Add a small gold fixture set with queries, expected sources and expected terms.
- Track `recall@k`, mean reciprocal rank, source hit rate and empty-result rate.
- Surface retrieval debug data in tests and API responses before adding more UI polish.
- Keep the first evaluation layer LLM-free so CI can catch retrieval regressions deterministically.

### P5: Real Embedding Backend

Goal: replace the local hash-vector prototype with optional real embeddings without breaking local-first defaults.

- Extract a retriever / vector-backend contract.
- Keep JSON + lexical / hybrid retrieval as the zero-infrastructure fallback.
- Add one optional backend first, likely Qdrant or Chroma; defer FAISS if Windows install friction is high.
- Make embedding provider selection explicit through config.

### P6: Knowledge UI

Goal: turn the Streamlit expander into a usable knowledge panel.

- List indexed documents with chunk count, mtime, hash and status.
- Add query debugging controls for mode, `top_k`, threshold and score preview.
- Add source preview with title, path, page or line range and matched terms.
- Add per-chat RAG scope selection instead of one global toggle only.

### P7: Agentic RAG

Goal: let the model retrieve when it needs evidence instead of always pre-retrieving.

- Add a `retrieve_local_knowledge(query)` tool boundary.
- Route retrieval only for knowledge-grounded questions.
- Allow query rewrite and second-pass retrieval when first-pass evidence is weak.
- Require explicit "not found in local knowledge" behavior when no source is retrieved.
