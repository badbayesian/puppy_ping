from __future__ import annotations

from logging import Logger
import os
from datetime import datetime, timezone
from typing import Iterable

import psycopg
from psycopg.types.json import Json

from .models import DogProfile


def _get_pg_config() -> dict[str, str | int]:
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", "postgres"),
        "dbname": os.environ.get("PGDATABASE", "puppyping"),
    }


def get_connection() -> psycopg.Connection:
    return psycopg.connect(**_get_pg_config())


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
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
                id BIGSERIAL PRIMARY KEY,
                links JSONB NOT NULL,
                fetched_at_utc TIMESTAMPTZ NOT NULL
            );
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_dog_profiles_scraped_at
            ON dog_profiles (scraped_at_utc DESC);
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cached_links_fetched_at
            ON cached_links (fetched_at_utc DESC);
            """)
    conn.commit()


def _parse_scraped_at(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def store_profiles_in_db(profiles: Iterable[DogProfile], logger: Logger) -> None:
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


def get_cached_links(
    max_age_seconds: int, logger: Logger | None = None
) -> list[str] | None:
    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT links, fetched_at_utc
                FROM cached_links
                ORDER BY fetched_at_utc DESC
                LIMIT 1;
                """)
            row = cur.fetchone()
            if not row:
                if logger:
                    logger.info(f"No cached links found in Postgres.")
                return None
            links, fetched_at = row
            age_seconds = (datetime.now(fetched_at.tzinfo) - fetched_at).total_seconds()
            if age_seconds > max_age_seconds:
                if logger:
                    logger.info(f"Cached links are stale (age {age_seconds:.0f}s).")
                return None
            if logger:
                logger.info(
                    f"Using cached links from Postgres (age {age_seconds:.0f}s)."
                )
            return list(links)


def store_cached_links(links: list[str], logger: Logger | None = None) -> None:
    with get_connection() as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cached_links (links, fetched_at_utc)
                VALUES (%s, %s);
                """,
                (Json(links), datetime.now(timezone.utc)),
            )
        conn.commit()
    if logger:
        logger.info(f"Stored {len(links)} cached links in Postgres.")
