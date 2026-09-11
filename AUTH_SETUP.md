# MineGuard Authentication System Setup & Integration Guide

This document describes the architecture, configuration, database migrations, and operational workflows for the MineGuard Production Authentication & Session Management System.

---

## 1. Architecture Overview

The MineGuard authentication system implements an industry-standard, defense-in-depth security model designed specifically for critical mine geotechnical telemetry:

- **Identity Providers**:
  - Email + Argon2/bcrypt password authentication.
  - Phone number + password authentication with international country codes and automatic E.164 normalization via `google-libphonenumber`.
  - Google OAuth 2.0 / OpenID Connect with state token verification and server-side token exchange.
- **Session Architecture**:
  - Secure, HTTP-only, SameSite session cookies (`mineguard_session`) preventing XSS token extraction.
  - Optional `Authorization: Bearer <session_token>` header support for mobile/IoT clients.
  - Server-side session store (`user_sessions` table) storing cryptographic SHA-256 hashes of tokens.
  - Instant session revocation on user logout.
- **Protection & Safeguards**:
  - Sliding-window in-memory IP rate limiter protecting `/api/auth/login`, `/api/auth/register`, and `/api/auth/forgot-password`.
  - Timing-safe error handling to prevent username/email enumeration.
  - Live client-side password strength validation (minimum 8 characters, uppercase, lowercase, digit, special character) corroborated by server-side verification.
  - Protected frontend route gate preventing unauthorized access to telemetry dashboards, node controls, and maps.

---

## 2. Database Migrations

The database models reside in `app/models.py` and `backend/app/models.py`.

### A. Local SQLite (Development)
The SQLite schema initializes automatically on first run via SQLAlchemy's `Base.metadata.create_all`. Four new tables are managed:
1. `users`: Stores core profile, password hash, role, provider, and account status.
2. `user_sessions`: Stores hashed session tokens, client user agents, IP addresses, and expiration timestamps.
3. `password_reset_tokens`: Stores one-time hashed recovery tokens with 1-hour expiration.
4. `verification_codes`: Stores OTPs for email and SMS verification workflows.

### B. PostgreSQL / TimescaleDB (Production)
Run the migration script located at `backend/migrations/002_auth_schema.sql`:

```bash
psql -U postgres -d subnet -f backend/migrations/002_auth_schema.sql
```

---

## 3. Environment Configuration

### Backend (`c:\Users\harshita\OneDrive\Documents\Backend\.env`)

Copy `.env.example` to `.env` and configure:

```env
# Cryptographic secret for signing tokens (minimum 32 characters)
JWT_SECRET_KEY=generate-a-secure-random-32-byte-hex-string

# Session lifetime
SESSION_EXPIRE_DAYS=7
PASSWORD_RESET_EXPIRE_HOURS=1

# Set to true in production over HTTPS so cookies use Secure flag
SESSION_COOKIE_SECURE=false

# Google OAuth 2.0 Credentials (from Google Cloud Console)
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_CALLBACK_URL=http://localhost:5173/auth/callback

# Allowed CORS origins (must not use '*' with credentials: include)
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000

# Optional Email / SMS external providers
# SMTP_HOST=smtp.sendgrid.net
# SMTP_PORT=587
# SMTP_USER=apikey
# SMTP_PASSWORD=your_api_key
# EMAILS_FROM_EMAIL=alerts@mineguard.local
# TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxx
# TWILIO_AUTH_TOKEN=your_token
# TWILIO_PHONE_NUMBER=+1234567890
```

### Frontend (`C:\Users\harshita\MineGuard\web\.env`)

Create or update `.env` in the web frontend directory:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000/api/telemetry/ws
VITE_DEFAULT_NODE_ID=NODE-001
VITE_GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
```

---

## 4. Google OAuth 2.0 Setup

To enable Google Sign-In:

1. Navigate to the **[Google Cloud Console](https://console.cloud.google.com/)**.
2. Create or select your project.
3. Go to **APIs & Services > Credentials**.
4. Click **Create Credentials > OAuth Client ID**:
   - **Application type**: Web application.
   - **Name**: `MineGuard Web Client`.
   - **Authorized JavaScript origins**:
     - `http://localhost:5173`
     - `http://127.0.0.1:5173`
     - `https://your-production-domain.com`
   - **Authorized redirect URIs**:
     - `http://localhost:5173`
     - `http://localhost:8000/api/auth/google/callback`
5. Copy the **Client ID** and **Client Secret** into your backend `.env` file (`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`).

---

## 5. API Endpoints Reference

| Method | Path | Description | Access |
|---|---|---|---|
| `POST` | `/api/auth/register` | Register a new user with email or phone + password | Public (Rate-limited) |
| `POST` | `/api/auth/login` | Authenticate with email/phone + password | Public (Rate-limited) |
| `GET` | `/api/auth/me` | Fetch currently authenticated user session | Authenticated |
| `POST` | `/api/auth/logout` | Revoke active session and clear HTTP-only cookie | Authenticated |
| `POST` | `/api/auth/forgot-password` | Request password reset token | Public (Rate-limited) |
| `POST` | `/api/auth/reset-password` | Set new password using reset token | Public |
| `GET` | `/api/auth/google/url` | Retrieve Google OAuth authorization URL | Public |
| `POST` | `/api/auth/google/callback`| Exchange authorization code for session | Public |
| `POST` | `/api/auth/google/credential`| Verify Google ID token credential | Public |

---

## 6. Verification and Testing

### Backend Automated Test Suite
Execute the full pytest suite in `.venv`:
```bash
pytest -v
```
To run authentication tests specifically:
```bash
pytest tests/test_auth.py -v
```

### Frontend Typecheck & Build
In `MineGuard/web`:
```bash
npm run typecheck
npm run build
```

### Manual Acceptance Flow
1. **Unauthenticated Check**: Opening `http://localhost:5173` displays the MineGuard Login screen. Telemetry and map views are hidden.
2. **Registration**: Click "Register for an account". Enter Name, valid Email or Phone number (with country code), and a strong password. The password strength checklist displays real-time compliance. Submit to automatically log in.
3. **Session Persistence**: Refresh the browser page. The application restores your session via `/api/auth/me` and opens directly to the Dashboard without prompting for credentials.
4. **Header Profile**: The top bar displays your user name, email or phone, and a "Sign Out" button.
5. **Logout**: Click the sign out icon. The session is destroyed on the server and client, redirecting immediately back to the Login screen.
6. **Password Recovery**: Click "Forgot password?" from the login screen. Input your email or phone number. If SMTP is not yet configured, the system logs the recovery token to the server console and displays clear configuration guidance.
