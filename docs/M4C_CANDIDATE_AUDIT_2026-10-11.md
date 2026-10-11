# M4-C candidate loss diagnostic slice (2026-10-11)

Base: main `7a8b6d5573a202debb1051ecb743aedc5138cbc8` after #204. Branch
`codex/m4c-reader-index-recovery-20261011`; worktree
`D:/study-agent-validation/m4c-reader-index-recovery-20261011`.
This slice follows [the frozen M4-C/Q1 contract](M4C0_ARCHIVE_AND_SLICE1_CONTRACT.md).

## Result and scope

Added `tools/audit_tool_agent_candidates.py`: an offline reader of existing tool-agent
records. It separates shown-but-unread candidates, confirmation/eligibility refusal,
quota or other pre-fetch refusal, failed fetch, and successful transport whose body
support still needs review. A repeated-read refusal cannot erase an earlier success.
Different searches returning the same candidate set are counted separately from
literal duplicate queries. Redirected bodies bind through the recorded source chain.

Raw and filtered per-URL inventories are absent from these records, so those fields
remain unknown. Old records without candidate_trace retain unknown visibility and
fetch outcomes rather than fabricated zeroes. Source bytes are SHA256 pinned;
only same-run full text gets a body hash, never a truncated preview. Q1 states remain
blank for independent review; no automatic SUPPORTED/DERIVED verdict is produced.
This is diagnostic tooling; production execution, providers, URL safety, budget,
learning writes and publication authority are unchanged.

## Reused evidence and actual failure distinction

Replayed 14 existing records from `D:/study-agent-validation/M4C1/runs`,
`M4C2/runs_fixed` and `M4C2/runs_slice_r2`. Reports and input hashes live under
`D:/study-agent-validation/m4c-candidate-audit-20261011/summary.json`.
These previously inspected sealed records are development diagnostics now, **not a
fresh unseen qualification set**. No network re-fetch or model call was made.

| PostgreSQL record | Observed mechanism | Limits |
| --- | --- | --- |
| M4C2/runs_fixed/sealed-postgres-mvcc.new.eval60.json | Four searches return the same five URLs (three repeated result sets); one read fails HTTP 403; the successful 1883-character body is a general tutorial | No proof that the needed deep page existed in the raw results; no automatic semantic label |
| M4C2/runs_slice_r2/sealed-postgres-mvcc.new.eval60.json | Three searches repeat a result set twice; follow exposes and confirms mvcc.html; one successful read obtains 764 characters; the next action rereads it and is correctly refused without quota use | Same-run text is a chapter table of contents plus a general introduction; it does not explain the requested nonblocking mechanism and costs |

The latter case loses effective reading **after** candidate confirmation, not at the
URL gate. The model requests the same chapter again because it wants more content;
the current reader has already returned that chapter index. Discovery and transport
success therefore cannot close the question-support gate.

## Verification and next slice

Impact set: the audit tests plus `test_deep_page_candidates`, `test_link_discovery`,
`test_candidate_funnel`, and `test_research_tool_agent`. Negative controls cover
guessed URLs, excluded confirmed URLs, quota refusal, HTTP failures, missing older
telemetry, previews, redirect binding, repeated reads and source overwrite refusal.
Final impact set: **55 passed / 22.66s**; Ruff and formatter PASS, audit-tool mypy PASS (no production typing scope changed), diff-check PASS. No L3 rerun: this slice only adds offline tooling/tests/docs; the existing 4294/6 production regression remains separate evidence. Exact commit/CI are recovered from Git/PR.

Next bounded implementation: examine navigation-only successful reads and the
legal follow path to their child pages, including shared-read-quota costs. First
reuse recorded candidate/HTML fixtures to prove the relevant child actually exists;
then fix only that contained mechanism. Preserve guessed-URL refusal, defaults
6/4/3/20, existing successes and telemetry-only authority. Use fresh sealed paired
samples for any later quality qualification. Do not bundle providers, free subgoal
planning, answer repair or new UI into that slice. Search quality remains NO-GO.
