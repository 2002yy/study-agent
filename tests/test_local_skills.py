from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from src import skills
from src.api import app
from src.skills import SkillNotFoundError, SkillStore


def document(name="local-helper", body="Answer with a concrete example."):
    return f"---\nname: {name}\ndescription: A local skill\n---\n{body}\n"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "SKILL_STORE_PATH", tmp_path / "local_skills.json")
    return SkillStore()


def test_import_preserves_full_text_and_starts_disabled(store):
    content = document(body="中文说明\r\nRun `scripts/helper.py` only if requested.")
    row = store.import_skill(content)
    assert row["id"].startswith("skill_")
    assert row == SkillStore().list_skills()[0]
    assert row["content"] == content
    assert row["enabled"] is False
    assert row["name"] == "local-helper"
    with pytest.raises(ValueError, match="disabled"):
        store.get_enabled([row["id"]])
    store.set_enabled(row["id"], True)
    assert store.get_enabled([row["id"]])[0]["content"] == content
    store.set_enabled(row["id"], False)
    with pytest.raises(ValueError, match="disabled"):
        store.get_enabled([row["id"]])
    store.delete(row["id"])
    assert SkillStore().list_skills() == []


@pytest.mark.parametrize(
    "content",
    [
        "",
        "# Instructions without metadata",
        "---\nname: helper\n",
        "---\nname: helper\n---\nInstructions",
        "---\nname: ../outside\ndescription: test\n---\nInstructions",
        "---\nname: [helper]\ndescription: test\n---\nInstructions",
        "---\nname: helper\ndescription: ''\n---\nInstructions",
        "---\nname: helper\ndescription: test\n---\n",
        "---\n!!python/object/apply:os.system ['echo unsafe']\n---\nInstructions",
        document(body="x" * 20_000),
    ],
)
def test_invalid_import_never_replaces_existing_content(store, content):
    original = store.import_skill(document())
    original_bytes = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.import_skill(content)
    assert store.path.read_bytes() == original_bytes
    assert store.list_skills() == [original]


def test_metadata_multiline_description_and_bom(store):
    content = "\ufeff---\nname: sample-1\ndescription: |\n  First line\n  Second line\n---\nInstructions\n"
    row = store.import_skill(content)
    assert row["description"] == "First line\nSecond line"
    assert row["content"] == content


def test_installation_limit_and_independent_instances(store):
    with ThreadPoolExecutor(max_workers=8) as executor:
        rows = list(
            executor.map(
                lambda i: SkillStore().import_skill(document(f"skill-{i}")), range(32)
            )
        )
    assert len({row["id"] for row in rows}) == 32
    with pytest.raises(ValueError, match="32"):
        store.import_skill(document("excess"))
    assert len(store.list_skills()) == 32


def test_selected_limits_unknown_disabled_and_order(store):
    rows = [store.import_skill(document(f"skill-{i}")) for i in range(4)]
    ids = [row["id"] for row in rows]
    for skill_id in ids:
        store.set_enabled(skill_id, True)
    assert [row["id"] for row in store.get_enabled(ids[:3][::-1])] == ids[:3][::-1]
    assert store.get_enabled([]) == []
    for selected in [ids, [ids[0], ids[0]], [None], "wrong"]:
        with pytest.raises(ValueError):
            store.get_enabled(selected)
    with pytest.raises(SkillNotFoundError):
        store.get_enabled(["missing"])
    for operation in [
        lambda: store.set_enabled("missing", True),
        lambda: store.delete("missing"),
    ]:
        with pytest.raises(SkillNotFoundError):
            operation()


def test_selected_content_budget(store):
    ids = []
    for index in range(2):
        row = store.import_skill(document(f"large-{index}", "x" * 12_000))
        store.set_enabled(row["id"], True)
        ids.append(row["id"])
    assert len(store.get_enabled(ids[:1])) == 1
    with pytest.raises(ValueError, match="24000"):
        store.get_enabled(ids)


def test_atomic_replace_failure_preserves_old_store_and_cleans_temporary(
    store, monkeypatch
):
    store.import_skill(document())
    original = store.path.read_bytes()

    def fail_replace(*args):
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr(skills.os, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted"):
        store.import_skill(document("second"))
    assert store.path.read_bytes() == original
    assert not list(store.path.parent.glob(f".{store.path.name}.*.tmp"))


def test_corrupt_store_is_never_reset(store):
    store.path.write_text('{"skills": broken', encoding="utf-8")
    original = store.path.read_bytes()
    with pytest.raises(ValueError, match="preserved"):
        store.import_skill(document())
    assert store.path.read_bytes() == original


def test_skill_api_lifecycle_and_bad_requests(store):
    client = TestClient(app)
    assert client.get("/skills").json() == {"skills": []}
    response = client.post("/skills", json={"content": document()})
    assert response.status_code == 200
    row = response.json()
    assert row["enabled"] is False
    assert client.get("/skills").json() == {"skills": [row]}
    assert (
        client.patch(f"/skills/{row['id']}", json={"enabled": True}).json()["enabled"]
        is True
    )
    assert store.get_enabled([row["id"]])[0]["name"] == "local-helper"
    assert (
        client.patch(f"/skills/{row['id']}", json={"enabled": "yes"}).status_code == 422
    )
    assert client.post("/skills", json={"content": "invalid"}).status_code == 400
    assert (
        client.post(
            "/skills", json={"content": document(body="x" * 20_000)}
        ).status_code
        == 400
    )
    assert client.patch("/skills/missing", json={"enabled": True}).status_code == 404
    assert client.delete("/skills/missing").status_code == 404
    assert client.delete(f"/skills/{row['id']}").json() == {"deleted": True}
    assert client.get("/skills").json() == {"skills": []}


def test_skill_api_requires_existing_api_auth(store, monkeypatch):
    monkeypatch.setenv("STUDY_AGENT_API_TOKEN", "local-skills-test-secret")
    client = TestClient(app)
    for method, path, payload in [
        ("get", "/skills", None),
        ("post", "/skills", {"content": document()}),
        ("patch", "/skills/missing", {"enabled": True}),
        ("delete", "/skills/missing", None),
    ]:
        assert client.request(method, path, json=payload).status_code == 401
    assert not store.path.exists()
