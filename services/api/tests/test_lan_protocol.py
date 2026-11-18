"""LAN-02/LAN-03 protocol and runtime tests (synthetic data only)."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from shiyi_api import storage
from shiyi_api.device_runtime import DeviceRuntime
from shiyi_api.main import app

USER = {"Authorization": "Bearer alpha-token-for-tests"}
TOKEN = "simulator-token-for-tests"
DEVICE = {"Authorization": f"Bearer {TOKEN}"}
ROOT = "/api/v1/devices"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIYI_DB_PATH", str(tmp_path / "devices.sqlite3"))
    monkeypatch.setenv(
        "SHIYI_DEV_USERS", '{"alice":"alpha-token-for-tests","bob":"bravo-token-for-tests"}'
    )
    monkeypatch.setenv(
        "SHIYI_DEV_DEVICES",
        '{"sim":{"user_id":"alice","token":"simulator-token-for-tests"}}',
    )
    yield TestClient(app)
    storage.store_for.cache_clear()


def new_session(client):
    response = client.post(
        "/api/v1/activities/sessions",
        headers=USER,
        json={"activity_id": "stretch", "client_request_id": "lan-session"},
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    assert (
        client.post(
            f"/api/v1/activities/sessions/{session_id}/start", headers=USER
        ).status_code
        == 200
    )
    return session_id


def enqueue(client, session_id, command_type, payload, key):
    response = client.post(
        ROOT + "/commands",
        headers=USER,
        json={
            "session_id": session_id,
            "device_id": "sim",
            "client_request_id": key,
            "command_type": command_type,
            "payload": payload,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def runtime(client, tmp_path):
    return DeviceRuntime(
        client,
        "sim",
        TOKEN,
        speed=0,
        sleep=lambda _seconds: None,
        max_retries=0,
        spool_path=tmp_path / "spool.json",
    )


CASES = [
    ("SET_EXPRESSION", {"preset": "happy"}),
    ("SPEAK_TEXT", {"text": "慢慢来，先放松肩膀。", "emotion": "neutral"}),
    (
        "PLAY_GUIDE",
        {
            "guide_id": "stretch-5min",
            "title": "5 分钟肩颈放松",
            "duration_seconds": 300,
            "steps": ["坐直", "抬肩", "放松"],
        },
    ),
    ("SHOW_TIMER", {"duration_seconds": 300, "label": "肩颈放松"}),
    ("MOVE_HEAD_PRESET", {"preset": "nod"}),
    ("CANCEL_TASK", {"reason": "user_cancel"}),
]


@pytest.mark.parametrize(("command_type", "payload"), CASES)
def test_whitelisted_command_types_complete(client, tmp_path, command_type, payload):
    session_id = new_session(client)
    command = enqueue(client, session_id, command_type, payload, f"cmd-{command_type}")

    assert command["type"] == command_type
    assert command["payload"] == payload
    assert command["status"] == "QUEUED"

    report = runtime(client, tmp_path).run_once()
    assert report is not None
    assert report.command_id == command["command_id"]
    assert report.status == "COMPLETED"
    assert report.reason == "timer_elapsed"

    status = client.get(
        f"{ROOT}/commands/{command['command_id']}", headers=USER
    ).json()
    assert status["status"] == "COMPLETED"


def test_legacy_preset_field_still_works(client):
    session_id = new_session(client)
    response = client.post(
        ROOT + "/commands",
        headers=USER,
        json={
            "session_id": session_id,
            "device_id": "sim",
            "client_request_id": "legacy",
            "preset": "sleepy",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "SET_EXPRESSION"
    assert body["payload"] == {"preset": "sleepy"}


@pytest.mark.parametrize(
    "body",
    [
        {"command_type": "PLAY_GUIDE", "payload": None},
        {"command_type": "PLAY_GUIDE", "payload": {"guide_id": "x", "title": "t",
                                                   "duration_seconds": 5}},
        {"command_type": "SPEAK_TEXT", "payload": {"text": ""}},
        {"command_type": "SPEAK_TEXT", "payload": {"text": "x" * 201}},
        {"command_type": "SPEAK_TEXT", "preset": "happy", "payload": {"text": "hi"}},
        {"command_type": "MOVE_HEAD_PRESET", "payload": {"preset": "spin"}},
        {"command_type": "SET_EXPRESSION", "payload": {"preset": "happy", "extra": 1}},
        {"command_type": "NOT_A_COMMAND", "payload": {}},
    ],
)
def test_invalid_payloads_are_rejected(client, body):
    session_id = new_session(client)
    response = client.post(
        ROOT + "/commands",
        headers=USER,
        json={
            "session_id": session_id,
            "device_id": "sim",
            "client_request_id": "bad",
            **body,
        },
    )
    assert response.status_code == 422


def test_client_request_id_conflict_on_changed_payload(client):
    session_id = new_session(client)
    enqueue(client, session_id, "SHOW_TIMER", {"duration_seconds": 60, "label": "a"}, "same")
    response = client.post(
        ROOT + "/commands",
        headers=USER,
        json={
            "session_id": session_id,
            "device_id": "sim",
            "client_request_id": "same",
            "command_type": "SHOW_TIMER",
            "payload": {"duration_seconds": 90, "label": "a"},
        },
    )
    assert response.status_code == 409


def test_touch_decline_reports_failed(client, tmp_path):
    session_id = new_session(client)
    command = enqueue(
        client,
        session_id,
        "PLAY_GUIDE",
        {
            "guide_id": "stretch-5min",
            "title": "5 分钟肩颈放松",
            "duration_seconds": 300,
        },
        "decline",
    )

    report = runtime(client, tmp_path).run_once(touch="decline")

    assert report.status == "FAILED"
    assert report.reason == "user_declined"
    assert report.elapsed_seconds == 90
    assert (
        client.get(f"{ROOT}/commands/{command['command_id']}", headers=USER).json()[
            "status"
        ]
        == "FAILED"
    )


def test_touch_confirm_completes_early(client, tmp_path):
    session_id = new_session(client)
    command = enqueue(
        client,
        session_id,
        "PLAY_GUIDE",
        {"guide_id": "stretch-5min", "title": "5 分钟肩颈放松", "duration_seconds": 300},
        "confirm",
    )

    report = runtime(client, tmp_path).run_once(touch="confirm")

    assert report.status == "COMPLETED"
    assert report.reason == "touch_confirmed"
    assert (
        client.get(f"{ROOT}/commands/{command['command_id']}", headers=USER).json()[
            "status"
        ]
        == "COMPLETED"
    )


class FlakyTransport:
    """Fails the first terminal event to exercise spool/replay."""

    def __init__(self, client):
        self.client = client
        self.failed = False

    def get(self, url, headers=None):
        return self.client.get(url, headers=headers)

    def post(self, url, json=None, headers=None):
        if (
            not self.failed
            and json is not None
            and json.get("type") in {"COMMAND_COMPLETED", "COMMAND_FAILED"}
        ):
            self.failed = True
            raise RuntimeError("simulated network drop")
        return self.client.post(url, json=json, headers=headers)


def test_terminal_event_spools_and_replays(client, tmp_path):
    session_id = new_session(client)
    command = enqueue(
        client,
        session_id,
        "SHOW_TIMER",
        {"duration_seconds": 60, "label": "demo"},
        "spool",
    )
    transport = FlakyTransport(client)
    device = DeviceRuntime(
        transport,
        "sim",
        TOKEN,
        speed=0,
        sleep=lambda _seconds: None,
        max_retries=0,
        spool_path=tmp_path / "spool.json",
    )

    report = device.run_once()
    assert report.status == "UNSENT"
    assert (tmp_path / "spool.json").exists()

    assert device.flush_spool() == 1
    assert not (tmp_path / "spool.json").exists()
    assert (
        client.get(f"{ROOT}/commands/{command['command_id']}", headers=USER).json()[
            "status"
        ]
        == "COMPLETED"
    )


def test_acknowledged_command_resumes_after_restart(client, tmp_path):
    session_id = new_session(client)
    command = enqueue(
        client, session_id, "MOVE_HEAD_PRESET", {"preset": "greet"}, "resume"
    )
    now = storage.now_utc()
    ack = {
        "schema_version": "0.1-draft",
        "event_id": "restart-ack",
        "device_id": "sim",
        "type": "COMMAND_ACKNOWLEDGED",
        "command_id": command["command_id"],
        "occurred_at": now.isoformat(),
        "is_demo": True,
    }
    assert client.post(ROOT + "/sim/events", headers=DEVICE, json=ack).status_code == 200

    report = runtime(client, tmp_path).run_once()

    assert report.status == "COMPLETED"
    assert report.command_id == command["command_id"]


def test_expired_command_not_executed(client, tmp_path, monkeypatch):
    session_id = new_session(client)
    enqueue(
        client, session_id, "SPEAK_TEXT", {"text": "来看一下。"}, "expired"
    )
    now = storage.now_utc()
    monkeypatch.setattr(storage, "now_utc", lambda: now + timedelta(seconds=61))

    assert runtime(client, tmp_path).run_once() is None
