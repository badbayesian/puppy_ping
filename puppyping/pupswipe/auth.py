"""Authentication and session utilities for PupSwipe."""

from __future__ import annotations

import hashlib
import hmac
import os
import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse

from puppyping.pupswipe.config import (
    DEFAULT_SESSION_SECRET,
    PASSWORD_HASH_ITERATIONS,
    PASSWORD_MIN_LENGTH,
    PASSWORD_RESET_TOKEN_TTL_MINUTES,
)


def password_error(password: str) -> str | None:
    """Return a validation error for password input, if any."""
    if len(password or "") < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    return None


def new_password_error(new_password: str, confirm_password: str) -> str | None:
    """Return validation error for new-password and confirmation inputs."""
    validation_error = password_error(new_password)
    if validation_error:
        return validation_error
    if new_password != confirm_password:
        return "New passwords do not match."
    return None


def password_reset_error(
    current_password: str,
    new_password: str,
    confirm_password: str,
) -> str | None:
    """Return validation error for reset-password form input, if any."""
    if not current_password:
        return "Enter your current password."
    validation_error = new_password_error(new_password, confirm_password)
    if validation_error:
        return validation_error
    if current_password == new_password:
        return "New password must be different from current password."
    return None


def hash_password(password: str) -> str:
    """Hash a password for storage using PBKDF2-HMAC-SHA256."""
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify plaintext password against a stored PBKDF2 hash."""
    try:
        algo, iterations_text, salt, expected_digest = password_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if iterations < 1 or not salt or not expected_digest:
            return False
    except (ValueError, TypeError):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
    ).hex()
    return hmac.compare_digest(actual_digest, expected_digest)


def password_reset_token_hash(token: str) -> str:
    """Return a fixed hash for a reset token so raw tokens are not stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def send_password_reset_email(email: str, reset_link: str) -> None:
    """Send password reset link via SMTP credentials from environment."""
    msg = EmailMessage()
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = email
    msg["Subject"] = "PupSwipe password reset"
    msg.set_content(
        "\n".join(
            [
                "You requested a password reset for PupSwipe.",
                f"This link expires in {PASSWORD_RESET_TOKEN_TTL_MINUTES} minutes.",
                "",
                reset_link,
                "",
                "If you did not request this, you can ignore this email.",
            ]
        )
    )
    with smtplib.SMTP_SSL(os.environ["EMAIL_HOST"], int(os.environ["EMAIL_PORT"])) as smtp:
        smtp.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASS"])
        smtp.send_message(msg)


def normalize_next_path(value: str | None, default: str = "/") -> str:
    """Normalize redirect targets to local absolute paths only."""
    candidate = (value or "").strip()
    if not candidate:
        return default
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return default
    if not candidate.startswith("/") or candidate.startswith("//"):
        return default
    return candidate


def session_secret() -> str:
    """Return the cookie-signing secret."""
    secret = os.environ.get("PUPSWIPE_SESSION_SECRET", "").strip()
    return secret or DEFAULT_SESSION_SECRET


def session_signature(user_id: int) -> str:
    """Build an HMAC signature for a user-id session payload."""
    payload = str(user_id).encode("utf-8")
    secret = session_secret().encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def encode_session_value(user_id: int) -> str:
    """Encode signed session cookie contents."""
    return f"{user_id}.{session_signature(user_id)}"


def decode_session_value(raw_value: str | None) -> int | None:
    """Decode and verify a signed session cookie value."""
    value = (raw_value or "").strip()
    if "." not in value:
        return None
    user_id_text, signature = value.split(".", 1)
    if not user_id_text.isdigit():
        return None
    user_id = int(user_id_text)
    if user_id <= 0:
        return None
    expected = session_signature(user_id)
    if not hmac.compare_digest(signature, expected):
        return None
    return user_id
