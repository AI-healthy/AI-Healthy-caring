from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from . import identity_storage
from .auth import bearer, current_user
from .identity_contract import (
    Credentials,
    LoginResponse,
    Profile,
    ProfileUpdate,
    RegisterRequest,
)
from .storage import SessionStore, StoreError, get_store

router = APIRouter(prefix="/api/v1/users", tags=["local-accounts"])
Store = Annotated[SessionStore, Depends(get_store)]
User = Annotated[str, Depends(current_user)]


def call(operation, *args):
    try:
        return operation(*args)
    except StoreError as error:
        raise HTTPException(error.status, error.message) from None


@router.post("/register", response_model=Profile, status_code=201)
def register(payload: RegisterRequest, store: Store):
    return call(identity_storage.register, store, payload)


@router.post("/login", response_model=LoginResponse)
def login(payload: Credentials, store: Store):
    return call(identity_storage.login, store, payload)


@router.post("/logout", status_code=204)
def logout(
    user: User, store: Store,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    call(identity_storage.logout, store, user, credentials.credentials)


@router.get("/me", response_model=Profile)
def get_me(user: User, store: Store):
    return call(identity_storage.get_profile, store, user)


@router.patch("/me", response_model=Profile)
def update_me(payload: ProfileUpdate, user: User, store: Store):
    return call(identity_storage.update_profile, store, user, payload)
