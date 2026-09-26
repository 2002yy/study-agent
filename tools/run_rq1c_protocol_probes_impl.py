"""Compatibility facade for deterministic RQ1-C protocol probes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import run_rq1c_protocol_probes_core as _core  # noqa: E402

REQUIRED_PROBES = _core.REQUIRED_PROBES
DEFAULT_RUNTIME = _core.DEFAULT_RUNTIME
DEFAULT_OUTPUT = _core.DEFAULT_OUTPUT
_parser = _core._parser
_git_sha = _core._git_sha
run_protocol_probes = _core.run_protocol_probes


def main() -> int:
    args = _parser().parse_args()
    artifact = run_protocol_probes(
        runtime_path=args.runtime.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if not artifact["summary"]["failed"] else 2


def __getattr__(name: str) -> Any:
    return getattr(_core, name)


if __name__ == "__main__":
    from tools.run_rq1c_protocol_probes import main as guarded_main

    raise SystemExit(guarded_main())
