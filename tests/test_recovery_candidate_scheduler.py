from src.web.recovery_candidates import CandidateScheduler, canonical_document


def candidate(url, relevance=0.9):
    return {"assessment": {"url": url, "relevance": relevance}}


def test_language_and_tracking_variants_share_scheduling_identity_only():
    english = "https://docs.example.com/docs/en/model-x/?utm_source=test"
    chinese = "https://docs.example.com/docs/zh-CN/model-x"
    assert canonical_document(english) == canonical_document(chinese)
    assert canonical_document(chinese) != canonical_document(chinese + "?version=2")
    assert canonical_document(chinese) != canonical_document(
        chinese.replace("model-x", "model-y")
    )
    scheduler = CandidateScheduler()
    scheduler.begin(english)
    assert scheduler.rejection(english) == "already_attempted_url"
    assert scheduler.rejection(chinese) == "same_document_locale_variant"


def test_redirect_sink_and_known_unavailable_host_do_not_get_another_slot():
    scheduler = CandidateScheduler()
    original = "https://docs.example.com/docs/en/model-x"
    sink = "https://app.example.com/app-unavailable-in-region"
    scheduler.begin(original)
    assert scheduler.finish(original, {"ok": True, "url": sink}) == "REGION_UNAVAILABLE"
    assert scheduler.rejection(sink) == "already_read_redirect_target"
    assert (
        scheduler.rejection("https://docs.example.com/api/model-y")
        == "run_local_host_cooldown"
    )
    assert scheduler.rejection("https://release.example.com/model-x") == ""
    assert scheduler.snapshot()["unique_canonical_docs"] == 1
    # No global memory: a new run can try this host again.
    assert CandidateScheduler().rejection(original) == ""


def test_failed_host_penalty_prefers_new_authority_family():
    scheduler = CandidateScheduler()
    docs = "https://docs.example.com/api/model-x"
    release = "https://release.example.com/model-x"
    scheduler.begin(docs)
    scheduler.finish(docs, {"ok": False, "error": "page_timeout"})
    next_doc = "https://docs.example.com/api/model-y"
    records = [candidate(next_doc, 1), candidate(release, 0.7)]
    ordered = scheduler.order(records, ("docs.example.com", "release.example.com"))
    assert ordered[0]["assessment"]["url"] == release
    assert records[0]["assessment"]["url"] == next_doc


def test_two_unknown_host_failures_trigger_only_run_local_cooldown():
    scheduler = CandidateScheduler()
    for path in ["one", "two"]:
        url = f"https://docs.example.com/{path}"
        scheduler.begin(url)
        scheduler.finish(url, {"ok": False, "error": "timeout"})
    assert (
        scheduler.rejection("https://docs.example.com/three")
        == "run_local_host_cooldown"
    )


def test_authority_priority_and_source_diversity_are_preserved():
    scheduler = CandidateScheduler()
    records = [
        candidate("https://docs.example.com/docs/en/x"),
        candidate("https://docs.example.com/docs/zh/x"),
        candidate("https://release.example.com/x"),
        candidate("https://community.example.com/x", 1),
    ]
    ordered = scheduler.order(records, ("docs.example.com", "release.example.com"))
    assert [record["assessment"]["url"] for record in ordered[:2]] == [
        records[0]["assessment"]["url"],
        records[2]["assessment"]["url"],
    ]
