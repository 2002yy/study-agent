# §161 semantic calibration — diagnostic only

The DeepSeek pro probe reviewed the two frozen-source DeepSeek flash answers in
bundle SHA-256 `90d5264345ce23da3158ad4796e549fc04bcbb024ad021399aa21fc56ed49ace`.
The probe ran at review code head `adb409c73b4c491da34f3748d6836d23f04620d2`;
its canonical artifact SHA-256 is
`cc077b526092d7fac95c56d567b18c31e323933565fcc4c8fbc23ffcfcdae643`.
The calibration ran at code head `c41816a386d5120a4c152b874598feb14e61fffb`;
its canonical artifact SHA-256 is
`eabc3b04fc5aac004c1c564e2271b3486269a5b35bf757601cc85c9337191bbe`.

The saved raw responses and prompts replay exactly against the registered frozen
sources and answer bundle. Both actual answers received clean model diagnostics.
Target control detection was **6/6**, but specificity was **1/6**:

| Case | Wrong locator | Missing aspect | Unsupported sentence |
| --- | --- | --- | --- |
| TEXT | Grounding was also marked as a gap. | Grounding was also marked as a gap. | Coverage was also marked partial. |
| PDF | Coverage and grounding were also marked as gaps; wrong-citation and unsupported issues were repeated. | Grounding and citation support were also marked as gaps. | Specificity passed. |

The calibration gate is **fail**. The reviewer is from the same provider family
as the answer model. `qualified_judge=false`, `formal_semantic_label=false`,
`release_observation=false`, and release remains **NO-GO**. The original v2
observation and score retain zero observed semantic labels.
