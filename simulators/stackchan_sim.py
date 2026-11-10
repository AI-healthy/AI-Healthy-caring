"""Offline Stack-chan command validator/simulator (no hardware interaction)."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ALLOWED = {"SET_EXPRESSION": {"happy", "neutral", "sleepy"}}


def simulate(command: dict) -> dict:
    if command.get("type") not in ALLOWED:
        raise ValueError("Unsupported command type in simulator")
    if command.get("payload", {}).get("preset") not in ALLOWED[command["type"]]:
        raise ValueError("Unknown expression preset")
    expires = datetime.fromisoformat(command["expires_at"])
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("Expired or timezone-less command")
    return {
        "schema_version": "0.1-draft",
        "event_id": "evt-" + str(uuid4()),
        "device_id": command["device_id"],
        "type": "COMMAND_COMPLETED",
        "command_id": command["command_id"],
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "is_demo": True,
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python simulators/stackchan_sim.py <command.json>")
    command = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(simulate(command), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
