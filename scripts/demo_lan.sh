#!/usr/bin/env bash
# LAN-03 demo: 5-minute stretch, sped up, touch confirm/decline, receipts.
set -euo pipefail
cd "$(dirname "$0")/../services/api"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install -q -e '.[dev]'

TMP="$(mktemp -d)"
PID=""
PORT="${SHIYI_LAN_PORT:-8011}"
cleanup() {
  if [[ -n "$PID" ]]; then kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; fi
  rm -rf -- "$TMP"
}
trap cleanup EXIT

export SHIYI_DB_PATH="$TMP/lan.sqlite3"
export SHIYI_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SHIYI_SIM_DEVICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SHIYI_SIM_DEVICE_ID=sim
export SHIYI_API_URL="http://127.0.0.1:$PORT"
export SHIYI_DEV_USERS="$(python -c 'import json,os; print(json.dumps({"demo":os.environ["SHIYI_TOKEN"]}))')"
export SHIYI_DEV_DEVICES="$(python -c 'import json,os; print(json.dumps({"sim":{"user_id":"demo","token":os.environ["SHIYI_SIM_DEVICE_TOKEN"]}}))')"

uvicorn shiyi_api.main:app --host 127.0.0.1 --port "$PORT" >"$TMP/server.log" 2>&1 &
PID=$!

python - <<'PY'
import os
import subprocess
import sys
import time

import httpx

base = os.environ["SHIYI_API_URL"]
with httpx.Client(base_url=base, timeout=10) as client:
    for _ in range(50):
        try:
            if client.get("/api/v1/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    else:
        raise SystemExit("API startup failed")

    user = {"Authorization": "Bearer " + os.environ["SHIYI_TOKEN"]}
    session = client.post(
        "/api/v1/activities/sessions",
        headers=user,
        json={"activity_id": "stretch", "client_request_id": "lan-stretch"},
    )
    session.raise_for_status()
    sid = session.json()["session_id"]
    client.post(f"/api/v1/activities/sessions/{sid}/start", headers=user).raise_for_status()

    guide = client.post(
        "/api/v1/devices/commands",
        headers=user,
        json={
            "session_id": sid,
            "device_id": "sim",
            "client_request_id": "lan-guide",
            "command_type": "PLAY_GUIDE",
            "payload": {
                "guide_id": "stretch-5min",
                "title": "5 分钟肩颈放松",
                "duration_seconds": 300,
                "steps": ["坐直", "抬肩", "缓慢转头", "放松"],
            },
        },
    )
    guide.raise_for_status()
    command_id = guide.json()["command_id"]

    print(">> 设备拉取 PLAY_GUIDE，并在 30% 处模拟触摸确认")
    subprocess.run(
        [sys.executable, "-m", "shiyi_api.device_runtime", "--once",
         "--touch", "confirm", "--speed", "0"],
        check=True,
    )
    status = client.get(f"/api/v1/devices/commands/{command_id}", headers=user)
    status.raise_for_status()
    assert status.json()["status"] == "COMPLETED", status.text
    assert status.json()["type"] == "PLAY_GUIDE"

    # 机器人的完成回执不等于用户完成活动。
    running = client.get(f"/api/v1/activities/sessions/{sid}", headers=user)
    assert running.json()["status"] == "RUNNING", running.text
    print(">> 机器人回执 COMPLETED；活动会话仍为 RUNNING（等待用户确认）")

    for key, command_type, payload in (
        ("lan-speak", "SPEAK_TEXT", {"text": "慢慢来，先放松肩膀。", "emotion": "neutral"}),
        ("lan-head", "MOVE_HEAD_PRESET", {"preset": "nod"}),
        ("lan-timer", "SHOW_TIMER", {"duration_seconds": 300, "label": "肩颈放松"}),
    ):
        response = client.post(
            "/api/v1/devices/commands",
            headers=user,
            json={"session_id": sid, "device_id": "sim",
                  "client_request_id": key, "command_type": command_type,
                  "payload": payload},
        )
        response.raise_for_status()

    print(">> 设备顺序执行 SPEAK_TEXT / MOVE_HEAD_PRESET / SHOW_TIMER")
    subprocess.run(
        [sys.executable, "-m", "shiyi_api.device_runtime", "--drain", "--speed", "0"],
        check=True,
    )
    print(">> 用户确认活动完成并提交反馈")
    client.post(f"/api/v1/activities/sessions/{sid}/complete", headers=user).raise_for_status()
    client.post(
        "/api/v1/activities/feedback",
        headers=user,
        json={"session_id": sid, "activity_id": "stretch", "completed": True,
              "client_event_id": "lan-feedback"},
    ).raise_for_status()
    print("LAN-03 DEMO PASS: guide/timer/actions -> touch receipt -> user completion")
PY
