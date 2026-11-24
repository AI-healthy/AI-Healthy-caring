"""LAN-02/LAN-03 local Stack-chan device runtime.

The runtime is deliberately transport-thin: it talks to the same local REST
contract as ``simulator.py`` but keeps device-side state, executes whitelisted
commands for a short, sped-up demo, and reports touch confirm/decline.

It never talks to M5Stack hardware. Its job is to prove the protocol, retry and
receipt behaviour end-to-end before a real K151 is available.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from pydantic import ValidationError

from .device_contract import PAYLOAD_MODELS, CommandView, DeviceEvent

WHITELIST = frozenset(PAYLOAD_MODELS)
GUIDE_DURATION_SECONDS = 5 * 60


class RuntimeTransport(Protocol):
    def get(self, url: str, headers: dict | None = None): ...

    def post(self, url: str, json: dict | None = None, headers: dict | None = None): ...


@dataclass
class RuntimeReport:
    command_id: str
    type: str
    status: str
    reason: str | None
    elapsed_seconds: int
    duplicate: bool = False
    transcript: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


def estimate_seconds(command: CommandView) -> int:
    """Wall-clock duration the physical action would take (before demo speeding)."""
    kind = command.type
    payload = command.payload
    if kind == "SET_EXPRESSION":
        return 1
    if kind == "SET_FACE":
        return 1
    if kind == "MOVE_HEAD_PRESET":
        return 2
    if kind == "SPEAK_TEXT":
        return max(3, len(payload.get("text", "")) // 6)
    if kind == "SHOW_TIMER":
        return int(payload.get("duration_seconds", 60))
    if kind == "PLAY_GUIDE":
        return min(int(payload.get("duration_seconds", GUIDE_DURATION_SECONDS)), 900)
    if kind == "CANCEL_TASK":
        return 0
    raise ValueError("Unsupported command type")


class DeviceRuntime:
    """Poll -> ACK -> execute -> terminal event, with bounded retry and spool."""

    def __init__(
        self,
        client: RuntimeTransport,
        device_id: str,
        token: str,
        *,
        speed: float = 0.02,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 2,
        spool_path: str | Path | None = None,
        base_url: str = "",
    ):
        self.client = client
        self.device_id = device_id
        self.token = token
        self.speed = max(0.0, speed)
        self.sleep = sleep
        self.max_retries = max(0, max_retries)
        self.spool_path = Path(spool_path) if spool_path else None
        self.base_url = base_url.rstrip("/")
        self.transcript: list[str] = []

    # ------------------------------------------------------------------ HTTP
    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def _path(self, suffix: str) -> str:
        return f"/api/v1/devices/{quote(self.device_id, safe='')}{suffix}"

    def pending(self) -> CommandView | None:
        response = self.client.get(self._path("/pending"), headers=self._headers)
        response.raise_for_status()
        body = response.json()
        if body is None:
            return None
        return CommandView.model_validate(body)

    def _post_event(self, event: DeviceEvent) -> dict | None:
        payload = event.model_dump(mode="json")
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.post(
                    self._path("/events"), json=payload, headers=self._headers
                )
            except Exception as error:  # noqa: BLE001 - transport failures are retried
                last_error = error
            else:
                if response.status_code < 400:
                    return response.json()
                if response.status_code < 500:
                    # 4xx means the contract itself is wrong; retrying will not help.
                    raise RuntimeError(
                        f"Event rejected ({response.status_code}): {response.text[:120]}"
                    )
                last_error = RuntimeError(f"Server error {response.status_code}")
            if attempt < self.max_retries:
                self.sleep(0.2 * (2**attempt))
        self._spool(event)
        self.transcript.append(f"spooled {event.type} {event.event_id} ({last_error})")
        return None

    # --------------------------------------------------------------- spooling
    def _spool(self, event: DeviceEvent) -> None:
        if self.spool_path is None:
            return
        entries = self._read_spool()
        entries.append(event.model_dump(mode="json"))
        self.spool_path.parent.mkdir(parents=True, exist_ok=True)
        self.spool_path.write_text(
            json.dumps(entries, ensure_ascii=False), encoding="utf-8"
        )

    def _read_spool(self) -> list[dict]:
        if self.spool_path is None or not self.spool_path.exists():
            return []
        try:
            data = json.loads(self.spool_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def flush_spool(self) -> int:
        """Replay queued events; return how many were accepted."""
        if self.spool_path is None:
            return 0
        entries = self._read_spool()
        if not entries:
            return 0
        remaining: list[dict] = []
        flushed = 0
        for entry in entries:
            try:
                DeviceEvent.model_validate(entry)
            except ValidationError:
                continue
            try:
                response = self.client.post(
                    self._path("/events"), json=entry, headers=self._headers
                )
            except Exception:  # noqa: BLE001 - keep the event for the next replay
                remaining.append(entry)
                continue
            if response.status_code < 400:
                flushed += 1
            else:
                remaining.append(entry)
        if remaining:
            self.spool_path.write_text(
                json.dumps(remaining, ensure_ascii=False), encoding="utf-8"
            )
        else:
            self.spool_path.unlink(missing_ok=True)
        return flushed

    # -------------------------------------------------------------- execution
    def _validate(self, command: CommandView) -> str | None:
        if command.type not in WHITELIST:
            return "unsupported_command"
        try:
            PAYLOAD_MODELS[command.type].model_validate(command.payload)
        except ValidationError:
            return "invalid_payload"
        return None

    def _event(
        self, command: CommandView, event_type: str, reason: str | None, elapsed: int | None
    ) -> DeviceEvent:
        suffix = event_type.rsplit("_", 1)[-1].lower()
        event_id = f"{command.command_id}:{suffix}"
        if reason:
            event_id += f":{reason}"
        return DeviceEvent(
            schema_version=command.schema_version,
            device_id=self.device_id,
            command_id=command.command_id,
            event_id=event_id,
            type=event_type,
            occurred_at=_now(),
            is_demo=True,
            reason=reason,
            elapsed_seconds=elapsed,
        )

    def run_once(self, touch: str | None = None) -> RuntimeReport | None:
        """Process one pending command.

        ``touch`` is ``"confirm"`` (user ends/starts early), ``"decline"`` or
        ``None`` (let the timer finish). Durations are multiplied by ``speed``;
        0.02 turns the 5-minute stretch into ~6 seconds.
        """
        self.transcript = []
        self.flush_spool()
        command = self.pending()
        if command is None:
            return None

        self.transcript.append(f"recv {command.type} {command.command_id}")
        if command.status == "QUEUED":
            receipt = self._post_event(
                self._event(command, "COMMAND_ACKNOWLEDGED", "accepted", 0)
            )
            self.transcript.append("ack " + ("ok" if receipt else "spooled"))
            if receipt is None:
                # Do not execute a command the server has not acknowledged yet;
                # the ACK stays spooled and will be replayed on the next poll.
                return RuntimeReport(
                    command_id=command.command_id,
                    type=command.type,
                    status="UNSENT",
                    reason="ack_not_delivered",
                    elapsed_seconds=0,
                    transcript=self.transcript,
                )
        elif command.status != "ACKNOWLEDGED":
            return None

        problem = self._validate(command)
        if problem is not None:
            receipt = self._post_event(
                self._event(command, "COMMAND_FAILED", problem, 0)
            )
            return RuntimeReport(
                command_id=command.command_id,
                type=command.type,
                status=receipt["command"]["status"] if receipt else "UNSENT",
                reason=problem,
                elapsed_seconds=0,
                duplicate=bool(receipt and receipt.get("duplicate")),
                transcript=self.transcript,
            )

        duration = estimate_seconds(command)
        action_seconds = duration * self.speed
        early = touch in {"confirm", "decline"}
        wall_seconds = action_seconds * 0.3 if early else action_seconds
        if wall_seconds > 0:
            self.sleep(wall_seconds)
        elapsed = max(0, int(duration * 0.3)) if early else duration

        if touch == "decline":
            event_type, reason = "COMMAND_FAILED", "user_declined"
            self.transcript.append("touch decline -> stop")
        elif touch == "confirm":
            event_type, reason = "COMMAND_COMPLETED", "touch_confirmed"
            self.transcript.append("touch confirm -> finish")
        else:
            event_type, reason = "COMMAND_COMPLETED", "timer_elapsed"
            self.transcript.append(f"timer {duration}s elapsed")

        receipt = self._post_event(self._event(command, event_type, reason, elapsed))
        status = receipt["command"]["status"] if receipt else "UNSENT"
        self.transcript.append(f"sent {event_type} ({reason}) -> {status}")
        return RuntimeReport(
            command_id=command.command_id,
            type=command.type,
            status=status,
            reason=reason,
            elapsed_seconds=elapsed,
            duplicate=bool(receipt and receipt.get("duplicate")),
            transcript=self.transcript,
        )

    def run_until_empty(self, touch: str | None = None, limit: int = 10) -> list[RuntimeReport]:
        reports = []
        for _ in range(limit):
            report = self.run_once(touch=touch)
            if report is None:
                break
            reports.append(report)
        return reports


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    import httpx

    parser = argparse.ArgumentParser(description="Local Stack-chan LAN-02 runtime demo")
    parser.add_argument("--once", action="store_true", help="process at most one command")
    parser.add_argument("--drain", action="store_true", help="process pending commands until empty")
    parser.add_argument("--touch", choices=["confirm", "decline"], default=None)
    parser.add_argument("--speed", type=float, default=0.02,
                        help="wall-clock multiplier for action durations (default 0.02)")
    parser.add_argument("--spool", default=os.environ.get("SHIYI_SIM_SPOOL"),
                        help="offline terminal-event spool file")
    args = parser.parse_args(argv)

    api = os.environ.get("SHIYI_API_URL", "http://127.0.0.1:8000")
    device_id = os.environ["SHIYI_SIM_DEVICE_ID"]
    token = os.environ["SHIYI_SIM_DEVICE_TOKEN"]

    with httpx.Client(base_url=api, timeout=10) as client:
        runtime = DeviceRuntime(
            client,
            device_id,
            token,
            speed=args.speed,
            spool_path=args.spool,
        )
        if args.drain:
            reports = runtime.run_until_empty(touch=args.touch)
        else:
            report = runtime.run_once(touch=args.touch)
            reports = [report] if report else []

    if not reports:
        print("No pending command")
        return 0
    for report in reports:
        print(
            json.dumps(
                {
                    "command_id": report.command_id,
                    "type": report.type,
                    "status": report.status,
                    "reason": report.reason,
                    "elapsed_seconds": report.elapsed_seconds,
                    "duplicate": report.duplicate,
                    "transcript": report.transcript,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
