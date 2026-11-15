"""Authenticated local-development activity lifecycle API."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from .auth import current_user
from .recommendation import get_activity
from .schemas import FeedbackRequest, FeedbackResponse, SessionCreate, SessionResponse
from .storage import SessionStore, StoreError, get_store

router = APIRouter(prefix="/api/v1/activities", tags=["activities"])
User = Annotated[str, Depends(current_user)]
Store = Annotated[SessionStore, Depends(get_store)]


def _known_activity(activity_id: str):
    activity = get_activity(activity_id)
    if activity is None:
        raise HTTPException(404, "Unknown activity")
    return activity


def _call(operation, *args):
    try:
        return operation(*args)
    except StoreError as error:
        raise HTTPException(error.status, error.message) from None


@router.post("/sessions", response_model=SessionResponse)
def create_session(payload: SessionCreate, user: User, store: Store):
    _, title, minutes, _ = _known_activity(payload.activity_id)
    return _call(store.create, user, payload.activity_id, title,
                 minutes, payload.client_request_id)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, user: User, store: Store):
    return _call(store.get, user, session_id)


@router.post("/sessions/{session_id}/start", response_model=SessionResponse)
def start_session(session_id: str, user: User, store: Store):
    return _call(store.transition, user, session_id, "RUNNING")


@router.post("/sessions/{session_id}/complete", response_model=SessionResponse)
def complete_session(session_id: str, user: User, store: Store):
    return _call(store.transition, user, session_id, "COMPLETED")


@router.post("/sessions/{session_id}/cancel", response_model=SessionResponse)
def cancel_session(session_id: str, user: User, store: Store):
    return _call(store.transition, user, session_id, "CANCELLED")


@router.post("/feedback", response_model=FeedbackResponse)
def feedback(payload: FeedbackRequest, user: User, store: Store):
    if payload.session_id is None:
        _known_activity(payload.activity_id)
    duplicate = _call(store.feedback, user, payload)
    return FeedbackResponse(accepted=True, event_id=payload.client_event_id, duplicate=duplicate)
