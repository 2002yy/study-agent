# Failure-State Writer Inventory (Batch B input)

Static scan captured during Batch A. Batch B was implemented from
`main@2c1e15c` on `codex/rqce-p1-failure-state-batch-b`.

Batch B scope is intentionally narrower than every textual `type(exc)` match
below: only Claim Engine `RuntimeFailure` writers and active search/read outcome
projection are failure-truth owners. Other matches are domain-local diagnostic
strings and remain unchanged unless their own contract batch names them.

Batch B local closure (implementation commit `7f5eb7d`, pushed; CI pending):

- `src/application/active_research_runtime.py`: all RuntimeFailure producers use
  the canonical factory, deterministic ID and append-by-ID; policy double-count
  is removed; search/read outcomes project bounded local codes; hard budget is
  stop truth only.
- `src/web/research/runtime.py`: model/search/read interruption recovery emits
  stage-specific canonical v2 failures with `interrupted_unknown` in detail;
  new cursors default to v2 while explicitly loaded v1 cursors remain v1.
- Verification: focused 88/88 + final incremental 7/7; full pytest 1510/1510;
  Ruff; mypy baseline 122 <= 128; diff-check.
- Deferred to Batch C: StopGate typing, API/UI mapping and full
  writer-code-stop-consumer matrix acceptance.

Post-merge P2 finding and hotfix (2026-09-02):

- PR #139 merged before the delayed review thread identified that canonical v2
  interruption metadata is not representable in the v1 three-field wire shape.
- Hotfix rule: v1 recovery alone preserves `code="interrupted_unknown"`; v2
  recovery remains stage-specific canonical code with interruption detail and
  attempt identity.
- Two interrupted external attempts are terminally projected as bounded
  `search_failed` / `read_failed`; attempt 2 is never physically repeated.
- Batch C stays blocked until hotfix exact-head and exact-main CI are green.

## src\api\routes\chat_routes.py

- `src\api\routes\chat_routes.py:165: type(exc).__name__: {"message": str(exc), "error_type": type(exc).__name__},`
- `src\api\routes\chat_routes.py:260: type(exc).__name__: {"message": str(exc), "error_type": type(exc).__name__},`

## src\api\routes\wechat_routes.py

- `src\api\routes\wechat_routes.py:177: type(exc).__name__: "error", {"message": str(exc), "error_type": type(exc).__name__}`

## src\application\active_research_runtime.py

- CLOSED in Batch B: `_append_failure` is the single RuntimeFailure writer and
  always calls `build_runtime_failure` plus `append_runtime_failure`.
- CLOSED in Batch B: search/read outcome `error_code` is bounded to
  `search_failed` / `read_failed`; dynamic data is projected to the matching
  RuntimeFailure fields.
- CLOSED in Batch B: `type(exc).__name__` is never a top-level failure code;
  reader/runtime exceptions store it only as `exception_type`.
- INTENTIONALLY UNCHANGED: checkpoint `stop_reason=""` is non-terminal clearing,
  not a failure writer.

## src\application\github_snapshot_service.py

- `src\application\github_snapshot_service.py:255: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`

## src\application\learning_freshness.py

- `src\application\learning_freshness.py:170: type(exc).__name__: message = f"blob_read_failed: {type(exc).__name__}: {exc}"`
- `src\application\learning_freshness.py:235: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`

## src\application\learning_resume.py

- `src\application\learning_resume.py:217: type(exc).__name__: "unavailable_reason": f"{type(exc).__name__}: {exc}",`

## src\application\learning_revalidation.py

- `src\application\learning_revalidation.py:126: type(exc).__name__: return f"unavailable: {type(exc).__name__}: {exc}"`

## src\application\web_lookup_service.py

- `src\application\web_lookup_service.py:743: stop_reason writer: stop_reason="chat_tool_loop_failed",`
- `src\application\web_lookup_service.py:1098: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`
- `src\application\web_lookup_service.py:1101: type(exc).__name__: f"source read failed ({url}): {type(exc).__name__}: {exc}"`
- `src\application\web_lookup_service.py:1597: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`

## src\infrastructure\sqlite\database.py

- `src\infrastructure\sqlite\database.py:403: stop_reason writer: stop_reason = 'legacy_run_interrupted',`

## src\llm_client.py

- `src\llm_client.py:626: type(exc).__name__: result = {"error": f"{type(exc).__name__}: {exc}"}`

## src\news\article_fetcher.py

- `src\news\article_fetcher.py:367: type(exc).__name__: reason=f"exception:{type(exc).__name__}:{exc}",`

## src\news\search_sources\searxng_source.py

- `src\news\search_sources\searxng_source.py:201: type(exc).__name__: _LAST_SEARXNG_ERROR = f"{type(exc).__name__}: {exc}"`

## src\pedagogy\evaluation.py

- `src\pedagogy\evaluation.py:231: type(exc).__name__: reasons=(f"semantic_evaluator_failed:{type(exc).__name__}",),`

## src\rag\answer_claim_eval.py

- `src\rag\answer_claim_eval.py:265: type(exc).__name__: parse_error=f"{type(exc).__name__}: {exc}",`
- `src\rag\answer_claim_eval.py:457: type(exc).__name__: parse_error=f"producer_failed:{type(exc).__name__}",`

## src\rag\provider_replay.py

- `src\rag\provider_replay.py:206: type(exc).__name__: parse_error=f"{type(exc).__name__}: {exc}",`
- `src\rag\provider_replay.py:280: type(exc).__name__: "error_type": type(exc).__name__,`

## src\repositories\web_lookup_repository.py

- `src\repositories\web_lookup_repository.py:632: stop_reason writer: stop_reason = 'user_cancelled', completed_at = ?,`
- `src\repositories\web_lookup_repository.py:670: stop_reason writer: research_context = ?, stop_reason = 'user_cancelled',`

## src\tools\persistent_web_agent.py

- `src\tools\persistent_web_agent.py:169: type(exc).__name__: f"ResearchRun create failed: {type(exc).__name__}: {exc}"`
- `src\tools\persistent_web_agent.py:235: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`
- `src\tools\persistent_web_agent.py:330: type(exc).__name__: error = f"{type(exc).__name__}: {exc}"`
- `src\tools\persistent_web_agent.py:423: type(exc).__name__: error = f"{type(exc).__name__}: {exc}"`
- `src\tools\persistent_web_agent.py:424: type(exc).__name__: cancelled = "ResearchCancelled" in type(exc).__name__ or (`
- `src\tools\persistent_web_agent.py:455: type(exc).__name__: return f"ResearchRun persistence failed: {type(exc).__name__}: {exc}"`

## src\tools\web_agent.py

- `src\tools\web_agent.py:386: type(exc).__name__: return WebToolTrace(error=f"{type(exc).__name__}: {exc}")`

## src\web\github_change_impact.py

- `src\web\github_change_impact.py:216: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`

## src\web\github_freshness.py

- `src\web\github_freshness.py:38: type(exc).__name__: return f"{type(exc).__name__}: {exc}"`

## src\web\github_history.py

- `src\web\github_history.py:63: type(exc).__name__: return None, f"{type(exc).__name__}: {exc}"`
- `src\web\github_history.py:239: type(exc).__name__: return None, f"{type(exc).__name__}: {exc}"`
- `src\web\github_history.py:270: type(exc).__name__: error=f"{type(exc).__name__}: {exc}",`
- `src\web\github_history.py:516: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`
- `src\web\github_history.py:639: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`

## src\web\github_paginated_base.py

- `src\web\github_paginated_base.py:156: stop_reason writer: stop_reason = "provider_exhausted"`
- `src\web\github_paginated_base.py:166: stop_reason writer: stop_reason = "request_budget_exhausted"`
- `src\web\github_paginated_base.py:182: type(exc).__name__: _provider_error(operation, f"{type(exc).__name__}: {exc}")`
- `src\web\github_paginated_base.py:184: stop_reason writer: stop_reason = "provider_error"`
- `src\web\github_paginated_base.py:191: stop_reason writer: stop_reason = "provider_error"`
- `src\web\github_paginated_base.py:239: stop_reason writer: stop_reason = "item_budget_reached"`
- `src\web\github_paginated_base.py:246: stop_reason writer: stop_reason = "provider_exhausted"`
- `src\web\github_paginated_base.py:252: stop_reason writer: stop_reason = "provider_error"`
- `src\web\github_paginated_base.py:255: stop_reason writer: stop_reason = "page_budget_exhausted"`
- `src\web\github_paginated_base.py:338: stop_reason writer: stop_reason = "provider_exhausted"`
- `src\web\github_paginated_base.py:360: stop_reason writer: stop_reason = "page_budget_exhausted"`
- `src\web\github_paginated_base.py:367: stop_reason writer: stop_reason = "provider_error"`
- `src\web\github_paginated_base.py:373: stop_reason writer: stop_reason = "request_budget_exhausted"`
- `src\web\github_paginated_base.py:390: type(exc).__name__: _provider_error(operation, f"{type(exc).__name__}: {exc}")`
- `src\web\github_paginated_base.py:392: stop_reason writer: stop_reason = "provider_error"`
- `src\web\github_paginated_base.py:400: stop_reason writer: stop_reason = "provider_error"`
- `src\web\github_paginated_base.py:420: stop_reason writer: stop_reason = "item_budget_reached"`
- `src\web\github_paginated_base.py:422: stop_reason writer: stop_reason = "provider_exhausted"`

## src\web\github_provider_pagination.py

- `src\web\github_provider_pagination.py:133: stop_reason writer: stop_reason = "provider_exhausted"`
- `src\web\github_provider_pagination.py:155: stop_reason writer: stop_reason = "item_budget_reached"`
- `src\web\github_provider_pagination.py:159: stop_reason writer: stop_reason = "provider_exhausted"`
- `src\web\github_provider_pagination.py:164: stop_reason writer: stop_reason = "page_budget_exhausted"`

## src\web\github_reader.py

- `src\web\github_reader.py:233: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`
- `src\web\github_reader.py:294: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`

## src\web\github_snapshot.py

- `src\web\github_snapshot.py:293: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`
- `src\web\github_snapshot.py:377: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`

## src\web\github_work_items.py

- `src\web\github_work_items.py:253: type(exc).__name__: return None, _provider_error(operation, f"{type(exc).__name__}: {exc}")`
- `src\web\github_work_items.py:378: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`
- `src\web\github_work_items.py:1155: type(exc).__name__: "error": f"{type(exc).__name__}: {exc}",`

## src\web\lsp_adapter.py

- `src\web\lsp_adapter.py:112: type(exc).__name__: error=f"{type(exc).__name__}: {exc}",`

## src\web\provider_health.py

- `src\web\provider_health.py:50: type(exc).__name__: return False, f"{type(exc).__name__}: {exc}"`

## src\web\research\candidate_pool.py

- `src\web\research\candidate_pool.py:160: type(exc).__name__: provider_errors = (f"search_exception:{type(exc).__name__}",)`

## src\web\research\model_gateway.py

- `src\web\research\model_gateway.py:389: type(exc).__name__: error_type = type(exc).__name__`

## src\web\research\provider_search.py

- `src\web\research\provider_search.py:362: type(exc).__name__: name = type(exc).__name__.casefold()`

## src\web\research\runtime.py

- INTENTIONALLY UNCHANGED: query/read `from_dict` accepts bounded legacy values;
  reader compatibility does not enforce the new-writer catalog.
- CLOSED in Batch A: direct `RuntimeFailure(...)` construction remains private
  to the validated `build_runtime_failure` factory.
- CLOSED in Batch B: interrupted model/external recovery uses the canonical
  factory and append-by-ID with stage-specific code plus
  `detail="interrupted_unknown"`.

## src\web\tool_gateway.py

- `src\web\tool_gateway.py:449: type(exc).__name__: return [], f"bing_rss:{type(exc).__name__}:{exc}"`
- `src\web\tool_gateway.py:492: type(exc).__name__: return [], f"duckduckgo_html:{type(exc).__name__}:{exc}"`

## src\web\tree_sitter_backend\__init__.py

- `src\web\tree_sitter_backend\__init__.py:58: type(exc).__name__: parse_error=f"{type(exc).__name__}: {exc}",`

## src\wechat_service.py

- `src\wechat_service.py:373: type(exc).__name__: data={"error_type": type(exc).__name__},`
- `src\wechat_service.py:403: type(exc).__name__: data={"error_type": type(exc).__name__},`

