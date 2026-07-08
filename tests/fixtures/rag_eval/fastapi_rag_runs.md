# FastAPI RagRun Notes

FastAPI exposes durable RagRun endpoints for query, upload and rebuild.
Each query run persists retrieval mode, result count, debug diagnostics and index version.
Upload and rebuild writes use staging versions before activating the local knowledge index.
