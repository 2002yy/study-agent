"""§43A selector schema probe: classify the raw selector responses.

Samples the selector transport directly (same system prompt, same frozen
candidate pool, json_object + thinking-off, same model) and classifies every
raw response by shape, so ``invalid_schema`` can be split into transport /
representation forms before any normalization is added:

    contract_shape             {"urls": [str, ...]}
    url_array                  [str, ...]  (unambiguous URL array)
    fenced_json                valid JSON wrapped in a code fence (gateway strips)
    valid_json_wrong_shape     valid JSON, list/dict of an unusable shape
    valid_json_wrong_field     dict without a urls string list
    truncated_json             JSON-looking text that does not parse
    non_json_text              free text
    empty_content              empty response

Diagnostic-only; no runtime path changes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.web.research.selection_authority import SELECTION_SYSTEM_PROMPT  # noqa: E402
from tools.run_selector_replay import DEFAULT_PROBE, build_pool, load_probe_cases  # noqa: E402

SCHEMA_PROBE_VERSION = "selector-schema-probe-v1"
DEFAULT_CASE = "rq1c-historical-current-node-modules"
DEFAULT_SAMPLES = 20
_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$")


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _FENCE.sub("", stripped).strip()
    return stripped


def classify_raw_response(raw: str) -> dict[str, Any]:
    """Mechanical shape classification of one raw selector response."""

    text = str(raw or "")
    if not text.strip():
        return {"shape": "empty_content"}
    fenced = text.strip().startswith("```")
    stripped = _strip_fence(text)
    try:
        payload = json.loads(stripped)
    except Exception:
        if stripped.startswith("{") or stripped.startswith("["):
            return {"shape": "truncated_json", "chars": len(text)}
        return {"shape": "non_json_text", "chars": len(text)}
    if isinstance(payload, Mapping):
        urls = payload.get("urls")
        if isinstance(urls, list) and all(isinstance(item, str) for item in urls):
            return {"shape": "contract_shape", "chars": len(text), "picks": len(urls)}
        return {"shape": "valid_json_wrong_field", "chars": len(text)}
    if isinstance(payload, list):
        if payload and all(isinstance(item, str) for item in payload):
            shape = "fenced_json" if fenced else "url_array"
            return {"shape": shape, "chars": len(text), "picks": len(payload)}
        return {"shape": "valid_json_wrong_shape", "chars": len(text)}
    return {"shape": "valid_json_wrong_shape", "chars": len(text)}


@dataclass
class SchemaProbeArtifact:
    samples: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        shapes: dict[str, int] = {}
        for sample in self.samples:
            shape = str(sample.get("shape") or "unknown")
            shapes[shape] = shapes.get(shape, 0) + 1
        return {
            "schema_version": SCHEMA_PROBE_VERSION,
            "diagnostic_only": True,
            "qualification_evidence": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sample_count": len(self.samples),
            "shape_counts": dict(sorted(shapes.items())),
            "samples": self.samples,
        }


def _selector_messages(pool: list[dict[str, Any]], question: str) -> list[dict[str, str]]:
    payload = {
        "schema_version": "research-selection-authority-v1",
        "claim": question[:2000],
        "max_urls": 2,
        "candidates": pool,
    }
    return [
        {"role": "system", "content": SELECTION_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def run_probe(
    *, probe_path: Path, output_path: Path, case_id: str, samples: int
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")

    from src.llm_client import chat

    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    case = next(
        (
            item
            for item in load_probe_cases(probe)
            if str(item.get("case_id")) == case_id
        ),
        None,
    )
    if case is None:
        raise ValueError(f"case not found in probe: {case_id}")
    pool = build_pool(case)
    messages = _selector_messages(pool, str(case.get("question") or ""))
    artifact = SchemaProbeArtifact()
    for index in range(max(1, int(samples))):
        raw = chat(
            messages,
            temperature=0.0,
            model_profile="flash",
            max_tokens=500,
            response_format="json_object",
            task_name="selector_schema_probe",
            request_max_retries=0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        classification = classify_raw_response(raw)
        artifact.samples.append(
            {
                "sample": index + 1,
                **classification,
                "excerpt": str(raw or "")[:200],
            }
        )
        print(f"[{index + 1}/{samples}] {classification}")
    payload = artifact.to_dict()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", default=DEFAULT_CASE)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    payload = run_probe(
        probe_path=args.probe.resolve(),
        output_path=args.output.resolve(),
        case_id=args.case,
        samples=args.samples,
    )
    print(json.dumps(payload["shape_counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
