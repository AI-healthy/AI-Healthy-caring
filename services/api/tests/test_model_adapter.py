import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from shiyi_api import storage
from shiyi_api.harness.engine import DecisionContext, choose
from shiyi_api.harness.model_adapter import LocalModelRanker, build_context, route_tool
from shiyi_api.main import app
from shiyi_api.recommendation import catalog_entries

ROOT = "/api/v1/harness"
AUTH = {"Authorization": "Bearer alpha-token-for-tests"}
CONTEXT = DecisionContext(5, 2, frozenset({"culture"}), (("culture", 0.6667), ("walk", 1.2)))
CANDIDATES = tuple(entry for entry in catalog_entries() if entry[2] <= 5)


@pytest.fixture
def server():
    state = {"requests": [], "proposal": {"tool": "rank_activities", "activity_ids": ["culture"]},
             "delay": 0, "status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers["Content-Length"])
            state["requests"].append(json.loads(self.rfile.read(size)))
            time.sleep(state["delay"])
            response = json.dumps({"choices": [{"message": {
                "content": json.dumps(state["proposal"])
            }}]}).encode()
            try:
                self.send_response(state["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{http.server_port}/v1/chat/completions"
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


@pytest.fixture
def client(tmp_path, monkeypatch, server):
    _, endpoint = server
    monkeypatch.setenv("SHIYI_DB_PATH", str(tmp_path / "model.sqlite3"))
    monkeypatch.setenv("SHIYI_DEV_USERS", '{"alice":"alpha-token-for-tests"}')
    monkeypatch.setenv("SHIYI_RANKER", "local_llm")
    monkeypatch.setenv("SHIYI_LOCAL_MODEL_NAME", "synthetic-model")
    monkeypatch.setenv("SHIYI_LOCAL_MODEL_URL", endpoint)
    yield TestClient(app)
    storage.store_for.cache_clear()


def run(client, key, **extra):
    response = client.post(ROOT + "/runs", headers=AUTH, json={"client_request_id": key, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_context_minimization_and_tool_router():
    context = build_context(CONTEXT, CANDIDATES)
    assert context["self_reported_energy_band"] == "low"
    assert context["memory_scores"] == {"culture": 0.67}
    assert set(context) == {"available_minutes", "self_reported_energy_band",
                           "preference_tags", "memory_scores", "candidates"}
    assert route_tool('{"tool":"rank_activities","activity_ids":["culture"]}',
                      CANDIDATES) == ["culture"]


@pytest.mark.parametrize("proposal", [
    {"tool":"create_session","activity_ids":["culture"]},
    {"tool":"rank_activities","activity_ids":["culture","culture"]},
    {"tool":"rank_activities","activity_ids":["walk"]},
    {"tool":"rank_activities","activity_ids":["culture"],"command":"MOVE_HEAD"},
    {"tool":"rank_activities","activity_ids":[]},
])
def test_invalid_tool_falls_back(server, proposal):
    state, endpoint = server
    state["proposal"] = proposal
    options, fallback = choose(CONTEXT, CANDIDATES, LocalModelRanker(endpoint, "fake"))
    assert fallback
    assert options and all(o.activity_id in {c[0] for c in CANDIDATES} for o in options)
    assert len(state["requests"]) == 1


def test_real_loopback_http_and_explicit_opt_in(client, server):
    state, _ = server
    assert run(client, "off")["algorithm"] == "rules_v1"
    assert state["requests"] == []
    assert client.put(ROOT + "/settings", headers=AUTH,
                      json={"use_local_model":True,"preference_tags":["culture"]}).status_code == 200
    plan = run(client, "on", energy_level=1)
    assert plan["algorithm"] == "local_llm_v1"
    assert [o["activity_id"] for o in plan["options"]] == ["culture"]
    assert plan["status"] == "AWAITING_CONFIRMATION"
    assert plan["session_id"] is None
    body = state["requests"][0]
    assert body["model"] == "synthetic-model"
    context = json.loads(body["messages"][1]["content"])
    assert context["self_reported_energy_band"] == "low"
    serialized = json.dumps(body)
    assert "alpha-token-for-tests" not in serialized
    assert "alice" not in serialized
    assert "client_request_id" not in serialized
    assert run(client, "on", energy_level=1)["run_id"] == plan["run_id"]
    assert len(state["requests"]) == 1


def test_timeout_and_http_failure(server):
    state, endpoint = server
    state["delay"] = 0.4
    options, fallback = choose(CONTEXT, CANDIDATES, LocalModelRanker(endpoint, "fake", 0.12))
    assert fallback and options
    state["delay"] = 0
    state["status"] = 503
    assert choose(CONTEXT, CANDIDATES, LocalModelRanker(endpoint, "fake"))[1]


@pytest.mark.parametrize("endpoint", [
    "https://example.invalid/v1/chat/completions",
    "http://localhost:11434/v1/chat/completions",
    "http://127.0.0.1:11434/other",
])
def test_invalid_endpoint_fails_closed(endpoint):
    options, fallback = choose(CONTEXT, CANDIDATES, LocalModelRanker(endpoint, "fake"))
    assert fallback and options
