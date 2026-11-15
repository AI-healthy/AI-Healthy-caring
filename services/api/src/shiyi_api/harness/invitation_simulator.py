"""Simulate receiving a generic invitation; never start a physical action."""
import os
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from .proactive_contracts import DeviceOffer

MESSAGE = "要不要抽一点时间，试试时宜为你准备的小活动？请在 App 中选择。"


def poll_once(client, device_id, token):
    headers = {"Authorization": f"Bearer {token}"}
    root = f"/api/v1/proactive/devices/{quote(device_id, safe='')}"
    response = client.get(root + "/pending", headers=headers)
    response.raise_for_status()
    if response.json() is None:
        return None
    offer = DeviceOffer.model_validate(response.json())
    if offer.expires_at <= datetime.now(UTC):
        return None
    # ACK only means successful receipt at the simulated endpoint, not actual display/speech.
    ack = client.post(f"{root}/offers/{offer.offer_id}/ack", headers=headers)
    ack.raise_for_status()
    return offer, MESSAGE


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=5, trust_env=False) as client:
        result = poll_once(client, os.environ["SHIYI_SIM_DEVICE_ID"],
                           os.environ["SHIYI_SIM_DEVICE_TOKEN"])
    print("SIMULATED invitation:", result[1] if result else "No pending invitation")


if __name__ == "__main__":
    main()
