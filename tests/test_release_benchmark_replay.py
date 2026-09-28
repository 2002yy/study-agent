from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import socket

import pytest

from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_registry
from src.evals.release_benchmark_replay import (
    FrozenTextGateway,
    block_python_network,
    run_frozen_text_pilot,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def _cases():
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    return {case.case_id: case for case in load_registry(
        FIXTURES / "registry_v1.json", ROOT, plan,
    ).cases}


def test_frozen_text_pilot_executes_real_service_with_verified_source():
    case = _cases()["REL-F-TEXT-001"]
    content = FrozenTextGateway(case, ROOT).read(case.sources[0].locator)["content"]
    result = run_frozen_text_pilot(case, ROOT)

    assert "storm tide is the total" in content.lower()
    assert "winds pushing water onshore" in content.lower()
    assert result["run_status"] == "completed"
    assert result["provider_status"] == "found"
    assert result["source_reads"][0]["state"] == "read"
    assert result["source_reads"][0]["source_sha256"] == case.sources[0].sha256
    assert result["release_gate"] == "NO_GO"


def test_frozen_gateway_rejects_unknown_url_and_snapshot_drift(tmp_path: Path):
    case = _cases()["REL-F-TEXT-001"]
    source = case.sources[0]
    relative = Path(source.snapshot_path or "")
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / relative, target)
    gateway = FrozenTextGateway(case, tmp_path)

    with pytest.raises(ValueError, match="allowlist"):
        gateway.read("https://example.invalid/other")
    with pytest.raises(ValueError, match="query"):
        gateway.search("different question", max_items=1)

    target.write_bytes(target.read_bytes() + b" changed")
    with pytest.raises(ValueError, match="digest drift"):
        gateway.read(source.locator)
    with pytest.raises(ValueError, match="digest drift"):
        FrozenTextGateway(replace(case, sources=(source,)), tmp_path)


def test_frozen_pilot_rejects_binary_and_blocks_socket_connects():
    with pytest.raises(ValueError, match="frozen text"):
        FrozenTextGateway(_cases()["REL-F-PDF-001"], ROOT)
    with block_python_network(), socket.socket() as sock:
        with pytest.raises(RuntimeError, match="network disabled"):
            sock.connect(("127.0.0.1", 9))
