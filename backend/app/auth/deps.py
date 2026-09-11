"""
app/auth/deps.py

FastAPI dependency injection utilities to authenticate incoming requests,
validating HTTP-only session cookies and Authorization bearer tokens.
"""

from __future__ import annotations

import time
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..db import get_db
from ..models import User, UserSession
from .security import hash_token


async def extract_session_token(request: Request) -> Optional[str]:
    """Extracts raw session token from HTTP-only cookie or Authorization header."""
    cookie_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        bearer_token = auth_header.split(" ", 1)[1].strip()
        if bearer_token:
            return bearer_token

    return None


async def get_optional_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Resolves authenticated User from request if session is active, or returns None."""
    raw_token = await extract_session_token(request)
    if not raw_token:
        return None

    token_hash = hash_token(raw_token)
    now = time.time()

    stmt = (
        select(UserSession)
        .options(selectinload(UserSession.user))
        .filter(UserSession.token_hash == token_hash, UserSession.expires_at > now)
    )
    result = await session.execute(stmt)
    user_session = result.scalar_one_or_none()

    if not user_session or not user_session.user:
        return None

    return user_session.user


async def get_current_user(
    user: Optional[User] = Depends(get_optional_user),
) -> User:
    """Enforces authentication. Raises HTTP 401 if request has no valid active session."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access this resource.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
