"""Local registered-account and pre-provisioned Bearer identities."""
import json
import os
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .identity_storage import authenticated_account
from .storage import get_store

bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if credentials is None:
        raise HTTPException(401, "A bearer token is required",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        identities = json.loads(os.environ.get("SHIYI_DEV_USERS", "{}"))
        if not isinstance(identities, dict) or not all(
            isinstance(user, str) and 0 < len(user) <= 80 and not user.startswith("usr_")
            and isinstance(token, str) and len(token) >= 16 and not token.startswith("shiyi_")
            for user, token in identities.items()
        ) or len(set(identities.values())) != len(identities):
            raise ValueError("Invalid development identities")
    except (ValueError, TypeError):
        raise HTTPException(503, "Development identity configuration is invalid") from None

    for user, token in identities.items():
        if compare_digest(credentials.credentials.encode(), token.encode()):
            return user
    if credentials.credentials.startswith("shiyi_"):
        user = authenticated_account(get_store(), credentials.credentials)
        if user is not None:
            return user
    raise HTTPException(401, "Invalid or expired bearer token",
                        headers={"WWW-Authenticate": "Bearer"})
