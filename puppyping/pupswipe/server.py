"""Server-rendered PupSwipe application.

This module provides a minimal HTTP server for browsing adoptable dogs,
recording swipe actions, and exposing health/data APIs backed by Postgres.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from puppyping.db import add_email_subscriber, ensure_schema, get_connection
from puppyping.email_utils import is_valid_email, normalize_email

APP_DIR = Path(__file__).resolve().parent
DEFAULT_LIMIT = 40
MAX_LIMIT = 200
PAGE_SIZE = 1
MAX_PUPPY_AGE_MONTHS = 8.0
MAX_BREED_FILTER_LENGTH = 80
MAX_NAME_FILTER_LENGTH = 80
SESSION_COOKIE_NAME = "pupswipe_session"
SESSION_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
DEFAULT_SESSION_SECRET = "pupswipe-dev-session-secret-change-me"
DEFAULT_PUPSWIPE_SOURCES = ("paws_chicago", "wright_way")
PROVIDER_DISCLAIMER = (
    "PuppyPing is not affiliated with any dog rescue, shelter, breeder, "
    "or adoption provider."
)


def _get_pupswipe_sources() -> tuple[str, ...]:
    """Return feed sources for PupSwipe from env, with sensible defaults.

    Returns:
        Tuple of enabled source keys.
    """
    raw = os.environ.get("PUPSWIPE_SOURCES", ",".join(DEFAULT_PUPSWIPE_SOURCES))
    parsed = [item.strip() for item in raw.split(",") if item.strip()]
    deduped = tuple(dict.fromkeys(parsed))
    return deduped or DEFAULT_PUPSWIPE_SOURCES


PUPSWIPE_SOURCES = _get_pupswipe_sources()


def _provider_name(source: str | None, profile_url: str | None = None) -> str:
    """Return a human-readable provider label for a profile.

    Args:
        source: Optional normalized provider source key.
        profile_url: Optional profile URL for fallback detection.

    Returns:
        Provider display name.
    """
    if source == "paws_chicago":
        return "PAWS Chicago"
    if source == "wright_way":
        return "Wright-Way Rescue"

    url = (profile_url or "").lower()
    if "pawschicago.org" in url:
        return "PAWS Chicago"
    if "petango.com" in url or "wright-wayrescue.org" in url:
        return "Wright-Way Rescue"
    return "Adoption Provider"


def _ensure_app_schema(conn) -> None:
    """Create or update tables/indexes needed by the PupSwipe app.

    Args:
        conn: An open psycopg connection.

    Returns:
        None.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dog_swipes (
                id BIGSERIAL PRIMARY KEY,
                dog_id INTEGER NOT NULL,
                swipe TEXT NOT NULL CHECK (swipe IN ('left', 'right')),
                source TEXT,
                created_at_utc TIMESTAMPTZ NOT NULL,
                user_key TEXT,
                user_ip TEXT,
                user_agent TEXT,
                accept_language TEXT,
                screen_info JSONB
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                created_at_utc TIMESTAMPTZ NOT NULL,
                last_seen_at_utc TIMESTAMPTZ NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dog_likes (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                dog_id INTEGER NOT NULL,
                source TEXT,
                created_at_utc TIMESTAMPTZ NOT NULL,
                UNIQUE (user_id, dog_id)
            );
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS user_key TEXT;
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS user_ip TEXT;
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS user_agent TEXT;
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS accept_language TEXT;
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS screen_info JSONB;
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS user_id BIGINT;
            """
        )
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'dog_swipes_user_id_fkey'
                ) THEN
                    ALTER TABLE dog_swipes
                    ADD CONSTRAINT dog_swipes_user_id_fkey
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE SET NULL;
                END IF;
            END
            $$;
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_swipes_created_at
            ON dog_swipes (created_at_utc DESC);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_swipes_dog_id
            ON dog_swipes (dog_id);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_swipes_user_key
            ON dog_swipes (user_key);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_swipes_user_id
            ON dog_swipes (user_id);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_likes_user_created
            ON dog_likes (user_id, created_at_utc DESC);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_likes_dog_id
            ON dog_likes (dog_id);
            """
        )
    conn.commit()


def _coerce_json(value):
    """Coerce non-JSON-native values into JSON-serializable values.

    Args:
        value: Any value that may need JSON coercion.

    Returns:
        A JSON-serializable representation of the input value.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _jsonify(obj):
    """Recursively convert an object graph to JSON-safe values.

    Args:
        obj: A primitive, list, or dict to transform.

    Returns:
        A recursively transformed object suitable for JSON serialization.
    """
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    return _coerce_json(obj)


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


def _text_like_pattern(value: str) -> str:
    """Escape wildcard characters so text filters match literal text."""
    escaped = (
        value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


def _filter_hidden_inputs(
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
) -> str:
    """Render hidden form inputs for currently active filters."""
    hidden_inputs: list[str] = []
    if breed_filter:
        hidden_inputs.append(
            f'<input type="hidden" name="breed" value="{escape(breed_filter)}" />'
        )
    if name_filter:
        hidden_inputs.append(
            f'<input type="hidden" name="name" value="{escape(name_filter)}" />'
        )
    if provider_filter:
        hidden_inputs.append(
            f'<input type="hidden" name="provider" value="{escape(provider_filter)}" />'
        )
    return "\n            ".join(hidden_inputs)


def _add_active_filters(
    query_params: dict[str, str],
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
) -> dict[str, str]:
    """Attach non-empty filters to query params for redirects/links."""
    if breed_filter:
        query_params["breed"] = breed_filter
    if name_filter:
        query_params["name"] = name_filter
    if provider_filter:
        query_params["provider"] = provider_filter
    return query_params


def _fetch_puppies(
    limit: int,
    offset: int = 0,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
) -> list[dict]:
    """Load the latest available dog profiles ordered by recency.

    Args:
        limit: Maximum number of profiles to return.
        offset: Number of rows to skip for pagination.
        breed_filter: Optional case-insensitive breed text filter.
        name_filter: Optional case-insensitive name text filter.
        provider_filter: Optional provider source filter.

    Returns:
        A list of dog profile dictionaries.
    """
    normalized_breed = _normalize_breed_filter(breed_filter)
    normalized_name = _normalize_name_filter(name_filter)
    normalized_provider = _normalize_provider_filter(provider_filter)
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (dog_id)
                        dog_id,
                        url,
                        name,
                        breed,
                        gender,
                        age_raw,
                        age_months,
                        weight_lbs,
                        location,
                        status,
                        ratings,
                        description,
                        media,
                        scraped_at_utc
                    FROM dog_profiles
                    ORDER BY dog_id, scraped_at_utc DESC
                ), active AS (
                    SELECT
                        latest.*,
                        dog_status.source
                    FROM latest
                    JOIN dog_status
                      ON dog_status.link = latest.url
                     AND dog_status.is_active = true
                     AND dog_status.source = ANY(%s::text[])
                )
                SELECT *
                FROM active
                WHERE COALESCE(status, '') ILIKE 'Available%%'
                  AND age_months IS NOT NULL
                  AND age_months < %s
                  AND (%s = '' OR source = %s)
                  AND (%s = '' OR COALESCE(breed, '') ILIKE %s ESCAPE '\\')
                  AND (%s = '' OR COALESCE(name, '') ILIKE %s ESCAPE '\\')
                ORDER BY scraped_at_utc DESC, dog_id DESC
                LIMIT %s
                OFFSET %s;
                """,
                (
                    list(PUPSWIPE_SOURCES),
                    MAX_PUPPY_AGE_MONTHS,
                    normalized_provider,
                    normalized_provider,
                    normalized_breed,
                    _text_like_pattern(normalized_breed),
                    normalized_name,
                    _text_like_pattern(normalized_name),
                    limit,
                    max(0, offset),
                ),
            )
            rows = cur.fetchall()
            columns = [col.name for col in cur.description]

    puppies: list[dict] = []
    for row in rows:
        record = dict(zip(columns, row))
        record = _jsonify(record)
        media = record.get("media") or {}
        images = media.get("images") or []
        record["primary_image"] = images[0] if images else None
        puppies.append(record)
    return puppies


def _count_puppies(
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
) -> int:
    """Count latest dog profiles that are currently available.

    Returns:
        The number of available dogs based on each dog's latest record.
    """
    normalized_breed = _normalize_breed_filter(breed_filter)
    normalized_name = _normalize_name_filter(name_filter)
    normalized_provider = _normalize_provider_filter(provider_filter)
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (dog_id)
                        dog_id,
                        url,
                        name,
                        breed,
                        age_months,
                        status,
                        scraped_at_utc
                    FROM dog_profiles
                    ORDER BY dog_id, scraped_at_utc DESC
                )
                SELECT count(*)
                FROM latest
                WHERE EXISTS (
                    SELECT 1
                    FROM dog_status
                    WHERE dog_status.link = latest.url
                      AND dog_status.source = ANY(%s::text[])
                      AND (%s = '' OR dog_status.source = %s)
                      AND dog_status.is_active = true
                )
                  AND COALESCE(status, '') ILIKE 'Available%%'
                  AND age_months IS NOT NULL
                  AND age_months < %s
                  AND (%s = '' OR COALESCE(breed, '') ILIKE %s ESCAPE '\\')
                  AND (%s = '' OR COALESCE(name, '') ILIKE %s ESCAPE '\\');
                """,
                (
                    list(PUPSWIPE_SOURCES),
                    normalized_provider,
                    normalized_provider,
                    MAX_PUPPY_AGE_MONTHS,
                    normalized_breed,
                    _text_like_pattern(normalized_breed),
                    normalized_name,
                    _text_like_pattern(normalized_name),
                ),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _store_swipe(
    dog_id: int,
    swipe: str,
    source: str | None = None,
    user_id: int | None = None,
    user_key: str | None = None,
    user_ip: str | None = None,
    user_agent: str | None = None,
    accept_language: str | None = None,
    screen_info: dict | None = None,
) -> None:
    """Persist a swipe event for a dog.

    Args:
        dog_id: Dog identifier.
        swipe: Swipe direction, either "left" or "right".
        source: Optional source identifier (for example, "pupswipe").
        user_id: Optional signed-in user id.
        user_key: Derived per-user fingerprint key.
        user_ip: Client IP address.
        user_agent: Client user agent string.
        accept_language: Client language header value.
        screen_info: Optional screen/viewport metadata.

    Returns:
        None.
    """
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            screen_info_json = json.dumps(screen_info, sort_keys=True) if screen_info else None
            cur.execute(
                """
                INSERT INTO dog_swipes (
                    dog_id,
                    swipe,
                    source,
                    created_at_utc,
                    user_id,
                    user_key,
                    user_ip,
                    user_agent,
                    accept_language,
                    screen_info
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb);
                """,
                (
                    dog_id,
                    swipe,
                    source,
                    datetime.now(timezone.utc),
                    user_id,
                    user_key,
                    user_ip,
                    user_agent,
                    accept_language,
                    screen_info_json,
                ),
            )
            if user_id is not None:
                if swipe == "right":
                    cur.execute(
                        """
                        INSERT INTO dog_likes (
                            user_id,
                            dog_id,
                            source,
                            created_at_utc
                        )
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id, dog_id)
                        DO UPDATE SET
                            source = EXCLUDED.source,
                            created_at_utc = EXCLUDED.created_at_utc;
                        """,
                        (
                            user_id,
                            dog_id,
                            source,
                            datetime.now(timezone.utc),
                        ),
                    )
                else:
                    cur.execute(
                        """
                        DELETE FROM dog_likes
                        WHERE user_id = %s
                          AND dog_id = %s;
                        """,
                        (user_id, dog_id),
                    )
        conn.commit()


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


def _normalize_next_path(value: str | None, default: str = "/") -> str:
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


def _session_secret() -> str:
    """Return the cookie-signing secret."""
    secret = os.environ.get("PUPSWIPE_SESSION_SECRET", "").strip()
    return secret or DEFAULT_SESSION_SECRET


def _session_signature(user_id: int) -> str:
    """Build an HMAC signature for a user-id session payload."""
    payload = str(user_id).encode("utf-8")
    secret = _session_secret().encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _encode_session_value(user_id: int) -> str:
    """Encode signed session cookie contents."""
    return f"{user_id}.{_session_signature(user_id)}"


def _decode_session_value(raw_value: str | None) -> int | None:
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
    expected = _session_signature(user_id)
    if not hmac.compare_digest(signature, expected):
        return None
    return user_id


def _upsert_user(email: str) -> dict:
    """Create or update a user row keyed by email."""
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, created_at_utc, last_seen_at_utc)
                VALUES (%s, %s, %s)
                ON CONFLICT (email)
                DO UPDATE SET last_seen_at_utc = EXCLUDED.last_seen_at_utc
                RETURNING id, email, created_at_utc, last_seen_at_utc;
                """,
                (email, now, now),
            )
            row = cur.fetchone()
            columns = [col.name for col in cur.description]
        conn.commit()
    return _jsonify(dict(zip(columns, row))) if row else {}


def _get_user_by_id(user_id: int) -> dict | None:
    """Load a user row by id and update last-seen timestamp."""
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET last_seen_at_utc = %s
                WHERE id = %s
                RETURNING id, email, created_at_utc, last_seen_at_utc;
                """,
                (now, user_id),
            )
            row = cur.fetchone()
            columns = [col.name for col in cur.description] if row else []
        conn.commit()
    if not row:
        return None
    return _jsonify(dict(zip(columns, row)))


def _count_liked_puppies(user_id: int) -> int:
    """Count likes for a given user."""
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM dog_likes
                WHERE user_id = %s;
                """,
                (user_id,),
            )
            row = cur.fetchone()
    return int(row[0]) if row else 0


def _fetch_liked_puppies(user_id: int, limit: int = 120, offset: int = 0) -> list[dict]:
    """Load a user's liked puppies ordered by most recently liked."""
    page_limit = max(1, min(200, int(limit)))
    page_offset = max(0, int(offset))
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH liked AS (
                    SELECT dog_id, created_at_utc, source
                    FROM dog_likes
                    WHERE user_id = %s
                    ORDER BY created_at_utc DESC, dog_id DESC
                    LIMIT %s
                    OFFSET %s
                ), latest AS (
                    SELECT DISTINCT ON (dog_id)
                        dog_id,
                        url,
                        name,
                        breed,
                        gender,
                        age_raw,
                        age_months,
                        location,
                        status,
                        description,
                        media,
                        scraped_at_utc
                    FROM dog_profiles
                    ORDER BY dog_id, scraped_at_utc DESC
                )
                SELECT
                    liked.dog_id,
                    liked.created_at_utc AS liked_at_utc,
                    COALESCE(status_pick.source, liked.source) AS source,
                    latest.url,
                    latest.name,
                    latest.breed,
                    latest.gender,
                    latest.age_raw,
                    latest.age_months,
                    latest.location,
                    latest.status,
                    latest.description,
                    latest.media,
                    latest.scraped_at_utc
                FROM liked
                LEFT JOIN latest
                  ON latest.dog_id = liked.dog_id
                LEFT JOIN LATERAL (
                    SELECT source
                    FROM dog_status
                    WHERE dog_status.link = latest.url
                      AND dog_status.source = ANY(%s::text[])
                    ORDER BY dog_status.is_active DESC, dog_status.source ASC
                    LIMIT 1
                ) AS status_pick
                  ON true
                ORDER BY liked.created_at_utc DESC, liked.dog_id DESC;
                """,
                (user_id, page_limit, page_offset, list(PUPSWIPE_SOURCES)),
            )
            rows = cur.fetchall()
            columns = [col.name for col in cur.description]

    liked_pups: list[dict] = []
    for row in rows:
        record = _jsonify(dict(zip(columns, row)))
        media = record.get("media") or {}
        images = media.get("images") or []
        record["primary_image"] = images[0] if images else None
        liked_pups.append(record)
    return liked_pups


def _get_primary_image(pup: dict) -> str | None:
    """Extract the primary image URL from a dog record.

    Args:
        pup: Dog profile dictionary.

    Returns:
        The primary image URL if present, otherwise ``None``.
    """
    image = pup.get("primary_image")
    if isinstance(image, str) and image.strip():
        return image
    media = pup.get("media") or {}
    images = media.get("images") if isinstance(media, dict) else None
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str) and first.strip():
            return first
    return None


def _get_photo_urls(pup: dict) -> list[str]:
    """Collect unique photo URLs for a dog record.

    Args:
        pup: Dog profile dictionary.

    Returns:
        An ordered list of unique image URLs.
    """
    urls: list[str] = []
    primary = _get_primary_image(pup)
    if primary:
        urls.append(primary)
    media = pup.get("media") or {}
    images = media.get("images") if isinstance(media, dict) else None
    if isinstance(images, list):
        for item in images:
            if isinstance(item, str) and item.strip() and item not in urls:
                urls.append(item)
    return urls


def _render_page(
    offset: int = 0,
    message: str | None = None,
    photo_index: int = 0,
    randomize: bool = False,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    signed_in_email: str | None = None,
) -> bytes:
    """Render the main HTML page.

    Args:
        offset: Current dog index offset.
        message: Optional info/error message to display.
        photo_index: Selected image index within the current dog carousel.
        randomize: Whether to pick a random dog from the current result set.
        breed_filter: Optional breed filter text.
        name_filter: Optional name filter text.
        provider_filter: Optional provider source filter text.
        signed_in_email: Optional signed-in email for account actions.

    Returns:
        UTF-8 encoded HTML document bytes.
    """
    normalized_breed = _normalize_breed_filter(breed_filter)
    normalized_name = _normalize_name_filter(name_filter)
    normalized_provider = _normalize_provider_filter(provider_filter)
    escaped_breed = escape(normalized_breed)
    escaped_name = escape(normalized_name)
    filter_hidden_inputs = _filter_hidden_inputs(
        breed_filter=normalized_breed,
        name_filter=normalized_name,
        provider_filter=normalized_provider,
    )
    escaped_signed_in_email = escape(signed_in_email) if signed_in_email else ""
    if signed_in_email:
        account_actions_html = f"""
          <div class="account-actions">
            <span class="account-email">{escaped_signed_in_email}</span>
            <a class="profile-link" href="/likes">Liked pups</a>
            <form class="inline-form" method="post" action="/signout">
              <input type="hidden" name="next" value="/" />
              <button class="btn subtle" type="submit">Sign out</button>
            </form>
          </div>
        """
    else:
        signin_query = urlencode({"next": "/"})
        account_actions_html = (
            f'<a class="profile-link account-link" href="/signin?{signin_query}">'
            "Sign in to save likes"
            "</a>"
        )

    try:
        total = _count_puppies(
            breed_filter=normalized_breed,
            name_filter=normalized_name,
            provider_filter=normalized_provider,
        )
        if total > 0 and offset >= total:
            offset = 0
        if total > 1 and randomize:
            current_offset = offset
            random_offset = random.randrange(total - 1)
            if random_offset >= current_offset:
                random_offset += 1
            offset = random_offset
        elif total == 1 and randomize:
            offset = 0
        puppies = _fetch_puppies(
            PAGE_SIZE,
            offset=offset,
            breed_filter=normalized_breed,
            name_filter=normalized_name,
            provider_filter=normalized_provider,
        )
    except Exception as exc:
        error_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PupSwipe | PuppyPing</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">PS</div>
          <div>
            <h1>PupSwipe</h1>
            <p>By PuppyPing</p>
          </div>
        </div>
        {account_actions_html}
      </header>
      <main>
        <section class="stack">
          <div class="state state-error">Failed to load puppies: {escape(str(exc))}</div>
        </section>
      </main>
    </div>
  </body>
</html>"""
        return error_html.encode("utf-8")

    stats = f"{max(total - offset, 0)} left of {total}" if total else "No puppies found"
    active_filters: list[str] = []
    if normalized_breed:
        active_filters.append(f"Breed: {normalized_breed}")
    if normalized_name:
        active_filters.append(f"Name: {normalized_name}")
    if normalized_provider:
        active_filters.append(f"Provider: {_provider_name(normalized_provider)}")
    if active_filters:
        stats = f"{stats} | Filters: {', '.join(active_filters)}"

    clear_filter_html = ""
    if active_filters:
        clear_query = urlencode({"offset": "0"})
        clear_filter_html = f'<a class="clear-filter" href="/?{clear_query}">Clear</a>'

    provider_options = ['<option value="">All providers</option>']
    for source in PUPSWIPE_SOURCES:
        selected_attr = " selected" if source == normalized_provider else ""
        provider_options.append(
            f'<option value="{escape(source)}"{selected_attr}>{escape(_provider_name(source))}</option>'
        )
    provider_options_html = "".join(provider_options)

    filter_bar = f"""
      <section class="filter-strip" aria-label="Pup filters">
        <form class="breed-filter-form" method="get" action="/">
          <input type="hidden" name="offset" value="0" />
          <div class="filter-field">
            <label for="breed-filter">Breed</label>
            <input
              id="breed-filter"
              name="breed"
              type="text"
              value="{escaped_breed}"
              placeholder="e.g. Labrador"
              maxlength="{MAX_BREED_FILTER_LENGTH}"
            />
          </div>
          <div class="filter-field">
            <label for="name-filter">Name</label>
            <input
              id="name-filter"
              name="name"
              type="text"
              value="{escaped_name}"
              placeholder="e.g. Nova"
              maxlength="{MAX_NAME_FILTER_LENGTH}"
            />
          </div>
          <div class="filter-field">
            <label for="provider-filter">Provider</label>
            <select id="provider-filter" name="provider">
              {provider_options_html}
            </select>
          </div>
          <button class="btn filter" type="submit">Filter</button>
          {clear_filter_html}
        </form>
      </section>
    """

    if not puppies:
        empty_msg = (
            message
            or (
                "No puppies match those filters. Try different filters."
                if active_filters
                else "No puppies to show yet. Run scraper and refresh."
            )
        )
        no_data = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PupSwipe | PuppyPing</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">PS</div>
          <div>
            <h1>PupSwipe</h1>
            <p>By PuppyPing</p>
          </div>
        </div>
        <div class="stats">{escape(stats)}</div>
        {account_actions_html}
      </header>
      <main>
        <section class="stack">
          <div class="state state-empty">{escape(empty_msg)}</div>
        </section>
        <section class="controls">
          <form method="get" action="/">
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="random" value="1" />
            {filter_hidden_inputs}
            <button class="btn refresh" type="submit">Random</button>
          </form>
        </section>
        {filter_bar}
        <section class="ecosystem" aria-label="PuppyPing ecosystem">
          <h3>Get PuppyPing Alerts</h3>
          <p class="ecosystem-copy">
            PupSwipe runs inside the PuppyPing ecosystem. Join the PuppyPing email list for new puppy updates.
          </p>
          <p class="ecosystem-copy">
            {escape(PROVIDER_DISCLAIMER)}
          </p>
          <form class="subscribe-form" method="post" action="/subscribe">
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="photo" value="0" />
            {filter_hidden_inputs}
            <label class="subscribe-label" for="subscribe-email-empty">Email for PuppyPing alerts</label>
            <div class="subscribe-row">
              <input
                id="subscribe-email-empty"
                name="email"
                type="email"
                inputmode="email"
                autocomplete="email"
                placeholder="you@example.com"
                required
              />
              <button class="btn subscribe" type="submit">Join</button>
            </div>
          </form>
        </section>
      </main>
    </div>
  </body>
</html>"""
        return no_data.encode("utf-8")

    pup = puppies[0]
    dog_id = _safe_int(str(pup.get("dog_id")), 0)

    name = escape(str(pup.get("name") or "Unnamed pup"))
    age_raw = escape(str(pup.get("age_raw") or "Age unknown"))
    breed = escape(str(pup.get("breed") or "Unknown breed"))
    gender = escape(str(pup.get("gender") or "Unknown gender"))
    location = escape(str(pup.get("location") or "Unknown location"))
    status = escape(str(pup.get("status") or "Status unknown"))
    description = escape(
        str(
            pup.get("description")
            or "No description available yet. Open profile for full details."
        )
    )
    raw_profile_url = str(pup.get("url") or "").strip()
    profile_url = escape(raw_profile_url or "#")
    source_key = str(pup.get("source")) if pup.get("source") is not None else None
    provider_name = escape(_provider_name(source_key, raw_profile_url))
    if raw_profile_url:
        provider_link_html = (
            f'<a class="profile-link card-profile-link" href="{profile_url}" '
            f'target="_blank" rel="noopener">View on {provider_name}</a>'
        )
    else:
        provider_link_html = f'<span class="provider-missing">{provider_name}</span>'

    photo_urls = _get_photo_urls(pup)
    photo_count = len(photo_urls)
    if photo_count > 0:
        selected_photo = photo_urls[photo_index % photo_count]
        image_block = (
            f'<img src="{escape(selected_photo)}" alt="{name} photo" referrerpolicy="no-referrer" />'
        )
    else:
        initials = "".join(part[0] for part in name.split()[:2]).upper() or "PUP"
        image_block = f'<div class="photo-fallback">{escape(initials)}</div>'
    current_photo_index = photo_index % photo_count if photo_count > 0 else 0

    carousel_controls = ""
    if photo_count > 1:
        prev_photo = (photo_index - 1) % photo_count
        next_photo = (photo_index + 1) % photo_count
        current_index = photo_index % photo_count
        dots = "".join(
            f'<span class="carousel-dot{" is-active" if idx == current_index else ""}" aria-hidden="true"></span>'
            for idx in range(photo_count)
        )
        carousel_controls = f"""
            <div class="carousel-controls" aria-label="Photo carousel controls">
              <form method="get" action="/">
                <input type="hidden" name="offset" value="{offset}" />
                <input type="hidden" name="photo" value="{prev_photo}" />
                {filter_hidden_inputs}
                <button class="carousel-btn" type="submit" aria-label="Previous photo">Prev</button>
              </form>
              <div class="carousel-middle">
                <div class="carousel-meta">{current_index + 1} / {photo_count}</div>
                <div class="carousel-dots" aria-hidden="true">{dots}</div>
              </div>
              <form method="get" action="/">
                <input type="hidden" name="offset" value="{offset}" />
                <input type="hidden" name="photo" value="{next_photo}" />
                {filter_hidden_inputs}
                <button class="carousel-btn" type="submit" aria-label="Next photo">Next</button>
              </form>
            </div>
        """

    info_msg = f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    page_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PupSwipe | PuppyPing</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="background">
      <div class="glow glow-a"></div>
      <div class="glow glow-b"></div>
      <div class="grid"></div>
    </div>

    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">PS</div>
          <div>
            <h1>PupSwipe</h1>
            <p>By PuppyPing</p>
          </div>
        </div>
        <div class="topbar-meta">
          <div class="stats">{escape(stats)}</div>
          <a class="profile-link top-profile-link" href="{profile_url}" target="_blank" rel="noopener">Open profile</a>
        </div>
        {account_actions_html}
      </header>

      {info_msg}

      <main>
        <section class="stack">
          <article id="swipe-card" class="card enter" data-swipe-threshold="110">
            <div class="card-photo">
              {image_block}
              <div class="swipe-indicator like">Like</div>
              <div class="swipe-indicator nope">Nope</div>
            </div>
            <div class="card-body">
              <div class="card-title">
                <h2>{name}</h2>
                <span class="age-pill">{age_raw}</span>
              </div>
              <div class="card-facts">
                <span>{breed}</span>
                <span>{gender}</span>
                <span>{location}</span>
              </div>
              <div class="badges">
                <span class="badge">{status}</span>
                <span class="badge badge-provider">{provider_name}</span>
              </div>
              {carousel_controls}
              <div class="description-wrap">
                <h3 class="description-label">Description</h3>
                <p class="description">{description}</p>
              </div>
              <div class="provider-panel">
                <span class="provider-label">Provider link</span>
                {provider_link_html}
              </div>
            </div>
          </article>
        </section>

        <section class="controls" aria-label="Swipe controls">
          <form id="swipe-nope-form" method="post" action="/swipe">
            <input type="hidden" name="dog_id" value="{dog_id}" />
            <input type="hidden" name="offset" value="{offset}" />
            {filter_hidden_inputs}
            <input type="hidden" name="swipe" value="left" />
            <button class="btn nope" type="submit">Nope</button>
          </form>
          <form method="get" action="/">
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="random" value="1" />
            {filter_hidden_inputs}
            <button class="btn refresh" type="submit">Random</button>
          </form>
          <form id="swipe-like-form" method="post" action="/swipe">
            <input type="hidden" name="dog_id" value="{dog_id}" />
            <input type="hidden" name="offset" value="{offset}" />
            {filter_hidden_inputs}
            <input type="hidden" name="swipe" value="right" />
            <button class="btn like" type="submit">Like</button>
          </form>
        </section>
      </main>

      {filter_bar}

      <section class="ecosystem" aria-label="PuppyPing ecosystem">
        <h3>Get PuppyPing Alerts</h3>
        <p class="ecosystem-copy">
          PupSwipe is part of the PuppyPing ecosystem. Join PuppyPing email alerts to get fresh puppy updates.
        </p>
        <p class="ecosystem-copy">
          {escape(PROVIDER_DISCLAIMER)}
        </p>
        <form class="subscribe-form" method="post" action="/subscribe">
          <input type="hidden" name="offset" value="{offset}" />
          <input type="hidden" name="photo" value="{current_photo_index}" />
          {filter_hidden_inputs}
          <label class="subscribe-label" for="subscribe-email">Email for PuppyPing alerts</label>
          <div class="subscribe-row">
            <input
              id="subscribe-email"
              name="email"
              type="email"
              inputmode="email"
              autocomplete="email"
              placeholder="you@example.com"
              required
            />
            <button class="btn subscribe" type="submit">Join</button>
          </div>
        </form>
      </section>

    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _render_signin_page(
    message: str | None = None,
    next_path: str = "/likes",
    email_value: str = "",
    signed_in_email: str | None = None,
) -> bytes:
    """Render email sign-in page."""
    safe_next = _normalize_next_path(next_path, "/likes")
    escaped_email = escape(email_value)
    info_msg = f'<div class="flash" role="status">{escape(message)}</div>' if message else ""

    if signed_in_email:
        account_line = f"""
          <p class="auth-copy">
            You are currently signed in as <strong>{escape(signed_in_email)}</strong>.
            <a class="profile-link" href="/likes">View liked puppies</a>
          </p>
        """
    else:
        account_line = (
            '<p class="auth-copy">Use any valid email (Gmail, Outlook, Yahoo, or others).</p>'
        )

    page_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Sign In | PupSwipe</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="background">
      <div class="glow glow-a"></div>
      <div class="glow glow-b"></div>
      <div class="grid"></div>
    </div>
    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">PS</div>
          <div>
            <h1>PupSwipe</h1>
            <p>Sign in to save your likes</p>
          </div>
        </div>
      </header>
      {info_msg}
      <main>
        <section class="auth-shell">
          <article class="auth-card">
            <h2>Sign in</h2>
            {account_line}
            <form class="auth-form" method="post" action="/signin">
              <input type="hidden" name="next" value="{escape(safe_next)}" />
              <label for="signin-email">Email address</label>
              <input
                id="signin-email"
                name="email"
                type="email"
                inputmode="email"
                autocomplete="email"
                placeholder="you@example.com"
                value="{escaped_email}"
                required
              />
              <button class="btn like" type="submit">Continue</button>
            </form>
            <a class="profile-link" href="/">Back to PupSwipe</a>
          </article>
        </section>
      </main>
    </div>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _format_liked_time(value) -> str:
    """Format liked timestamp for simple display."""
    text = str(value or "").strip()
    if not text:
        return "Unknown time"
    return text.replace("T", " ").replace("+00:00", " UTC")


def _render_likes_page(
    email: str,
    puppies: list[dict],
    total_likes: int,
    message: str | None = None,
) -> bytes:
    """Render page showing the signed-in user's liked puppies."""
    info_msg = f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    cards_html = ""
    for pup in puppies:
        dog_id = _safe_int(str(pup.get("dog_id")), 0)
        name = escape(str(pup.get("name") or "Unnamed pup"))
        breed = escape(str(pup.get("breed") or "Unknown breed"))
        age_raw = escape(str(pup.get("age_raw") or "Age unknown"))
        location = escape(str(pup.get("location") or "Unknown location"))
        status = escape(str(pup.get("status") or "Status unknown"))
        liked_at = escape(_format_liked_time(pup.get("liked_at_utc")))
        raw_profile_url = str(pup.get("url") or "").strip()
        profile_url = escape(raw_profile_url or "#")
        source_key = str(pup.get("source")) if pup.get("source") is not None else None
        provider_name = escape(_provider_name(source_key, raw_profile_url))
        photo_url = _get_primary_image(pup)
        if photo_url:
            image_html = (
                f'<img src="{escape(photo_url)}" alt="{name} photo" referrerpolicy="no-referrer" />'
            )
        else:
            initials = "".join(part[0] for part in str(name).split()[:2]).upper() or "PUP"
            image_html = f'<div class="photo-fallback">{escape(initials)}</div>'

        if raw_profile_url:
            link_html = (
                f'<a class="profile-link" href="{profile_url}" target="_blank" rel="noopener">'
                f"Open on {provider_name}</a>"
            )
        else:
            link_html = f'<span class="provider-missing">{provider_name}</span>'

        cards_html += f"""
          <article class="liked-card">
            <div class="liked-photo">{image_html}</div>
            <div class="liked-body">
              <h3>{name}</h3>
              <p class="liked-meta">{breed} · {age_raw} · {location}</p>
              <div class="badges">
                <span class="badge">{status}</span>
                <span class="badge badge-provider">{provider_name}</span>
              </div>
              <p class="liked-time">Liked at {liked_at}</p>
              <p class="liked-id">Dog ID: {dog_id}</p>
              {link_html}
            </div>
          </article>
        """

    if not cards_html:
        cards_html = """
          <div class="state state-empty">
            No liked puppies yet. Swipe right on PupSwipe while signed in.
          </div>
        """

    page_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Liked Puppies | PupSwipe</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="background">
      <div class="glow glow-a"></div>
      <div class="glow glow-b"></div>
      <div class="grid"></div>
    </div>
    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">PS</div>
          <div>
            <h1>Liked Puppies</h1>
            <p>{escape(email)}</p>
          </div>
        </div>
        <div class="topbar-meta">
          <div class="stats">{total_likes} liked</div>
          <a class="profile-link top-profile-link" href="/">Back to PupSwipe</a>
        </div>
        <div class="account-actions">
          <span class="account-email">{escape(email)}</span>
          <form class="inline-form" method="post" action="/signout">
            <input type="hidden" name="next" value="/signin" />
            <button class="btn subtle" type="submit">Sign out</button>
          </form>
        </div>
      </header>
      {info_msg}
      <main>
        <section class="likes-shell">
          <div class="liked-grid">
            {cards_html}
          </div>
        </section>
      </main>
    </div>
  </body>
</html>"""
    return page_html.encode("utf-8")


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

    @staticmethod
    def _clear_session_cookie_header() -> str:
        """Build Set-Cookie header value for clearing session cookie."""
        return (
            f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; "
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
            try:
                puppies = _fetch_puppies(
                    limit,
                    breed_filter=breed_filter,
                    name_filter=name_filter,
                    provider_filter=provider_filter,
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
            message = parse_qs(parsed.query).get("msg", [None])[0]
            try:
                user_id = _safe_int(str(current_user.get("id")), 0)
                if user_id <= 0:
                    raise ValueError("invalid user id")
                total_likes = _count_liked_puppies(user_id)
                puppies = _fetch_liked_puppies(user_id=user_id, limit=120, offset=0)
            except Exception as exc:
                body = _render_likes_page(
                    email=str(current_user.get("email") or ""),
                    puppies=[],
                    total_likes=0,
                    message=f"Failed to load liked puppies: {exc}",
                )
                return self._send_html(200, body)

            body = _render_likes_page(
                email=str(current_user.get("email") or ""),
                puppies=puppies,
                total_likes=total_likes,
                message=message,
            )
            return self._send_html(200, body)

        if parsed.path == "/" or parsed.path == "/index.html":
            query = parse_qs(parsed.query)
            offset = _safe_int(query.get("offset", ["0"])[0], 0)
            photo_index = _safe_int(query.get("photo", ["0"])[0], 0)
            breed_filter = _normalize_breed_filter(query.get("breed", [""])[0])
            name_filter = _normalize_name_filter(query.get("name", [""])[0])
            provider_filter = _normalize_provider_filter(query.get("provider", [""])[0])
            randomize = query.get("random", ["0"])[0].strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            msg = query.get("msg", [None])[0]
            current_user = self._signed_in_user()
            body = _render_page(
                offset=offset,
                message=msg,
                photo_index=photo_index,
                randomize=randomize,
                breed_filter=breed_filter,
                name_filter=name_filter,
                provider_filter=provider_filter,
                signed_in_email=(
                    str(current_user.get("email") or "") if current_user else None
                ),
            )
            return self._send_html(200, body)

        return super().do_GET()

    def do_POST(self):
        """Handle POST requests for subscriptions, swipes, and API writes.

        Returns:
            None.
        """
        parsed = urlparse(self.path)
        if parsed.path == "/signin":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)

            email_raw = form.get("email", [""])[0]
            email = _normalize_email(email_raw)
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

            try:
                user = _upsert_user(email)
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

        if parsed.path == "/subscribe":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)

            offset = _safe_int(form.get("offset", ["0"])[0], 0)
            photo_index = _safe_int(form.get("photo", ["0"])[0], 0)
            breed_filter = _normalize_breed_filter(form.get("breed", [""])[0])
            name_filter = _normalize_name_filter(form.get("name", [""])[0])
            provider_filter = _normalize_provider_filter(form.get("provider", [""])[0])
            email = _normalize_email(form.get("email", [""])[0])

            query_params = {"offset": str(offset), "photo": str(photo_index)}
            query_params = _add_active_filters(
                query_params,
                breed_filter=breed_filter,
                name_filter=name_filter,
                provider_filter=provider_filter,
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
            try:
                dog_id = int(form.get("dog_id", [""])[0])
            except (TypeError, ValueError):
                breed_filter = _normalize_breed_filter(form.get("breed", [""])[0])
                name_filter = _normalize_name_filter(form.get("name", [""])[0])
                provider_filter = _normalize_provider_filter(form.get("provider", [""])[0])
                query_params = {"msg": "Invalid dog id"}
                query_params = _add_active_filters(
                    query_params,
                    breed_filter=breed_filter,
                    name_filter=name_filter,
                    provider_filter=provider_filter,
                )
                self.send_response(303)
                self.send_header("Location", f"/?{urlencode(query_params)}")
                self.end_headers()
                return

            swipe = form.get("swipe", [""])[0]
            breed_filter = _normalize_breed_filter(form.get("breed", [""])[0])
            name_filter = _normalize_name_filter(form.get("name", [""])[0])
            provider_filter = _normalize_provider_filter(form.get("provider", [""])[0])
            if swipe not in ("left", "right"):
                query_params = {"msg": "Invalid swipe value"}
                query_params = _add_active_filters(
                    query_params,
                    breed_filter=breed_filter,
                    name_filter=name_filter,
                    provider_filter=provider_filter,
                )
                self.send_response(303)
                self.send_header("Location", f"/?{urlencode(query_params)}")
                self.end_headers()
                return

            offset = _safe_int(form.get("offset", ["0"])[0], 0)
            current_user = self._signed_in_user()
            current_user_id = (
                _safe_int(str(current_user.get("id")), 0) if current_user else 0
            )
            try:
                _store_swipe(
                    dog_id,
                    swipe,
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
                )
                query = urlencode(query_params)
                self.send_response(303)
                self.send_header("Location", f"/?{query}")
                self.end_headers()
                return

            query_params = {"offset": str(offset + 1)}
            query_params = _add_active_filters(
                query_params,
                breed_filter=breed_filter,
                name_filter=name_filter,
                provider_filter=provider_filter,
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
        current_user = self._signed_in_user()
        current_user_id = _safe_int(str(current_user.get("id")), 0) if current_user else 0
        try:
            _store_swipe(
                dog_id,
                swipe,
                source,
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
