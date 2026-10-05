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

## Main merge gate (user revision, 2026-10-05)

Merge readiness and final qualification are separate decisions. A bounded version
may enter main with documented gaps when verified source paths improve on main,
actual ChatService/SQLite observations support the shipped capabilities, unsupported
facts and interrupted prefixes cannot bypass publication checks, regressions pass,
the reviewed head has green CI, and no known dangerous regression remains.

The verified delivery paths are FastAPI, SQLite and arXiv. Official registry seeds
are still candidates rather than evidence: exact registered identity authorizes a
read, while only validated response metadata authorizes publication. Python and
Opus remain documented follow-up gaps; this merge does not mark the phase CLOSED.
Unbound research without a claim-validation plan conservatively withholds prose;
the existing explicit answer-validation Gate remains available. This is a known
answer-coverage limitation, not a general semantic synthesis qualification.

Ship production recovery/scheduling, official-first routing, bounded readers,
candidate/read diagnostics, publication safety and regression tests. Do not ship
temporary benchmark scripts/manifests/artifacts, failed experimental mechanisms,
Python hacks, unverified Opus assumptions or unrelated frontend changes.

## Final qualification gate (not CLOSED)

This is the source-quality gate for shared capabilities and Lookup examples, not
the closure of all research tiers. The frozen order remains shared foundation →
Lookup qualification → Standard multi-source/comparison/conflict qualification →
Deep contract and multi-round Evidence Gain/saturation/interruption qualification.
The three approximate strategy budgets and the current Opus activation boundary
are recorded in `OPUS_LOOKUP_BINDING_CONTRACT.md`; they do not change runtime
budgets in this slice. Passing Python/Opus does not close Standard or Deep.

- Python official version page is readable, with actual date field.
- FastAPI official metadata/release record identifies the requested/current version with precisely labelled date provenance.
- SQLite official release section retains version, date and changes, excluding adjacent releases.
- arXiv authors have actual metadata support; absent/tampered author fields and publication spans are rejected.
- Opus adjacent-version material cannot escape the answer gate; missing exact-version evidence yields an explicit abstention.
- All five live observations use actual production gateway/recovery and final ChatService/SQLite publication, not browser-tool snapshots or an alternative fetch-only path. Bind base/head, source/module digests, source times and resulting answers. A clean exact-head observation is mandatory; preserve old failed rows.
- Full benchmark qualification remains required before CLOSED. No qualification merely because mocks or relevance checks pass.

The main merge still requires the focused impact set, retrieval integration gate,
one final backend L3, Ruff, mypy no-new-errors, diff/scope/clean checks, exact-head
CI and final review, followed by exact-main CI. Live failed samples are retained
outside the repository and distinguish source acquisition from final publication.

Premium Web Search (Exa/Tavily), free rescue and Platform Specialists remain separate follow-up layers. No paid keys, login profiles, automatic specialist promotion, new semantic judge or community-as-official authority in this batch.
