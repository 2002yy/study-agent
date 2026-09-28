# Release benchmark plan

`plan_v1.json` declares **56 target slots** across frozen/live and five modalities. It contains no questions, evidence, gold labels, or admitted release cases. The release gate remains **NO-GO (0/56)**.

Run the offline inventory:

```powershell
.venv\Scripts\python.exe tools/check_release_benchmark_plan.py
```

The report binds this plan and four existing calibration/qualification assets to SHA-256 digests. The 10 frozen traps, 10 live traps, 12 RQ1-C holdout cases, and six Q1–Q6 multimodal controls are excluded from release scoring.

`registry_v1.json` and `gold_v1.json` are separate, strictly parsed manifests bound to the plan and each other. Both currently contain **zero cases**. Gold is scorer-only input; an evaluated system must see only the case question and permitted sources. Frozen sources belong under `sources/` and must pass byte SHA-256 checks; live cases carry source locators and freshness requirements, never cached answers or page bodies. Distinct annotator/reviewer names and complete source, leakage, difficulty, and modality checks make a case a **reviewed candidate** for pilot scoring. JSON fields do not attest that independent review happened, so this batch grants no release admission; the gate remains NO-GO until external review and qualification are complete.

Validate registry and gold, then inspect the fail-closed score report:

```powershell
.venv\Scripts\python.exe tools/check_release_benchmark_registry.py
.venv\Scripts\python.exe tools/score_release_benchmark.py
```

The scorer accepts recorded frozen and manual live observations with an exact code SHA via `--observation <path> --expected-code-sha <sha>`. It checks manifest/gold digests, mode and network declarations, per-source locator/read-state/time/page/region/review metadata, and metric labels. Original-source recall and read success are computed from read records. It does **not** execute a web lookup, attest that an offline run had no network, qualify a semantic judge, or infer missing labels. Observed values and missing/unavailable/failure counts stay separate by case and stratum; the current score remains **NO-GO**.

Exit code 0 means the **plan and inventory are valid**. It does not mean release GO; consumers must read `release_gate`.
