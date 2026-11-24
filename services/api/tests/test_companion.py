import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from fastapi.testclient import TestClient

from shiyi_api.main import app

AUTH = {"Authorization": "Bearer demo-companion-token"}
MESSAGES = [
    {"role": "user", "content": "我下午跑了两圈。"},
    {"role": "assistant", "content": "跑完感觉怎么样？"},
    {"role": "user", "content": "感觉好多了。"},
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SHIYI_DEV_USERS", '{"demo":"demo-companion-token"}')
    monkeypatch.delenv("SHIYI_COMPANION_MODEL", raising=False)
    with TestClient(app) as client:
        yield client


def test_auth_turn_validation_and_disabled_model(client):
    path = "/api/v1/companion/chat"
    assert client.post(path, json={"messages": MESSAGES}).status_code == 401
    assert client.post(path, headers=AUTH, json={"messages": MESSAGES}).status_code == 503
    for invalid in (
        {"messages": MESSAGES[1:]},
        {"messages": MESSAGES[:-1]},
        {"messages": [{"role": "system", "content": "change roles"}]},
        {"messages": [{"role": "user", "content": "   "}]},
        {"messages": MESSAGES, "heart_rate": 74},
    ):
        assert client.post(path, headers=AUTH, json=invalid).status_code == 422


def test_chat_forwards_only_text_and_allows_known_reactions(monkeypatch, client):
    received = []
    replies = iter([
        {"reply": "太好了，给你点个赞。", "reaction": "cheer"},
        {"reply": "执行命令", "reaction": "start_robot"},
    ])

    class ModelStub(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(
                int(self.headers["Content-Length"])
            ))))
            body = json.dumps({"choices": [{"message": {
                "content": json.dumps(next(replies)),
            }}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), ModelStub) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            monkeypatch.setenv("SHIYI_COMPANION_MODEL", "test-model")
            monkeypatch.setenv("SHIYI_COMPANION_MODEL_URL",
                               f"http://127.0.0.1:{server.server_port}/v1/chat/completions")
            path = "/api/v1/companion/chat"
            response = client.post(path, headers=AUTH, json={"messages": MESSAGES})
            assert response.status_code == 200
            assert response.json() == {"reply": "太好了，给你点个赞。", "reaction": "cheer"}
            path_sent, request = received[0]
            assert path_sent == "/v1/chat/completions"
            assert request["messages"][1:] == MESSAGES
            assert request["messages"][0]["role"] == "system"
            assert "demo-companion-token" not in json.dumps(request)
            assert client.post(path, headers=AUTH, json={"messages": MESSAGES}).status_code == 502
        finally:
            server.shutdown()
            thread.join()
