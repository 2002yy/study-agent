"""A2: without a configured token the API refuses, it does not open.

The previous behaviour treated "no `STUDY_AGENT_API_TOKEN`" as "private
deployment, no authentication needed". That is not a boundary: a reverse proxy
can present a remote request as loopback, so the only safe reading of a missing
secret is "refuse every private resource".

`/health` and the static bundle stay public so the browser can load the app and
ask for the token; everything else answers 401 with a code the client can act
on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import app

TOKEN = "s1-test-token"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _detail(response) -> dict:
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


def test_a_deployment_without_a_token_refuses_private_resources(monkeypatch, client):
    monkeypatch.delenv("STUDY_AGENT_API_TOKEN", raising=False)

    response = client.get("/sessions")

    assert response.status_code == 401
    payload = _detail(response)
    assert payload["code"] == "api_token_not_configured"
    assert "STUDY_AGENT_API_TOKEN" in payload["detail"]


def test_a_configured_token_is_required_on_private_resources(monkeypatch, client):
    monkeypatch.setenv("STUDY_AGENT_API_TOKEN", TOKEN)

    missing = client.get("/sessions")
    wrong = client.get("/sessions", headers={"X-Study-Agent-Token": "not-the-token"})

    for response in (missing, wrong):
        assert response.status_code == 401
        assert _detail(response)["code"] == "api_token_required"


def test_the_configured_token_admits_the_request(monkeypatch, client):
    monkeypatch.setenv("STUDY_AGENT_API_TOKEN", TOKEN)

    response = client.get("/sessions", headers={"X-Study-Agent-Token": TOKEN})

    assert response.status_code != 401


def test_a_bearer_header_is_equivalent_to_the_token_header(monkeypatch, client):
    monkeypatch.setenv("STUDY_AGENT_API_TOKEN", TOKEN)

    response = client.get(
        "/sessions", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code != 401


def test_health_and_static_assets_stay_public(monkeypatch, client):
    monkeypatch.delenv("STUDY_AGENT_API_TOKEN", raising=False)

    assert client.get("/health").status_code == 200
    # The bundle must load without a token or the app could never ask for one.
    assert client.get("/assets/").status_code != 401


def test_settings_are_not_readable_without_the_token(monkeypatch, client):
    monkeypatch.delenv("STUDY_AGENT_API_TOKEN", raising=False)

    response = client.get("/runtime/settings")

    assert response.status_code == 401
