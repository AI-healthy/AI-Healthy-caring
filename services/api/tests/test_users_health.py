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


def test_registered_account_simulator_binding(client):
    _, auth = account(client)
    _, other = account(client, "bob")
    path = USERS + "/me/simulated-devices"
    result = client.post(path, headers=auth, json={"name": "Synthetic StackChan"})
    assert result.status_code == 201, result.text
    record = result.json()
    did = record["device"]["device_id"]
    device_auth = {"Authorization": "Bearer " + record["device_token"]}
    listed = client.get(path, headers=auth).json()
    assert listed == [record["device"]]
    assert client.get(path, headers=other).json() == []
    assert client.get(USERS + "/me", headers=device_auth).status_code == 401
    session = client.post("/api/v1/activities/sessions", headers=auth,
                          json={"activity_id": "stretch"}).json()
    sid = session["session_id"]
    assert client.post(f"/api/v1/activities/sessions/{sid}/start",
                       headers=auth).status_code == 200
    payload = {"device_id": did, "session_id": sid, "preset": "happy",
               "client_request_id": "new-account-command"}
    root = "/api/v1/devices"
    command = client.post(root + "/commands", headers=auth, json=payload)
    assert command.status_code == 200, command.text
    cid = command.json()["command_id"]
    assert client.get(f"{root}/{did}/pending", headers=device_auth).json()["command_id"] == cid
    assert client.get(f"{root}/{did}/pending", headers=other).status_code == 401
    assert client.delete(path + "/" + did, headers=other).status_code == 404
    assert client.delete(path + "/" + did, headers=auth).status_code == 204
    assert client.get(f"{root}/{did}/pending", headers=device_auth).status_code == 401
    assert client.get(root + "/commands/" + cid, headers=auth).json()["status"] == "CANCELLED"
    assert client.post(root + "/commands", headers=auth, json=payload).status_code == 404


POLICY = "local-wearable-v1"


def real_consent(client, auth, metric="heart_rate_bpm", granted=True):
    return client.put(
        f"{HEALTH}/consents/health_connect/{metric}", headers=auth,
        json={"granted": granted, "policy_version": POLICY},
    )


def hr(**changes):
    return sample(
        client_sample_id="hc-hr-1", metric="heart_rate_bpm", value=72,
        interval_start=None, is_demo=False,
        data_origin="nodomain.freeyourgadget.gadgetbridge", **changes,
    )


def test_real_health_is_opt_in(client, monkeypatch):
    _, auth = account(client)
    monkeypatch.delenv("SHIYI_ENABLE_REAL_HEALTH", raising=False)
    assert real_consent(client, auth).status_code == 403
    assert upload(client, auth, hr()).status_code == 403
    monkeypatch.setenv("SHIYI_ENABLE_REAL_HEALTH", "1")
    assert consent(client, auth, metric="heart_rate_bpm").status_code == 200
    assert upload(client, auth, hr()).status_code == 403
    assert real_consent(client, auth).json()["policy_version"] == POLICY
    first = upload(client, auth, hr())
    assert first.status_code == 200, first.text
    assert upload(client, auth, hr()).json()["items"][0]["duplicate"]
    items = client.get(HEALTH + "/observations", headers=auth).json()["items"]
    assert items[0]["is_demo"] is False
    assert items[0]["data_origin"] == "nodomain.freeyourgadget.gadgetbridge"
    monkeypatch.delenv("SHIYI_ENABLE_REAL_HEALTH")
    assert real_consent(client, auth, granted=False).status_code == 200
    assert upload(client, auth, hr()).status_code == 403


def test_real_health_account_isolation_and_atomicity(client, monkeypatch):
    monkeypatch.setenv("SHIYI_ENABLE_REAL_HEALTH", "1")
    _, alice = account(client)
    _, bob = account(client, "bob")
    assert real_consent(client, alice).status_code == 200
    assert real_consent(client, {"Authorization": "Bearer development-token-123"}).status_code == 403
    steps = sample(is_demo=False, data_origin="nodomain.freeyourgadget.gadgetbridge")
    assert upload(client, alice, hr(), steps).status_code == 403
    assert client.get(HEALTH + "/observations", headers=alice).json()["items"] == []
    assert upload(client, alice, hr()).status_code == 200
    assert client.get(HEALTH + "/observations", headers=bob).json()["items"] == []
    assert upload(client, bob, hr()).status_code == 403
    assert real_consent(client, alice, "steps").status_code == 200
    assert upload(client, alice, steps).status_code == 200
    assert real_consent(client, alice, "sleep_minutes").status_code == 200
    sleep = sample(
        client_sample_id="sleep-1", metric="sleep_minutes", value=420,
        interval_start=(NOW - timedelta(hours=8)).isoformat(),
        is_demo=False, data_origin="nodomain.freeyourgadget.gadgetbridge",
    )
    assert upload(client, alice, sleep).status_code == 200


def test_provenance_validation(client, monkeypatch):
    monkeypatch.setenv("SHIYI_ENABLE_REAL_HEALTH", "1")
    _, auth = account(client)
    assert real_consent(client, auth).status_code == 200
    assert upload(client, auth, {**hr(), "data_origin": None}).status_code == 422
    assert upload(client, auth, {**hr(), "source": "demo"}).status_code == 422
    assert upload(client, auth, {**hr(), "is_demo": "false"}).status_code == 422
    assert upload(client, auth, {**hr(), "is_demo": True}).status_code == 422


def test_embedded_gadgetbridge_source(client, monkeypatch):
    monkeypatch.setenv("SHIYI_ENABLE_REAL_HEALTH", "1")
    _, auth = account(client)
    payload = {**hr(), "source": "gadgetbridge", "data_origin": "org.aihealthy.shiyi.embedded"}
    assert real_consent(client, auth).status_code == 200
    assert upload(client, auth, payload).status_code == 403
    response = client.put(
        HEALTH + "/consents/gadgetbridge/heart_rate_bpm", headers=auth,
        json={"granted": True, "policy_version": POLICY},
    )
    assert response.status_code == 200
    assert upload(client, auth, payload).status_code == 200


def test_wearable_stream_summary_and_revocation(client, monkeypatch):
    monkeypatch.setenv("SHIYI_ENABLE_REAL_HEALTH", "1")
    _, auth = account(client)
    _, other = account(client, "bob")
    for metric in ("steps", "sleep_minutes", "heart_rate_bpm"):
        assert real_consent(client, auth, metric).status_code == 200
    scope = "a" * 32
    common = {"is_demo": False, "data_origin": "test.app", "device_scope": scope}
    rows = [
        sample(**common),
        sample(**{**common, "client_sample_id": "other-device", "device_scope": "b" * 32}),
        sample(**{**common, "client_sample_id": "old", "device_scope": None}),
        sample(**{**common, "client_sample_id": "sleep1", "metric": "sleep_minutes",
                  "value": 120, "observed_at": (NOW - timedelta(hours=8)).isoformat(),
                  "interval_start": (NOW - timedelta(hours=10)).isoformat()}),
        sample(**{**common, "client_sample_id": "sleep2", "metric": "sleep_minutes",
                  "value": 120, "observed_at": (NOW - timedelta(hours=7)).isoformat(),
                  "interval_start": (NOW - timedelta(hours=9)).isoformat()}),
        sample(**{**common, "client_sample_id": "hr1", "metric": "heart_rate_bpm",
                  "value": 72, "interval_start": None}),
    ]
    assert upload(client, auth, *rows).status_code == 200
    params = {"source": "health_connect", "data_origin": "test.app", "device_scope": scope}
    endpoint = HEALTH + "/summary"
    result = client.get(endpoint, headers=auth, params=params)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["steps"] == 1200
    assert data["sleep_minutes"] == 180
    assert data["heart_rate_bpm"] == 72
    assert len(client.get(HEALTH + "/streams", headers=auth).json()) == 2
    assert client.get(endpoint, headers=other, params=params).status_code == 404
    assert real_consent(client, auth, "steps", granted=False).status_code == 200
    assert client.get(endpoint, headers=auth, params=params).json()["steps"] is None
    assert client.get(endpoint, headers=auth, params={**params, "timezone": "invalid"}).status_code == 422


def test_stream_scope_backfill_idempotency(client, monkeypatch):
    monkeypatch.setenv("SHIYI_ENABLE_REAL_HEALTH", "1")
    _, auth = account(client)
    assert real_consent(client, auth).status_code == 200
    original = hr()
    assert upload(client, auth, original).status_code == 200
    scoped = {**original, "device_scope": "a" * 32}
    assert upload(client, auth, scoped).json()["items"][0]["duplicate"]
    assert upload(client, auth, original).json()["items"][0]["duplicate"]
    assert upload(client, auth, {**scoped, "device_scope": "b" * 32}).status_code == 409
    assert len(client.get(HEALTH + "/observations", headers=auth).json()["items"]) == 1
    assert client.get(HEALTH + "/streams", headers=auth).json()[0]["device_scope"] == "a" * 32
