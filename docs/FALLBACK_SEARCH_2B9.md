# B-Search-2B9 — cross-topic generalization (initial probe)

Real `deepseek-flash`, live channels, full-text capture (`tools/eval_2b9_crosstopic.py`).
Raw: `model-driven-search-2b9/crosstopic.json`.

| task | stop | rounds | reads | read URL(s) | rejections |
|---|---|---|---|---|---|
| factorio (train interrupts vs fixed schedule) | round_limit | 6 | 1 | `wiki.factorio.com/Main_Page/zh` (main page, not the mechanics article) | 0 |
| go_rules (提子 / 打劫; not the Go language) | round_limit | 6 | 1 attempt | **none readable** | 0 |
| python_reference (3.15.0 release) | round_limit | 6 | **0** | — | 0 |

## Reading (honest)
- **No transfer demonstrated.** The Factorio task reached only a wiki **main page**, not the
  train-interrupt/mechanism article; the Go-rules task produced no readable body at all; and the
  Python **regression reference did not reproduce** the earlier success (0 reads this run).
- Failures span layers: **recall** (only a landing page surfaced), **reader** (Go page unreadable),
  and **decision** (nothing `finished`). `entry_exclusions` never fired here because these topics
  are not RSS-feed-driven — the semantic admission has no feed to gate on.
- Full-text artifacts (length, SHA256, final URL, truncation, head) were captured for the one body
  that read, so bodies are auditable — not the 600-char preview.

## Implication
2B8's mechanism is a **feed/search admission layer**, and these cross-topic tasks do not run on a
feed, so they exercise recall + reader + decision much more than admission. The system currently
looks **Python-release-shaped**, not generally research-capable.

## Next (do NOT hardcode per-topic rules)
1. Controlled re-check of the Python reference (run variance vs real regression).
2. Source discovery beyond a single RSS feed (so mechanism/rule topics can find wiki/article pages).
3. Independent full-text annotation of the captured bodies (truth, not `assess_body`).
