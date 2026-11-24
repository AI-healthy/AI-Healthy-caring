"""Runs on a PC/phone on the same LAN as StackChan.

Polls the ShiYi device command queue, translates each command through the
official/community MCP bridge, and reports ACK/terminal events. It is the
counterpart of ``device_runtime.py`` for real hardware.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .device_contract import CommandView, DeviceEvent
from .stackchan_bridge import BridgeError, OfficialStackChan


@dataclass
class GatewayReport:
    command_id: str
    command_type: str
    status: str
    reason: str
    elapsed_seconds: int


class StackChanGateway:
    def __init__(
        self,
        api: Any,
        device_id: str,
        token: str,
        bridge: OfficialStackChan,
        *,
        speed: float = 0.02,
        sleep=time.sleep,
    ):
        self.api = api
        self.device_id = device_id
        self.token = token
        self.bridge = bridge
        self.speed = max(0.0, speed)
        self.sleep = sleep

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _path(self, suffix: str) -> str:
        return f"/api/v1/devices/{quote(self.device_id, safe='')}{suffix}"

    def pending(self) -> CommandView | None:
        response = self.api.get(self._path("/pending"), headers=self._headers)
        response.raise_for_status()
        body = response.json()
        return CommandView.model_validate(body) if body is not None else None

    def _post_event(
        self, command: CommandView, event_type: str, reason: str, elapsed: int
    ) -> None:
        event = DeviceEvent(
            schema_version=command.schema_version,
            event_id=f"{command.command_id}:{event_type}:{reason}",
            device_id=self.device_id,
            type=event_type,
            command_id=command.command_id,
            occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            is_demo=True,
            reason=reason,
            elapsed_seconds=elapsed,
        )
        response = self.api.post(
            self._path("/events"),
            json=event.model_dump(mode="json"),
            headers=self._headers,
        )
        response.raise_for_status()

    @staticmethod
    def _duration(command: CommandView) -> int:
        payload = command.payload
        if command.type in {"PLAY_GUIDE", "SHOW_TIMER"}:
            return min(int(payload.get("duration_seconds", 60)), 900)
        if command.type == "SPEAK_TEXT":
            return max(3, len(payload.get("text", "")) // 6)
        if command.type == "MOVE_HEAD_PRESET":
            return 2
        if command.type in {"SET_EXPRESSION", "SET_FACE"}:
            return 1
        return 0

    def poll_once(self) -> GatewayReport | None:
        command = self.pending()
        if command is None:
            return None

        if command.status == "QUEUED":
            self._post_event(command, "COMMAND_ACKNOWLEDGED", "accepted", 0)
        elif command.status != "ACKNOWLEDGED":
            return None

        try:
            self.bridge.execute(command)
        except BridgeError as error:
            self._post_event(command, "COMMAND_FAILED", "mcp_error", 0)
            return GatewayReport(
                command.command_id, command.type, "FAILED", f"mcp_error: {error}", 0
            )

        duration = self._duration(command)
        wall = duration * self.speed
        if wall > 0:
            self.sleep(wall)
        self._post_event(command, "COMMAND_COMPLETED", "mcp_executed", duration)
        return GatewayReport(
            command.command_id, command.type, "COMPLETED", "mcp_executed", duration
        )

    def run_forever(self, interval: float = 1.0) -> None:
        while True:
            report = self.poll_once()
            if report is None:
                self.sleep(interval)


def build_from_env() -> StackChanGateway:
    from .stackchan_bridge import HttpMcpTransport

    api_url = os.environ.get("SHIYI_API_URL", "http://127.0.0.1:8000")
    device_id = os.environ["SHIYI_SIM_DEVICE_ID"]
    device_token = os.environ["SHIYI_SIM_DEVICE_TOKEN"]
    mcp_url = os.environ.get("SHIYI_STACKCHAN_MCP_URL", "http://stackchan.local:8788")
    mcp_token = os.environ.get("SHIYI_STACKCHAN_MCP_TOKEN")

    api = httpx.Client(base_url=api_url, timeout=10)
    transport = HttpMcpTransport(mcp_url, token=mcp_token)
    return StackChanGateway(api, device_id, device_token, OfficialStackChan(transport))


def main() -> int:
    gateway = build_from_env()
    print(
        json.dumps(
            {
                "device": gateway.device_id,
                "api": str(gateway.api.base_url),
                "mcp": getattr(gateway.bridge.transport, "base_url", "unknown"),
            },
            ensure_ascii=False,
        )
    )
    gateway.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
