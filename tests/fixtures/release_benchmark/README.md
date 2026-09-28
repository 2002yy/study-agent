# Release benchmark plan

`plan_v1.json` declares **56 target slots** across frozen/live and five modalities. It contains no questions, evidence, or gold labels. Six reviewed pilot cases are admitted under the personal-project owner decision; the release gate remains **NO-GO (6/56)**.

Run the offline inventory:

```powershell
.venv\Scripts\python.exe tools/check_release_benchmark_plan.py
```

The report binds this plan and four existing calibration/qualification assets to SHA-256 digests. The 10 frozen traps, 10 live traps, 12 RQ1-C holdout cases, and six Q1–Q6 multimodal controls are excluded from release scoring.

`registry_v1.json` and `gold_v1.json` are separate, strictly parsed manifests bound to the plan and each other. Gold is scorer-only input; an evaluated system must see only the case question and permitted sources. Frozen sources belong under `sources/` and must pass byte SHA-256 checks; live cases carry source locators and freshness requirements, never cached answers or page bodies. Distinct annotator/reviewer names and complete source, leakage, difficulty, and modality checks make a case a **reviewed candidate**. For this personal project, the owner delegated acceptance of the six-case content review; structurally reviewed cases now count toward admission. This is an owner governance decision, not a cryptographically verified external attestation or release GO.

The first independent-source pilot registers **six reviewed cases**: five frozen and one live. All six gold rows are `approved` with reviewer `chatgpt-independent-review-1` and four review flags true. The raw unsigned review is preserved at `docs/research_quality/RELEASE_BENCHMARK_SIX_CASE_REVIEW_2026-09-29.txt`; the owner accepted its content with noted transcription defects. Source bytes were fetched on 2026-09-28 UTC from these original publishers:

| Candidate | Original source | Frozen artifact |
| --- | --- | --- |
| `REL-F-TEXT-001` | [NOAA storm surge explanation](https://oceanservice.noaa.gov/facts/stormsurge-stormtide.html) | `sources/noaa_storm_surge_2026-09-28.html` |
| `REL-F-PDF-001` | [NASA Moon lithograph](https://science.nasa.gov/wp-content/uploads/2024/01/62217main-moon-lithograph.pdf), page 2 | `sources/nasa_moon_lithograph.pdf` |
| `REL-F-IMAGE-001` | [USGS shield-volcano diagram](https://www.usgs.gov/media/images/shield-volcano-diagram), [original raster](https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/s3fs-public/thumbnails/image/4%20shield%20volcano%20cross%20section.gif) (USGS marks it Public Domain) | `sources/usgs_shield_volcano.gif`; single raster uses page 1 |
| `REL-F-CHART-001` | [NASA GISTEMP historical annual chart](https://data.giss.nasa.gov/gistemp/history/output/history_loti_ann.pdf), page 1 | `sources/nasa_giss_history_annual.pdf` |
| `REL-F-MIXED-001` | [NWS heat-safety one-pager](https://www.weather.gov/media/twc/HeatSafety-OnePager.pdf), page 1 | `sources/nws_heat_safety_onepager.pdf` |
| `REL-L-TEXT-001` | [USGS magnitude 4.5+ past-day feed](https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson) | Live locator only; no snapshot |

Each frozen file's exact SHA-256 lives in the registry. `.gitattributes` disables text conversion and text diff for this source directory so checked-out bytes remain identical to the publisher snapshots. The chart has multiple colored curves without a legend in the snapshot; its question deliberately asks only about the black curve and axes. The dated Moon handout and historical chart are not current-fact evidence. The six-case review checked original-source support, leakage, difficulty, modality, and gold; later cases need their own review.

The opt-in text/PDF pilot uses a snapshot allowlist, rechecks bytes on each read, blocks Python socket connections during execution, and runs the real `WebLookupService` against a temporary SQLite database. The PDF reader extracts only the declared page. Image and chart candidates enter the existing visual escalation pipeline with page/region provenance; PDF visuals are rendered locally with Poppler when available. With no qualified vision adapter injected, visual outcomes stay `unavailable`:

```powershell
.venv\Scripts\python.exe tools/run_release_benchmark_frozen_pilot.py --case-id REL-F-TEXT-001
.venv\Scripts\python.exe tools/run_release_benchmark_frozen_pilot.py --case-id REL-F-PDF-001
.venv\Scripts\python.exe tools/run_release_benchmark_frozen_pilot.py --case-id REL-F-IMAGE-001
.venv\Scripts\python.exe tools/run_release_benchmark_frozen_pilot.py --case-id REL-F-CHART-001
.venv\Scripts\python.exe tools/run_release_benchmark_frozen_pilot.py --case-id REL-F-MIXED-001
```

These outputs are diagnostic runtime transcripts, not scored release observations. The guard covers Python socket connects in this process; it is not an OS-level network sandbox. An absent PDF renderer is reported as `unavailable`, and a present renderer does not supply semantic vision. The mixed case records its PDF text read and visual read separately.

To record the five approved **frozen** reader pilots against one clean code head and score them, run:

```powershell
.venv\Scripts\python.exe tools/run_release_benchmark_recorded_pilot.py --output-dir .workbuddy/release-recorded-pilot
```

The output directory contains `pilot_bundle.json`, `observation.json`, and `score.json`. The observation binds the bundle's exact byte SHA-256, registry/gold digests, source locator/SHA/page/region, and code head. It maps WebLookupService's local source IDs back to registry IDs only after checking the source binding. Reader success does not imply an answer: text/PDF cases stay `unavailable` because answer generation was not run; image/chart/mixed stay `unavailable` without qualified visual interpretation. The live case remains `missing` until a real manual live read with an actual human reviewer is recorded. The scorer still reports `NO_GO`.

The gold spells out source-backed answer criteria. Prepare a packet containing each selected case, source SHA, substantive gold and review checklist:

```powershell
.venv\Scripts\python.exe tools/check_release_benchmark_review.py
```

The stricter verification paths remain available. A collaborator can submit an exact-head GitHub PR approval with the packet marker and checklist (`--pr-number <number> --review-id <id>`), or an operator can verify an artifact signed by an out-of-band trusted issuer (`--pr-number <number> --artifact <path>`). Either check is diagnostic and does not itself admit cases. The personal-project owner acceptance is recorded in gold and the handoff; it does not create a signed artifact. Qualified semantic labels, locked thresholds, and the remaining 50 admitted/executed cases are absent.

Validate registry and gold, then inspect the fail-closed score report:

```powershell
.venv\Scripts\python.exe tools/check_release_benchmark_registry.py
.venv\Scripts\python.exe tools/score_release_benchmark.py
```

The scorer accepts recorded frozen and manual live observations with an exact code SHA via `--observation <path> --expected-code-sha <sha>`. It checks manifest/gold digests, mode and network declarations, per-source locator/read-state/time/page/region/review metadata, and metric labels. Original-source recall and read success are computed from read records. It does **not** execute a web lookup, attest that an offline run had no network, qualify a semantic judge, or infer missing labels. Observed values and missing/unavailable/failure counts stay separate by case and stratum; the current score remains **NO-GO**.

Exit code 0 means the **plan and inventory are valid**. It does not mean release GO; consumers must read `release_gate`.
