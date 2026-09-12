"""Tests for the API adapter -- transport plumbing, and the equivalence that
matters most: this API must return exactly what a direct call to
IndicPassMeter returns, for the same password, every time.

Two full IndicPassMeter constructions happen in this module (the app's own,
via its lifespan, and ``direct_meter`` below) -- each pays the dictionary
load and PCFG refit cost once (see ``docs/frontend.md``), so this file is
slow (roughly a minute) and deliberately kept out of the default
``python -m pytest`` run. See ``api/README.md``.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.main import MAX_PASSWORD_LENGTH, _serialize, app
from indicpass.config import load_config
from indicpass.password.meter import IndicPassMeter

REPRESENTATIVE_PASSWORDS = [
    "namaste123",
    "bharat2024",
    "Tr0ub4dor&3",
    "qwerty",
    "xk7#pQ2!mZ9v",
    "a",
    "sharma@123",
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:  # runs the lifespan -> a real meter
        yield test_client


@pytest.fixture(scope="module")
def direct_meter() -> IndicPassMeter:
    """The same construction scripts/check_password.py uses -- built
    independently of the running app, so equivalence tests are not just
    calling the same object twice."""
    return IndicPassMeter.from_config(load_config())


# -- health ------------------------------------------------------------


def test_health_reports_ready_once_the_meter_has_loaded(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["status"] == "ok"


# -- malformed / edge-case requests -------------------------------------


def test_missing_password_field_is_a_422_not_a_500(client):
    response = client.post("/api/analyze", json={})
    assert response.status_code == 422


def test_empty_password_is_rejected_with_a_clear_message(client):
    response = client.post("/api/analyze", json={"password": ""})
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_an_oversized_password_is_rejected_with_a_clear_message(client):
    response = client.post(
        "/api/analyze", json={"password": "a" * (MAX_PASSWORD_LENGTH + 1)}
    )
    assert response.status_code == 400
    assert "length" in response.json()["detail"].lower()


def test_a_malformed_json_body_is_a_422_not_a_500(client):
    response = client.post(
        "/api/analyze",
        content="not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "response_password",
    ["", "a" * (MAX_PASSWORD_LENGTH + 1)],
)
def test_error_responses_carry_no_traceback_or_filesystem_path(client, response_password):
    response = client.post("/api/analyze", json={"password": response_password})
    body = response.text
    assert "Traceback" not in body
    assert str(load_config().root) not in body


# -- the response redacts the password unless asked not to ---------------


def test_the_default_response_does_not_echo_the_password(client):
    response = client.post("/api/analyze", json={"password": "namaste123"})
    assert response.status_code == 200
    assert "namaste" not in response.text


def test_reveal_tokens_surfaces_the_match_only_when_asked(client):
    redacted = client.post("/api/analyze", json={"password": "namaste123"})
    revealed = client.post(
        "/api/analyze", json={"password": "namaste123", "reveal_tokens": True}
    )
    assert "namaste" not in redacted.text
    assert "namaste" in revealed.text


# -- equivalence: API result == direct call, for representative passwords -


@pytest.mark.parametrize("password", REPRESENTATIVE_PASSWORDS)
def test_api_result_matches_direct_invocation_exactly(client, direct_meter, password):
    response = client.post(
        "/api/analyze", json={"password": password, "reveal_tokens": True}
    )
    assert response.status_code == 200
    api_payload = response.json()

    direct_result = direct_meter.score(password)
    direct_payload = json.loads(
        _serialize(direct_result, direct_meter, include_tokens=True)
    )

    assert api_payload == direct_payload


def test_redacted_and_revealed_payloads_agree_on_every_numeric_field(client):
    """reveal_tokens must change only which redacted keys are present -- never
    a number. This is the API-level restatement of PasswordStrengthResult's
    own redaction contract in result.py."""
    password = "sharma2024"
    redacted = client.post("/api/analyze", json={"password": password}).json()
    revealed = client.post(
        "/api/analyze", json={"password": password, "reveal_tokens": True}
    ).json()

    for key in ("guess_number", "log10_guesses", "strength_score", "strength_label"):
        assert redacted[key] == revealed[key]
