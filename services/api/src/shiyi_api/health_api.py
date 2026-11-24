from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from . import health_state_service, health_storage, health_summary, pressure_storage
from .auth import current_user
from .health_contract import (
    BatchReceipt,
    ConsentUpdate,
    ConsentView,
    Metric,
    ObservationBatch,
    ObservationPage,
    Source,
    WearableStream,
    WearableSummary,
)
from .health_state_contract import HealthStateView
from .pressure_contract import PressureCheckin, PressureCheckinInput, PressureConsent, PressurePair
from .storage import SessionStore, StoreError, get_store

router = APIRouter(prefix="/api/v1/health", tags=["health-observations"])
User = Annotated[str, Depends(current_user)]
Store = Annotated[SessionStore, Depends(get_store)]


def call(operation, *args):
    try:
        return operation(*args)
    except StoreError as error:
        raise HTTPException(error.status, error.message) from None


@router.get("/consents", response_model=list[ConsentView])
def consents(user: User, store: Store):
    return call(health_storage.list_consents, store, user)


@router.put("/consents/{source}/{metric}", response_model=ConsentView)
def set_consent(source: Source, metric: Metric, payload: ConsentUpdate, user: User, store: Store):
    return call(health_storage.update_consent, store, user, source, metric, payload)


@router.post("/observations", response_model=BatchReceipt)
def upload(payload: ObservationBatch, user: User, store: Store):
    return call(health_storage.upload, store, user, payload)


@router.get("/observations", response_model=ObservationPage)
def history(
    user: User, store: Store, source: Source | None = None, metric: Metric | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
):
    return call(health_storage.history, store, user, source, metric, limit, offset)


@router.delete("/observations/{observation_id}", status_code=204)
def delete_observation(observation_id: str, user: User, store: Store):
    call(health_storage.delete_observation, store, user, observation_id)


@router.get("/streams", response_model=list[WearableStream])
def wearable_streams(user: User, store: Store):
    return call(health_summary.streams, store, user)


@router.get("/summary", response_model=WearableSummary)
def wearable_summary(
    user: User, store: Store, source: Literal["gadgetbridge", "health_connect"],
    data_origin: Annotated[str, Query(min_length=1, max_length=200)],
    device_scope: Annotated[str, Query(pattern=r"^[0-9a-f]{32}$")],
    timezone: Annotated[str, Query(min_length=1, max_length=64)] = "Asia/Shanghai",
    day: date | None = None,
):
    return call(
        health_summary.daily, store, user, source, data_origin, device_scope, timezone, day
    )


@router.get("/state", response_model=HealthStateView)
def wearable_state(
    user: User, store: Store, source: Literal["gadgetbridge", "health_connect"],
    data_origin: Annotated[str, Query(min_length=1, max_length=200)],
    device_scope: Annotated[str, Query(pattern=r"^[0-9a-f]{32}$")],
    timezone: Annotated[str, Query(min_length=1, max_length=64)] = "Asia/Shanghai",
):
    return call(health_state_service.current, store, user, source, data_origin, device_scope, timezone)


@router.get("/pressure/consent", response_model=PressureConsent)
def pressure_consent(user: User, store: Store):
    return call(pressure_storage.get_consent, store, user)


@router.put("/pressure/consent", response_model=PressureConsent)
def set_pressure_consent(payload: PressureConsent, user: User, store: Store):
    return call(pressure_storage.consent, store, user, payload)


@router.post("/pressure/checkins", response_model=PressureCheckin)
def pressure_checkin(payload: PressureCheckinInput, user: User, store: Store):
    return call(pressure_storage.create, store, user, payload)


@router.get("/pressure/checkins", response_model=list[PressureCheckin])
def pressure_history(
    user: User, store: Store, limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
):
    return call(pressure_storage.history, store, user, limit, offset)


@router.get("/pressure/checkins/{checkin_id}/features", response_model=PressurePair)
def pressure_features(checkin_id: str, user: User, store: Store):
    return call(pressure_storage.pair, store, user, checkin_id)


@router.delete("/pressure/checkins/{checkin_id}", status_code=204)
def delete_pressure_checkin(checkin_id: str, user: User, store: Store):
    call(pressure_storage.delete, store, user, checkin_id)
