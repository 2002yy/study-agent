# Research source quality v2

Owner: `docs/PROJECT_STATUS.md` Current Handoff. User scope frozen 2026-10-05.
Base: main `5c9409fca58ce569bd82601b98fe87c86ce3c9a8`. Old #161/#164 are donor/experiment branches, not merge candidates.

## Three independently reviewable components

1. Generic scheduling from #161: recovery, candidate lifecycle/deduplication, 3+2 read budget, deadline/cancellation, durable trace. It finds/reads candidates; it does not certify answer quality. No further search expansion.
2. Selective #164 reader/diagnostic fixes: gzip/deflate, tables, author metadata, release-link ranking, actual decision-site Candidate→Read funnel. No old UI, startup scripts, expanded 12→24 pool, provider multiplication or archived qualification artifacts.
3. Official resolver plus final publication boundary: recognize unambiguous supported project/version or paper IDs; official addresses first, legacy recovery only on failure. Registry addresses are not search results and have no factual authority. Real responses yield bounded metadata fields. Every published fact must carry a read digest and an exact span in the parsed metadata body.

## Conservative publication v1

The existing Gate remains the authority for explicit answer-validation plans. Known-source questions without such a plan use server-rendered, parsed official fields; arbitrary model prose is withheld rather than blessed by a relevance model. Other explicit research turns lacking a claim-bound validation plan abstain at the same exit. Generic scheduling remains available but related bodies alone never authorize a final factual answer. Streaming is buffered before publication. Interrupted/failed turns cannot publish unchecked prefixes. This is intentionally conservative and extractive: it does not provide general semantic paraphrase validation, and never grants formal semantic labels or learner mastery.

PyPI upload timestamps are labelled package-upload timestamps, not fabricated release announcements. SQLite changes are limited to one release section. arXiv authors come exclusively from citation metadata, missing authors stay missing, v1 submission history is distinguished from citation/update dates. A models overview without an exact-version reader cannot authorize Opus claims; absence in a page is not proof of model nonexistence.

## Required evidence before merge

- Python official version page is readable, with actual date field.
- FastAPI official metadata/release record identifies the requested/current version with precisely labelled date provenance.
- SQLite official release section retains version, date and changes, excluding adjacent releases.
- arXiv authors have actual metadata support; absent/tampered author fields and publication spans are rejected.
- Opus adjacent-version material cannot escape the answer gate; missing exact-version evidence yields an explicit abstention.
- All five live observations use actual production gateway/recovery and final ChatService/SQLite publication, not browser-tool snapshots or an alternative fetch-only path. Bind base/head, source/module digests, source times and resulting answers. A clean exact-head observation is mandatory; preserve old failed rows.
- Focused impact set, named retrieval integration gate, one final backend L3, Ruff, mypy no-new-errors, diff/scope/clean checks, exact-head CI, final review and exact-main CI. No merge merely because mocks or relevance checks pass.

Premium Web Search (Exa/Tavily), free rescue and Platform Specialists remain separate follow-up layers. No paid keys, login profiles, automatic specialist promotion, new semantic judge or community-as-official authority in this batch.
