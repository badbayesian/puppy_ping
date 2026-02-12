from __future__ import annotations

import re
from collections.abc import Iterable
from email.utils import parseaddr

EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)
MAX_EMAIL_LENGTH = 320


def normalize_email(email: str | None) -> str:
    """Return a normalized email string for comparisons and storage."""
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    """Return True when an email has a pragmatic valid format."""
    if not email or len(email) > MAX_EMAIL_LENGTH:
        return False
    if "\r" in email or "\n" in email:
        return False
    _, parsed = parseaddr(email)
    if parsed != email:
        return False
    return bool(EMAIL_PATTERN.fullmatch(email))


def sanitize_email(email: str | None) -> str | None:
    """Normalize an email and return None when invalid."""
    normalized = normalize_email(email)
    return normalized if is_valid_email(normalized) else None


def parse_email_list(raw: str | None) -> list[str]:
    """Split a raw recipient string into candidate values."""
    if not raw:
        return []
    return [item.strip() for item in re.split(r"[,\n;]+", raw) if item.strip()]


def sanitize_emails(emails: Iterable[str | None]) -> list[str]:
    """Normalize, validate, and dedupe recipients while preserving order."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for email in emails:
        sanitized = sanitize_email(email)
        if not sanitized or sanitized in seen:
            continue
        seen.add(sanitized)
        cleaned.append(sanitized)
    return cleaned
