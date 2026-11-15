from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from shiyi_api import storage
from shiyi_api.main import app

USERS = "/api/v1/users"
HEALTH = "/api/v1/health"
NOW = datetime(2026, 11, 15, 8, 0, tzinfo=UTC)
PASSWORD = "synthetic-password-123"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIYI_DB_PATH", str(tmp_path / "accounts.sqlite3"))
    monkeypatch.setenv("SHIYI_DEV_USERS", '{"dev":"development-token-123"}')
    monkeypatch.setattr(storage, "now_utc", lambda: NOW)
    yield TestClient(app)
    storage.store_for.cache_clear()


def account(client, name="alice"):
    cred = {"username": name, "password": PASSWORD}
    r = client.post(USERS + "/register", json=cred)
    assert r.status_code == 201, r.text
    assert "password" not in r.text
    response = client.post(USERS + "/login", json=cred)
    assert response.status_code == 200, response.text
    return r.json(), {"Authorization": "Bearer " + response.json()["access_token"]}


def consent(client, auth, source="health_connect", metric="steps", granted=True):
    return client.put(f"{HEALTH}/consents/{source}/{metric}", headers=auth,
                      json={"granted": granted, "policy_version": "local-demo-v1"})


def sample(**changes):
    return {"client_sample_id": "steps-1", "source": "health_connect", "metric": "steps",
            "value": 1200, "observed_at": NOW.isoformat(),
            "interval_start": (NOW - timedelta(hours=1)).isoformat(), "is_demo": True,
            **changes}


def upload(client, auth, *samples):
    return client.post(HEALTH + "/observations", headers=auth, json={"observations": samples})


def test_register_login_profile_and_activity(client):
    user, auth = account(client)
    assert client.get(USERS + "/me", headers=auth).json() == user
    assert client.patch(USERS + "/me", headers=auth,
                        json={"display_name": "Demo"}).json()["display_name"] == "Demo"
    assert client.post(USERS + "/register",
                       json={"username": "ALICE", "password": PASSWORD}).status_code == 409
    assert client.post(USERS + "/login",
                       json={"username": "alice", "password": "invalid-password"}).status_code == 401
    assert client.post(USERS + "/login",
                       json={"username": "absent", "password": PASSWORD}).status_code == 401
    r = client.post("/api/v1/activities/sessions", headers=auth,
                    json={"activity_id": "stretch"})
    assert r.status_code == 200
    storage.store_for.cache_clear()
    assert client.get(USERS + "/me", headers=auth).json()["user_id"] == user["user_id"]
    assert client.post(USERS + "/logout", headers=auth).status_code == 204
    assert client.get(USERS + "/me", headers=auth).status_code == 401


def test_expired_credential(client, monkeypatch):
    _, auth = account(client)
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(hours=24))
    assert client.get(USERS + "/me", headers=auth).status_code == 401


def test_sensitive_invalid_input_not_reflected(client):
    r = client.post(USERS + "/register", json={"username": "alice", "password": "short123"})
    assert r.status_code == 422
    assert "short123" not in r.text


def test_consent_dedupe_and_history(client):
    _, auth = account(client)
    assert client.get(HEALTH + "/consents", headers=auth).json() == []
    assert upload(client, auth, sample()).status_code == 403
    assert consent(client, auth).status_code == 200
    first = upload(client, auth, sample())
    assert first.status_code == 200, first.text
    item = first.json()["items"][0]
    assert not item["duplicate"]
    assert upload(client, auth, sample()).json()["items"][0]["duplicate"]
    assert upload(client, auth, sample(value=1000)).status_code == 409
    storage.store_for.cache_clear()
    page = client.get(HEALTH + "/observations", headers=auth).json()
    assert page["items"][0]["is_demo"] is True
    assert page["items"][0]["observation_id"] == item["observation_id"]
    assert page["items"][0]["recorded_at"]
    assert consent(client, auth, granted=False).status_code == 200
    assert upload(client, auth, sample(client_sample_id="steps-2")).status_code == 403
    # Revocation blocks future collection; the user can audit/delete prior records.
    assert len(client.get(HEALTH + "/observations", headers=auth).json()["items"]) == 1
    assert client.delete(HEALTH + "/observations/" + item["observation_id"],
                         headers=auth).status_code == 204
    assert client.get(HEALTH + "/observations", headers=auth).json()["items"] == []


def test_user_isolation_and_atomic_batch(client):
    _, a = account(client)
    _, b = account(client, "bob")
    consent(client, a)
    assert upload(client, a, sample(), sample(source="vendor_sdk")).status_code == 403
    assert client.get(HEALTH + "/observations", headers=a).json()["items"] == []
    oid = upload(client, a, sample()).json()["items"][0]["observation_id"]
    assert client.get(HEALTH + "/observations", headers=b).json()["items"] == []
    assert upload(client, b, sample()).status_code == 403
    assert client.delete(HEALTH + "/observations/" + oid, headers=b).status_code == 404
    consent(client, b)
    assert upload(client, b, sample()).status_code == 200


def test_schema_provenance_and_missing_values(client):
    _, auth = account(client)
    consent(client, auth)
    assert upload(client, auth, sample(is_demo=False)).status_code == 422
    assert upload(client, auth, sample(value=None)).status_code == 422
    assert upload(client, auth, sample(value=-1)).status_code == 422
    assert upload(client, auth, sample(observed_at="2026-11-15T08:00:00")).status_code == 422
    assert upload(client, auth, sample(
        observed_at=(NOW + timedelta(minutes=6)).isoformat()
    )).status_code == 422
    assert upload(client, auth, sample(
        metric="energy_level", value=3, interval_start=None
    )).status_code == 422
    assert upload(client, auth, sample(value=None, missing_reason="not_worn")).status_code == 200
    page = client.get(HEALTH + "/observations?limit=1", headers=auth).json()
    assert page["items"][0]["value"] is None
    assert page["items"][0]["missing_reason"] == "not_worn"
    assert client.get(HEALTH + "/observations").status_code == 401
    assert upload(client, auth, sample(client_sample_id="steps-2")).status_code == 200
    page = client.get(HEALTH + "/observations?limit=1", headers=auth).json()
    assert page["next_offset"] == 1
