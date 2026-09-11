"""
app/auth/security.py

Cryptographic security helpers, password hashing with bcrypt, phone normalization
with libphonenumber, and token hashing to safeguard database records.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Optional, Tuple
import bcrypt
import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


# Precomputed dummy hash for constant-time comparison against non-existent users
_DUMMY_HASH = bcrypt.hashpw(b"mineguard_dummy_constant_time_salt_password", bcrypt.gensalt(12)).decode("utf-8")


def hash_password(plain_password: str) -> str:
    """Securely hashes a plaintext password using bcrypt with work factor 12."""
    if not plain_password:
        raise ValueError("Password cannot be empty")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """
    Verifies a plaintext password against a stored bcrypt hash.
    Performs constant-time evaluation even if the user record has no password (e.g. Google-only account).
    """
    if not hashed_password:
        bcrypt.checkpw(plain_password.encode("utf-8"), _DUMMY_HASH.encode("utf-8"))
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Validates that password meets production security criteria:
    - At least 8 characters in length
    - Contains lowercase letter
    - Contains uppercase letter
    - Contains numeric digit
    - Contains special symbol
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one numeric digit."
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        return False, "Password must contain at least one special character or symbol."
    return True, ""


def normalize_email(email: Optional[str]) -> Optional[str]:
    """Normalizes email to lowercase and trims surrounding whitespace."""
    if not email:
        return None
    cleaned = email.strip().lower()
    return cleaned if cleaned else None


def normalize_phone_number(phone_str: Optional[str], default_region: str = "IN") -> Optional[str]:
    """
    Parses and validates phone number using Google's libphonenumber port.
    Returns normalized E.164 representation (e.g. '+919876543210').
    Raises ValueError if the phone number is invalid.
    """
    if not phone_str:
        return None
    cleaned = phone_str.strip()
    if not cleaned:
        return None

    try:
        parsed = phonenumbers.parse(cleaned, default_region)
    except NumberParseException as e:
        raise ValueError(f"Invalid phone number format: {e._msg}")

    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("The provided phone number is not a valid recognized telephone number.")

    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def generate_session_token() -> Tuple[str, str]:
    """
    Generates a cryptographically strong random session token.
    Returns:
        raw_token: To be stored only in the user's secure HTTP-only cookie.
        token_hash: SHA-256 hash stored in the database.
    """
    raw_token = secrets.token_urlsafe(36)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def hash_token(raw_token: str) -> str:
    """Computes SHA-256 hash of a raw token for database lookup."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_reset_token() -> Tuple[str, str]:
    """Generates a secure one-time password reset token and its database hash."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def generate_verification_code() -> str:
    """Generates a 6-digit numeric verification code for SMS/email verification."""
    return f"{secrets.randbelow(900000) + 100000}"
