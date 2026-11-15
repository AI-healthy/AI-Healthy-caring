from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from shiyi_api import storage
from shiyi_api.harness.proactive import tick
from shiyi_api.main import app

ROOT = "/api/v1/proactive"
H = "/api/v1/harness"
A = {"Authorization": "Bearer alpha-token-for-tests"}
B = {"Authorization": "Bearer bravo-token-for-tests"}
NOW = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIYI_DB_PATH", str(tmp_path / "proactive.sqlite3"))
    monkeypatch.setenv("SHIYI_DEV_USERS",
                       '{"alice":"alpha-token-for-tests","bob":"bravo-token-for-tests"}')
    monkeypatch.setenv("SHIYI_RANKER", "rules")
    monkeypatch.setattr(storage, "now_utc", lambda: NOW)
    yield TestClient(app)
    storage.store_for.cache_clear()


def opt_in(client, auth=A, **extra):
    response = client.put(H + "/settings", headers=auth, json={
        "proactive_enabled":True, "timezone":"UTC", "quiet_start":"22:00:00",
        "quiet_end":"01:00:00", **extra,
    })
    assert response.status_code == 200, response.text


def schedule(client, auth=A, **extra):
    response = client.put(ROOT + "/schedule", headers=auth, json={
        "enabled":True, **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def pending(client, auth=A):
    r = client.get(ROOT + "/offers/pending", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def confirm(client, invitation, auth=A):
    run = invitation["run"]
    return client.post(H + "/runs/" + run["run_id"] + "/confirm", headers=auth,
                       json={"activity_id":run["options"][0]["activity_id"]})


def test_optin_schedule_atomic_and_app_receipt(client):
    assert tick(storage.get_store()) == {}
    assert client.put(ROOT + "/schedule", headers=A, json={"enabled":True}).status_code == 409
    assert client.get(ROOT + "/schedule", headers=A).json()["enabled"] is False
    opt_in(client)
    schedule(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: tick(storage.get_store()), range(2)))
    assert sum(x.get("offer_created", 0) for x in results) == 1
    invitation = pending(client)
    assert invitation["run"]["status"] == "AWAITING_CONFIRMATION"
    assert invitation["run"]["algorithm"] == "rules_v1"
    assert invitation["run"]["session_id"] is None
    assert pending(client, B) is None
    path = ROOT + "/offers/" + invitation["offer_id"] + "/ack"
    assert client.post(path, headers=B).status_code == 404
    receipt = client.post(path, headers=A).json()
    assert receipt["acknowledged_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert client.post(path, headers=A).json() == receipt
    assert pending(client)["acknowledged_at"] == receipt["acknowledged_at"]
    storage.store_for.cache_clear()
    assert pending(client)["offer_id"] == invitation["offer_id"]
    assert confirm(client, invitation).json()["session"]["status"] == "CREATED"
    assert pending(client) is None
    assert tick(storage.get_store()) == {}


def test_expired_lease_and_no_backlog(client, monkeypatch):
    opt_in(client)
    schedule(client, available_for_minutes=15)
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(minutes=16))
    assert tick(storage.get_store()) == {"availability_expired":1}
    assert pending(client) is None
    assert client.get(ROOT + "/schedule", headers=A).json()["next_check_at"] is None
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(days=1))
    assert tick(storage.get_store()) == {}


def test_disable_then_reenable_requires_new_lease(client):
    opt_in(client)
    schedule(client)
    assert tick(storage.get_store()) == {"offer_created":1}
    invitation = pending(client)
    assert client.put(H + "/settings", headers=A, json={}).status_code == 200
    opt_in(client)
    assert pending(client) is None
    assert confirm(client, invitation).status_code == 409
    assert tick(storage.get_store()) == {}
    assert client.get(ROOT + "/schedule", headers=A).json()["available_until"] is None


def test_pause_revokes_invitation(client):
    opt_in(client)
    schedule(client)
    tick(storage.get_store())
    invitation = pending(client)
    assert client.put(ROOT + "/schedule", headers=A, json={"enabled":False}).status_code == 200
    assert pending(client) is None
    assert confirm(client, invitation).status_code == 409
    assert client.post(ROOT + "/offers/" + invitation["offer_id"] + "/ack",
                       headers=A).status_code == 409


def test_quiet_at_delivery_and_active_activity(client, monkeypatch):
    opt_in(client, quiet_start="04:02:00", quiet_end="06:00:00")
    schedule(client)
    tick(storage.get_store())
    invitation = pending(client)
    assert invitation is not None
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(minutes=3))
    assert confirm(client, invitation).status_code == 409
    assert pending(client) is None
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(minutes=16))
    # The worker re-evaluates quiet hours; no stale delivery.
    assert tick(storage.get_store()) == {"quiet_hours":1}
    opt_in(client, B)
    schedule(client, B)
    r = client.post("/api/v1/activities/sessions", headers=B, json={"activity_id":"stretch"})
    assert r.status_code == 200
    assert tick(storage.get_store()) == {"active_activity":1}
    assert pending(client, B) is None


def account(client, name):
    credentials = {"username":name,"password":"synthetic-password-123"}
    assert client.post("/api/v1/users/register", json=credentials).status_code == 201
    r = client.post("/api/v1/users/login", json=credentials)
    assert r.status_code == 200
    return {"Authorization":"Bearer " + r.json()["access_token"]}


def bind(client, auth):
    r = client.post("/api/v1/users/me/simulated-devices", headers=auth, json={"name":"Demo"})
    assert r.status_code == 201, r.text
    return r.json()["device"]["device_id"], {"Authorization":"Bearer " + r.json()["device_token"]}


def test_simulator_target_minimal_receipt_and_user_confirmation(client):
    auth = account(client, "device_owner")
    other = account(client, "another_owner")
    device, dev_auth = bind(client, auth)
    second, second_auth = bind(client, auth)
    opt_in(client, auth)
    opt_in(client, other)
    assert client.put(ROOT + "/schedule", headers=other, json={
        "enabled":True,"channel":"simulator","device_id":device,
    }).status_code == 404
    schedule(client, auth, channel="simulator", device_id=device)
    assert tick(storage.get_store()) == {"offer_created":1}
    invitation = pending(client, auth)
    path = ROOT + "/devices/" + device
    r = client.get(path + "/pending", headers=dev_auth)
    assert r.status_code == 200
    message = r.json()
    assert set(message) == {"offer_id","message_code","expires_at","is_demo"}
    assert message["offer_id"] == invitation["offer_id"]
    assert client.get(ROOT + "/devices/" + second + "/pending", headers=second_auth).json() is None
    assert client.get(path + "/pending", headers=auth).status_code == 401
    ack_path = path + "/offers/" + message["offer_id"] + "/ack"
    assert client.post(ROOT + "/offers/" + message["offer_id"] + "/ack",
                       headers=auth).status_code == 404
    result = client.post(ack_path, headers=dev_auth)
    assert result.status_code == 200
    assert client.post(ack_path, headers=dev_auth).json() == result.json()
    assert client.get(path + "/pending", headers=dev_auth).json() is None
    assert pending(client, auth)["run"]["session_id"] is None
    assert confirm(client, invitation, dev_auth).status_code == 401
    assert confirm(client, invitation, auth).json()["session"]["status"] == "CREATED"


def test_revoking_simulator_invalidates_pending(client):
    auth = account(client, "revoke_owner")
    device, dev_auth = bind(client, auth)
    opt_in(client, auth)
    schedule(client, auth, channel="simulator", device_id=device)
    tick(storage.get_store())
    invitation = pending(client, auth)
    assert client.delete("/api/v1/users/me/simulated-devices/" + device,
                         headers=auth).status_code == 204
    assert client.get(ROOT + "/devices/" + device + "/pending", headers=dev_auth).status_code == 401
    assert confirm(client, invitation, auth).status_code == 409
    assert pending(client, auth) is None
