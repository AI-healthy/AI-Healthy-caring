from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from shiyi_api import storage
from shiyi_api.main import app
from shiyi_api.storage import store_for

ROOT = "/api/v1/activities"
A = {"Authorization": "Bearer alpha-token-for-tests"}
B = {"Authorization": "Bearer beta-token-for-tests"}
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIYI_DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv(
        "SHIYI_DEV_USERS",
        '{"alice":"alpha-token-for-tests","bob":"beta-token-for-tests"}',
    )
    monkeypatch.setattr(storage, "now_utc", lambda: BASE_TIME)
    yield TestClient(app)
    store_for.cache_clear()


def create(client, headers=A, activity="stretch", key="create-1"):
    r = client.post(
        ROOT + "/sessions", headers=headers,
        json={"activity_id": activity, "client_request_id": key},
    )
    assert r.status_code == 200, r.text
    return r.json()


def action(client, sid, verb, headers=A):
    return client.post(f"{ROOT}/sessions/{sid}/{verb}", headers=headers)


def test_full_lifecycle_and_persistence(client):
    data = create(client)
    sid = data["session_id"]
    assert data["status"] == "CREATED"
    assert data["duration_minutes"] == 5
    assert data["is_demo"] is True
    assert action(client, sid, "start").json()["status"] == "RUNNING"
    assert action(client, sid, "complete").json()["status"] == "COMPLETED"
    payload = {
        "session_id": sid, "activity_id": "stretch", "completed": True,
        "client_event_id": "feedback-1", "enjoyment": 4,
    }
    first = client.post(ROOT + "/feedback", headers=A, json=payload)
    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    # Reopen the persisted database rather than relying on process-local state.
    store_for.cache_clear()
    assert client.get(f"{ROOT}/sessions/{sid}", headers=A).json()["status"] == "COMPLETED"
    assert client.post(ROOT + "/feedback", headers=A, json=payload).json()["duplicate"] is True
    assert action(client, sid, "complete").status_code == 200
    assert action(client, sid, "cancel").status_code == 409


def test_auth_and_other_user_isolation(client):
    sid = create(client)["session_id"]
    assert client.get(f"{ROOT}/sessions/{sid}").status_code == 401
    assert client.get(f"{ROOT}/sessions/{sid}", headers=B).status_code == 404
    assert action(client, sid, "start", B).status_code == 404
    assert create(client, B)["session_id"] != sid
    payload = {"session_id": sid, "activity_id": "stretch", "completed": True,
               "client_event_id": "e2"}
    assert client.post(ROOT + "/feedback", headers=B, json=payload).status_code == 404
    assert client.get(
        f"{ROOT}/sessions/{sid}", headers={"Authorization": "Bearer invalid"}
    ).status_code == 401


def test_create_idempotency_and_catalog(client):
    data = create(client)
    assert create(client)["session_id"] == data["session_id"]
    response = client.post(ROOT + "/sessions", headers=A,
                           json={"activity_id": "walk", "client_request_id": "create-1"})
    assert response.status_code == 409
    response = client.post(ROOT + "/sessions", headers=A, json={"activity_id": "invented"})
    assert response.status_code == 404


def test_cancel_and_illegal_transitions(client):
    sid = create(client)["session_id"]
    assert action(client, sid, "complete").status_code == 409
    assert action(client, sid, "cancel").json()["status"] == "CANCELLED"
    assert action(client, sid, "start").status_code == 409
    payload = {"session_id": sid, "activity_id": "stretch", "completed": False,
               "client_event_id": "cancelled"}
    assert client.post(ROOT + "/feedback", headers=A, json=payload).status_code == 200


@pytest.mark.parametrize("start,elapsed", [(False, 30), (True, 15)])
def test_expiration_and_no_resurrection(client, monkeypatch, start, elapsed):
    sid = create(client)["session_id"]
    if start:
        assert action(client, sid, "start").status_code == 200
    monkeypatch.setattr(storage, "now_utc", lambda: BASE_TIME + timedelta(minutes=elapsed))
    assert action(client, sid, "complete").status_code == 409
    result = client.get(f"{ROOT}/sessions/{sid}", headers=A).json()
    assert result["status"] == "EXPIRED"
    assert result["ended_at"] == result["expires_at"]
    assert action(client, sid, "start").status_code == 409


def test_feedback_checks_terminal_state_and_conflicts(client):
    sid = create(client)["session_id"]
    payload = {"session_id": sid, "activity_id": "stretch", "completed": True,
               "client_event_id": "feedback-2"}
    assert client.post(ROOT + "/feedback", headers=A, json=payload).status_code == 409
    action(client, sid, "start")
    action(client, sid, "complete")
    assert client.post(ROOT + "/feedback", headers=A,
                       json={**payload, "activity_id": "walk"}).status_code == 409
    assert client.post(ROOT + "/feedback", headers=A,
                       json={**payload, "completed": False}).status_code == 409
    assert client.post(ROOT + "/feedback", headers=A, json=payload).status_code == 200
    assert client.post(ROOT + "/feedback", headers=A,
                       json={**payload, "enjoyment": 3}).status_code == 409
    assert client.post(ROOT + "/feedback", headers=A,
                       json={**payload, "client_event_id": "new"}).status_code == 409


def test_legacy_events_are_user_scoped(client):
    payload = {"activity_id": "stretch", "completed": True, "client_event_id": "legacy"}
    for headers in (A, B):
        response = client.post(ROOT + "/feedback", headers=headers, json=payload)
        assert response.status_code == 200
        assert response.json()["duplicate"] is False
        assert client.post(ROOT + "/feedback", headers=headers,
                           json=payload).json()["duplicate"] is True
