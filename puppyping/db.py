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

from .models import PetProfile
from .email_utils import sanitize_email, sanitize_emails


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


def _species_from_link(link: str) -> str:
    """Infer species from known provider URL patterns."""
    text = str(link or "").strip().lower()
    if "/showcat/" in text:
        return "cat"
    if "/showdog/" in text:
        return "dog"
    return "unknown"


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
            DO $$
            BEGIN
                IF to_regclass('public.pet_profiles') IS NULL
                   AND to_regclass('public.dog_profiles') IS NOT NULL THEN
                    ALTER TABLE dog_profiles RENAME TO pet_profiles;
                END IF;
                IF to_regclass('public.pet_status') IS NULL
                   AND to_regclass('public.dog_status') IS NOT NULL THEN
                    ALTER TABLE dog_status RENAME TO pet_status;
                END IF;
            END
            $$;
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pet_profiles (
                id BIGSERIAL PRIMARY KEY,
                pet_id INTEGER NOT NULL,
                species TEXT NOT NULL DEFAULT 'dog',
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
                UNIQUE (pet_id, species, scraped_at_utc)
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
            CREATE INDEX IF NOT EXISTS idx_pet_profiles_scraped_at
            ON pet_profiles (scraped_at_utc DESC);
            """)
        cur.execute("""
            ALTER TABLE pet_profiles
            ADD COLUMN IF NOT EXISTS species TEXT NOT NULL DEFAULT 'dog';
            """)
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'pet_profiles'
                      AND column_name = 'dog_id'
                ) THEN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'pet_profiles'
                          AND column_name = 'pet_id'
                    ) THEN
                        ALTER TABLE pet_profiles
                        ADD COLUMN pet_id INTEGER;
                    END IF;
                    UPDATE pet_profiles
                    SET pet_id = COALESCE(pet_id, dog_id)
                    WHERE pet_id IS NULL;
                END IF;
            END
            $$;
            """)
        cur.execute("""
            ALTER TABLE pet_profiles
            ALTER COLUMN pet_id SET NOT NULL;
            """)
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'dog_profiles_dog_id_scraped_at_utc_key'
                ) THEN
                    ALTER TABLE pet_profiles
                    DROP CONSTRAINT dog_profiles_dog_id_scraped_at_utc_key;
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'pet_profiles_dog_id_scraped_at_utc_key'
                ) THEN
                    ALTER TABLE pet_profiles
                    DROP CONSTRAINT pet_profiles_dog_id_scraped_at_utc_key;
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'pet_profiles_pet_id_species_scraped_at_utc_key'
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'dog_profiles_dog_id_species_scraped_at_utc_key'
                ) AND NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'pet_profiles_dog_id_species_scraped_at_utc_key'
                ) THEN
                    ALTER TABLE pet_profiles
                    ADD CONSTRAINT pet_profiles_pet_id_species_scraped_at_utc_key
                    UNIQUE (pet_id, species, scraped_at_utc);
                END IF;
            END
            $$;
            """)
        cur.execute("""
            ALTER TABLE pet_profiles
            DROP CONSTRAINT IF EXISTS pet_profiles_dog_id_species_scraped_at_utc_key;
            """)
        cur.execute("""
            ALTER TABLE pet_profiles
            DROP COLUMN IF EXISTS dog_id;
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pet_profiles_species
            ON pet_profiles (species);
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pet_profiles_pet_id
            ON pet_profiles (pet_id);
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
            CREATE TABLE IF NOT EXISTS emailed_pet_profiles (
                id BIGSERIAL PRIMARY KEY,
                recipient_email TEXT NOT NULL,
                pet_id INTEGER NOT NULL,
                species TEXT NOT NULL DEFAULT 'dog',
                first_sent_at_utc TIMESTAMPTZ NOT NULL,
                last_sent_at_utc TIMESTAMPTZ NOT NULL,
                send_count INTEGER NOT NULL DEFAULT 1,
                UNIQUE (recipient_email, pet_id, species)
            );
            """)
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'emailed_pet_profiles'
                      AND column_name = 'dog_id'
                ) THEN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'emailed_pet_profiles'
                          AND column_name = 'pet_id'
                    ) THEN
                        ALTER TABLE emailed_pet_profiles
                        ADD COLUMN pet_id INTEGER;
                    END IF;
                    UPDATE emailed_pet_profiles
                    SET pet_id = COALESCE(pet_id, dog_id)
                    WHERE pet_id IS NULL;
                END IF;
            END
            $$;
            """)
        cur.execute("""
            ALTER TABLE emailed_pet_profiles
            ALTER COLUMN pet_id SET NOT NULL;
            """)
        cur.execute("""
            ALTER TABLE emailed_pet_profiles
            DROP CONSTRAINT IF EXISTS emailed_pet_profiles_recipient_email_dog_id_species_key;
            """)
        cur.execute("""
            ALTER TABLE emailed_pet_profiles
            DROP CONSTRAINT IF EXISTS emailed_pet_profiles_recipient_email_pet_id_species_key;
            """)
        cur.execute("""
            ALTER TABLE emailed_pet_profiles
            ADD CONSTRAINT emailed_pet_profiles_recipient_email_pet_id_species_key
            UNIQUE (recipient_email, pet_id, species);
            """)
        cur.execute("""
            ALTER TABLE emailed_pet_profiles
            DROP COLUMN IF EXISTS dog_id;
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
            CREATE INDEX IF NOT EXISTS idx_emailed_pet_profiles_recipient_last_sent
            ON emailed_pet_profiles (recipient_email, last_sent_at_utc DESC);
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pet_status (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                link TEXT NOT NULL,
                species TEXT NOT NULL DEFAULT 'unknown',
                is_active BOOLEAN NOT NULL DEFAULT FALSE,
                last_active_utc TIMESTAMPTZ
            );
            """)
        cur.execute("""
            ALTER TABLE pet_status
            ADD COLUMN IF NOT EXISTS species TEXT NOT NULL DEFAULT 'unknown';
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pet_status_source_active
            ON pet_status (source, is_active);
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pet_status_species
            ON pet_status (species);
            """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pet_status_source_link
            ON pet_status (source, link);
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
    normalized = sanitize_email(email)
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
    emails = sanitize_emails(str(row[0]) for row in rows if row and row[0])
    if logger:
        logger.info(f"Loaded {len(emails)} email subscribers from DB.")
    return emails


def _normalize_species(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return normalized or "dog"


def get_sent_pet_keys(
    recipient_email: str, logger: Logger | None = None
) -> set[tuple[int, str]]:
    """Load previously emailed pet keys for one recipient."""
    _require_psycopg()
    recipient = sanitize_email(recipient_email)
    if not recipient:
        return set()

    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pet_id, species
                FROM emailed_pet_profiles
                WHERE recipient_email = %s;
                """,
                (recipient,),
            )
            rows = cur.fetchall()

    keys = {
        (int(row[0]), _normalize_species(str(row[1]) if row[1] is not None else None))
        for row in rows
        if row and row[0] is not None
    }
    if logger:
        logger.info(f"Loaded {len(keys)} emailed pet keys for {recipient}.")
    return keys


def mark_pet_profiles_emailed(
    recipient_email: str,
    profiles: Iterable[PetProfile],
    logger: Logger | None = None,
) -> None:
    """Record that profiles were included in an email to recipient."""
    _require_psycopg()
    recipient = sanitize_email(recipient_email)
    if not recipient:
        return

    deduped_keys: set[tuple[int, str]] = set()
    for profile in profiles:
        deduped_keys.add((int(profile.pet_id), _normalize_species(profile.species)))
    if not deduped_keys:
        return

    sent_at = datetime.now(timezone.utc)
    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO emailed_pet_profiles (
                    recipient_email,
                    pet_id,
                    species,
                    first_sent_at_utc,
                    last_sent_at_utc,
                    send_count
                )
                VALUES (%s, %s, %s, %s, %s, 1)
                ON CONFLICT (recipient_email, pet_id, species)
                DO UPDATE SET
                    last_sent_at_utc = EXCLUDED.last_sent_at_utc,
                    send_count = emailed_pet_profiles.send_count + 1;
                """,
                [
                    (recipient, pet_id, species, sent_at, sent_at)
                    for pet_id, species in sorted(deduped_keys)
                ],
            )
        conn.commit()
    if logger:
        logger.info(
            f"Updated emailed history for {len(deduped_keys)} pets to {recipient}."
        )


def store_profiles_in_db(profiles: Iterable[PetProfile], logger: Logger) -> None:
    _require_psycopg()
    profiles = list(profiles)
    if not profiles:
        return

    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO pet_profiles (
                    pet_id,
                    species,
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
                    %(pet_id)s,
                    %(species)s,
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
                ON CONFLICT (pet_id, species, scraped_at_utc) DO NOTHING;
                """,
                [
                    {
                        "pet_id": p.pet_id,
                        "species": p.species,
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


def store_pet_profiles_in_db(profiles: Iterable[PetProfile], logger: Logger) -> None:
    """Store scraped pet profiles in Postgres."""
    store_profiles_in_db(profiles, logger=logger)


def store_pet_status(
    source: str, links: list[str], logger: Logger | None = None
) -> None:
    _require_psycopg()
    unique_links = sorted(set(links))
    with get_connection() as conn:
        ensure_schema(conn)
        fetched_at = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE pet_status
                SET is_active = false
                WHERE is_active = true
                  AND source = %s;
                """, (source,))
            if unique_links:
                cur.executemany(
                    """
                    INSERT INTO pet_status (
                        id,
                        source,
                        link,
                        species,
                        is_active,
                        last_active_utc
                    )
                    VALUES (%s, %s, %s, %s, true, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET source = EXCLUDED.source,
                            link = EXCLUDED.link,
                            species = EXCLUDED.species,
                            is_active = true,
                            last_active_utc = EXCLUDED.last_active_utc;
                    """,
                    [
                        (
                            _status_id(source, link),
                            source,
                            link,
                            _species_from_link(link),
                            fetched_at,
                        )
                        for link in unique_links
                    ],
                )
        conn.commit()
    if logger:
        if unique_links:
            logger.info(
                f"Stored {len(unique_links)} active pet links for {source}."
            )
        else:
            logger.info(f"Marked pet links inactive for {source} (empty batch).")


def store_dog_status(
    source: str, links: list[str], logger: Logger | None = None
) -> None:
    """Backward-compatible alias for store_pet_status."""
    store_pet_status(source=source, links=links, logger=logger)

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
