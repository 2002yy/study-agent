# Identity resolution and version evidence binding

Owner: `docs/PROJECT_STATUS.md` Current Handoff. User decision: 2026-10-05.
Independent branch from main `5c9409fca58ce569bd82601b98fe87c86ce3c9a8`.

Models may propose intent, search strategy, candidate priority and source spans.
Only deterministic checks may establish entity/version identity and bind a quote
to a successful read. Relevance is not factual support; binding is not truth.

## Foundation scope

`ResearchIdentity` resolves explicitly supported product aliases and exact version
schemes. Python/FastAPI missing patch components normalize to zero; CUDA missing
minor components normalize to zero. Model generations retain precision. A stable
release differs from its prerelease. Unknown products/syntax remain unknown.
Exact Python 3.14 means 3.14.0 in this rule; requesting the latest stable 3.14.x
requires a separate family intent and an official selection, never wildcard
matching by this identity function. No alias equates Qwen3 with Qwen3.5 or GPT6
with GPT6.1.

The trusted reader constructs one immutable document with a read ID, final URL,
decompressed payload digest, canonical text digest and parser-derived heading
boundaries. Digests explicitly describe these representations, not wire bytes.
An `EvidenceProposal` supplies identity, read ID, URL, text digest, exact heading
span, exact quote span and quote. The verifier requires all read identifiers and
digests to match, a single unambiguous version identity in the heading, the quote
inside that section, exact text equality and no different identity in the quote.
Sections conservatively end at every next heading, including nested headings.
Missing anchors, fabricated spans, modified text and adjacent versions yield
`UNKNOWN`. Script/style contents do not create visible headings.

`VersionEvidenceBinding` proves source location and version scope only. It does
not certify benchmark interpretation, author/date extraction, official source
authority or assertion support. The existing evidence/publication gate retains
those responsibilities. Comparisons need separate supported assertions and
bindings for both identities; mixed-version quotes are rejected in this initial
implementation.

## Python activation; broader qualification remains open

Base now includes merged research #171, main `090678a2`. Python's official
resolver consumes product-specific exact identity; the recovery marker may be
skipped only for matching reader-owned project/version fields, exact spans and
body digest on the registered official URL. A candidate identity flag is never
accepted. Other projects and generic search retain their existing marker gates.
Python latest-family, wildcard and prerelease requests are not silently rewritten
as the initial stable release; those intents still need separate planning.

The Python release-date adapter uses the reader-owned heading document. Label
matching is case-insensitive, dates accept explicit ISO or English month/day/year
formats and validate the calendar, and absent/invalid/ambiguous/adjacent-section
fields stay absent. Published parsed metadata includes a source-binding audit of
the original label/date quote, heading and quote spans, canonical text digest and
decoded-payload digest; wire transport digest remains distinct. This binds the
source location, while the existing publication gate retains final authority.

No new LLM extractor, paid or login provider is added. Other anchor kinds remain
unknown. UTF-8 and conservative per-heading scope limitations remain. Opus's
independent activation is limited by `OPUS_LOOKUP_BINDING_CONTRACT.md`: an exact
page may support its bound positioning quote; a mixed overview cannot authorize
model claims, capabilities or comparisons.

Acceptance: named identity/source-quality impact and retrieval integration gates,
mypy no-new-errors, Ruff/diff/scope checks, one clean candidate backend L3 and a
real Python ChatService/SQLite observation bound to code/source/answer digests and
times. Do not modify tracked documents during the clean full suite. No general
semantic-judge or learner-mastery authority is granted by these tests. Research
qualification stays NOT CLOSED. Python/Opus exercise the shared foundation through
Lookup examples; Lookup budget/coverage, Standard multi-source/conflict/comparison
and Deep Evidence Gain/convergence/interruption qualifications remain separate.
