from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from shiyi_api import storage
from shiyi_api.harness.contracts import RunRequest
from shiyi_api.harness.repository import create_run, reset_memory
from shiyi_api.main import app

ROOT = "/api/v1/harness"
A = {"Authorization": "Bearer alpha-token-for-tests"}
B = {"Authorization": "Bearer bravo-token-for-tests"}
NOW = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIYI_DB_PATH", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("SHIYI_DEV_USERS",
                       '{"alice":"alpha-token-for-tests","bob":"bravo-token-for-tests"}')
    monkeypatch.setenv("SHIYI_RANKER", "rules")
    monkeypatch.setattr(storage, "now_utc", lambda: NOW)
    yield TestClient(app)
    storage.store_for.cache_clear()


def settings(client, headers=A, **kwargs):
    response = client.put(ROOT + "/settings", headers=headers, json=kwargs)
    assert response.status_code == 200, response.text


def complete(client, aid, key, rating=None, headers=A):
    r = client.post("/api/v1/activities/sessions", headers=headers,
                    json={"activity_id": aid, "client_request_id": key})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    path = "/api/v1/activities/sessions/" + sid
    assert client.post(path + "/start", headers=headers).status_code == 200
    assert client.post(path + "/complete", headers=headers).status_code == 200
    if rating is not None:
        r = client.post("/api/v1/activities/feedback", headers=headers, json={
            "session_id": sid, "activity_id": aid, "client_event_id": key,
            "completed": True, "enjoyment": rating,
        })
        assert r.status_code == 200, r.text
    return sid


def memory(client, headers=A, minutes=None):
    params = {} if minutes is None else {"available_minutes": minutes}
    r = client.get(ROOT + "/memory", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def run(client, key, **kwargs):
    r = client.post(ROOT + "/runs", headers=A, json={"client_request_id": key, **kwargs})
    assert r.status_code == 200, r.text
    return r.json()


def test_temporal_decay_and_expiry(client, monkeypatch):
    settings(client, use_feedback_memory=True)
    complete(client, "culture", "rated", 5)
    item = memory(client)["entries"][0]
    assert item["score"] == pytest.approx(2 / 3, abs=0.0001)
    assert item["effective_weight"] == 1
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(days=7))
    item = memory(client)["entries"][0]
    assert item["effective_weight"] == 0.5
    assert item["score"] == 0.4
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(days=31))
    assert memory(client)["entries"] == []


def test_candidate_filter_precedes_budget_and_local_cap(client, monkeypatch):
    settings(client, use_feedback_memory=True, memory_budget=2)
    complete(client, "culture", "eligible", 5)
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(hours=1))
    for i in range(5):
        complete(client, "walk", f"walk-{i}", 1)
    assert memory(client)["recalled_events"] == 2
    scoped = memory(client, minutes=5)
    assert scoped["recalled_events"] == 1
    assert [m["activity_id"] for m in scoped["entries"]] == ["culture"]
    assert run(client, "filtered")["options"][0]["activity_id"] == "culture"
    settings(client, use_feedback_memory=True, memory_budget=20)
    assert memory(client)["recalled_events"] == 5
    assert next(m for m in memory(client)["entries"] if m["activity_id"] == "walk")["count"] == 4
    settings(client, use_feedback_memory=True, blocked_activity_ids=["culture"])
    assert memory(client, minutes=5)["entries"] == []


def test_behavior_separate_and_expires(client, monkeypatch):
    settings(client, use_behavior_memory=True)
    assert run(client, "first")["options"][0]["activity_id"] == "stretch"
    complete(client, "stretch", "behavior", 5)
    item = memory(client)["entries"][0]
    assert item["count"] == 0
    assert item["recent_completions"] == 1
    assert item["decision_score"] == -0.25
    assert run(client, "variety")["options"][0]["activity_id"] == "culture"
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(days=3))
    assert memory(client)["entries"] == []
    assert run(client, "after")["options"][0]["activity_id"] == "stretch"


def test_reset_and_reenable_exclude_same_timestamp_evidence(client):
    complete(client, "culture", "before", 5)
    settings(client, use_feedback_memory=True, use_behavior_memory=True)
    assert memory(client)["entries"] == []
    complete(client, "culture", "after", 5)
    assert memory(client)["entries"][0]["count"] == 1
    pending = run(client, "pending")
    result = client.post(ROOT + "/memory/reset", headers=A)
    assert result.status_code == 200
    assert result.json()["entries"] == []
    assert result.json()["enabled"] and result.json()["behavior_enabled"]
    assert client.get(ROOT + "/runs/" + pending["run_id"],
                      headers=A).json()["status"] == "INVALIDATED"
    assert client.post(ROOT + "/runs/" + pending["run_id"] + "/confirm",
                       headers=A, json={"activity_id":"culture"}).status_code == 409
    complete(client, "stretch", "new", 4)
    storage.store_for.cache_clear()
    assert [m["activity_id"] for m in memory(client)["entries"]] == ["stretch"]
    settings(client)
    assert memory(client)["entries"] == []
    complete(client, "culture", "while-off", 5)
    settings(client, use_feedback_memory=True, use_behavior_memory=True)
    assert memory(client)["entries"] == []
    complete(client, "culture", "reenabled", 4)
    assert memory(client)["entries"][0]["count"] == 1


def test_reset_isolation_and_preserves_business_record(client):
    settings(client, use_feedback_memory=True)
    settings(client, headers=B, use_feedback_memory=True)
    sid = complete(client, "culture", "same", 5)
    complete(client, "stretch", "same", 1, B)
    assert client.post(ROOT + "/memory/reset", headers=A).status_code == 200
    assert memory(client)["entries"] == []
    assert memory(client, B)["entries"][0]["activity_id"] == "stretch"
    assert client.get("/api/v1/activities/sessions/" + sid,
                      headers=A).json()["status"] == "COMPLETED"
    assert client.post(ROOT + "/memory/reset").status_code == 401


def test_reset_during_inference_replans(client):
    settings(client, use_feedback_memory=True)
    complete(client, "culture", "experience", 5)
    store = storage.get_store()

    class ResettingRanker:
        def rank(self, context, candidates):
            assert dict(context.memory_scores)["culture"] > 0
            reset_memory(store, "alice")
            return ["culture"]

    plan = create_run(store, "alice", RunRequest(client_request_id="race"), ResettingRanker())
    assert plan.algorithm == "rules_v1"
    assert plan.options[0].activity_id == "stretch"
    assert plan.trace[-1].result == "context_changed_replanned"


def test_no_learning_from_unbound_or_cancelled_feedback(client):
    settings(client, use_feedback_memory=True, use_behavior_memory=True)
    response = client.post("/api/v1/activities/feedback", headers=A, json={
        "activity_id":"culture","completed":True,"enjoyment":5,"client_event_id":"unbound"
    })
    assert response.status_code == 200
    r = client.post("/api/v1/activities/sessions", headers=A, json={"activity_id":"culture"})
    sid = r.json()["session_id"]
    assert client.post(f"/api/v1/activities/sessions/{sid}/cancel", headers=A).status_code == 200
    assert client.post("/api/v1/activities/feedback", headers=A, json={
        "session_id":sid,"activity_id":"culture","completed":False,"enjoyment":1,
        "client_event_id":"cancelled"
    }).status_code == 200
    assert memory(client)["entries"] == []
