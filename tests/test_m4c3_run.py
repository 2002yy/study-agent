import json

import pytest

from src import llm_spend_guard as spend
from tools.m4c3_run import run_batch, validate_authorization
from tools.m4c3_prepare import ledger_snapshot

PRICING = {
    "input_cny_per_mtok": 9,
    "output_cny_per_mtok": 27,
    "source": "offline-test",
    "verified_at": "2026-11-04",
}
ANSWER = (
    "```study-ui\n"
    + json.dumps(
        {
            "type": "interactive",
            "id": "fixture",
            "revision": 1,
            "title": "Fixture",
            "summary": "Not model quality evidence",
            "html": "<p>fixture</p>",
        }
    )
    + "\n```"
)


def test_product_chain_reserves_each_actual_request_before_one_fake_http_send(
    tmp_path, monkeypatch
):
    import httpx

    monkeypatch.setattr(
        httpx,
        "HTTPTransport",
        lambda **kw: pytest.fail("offline runner attempted network transport"),
    )
    spend.reset_spend()  # Tests only: durable reservations cannot be reset.
    out, ledger = tmp_path / "run", tmp_path / "spend.db"
    report = run_batch(out, ledger, PRICING, fake_reply=ANSWER)
    assert len(report["cases"]) == 12
    assert all(
        case["status"] == "completed" and case["sent"] for case in report["cases"]
    )
    assert report["ledger"]["reservation_count"] == 12
    assert report["ledger"]["reserved_micros"] <= 12_000_000
    index = json.loads((out / "index.json").read_text())
    assert index["generation_mode"] == "fake_http"
    assert len(index["cases"]) == 12
    assert {case["source_kind"] for case in index["cases"]} == {"fake_transport"}
    for case in report["cases"]:
        directory = out / case["task_id"]
        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        assert request["model"] == "deepseek-flash"
        assert request["max_tokens"] == 9000
        assert request["temperature"] == 0.7
        assert request["thinking"] == {"type": "disabled"}
        assert (directory / "answer.txt").read_text() == ANSWER
        assert (directory / "reservation.json").exists()
        assert (directory / "provider-response.txt").exists()
        assert 0 < case["reserved_micros"] <= 1_000_000
    with pytest.raises(ValueError, match="fresh temporary ledger"):
        run_batch(tmp_path / "restart", ledger, PRICING, fake_reply=ANSWER)
    assert (
        ledger_snapshot(ledger, "study-agent-live-20261102")["reservation_count"] == 12
    )


def test_paid_mode_requires_explicit_authorization_before_creating_artifacts(tmp_path):
    with pytest.raises(ValueError, match="authorization"):
        run_batch(tmp_path / "run", tmp_path / "shared.db", PRICING, allow_paid=True)
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "shared.db").exists()


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_calls", 13),
        ("batch_cny", 30),
        ("per_call_cny", 2),
        ("model", "deepseek-pro"),
        ("shared_cny", 31),
    ],
)
def test_paid_authorization_cannot_widen_batch_limits(key, value):
    authorization = dict(
        authorized=True,
        model="deepseek-flash",
        experiment="study-agent-live-20261102",
        max_calls=12,
        per_call_cny=1,
        batch_cny=12,
        shared_cny=30,
        approval_reference="test",
    )
    authorization[key] = value
    with pytest.raises(ValueError):
        validate_authorization(authorization)


def test_actual_request_that_exceeds_single_reservation_limit_never_sends(
    tmp_path, monkeypatch
):
    import tools.m4c3_run as runner

    spend.reset_spend()
    monkeypatch.setattr(
        runner,
        "build_manifest",
        lambda: {
            "cases": [
                {
                    "task_id": "J01",
                    "invocation_key": "m4c3-v1:J01:first",
                    "prompt": "制作交互界面" + "x" * 200_000,
                }
            ]
        },
    )
    report = run_batch(
        tmp_path / "run", tmp_path / "spend.db", PRICING, fake_reply=ANSWER
    )
    assert report["cases"][0]["status"] == "failed"
    assert report["cases"][0]["sent"] is False
    assert not (tmp_path / "run/J01/request.json").exists()


def test_paid_mode_cannot_reset_shared_history_with_another_ledger(tmp_path):
    authorization = dict(
        authorized=True,
        model="deepseek-flash",
        experiment="study-agent-live-20261102",
        max_calls=12,
        per_call_cny=1,
        batch_cny=12,
        shared_cny=30,
        approval_reference="explicit test approval",
    )
    with pytest.raises(ValueError, match="canonical shared ledger"):
        run_batch(
            tmp_path / "run",
            tmp_path / "other.db",
            PRICING,
            allow_paid=True,
            authorization=authorization,
        )
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "other.db").exists()
