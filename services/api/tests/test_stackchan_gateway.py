"""LAN-02 tests for the StackChan gateway (no real hardware)."""
from datetime import UTC, datetime

from shiyi_api.device_contract import CommandView
from shiyi_api.stackchan_gateway import StackChanGateway


class FakeResponse:
    status_code = 200

    def __init__(self, body=None):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


class FakeApi:
    def __init__(self, pending):
        self.pending_body = pending
        self.posts = []

    def get(self, url, headers=None):
        return FakeResponse(self.pending_body)

    def post(self, url, json=None, headers=None):
        self.posts.append((url, json))
        return FakeResponse({"accepted": True})


class FakeBridge:
    def __init__(self):
        self.executed = []

    def execute(self, command):
        self.executed.append(command)


def make_command(status="QUEUED"):
    return CommandView(
        schema_version="0.1-draft",
        command_id="cmd-1",
        correlation_id="session-1",
        device_id="sim",
        type="SHOW_TIMER",
        payload={"duration_seconds": 60, "label": "肩颈放松"},
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        is_demo=True,
        status=status,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_gateway_ack_then_complete():
    api = FakeApi(make_command().model_dump(mode="json"))
    bridge = FakeBridge()
    sleeps = []
    gateway = StackChanGateway(
        api, "sim", "token", bridge, speed=0.5, sleep=lambda seconds: sleeps.append(seconds)
    )

    report = gateway.poll_once()

    assert report.status == "COMPLETED"
    assert report.reason == "mcp_executed"
    assert len(bridge.executed) == 1
    assert sleeps == [30.0]
    assert [post[1]["type"] for post in api.posts] == [
        "COMMAND_ACKNOWLEDGED",
        "COMMAND_COMPLETED",
    ]
    assert api.posts[0][1]["reason"] == "accepted"


def test_gateway_no_pending():
    gateway = StackChanGateway(
        FakeApi(None), "sim", "token", FakeBridge(), sleep=lambda _seconds: None
    )
    assert gateway.poll_once() is None


def test_gateway_bridge_error_fails_command():
    class BrokenBridge:
        def execute(self, command):
            from shiyi_api.stackchan_bridge import BridgeError

            raise BridgeError("device offline")

    api = FakeApi(make_command(status="ACKNOWLEDGED").model_dump(mode="json"))
    gateway = StackChanGateway(api, "sim", "token", BrokenBridge(), sleep=lambda _s: None)

    report = gateway.poll_once()

    assert report.status == "FAILED"
    assert report.reason.startswith("mcp_error")
    assert api.posts[-1][1]["type"] == "COMMAND_FAILED"
