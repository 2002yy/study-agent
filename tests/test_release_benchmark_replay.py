from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import socket

import pytest

from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_registry
from src.evals.release_benchmark_replay import (
    FrozenPdfGateway,
    FrozenTextGateway,
    block_python_network,
    run_frozen_mixed_pilot,
    run_frozen_pdf_pilot,
    run_frozen_text_pilot,
    run_frozen_visual_pilot,
)
from src.web.research.multimodal_reader import VisionAdapter, VisionObservation


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


def test_pdf_and_mixed_replay_use_verified_page_text_and_keep_visual_gap():
    pdf_case = _cases()["REL-F-PDF-001"]
    content = FrozenPdfGateway(pdf_case, ROOT).read(pdf_case.sources[0].locator)
    assert content["page"] == 2
    assert "synchronous rotation" in content["content"].lower()
    result = run_frozen_pdf_pilot(pdf_case, ROOT)
    assert result["source_reads"][0]["state"] == "read"
    assert result["source_reads"][0]["page"] == 2

    mixed = run_frozen_mixed_pilot(_cases()["REL-F-MIXED-001"], ROOT)
    assert mixed["text_read"]["source_reads"][0]["state"] == "read"
    assert mixed["visual_read"]["source_outcomes"][0]["status"] == "unavailable"
    assert mixed["release_gate"] == "NO_GO"


def test_visual_replay_uses_real_pipeline_and_never_self_qualifies():
    case = _cases()["REL-F-IMAGE-001"]
    default = run_frozen_visual_pilot(case, ROOT)["source_outcomes"][0]
    assert default["reason"] == "vision_not_configured"
    assert default["source_sha256"] == case.sources[0].sha256

    def observe(*, image, prompt):
        assert Path(image.local_path).is_file()
        assert image.page == 1 and image.region == case.sources[0].region
        assert "reservoir_position" in prompt
        return VisionObservation(text="test-only observation")

    injected = run_frozen_visual_pilot(case, ROOT, adapter=VisionAdapter(observe))
    outcome = injected["source_outcomes"][0]
    assert outcome["status"] == "normalized"
    assert outcome["unit"]["page"] == 1
    assert outcome["unit"]["region"] == case.sources[0].region
    assert injected["release_gate"] == "NO_GO"


def test_pdf_visual_replay_reports_missing_renderer(monkeypatch):
    monkeypatch.setattr("src.evals.release_benchmark_replay.shutil.which", lambda _: None)
    result = run_frozen_visual_pilot(_cases()["REL-F-CHART-001"], ROOT)
    assert result["source_outcomes"][0]["reason"] == "pdf_visual_page_renderer_not_available"


def test_visual_replay_rejects_changed_source_bytes(tmp_path: Path):
    case = _cases()["REL-F-IMAGE-001"]
    relative = Path(case.sources[0].snapshot_path or "")
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / relative, target)
    target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="digest drift"):
        run_frozen_visual_pilot(case, tmp_path)
