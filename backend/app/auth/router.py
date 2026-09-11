"""
app/auth/router.py

FastAPI router exposing all authentication endpoints:
- Registration (email or phone)
- Login (identifier + password)
- Active session inspection (/api/auth/me)
- Secure logout with cookie clearance
- Forgot password & password reset token workflows
- Google OAuth 2.0 authorization URL & callback exchange
"""

from __future__ import annotations

import time
import httpx
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import User, UserSession, PasswordResetToken, VerificationCode
from .deps import get_current_user, extract_session_token
from .rate_limiter import enforce_rate_limit, auth_limiter
from .security import (
    hash_password,
    verify_password,
    validate_password_strength,
    normalize_email,
    normalize_phone_number,
    generate_session_token,
    hash_token,
    generate_reset_token,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# -------------------------------------------------------------------------
# Request / Response Schemas
# -------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=128, description="User's full name")
    email: Optional[str] = Field(default=None, description="Email address")
    phoneNumber: Optional[str] = Field(default=None, description="Mobile telephone number")
    countryCode: Optional[str] = Field(default="IN", description="Default country code ISO alpha-2")
    password: str = Field(..., description="Plaintext password meeting strength requirements")
    confirmPassword: str = Field(..., description="Password confirmation")


class LoginRequest(BaseModel):
    identifier: str = Field(..., description="Registered email address or phone number")
    password: str = Field(..., description="Plaintext password")


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(..., description="Email address or phone number")


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., description="One-time password reset token")
    password: str = Field(..., description="New password")
    confirmPassword: str = Field(..., description="New password confirmation")


class GoogleCallbackRequest(BaseModel):
    code: str = Field(..., description="Authorization code returned by Google OAuth")
    redirectUri: Optional[str] = Field(default=None, description="OAuth redirect URI")


class GoogleCredentialRequest(BaseModel):
    credential: str = Field(..., description="Google ID Token JWT")


class UserResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phoneNumber: Optional[str] = None
    role: str
    emailVerified: bool
    phoneVerified: bool
    hasPassword: bool
    hasGoogle: bool
    createdAt: float
    lastLoginAt: Optional[float] = None


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phoneNumber=user.phone_number,
        role=user.role,
        emailVerified=user.email_verified,
        phoneVerified=user.phone_verified,
        hasPassword=bool(user.password_hash),
        hasGoogle=bool(user.google_id),
        createdAt=user.created_at,
        lastLoginAt=user.last_login_at,
    )


def _set_auth_cookie(response: Response, raw_token: str) -> None:
    max_age = settings.SESSION_EXPIRE_DAYS * 86400
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.SESSION_COOKIE_SECURE,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        samesite="lax",
        httponly=True,
    )


# -------------------------------------------------------------------------
# 1. Registration
# -------------------------------------------------------------------------

@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(
        key=f"reg:{client_ip}",
        max_attempts=6,
        window_seconds=600,
        error_detail="Too many registration attempts.",
    )

    if body.password != body.confirmPassword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match.",
        )

    is_strong, strength_err = validate_password_strength(body.password)
    if not is_strong:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=strength_err,
        )

    norm_email = normalize_email(body.email)
    norm_phone = None
    if body.phoneNumber:
        try:
            norm_phone = normalize_phone_number(body.phoneNumber, body.countryCode or "IN")
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    if not norm_email and not norm_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either an email address or a valid phone number must be provided.",
        )

    # Enforce uniqueness
    if norm_email:
        existing_email = await session.execute(select(User).filter_by(email=norm_email))
        if existing_email.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address already exists.",
            )

    if norm_phone:
        existing_phone = await session.execute(select(User).filter_by(phone_number=norm_phone))
        if existing_phone.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this phone number already exists.",
            )

    now = time.time()
    hashed_pwd = hash_password(body.password)

    user = User(
        name=body.name.strip(),
        email=norm_email,
        phone_number=norm_phone,
        password_hash=hashed_pwd,
        google_id=None,
        email_verified=False,
        phone_verified=False,
        role="user",
        created_at=now,
        updated_at=now,
        last_login_at=now,
    )
    session.add(user)
    await session.flush()

    # Create active session and issue HTTP-only cookie
    raw_token, token_hash = generate_session_token()
    user_session = UserSession(
        id=raw_token[:32],
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + (settings.SESSION_EXPIRE_DAYS * 86400),
        created_at=now,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:255],
    )
    session.add(user_session)
    await session.commit()

    _set_auth_cookie(response, raw_token)
    return _to_user_response(user)


# -------------------------------------------------------------------------
# 2. Login
# -------------------------------------------------------------------------

@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"login:{client_ip}:{body.identifier.strip().lower()}"
    enforce_rate_limit(
        key=rate_key,
        max_attempts=6,
        window_seconds=300,
        error_detail="Too many failed login attempts.",
    )

    clean_id = body.identifier.strip()
    is_email = "@" in clean_id

    user = None
    if is_email:
        res = await session.execute(select(User).filter_by(email=clean_id.lower()))
        user = res.scalar_one_or_none()
    else:
        # Try normalizing as phone number, or match raw phone string
        try:
            norm_phone = normalize_phone_number(clean_id)
        except ValueError:
            norm_phone = clean_id

        res = await session.execute(
            select(User).filter(
                or_(User.phone_number == norm_phone, User.phone_number == clean_id)
            )
        )
        user = res.scalar_one_or_none()

    # Verification: time-constant check prevents account enumeration
    pwd_valid = verify_password(body.password, user.password_hash if user else None)
    if not user or not pwd_valid:
        auth_limiter.record(rate_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/phone number or password.",
        )

    auth_limiter.reset(rate_key)
    now = time.time()
    user.last_login_at = now

    raw_token, token_hash = generate_session_token()
    user_session = UserSession(
        id=raw_token[:32],
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + (settings.SESSION_EXPIRE_DAYS * 86400),
        created_at=now,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:255],
    )
    session.add(user_session)
    await session.commit()

    _set_auth_cookie(response, raw_token)
    return _to_user_response(user)


# -------------------------------------------------------------------------
# 3. Current Authenticated Profile (/api/auth/me)
# -------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return _to_user_response(user)


# -------------------------------------------------------------------------
# 4. Logout
# -------------------------------------------------------------------------

@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    raw_token = await extract_session_token(request)
    if raw_token:
        token_hash = hash_token(raw_token)
        res = await session.execute(select(UserSession).filter_by(token_hash=token_hash))
        active_sess = res.scalar_one_or_none()
        if active_sess:
            await session.delete(active_sess)
            await session.commit()

    _clear_auth_cookie(response)
    return {"status": "ok", "message": "Logged out successfully"}


# -------------------------------------------------------------------------
# 5. Forgot Password & Reset
# -------------------------------------------------------------------------

@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(
        key=f"reset:{client_ip}",
        max_attempts=4,
        window_seconds=600,
        error_detail="Too many password reset requests.",
    )

    clean_id = body.identifier.strip()
    is_email = "@" in clean_id

    user = None
    if is_email:
        res = await session.execute(select(User).filter_by(email=clean_id.lower()))
        user = res.scalar_one_or_none()
    else:
        try:
            norm_phone = normalize_phone_number(clean_id)
        except ValueError:
            norm_phone = clean_id

        res = await session.execute(
            select(User).filter(
                or_(User.phone_number == norm_phone, User.phone_number == clean_id)
            )
        )
        user = res.scalar_one_or_none()

    dev_token = None
    if user:
        now = time.time()
        raw_token, token_hash = generate_reset_token()
        reset_entry = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + (settings.PASSWORD_RESET_EXPIRE_HOURS * 3600),
            used=False,
            created_at=now,
        )
        session.add(reset_entry)
        await session.commit()

        # In development without external SMTP, log token for testing
        if not settings.SMTP_HOST:
            print(f"[MineGuard Auth] Password reset token generated for user ID {user.id}: {raw_token}")
            dev_token = raw_token

    return {
        "status": "ok",
        "message": "If an account with that identifier exists, password reset instructions have been dispatched.",
        "emailProviderConfigured": bool(settings.SMTP_HOST),
        "smsProviderConfigured": bool(settings.TWILIO_ACCOUNT_SID),
        "devToken": dev_token if not settings.SMTP_HOST else None,
    }


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    session: AsyncSession = Depends(get_db),
):
    if body.password != body.confirmPassword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match.",
        )

    is_strong, strength_err = validate_password_strength(body.password)
    if not is_strong:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=strength_err,
        )

    token_hash = hash_token(body.token.strip())
    now = time.time()

    res = await session.execute(
        select(PasswordResetToken).filter_by(token_hash=token_hash, used=False)
    )
    reset_entry = res.scalar_one_or_none()

    if not reset_entry or reset_entry.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, or previously used password reset token.",
        )

    # Fetch user
    user_res = await session.execute(select(User).filter_by(id=reset_entry.user_id))
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Associated user account not found.",
        )

    # Update password and mark token used
    user.password_hash = hash_password(body.password)
    user.updated_at = now
    reset_entry.used = True

    # Invalidate all existing sessions for security
    user_sessions_res = await session.execute(
        select(UserSession).filter_by(user_id=user.id)
    )
    for s in user_sessions_res.scalars().all():
        await session.delete(s)

    await session.commit()
    return {
        "status": "ok",
        "message": "Password has been successfully reset. Please sign in with your new password.",
    }


# -------------------------------------------------------------------------
# 6. Google OAuth 2.0 / OpenID Connect
# -------------------------------------------------------------------------

@router.get("/google/url")
def get_google_auth_url():
    """Generates the official Google OAuth 2.0 authorization URL."""
    if not settings.GOOGLE_CLIENT_ID:
        return {
            "configured": False,
            "url": None,
            "detail": "Google OAuth is not configured. Set GOOGLE_CLIENT_ID in environment variables.",
        }

    redirect_uri = settings.GOOGLE_CALLBACK_URL
    scope = "openid email profile"
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&access_type=offline"
        f"&prompt=select_account"
    )
    return {"configured": True, "url": url}


@router.post("/google/callback", response_model=UserResponse)
async def google_callback(
    body: GoogleCallbackRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    """Exchanges Google authorization code for token and user profile."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth is not configured on the server. Please configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    redirect_uri = body.redirectUri or settings.GOOGLE_CALLBACK_URL

    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": body.code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(token_url, data=token_data)
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to exchange Google authorization code: {token_resp.text}",
            )
        token_json = token_resp.json()
        access_token = token_json.get("access_token")

        # Fetch user info
        userinfo_resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to retrieve Google user profile.",
            )
        userinfo = userinfo_resp.json()

    google_sub = userinfo.get("sub")
    email = normalize_email(userinfo.get("email"))
    name = userinfo.get("name") or "Google User"

    if not google_sub:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Google profile payload (missing sub).",
        )

    # 1. Match by google_id
    res = await session.execute(select(User).filter_by(google_id=google_sub))
    user = res.scalar_one_or_none()

    # 2. Match by email to link account
    if not user and email:
        email_res = await session.execute(select(User).filter_by(email=email))
        user = email_res.scalar_one_or_none()
        if user:
            user.google_id = google_sub
            user.email_verified = True

    now = time.time()

    # 3. Create new account if no match
    if not user:
        user = User(
            name=name,
            email=email,
            phone_number=None,
            password_hash=None,
            google_id=google_sub,
            email_verified=True,
            phone_verified=False,
            role="user",
            created_at=now,
            updated_at=now,
            last_login_at=now,
        )
        session.add(user)
        await session.flush()
    else:
        user.last_login_at = now

    client_ip = request.client.host if request.client else "unknown"
    raw_token, token_hash = generate_session_token()
    user_session = UserSession(
        id=raw_token[:32],
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + (settings.SESSION_EXPIRE_DAYS * 86400),
        created_at=now,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:255],
    )
    session.add(user_session)
    await session.commit()

    _set_auth_cookie(response, raw_token)
    return _to_user_response(user)


@router.post("/google/credential", response_model=UserResponse)
async def google_credential(
    body: GoogleCredentialRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
):
    """Verifies a Google ID Token (from Google Identity Services button) and establishes session."""
    async with httpx.AsyncClient() as client:
        verify_resp = await client.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={body.credential}"
        )
        if verify_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google ID token verification failed.",
            )
        info = verify_resp.json()

    # Validate audience if client ID configured
    if settings.GOOGLE_CLIENT_ID and info.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google ID token audience mismatch.",
        )

    google_sub = info.get("sub")
    email = normalize_email(info.get("email"))
    name = info.get("name") or "Google User"

    # Match by google_id
    res = await session.execute(select(User).filter_by(google_id=google_sub))
    user = res.scalar_one_or_none()

    # Match by email to link account
    if not user and email:
        email_res = await session.execute(select(User).filter_by(email=email))
        user = email_res.scalar_one_or_none()
        if user:
            user.google_id = google_sub
            user.email_verified = True

    now = time.time()
    if not user:
        user = User(
            name=name,
            email=email,
            phone_number=None,
            password_hash=None,
            google_id=google_sub,
            email_verified=True,
            phone_verified=False,
            role="user",
            created_at=now,
            updated_at=now,
            last_login_at=now,
        )
        session.add(user)
        await session.flush()
    else:
        user.last_login_at = now

    client_ip = request.client.host if request.client else "unknown"
    raw_token, token_hash = generate_session_token()
    user_session = UserSession(
        id=raw_token[:32],
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + (settings.SESSION_EXPIRE_DAYS * 86400),
        created_at=now,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:255],
    )
    session.add(user_session)
    await session.commit()

    _set_auth_cookie(response, raw_token)
    return _to_user_response(user)
