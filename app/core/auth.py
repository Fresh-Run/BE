"""Authentication: resolve the current user from a Supabase JWT.

Provides a FastAPI dependency, `get_current_user`, that reads the
`Authorization: Bearer <token>` header, validates the token against Supabase
Auth, and returns the user. Invalid/missing tokens yield HTTP 401.

This only needs SUPABASE_URL and SUPABASE_KEY (already configured); validation
is delegated to Supabase via `auth.get_user(token)`.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.supabase_client import get_supabase
from app.models.schemas import CurrentUser

logger = logging.getLogger(__name__)

# auto_error=False so we can return 401 (not 403) for a missing token.
_bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing authentication token.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """Return the authenticated user, or raise 401.

    Use as a dependency: `user: CurrentUser = Depends(get_current_user)`.
    """
    if credentials is None or not credentials.credentials:
        raise _UNAUTHORIZED

    token = credentials.credentials
    try:
        supabase = get_supabase()
        # supabase-py is synchronous; run off the event loop.
        response = await asyncio.to_thread(lambda: supabase.auth.get_user(token))
    except Exception as exc:  # noqa: BLE001 - any failure means "not authenticated"
        logger.info("Token validation failed: %s", exc)
        raise _UNAUTHORIZED from exc

    user = getattr(response, "user", None)
    if user is None or not user.id:
        raise _UNAUTHORIZED

    return CurrentUser(user_id=user.id, email=user.email)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser | None:
    """Like get_current_user, but tolerates anonymous (token-less) requests.

    - No token        -> None (treated as anonymous; caller stores NULL).
    - Valid token      -> CurrentUser.
    - Invalid/expired  -> 401 (a supplied-but-bad token is still an error).
    """
    if credentials is None or not credentials.credentials:
        return None
    return await get_current_user(credentials)
