"""LAN-02 tests for the official StackChan MCP bridge."""
import json
from types import SimpleNamespace

import httpx
import pytest

from shiyi_api.stackchan_bridge import (
    BridgeError,
    HttpMcpTransport,
    McpCall,
    OfficialStackChan,
    UsbMcpTransport,
)


class RecordingTransport:
    def __init__(self):
        self.calls = []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        return f"ok:{tool}"

    def list_tools(self):
        return [{"name": "self.face.expression"}]


def command(kind, payload):
    return SimpleNamespace(type=kind, payload=payload)


def test_expression_and_head_mapping():
    transport = RecordingTransport()
    bridge = OfficialStackChan(transport)

    bridge.execute(command("SET_EXPRESSION", {"preset": "happy"}))
    bridge.execute(command("MOVE_HEAD_PRESET", {"preset": "nod"}))
    bridge.execute(command("MOVE_HEAD_PRESET", {"preset": "greet"}))

    assert transport.calls == [
        ("self.face.expression", {"expression": "happy"}),
        ("self.head.nod", {}),
        ("self.head.move", {"yaw": 0, "pitch": 80, "speed": 500}),
    ]


def test_speak_and_guide_include_text():
    transport = RecordingTransport()
    bridge = OfficialStackChan(transport)

    bridge.execute(command("SPEAK_TEXT", {"text": "该吃药啦"}))
    bridge.execute(command("PLAY_GUIDE", {"title": "5 分钟肩颈放松"}))
    bridge.execute(command("SHOW_TIMER", {"label": "肩颈放松"}))

    assert transport.calls[0] == ("self.audio_speaker.play_text", {"text": "该吃药啦"})
    assert transport.calls[1] == ("self.face.expression", {"expression": "thinking"})
    assert transport.calls[2] == (
        "self.audio_speaker.play_text",
        {"text": "5 分钟肩颈放松"},
    )
    assert transport.calls[-1][1] == {"text": "肩颈放松"}


def test_cancel_and_unknown_inputs():
    bridge = OfficialStackChan(RecordingTransport())
    assert [call.tool for call in bridge.plan(command("CANCEL_TASK", {}))] == [
        "self.head.center",
        "self.face.expression",
    ]

    with pytest.raises(BridgeError):
        bridge.plan(command("MOVE_HEAD_PRESET", {"preset": "spin"}))
    with pytest.raises(BridgeError):
        bridge.plan(command("DANCE", {}))
    with pytest.raises(BridgeError):
        bridge.plan(command("SET_EXPRESSION", {"preset": "angry"}))


def test_profile_override():
    transport = RecordingTransport()
    bridge = OfficialStackChan(
        transport, profile={"SET_EXPRESSION": [McpCall("my.face", {"name": "x"})]}
    )
    bridge.execute(command("SET_EXPRESSION", {"preset": "happy"}))
    assert transport.calls == [("my.face", {"name": "x"})]


def _mock_client(handler):
    return httpx.Client(
        base_url="http://stackchan.local:8788",
        transport=httpx.MockTransport(handler),
    )


def test_http_transport_json_rpc_and_tools():
    seen = {}

    def handler(request: httpx.Request):
        if request.url.path == "/tools":
            return httpx.Response(200, json=[{"name": "self.head.nod"}])
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "moved"}]},
            },
        )

    client = _mock_client(handler)
    transport = HttpMcpTransport("http://stackchan.local:8788", token="t0ken", client=client)

    assert transport.call("self.head.nod", {}) == "moved"
    assert seen["body"]["method"] == "tools/call"
    assert seen["body"]["params"] == {"name": "self.head.nod", "arguments": {}}
    assert seen["auth"] == "Bearer t0ken"
    assert transport.list_tools() == [{"name": "self.head.nod"}]
    client.close()


def test_http_transport_error():
    client = _mock_client(
        lambda request: httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "error": {"message": "boom"}}
        )
    )
    transport = HttpMcpTransport("http://stackchan.local:8788", client=client)
    with pytest.raises(BridgeError):
        transport.call("self.head.nod", {})
    client.close()


class FakeSerial:
    def __init__(self, lines):
        self.lines = list(lines)
        self.written = b""

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written = data

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def test_usb_transport_parses_prefixed_result():
    serial = FakeSerial(
        [
            b"log: boot\n",
            b'__MCP_RESULT__{"result":{"content":[{"type":"text","text":"usb-ok"}]}}\n',
        ]
    )
    transport = UsbMcpTransport(serial)
    assert transport.call("self.head.nod", {}) == "usb-ok"
    assert b"self.head.nod" in serial.written
