# Citation, Grounding and Refusal Notes

A trustworthy RAG answer should cite sources that actually support the claims it makes.
Citation precision asks whether cited sources are relevant to the answer; citation recall asks whether the important supporting sources were included.
Claim support is stricter than source retrieval: a retrieved document can be relevant while still failing to justify a specific statement.
Groundedness should decrease when an answer adds assertions that are not supported by the cited evidence.
If the available material does not contain enough evidence to answer a question, the system should say that the answer cannot be established from the current sources instead of inventing a confident response.
When multiple sources are required, the answer should preserve source diversity rather than citing only one convenient document.
Stale or superseded revisions should be treated as leakage when the question asks for current behavior.
