"""Server-rendered PupSwipe application.

This module provides a minimal HTTP server for browsing adoptable dogs,
recording swipe actions, and exposing health/data APIs backed by Postgres.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import random
from datetime import datetime
from html import escape
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from puppyping.db import add_email_subscriber, get_connection
from puppyping.email_utils import is_valid_email, normalize_email
import puppyping.pupswipe.pages as pages
from puppyping.pupswipe.auth import (
    decode_session_value,
    encode_session_value,
    hash_password,
    new_password_error,
    normalize_next_path,
    password_error,
    password_reset_error,
    password_reset_token_hash,
    session_secret,
    send_password_reset_email,
    verify_password,
)
from puppyping.pupswipe.config import (
    APP_DIR,
    DEFAULT_LIMIT,
    MAX_BREED_FILTER_LENGTH,
    MAX_LIMIT,
    MAX_NAME_FILTER_LENGTH,
    MAX_PUPPY_AGE_MONTHS,
    PAGE_SIZE,
    PASSWORD_MIN_LENGTH,
    PROVIDER_DISCLAIMER,
    SESSION_COOKIE_MAX_AGE_SECONDS,
    SESSION_COOKIE_NAME,
    get_pupswipe_sources,
    provider_name,
)
from puppyping.pupswipe.repository import (
    count_passed_puppies as repo_count_passed_puppies,
    consume_password_reset_token as repo_consume_password_reset_token,
    delete_liked_pet as repo_delete_liked_pet,
    delete_liked_puppies as repo_delete_liked_puppies,
    count_puppies as repo_count_puppies,
    count_unseen_puppies as repo_count_unseen_puppies,
    count_liked_puppies as repo_count_liked_puppies,
    create_password_reset_token as repo_create_password_reset_token,
    ensure_app_schema as repo_ensure_app_schema,
    fetch_puppies as repo_fetch_puppies,
    fetch_liked_puppies as repo_fetch_liked_puppies,
    get_user_by_id as repo_get_user_by_id,
    get_user_for_password_reset as repo_get_user_for_password_reset,
    is_password_reset_token_valid as repo_is_password_reset_token_valid,
    store_swipe as repo_store_swipe,
    update_user_password as repo_update_user_password,
    upsert_user as repo_upsert_user,
)


_get_pupswipe_sources = get_pupswipe_sources
_provider_name = provider_name
PUPSWIPE_SOURCES = _get_pupswipe_sources()
_ensure_app_schema = repo_ensure_app_schema

MAX_SPECIES_FILTER_LENGTH = 40
MIN_MAX_AGE_MONTHS = 0.5
MAX_MAX_AGE_MONTHS = 120.0
FILTER_COOKIE_NAME = "pupswipe_filters"


def _normalize_breed_filter(value: str | None) -> str:
    """Normalize user-entered breed filter text."""
    text = " ".join((value or "").split()).strip()
    if not text:
        return ""
    return text[:MAX_BREED_FILTER_LENGTH]


def _normalize_name_filter(value: str | None) -> str:
    """Normalize user-entered name filter text."""
    text = " ".join((value or "").split()).strip()
    if not text:
        return ""
    return text[:MAX_NAME_FILTER_LENGTH]


def _normalize_provider_filter(value: str | None) -> str:
    """Normalize provider filter text to known source keys."""
    candidate = (value or "").strip()
    if not candidate:
        return ""
    if candidate in PUPSWIPE_SOURCES:
        return candidate
    return ""


def _normalize_species_filter(value: str | None) -> str:
    """Normalize species filter text."""
    text = " ".join((value or "").split()).strip().lower()
    if not text:
        return ""
    return text[:MAX_SPECIES_FILTER_LENGTH]


def _normalize_max_age_filter(
    value,
    default: float = MAX_PUPPY_AGE_MONTHS,
) -> float:
    """Normalize age filter to a bounded positive month value."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    return max(MIN_MAX_AGE_MONTHS, min(MAX_MAX_AGE_MONTHS, parsed))


def _normalized_filter_payload(
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
) -> dict[str, str | float]:
    """Build canonical normalized filter payload."""
    return {
        "breed": _normalize_breed_filter(breed_filter),
        "name": _normalize_name_filter(name_filter),
        "provider": _normalize_provider_filter(provider_filter),
        "species": _normalize_species_filter(species_filter),
        "max_age": _normalize_max_age_filter(max_age_months),
    }


def _has_active_filters(payload: dict[str, str | float]) -> bool:
    """Return True when payload has at least one non-default filter value."""
    return bool(
        str(payload.get("breed") or "").strip()
        or str(payload.get("name") or "").strip()
        or str(payload.get("provider") or "").strip()
        or str(payload.get("species") or "").strip()
        or float(payload.get("max_age") or MAX_PUPPY_AGE_MONTHS) != MAX_PUPPY_AGE_MONTHS
    )


def _filter_hash(payload: dict[str, str | float]) -> str:
    """Create short stable hash identifier for a filter payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _encode_filter_cookie_value(payload: dict[str, str | float]) -> str:
    """Encode signed cookie value containing normalized filter payload."""
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    encoded = base64.urlsafe_b64encode(canonical_json).decode("ascii").rstrip("=")
    signature = hmac.new(
        session_secret().encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def _decode_filter_cookie_value(raw_value: str | None) -> dict[str, str | float] | None:
    """Decode and verify signed filter cookie payload."""
    value = (raw_value or "").strip()
    if "." not in value:
        return None
    encoded, signature = value.split(".", 1)
    expected = hmac.new(
        session_secret().encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        parsed = json.loads(decoded)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return _normalized_filter_payload(
        breed_filter=str(parsed.get("breed") or ""),
        name_filter=str(parsed.get("name") or ""),
        provider_filter=str(parsed.get("provider") or ""),
        species_filter=str(parsed.get("species") or ""),
        max_age_months=parsed.get("max_age", MAX_PUPPY_AGE_MONTHS),
    )


def _filter_hidden_inputs(
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
    filter_hash: str = "",
    review_mode: str = "",
) -> str:
    """Render hidden form inputs for currently active filters."""
    hidden_inputs: list[str] = []
    normalized_payload = _normalized_filter_payload(
        breed_filter=breed_filter,
        name_filter=name_filter,
        provider_filter=provider_filter,
        species_filter=species_filter,
        max_age_months=max_age_months,
    )
    active_hash = (filter_hash or "").strip()
    if not active_hash and _has_active_filters(normalized_payload):
        active_hash = _filter_hash(normalized_payload)
    if active_hash:
        hidden_inputs.append(f'<input type="hidden" name="f" value="{escape(active_hash)}" />')
    if (review_mode or "").strip().lower() == "passed":
        hidden_inputs.append('<input type="hidden" name="review" value="passed" />')
    return "\n            ".join(hidden_inputs)


def _add_active_filters(
    query_params: dict[str, str],
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
    filter_hash: str = "",
    review_mode: str = "",
) -> dict[str, str]:
    """Attach non-empty filters to query params for redirects/links."""
    active_hash = (filter_hash or "").strip()
    if not active_hash:
        normalized_payload = _normalized_filter_payload(
            breed_filter=breed_filter,
            name_filter=name_filter,
            provider_filter=provider_filter,
            species_filter=species_filter,
            max_age_months=max_age_months,
        )
        if _has_active_filters(normalized_payload):
            active_hash = _filter_hash(normalized_payload)
    if active_hash:
        query_params["f"] = active_hash
    if (review_mode or "").strip().lower() == "passed":
        query_params["review"] = "passed"
    return query_params


def _fetch_puppies(
    limit: int,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
    *,
    viewer_user_id: int | None = None,
    viewer_user_key: str | None = None,
    randomize: bool = False,
    review_passed: bool = False,
) -> list[dict]:
    """Load the latest available dog profiles ordered by recency."""
    return repo_fetch_puppies(
        limit,
        breed_filter=breed_filter,
        name_filter=name_filter,
        provider_filter=provider_filter,
        species_filter=species_filter,
        max_age_months=max_age_months,
        viewer_user_id=viewer_user_id,
        viewer_user_key=viewer_user_key,
        randomize=randomize,
        review_passed=review_passed,
        sources=PUPSWIPE_SOURCES,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _count_puppies(
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
) -> int:
    """Count latest dog profiles that are currently available."""
    return repo_count_puppies(
        breed_filter=breed_filter,
        name_filter=name_filter,
        provider_filter=provider_filter,
        species_filter=species_filter,
        max_age_months=max_age_months,
        sources=PUPSWIPE_SOURCES,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _count_unseen_puppies(
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
    *,
    viewer_user_id: int | None = None,
    viewer_user_key: str | None = None,
) -> int:
    """Count available profiles not yet swiped by this viewer context."""
    if viewer_user_id is None and not (viewer_user_key or "").strip():
        return _count_puppies(
            breed_filter=breed_filter,
            name_filter=name_filter,
            provider_filter=provider_filter,
            species_filter=species_filter,
            max_age_months=max_age_months,
        )
    return repo_count_unseen_puppies(
        breed_filter=breed_filter,
        name_filter=name_filter,
        provider_filter=provider_filter,
        species_filter=species_filter,
        max_age_months=max_age_months,
        viewer_user_id=viewer_user_id,
        viewer_user_key=viewer_user_key,
        sources=PUPSWIPE_SOURCES,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _count_passed_puppies(
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
    *,
    viewer_user_id: int | None = None,
    viewer_user_key: str | None = None,
) -> int:
    """Count available profiles whose latest swipe for this viewer was pass."""
    return repo_count_passed_puppies(
        breed_filter=breed_filter,
        name_filter=name_filter,
        provider_filter=provider_filter,
        species_filter=species_filter,
        max_age_months=max_age_months,
        viewer_user_id=viewer_user_id,
        viewer_user_key=viewer_user_key,
        sources=PUPSWIPE_SOURCES,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _store_swipe(
    dog_id: int,
    swipe: str,
    species: str | None = None,
    source: str | None = None,
    user_id: int | None = None,
    user_key: str | None = None,
    user_ip: str | None = None,
    user_agent: str | None = None,
    accept_language: str | None = None,
    screen_info: dict | None = None,
) -> None:
    """Persist a swipe event for a dog."""
    repo_store_swipe(
        dog_id=dog_id,
        species=species,
        swipe=swipe,
        source=source,
        user_id=user_id,
        user_key=user_key,
        user_ip=user_ip,
        user_agent=user_agent,
        accept_language=accept_language,
        screen_info=screen_info,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _safe_int(value: str | None, default: int = 0) -> int:
    """Safely parse a non-negative integer from text.

    Args:
        value: Input value to parse.
        default: Fallback value when parsing fails.

    Returns:
        A non-negative integer.
    """
    try:
        return max(0, int(value or default))
    except (TypeError, ValueError):
        return default


def _normalize_email(email: str | None) -> str:
    """Normalize an email address for storage and comparisons.

    Args:
        email: Raw email input.

    Returns:
        Lower-cased, trimmed email string.
    """
    return normalize_email(email)


def _is_valid_email(email: str) -> bool:
    """Validate an email address with a pragmatic syntax check.

    Args:
        email: Normalized email address.

    Returns:
        ``True`` when the email looks valid, otherwise ``False``.
    """
    return is_valid_email(email)


_password_error = password_error
_new_password_error = new_password_error
_password_reset_error = password_reset_error
_hash_password = hash_password
_verify_password = verify_password
_password_reset_token_hash = password_reset_token_hash
_send_password_reset_email = send_password_reset_email
_normalize_next_path = normalize_next_path
_encode_session_value = encode_session_value
_decode_session_value = decode_session_value


def _get_user_for_password_reset(email: str) -> dict | None:
    """Load minimal user fields needed to issue a password reset."""
    return repo_get_user_for_password_reset(
        email,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _create_password_reset_token(user_id: int) -> tuple[str, datetime]:
    """Create and persist a one-time password-reset token."""
    return repo_create_password_reset_token(
        user_id,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _consume_password_reset_token(
    token: str,
    new_password: str,
) -> int:
    """Consume reset token and update user password.

    Returns:
        The user id whose password was updated.
    """
    return repo_consume_password_reset_token(
        token,
        new_password,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _is_password_reset_token_valid(token: str) -> bool:
    """Check whether reset token exists, is unused, and not expired."""
    return repo_is_password_reset_token_valid(
        token,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _upsert_user(email: str, password: str) -> dict:
    """Create or authenticate a user row keyed by email."""
    return repo_upsert_user(
        email,
        password,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _get_user_by_id(user_id: int) -> dict | None:
    """Load a user row by id and update last-seen timestamp."""
    return repo_get_user_by_id(
        user_id,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _update_user_password(user_id: int, current_password: str, new_password: str) -> None:
    """Verify current password and replace it with a new password hash."""
    repo_update_user_password(
        user_id,
        current_password,
        new_password,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _count_liked_puppies(
    user_id: int,
    name_filter: str = "",
    breed_filter: str = "",
    species_filter: str = "",
    provider_filter: str = "",
) -> int:
    """Count likes for a given user."""
    return repo_count_liked_puppies(
        user_id,
        name_filter=name_filter,
        breed_filter=breed_filter,
        species_filter=species_filter,
        provider_filter=provider_filter,
        sources=PUPSWIPE_SOURCES,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _fetch_liked_puppies(
    user_id: int,
    limit: int = 120,
    offset: int = 0,
    name_filter: str = "",
    breed_filter: str = "",
    species_filter: str = "",
    provider_filter: str = "",
) -> list[dict]:
    """Load a user's liked puppies ordered by most recently liked."""
    return repo_fetch_liked_puppies(
        user_id=user_id,
        limit=limit,
        offset=offset,
        name_filter=name_filter,
        breed_filter=breed_filter,
        species_filter=species_filter,
        provider_filter=provider_filter,
        sources=PUPSWIPE_SOURCES,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _remove_liked_pet(
    user_id: int,
    pet_id: int,
    species: str = "",
) -> int:
    """Remove a single liked pet for a user."""
    return repo_delete_liked_pet(
        user_id=user_id,
        pet_id=pet_id,
        species=species,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _remove_liked_puppies(
    user_id: int,
    *,
    name_filter: str = "",
    breed_filter: str = "",
    species_filter: str = "",
    provider_filter: str = "",
    only_unavailable: bool = False,
) -> int:
    """Bulk-remove liked pets for a user."""
    return repo_delete_liked_puppies(
        user_id=user_id,
        name_filter=name_filter,
        breed_filter=breed_filter,
        species_filter=species_filter,
        provider_filter=provider_filter,
        only_unavailable=only_unavailable,
        sources=PUPSWIPE_SOURCES,
        connection_factory=get_connection,
        ensure_schema_fn=_ensure_app_schema,
    )


def _sync_page_context() -> None:
    """Bind server-level dependencies into the pages module."""
    pages.random = random
    pages._normalize_breed_filter = _normalize_breed_filter
    pages._normalize_name_filter = _normalize_name_filter
    pages._normalize_provider_filter = _normalize_provider_filter
    pages._normalize_species_filter = _normalize_species_filter
    pages._normalize_max_age_filter = _normalize_max_age_filter
    pages._filter_hidden_inputs = _filter_hidden_inputs
    pages._count_puppies = _count_puppies
    pages._count_unseen_puppies = _count_unseen_puppies
    pages._count_passed_puppies = _count_passed_puppies
    pages._fetch_puppies = _fetch_puppies
    pages._provider_name = _provider_name
    pages._safe_int = _safe_int
    pages._normalize_next_path = _normalize_next_path
    pages.PUPSWIPE_SOURCES = PUPSWIPE_SOURCES
    pages.PAGE_SIZE = PAGE_SIZE
    pages.MAX_PUPPY_AGE_MONTHS = MAX_PUPPY_AGE_MONTHS
    pages.MAX_BREED_FILTER_LENGTH = MAX_BREED_FILTER_LENGTH
    pages.MAX_NAME_FILTER_LENGTH = MAX_NAME_FILTER_LENGTH
    pages.PASSWORD_MIN_LENGTH = PASSWORD_MIN_LENGTH
    pages.PROVIDER_DISCLAIMER = PROVIDER_DISCLAIMER


def _get_primary_image(pup: dict) -> str | None:
    return pages._get_primary_image(pup)


def _get_photo_urls(pup: dict) -> list[str]:
    return pages._get_photo_urls(pup)


def _render_page(
    message: str | None = None,
    photo_index: int = 0,
    randomize: bool = False,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = MAX_PUPPY_AGE_MONTHS,
    signed_in_email: str | None = None,
    viewer_user_id: int | None = None,
    viewer_user_key: str | None = None,
    review_passed: bool = False,
) -> bytes:
    _sync_page_context()
    return pages._render_page(
        message=message,
        photo_index=photo_index,
        randomize=randomize,
        breed_filter=breed_filter,
        name_filter=name_filter,
        provider_filter=provider_filter,
        species_filter=species_filter,
        max_age_months=max_age_months,
        signed_in_email=signed_in_email,
        viewer_user_id=viewer_user_id,
        viewer_user_key=viewer_user_key,
        review_passed=review_passed,
    )


def _render_signin_page(
    message: str | None = None,
    next_path: str = "/likes",
    email_value: str = "",
    signed_in_email: str | None = None,
) -> bytes:
    _sync_page_context()
    return pages._render_signin_page(
        message=message,
        next_path=next_path,
        email_value=email_value,
        signed_in_email=signed_in_email,
    )


def _render_forgot_password_page(
    message: str | None = None,
    email_value: str = "",
) -> bytes:
    _sync_page_context()
    return pages._render_forgot_password_page(
        message=message,
        email_value=email_value,
    )


def _render_forgot_password_reset_page(
    token: str,
    message: str | None = None,
) -> bytes:
    _sync_page_context()
    return pages._render_forgot_password_reset_page(
        token=token,
        message=message,
    )


def _render_reset_password_page(
    signed_in_email: str,
    message: str | None = None,
) -> bytes:
    _sync_page_context()
    return pages._render_reset_password_page(
        signed_in_email=signed_in_email,
        message=message,
    )


def _format_liked_time(value) -> str:
    return pages._format_liked_time(value)


def _render_likes_page(
    email: str,
    puppies: list[dict],
    total_likes: int,
    filtered_likes: int | None = None,
    name_filter: str = "",
    breed_filter: str = "",
    species_filter: str = "",
    provider_filter: str = "",
    message: str | None = None,
) -> bytes:
    _sync_page_context()
    return pages._render_likes_page(
        email=email,
        puppies=puppies,
        total_likes=total_likes,
        filtered_likes=filtered_likes,
        name_filter=name_filter,
        breed_filter=breed_filter,
        species_filter=species_filter,
        provider_filter=provider_filter,
        message=message,
    )

class AppHandler(SimpleHTTPRequestHandler):
    """HTTP handler for PupSwipe API and server-rendered pages."""

    def __init__(self, *args, **kwargs):
        """Initialize the handler with the app directory as static root.

        Args:
            *args: Positional arguments passed to the base handler.
            **kwargs: Keyword arguments passed to the base handler.
        """
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def end_headers(self):
        """Attach client hint headers before completing the response.

        Returns:
            None.
        """
        self.send_header(
            "Accept-CH",
            "Viewport-Width, Sec-CH-Viewport-Width, Width, DPR, Sec-CH-UA, Sec-CH-UA-Platform, Sec-CH-UA-Mobile",
        )
        super().end_headers()

    def _send_json(self, status: int, payload: dict) -> None:
        """Write a JSON response.

        Args:
            status: HTTP status code.
            payload: JSON-serializable response payload.

        Returns:
            None.
        """
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, status: int, body: bytes) -> None:
        """Write an HTML response."""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _public_base_url(self) -> str:
        """Resolve the externally reachable base URL for email links."""
        configured = os.environ.get("PUPSWIPE_PUBLIC_URL", "").strip()
        if configured:
            return configured.rstrip("/")
        proto = (self._first_header("X-Forwarded-Proto") or "http").strip().lower()
        if proto not in {"http", "https"}:
            proto = "http"
        host = (self._first_header("X-Forwarded-Host", "Host") or "").strip()
        if not host:
            host = "127.0.0.1:8000"
        return f"{proto}://{host}"

    def _absolute_url(self, path: str) -> str:
        """Build an absolute URL from a site-relative path."""
        return f"{self._public_base_url()}{path}"

    def _session_cookie_header(self, user_id: int) -> str:
        """Build Set-Cookie header value for a signed-in session."""
        parts = [
            f"{SESSION_COOKIE_NAME}={_encode_session_value(user_id)}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={SESSION_COOKIE_MAX_AGE_SECONDS}",
        ]
        forwarded_proto = (self._first_header("X-Forwarded-Proto") or "").lower()
        if forwarded_proto == "https":
            parts.append("Secure")
        return "; ".join(parts)

    def _filter_cookie_header(self, payload: dict[str, str | float]) -> str:
        """Build Set-Cookie header for persisted filter state."""
        parts = [
            f"{FILTER_COOKIE_NAME}={_encode_filter_cookie_value(payload)}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={SESSION_COOKIE_MAX_AGE_SECONDS}",
        ]
        forwarded_proto = (self._first_header("X-Forwarded-Proto") or "").lower()
        if forwarded_proto == "https":
            parts.append("Secure")
        return "; ".join(parts)

    @staticmethod
    def _clear_session_cookie_header() -> str:
        """Build Set-Cookie header value for clearing session cookie."""
        return (
            f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; "
            "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
        )

    @staticmethod
    def _clear_filter_cookie_header() -> str:
        """Build Set-Cookie header value for clearing filter cookie."""
        return (
            f"{FILTER_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; "
            "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
        )

    def _cookie_value(self, key: str) -> str | None:
        """Read a cookie value by key from request headers."""
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return None
        morsel = jar.get(key)
        return morsel.value if morsel else None

    def _signed_in_user(self) -> dict | None:
        """Resolve signed-in user from session cookie."""
        user_id = _decode_session_value(self._cookie_value(SESSION_COOKIE_NAME))
        if user_id is None:
            return None
        try:
            return _get_user_by_id(user_id)
        except Exception:
            return None

    def _filter_state_from_cookie(self) -> dict[str, str | float]:
        """Read normalized filter state from signed filter cookie."""
        decoded = _decode_filter_cookie_value(self._cookie_value(FILTER_COOKIE_NAME))
        if decoded:
            return decoded
        return _normalized_filter_payload()

    def _first_header(self, *names: str) -> str | None:
        """Return the first non-empty header value from a list of names.

        Args:
            *names: Candidate header names to inspect in order.

        Returns:
            The stripped header value if found, otherwise ``None``.
        """
        for name in names:
            value = self.headers.get(name)
            if value:
                return value.strip()
        return None

    def _client_ip(self) -> str | None:
        """Resolve the most likely client IP.

        Returns:
            The client IP address if available, otherwise ``None``.
        """
        forwarded = self._first_header(
            "X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP"
        )
        if forwarded:
            return forwarded.split(",")[0].strip()
        if self.client_address:
            return self.client_address[0]
        return None

    def _screen_info(self, payload: dict | None = None) -> dict | None:
        """Build screen/client-hint metadata from headers and optional payload.

        Args:
            payload: Optional request payload containing client screen values.

        Returns:
            A metadata dictionary, or ``None`` when no values are available.
        """
        info: dict[str, str | int | float | bool] = {}
        header_map = {
            "viewport_width": ("Viewport-Width", "Sec-CH-Viewport-Width", "Width"),
            "pixel_ratio": ("DPR",),
            "ua_platform": ("Sec-CH-UA-Platform",),
            "ua_mobile": ("Sec-CH-UA-Mobile",),
            "ua_hint": ("Sec-CH-UA",),
            "device_memory": ("Device-Memory",),
        }
        for key, names in header_map.items():
            value = self._first_header(*names)
            if value:
                info[key] = value

        if isinstance(payload, dict):
            screen_payload = payload.get("screen_info")
            if isinstance(screen_payload, dict):
                for key, value in screen_payload.items():
                    if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                        info[f"client_{key}"] = value

            for key in (
                "screen_width",
                "screen_height",
                "viewport_width",
                "viewport_height",
                "pixel_ratio",
            ):
                value = payload.get(key)
                if isinstance(value, (str, int, float, bool)):
                    info[f"client_{key}"] = value

        return info or None

    def _user_context(self, payload: dict | None = None) -> dict:
        """Build user context fields used for swipe analytics.

        Args:
            payload: Optional body/form payload.

        Returns:
            A dictionary containing user fingerprint and client metadata.
        """
        user_ip = self._client_ip()
        user_agent = self._first_header("User-Agent")
        accept_language = self._first_header("Accept-Language")
        screen_info = self._screen_info(payload)

        fingerprint_input = "|".join(
            [
                user_ip or "",
                user_agent or "",
                json.dumps(screen_info, sort_keys=True) if screen_info else "",
            ]
        )
        user_key = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()[:32]
        return {
            "user_key": user_key,
            "user_ip": user_ip,
            "user_agent": user_agent,
            "accept_language": accept_language,
            "screen_info": screen_info,
        }

    def do_GET(self):
        """Handle GET requests for APIs, root page, and static assets.

        Returns:
            None.
        """
        parsed = urlparse(self.path)
        if parsed.path == "/api/puppies":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", [DEFAULT_LIMIT])[0])
            except ValueError:
                return self._send_json(400, {"error": "limit must be an integer"})
            limit = max(1, min(MAX_LIMIT, limit))
            breed_filter = _normalize_breed_filter(query.get("breed", [""])[0])
            name_filter = _normalize_name_filter(query.get("name", [""])[0])
            provider_filter = _normalize_provider_filter(query.get("provider", [""])[0])
            species_filter = _normalize_species_filter(query.get("species", [""])[0])
            max_age_months = _normalize_max_age_filter(
                query.get("max_age", [str(MAX_PUPPY_AGE_MONTHS)])[0]
            )
            try:
                puppies = _fetch_puppies(
                    limit,
                    breed_filter=breed_filter,
                    name_filter=name_filter,
                    provider_filter=provider_filter,
                    species_filter=species_filter,
                    max_age_months=max_age_months,
                )
            except Exception as exc:
                return self._send_json(
                    500,
                    {"error": "failed to load puppies", "detail": str(exc)},
                )
            return self._send_json(
                200, {"items": puppies, "count": len(puppies)}
            )

        if parsed.path == "/api/health":
            try:
                _fetch_puppies(1)
                return self._send_json(200, {"ok": True})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "detail": str(exc)})

        if parsed.path == "/forgot-password":
            query = parse_qs(parsed.query)
            message = query.get("msg", [None])[0]
            email_value = " ".join(query.get("email", [""])[0].split()).strip()
            body = _render_forgot_password_page(
                message=message,
                email_value=email_value,
            )
            return self._send_html(200, body)

        if parsed.path == "/forgot-password/reset":
            query = parse_qs(parsed.query)
            token = query.get("token", [""])[0].strip()
            message = query.get("msg", [None])[0]
            if not token:
                msg_query = urlencode({"msg": "Invalid reset link."})
                self.send_response(303)
                self.send_header("Location", f"/forgot-password?{msg_query}")
                self.end_headers()
                return
            try:
                is_valid = _is_password_reset_token_valid(token)
            except Exception:
                is_valid = False
            if not is_valid:
                msg_query = urlencode({"msg": "Reset link is invalid or expired."})
                self.send_response(303)
                self.send_header("Location", f"/forgot-password?{msg_query}")
                self.end_headers()
                return
            body = _render_forgot_password_reset_page(token=token, message=message)
            return self._send_html(200, body)

        if parsed.path == "/signin":
            query = parse_qs(parsed.query)
            message = query.get("msg", [None])[0]
            next_path = _normalize_next_path(query.get("next", ["/likes"])[0], "/likes")
            email_value = " ".join(query.get("email", [""])[0].split()).strip()
            current_user = self._signed_in_user()
            body = _render_signin_page(
                message=message,
                next_path=next_path,
                email_value=email_value,
                signed_in_email=str(current_user.get("email") or "") if current_user else None,
            )
            return self._send_html(200, body)

        if parsed.path == "/likes":
            current_user = self._signed_in_user()
            if not current_user:
                query = urlencode(
                    {"next": "/likes", "msg": "Sign in to view liked puppies."}
                )
                self.send_response(303)
                self.send_header("Location", f"/signin?{query}")
                self.end_headers()
                return
            likes_query = parse_qs(parsed.query)
            message = likes_query.get("msg", [None])[0]
            name_filter = _normalize_name_filter(likes_query.get("name", [""])[0])
            breed_filter = _normalize_breed_filter(likes_query.get("breed", [""])[0])
            species_filter = _normalize_species_filter(likes_query.get("species", [""])[0])
            provider_filter = _normalize_provider_filter(likes_query.get("provider", [""])[0])
            try:
                user_id = _safe_int(str(current_user.get("id")), 0)
                if user_id <= 0:
                    raise ValueError("invalid user id")
                total_likes = _count_liked_puppies(user_id)
                filtered_likes = _count_liked_puppies(
                    user_id,
                    name_filter=name_filter,
                    breed_filter=breed_filter,
                    species_filter=species_filter,
                    provider_filter=provider_filter,
                )
                puppies = _fetch_liked_puppies(
                    user_id=user_id,
                    limit=120,
                    name_filter=name_filter,
                    breed_filter=breed_filter,
                    species_filter=species_filter,
                    provider_filter=provider_filter,
                )
            except Exception as exc:
                body = _render_likes_page(
                    email=str(current_user.get("email") or ""),
                    puppies=[],
                    total_likes=0,
                    filtered_likes=0,
                    name_filter=name_filter,
                    breed_filter=breed_filter,
                    species_filter=species_filter,
                    provider_filter=provider_filter,
                    message=f"Failed to load liked puppies: {exc}",
                )
                return self._send_html(200, body)

            body = _render_likes_page(
                email=str(current_user.get("email") or ""),
                puppies=puppies,
                total_likes=total_likes,
                filtered_likes=filtered_likes,
                name_filter=name_filter,
                breed_filter=breed_filter,
                species_filter=species_filter,
                provider_filter=provider_filter,
                message=message,
            )
            return self._send_html(200, body)

        if parsed.path == "/reset-password":
            current_user = self._signed_in_user()
            if not current_user:
                query = urlencode(
                    {"next": "/reset-password", "msg": "Sign in to reset password."}
                )
                self.send_response(303)
                self.send_header("Location", f"/signin?{query}")
                self.end_headers()
                return
            message = parse_qs(parsed.query).get("msg", [None])[0]
            body = _render_reset_password_page(
                signed_in_email=str(current_user.get("email") or ""),
                message=message,
            )
            return self._send_html(200, body)

        if parsed.path == "/" or parsed.path == "/index.html":
            query = parse_qs(parsed.query)
            photo_index = _safe_int(query.get("photo", ["0"])[0], 0)
            review_mode = (
                "passed"
                if query.get("review", [""])[0].strip().lower() == "passed"
                else ""
            )
            randomize = query.get("random", ["0"])[0].strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            msg = query.get("msg", [None])[0]
            clear_filters = query.get("clear_filters", ["0"])[0].strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            raw_filters_present = any(
                key in query for key in ("breed", "name", "provider", "species", "max_age")
            )

            if clear_filters:
                location = "/?review=passed" if review_mode == "passed" else "/"
                self.send_response(303)
                self.send_header("Set-Cookie", self._clear_filter_cookie_header())
                self.send_header("Location", location)
                self.end_headers()
                return

            if raw_filters_present:
                normalized_payload = _normalized_filter_payload(
                    breed_filter=query.get("breed", [""])[0],
                    name_filter=query.get("name", [""])[0],
                    provider_filter=query.get("provider", [""])[0],
                    species_filter=query.get("species", [""])[0],
                    max_age_months=query.get("max_age", [str(MAX_PUPPY_AGE_MONTHS)])[0],
                )
                redirect_params: dict[str, str] = {}
                if photo_index > 0:
                    redirect_params["photo"] = str(photo_index)
                if randomize:
                    redirect_params["random"] = "1"
                if msg:
                    redirect_params["msg"] = msg
                redirect_params = _add_active_filters(
                    redirect_params,
                    breed_filter=str(normalized_payload.get("breed") or ""),
                    name_filter=str(normalized_payload.get("name") or ""),
                    provider_filter=str(normalized_payload.get("provider") or ""),
                    species_filter=str(normalized_payload.get("species") or ""),
                    max_age_months=float(
                        normalized_payload.get("max_age") or MAX_PUPPY_AGE_MONTHS
                    ),
                    review_mode=review_mode,
                )
                location = "/" if not redirect_params else f"/?{urlencode(redirect_params)}"
                self.send_response(303)
                self.send_header("Set-Cookie", self._filter_cookie_header(normalized_payload))
                self.send_header("Location", location)
                self.end_headers()
                return

            filter_state = self._filter_state_from_cookie()
            breed_filter = str(filter_state.get("breed") or "")
            name_filter = str(filter_state.get("name") or "")
            provider_filter = str(filter_state.get("provider") or "")
            species_filter = str(filter_state.get("species") or "")
            max_age_months = float(filter_state.get("max_age") or MAX_PUPPY_AGE_MONTHS)
            current_user = self._signed_in_user()
            current_user_id = _safe_int(str(current_user.get("id")), 0) if current_user else 0
            viewer_context = self._user_context()
            viewer_user_key = (
                str(viewer_context.get("user_key") or "")
                if current_user_id <= 0
                else ""
            )
            body = _render_page(
                message=msg,
                photo_index=photo_index,
                randomize=randomize,
                breed_filter=breed_filter,
                name_filter=name_filter,
                provider_filter=provider_filter,
                species_filter=species_filter,
                max_age_months=max_age_months,
                signed_in_email=(
                    str(current_user.get("email") or "") if current_user else None
                ),
                viewer_user_id=current_user_id if current_user_id > 0 else None,
                viewer_user_key=viewer_user_key,
                review_passed=(review_mode == "passed"),
            )
            return self._send_html(200, body)

        return super().do_GET()

    def do_POST(self):
        """Handle POST requests for subscriptions, swipes, and API writes.

        Returns:
            None.
        """
        parsed = urlparse(self.path)
        if parsed.path == "/forgot-password":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)
            email_raw = form.get("email", [""])[0]
            email = _normalize_email(email_raw)
            if not _is_valid_email(email):
                query = urlencode(
                    {
                        "msg": "Enter a valid email address.",
                        "email": " ".join(str(email_raw).split()).strip(),
                    }
                )
                self.send_response(303)
                self.send_header("Location", f"/forgot-password?{query}")
                self.end_headers()
                return

            # Avoid account enumeration: response is always generic.
            generic_msg = (
                f"If an account exists for {email}, a reset link has been sent."
            )
            try:
                user = _get_user_for_password_reset(email)
                if user:
                    user_id = _safe_int(str(user.get("id")), 0)
                    if user_id > 0:
                        token, _expires = _create_password_reset_token(user_id)
                        reset_query = urlencode({"token": token})
                        reset_link = self._absolute_url(f"/forgot-password/reset?{reset_query}")
                        _send_password_reset_email(email, reset_link)
            except Exception:
                # Intentionally suppress details to prevent user enumeration.
                pass

            query = urlencode({"msg": generic_msg, "email": email})
            self.send_response(303)
            self.send_header("Location", f"/signin?{query}")
            self.end_headers()
            return

        if parsed.path == "/forgot-password/reset":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)
            token = form.get("token", [""])[0].strip()
            new_password = form.get("new_password", [""])[0]
            confirm_password = form.get("confirm_password", [""])[0]
            if not token:
                query = urlencode({"msg": "Invalid reset link."})
                self.send_response(303)
                self.send_header("Location", f"/forgot-password?{query}")
                self.end_headers()
                return

            validation_error = _new_password_error(new_password, confirm_password)
            if validation_error:
                query = urlencode({"token": token, "msg": validation_error})
                self.send_response(303)
                self.send_header("Location", f"/forgot-password/reset?{query}")
                self.end_headers()
                return

            try:
                _consume_password_reset_token(token, new_password)
            except Exception as exc:
                query = urlencode({"msg": f"Password reset failed: {exc}"})
                self.send_response(303)
                self.send_header("Location", f"/forgot-password?{query}")
                self.end_headers()
                return

            query = urlencode({"msg": "Password updated. Sign in with your new password."})
            self.send_response(303)
            self.send_header("Location", f"/signin?{query}")
            self.end_headers()
            return

        if parsed.path == "/signin":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)

            email_raw = form.get("email", [""])[0]
            email = _normalize_email(email_raw)
            password = form.get("password", [""])[0]
            next_path = _normalize_next_path(form.get("next", ["/likes"])[0], "/likes")

            if not _is_valid_email(email):
                query = urlencode(
                    {
                        "msg": "Enter a valid email address.",
                        "next": next_path,
                        "email": " ".join(str(email_raw).split()).strip(),
                    }
                )
                self.send_response(303)
                self.send_header("Location", f"/signin?{query}")
                self.end_headers()
                return

            password_validation_error = _password_error(password)
            if password_validation_error:
                query = urlencode(
                    {
                        "msg": password_validation_error,
                        "next": next_path,
                        "email": email,
                    }
                )
                self.send_response(303)
                self.send_header("Location", f"/signin?{query}")
                self.end_headers()
                return

            try:
                user = _upsert_user(email, password)
                user_id = _safe_int(str(user.get("id")), 0)
                if user_id <= 0:
                    raise ValueError("failed to create session user")
            except Exception as exc:
                query = urlencode(
                    {
                        "msg": f"Sign-in failed: {exc}",
                        "next": next_path,
                        "email": email,
                    }
                )
                self.send_response(303)
                self.send_header("Location", f"/signin?{query}")
                self.end_headers()
                return

            self.send_response(303)
            self.send_header("Set-Cookie", self._session_cookie_header(user_id))
            self.send_header("Location", next_path)
            self.end_headers()
            return

        if parsed.path == "/signout":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)
            next_path = _normalize_next_path(form.get("next", ["/signin"])[0], "/signin")
            self.send_response(303)
            self.send_header("Set-Cookie", self._clear_session_cookie_header())
            self.send_header("Location", next_path)
            self.end_headers()
            return

        if parsed.path == "/reset-password":
            current_user = self._signed_in_user()
            if not current_user:
                query = urlencode(
                    {"next": "/reset-password", "msg": "Sign in to reset password."}
                )
                self.send_response(303)
                self.send_header("Location", f"/signin?{query}")
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)
            current_password = form.get("current_password", [""])[0]
            new_password = form.get("new_password", [""])[0]
            confirm_password = form.get("confirm_password", [""])[0]
            validation_error = _password_reset_error(
                current_password,
                new_password,
                confirm_password,
            )
            if validation_error:
                query = urlencode({"msg": validation_error})
                self.send_response(303)
                self.send_header("Location", f"/reset-password?{query}")
                self.end_headers()
                return

            user_id = _safe_int(str(current_user.get("id")), 0)
            if user_id <= 0:
                query = urlencode({"msg": "Unable to locate signed-in account."})
                self.send_response(303)
                self.send_header("Location", f"/reset-password?{query}")
                self.end_headers()
                return

            try:
                _update_user_password(user_id, current_password, new_password)
            except Exception as exc:
                query = urlencode({"msg": f"Failed to reset password: {exc}"})
                self.send_response(303)
                self.send_header("Location", f"/reset-password?{query}")
                self.end_headers()
                return

            query = urlencode({"msg": "Password updated."})
            self.send_response(303)
            self.send_header("Location", f"/likes?{query}")
            self.end_headers()
            return

        if parsed.path == "/likes/remove":
            current_user = self._signed_in_user()
            if not current_user:
                query = urlencode(
                    {"next": "/likes", "msg": "Sign in to manage liked pets."}
                )
                self.send_response(303)
                self.send_header("Location", f"/signin?{query}")
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)
            user_id = _safe_int(str(current_user.get("id")), 0)
            pet_id = _safe_int(form.get("pet_id", ["0"])[0], 0)
            pet_species = " ".join(form.get("pet_species", [""])[0].split()).strip()
            name_filter = _normalize_name_filter(form.get("name", [""])[0])
            breed_filter = _normalize_breed_filter(form.get("breed", [""])[0])
            species_filter = _normalize_species_filter(form.get("species", [""])[0])
            provider_filter = _normalize_provider_filter(form.get("provider", [""])[0])

            query_params: dict[str, str] = {}
            if name_filter:
                query_params["name"] = name_filter
            if breed_filter:
                query_params["breed"] = breed_filter
            if species_filter:
                query_params["species"] = species_filter
            if provider_filter:
                query_params["provider"] = provider_filter

            if user_id <= 0 or pet_id <= 0:
                query_params["msg"] = "Unable to remove liked pet."
                self.send_response(303)
                self.send_header("Location", f"/likes?{urlencode(query_params)}")
                self.end_headers()
                return

            try:
                removed = _remove_liked_pet(
                    user_id=user_id,
                    pet_id=pet_id,
                    species=pet_species,
                )
            except Exception as exc:
                query_params["msg"] = f"Failed to remove liked pet: {exc}"
                self.send_response(303)
                self.send_header("Location", f"/likes?{urlencode(query_params)}")
                self.end_headers()
                return

            query_params["msg"] = (
                "Removed pet from liked list."
                if removed > 0
                else "Pet was already removed from liked list."
            )
            self.send_response(303)
            self.send_header("Location", f"/likes?{urlencode(query_params)}")
            self.end_headers()
            return

        if parsed.path == "/likes/remove-all":
            current_user = self._signed_in_user()
            if not current_user:
                query = urlencode(
                    {"next": "/likes", "msg": "Sign in to manage liked pets."}
                )
                self.send_response(303)
                self.send_header("Location", f"/signin?{query}")
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)
            user_id = _safe_int(str(current_user.get("id")), 0)
            mode = " ".join(form.get("mode", ["all"])[0].split()).strip().lower()
            only_unavailable = mode == "unavailable"
            name_filter = _normalize_name_filter(form.get("name", [""])[0])
            breed_filter = _normalize_breed_filter(form.get("breed", [""])[0])
            species_filter = _normalize_species_filter(form.get("species", [""])[0])
            provider_filter = _normalize_provider_filter(form.get("provider", [""])[0])

            query_params: dict[str, str] = {}
            if name_filter:
                query_params["name"] = name_filter
            if breed_filter:
                query_params["breed"] = breed_filter
            if species_filter:
                query_params["species"] = species_filter
            if provider_filter:
                query_params["provider"] = provider_filter

            if user_id <= 0:
                query_params["msg"] = "Unable to manage liked pets."
                self.send_response(303)
                self.send_header("Location", f"/likes?{urlencode(query_params)}")
                self.end_headers()
                return

            try:
                removed = _remove_liked_puppies(
                    user_id=user_id,
                    name_filter=name_filter,
                    breed_filter=breed_filter,
                    species_filter=species_filter,
                    provider_filter=provider_filter,
                    only_unavailable=only_unavailable,
                )
            except Exception as exc:
                query_params["msg"] = f"Failed to remove liked pets: {exc}"
                self.send_response(303)
                self.send_header("Location", f"/likes?{urlencode(query_params)}")
                self.end_headers()
                return

            if removed <= 0:
                query_params["msg"] = (
                    "No unavailable liked pets to remove."
                    if only_unavailable
                    else "No liked pets to remove."
                )
            else:
                query_params["msg"] = (
                    f"Removed {removed} unavailable liked pet"
                    f"{'' if removed == 1 else 's'}."
                    if only_unavailable
                    else f"Removed {removed} liked pet{'' if removed == 1 else 's'}."
                )
            self.send_response(303)
            self.send_header("Location", f"/likes?{urlencode(query_params)}")
            self.end_headers()
            return

        if parsed.path == "/subscribe":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)

            photo_index = _safe_int(form.get("photo", ["0"])[0], 0)
            filter_hash = " ".join(form.get("f", [""])[0].split()).strip()
            review_mode = (
                "passed"
                if form.get("review", [""])[0].strip().lower() == "passed"
                else ""
            )
            breed_filter = _normalize_breed_filter(form.get("breed", [""])[0])
            name_filter = _normalize_name_filter(form.get("name", [""])[0])
            provider_filter = _normalize_provider_filter(form.get("provider", [""])[0])
            species_filter = _normalize_species_filter(form.get("species", [""])[0])
            max_age_months = _normalize_max_age_filter(
                form.get("max_age", [str(MAX_PUPPY_AGE_MONTHS)])[0]
            )
            email = _normalize_email(form.get("email", [""])[0])

            query_params = {"photo": str(photo_index)}
            query_params = _add_active_filters(
                query_params,
                breed_filter=breed_filter,
                name_filter=name_filter,
                provider_filter=provider_filter,
                species_filter=species_filter,
                max_age_months=max_age_months,
                filter_hash=filter_hash,
                review_mode=review_mode,
            )
            if not _is_valid_email(email):
                query_params["msg"] = "Enter a valid email address."
                query = urlencode(query_params)
                self.send_response(303)
                self.send_header("Location", f"/?{query}")
                self.end_headers()
                return

            try:
                created = add_email_subscriber(email, source="pupswipe")
            except Exception as exc:
                query_params["msg"] = f"Failed to save subscription: {exc}"
                query = urlencode(query_params)
                self.send_response(303)
                self.send_header("Location", f"/?{query}")
                self.end_headers()
                return

            query_params["msg"] = (
                "Subscribed to PuppyPing email updates."
                if created
                else "Email is already subscribed."
            )
            query = urlencode(query_params)
            self.send_response(303)
            self.send_header("Location", f"/?{query}")
            self.end_headers()
            return

        if parsed.path == "/swipe":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)
            form_payload = {
                key: values[0]
                for key, values in form.items()
                if isinstance(values, list) and values
            }
            filter_hash = " ".join(form.get("f", [""])[0].split()).strip()
            review_mode = (
                "passed"
                if form.get("review", [""])[0].strip().lower() == "passed"
                else ""
            )
            try:
                dog_id = int(form.get("dog_id", [""])[0])
            except (TypeError, ValueError):
                breed_filter = _normalize_breed_filter(form.get("breed", [""])[0])
                name_filter = _normalize_name_filter(form.get("name", [""])[0])
                provider_filter = _normalize_provider_filter(form.get("provider", [""])[0])
                species_filter = _normalize_species_filter(form.get("species", [""])[0])
                max_age_months = _normalize_max_age_filter(
                    form.get("max_age", [str(MAX_PUPPY_AGE_MONTHS)])[0]
                )
                query_params = {"msg": "Invalid dog id"}
                query_params = _add_active_filters(
                    query_params,
                    breed_filter=breed_filter,
                    name_filter=name_filter,
                    provider_filter=provider_filter,
                    species_filter=species_filter,
                    max_age_months=max_age_months,
                    filter_hash=filter_hash,
                    review_mode=review_mode,
                )
                self.send_response(303)
                self.send_header("Location", f"/?{urlencode(query_params)}")
                self.end_headers()
                return

            swipe = form.get("swipe", [""])[0]
            breed_filter = _normalize_breed_filter(form.get("breed", [""])[0])
            name_filter = _normalize_name_filter(form.get("name", [""])[0])
            provider_filter = _normalize_provider_filter(form.get("provider", [""])[0])
            species_filter = _normalize_species_filter(form.get("species", [""])[0])
            max_age_months = _normalize_max_age_filter(
                form.get("max_age", [str(MAX_PUPPY_AGE_MONTHS)])[0]
            )
            if swipe not in ("left", "right"):
                query_params = {"msg": "Invalid swipe value"}
                query_params = _add_active_filters(
                    query_params,
                    breed_filter=breed_filter,
                    name_filter=name_filter,
                    provider_filter=provider_filter,
                    species_filter=species_filter,
                    max_age_months=max_age_months,
                    filter_hash=filter_hash,
                    review_mode=review_mode,
                )
                self.send_response(303)
                self.send_header("Location", f"/?{urlencode(query_params)}")
                self.end_headers()
                return

            current_user = self._signed_in_user()
            current_user_id = (
                _safe_int(str(current_user.get("id")), 0) if current_user else 0
            )
            try:
                _store_swipe(
                    dog_id=dog_id,
                    species=form.get("species", [""])[0],
                    swipe=swipe,
                    source="pupswipe",
                    user_id=current_user_id if current_user_id > 0 else None,
                    **self._user_context(form_payload),
                )
            except Exception as exc:
                query_params = {"msg": f"Failed to store swipe: {exc}"}
                query_params = _add_active_filters(
                    query_params,
                    breed_filter=breed_filter,
                    name_filter=name_filter,
                    provider_filter=provider_filter,
                    species_filter=species_filter,
                    max_age_months=max_age_months,
                    filter_hash=filter_hash,
                    review_mode=review_mode,
                )
                query = urlencode(query_params)
                self.send_response(303)
                self.send_header("Location", f"/?{query}")
                self.end_headers()
                return

            query_params: dict[str, str] = {}
            query_params = _add_active_filters(
                query_params,
                breed_filter=breed_filter,
                name_filter=name_filter,
                provider_filter=provider_filter,
                species_filter=species_filter,
                max_age_months=max_age_months,
                filter_hash=filter_hash,
                review_mode=review_mode,
            )
            query = urlencode(query_params)
            self.send_response(303)
            self.send_header("Location", f"/?{query}")
            self.end_headers()
            return

        if parsed.path != "/api/swipes":
            self.send_error(404, "Not Found")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return self._send_json(400, {"error": "invalid json"})

        try:
            dog_id = int(payload.get("dog_id"))
        except (TypeError, ValueError):
            return self._send_json(400, {"error": "dog_id is required"})

        swipe = payload.get("swipe")
        if swipe not in ("left", "right"):
            return self._send_json(400, {"error": "swipe must be left or right"})

        source = payload.get("source")
        species = payload.get("species")
        current_user = self._signed_in_user()
        current_user_id = _safe_int(str(current_user.get("id")), 0) if current_user else 0
        try:
            _store_swipe(
                dog_id=dog_id,
                species=species,
                swipe=swipe,
                source=source,
                user_id=current_user_id if current_user_id > 0 else None,
                **self._user_context(payload),
            )
        except Exception as exc:
            return self._send_json(500, {"error": "failed to store swipe", "detail": str(exc)})

        return self._send_json(201, {"ok": True})

    def log_message(self, fmt, *args):
        """Suppress default HTTP request logging output.

        Args:
            fmt: Log format string.
            *args: Format arguments.

        Returns:
            None.
        """
        return


def main() -> None:
    """Run the PupSwipe HTTP server from CLI arguments.

    Returns:
        None.
    """
    parser = argparse.ArgumentParser(description="Serve PupSwipe web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"PupSwipe running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
