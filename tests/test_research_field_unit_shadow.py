"""Field proofs are observations, never Claim Engine or publication authority."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from src.web.research.contracts import EvidenceCluster, ResearchQuestion
from src.web.research.evidence_gate import evaluate_evidence_gate
from src.web.research.field_unit_shadow import (
    KEY,
    declare,
    digest,
    observe,
    safe_observe,
    seal_read,
)
from tests.test_claim_evidence_assessment import (
    _evidence,
    _requirement,
    _state,
    _support,
)
from tests.test_deep_execution import ctx as ctx, saved_parent as saved_parent

QUERY = "Python 3.14.0 发布日期和版本号"
BODY = "Python 3.14.0 was released on 2025-10-07."


def inputs(bodies=(BODY, BODY), *, clusters=("c1", "c2"), strength=0.9, spans=True):
    records = []
    evidence = []
    links = []
    for index, body in enumerate(bodies):
        eid = f"ev{index}"
        evidence.append(
            replace(_evidence(eid), anchored_spans=(body,) if spans else ())
        )
        links.append(
            _support(
                eid,
                cluster=clusters[index],
                role="primary" if index == 0 else "independent_secondary",
                strength=strength,
            )
        )
        records.append(
            {
                "field_shadow_evidence_id": eid,
                "field_shadow_read": seal_read({"content": body}, body),
                "item": {"url": f"https://example{index}.org/release"},
                "read": {"ok": True, "content": body},
            }
        )
    state = _state(
        requirement=_requirement(requires_primary=True),
        evidence=tuple(evidence),
        links=tuple(links),
        clusters=tuple(
            EvidenceCluster(
                cluster,
                tuple(
                    link.evidence_id
                    for link in links
                    if link.source_cluster_id == cluster
                ),
            )
            for cluster in set(clusters)
        ),
    )
    return replace(
        state, questions=(ResearchQuestion("q1", QUERY, "critical"),)
    ), records


def fields(result):
    return {row["field"]: row for row in result["coverage"]}


def test_supported_fields_are_independently_bound_without_authority_or_mutation():
    state, records = inputs()
    before = deepcopy((state.to_dict(), records))
    gate_before = evaluate_evidence_gate(state).to_dict()
    result = observe(declare(QUERY), state, records)
    assert {row["status"] for row in result["coverage"]} == {"COVERED"}
    assert len(result["coverage"]) == 2
    for row in result["coverage"]:
        assert row["supporting_clusters"] == 2
        for candidate in row["candidates"]:
            start, end = candidate["source_span"]
            assert BODY[start:end] == candidate["quote"]
            assert candidate["claim_id"] == "claim1"
    assert (
        result["publication_authority"] is False and result["stop_authority"] is False
    )
    assert (state.to_dict(), records) == before
    assert evaluate_evidence_gate(state).to_dict() == gate_before
    assert not state.claims[0].evidence_requirement.required_units
    assert all(not item.units for item in state.evidence)


@pytest.mark.parametrize(
    "body",
    [
        "FastAPI 3.14.0 was released on 2025-10-07.",
        "Python 3.14.1 was released on 2025-10-07.",
        "Python 3.14.0rc1 was released on 2025-10-07.",
        "Python 3.14.0-beta1 was released on 2025-10-07.",
        "Python 3.14.0 and Python 3.14.1 were released on 2025-10-07.",
        "Python 3.14.0\nAn unrelated product was released on 2025-10-07.",
        "Python 3.14.0 notes say another product was released on 2025-10-07.",
        "Python 3.14.0 was not released on 2025-10-07.",
        "Python 3.14.0 was released on 2025-10-07 is false.",
    ],
)
def test_wrong_identity_or_unbound_relation_cannot_cover_release_date(body):
    state, records = inputs((body, body))
    assert (
        fields(observe(declare(QUERY), state, records))["release_date"]["status"]
        == "NOT_EVALUATED"
    )


@pytest.mark.parametrize("relation", ["uploaded on", "updated on", "published on"])
def test_upload_update_and_publication_dates_are_not_release_dates(relation):
    body = f"Python 3.14.0 was {relation} 2025-10-07."
    state, records = inputs((body, body))
    result = fields(observe(declare(QUERY), state, records))
    assert result["version"]["status"] == "COVERED"
    assert result["release_date"]["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize(
    "fault",
    [
        "body",
        "input_hash",
        "missing_seal",
        "missing_ref",
        "private_url",
        "missing_span",
        "unrelated_span",
        "failed_read",
    ],
)
def test_corrupt_or_unqualified_read_cannot_support_fields(fault):
    state, records = inputs()
    for record in records:
        if fault == "body":
            record["read"]["content"] += " altered"
        elif fault == "input_hash":
            record["field_shadow_read"] = seal_read(
                {"content": BODY, "content_sha256": "forged"}, BODY
            )
        elif fault == "missing_seal":
            record.pop("field_shadow_read")
        elif fault == "missing_ref":
            record["field_shadow_evidence_id"] = "forged"
        elif fault == "private_url":
            record["item"]["url"] = "https://127.0.0.1/release"
        elif fault == "failed_read":
            record["read"]["ok"] = False
    if fault in {"missing_span", "unrelated_span"}:
        state = replace(
            state,
            evidence=tuple(
                replace(
                    item,
                    anchored_spans=() if fault == "missing_span" else ("unrelated",),
                )
                for item in state.evidence
            ),
        )
    assert {
        row["status"] for row in observe(declare(QUERY), state, records)["coverage"]
    } == {"NOT_EVALUATED"}


def test_same_cluster_and_weak_support_do_not_gain_independent_coverage():
    state, records = inputs(clusters=("c1", "c1"))
    result = observe(declare(QUERY), state, records)
    assert {row["status"] for row in result["coverage"]} == {"PARTIAL"}
    assert all(row["supporting_clusters"] == 1 for row in result["coverage"])
    state, records = inputs(strength=0.6)
    assert {
        row["status"] for row in observe(declare(QUERY), state, records)["coverage"]
    } == {"NOT_EVALUATED"}


def test_conflicting_dates_do_not_overwrite_or_average():
    state, records = inputs((BODY, BODY.replace("2025-10-07", "2025-10-08")))
    result = fields(observe(declare(QUERY), state, records))
    assert result["release_date"]["status"] == "CONFLICT"
    assert result["version"]["status"] == "COVERED"


def test_declaration_is_request_owned_and_cannot_be_pruned_after_reading():
    state, records = inputs()
    shadow = declare(QUERY)
    shadow["declaration"]["requirements"].pop()
    shadow["declaration_sha256"] = digest(shadow["declaration"])
    assert observe(shadow, state, records)["status"] == "INVALID"
    other = replace(
        state, questions=(ResearchQuestion("q1", "Different request", "critical"),)
    )
    assert (
        observe(declare(QUERY), other, records)["status"] == "WAITING_FOR_OWNED_CLAIM"
    )


@pytest.mark.parametrize(
    "query",
    [
        "教我围棋",
        "Python 3.14.0 和 FastAPI 0.115.0 对比",
        "Python 3.14.0rc1 发布日期和版本号",
    ],
)
def test_unsupported_or_ambiguous_request_does_not_guess_requirements(query):
    assert declare(query)["status"] == "NOT_DECLARED"


def test_checkpoint_roundtrip_is_idempotent_without_duplicate_units():
    state, records = inputs()
    first = observe(declare(QUERY), state, records)
    assert observe(json.loads(json.dumps(first)), state, records) == first
    assert safe_observe(None, state, records)["status"] == "INVALID"
    assert safe_observe({"declaration": []}, state, records)["coverage"] == []


@pytest.mark.parametrize(
    "fault", ["no_primary", "rejected", "unavailable", "contradiction"]
)
def test_existing_claim_eligibility_and_conflict_still_block_coverage(fault):
    state, records = inputs()
    if fault == "no_primary":
        state = replace(
            state,
            evidence_links=tuple(
                replace(link, source_role="independent_secondary")
                for link in state.evidence_links
            ),
        )
    elif fault == "rejected":
        state = replace(
            state,
            evidence=tuple(
                replace(item, lifecycle_status="rejected") for item in state.evidence
            ),
        )
    elif fault == "unavailable":
        state = replace(state, claims=(replace(state.claims[0], state="unavailable"),))
    else:
        state = replace(
            state,
            evidence_links=(
                *state.evidence_links,
                _support("ev0", cluster="c1", role="primary", relation="contradicts"),
            ),
        )
    assert all(
        row["status"] != "COVERED"
        for row in observe(declare(QUERY), state, records)["coverage"]
    )


def test_unqualified_positioning_relation_remains_unknown():
    query = "Opus 5.5 发布日期、版本号和定位"
    body = "Opus 5.5 was released on 2025-10-07."
    state, records = inputs((body, body))
    state = replace(state, questions=(ResearchQuestion("q1", query, "critical"),))
    result = fields(observe(declare(query), state, records))
    assert result["version"]["status"] == "COVERED"
    assert result["official_positioning"]["status"] == "NOT_EVALUATED"


def test_new_deep_admission_persists_declaration_before_dispatch(ctx):
    service, _, runs, parent, _, prepared, dispatcher = ctx
    checked = []
    original_execute = dispatcher.execute

    def inspect(run_id):
        child = runs.get(run_id)
        shadow = child.research_context[KEY]
        assert shadow["status"] == "DECLARED"
        assert shadow["declaration"]["query"] == child.query
        assert not child.selected_sources
        checked.append(shadow)
        return original_execute(run_id)

    dispatcher.execute = inspect
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert len(checked) == 1
    child = runs.get(prepared.child_run_id)
    assert child.research_context[KEY] == checked[0]
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert runs.get(child.id).research_context[KEY] == checked[0]


def test_legacy_admitted_child_is_not_backfilled(ctx):
    from tests.test_deep_execution import _write_child_context

    service, repository, runs, parent, _, prepared, _ = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    child = runs.get(prepared.child_run_id)
    context = deepcopy(child.research_context)
    context.pop(KEY)
    _write_child_context(repository, child.id, context)
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert KEY not in runs.get(child.id).research_context


@pytest.mark.parametrize("shadow_mode", ["declared", "legacy", "malformed"])
def test_runtime_checkpoint_and_cold_repository_restore_keep_original_stop(
    tmp_path, shadow_mode
):
    from src.domain.runtime_entities import WebLookupRun
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.web_lookup_repository import WebLookupRepository
    from tests.test_active_research_runtime import (
        _PrimaryRoleClient,
        _ReadGateway,
        _SearchBackend,
        _TrackingRepository,
        _active_context,
        _service,
    )

    class Client(_PrimaryRoleClient):
        def create(self, **kwargs):
            response = super().create(**kwargs)
            payload = json.loads(response.choices[0].message.content)
            if payload.get("schema_version") == "research-evidence-extraction-v1":
                payload.update(locator=BODY, anchored_spans=[BODY])
                response.choices[0].message.content = json.dumps(payload)
            return response

    class Reader(_ReadGateway):
        def read(self, url, *, max_chars=6000):
            result = super().read(url, max_chars=max_chars)
            result["content"] = BODY
            return result

    class CrashRepository(_TrackingRepository):
        crashed = False

        def checkpoint(self, run_id, **kwargs):
            persisted = super().checkpoint(run_id, **kwargs)
            if not self.crashed and any(
                row.get("field_shadow_evidence_id")
                for row in persisted.selected_sources
            ):
                self.crashed = True
                assert persisted.research_context[KEY]["coverage"]
                self.fail(
                    run_id,
                    "shadow checkpoint interruption",
                    operation_id=persisted.active_operation_id,
                )
                raise RuntimeError("shadow checkpoint interruption")
            return persisted

    path = tmp_path / "runtime.sqlite"
    repository = CrashRepository(RuntimeDatabase(path))
    context = _active_context()
    if shadow_mode != "legacy":
        context[KEY] = declare(QUERY) if shadow_mode == "declared" else None
    run = repository.create(
        WebLookupRun(
            id="shadow-run",
            query=QUERY,
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    client, search, reader = Client(), _SearchBackend(), Reader()
    service = _service(repository, client, search_backend=search, read_gateway=reader)
    if shadow_mode == "declared":
        with pytest.raises(RuntimeError, match="shadow checkpoint interruption"):
            service.execute(run.id, raise_on_error=True)
        crashed = repository.get(run.id)
        assert {row["status"] for row in crashed.research_context[KEY]["coverage"]} == {
            "PARTIAL"
        }
        # A fresh connection/service loads the original cursor and declaration.
        restored = WebLookupRepository(RuntimeDatabase(path))
        service = _service(restored, client, search_backend=search, read_gateway=reader)
    elif shadow_mode == "malformed":
        repository.crashed = True
    completed = service.execute(run.id, raise_on_error=True)
    assert (
        completed.status == "completed"
        and completed.stop_reason == "evidence_gate_pass"
    )
    assert reader.calls == 2  # no duplicate read after the durable interruption
    if shadow_mode == "declared":
        shadow = completed.research_context[KEY]
        assert {row["status"] for row in shadow["coverage"]} == {"COVERED"}
        assert shadow["declaration"] == declare(QUERY)["declaration"]
        assert len({row["unit_id"] for row in shadow["coverage"]}) == 2
    elif shadow_mode == "legacy":
        assert KEY not in completed.research_context
    else:
        assert completed.research_context[KEY]["status"] == "INVALID"
