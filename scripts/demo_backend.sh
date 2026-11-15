#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../services/api"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install -e '.[dev,mcp]'
TMP="$(mktemp -d)"
PID=""
cleanup() {
  if [[ -n "$PID" ]]; then kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; fi
  rm -rf -- "$TMP"
}
trap cleanup EXIT
export SHIYI_DB_PATH="$TMP/shiyi.sqlite3"
export SHIYI_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SHIYI_SIM_DEVICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SHIYI_SIM_DEVICE_ID=sim
export SHIYI_DEV_USERS="$(python -c 'import json,os; print(json.dumps({"demo":os.environ["SHIYI_TOKEN"]}))')"
export SHIYI_DEV_DEVICES="$(python -c 'import json,os; print(json.dumps({"sim":{"user_id":"demo","token":os.environ["SHIYI_SIM_DEVICE_TOKEN"]}}))')"
python - <<'PY'
import socket
with socket.socket() as s:
    s.bind(("127.0.0.1", 8000))
PY
uvicorn shiyi_api.main:app --host 127.0.0.1 --port 8000 >"$TMP/server.log" 2>&1 &
PID=$!
python - <<'PY'
import os
import time
import httpx
from shiyi_api.simulator import run_once

with httpx.Client(base_url="http://127.0.0.1:8000", timeout=5) as c:
    for _ in range(50):
        try:
            if c.get("/api/v1/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(.2)
    else:
        raise SystemExit("API startup failed")
    headers = {"Authorization": "Bearer " + os.environ["SHIYI_TOKEN"]}
    def post(path, data=None):
        res = c.post(path, json=data, headers=headers)
        res.raise_for_status()
        return res.json()
    rec = post("/api/v1/recommendations", {"context":{"available_minutes":5,"source":"demo","is_demo":True}})
    aid = rec["options"][0]["activity_id"]
    r = post("/api/v1/activities/sessions", {"activity_id":aid,"client_request_id":"demo"})
    sid = r["session_id"]
    path = "/api/v1/activities/sessions/" + sid
    post(path + "/start")
    cmd = post("/api/v1/devices/commands", {"session_id":sid,"device_id":"sim","client_request_id":"demo-command"})
    receipt = run_once(c, "sim", os.environ["SHIYI_SIM_DEVICE_TOKEN"])
    assert receipt["command"]["status"] == "COMPLETED"
    assert receipt["command"]["command_id"] == cmd["command_id"]
    post(path + "/complete")
    feedback = post("/api/v1/activities/feedback", {"session_id":sid,"activity_id":aid,"completed":True,"client_event_id":"demo-feedback"})
    assert feedback["accepted"]
    print("SIMULATED E2E PASS: recommendation -> start -> device ACK/completed -> user completion -> feedback")
PY

python - <<'PY'
import asyncio
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def verify():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "shiyi_api.mcp_server"],
        env={"SHIYI_API_URL":"http://127.0.0.1:8000"},
    )
    async with asyncio.timeout(30):
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {
                    "get_shiyi_season_card", "recommend_shiyi_activity"
                }
                for name, args in (
                    ("get_shiyi_season_card", {}),
                    ("recommend_shiyi_activity", {"available_minutes":5}),
                ):
                    result = await session.call_tool(name, arguments=args)
                    assert not result.isError, result
                    data = result.structuredContent
                    if data is None:
                        texts = [block.text for block in result.content if block.type == "text"]
                        assert len(texts) == 1, result
                        data = json.loads(texts[0])
                    data = data.get("result", data)
                    assert data.get("ok") is True and data.get("is_demo") is True, data
                    if name == "get_shiyi_season_card":
                        assert data["calendar_status"] == "sample_only"
                    else:
                        assert data["options"]
                print("LOCAL MCP STDIO PASS: tool discovery + 2 live API tool calls")

asyncio.run(verify())
PY

python - <<'PY'
import secrets
from datetime import UTC, datetime, timedelta
import httpx
from shiyi_api.simulator import run_once

with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as c:
    def request(method, path, data=None, auth=None, status=200):
        res = c.request(method, path, json=data, headers=auth)
        assert res.status_code == status, f"{method} {path}: {res.status_code}"
        return res.json() if status != 204 else None

    users = "/api/v1/users"
    health = "/api/v1/health"
    credentials = {"username":"synthetic_user","password":secrets.token_urlsafe(24)}
    request("POST", users + "/register", credentials, status=201)
    login = request("POST", users + "/login", credentials)
    auth = {"Authorization":"Bearer " + login["access_token"]}
    now = datetime.now(UTC)
    sample = {"client_sample_id":"demo-steps","source":"health_connect","metric":"steps",
              "value":1200,"interval_start":(now-timedelta(hours=1)).isoformat(),
              "observed_at":now.isoformat(),"is_demo":True}
    payload = {"observations":[sample]}
    request("POST", health + "/observations", payload, auth, 403)
    consent = {"granted":True,"policy_version":"local-demo-v1"}
    cp = health + "/consents/health_connect/steps"
    request("PUT", cp, consent, auth)
    receipt = request("POST", health + "/observations", payload, auth)
    assert not receipt["items"][0]["duplicate"]
    assert request("POST", health + "/observations", payload, auth)["items"][0]["duplicate"]
    page = request("GET", health + "/observations", auth=auth)
    assert page["items"][0]["is_demo"] and page["items"][0]["value"] == 1200
    request("PUT", cp, {**consent,"granted":False}, auth)
    request("POST", health + "/observations", payload, auth, 403)
    bind = request("POST", users + "/me/simulated-devices", {"name":"Demo robot"}, auth, 201)
    did = bind["device"]["device_id"]
    activity = request("POST", "/api/v1/activities/sessions", {"activity_id":"stretch"}, auth)
    sid = activity["session_id"]
    path = "/api/v1/activities/sessions/" + sid
    request("POST", path + "/start", auth=auth)
    request("POST", "/api/v1/devices/commands",
            {"session_id":sid,"device_id":did,"client_request_id":"registered-demo"}, auth)
    assert run_once(c, did, bind["device_token"])["command"]["status"] == "COMPLETED"
    request("POST", path + "/complete", auth=auth)
    request("POST", "/api/v1/activities/feedback",
            {"session_id":sid,"activity_id":"stretch","completed":True,
             "client_event_id":"registered-feedback"}, auth)
    request("DELETE", users + "/me/simulated-devices/" + did, auth=auth, status=204)
    request("DELETE", health + "/observations/" + receipt["items"][0]["observation_id"],
            auth=auth, status=204)
    request("POST", users + "/logout", auth=auth, status=204)
    request("GET", users + "/me", auth=auth, status=401)
    print("REGISTERED USER E2E PASS: login, consent, synthetic observations, robot simulation, feedback, revoke/logout")
PY
