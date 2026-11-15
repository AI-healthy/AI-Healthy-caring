import os
import socket
import subprocess
import sys
import time

import httpx
from fastapi.testclient import TestClient

from shiyi_api.main import app


def test_workbench_disabled_and_local_only(monkeypatch):
    client = TestClient(app, base_url="http://127.0.0.1",
                        client=("127.0.0.1", 12345))
    monkeypatch.delenv("SHIYI_DEBUG_WORKBENCH", raising=False)
    assert client.get("/workbench").status_code == 404
    monkeypatch.setenv("SHIYI_DEBUG_WORKBENCH", "1")
    remote = TestClient(app, base_url="http://127.0.0.1",
                        client=("192.0.2.1", 12345))
    assert remote.get("/workbench").status_code == 404
    assert client.get("/workbench", headers={"Host":"example.invalid"}).status_code == 404
    html = client.get("/workbench")
    assert html.status_code == 200
    assert "Harness Workbench" in html.text
    assert html.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in html.headers["content-security-policy"]
    script = client.get("/workbench/app.js")
    assert script.status_code == 200
    assert "localStorage" not in script.text and "sessionStorage" not in script.text
    assert "access_token" in script.text


def test_local_runtime_uses_disposable_database(tmp_path):
    sentinel = tmp_path / "do-not-use.sqlite3"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "shiyi_api.local_runtime", "--port", str(port)],
        env={**os.environ, "SHIYI_DB_PATH": str(sentinel), "SHIYI_RANKER": "local_llm"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1,
                          trust_env=False) as client:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                assert process.poll() is None
                try:
                    response = client.get("/workbench")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise AssertionError("Workbench startup failed")
            credentials = {"username":"test_workbench", "password":"synthetic-password-123"}
            assert client.post("/api/v1/users/register", json=credentials).status_code == 201
            login = client.post("/api/v1/users/login", json=credentials)
            assert login.status_code == 200
            auth = {"Authorization":"Bearer " + login.json()["access_token"]}
            plan = client.post("/api/v1/harness/runs", headers=auth,
                               json={"client_request_id":"workbench-run"})
            assert plan.status_code == 200
            assert plan.json()["algorithm"] == "rules_v1"
            assert not sentinel.exists()
    finally:
        process.terminate()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    assert process.returncode == 0
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
