"""Local-only, independently authenticated simulator and command API."""
import json
import os
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from .auth import bearer, current_user
from .device_contract import CommandRequest, CommandView, DeviceEvent, Receipt
from .device_storage import enqueue, get_command, pending, record_event
from .storage import SessionStore, StoreError, get_store

router = APIRouter(prefix="/api/v1/devices", tags=["device-simulation"])
User = Annotated[str, Depends(current_user)]
Store = Annotated[SessionStore, Depends(get_store)]


def configured_devices():
    try:
        devices = json.loads(os.environ.get("SHIYI_DEV_DEVICES", "{}"))
        users = json.loads(os.environ.get("SHIYI_DEV_USERS", "{}"))
        if not isinstance(devices, dict) or not isinstance(users, dict):
            raise TypeError
        tokens = set()
        for device_id, entry in devices.items():
            if (
                not isinstance(device_id, str) or not 0 < len(device_id) <= 80
                or not isinstance(entry, dict) or set(entry) != {"user_id", "token"}
                or not isinstance(entry["user_id"], str) or entry["user_id"] not in users
                or not isinstance(entry["token"], str) or len(entry["token"]) < 16
                or entry["token"] in users.values() or entry["token"] in tokens
            ):
                raise ValueError
            tokens.add(entry["token"])
    except (ValueError, TypeError):
        raise HTTPException(503, "Invalid development device configuration") from None
    return devices


def current_device(
    device_id: str,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    entry = configured_devices().get(device_id)
    if (
        entry is None or credentials is None
        or not compare_digest(credentials.credentials.encode(), entry["token"].encode())
    ):
        raise HTTPException(401, "Invalid device credential",
                            headers={"WWW-Authenticate": "Bearer"})
    return entry["user_id"]


DeviceOwner = Annotated[str, Depends(current_device)]


def check_owner(user: str, device_id: str):
    entry = configured_devices().get(device_id)
    if entry is None or entry["user_id"] != user:
        raise HTTPException(404, "Device not found")


def invoke(operation, *args):
    try:
        return operation(*args)
    except StoreError as error:
        raise HTTPException(error.status, error.message) from None


@router.post("/commands", response_model=CommandView)
def create_command(payload: CommandRequest, user: User, store: Store):
    check_owner(user, payload.device_id)
    return invoke(enqueue, store, user, payload)


@router.get("/commands/{command_id}", response_model=CommandView)
def command_status(command_id: str, user: User, store: Store):
    result = invoke(get_command, store, user, command_id)
    check_owner(user, result.device_id)
    return result


@router.get("/{device_id}/pending", response_model=CommandView | None)
def poll(device_id: str, owner: DeviceOwner, store: Store):
    return invoke(pending, store, owner, device_id)


@router.post("/{device_id}/events", response_model=Receipt)
def event(device_id: str, payload: DeviceEvent, owner: DeviceOwner, store: Store):
    if payload.device_id != device_id:
        raise HTTPException(409, "Device event identity does not match path")
    return invoke(record_event, store, owner, payload)
