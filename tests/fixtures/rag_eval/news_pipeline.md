# Web Research Source Safety and Evidence Trace

The web research pipeline starts from a learner question that needs external facts, not from a separate search-engine workspace.
Feed entries and discovered URLs are normalized before fetching so duplicates and redirect chains can be traced consistently.
Unsafe redirects, loopback addresses and private-network targets are blocked before article retrieval to reduce SSRF risk.
Research runs preserve query attempts, selected and rejected sources, reading outcomes, warnings, stop reasons and provider completeness.
A completed answer should disclose the evidence actually used rather than only listing every search result that was seen.
If a run fails or is cancelled, durable state supports retry or resume without pretending that incomplete evidence was complete.
The purpose of the trace is to let the learner verify externally sourced claims and continue the same conversation with trustworthy context.
