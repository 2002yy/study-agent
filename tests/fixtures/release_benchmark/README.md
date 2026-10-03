# Release benchmark plan

`plan_v1.json` declares **56 target slots** across frozen/live and five modalities. It contains no questions, evidence, gold labels, or admitted release cases. The release gate remains **NO-GO (0/56)**.

Run the offline inventory:

```powershell
.venv\Scripts\python.exe tools/check_release_benchmark_plan.py
```

The report binds this plan and four existing calibration/qualification assets to SHA-256 digests. The 10 frozen traps, 10 live traps, 12 RQ1-C holdout cases, and six Q1–Q6 multimodal controls are excluded from release scoring. New case registry, independent gold, replay, and scorer must follow the §151 contract in `docs/PROJECT_STATUS.md`.

Exit code 0 means the **plan and inventory are valid**. It does not mean release GO; consumers must read `release_gate`.
