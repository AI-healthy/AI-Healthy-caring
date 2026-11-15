import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import current_user
from ..storage import SessionStore, StoreError, get_store
from . import repository
from .contracts import ConfirmResult, MemoryView, RunRequest, RunView, Selection, Settings
from .engine import Ranker
from .model_adapter import LocalModelRanker

router = APIRouter(prefix="/api/v1/harness", tags=["agent-harness"])
User = Annotated[str, Depends(current_user)]
Store = Annotated[SessionStore, Depends(get_store)]


def get_ranker() -> Ranker | None:
    """Server-only strategy configuration; model use also requires user opt-in."""
    if os.environ.get("SHIYI_RANKER", "rules") == "local_llm":
        return LocalModelRanker.from_environment()
    return None


Strategy = Annotated[Ranker | None, Depends(get_ranker)]


def call(operation, *args):
    try:
        return operation(*args)
    except StoreError as error:
        raise HTTPException(error.status, error.message) from None


@router.get("/settings", response_model=Settings)
def settings(user: User, store: Store):
    return call(repository.get_settings, store, user)


@router.put("/settings", response_model=Settings)
def update_settings(payload: Settings, user: User, store: Store):
    return call(repository.put_settings, store, user, payload)


@router.get("/memory", response_model=MemoryView)
def memory(user: User, store: Store,
           available_minutes: Annotated[int | None, Query(ge=1, le=120)] = None):
    return call(repository.get_memory, store, user, available_minutes)


@router.post("/memory/reset", response_model=MemoryView)
def reset_memory(user: User, store: Store):
    return call(repository.reset_memory, store, user)


@router.post("/runs", response_model=RunView)
def run(payload: RunRequest, user: User, store: Store, ranker: Strategy):
    return call(repository.create_run, store, user, payload, ranker)


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(run_id: str, user: User, store: Store):
    return call(repository.get_run, store, user, run_id)


@router.post("/runs/{run_id}/confirm", response_model=ConfirmResult)
def confirm(run_id: str, payload: Selection, user: User, store: Store):
    return call(repository.confirm, store, user, run_id, payload)


@router.post("/runs/{run_id}/dismiss", response_model=RunView)
def dismiss(run_id: str, user: User, store: Store):
    return call(repository.dismiss, store, user, run_id)
