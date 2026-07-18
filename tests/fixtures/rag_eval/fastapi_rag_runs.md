# FastAPI Durable RagRun and Index Activation

The FastAPI service exposes durable RAG write and query runs so long operations have a stable owner instead of existing only inside one request.
A query run records the retrieval mode, result count, debug diagnostics and the active index version used for the search.
Upload and rebuild writes first construct a staged index version and complete required vector work before activation.
If a required vector stage fails, activation is skipped and the previous active version remains the source of truth.
Append-style upload replaces an older revision of the same document identity instead of keeping duplicate active revisions.
Rebuild replaces the whole selected corpus and therefore needs a deliberate user action at the knowledge-management boundary.
The durable run model is an implementation detail; the learner-facing flow should still end in a clear next action such as start learning or ask a question.
