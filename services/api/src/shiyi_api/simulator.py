"""One-shot HTTP simulator. No physical actions or real device data."""
import os
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from .device_contract import DeviceCommand, DeviceEvent


def run_once(client, device_id: str, token: str, fail: bool = False):
    headers = {"Authorization": f"Bearer {token}"}
    path = f"/api/v1/devices/{quote(device_id, safe='')}"
    response = client.get(path + "/pending", headers=headers)
    response.raise_for_status()
    if response.json() is None:
        return None
    command = DeviceCommand.model_validate(response.json())
    if command.device_id != device_id or command.expires_at <= datetime.now(UTC):
        raise ValueError("Wrong device or expired simulator command")
    # Deterministic event ID AND timestamp make retries identical across simulator restarts.
    # We use a fixed timestamp from the command for synthetic events only.
    for event_type in (
        "COMMAND_ACKNOWLEDGED", "COMMAND_FAILED" if fail else "COMMAND_COMPLETED"
    ):
        event = DeviceEvent(
            schema_version=command.schema_version, device_id=device_id,
            command_id=command.command_id, event_id=f"{command.command_id}:{event_type}",
            type=event_type, occurred_at=command.expires_at, is_demo=True,
        )
        response = client.post(path + "/events", headers=headers, json=event.model_dump(mode="json"))
        response.raise_for_status()
    return response.json()


def main():
    device = os.environ["SHIYI_SIM_DEVICE_ID"]
    token = os.environ["SHIYI_SIM_DEVICE_TOKEN"]
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=5) as client:
        result = run_once(client, device, token)
    print("Simulator:", result if result else "No pending command")


if __name__ == "__main__":
    main()
