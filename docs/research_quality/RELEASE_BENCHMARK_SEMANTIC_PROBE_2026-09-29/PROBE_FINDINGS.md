# §159 DeepSeek semantic probe findings

The owner explicitly allowed DeepSeek API inference for this personal project.
The frozen source snapshot and local reader remain byte-bound and offline;
model inference is remote and must be disclosed. This changes the planned
**future** execution contract. It does not retroactively make the existing
`release-benchmark-observation-v1` remote-inference compatible.

The probe reviewed the two answers in answer bundle SHA-256
`5de1ff1e94514187d709a3ce147a6162930f9f99b3cdd80d47f045b278ab2226`.
The answer model was DeepSeek flash and the diagnostic reviewer was DeepSeek
pro. Both are from the same provider family; this is a cross-model check, not
an independent or qualified judge attestation.

| Run | Code SHA | Artifact SHA-256 | Target controls detected | Consistency |
| --- | --- | --- | --- | --- |
| Initial | `9732ba63df2c6ba5fa375c39857e79537db65ade` | `a1639397fc06e00289cf4ba89c29369861e26096e22acd9950bfc8aabe7cf63c` | 2/6: both missing-aspect controls; both wrong-citation and both unsupported-claim dimension checks missed. | Unsupported-claim issues were emitted while `evidence_grounding` still said `supported`. |
| Explicit locator and consistency prompt | `87d39a61dbbae7d3243c75b81a98eeb6dde3bd71` | `d93e1dd8f8949dd88d015334289245868f383b8ed82bbb077e03551b58ab7622` | 6/6 target dimensions detected. | 8/8 assessments internally consistent. Five of six controls also received at least one issue type beyond their target; the probe is not calibrated for clean diagnosis. |

On both runs, the actual TEXT and PDF answers were marked `covered`,
`supported`, and `supported` by this diagnostic model with no issues. The
author-side source check is recorded beside the answer bundle. Neither check
is a formal manual or qualified semantic label. The probe records the full
prompt and raw model response for every answer/control; both artifacts say
`formal_semantic_label=false`, `release_observation=false`, `release_gate=NO_GO`.

Next: version the observation contract for **frozen source + disclosed remote
inference**, including a fresh read timestamp and answer digest. Keep v1
offline semantics intact. Then obtain an authorized semantic assessment and
calibrate judge specificity before any semantic score is observed.
