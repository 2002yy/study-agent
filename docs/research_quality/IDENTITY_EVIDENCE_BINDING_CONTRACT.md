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

## Activation and qualification remain open

These modules are initially inert: no gateway, chat, persistence or publication
consumer has been switched. There is no new LLM extractor or paid/login provider.
URL/metadata/release-ID anchor alternatives are not implemented and must remain
unknown. Reader-side trusted provenance must be preserved when wiring callers;
model-supplied HTML cannot be passed as a successful read.

Next integration slice after research-source-quality-v2 delivery: use normalized
verified Python identity instead of the generic model-name marker; extract the
actual labelled release date with deterministic date validation; verify the
real Python ChatService/SQLite result and wrong-version/missing-date controls.
Opus follows with actual official version anchors and adjacent-version controls.
Do not claim either gap fixed or final research qualification CLOSED from these
foundation tests. This branch does not expand the current merge candidate.
