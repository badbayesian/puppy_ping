from __future__ import annotations

from logging import Logger
import os
from datetime import datetime, timezone
import hashlib
from typing import Iterable

try:
    import psycopg
    from psycopg.types.json import Json
except ModuleNotFoundError as exc:  # Optional dependency for DB features
    psycopg = None
    Json = None
    _PSYCOPG_IMPORT_ERROR = exc
else:
    _PSYCOPG_IMPORT_ERROR = None

from .models import DogProfile


def _require_psycopg() -> None:
    if psycopg is None:
        raise ModuleNotFoundError(
            "psycopg is required for database operations. Install it to enable storage."
        ) from _PSYCOPG_IMPORT_ERROR


def _get_pg_config() -> dict[str, str | int]:
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", "postgres"),
        "dbname": os.environ.get("PGDATABASE", "puppyping"),
    }


def _link_id(link: str) -> str:
    return hashlib.md5(link.encode("utf-8")).hexdigest()


def _status_id(source: str, link: str) -> str:
    return hashlib.md5(f"{source}:{link}".encode("utf-8")).hexdigest()


def get_connection() -> psycopg.Connection:
    _require_psycopg()
    cfg = _get_pg_config()
    try:
        return psycopg.connect(**cfg)
    except psycopg.OperationalError as exc:
        message = str(exc).lower()
        fallback_hosts: list[str] = []

        if cfg["host"] == "postgres" and (
            "resolve host" in message
            or "getaddrinfo" in message
            or "name or service not known" in message
        ):
            fallback_hosts = ["localhost", "127.0.0.1"]

        candidates: list[dict[str, str | int]] = []
        for host in fallback_hosts:
            if host != cfg["host"]:
                candidates.append({**cfg, "host": host})

        if cfg["port"] == 5432:
            for host in [cfg["host"], *fallback_hosts]:
                if host in ("localhost", "127.0.0.1"):
                    candidates.append({**cfg, "host": host, "port": 5433})

        seen: set[tuple[str, int, str, str]] = set()
        for candidate in candidates:
            key = (
                str(candidate["host"]),
                int(candidate["port"]),
                str(candidate["user"]),
                str(candidate["dbname"]),
            )
            if key in seen:
                continue
            seen.add(key)
            try:
                return psycopg.connect(**candidate)
            except psycopg.OperationalError:
                continue

        raise


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'cached_links'
                      AND column_name = 'links'
                ) THEN
                    CREATE TABLE IF NOT EXISTS cached_links_new (
                        id TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        link TEXT NOT NULL,
                        fetched_at_utc TIMESTAMPTZ NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT FALSE,
                        last_active_utc TIMESTAMPTZ
                    );
                    INSERT INTO cached_links_new (id, source, link, fetched_at_utc, last_active_utc)
                    SELECT md5(link), 'unknown', link, fetched_at_utc, fetched_at_utc
                    FROM (
                        SELECT jsonb_array_elements_text(links) AS link, fetched_at_utc
                        FROM cached_links
                    ) expanded
                    ON CONFLICT (id) DO UPDATE
                        SET fetched_at_utc = GREATEST(cached_links_new.fetched_at_utc, EXCLUDED.fetched_at_utc),
                            link = EXCLUDED.link,
                            source = COALESCE(cached_links_new.source, EXCLUDED.source),
                            last_active_utc = GREATEST(
                                COALESCE(cached_links_new.last_active_utc, EXCLUDED.last_active_utc),
                                EXCLUDED.last_active_utc
                            );
                    DROP TABLE cached_links;
                    ALTER TABLE cached_links_new RENAME TO cached_links;
                ELSIF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'cached_links'
                      AND column_name = 'link'
                ) AND EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'cached_links'
                      AND column_name = 'id'
                      AND data_type <> 'text'
                ) THEN
                    CREATE TABLE IF NOT EXISTS cached_links_new (
                        id TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        link TEXT NOT NULL,
                        fetched_at_utc TIMESTAMPTZ NOT NULL,
                        is_active BOOLEAN NOT NULL DEFAULT FALSE,
                        last_active_utc TIMESTAMPTZ
                    );
                    INSERT INTO cached_links_new (id, source, link, fetched_at_utc, last_active_utc)
                    SELECT md5(link), 'unknown', link, fetched_at_utc, fetched_at_utc
                    FROM cached_links
                    ON CONFLICT (id) DO UPDATE
                        SET fetched_at_utc = GREATEST(cached_links_new.fetched_at_utc, EXCLUDED.fetched_at_utc),
                            link = EXCLUDED.link,
                            source = COALESCE(cached_links_new.source, EXCLUDED.source),
                            last_active_utc = GREATEST(
                                COALESCE(cached_links_new.last_active_utc, EXCLUDED.last_active_utc),
                                EXCLUDED.last_active_utc
                            );
                    DROP TABLE cached_links;
                    ALTER TABLE cached_links_new RENAME TO cached_links;
                END IF;
            END $$;
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS dog_profiles (
                id BIGSERIAL PRIMARY KEY,
                dog_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                name TEXT,
                breed TEXT,
                gender TEXT,
                age_raw TEXT,
                age_months NUMERIC,
                weight_lbs NUMERIC,
                location TEXT,
                status TEXT,
                ratings JSONB,
                description TEXT,
                media JSONB,
                scraped_at_utc TIMESTAMPTZ NOT NULL,
                UNIQUE (dog_id, scraped_at_utc)
            );
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cached_links (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                link TEXT NOT NULL,
                fetched_at_utc TIMESTAMPTZ NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT FALSE,
                last_active_utc TIMESTAMPTZ
            );
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_dog_profiles_scraped_at
            ON dog_profiles (scraped_at_utc DESC);
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS email_subscribers (
                id BIGSERIAL PRIMARY KEY,
                email TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'unknown',
                created_at_utc TIMESTAMPTZ NOT NULL
            );
            """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_email_subscribers_email_lower
            ON email_subscribers (LOWER(email));
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_email_subscribers_created_at
            ON email_subscribers (created_at_utc DESC);
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS dog_status (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                link TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT FALSE,
                last_active_utc TIMESTAMPTZ
            );
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_dog_status_source_active
            ON dog_status (source, is_active);
            """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_dog_status_source_link
            ON dog_status (source, link);
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cached_links_fetched_at
            ON cached_links (fetched_at_utc DESC);
            """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_cached_links_link
            ON cached_links (link);
            """)
        cur.execute("""
            ALTER TABLE cached_links
            ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'unknown';
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cached_links_source_active
            ON cached_links (source, is_active);
            """)
        cur.execute("""
            ALTER TABLE cached_links
            ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE;
            """)
        cur.execute("""
            ALTER TABLE cached_links
            ADD COLUMN IF NOT EXISTS last_active_utc TIMESTAMPTZ;
            """)
        cur.execute("""
            UPDATE cached_links
            SET last_active_utc = COALESCE(last_active_utc, fetched_at_utc);
            """)
        cur.execute("""
            WITH latest AS (
                SELECT source, max(fetched_at_utc) AS ts
                FROM cached_links
                GROUP BY source
            )
            UPDATE cached_links
            SET is_active = (cached_links.fetched_at_utc = latest.ts)
            FROM latest
            WHERE cached_links.source = latest.source
              AND latest.ts IS NOT NULL;
            """)
    conn.commit()


def _parse_scraped_at(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def add_email_subscriber(
    email: str, source: str = "unknown", logger: Logger | None = None
) -> bool:
    _require_psycopg()
    normalized = email.strip().lower()
    if not normalized:
        return False

    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO email_subscribers (email, source, created_at_utc)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id;
                """,
                (normalized, source, datetime.now(timezone.utc)),
            )
            created = cur.fetchone() is not None
        conn.commit()

    if logger:
        if created:
            logger.info(f"Added email subscriber: {normalized}")
        else:
            logger.info(f"Email already subscribed: {normalized}")
    return created


def get_email_subscribers(logger: Logger | None = None) -> list[str]:
    _require_psycopg()
    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT email
                FROM email_subscribers
                ORDER BY created_at_utc ASC;
                """
            )
            rows = cur.fetchall()
    emails = [str(row[0]).strip().lower() for row in rows if row and row[0]]
    if logger:
        logger.info(f"Loaded {len(emails)} email subscribers from DB.")
    return emails


def store_profiles_in_db(profiles: Iterable[DogProfile], logger: Logger) -> None:
    _require_psycopg()
    profiles = list(profiles)
    if not profiles:
        return

    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO dog_profiles (
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
                )
                VALUES (
                    %(dog_id)s,
                    %(url)s,
                    %(name)s,
                    %(breed)s,
                    %(gender)s,
                    %(age_raw)s,
                    %(age_months)s,
                    %(weight_lbs)s,
                    %(location)s,
                    %(status)s,
                    %(ratings)s,
                    %(description)s,
                    %(media)s,
                    %(scraped_at_utc)s
                )
                ON CONFLICT (dog_id, scraped_at_utc) DO NOTHING;
                """,
                [
                    {
                        "dog_id": p.dog_id,
                        "url": p.url,
                        "name": p.name,
                        "breed": p.breed,
                        "gender": p.gender,
                        "age_raw": p.age_raw,
                        "age_months": p.age_months,
                        "weight_lbs": p.weight_lbs,
                        "location": p.location,
                        "status": p.status,
                        "ratings": Json(p.ratings),
                        "description": p.description,
                        "media": Json(
                            {
                                "images": p.media.images,
                                "videos": p.media.videos,
                                "embeds": p.media.embeds,
                            }
                        ),
                        "scraped_at_utc": _parse_scraped_at(p.scraped_at_utc),
                    }
                    for p in profiles
                ],
            )
        conn.commit()
    if logger:
        logger.info(f"Stored {len(profiles)} profiles.")


def store_dog_status(
    source: str, links: list[str], logger: Logger | None = None
) -> None:
    _require_psycopg()
    unique_links = sorted(set(links))
    with get_connection() as conn:
        ensure_schema(conn)
        fetched_at = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE dog_status
                SET is_active = false
                WHERE is_active = true
                  AND source = %s;
                """, (source,))
            if unique_links:
                cur.executemany(
                    """
                    INSERT INTO dog_status (
                        id,
                        source,
                        link,
                        is_active,
                        last_active_utc
                    )
                    VALUES (%s, %s, %s, true, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET source = EXCLUDED.source,
                            link = EXCLUDED.link,
                            is_active = true,
                            last_active_utc = EXCLUDED.last_active_utc;
                    """,
                    [
                        (_status_id(source, link), source, link, fetched_at)
                        for link in unique_links
                    ],
                )
        conn.commit()
    if logger:
        if unique_links:
            logger.info(
                f"Stored {len(unique_links)} active dog links for {source}."
            )
        else:
            logger.info(f"Marked dog links inactive for {source} (empty batch).")

def get_cached_links(
    source: str, max_age_seconds: int, logger: Logger | None = None
) -> list[str] | None:
    _require_psycopg()
    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT max(fetched_at_utc)
                FROM cached_links
                WHERE is_active = true
                  AND source = %s;
                """, (source,))
            row = cur.fetchone()
            if not row or row[0] is None:
                if logger:
                    logger.info(f"No cached links found in Postgres for {source}.")
                return None
            (fetched_at,) = row
            age_seconds = (datetime.now(fetched_at.tzinfo) - fetched_at).total_seconds()
            if age_seconds > max_age_seconds:
                if logger:
                    logger.info(
                        f"Cached links for {source} are stale (age {age_seconds:.0f}s)."
                    )
                return None
            cur.execute("""
                SELECT link
                FROM cached_links
                WHERE is_active = true
                  AND source = %s
                ORDER BY link;
                """, (source,))
            links = [row[0] for row in cur.fetchall()]
            if logger:
                logger.info(
                    f"Using cached links for {source} from Postgres (age {age_seconds:.0f}s)."
                )
            return list(links)


def store_cached_links(
    source: str, links: list[str], logger: Logger | None = None
) -> None:
    _require_psycopg()
    unique_links = sorted(set(links))
    with get_connection() as conn:
        ensure_schema(conn)
        fetched_at = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE cached_links
                SET is_active = false
                WHERE is_active = true
                  AND source = %s;
                """, (source,))
            if unique_links:
                cur.executemany(
                    """
                    INSERT INTO cached_links (
                        id,
                        source,
                        link,
                        fetched_at_utc,
                        is_active,
                        last_active_utc
                    )
                    VALUES (%s, %s, %s, %s, true, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET fetched_at_utc = EXCLUDED.fetched_at_utc,
                            link = EXCLUDED.link,
                            source = EXCLUDED.source,
                            is_active = true,
                            last_active_utc = EXCLUDED.last_active_utc;
                    """,
                    [
                        (_link_id(link), source, link, fetched_at, fetched_at)
                        for link in unique_links
                    ],
                )
        conn.commit()
    if logger:
        if unique_links:
            logger.info(
                f"Stored {len(unique_links)} cached links in Postgres for {source}."
            )
        else:
            logger.info(f"Marked cached links inactive for {source} (empty batch).")
