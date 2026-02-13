"""Database schema and query helpers for PupSwipe."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from puppyping.db import ensure_schema, get_connection
from puppyping.pupswipe.auth import (
    hash_password,
    password_reset_token_hash,
    verify_password,
)
from puppyping.pupswipe.config import (
    MAX_BREED_FILTER_LENGTH,
    MAX_NAME_FILTER_LENGTH,
    MAX_PUPPY_AGE_MONTHS,
    PASSWORD_RESET_TOKEN_TTL_MINUTES,
    get_pupswipe_sources,
)


def ensure_app_schema(conn) -> None:
    """Create or update tables/indexes needed by the PupSwipe app."""
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
                password_hash TEXT,
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
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                created_at_utc TIMESTAMPTZ NOT NULL,
                expires_at_utc TIMESTAMPTZ NOT NULL,
                used_at_utc TIMESTAMPTZ
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
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS password_hash TEXT;
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
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
            ON password_reset_tokens (user_id, created_at_utc DESC);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires
            ON password_reset_tokens (expires_at_utc DESC);
            """
        )
    conn.commit()


def _coerce_json(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _jsonify(obj):
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    return _coerce_json(obj)


def _normalize_breed_filter(value: str | None) -> str:
    text = " ".join((value or "").split()).strip()
    if not text:
        return ""
    return text[:MAX_BREED_FILTER_LENGTH]


def _normalize_name_filter(value: str | None) -> str:
    text = " ".join((value or "").split()).strip()
    if not text:
        return ""
    return text[:MAX_NAME_FILTER_LENGTH]


def _normalize_provider_filter(value: str | None, sources: tuple[str, ...]) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return ""
    if candidate in sources:
        return candidate
    return ""


def _text_like_pattern(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


def fetch_puppies(
    limit: int,
    offset: int = 0,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    *,
    sources: tuple[str, ...] | None = None,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> list[dict]:
    """Load the latest available dog profiles ordered by recency."""
    active_sources = tuple(sources or get_pupswipe_sources())
    normalized_breed = _normalize_breed_filter(breed_filter)
    normalized_name = _normalize_name_filter(name_filter)
    normalized_provider = _normalize_provider_filter(provider_filter, active_sources)
    with connection_factory() as conn:
        ensure_schema_fn(conn)
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
                    list(active_sources),
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
        record = _jsonify(dict(zip(columns, row)))
        media = record.get("media") or {}
        images = media.get("images") or []
        record["primary_image"] = images[0] if images else None
        puppies.append(record)
    return puppies


def count_puppies(
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    *,
    sources: tuple[str, ...] | None = None,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> int:
    """Count latest dog profiles that are currently available."""
    active_sources = tuple(sources or get_pupswipe_sources())
    normalized_breed = _normalize_breed_filter(breed_filter)
    normalized_name = _normalize_name_filter(name_filter)
    normalized_provider = _normalize_provider_filter(provider_filter, active_sources)
    with connection_factory() as conn:
        ensure_schema_fn(conn)
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
                    list(active_sources),
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


def store_swipe(
    dog_id: int,
    swipe: str,
    source: str | None = None,
    user_id: int | None = None,
    user_key: str | None = None,
    user_ip: str | None = None,
    user_agent: str | None = None,
    accept_language: str | None = None,
    screen_info: dict | None = None,
    *,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> None:
    """Persist a swipe event for a dog."""
    with connection_factory() as conn:
        ensure_schema_fn(conn)
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


def get_user_for_password_reset(
    email: str,
    *,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> dict | None:
    """Load minimal user fields needed to issue a password reset."""
    with connection_factory() as conn:
        ensure_schema_fn(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email
                FROM users
                WHERE email = %s;
                """,
                (email,),
            )
            row = cur.fetchone()
            columns = [col.name for col in cur.description] if row else []
    if not row:
        return None
    return _jsonify(dict(zip(columns, row)))


def create_password_reset_token(
    user_id: int,
    *,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> tuple[str, datetime]:
    """Create and persist a one-time password-reset token."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = password_reset_token_hash(raw_token)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=PASSWORD_RESET_TOKEN_TTL_MINUTES)
    with connection_factory() as conn:
        ensure_schema_fn(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM password_reset_tokens
                WHERE user_id = %s
                  AND (used_at_utc IS NOT NULL OR expires_at_utc < %s);
                """,
                (user_id, now),
            )
            cur.execute(
                """
                INSERT INTO password_reset_tokens (
                    user_id,
                    token_hash,
                    created_at_utc,
                    expires_at_utc
                )
                VALUES (%s, %s, %s, %s);
                """,
                (user_id, token_hash, now, expires),
            )
        conn.commit()
    return raw_token, expires


def consume_password_reset_token(
    token: str,
    new_password: str,
    *,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> int:
    """Consume reset token and update user password.

    Returns:
        The user id whose password was updated.
    """
    token_hash = password_reset_token_hash(token)
    now = datetime.now(timezone.utc)
    with connection_factory() as conn:
        ensure_schema_fn(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, expires_at_utc, used_at_utc
                FROM password_reset_tokens
                WHERE token_hash = %s
                FOR UPDATE;
                """,
                (token_hash,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Reset link is invalid or expired.")
            token_id, user_id, expires_at_utc, used_at_utc = row
            if used_at_utc is not None or expires_at_utc is None or expires_at_utc <= now:
                raise ValueError("Reset link is invalid or expired.")

            cur.execute(
                """
                UPDATE users
                SET password_hash = %s,
                    last_seen_at_utc = %s
                WHERE id = %s;
                """,
                (hash_password(new_password), now, user_id),
            )
            cur.execute(
                """
                UPDATE password_reset_tokens
                SET used_at_utc = %s
                WHERE id = %s;
                """,
                (now, token_id),
            )
            cur.execute(
                """
                UPDATE password_reset_tokens
                SET used_at_utc = %s
                WHERE user_id = %s
                  AND used_at_utc IS NULL
                  AND id <> %s;
                """,
                (now, user_id, token_id),
            )
        conn.commit()
    return int(user_id)


def is_password_reset_token_valid(
    token: str,
    *,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> bool:
    """Check whether reset token exists, is unused, and not expired."""
    token_hash = password_reset_token_hash(token)
    now = datetime.now(timezone.utc)
    with connection_factory() as conn:
        ensure_schema_fn(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM password_reset_tokens
                WHERE token_hash = %s
                  AND used_at_utc IS NULL
                  AND expires_at_utc > %s
                LIMIT 1;
                """,
                (token_hash, now),
            )
            row = cur.fetchone()
    return bool(row)


def upsert_user(
    email: str,
    password: str,
    *,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> dict:
    """Create or authenticate a user row keyed by email."""
    now = datetime.now(timezone.utc)
    password_hash = hash_password(password)
    with connection_factory() as conn:
        ensure_schema_fn(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, password_hash, created_at_utc, last_seen_at_utc
                FROM users
                WHERE email = %s;
                """,
                (email,),
            )
            existing = cur.fetchone()
            if existing:
                user_id, _email, existing_hash, _created_at, _last_seen_at = existing
                if existing_hash and not verify_password(password, str(existing_hash)):
                    raise ValueError("Incorrect email or password.")
                if not existing_hash:
                    cur.execute(
                        """
                        UPDATE users
                        SET password_hash = %s,
                            last_seen_at_utc = %s
                        WHERE id = %s
                        RETURNING id, email, created_at_utc, last_seen_at_utc;
                        """,
                        (password_hash, now, user_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE users
                        SET last_seen_at_utc = %s
                        WHERE id = %s
                        RETURNING id, email, created_at_utc, last_seen_at_utc;
                        """,
                        (now, user_id),
                    )
            else:
                cur.execute(
                    """
                    INSERT INTO users (
                        email,
                        password_hash,
                        created_at_utc,
                        last_seen_at_utc
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, email, created_at_utc, last_seen_at_utc;
                    """,
                    (email, password_hash, now, now),
                )

            row = cur.fetchone()
            columns = [col.name for col in cur.description] if row else []
        conn.commit()
    return _jsonify(dict(zip(columns, row))) if row else {}


def get_user_by_id(
    user_id: int,
    *,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> dict | None:
    """Load a user row by id and update last-seen timestamp."""
    now = datetime.now(timezone.utc)
    with connection_factory() as conn:
        ensure_schema_fn(conn)
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


def update_user_password(
    user_id: int,
    current_password: str,
    new_password: str,
    *,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> None:
    """Verify current password and replace it with a new password hash."""
    now = datetime.now(timezone.utc)
    with connection_factory() as conn:
        ensure_schema_fn(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT password_hash
                FROM users
                WHERE id = %s;
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Account not found.")
            current_hash = str(row[0] or "")
            if not current_hash:
                raise ValueError("Password is not set for this account.")
            if not verify_password(current_password, current_hash):
                raise ValueError("Current password is incorrect.")

            cur.execute(
                """
                UPDATE users
                SET password_hash = %s,
                    last_seen_at_utc = %s
                WHERE id = %s;
                """,
                (hash_password(new_password), now, user_id),
            )
        conn.commit()


def count_liked_puppies(
    user_id: int,
    *,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> int:
    """Count likes for a given user."""
    with connection_factory() as conn:
        ensure_schema_fn(conn)
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


def fetch_liked_puppies(
    user_id: int,
    limit: int = 120,
    offset: int = 0,
    *,
    sources: tuple[str, ...] | None = None,
    connection_factory: Callable = get_connection,
    ensure_schema_fn: Callable = ensure_app_schema,
) -> list[dict]:
    """Load a user's liked puppies ordered by most recently liked."""
    active_sources = tuple(sources or get_pupswipe_sources())
    page_limit = max(1, min(200, int(limit)))
    page_offset = max(0, int(offset))
    with connection_factory() as conn:
        ensure_schema_fn(conn)
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
                (user_id, page_limit, page_offset, list(active_sources)),
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
