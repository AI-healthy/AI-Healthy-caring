"""Bridge between ShiYi's device contract and official StackChan MCP firmware.

Two transports are supported:

* local HTTP MCP (community firmware adds ``POST /mcp`` on port 8788)
* USB serial MCP (one JSON line request, ``__MCP_RESULT__`` response)

This module only translates commands; it does not flash or reconfigure the
device. Tool names differ between community patches, so the mapping can be
overridden with a profile dict / JSON file.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

MCP_RESULT_PREFIX = "__MCP_RESULT__"


class BridgeError(RuntimeError):
    """Raised when the device rejects an MCP call or returns invalid data."""


@dataclass(frozen=True)
class McpCall:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class BridgeResult:
    call: McpCall
    result: Any


class McpTransport(Protocol):
    def call(self, tool: str, arguments: dict[str, Any]) -> Any: ...

    def list_tools(self) -> list[dict[str, Any]]: ...


def _result_text(result: Any) -> Any:
    """MCP returns {"content":[{"type":"text","text":...}]}; keep it readable."""
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            texts = [item.get("text") for item in content if item.get("type") == "text"]
            if texts:
                return "\n".join(text for text in texts if text is not None)
    return result


class HttpMcpTransport:
    """Talks to the local MCP bridge: POST /mcp (JSON-RPC 2.0)."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 8.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._next_id = 0
        self._client = client or httpx.Client(
            base_url=self.base_url, timeout=timeout
        )

    def close(self) -> None:
        self._client.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        response = self._client.post("/mcp", json=payload, headers=self._headers)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise BridgeError("Invalid MCP response")
        if body.get("error"):
            raise BridgeError(f"MCP error: {body['error']}")
        return body.get("result")

    def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        return _result_text(
            self._rpc("tools/call", {"name": tool, "arguments": arguments})
        )

    def list_tools(self) -> list[dict[str, Any]]:
        response = self._client.get("/tools", headers=self._headers)
        if response.status_code == 200:
            body = response.json()
            if isinstance(body, list):
                return body
            if isinstance(body, dict) and isinstance(body.get("tools"), list):
                return body["tools"]
        result = self._rpc("tools/list", {"cursor": ""})
        tools = result.get("tools") if isinstance(result, dict) else None
        return tools if isinstance(tools, list) else []


class UsbMcpTransport:
    """USB serial JSON-RPC: write one line, read __MCP_RESULT__ lines.

    ``serial_port`` is any object with ``write``, ``readline`` and
    ``reset_input_buffer`` (e.g. ``serial.Serial``). pyserial is optional and
    intentionally not an API dependency.
    """

    def __init__(self, serial_port: Any, timeout: float = 8.0):
        self._port = serial_port
        self.timeout = timeout
        self._next_id = 0

    def _rpc(self, payload: dict[str, Any]) -> Any:
        self._port.reset_input_buffer()
        self._port.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            raw = self._port.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").rstrip()
            if not line.startswith(MCP_RESULT_PREFIX):
                continue
            body = json.loads(line[len(MCP_RESULT_PREFIX) :])
            if body.get("error"):
                raise BridgeError(f"MCP error: {body['error']}")
            return body.get("result")
        raise BridgeError("USB MCP timeout")

    def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        return _result_text(
            self._rpc({"tool": tool, "arguments": arguments, "id": self._next_id})
        )

    def list_tools(self) -> list[dict[str, Any]]:
        self._next_id += 1
        result = self._rpc(
            {"method": "tools/list", "params": {}, "id": self._next_id}
        )
        tools = result.get("tools") if isinstance(result, dict) else None
        return tools if isinstance(tools, list) else []


DEFAULT_PROFILE: dict[str, list[McpCall]] = {
    "SET_EXPRESSION": [McpCall("self.face.expression", {"expression": "{preset}"})],
    "SPEAK_TEXT": [McpCall("self.audio_speaker.play_text", {"text": "{text}"})],
    "PLAY_GUIDE": [
        McpCall("self.face.expression", {"expression": "thinking"}),
        McpCall("self.audio_speaker.play_text", {"text": "{title}"}),
    ],
    "SHOW_TIMER": [
        McpCall("self.face.expression", {"expression": "thinking"}),
        McpCall("self.audio_speaker.play_text", {"text": "{label}"}),
    ],
    "MOVE_HEAD_PRESET": [],  # selected by preset below
    "CANCEL_TASK": [
        McpCall("self.head.center"),
        McpCall("self.face.expression", {"expression": "idle"}),
    ],
}

FACE_MAP = {"happy": "happy", "neutral": "neutral", "sleepy": "sleepy"}
HEAD_PROFILE: dict[str, McpCall] = {
    "nod": McpCall("self.head.nod"),
    "shake": McpCall("self.head.shake"),
    "tilt": McpCall("self.head.tilt"),
    "look_around": McpCall("self.head.move", {"yaw": 0, "pitch": 45, "speed": 500}),
    "greet": McpCall("self.head.move", {"yaw": 0, "pitch": 80, "speed": 500}),
}


class OfficialStackChan:
    """Maps ShiYi commands to whitelisted MCP tool calls."""

    def __init__(self, transport: McpTransport, profile: dict | None = None):
        self.transport = transport
        self.profile = profile or DEFAULT_PROFILE

    def plan(self, command: Any) -> list[McpCall]:
        kind = command.type
        payload = command.payload

        if kind == "SET_FACE":
            calls = [
                McpCall(
                    "self.face.expression",
                    {"expression": payload.get("expression", "neutral")},
                )
            ]
            overlay = payload.get("overlay")
            if overlay:
                calls.append(McpCall("self.face.overlay", {"name": overlay}))
            return calls

        if kind == "MOVE_HEAD_PRESET":
            preset = payload.get("preset")
            call = HEAD_PROFILE.get(preset)
            if call is None:
                raise BridgeError(f"Unsupported head preset: {preset}")
            return [call]

        calls = self.profile.get(kind)
        if calls is None:
            raise BridgeError(f"Unsupported command type: {kind}")

        face = None
        if kind == "SET_EXPRESSION":
            face = FACE_MAP.get(payload.get("preset", "neutral"))
            if face is None:
                raise BridgeError(f"Unsupported expression: {payload.get('preset')}")

        values = {
            "text": payload.get("text", ""),
            "title": payload.get("title", "guide"),
            "label": payload.get("label", "timer"),
            "preset": face,
        }
        resolved = []
        for call in calls:
            args = {
                key: (value.format(**values) if isinstance(value, str) else value)
                for key, value in call.arguments.items()
            }
            resolved.append(McpCall(call.tool, args))
        return resolved

    def execute(self, command: Any) -> list[BridgeResult]:
        results = []
        for call in self.plan(command):
            results.append(BridgeResult(call, self.transport.call(call.tool, call.arguments)))
        return results

    def show_overlay(self, name: str) -> Any:
        """Extra expressions (heart/shy/sweat/dizzy/...) on community firmware."""
        return self.transport.call("self.face.overlay", {"name": name})
