#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../services/api"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install -e '.[dev]'
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
