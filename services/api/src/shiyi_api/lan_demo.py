"""In-process LAN-03 demo: stretch guide -> touch confirm -> user completion.

Runs the FastAPI app through TestClient, so it needs no uvicorn, port or network.
``bash scripts/demo_lan.sh`` is the HTTP variant; this module is the CI-friendly one.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

USER_TOKEN = "lan-demo-user-token"
DEVICE_TOKEN = "lan-demo-device-token"


def main() -> int:
    workdir = Path(os.environ.get("SHIYI_LAN_DEMO_DIR") or tempfile.gettempdir())
    workdir = workdir / f"shiyi-lan-demo-{uuid4().hex}"
    workdir.mkdir(parents=True, exist_ok=True)

    os.environ["SHIYI_DB_PATH"] = str(workdir / "lan.sqlite3")
    os.environ["SHIYI_DEV_USERS"] = json.dumps({"lan-demo": USER_TOKEN})
    os.environ["SHIYI_DEV_DEVICES"] = json.dumps(
        {"sim": {"user_id": "lan-demo", "token": DEVICE_TOKEN}}
    )

    try:
        from fastapi.testclient import TestClient

        from . import storage
        from .device_runtime import DeviceRuntime
        from .main import app

        storage.store_for.cache_clear()
        client = TestClient(app)
        user = {"Authorization": f"Bearer {USER_TOKEN}"}

        session = client.post(
            "/api/v1/activities/sessions",
            headers=user,
            json={"activity_id": "stretch", "client_request_id": "lan-demo-session"},
        )
        session.raise_for_status()
        session_id = session.json()["session_id"]
        client.post(f"/api/v1/activities/sessions/{session_id}/start", headers=user).raise_for_status()

        guide = client.post(
            "/api/v1/devices/commands",
            headers=user,
            json={
                "session_id": session_id,
                "device_id": "sim",
                "client_request_id": "lan-demo-guide",
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

        runtime = DeviceRuntime(
            client, "sim", DEVICE_TOKEN, speed=0, sleep=lambda _seconds: None
        )
        report = runtime.run_once(touch="confirm")
        assert report is not None and report.status == "COMPLETED", report
        assert report.reason == "touch_confirmed"
        print(f"[LAN-03] guide {command_id} -> {report.status} ({report.reason})")
        for line in report.transcript:
            print(f"         {line}")

        status = client.get(f"/api/v1/devices/commands/{command_id}", headers=user)
        status.raise_for_status()
        assert status.json()["status"] == "COMPLETED"
        running = client.get(f"/api/v1/activities/sessions/{session_id}", headers=user)
        assert running.json()["status"] == "RUNNING"
        print("[LAN-03] robot receipt COMPLETED; activity is still RUNNING until user confirms")

        for key, command_type, payload in (
            ("lan-demo-speak", "SPEAK_TEXT", {"text": "慢慢来，先放松肩膀。"}),
            ("lan-demo-head", "MOVE_HEAD_PRESET", {"preset": "nod"}),
            ("lan-demo-timer", "SHOW_TIMER", {"duration_seconds": 300, "label": "肩颈放松"}),
        ):
            response = client.post(
                "/api/v1/devices/commands",
                headers=user,
                json={
                    "session_id": session_id,
                    "device_id": "sim",
                    "client_request_id": key,
                    "command_type": command_type,
                    "payload": payload,
                },
            )
            response.raise_for_status()

        reports = runtime.run_until_empty()
        assert [r.status for r in reports] == ["COMPLETED"] * 3, reports
        print("[LAN-03] SPEAK_TEXT / MOVE_HEAD_PRESET / SHOW_TIMER all COMPLETED")

        print("LAN-03 DEMO PASS: guide + actions + touch receipt + user completion boundary")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
