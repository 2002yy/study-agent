# Frontend Workspace Notes

The React workspace stores only durable run ids for RAG, memory, tools and news.
Controllers rehydrate server-owned state and keep App shell state small.
Local UI state should not duplicate server-owned business workflow data.
