"""Zero-cost live check: the paid-run cap must stop a call before it is sent.

Runs the real FastAPI app in-process (no network server, no provider call) with
``LLM_SPEND_CAP_CNY`` set to a tiny value and asserts the chat route fails with
the spend guard instead of contacting a provider.

    python tools/check_llm_spend_guard.py            # cap = 0
    python tools/check_llm_spend_guard.py 0.000001   # cap = 1e-6 CNY
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    cap = sys.argv[1] if len(sys.argv) > 1 else "0"
    os.environ["LLM_SPEND_CAP_CNY"] = cap
    os.environ.setdefault("LLM_SPEND_INPUT_CNY_PER_MTOK", "2.5")
    os.environ.setdefault("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "9.0")
    os.environ["STUDY_AGENT_API_TOKEN"] = ""

    from fastapi.testclient import TestClient

    from src.api import app
    from src.llm_spend_guard import reset_spend

    reset_spend()
    client = TestClient(app)
    response = client.post(
        "/chat/stream",
        json={
            "user_input": "spend guard live check",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
        },
    )
    body = response.text
    tail = body[-800:].replace("\n", " ")
    print("status", response.status_code)
    print("tail", tail)
    stopped = "spend cap reached" in body or "SpendLimitExceeded" in body
    failed_turn = '"status": "failed"' in body or "event: error" in body
    print("SPEND_GUARD_STOPPED_BEFORE_PROVIDER:", stopped)
    print("TURN_FAILED_FAST:", failed_turn)
    return 0 if stopped else 1


if __name__ == "__main__":
    raise SystemExit(main())
