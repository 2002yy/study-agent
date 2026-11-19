"""Evidence and lead reads share wave charges without owning the live budget."""

from src.application.research_runtime_read_quota_context import ReadWaveQuotaContext
from src.web.research.deep_runtime import SEED_FINAL_BACKEND
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def test_restore_counts_physical_history_and_unique_seed_bytes_without_writing_back():
    context = {
        ACTIVE_RESEARCH_METRICS_KEY: {
            "reads": [
                {"content_chars": "12"},
                {"content_chars": 5},
                "not-a-read",
            ]
        }
    }
    sources = [
        {
            "candidate_id": "seed-a",
            "final_backend": SEED_FINAL_BACKEND,
            "read_status": "read",
            "read": {"content": "seed"},
        },
        {
            "candidate_id": "seed-a",
            "final_backend": SEED_FINAL_BACKEND,
            "read_status": "read",
            "read": {"content": "do-not-charge-twice"},
        },
        {"candidate_id": "normal", "read_status": "read", "read": {"content": "x"}},
    ]

    first = ReadWaveQuotaContext.restore(
        budget_reads_used=2, context=context, selected_sources=sources
    )
    second = ReadWaveQuotaContext.restore(
        budget_reads_used=2, context=context, selected_sources=sources
    )

    assert (first.successful_reads, first.used_chars) == (2, 21)
    first.charge_materialization("local-seed")
    assert (first.successful_reads, first.used_chars) == (2, 31)
    assert (second.successful_reads, second.used_chars) == (2, 21)
    assert context[ACTIVE_RESEARCH_METRICS_KEY]["reads"][0]["content_chars"] == "12"
    assert sources[0]["read"]["content"] == "seed"


def test_evidence_and_lead_reads_share_charges_with_latest_limits():
    quota = ReadWaveQuotaContext(successful_reads=1, used_chars=9)

    assert not quota.exhausted(max_reads=3, max_total_chars=20)
    assert quota.exhausted(max_reads=1, max_total_chars=20)
    assert quota.exhausted(max_reads=3, max_total_chars=9)
    assert quota.remaining_chars(max_total_chars=20) == 11
    assert quota.source_limit(max_total_chars=20) == 11
    assert quota.source_limit(max_total_chars=7000) == 6000

    quota.charge_materialization("seed")
    assert (quota.successful_reads, quota.used_chars) == (1, 13)
    quota.charge_read("evidence")
    assert (quota.successful_reads, quota.used_chars) == (2, 21)
    quota.charge_read("lead")
    assert (quota.successful_reads, quota.used_chars) == (3, 25)
    assert quota.exhausted(max_reads=3, max_total_chars=100)
    assert quota.exhausted(max_reads=10, max_total_chars=25)
    # Admission rejects exhausted quotas; the projection itself keeps the old
    # non-clamping arithmetic so it cannot silently change the reader contract.
    assert quota.source_limit(max_total_chars=20) == -5
