from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from shiyi_api import storage
from shiyi_api.harness.api import get_ranker
from shiyi_api.harness.contracts import RunRequest, Settings
from shiyi_api.harness.repository import create_run, put_settings
from shiyi_api.main import app

ROOT = "/api/v1/harness"
A = {"Authorization": "Bearer alpha-token-for-tests"}
B = {"Authorization": "Bearer bravo-token-for-tests"}
NOW = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIYI_DB_PATH", str(tmp_path / "harness.sqlite3"))
    monkeypatch.setenv("SHIYI_DEV_USERS",
                       '{"alice":"alpha-token-for-tests","bob":"bravo-token-for-tests"}')
    monkeypatch.setattr(storage, "now_utc", lambda: NOW)
    yield TestClient(app)
    storage.store_for.cache_clear()


def settings(client, **kwargs):
    response = client.put(ROOT + "/settings", headers=A, json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def run(client, key="run-1", headers=A, **kwargs):
    response = client.post(ROOT + "/runs", headers=headers,
                           json={"client_request_id":key, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, plan, aid=None, headers=A):
    return client.post(ROOT + "/runs/" + plan["run_id"] + "/confirm", headers=headers,
                       json={"activity_id":aid or plan["options"][0]["activity_id"]})


def test_run_confirm_idempotency_and_isolation(client):
    plan = run(client)
    assert plan["status"] == "AWAITING_CONFIRMATION"
    assert run(client)["run_id"] == plan["run_id"]
    assert client.post(ROOT + "/runs", headers=A,
                       json={"client_request_id":"run-1","available_minutes":20}).status_code == 409
    assert client.get(ROOT + "/runs/" + plan["run_id"], headers=B).status_code == 404
    assert confirm(client, plan, headers=B).status_code == 404
    assert confirm(client, plan, "invented").status_code == 422
    first = confirm(client, plan)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["session"]["status"] == "CREATED"
    assert data["run"]["status"] == "CONFIRMED"
    sid = data["session"]["session_id"]
    storage.store_for.cache_clear()
    assert confirm(client, plan).json()["session"]["session_id"] == sid
    assert confirm(client, plan, plan["options"][1]["activity_id"]).status_code == 409


def test_expired_dismissed_and_invalidated(client, monkeypatch):
    plan = run(client)
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(minutes=10))
    assert confirm(client, plan).status_code == 409
    assert client.get(ROOT + "/runs/" + plan["run_id"], headers=A).json()["status"] == "EXPIRED"
    other = run(client, "run-2")
    path = ROOT + "/runs/" + other["run_id"]
    assert client.post(path + "/dismiss", headers=A).json()["status"] == "DISMISSED"
    assert confirm(client, other).status_code == 409
    pending = run(client, "run-3")
    settings(client, blocked_activity_ids=["stretch"])
    assert confirm(client, pending).status_code == 409
    assert client.get(ROOT + "/runs/" + pending["run_id"],
                      headers=A).json()["status"] == "INVALIDATED"


def test_filter_and_no_action(client):
    settings(client, blocked_activity_ids=["stretch"], preference_tags=["culture"])
    plan = run(client, skip_activity_ids=["baduanjin_intro"])
    assert [x["activity_id"] for x in plan["options"]] == ["culture"]
    assert run(client, "short", available_minutes=1)["reason"] == "no_eligible_activity"
    assert run(client, "unwell", availability="unwell")["reason"] == "user_unavailable"
    assert client.get(ROOT + "/settings").status_code == 401


def _observe(client, key, value, when, headers=A):
    health = "/api/v1/health"
    consent = {"granted":True,"policy_version":"local-demo-v1"}
    assert client.put(health + "/consents/self_report/energy_level",
                      headers=headers,json=consent).status_code == 200
    item = {"source":"self_report","metric":"energy_level","client_sample_id":key,
            "value":value,"observed_at":when.isoformat(),"is_demo":True}
    if value is None:
        item["missing_reason"] = "not_reported"
    assert client.post(health + "/observations", headers=headers,
                       json={"observations":[item]}).status_code == 200


def test_perception_freshness_missing_consent_and_explicit_priority(client):
    settings(client, use_observations=True)
    _observe(client, "old", 1, NOW - timedelta(hours=7))
    old = run(client, "old")
    assert old["trace"][1]["result"] == "no_fresh_authorized_observation"
    _observe(client, "new", 1, NOW - timedelta(minutes=2))
    plan = run(client, "fresh")
    assert plan["trace"][1]["result"] == "authorized_synthetic_self_report"
    assert plan["options"][0]["activity_id"] == "stretch"
    explicit = run(client, "explicit", energy_level=5)
    assert explicit["trace"][1]["result"] == "explicit_self_report"
    _observe(client, "missing", None, NOW - timedelta(minutes=1))
    assert run(client, "missing")["trace"][1]["result"] == "missing_observation"
    assert client.put("/api/v1/health/consents/self_report/energy_level",
                      headers=A,json={"granted":False,"policy_version":"local-demo-v1"}).status_code == 200
    assert confirm(client, plan).status_code == 409
    assert run(client, "revoked")["trace"][1]["result"] == "no_fresh_authorized_observation"


def test_memory_opt_in_updates_scores_and_changes_order(client):
    settings(client, use_feedback_memory=True)
    initial = run(client)
    assert initial["options"][0]["activity_id"] == "stretch"
    receipt = confirm(client, initial, "culture")
    sid = receipt.json()["session"]["session_id"]
    path = "/api/v1/activities/sessions/" + sid
    assert client.post(path + "/start", headers=A).status_code == 200
    assert client.post(path + "/complete", headers=A).status_code == 200
    feedback = {"session_id":sid,"activity_id":"culture","client_event_id":"rated",
                "completed":True,"enjoyment":5}
    assert client.post("/api/v1/activities/feedback", headers=A,json=feedback).status_code == 200
    memory = client.get(ROOT + "/memory", headers=A).json()
    assert memory["entries"][0]["activity_id"] == "culture"
    assert memory["entries"][0]["count"] == 1
    assert run(client, "learned")["options"][0]["activity_id"] == "culture"
    assert client.get(ROOT + "/memory", headers=B).json()["entries"] == []
    settings(client)
    assert client.get(ROOT + "/memory", headers=A).json()["entries"] == []
    assert run(client, "off")["options"][0]["activity_id"] == "stretch"


def test_proactive_gate(client, monkeypatch):
    assert run(client, "disabled", trigger="scheduled_check")["reason"] == "proactive_disabled"
    settings(client, proactive_enabled=True, timezone="Asia/Shanghai")
    assert run(client, "first", trigger="scheduled_check")["status"] == "AWAITING_CONFIRMATION"
    assert run(client, "second", trigger="scheduled_check")["reason"] == "cooldown"
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(hours=4))
    assert run(client, "third", trigger="scheduled_check")["status"] == "AWAITING_CONFIRMATION"
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(hours=8))
    assert run(client, "limit", trigger="scheduled_check")["reason"] == "daily_offer_limit"
    monkeypatch.setattr(storage, "now_utc", lambda: NOW + timedelta(hours=11))
    assert run(client, "quiet", trigger="scheduled_check")["reason"] == "quiet_hours"
    assert run(client, "manual")["status"] == "AWAITING_CONFIRMATION"


@pytest.mark.parametrize("ids", [["injected"], ["stretch", "stretch"], []])
def test_bad_ranker_falls_back(client, ids):
    class InvalidRanker:
        def rank(self, context, candidates):
            return ids

    plan = create_run(storage.get_store(), "alice", RunRequest(client_request_id="adapter"),
                      InvalidRanker())
    assert plan.algorithm == "rules_v1_fallback"
    assert all(x.activity_id in {"stretch", "culture", "baduanjin_intro"} for x in plan.options)


def test_raising_ranker_falls_back(client):
    class BrokenRanker:
        def rank(self, context, candidates):
            raise RuntimeError("synthetic adapter failure")

    plan = create_run(storage.get_store(), "alice", RunRequest(client_request_id="broken"),
                      BrokenRanker())
    assert plan.algorithm == "rules_v1_fallback"


def test_server_side_ranker_dependency(client):
    class CultureRanker:
        def rank(self, context, candidates):
            assert context.available_minutes == 5
            return ["culture"]

    app.dependency_overrides[get_ranker] = CultureRanker
    try:
        plan = run(client)
        assert plan["algorithm"] == "adapter_v1"
        assert [o["activity_id"] for o in plan["options"]] == ["culture"]
        settings(client, blocked_activity_ids=["culture"])
        result = run(client, "blocked")
        assert result["algorithm"] == "rules_v1_fallback"
        assert "culture" not in [o["activity_id"] for o in result["options"]]
    finally:
        app.dependency_overrides.pop(get_ranker, None)


def test_active_activity_blocks_proactive(client):
    settings(client, proactive_enabled=True)
    pending = run(client)
    assert run(client, "pending", trigger="scheduled_check")["reason"] == "pending_plan"
    assert confirm(client, pending).status_code == 200
    assert run(client, "active", trigger="scheduled_check")["reason"] == "active_activity"


def test_delete_observation_invalidates_pending_plan(client):
    settings(client, use_observations=True)
    _observe(client, "fresh", 1, NOW - timedelta(minutes=1))
    plan = run(client)
    other_plan = run(client, headers=B)
    health = "/api/v1/health/observations"
    oid = client.get(health, headers=A).json()["items"][0]["observation_id"]
    assert client.delete(health + "/" + oid, headers=A).status_code == 204
    assert confirm(client, plan).status_code == 409
    assert confirm(client, other_plan, headers=B).status_code == 200


def test_ranker_runs_outside_write_transaction_and_revalidates(client):
    store = storage.get_store()

    class ChangingRanker:
        def rank(self, context, candidates):
            # This would deadlock/fail inside the old BEGIN IMMEDIATE transaction.
            put_settings(store, "alice", Settings(blocked_activity_ids=["culture"]))
            return ["culture"]

    plan = create_run(store, "alice", RunRequest(client_request_id="revalidate"), ChangingRanker())
    assert plan.algorithm == "rules_v1"
    assert "culture" not in [x.activity_id for x in plan.options]
    assert plan.trace[-1].result == "context_changed_replanned"


def test_ranker_rechecks_concurrent_proactive_offer(client):
    settings(client, proactive_enabled=True)
    store = storage.get_store()

    class CompetingRanker:
        def rank(self, context, candidates):
            other = create_run(store, "alice", RunRequest(
                client_request_id="other", trigger="scheduled_check"
            ))
            assert other.status == "AWAITING_CONFIRMATION"
            return ["culture"]

    plan = create_run(store, "alice", RunRequest(
        client_request_id="competing", trigger="scheduled_check"
    ), CompetingRanker())
    assert plan.status == "NO_ACTION"
    assert plan.reason == "cooldown"
    assert plan.trace[-1].result == "context_changed_replanned"
