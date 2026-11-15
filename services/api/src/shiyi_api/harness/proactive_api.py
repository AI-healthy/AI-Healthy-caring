from fastapi import APIRouter

from ..device_api import DeviceOwner, Store, User
from . import proactive
from .api import call
from .proactive_contracts import (
    DeliveryReceipt,
    DeviceOffer,
    OfferView,
    ScheduleRequest,
    ScheduleView,
)

router = APIRouter(prefix="/api/v1/proactive", tags=["proactive-simulation"])


@router.get("/schedule", response_model=ScheduleView)
def schedule(user: User, store: Store):
    return call(proactive.get_schedule, store, user)


@router.put("/schedule", response_model=ScheduleView)
def update_schedule(payload: ScheduleRequest, user: User, store: Store):
    return call(proactive.put_schedule, store, user, payload)


@router.get("/offers/pending", response_model=OfferView | None)
def pending(user: User, store: Store):
    return call(proactive.pending_offer, store, user)


@router.post("/offers/{offer_id}/ack", response_model=DeliveryReceipt)
def ack(offer_id: str, user: User, store: Store):
    return call(proactive.acknowledge, store, user, offer_id)


@router.get("/devices/{device_id}/pending", response_model=DeviceOffer | None)
def device_pending(device_id: str, owner: DeviceOwner, store: Store):
    return call(proactive.pending_device_offer, store, owner, device_id)


@router.post("/devices/{device_id}/offers/{offer_id}/ack", response_model=DeliveryReceipt)
def device_ack(device_id: str, offer_id: str, owner: DeviceOwner, store: Store):
    return call(proactive.acknowledge, store, owner, offer_id, device_id)
