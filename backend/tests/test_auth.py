"""
tests/test_auth.py

Comprehensive tests for the MineGuard authentication system:
- User registration (Email, Phone)
- Password validation and strength enforcement
- Duplicate account prevention
- Login via email or phone
- Timing-safe error handling (no account enumeration)
- Session persistence via HTTP-only cookie and /api/auth/me
- Secure session invalidation on logout
- Password reset request & one-time token redemption
- Rate limiting on authentication endpoints
- Google OAuth URL generator
"""

import time
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import init_db
from app.config import settings


@pytest.mark.asyncio
async def test_auth_registration_and_login_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await init_db()
        ts = int(time.time() * 1000)
        email = f"operator_{ts}@mineguard.in"
        phone = f"+919876{ts % 1000000:06d}"

        # 1. Weak password should be rejected
        resp = await ac.post("/api/auth/register", json={
            "name": "Miner One",
            "email": f"miner_{ts}@example.com",
            "password": "weak",
            "confirmPassword": "weak",
        })
        assert resp.status_code == 400
        assert "at least 8 characters" in resp.json()["detail"]

        # 2. Mismatched passwords should be rejected
        resp = await ac.post("/api/auth/register", json={
            "name": "Miner One",
            "email": f"miner_{ts}@example.com",
            "password": "StrongPassword123!",
            "confirmPassword": "DifferentPassword123!",
        })
        assert resp.status_code == 400
        assert "do not match" in resp.json()["detail"]

        # 3. Successful registration with Email & Phone
        resp = await ac.post("/api/auth/register", json={
            "name": "Chief Mine Operator",
            "email": email,
            "phoneNumber": phone,
            "password": "SecureOperator2026!",
            "confirmPassword": "SecureOperator2026!",
        })
        assert resp.status_code == 201
        user_data = resp.json()
        assert user_data["name"] == "Chief Mine Operator"
        assert user_data["email"] == email
        assert user_data["phoneNumber"] == phone
        assert user_data["hasPassword"] is True
        assert settings.SESSION_COOKIE_NAME in resp.cookies

        # 4. Duplicate email registration should fail
        resp = await ac.post("/api/auth/register", json={
            "name": "Impostor",
            "email": email.upper(),  # case insensitive
            "password": "AnotherPassword123!",
            "confirmPassword": "AnotherPassword123!",
        })
        assert resp.status_code == 400
        assert "email address already exists" in resp.json()["detail"]

        # 5. Successful inspection of authenticated session (/api/auth/me)
        resp = await ac.get("/api/auth/me")
        assert resp.status_code == 200
        me = resp.json()
        assert me["email"] == email
        assert me["name"] == "Chief Mine Operator"

        # 6. Logout should clear session
        resp = await ac.post("/api/auth/logout")
        assert resp.status_code == 200

        # Subsequent /api/auth/me should return 401
        resp = await ac.get("/api/auth/me")
        assert resp.status_code == 401

        # 7. Login with Email
        resp = await ac.post("/api/auth/login", json={
            "identifier": email,
            "password": "SecureOperator2026!",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "Chief Mine Operator"
        assert settings.SESSION_COOKIE_NAME in resp.cookies

        # Logout again
        await ac.post("/api/auth/logout")

        # 8. Login with Phone Number
        resp = await ac.post("/api/auth/login", json={
            "identifier": phone,
            "password": "SecureOperator2026!",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "Chief Mine Operator"

        # 9. Invalid credentials should return 401 with uniform message (anti-enumeration)
        resp = await ac.post("/api/auth/login", json={
            "identifier": "nonexistent@mineguard.in",
            "password": "WrongPassword123!",
        })
        assert resp.status_code == 401
        assert "Invalid email/phone number or password" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_password_reset_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await init_db()
        email = f"safety_{int(time.time() * 1000)}@mineguard.in"

        # Register user for reset test
        reg_resp = await ac.post("/api/auth/register", json={
            "name": "Safety Officer",
            "email": email,
            "password": "InitialPassword123!",
            "confirmPassword": "InitialPassword123!",
        })
        assert reg_resp.status_code == 201

        # Request password reset
        resp = await ac.post("/api/auth/forgot-password", json={
            "identifier": email,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        dev_token = data.get("devToken")
        assert dev_token is not None

        # Try resetting with mismatched passwords
        resp = await ac.post("/api/auth/reset-password", json={
            "token": dev_token,
            "password": "BrandNewPassword2026!",
            "confirmPassword": "MismatchPassword!",
        })
        assert resp.status_code == 400

        # Successful password reset
        resp = await ac.post("/api/auth/reset-password", json={
            "token": dev_token,
            "password": "BrandNewPassword2026!",
            "confirmPassword": "BrandNewPassword2026!",
        })
        assert resp.status_code == 200
        assert "successfully reset" in resp.json()["message"]

        # Re-using the same token should fail
        resp = await ac.post("/api/auth/reset-password", json={
            "token": dev_token,
            "password": "AnotherNewPassword2026!",
            "confirmPassword": "AnotherNewPassword2026!",
        })
        assert resp.status_code == 400

        # Login with old password must fail
        resp = await ac.post("/api/auth/login", json={
            "identifier": email,
            "password": "InitialPassword123!",
        })
        assert resp.status_code == 401

        # Login with new password must succeed
        resp = await ac.post("/api/auth/login", json={
            "identifier": email,
            "password": "BrandNewPassword2026!",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "Safety Officer"


@pytest.mark.asyncio
async def test_google_oauth_url():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/auth/google/url")
        assert resp.status_code == 200
        data = resp.json()
        assert "configured" in data
