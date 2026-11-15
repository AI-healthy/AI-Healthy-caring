from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from shiyi_api import storage
from shiyi_api.main import app
from shiyi_api.simulator import run_once

USER = {"Authorization": "Bearer alpha-token-for-tests"}
OTHER = {"Authorization": "Bearer bravo-token-for-tests"}
TOKEN = "simulator-token-for-tests"
DEVICE = {"Authorization": f"Bearer {TOKEN}"}
ROOT = "/api/v1/devices"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIYI_DB_PATH", str(tmp_path / "devices.sqlite3"))
    monkeypatch.setenv("SHIYI_DEV_USERS",
                       '{"alice":"alpha-token-for-tests","bob":"bravo-token-for-tests"}')
    monkeypatch.setenv("SHIYI_DEV_DEVICES",
                       '{"sim":{"user_id":"alice","token":"simulator-token-for-tests"},'
                       '"other":{"user_id":"bob","token":"another-device-token-test"}}')
    yield TestClient(app)
    storage.store_for.cache_clear()


def new_session(client):
    a = client.post("/api/v1/recommendations",
                    json={"context":{"available_minutes":5,"source":"demo","is_demo":True}})
    activity_id = a.json()["options"][0]["activity_id"]
    a = client.post("/api/v1/activities/sessions", headers=USER,
                    json={"activity_id":activity_id,"client_request_id":"session"})
    sid = a.json()["session_id"]
    assert client.post(f"/api/v1/activities/sessions/{sid}/start", headers=USER).status_code == 200
    return sid, activity_id


def enqueue(client, sid, key="command"):
    r = client.post(ROOT + "/commands", headers=USER,
                    json={"session_id":sid,"device_id":"sim","client_request_id":key})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("fail", [False, True])
def test_end_to_end(client, fail):
    sid, activity_id = new_session(client)
    command = enqueue(client, sid)
    assert command["status"] == "QUEUED"
    assert command["is_demo"]
    assert enqueue(client, sid)["command_id"] == command["command_id"]
    result = run_once(client, "sim", TOKEN, fail=fail)
    target = "FAILED" if fail else "COMPLETED"
    assert result["command"]["status"] == target
    storage.store_for.cache_clear()
    assert client.get(ROOT + "/commands/" + command["command_id"],
                      headers=USER).json()["status"] == target
    assert run_once(client, "sim", TOKEN) is None
    # A robot delivery result is NOT proof of user exercise completion.
    session_path = f"/api/v1/activities/sessions/{sid}"
    assert client.get(session_path, headers=USER).json()["status"] == "RUNNING"
    assert client.post(session_path + "/complete", headers=USER).status_code == 200
    feedback = {"session_id":sid,"activity_id":activity_id,
                "client_event_id":"feedback","completed":True}
    assert client.post("/api/v1/activities/feedback", headers=USER, json=feedback).status_code == 200


def test_credentials_and_validation(client):
    sid, _ = new_session(client)
    command = enqueue(client, sid)
    assert client.get(ROOT + "/sim/pending", headers=USER).status_code == 401
    assert client.get(ROOT + "/other/pending", headers=DEVICE).status_code == 401
    assert client.get(ROOT + "/commands/" + command["command_id"],
                      headers=OTHER).status_code == 404
    assert client.post(ROOT + "/commands", headers=OTHER,
                       json={"session_id":sid,"device_id":"sim",
                             "client_request_id":"intruder"}).status_code == 404
    assert client.post(ROOT + "/commands", headers=USER,
                       json={"session_id":sid,"device_id":"sim",
                             "preset":"arbitrary","client_request_id":"bad"}).status_code == 422
    assert client.post(ROOT + "/commands", headers=DEVICE,
                       json={"session_id":sid,"device_id":"sim",
                             "client_request_id":"bad"}).status_code == 401


def test_expiry_and_cancel(client, monkeypatch):
    sid, _ = new_session(client)
    command = enqueue(client, sid)
    now = storage.now_utc()
    monkeypatch.setattr(storage, "now_utc", lambda: now + timedelta(seconds=61))
    assert client.get(ROOT + "/sim/pending", headers=DEVICE).json() is None
    assert client.get(ROOT + "/commands/" + command["command_id"],
                      headers=USER).json()["status"] == "EXPIRED"
    next_command = enqueue(client, sid, "next")
    assert client.post(f"/api/v1/activities/sessions/{sid}/cancel", headers=USER).status_code == 200
    assert client.get(ROOT + "/sim/pending", headers=DEVICE).json() is None
    assert client.get(ROOT + "/commands/" + next_command["command_id"],
                      headers=USER).json()["status"] == "CANCELLED"


def test_event_order_replay_and_conflict(client):
    sid, _ = new_session(client)
    command = enqueue(client, sid)
    event = {"schema_version":"0.1-draft","event_id":"ack","device_id":"sim",
             "type":"COMMAND_ACKNOWLEDGED","command_id":command["command_id"],
             "occurred_at":storage.now_utc().isoformat(),"is_demo":True}
    path = ROOT + "/sim/events"
    assert client.post(path, headers=DEVICE,
                       json={**event,"type":"COMMAND_COMPLETED"}).status_code == 409
    assert not client.post(path, headers=DEVICE, json=event).json()["duplicate"]
    assert client.post(path, headers=DEVICE, json=event).json()["duplicate"]
    assert client.post(path, headers=DEVICE,
                       json={**event,"type":"COMMAND_FAILED"}).status_code == 409
    assert client.post(path, headers=DEVICE,
                       json={**event,"device_id":"other"}).status_code == 409
    assert client.post(path, headers=DEVICE,
                       json={**event,"is_demo":False}).status_code == 422


def test_simulator_resumes_after_ack(client):
    sid, _ = new_session(client)
    command = enqueue(client, sid)
    ack = {
        "schema_version": "0.1-draft", "event_id": "previous-ack", "device_id": "sim",
        "type": "COMMAND_ACKNOWLEDGED", "command_id": command["command_id"],
        "occurred_at": storage.now_utc().isoformat(), "is_demo": True,
    }
    assert client.post(ROOT + "/sim/events", headers=DEVICE, json=ack).status_code == 200
    assert client.get(ROOT + "/sim/pending", headers=DEVICE).json()["status"] == "ACKNOWLEDGED"
    assert run_once(client, "sim", TOKEN)["command"]["status"] == "COMPLETED"
