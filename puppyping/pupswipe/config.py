"""Configuration and simple helper utilities for PupSwipe."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

APP_DIR = Path(__file__).resolve().parent
DEFAULT_LIMIT = 40
MAX_LIMIT = 200
PAGE_SIZE = 1
MAX_PUPPY_AGE_MONTHS = 8.0
MAX_BREED_FILTER_LENGTH = 80
MAX_NAME_FILTER_LENGTH = 80
PASSWORD_MIN_LENGTH = 8
PASSWORD_HASH_ITERATIONS = 200000
PASSWORD_RESET_TOKEN_TTL_MINUTES = 30
SESSION_COOKIE_NAME = "pupswipe_session"
SESSION_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
DEFAULT_SESSION_SECRET = "pupswipe-dev-session-secret-change-me"
DEFAULT_PUPSWIPE_SOURCES = ("paws_chicago", "wright_way", "anti_cruelty")
PROVIDER_DISCLAIMER = (
    "PuppyPing is not affiliated with any dog rescue, shelter, breeder, "
    "or adoption provider."
)


def get_pupswipe_sources() -> tuple[str, ...]:
    """Return feed sources for PupSwipe from env, with sensible defaults."""
    raw = os.environ.get("PUPSWIPE_SOURCES", ",".join(DEFAULT_PUPSWIPE_SOURCES))
    parsed = [item.strip() for item in raw.split(",") if item.strip()]
    deduped = tuple(dict.fromkeys(parsed))
    return deduped or DEFAULT_PUPSWIPE_SOURCES


def require_session_secret() -> str:
    """Return a configured cookie-signing secret or raise."""
    secret = os.environ.get("PUPSWIPE_SESSION_SECRET", "").strip()
    if not secret or secret == DEFAULT_SESSION_SECRET:
        raise ValueError(
            "PUPSWIPE_SESSION_SECRET must be set to a non-default value before "
            "starting PupSwipe."
        )
    return secret


def get_public_base_url() -> str:
    """Return the configured public PupSwipe base URL or raise."""
    raw = os.environ.get("PUPSWIPE_PUBLIC_URL", "").strip()
    if not raw:
        raise ValueError("PUPSWIPE_PUBLIC_URL must be set before starting PupSwipe.")

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("PUPSWIPE_PUBLIC_URL must be an absolute http(s) URL.")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError(
            "PUPSWIPE_PUBLIC_URL must not include params, query, or fragment."
        )
    return raw.rstrip("/")


def build_public_url(path: str) -> str:
    """Build an absolute public URL from a site-relative path."""
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{get_public_base_url()}{normalized_path}"


def validate_runtime_config() -> None:
    """Validate required runtime configuration for PupSwipe startup."""
    require_session_secret()
    get_public_base_url()


def provider_name(source: str | None, profile_url: str | None = None) -> str:
    """Return a human-readable provider label for a profile."""
    if source == "paws_chicago":
        return "PAWS Chicago"
    if source == "wright_way":
        return "Wright-Way Rescue"
    if source == "anti_cruelty":
        return "Anti-Cruelty"

    url = (profile_url or "").lower()
    if "pawschicago.org" in url:
        return "PAWS Chicago"
    if "petango.com" in url or "wright-wayrescue.org" in url:
        return "Wright-Way Rescue"
    if "anticruelty.org" in url or "shelterluv.com/embed/animal/acil-" in url:
        return "Anti-Cruelty"
    return "Adoption Provider"
