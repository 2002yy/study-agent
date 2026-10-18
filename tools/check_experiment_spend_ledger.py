"""Zero-cost demonstration of the durable experiment budget.

Reserves a few calls against a temporary runtime database, shows the refusal at
the cap, and re-reads the totals from a **separate process** to prove the budget
is not a process-local counter. No provider is contacted and no paid request is
sent.

    python tools/check_experiment_spend_ledger.py
"""

from __future__ import annotations

import gc
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPERIMENT = "ledger-demo"
CAP_CNY = "0.0030"


def _configure(database: Path) -> None:
    os.environ["LLM_SPEND_LEDGER_DB"] = str(database.resolve())
    os.environ["LLM_SPEND_EXPERIMENT_ID"] = EXPERIMENT
    os.environ["LLM_SPEND_EXPERIMENT_CAP_CNY"] = CAP_CNY
    os.environ["LLM_SPEND_INPUT_CNY_PER_MTOK"] = "1"
    os.environ["LLM_SPEND_OUTPUT_CNY_PER_MTOK"] = "1"


def _reserve(index: int) -> float:
    from src.llm_spend_guard import reserve_call

    return reserve_call(
        prompt_chars=1_000,
        max_tokens=100,
        attempts=1,
        purpose="chat:demo",
        model="deepseek-flash",
        request_key=f"{EXPERIMENT}|run-demo|op-demo|chat:demo|{index}",
    )


def main() -> int:
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.llm_spend_guard import (
        SpendLimitExceeded,
        experiment_spend,
        reset_spend,
    )

    # Windows keeps the database file locked until every connection is collected,
    # so cleanup is best-effort rather than an error path.
    temporary = tempfile.mkdtemp(prefix="spend-ledger-demo-")
    try:
        database = Path(temporary) / "runtime.db"
        RuntimeDatabase(database).initialize()
        _configure(database)
        reset_spend()

        for index in (1, 2):
            print(f"reserved call {index}: {_reserve(index):.6f} CNY")

        refused = False
        try:
            _reserve(3)
        except SpendLimitExceeded as exc:
            refused = True
            print("refused at the cap:", exc)
        print("REFUSED_AT_CAP:", refused)

        in_process = experiment_spend(EXPERIMENT)
        print("in this process:", in_process)

        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, r'%s');"
                "from src.llm_spend_guard import experiment_spend;"
                "print(experiment_spend('%s'))" % (ROOT, EXPERIMENT),
            ],
            capture_output=True,
            text=True,
            env={**os.environ},
            timeout=120,
        )
        if child.returncode != 0:
            print("child failed:", child.stderr)
            return 1
        print("in a separate process:", child.stdout.strip())
        same = child.stdout.strip() == str(in_process)
        print("DURABLE_ACROSS_PROCESSES:", same)
        return 0 if refused and same else 1
    finally:
        gc.collect()
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
