"""Public exact-head entrypoint for deterministic RQ1-C protocol probes."""

from __future__ import annotations

import json

from tools import run_rq1c_protocol_probes_core as _core

REQUIRED_PROBES = _core.REQUIRED_PROBES
_git_sha = _core._git_sha
run_protocol_probes = _core.run_protocol_probes


def main() -> int:
    args = _core._parser().parse_args()
    artifact = run_protocol_probes(
        runtime_path=args.runtime.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if not artifact["summary"]["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
