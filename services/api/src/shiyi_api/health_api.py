from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from . import health_storage
from .auth import current_user
from .health_contract import (
    BatchReceipt,
    ConsentUpdate,
    ConsentView,
    Metric,
    ObservationBatch,
    ObservationPage,
    Source,
)
from .storage import SessionStore, StoreError, get_store

router = APIRouter(prefix="/api/v1/health", tags=["synthetic-health"])
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
