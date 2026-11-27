#!/usr/bin/env python
# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from puppyping.db import ensure_schema
from puppyping.pupswipe.repository import ensure_app_schema

PROFILE_FN_TO_SOURCE = {
    "fetch_dog_profile": "paws_chicago",
    "fetch_pet_profile_paws": "paws_chicago",
    "fetch_pet_profile_wrightway": "wright_way",
    "fetch_pet_profile_anti_cruelty": "anti_cruelty",
}
LINK_FN_TO_SOURCE = {
    "fetch_adoptable_dog_profile_links": "paws_chicago",
    "fetch_adoptable_pet_profile_links_paws": "paws_chicago",
    "fetch_adoptable_pet_profile_links_wrightway": "wright_way",
    "fetch_adoptable_pet_profile_links_anti_cruelty": "anti_cruelty",
}


def md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def infer_species_from_link(link: str | None) -> str:
    text = str(link or "").strip().lower()
    if "/showcat/" in text:
        return "cat"
    if "/showdog/" in text:
        return "dog"
    return "unknown"


def infer_source_from_profile_function(function_name: str | None) -> str | None:
    return PROFILE_FN_TO_SOURCE.get(str(function_name or "").strip())


def infer_source_from_link_function(function_name: str | None) -> str | None:
    return LINK_FN_TO_SOURCE.get(str(function_name or "").strip())


def normalize_source(value: str | None) -> str:
    return str(value or "").strip().lower() or "unknown"


def normalize_species(value: str | None, default: str = "unknown") -> str:
    return str(value or "").strip().lower() or default


def to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def max_dt(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_media(value: Any) -> dict[str, list[str]]:
    if isinstance(value, dict):
        images = value.get("images") or []
        videos = value.get("videos") or []
        embeds = value.get("embeds") or []
    else:
        images = getattr(value, "images", []) if value is not None else []
        videos = getattr(value, "videos", []) if value is not None else []
        embeds = getattr(value, "embeds", []) if value is not None else []
    return {
        "images": sorted({str(v).strip() for v in images if str(v).strip()}),
        "videos": sorted({str(v).strip() for v in videos if str(v).strip()}),
        "embeds": sorted({str(v).strip() for v in embeds if str(v).strip()}),
    }


def normalize_ratings(value: Any) -> dict[str, int | None]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int | None] = {}
    for key, item in value.items():
        name = str(key).strip()
        if not name:
            continue
        if item is None:
            out[name] = None
            continue
        try:
            out[name] = int(item)
        except (TypeError, ValueError):
            out[name] = None
    return out


class Accumulator:
    def __init__(self) -> None:
        self.pet_profiles: dict[tuple[int, str, datetime], dict[str, Any]] = {}
        self.cached_links: dict[str, dict[str, Any]] = {}
        self.pet_status: dict[str, dict[str, Any]] = {}
        self.sources_seen: set[str] = set()

    def add_profile(self, row: dict[str, Any]) -> None:
        key = (int(row["pet_id"]), str(row["species"]), row["scraped_at_utc"])
        current = self.pet_profiles.get(key)
        if current is None:
            self.pet_profiles[key] = row
            return
        current_score = sum(
            1 for name in ("name", "breed", "description") if current.get(name)
        )
        new_score = sum(1 for name in ("name", "breed", "description") if row.get(name))
        if new_score > current_score:
            self.pet_profiles[key] = row

    def add_link(
        self,
        source: str,
        link: str,
        fetched_at_utc: datetime,
        last_active_utc: datetime | None,
        is_active: bool,
    ) -> None:
        source = normalize_source(source)
        link = str(link or "").strip()
        if not link:
            return
        row_id = md5_hex(link)
        current = self.cached_links.get(row_id)
        if current is None:
            self.cached_links[row_id] = {
                "id": row_id,
                "source": source,
                "link": link,
                "fetched_at_utc": fetched_at_utc,
                "is_active": bool(is_active),
                "last_active_utc": max_dt(last_active_utc, fetched_at_utc),
            }
        else:
            if fetched_at_utc > current["fetched_at_utc"]:
                current["fetched_at_utc"] = fetched_at_utc
                current["source"] = source
            current["last_active_utc"] = max_dt(
                current.get("last_active_utc"), max_dt(last_active_utc, fetched_at_utc)
            )
            current["is_active"] = bool(current["is_active"]) or bool(is_active)
        self.sources_seen.add(source)

    def add_status(
        self,
        source: str,
        link: str,
        species: str,
        last_active_utc: datetime | None,
        is_active: bool,
    ) -> None:
        source = normalize_source(source)
        link = str(link or "").strip()
        if not link:
            return
        row_id = md5_hex(f"{source}:{link}")
        current = self.pet_status.get(row_id)
        normalized_species = normalize_species(
            species, default=infer_species_from_link(link)
        )
        if current is None:
            self.pet_status[row_id] = {
                "id": row_id,
                "source": source,
                "link": link,
                "species": normalized_species,
                "is_active": bool(is_active),
                "last_active_utc": last_active_utc,
            }
        else:
            current["last_active_utc"] = max_dt(
                current.get("last_active_utc"), last_active_utc
            )
            current["is_active"] = bool(current["is_active"]) or bool(is_active)
            if current.get("species") in (
                "",
                None,
                "unknown",
            ) and normalized_species not in ("", "unknown"):
                current["species"] = normalized_species
        self.sources_seen.add(source)


def table_exists(cur: psycopg.Cursor[Any], table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s);", (f"public.{table_name}",))
    row = cur.fetchone()
    if not row:
        return False
    if isinstance(row, dict):
        return next(iter(row.values())) is not None
    return row[0] is not None


def extract_legacy_source(
    source_conn: psycopg.Connection[Any], acc: Accumulator, warnings: list[str]
) -> dict[str, int]:
    stats = {"dog_profiles_rows": 0, "dog_status_rows": 0, "cached_links_rows": 0}
    with source_conn.cursor(row_factory=dict_row) as cur:
        if table_exists(cur, "dog_profiles"):
            cur.execute("""
                SELECT dog_id,url,name,breed,gender,age_raw,age_months,weight_lbs,location,status,ratings,description,media,scraped_at_utc
                FROM dog_profiles
                ORDER BY scraped_at_utc ASC;
                """)
            for row in cur.fetchall():
                scraped_at = to_dt(row.get("scraped_at_utc"))
                if scraped_at is None:
                    continue
                try:
                    pet_id = int(row.get("dog_id"))
                except (TypeError, ValueError):
                    continue
                url = str(row.get("url") or "").strip()
                if not url:
                    continue
                acc.add_profile(
                    {
                        "pet_id": pet_id,
                        "species": "dog",
                        "url": url,
                        "name": row.get("name"),
                        "breed": row.get("breed"),
                        "gender": row.get("gender"),
                        "age_raw": row.get("age_raw"),
                        "age_months": to_float(row.get("age_months")),
                        "weight_lbs": to_float(row.get("weight_lbs")),
                        "location": row.get("location"),
                        "status": row.get("status"),
                        "ratings": normalize_ratings(row.get("ratings")),
                        "description": row.get("description"),
                        "media": normalize_media(row.get("media")),
                        "scraped_at_utc": scraped_at,
                    }
                )
                stats["dog_profiles_rows"] += 1
        else:
            warnings.append("Source table dog_profiles was not found.")

        if table_exists(cur, "dog_status"):
            cur.execute("SELECT source,link,is_active,last_active_utc FROM dog_status;")
            for row in cur.fetchall():
                source = normalize_source(row.get("source"))
                link = str(row.get("link") or "").strip()
                if not link:
                    continue
                last_active = to_dt(row.get("last_active_utc"))
                acc.add_status(
                    source,
                    link,
                    infer_species_from_link(link),
                    last_active,
                    bool(row.get("is_active")),
                )
                stats["dog_status_rows"] += 1
        else:
            warnings.append("Source table dog_status was not found.")

        if table_exists(cur, "cached_links"):
            cur.execute(
                "SELECT source,link,fetched_at_utc,is_active,last_active_utc FROM cached_links;"
            )
            for row in cur.fetchall():
                source = normalize_source(row.get("source"))
                link = str(row.get("link") or "").strip()
                fetched_at = to_dt(row.get("fetched_at_utc"))
                if not link or fetched_at is None:
                    continue
                last_active = max_dt(to_dt(row.get("last_active_utc")), fetched_at)
                acc.add_link(
                    source, link, fetched_at, last_active, bool(row.get("is_active"))
                )
                stats["cached_links_rows"] += 1
        else:
            warnings.append("Source table cached_links was not found.")
    return stats


def profile_from_cached_object(
    obj: Any, fallback_time: datetime
) -> dict[str, Any] | None:
    pet_id_raw = getattr(obj, "pet_id", None)
    if pet_id_raw is None:
        pet_id_raw = getattr(obj, "dog_id", None)
    try:
        pet_id = int(pet_id_raw)
    except (TypeError, ValueError):
        return None
    url = str(getattr(obj, "url", "") or "").strip()
    if not url:
        return None
    return {
        "pet_id": pet_id,
        "species": normalize_species(getattr(obj, "species", None), default="dog"),
        "url": url,
        "name": getattr(obj, "name", None),
        "breed": getattr(obj, "breed", None),
        "gender": getattr(obj, "gender", None),
        "age_raw": getattr(obj, "age_raw", None),
        "age_months": to_float(getattr(obj, "age_months", None)),
        "weight_lbs": to_float(getattr(obj, "weight_lbs", None)),
        "location": getattr(obj, "location", None),
        "status": getattr(obj, "status", None),
        "ratings": normalize_ratings(getattr(obj, "ratings", None)),
        "description": getattr(obj, "description", None),
        "media": normalize_media(getattr(obj, "media", None)),
        "scraped_at_utc": to_dt(getattr(obj, "scraped_at_utc", None)) or fallback_time,
    }


def extract_cache_db(
    cache_db_path: Path, acc: Accumulator, warnings: list[str]
) -> dict[str, int]:
    stats = {
        "cache_rows_total": 0,
        "cache_rows_pickled": 0,
        "cache_rows_invalid_pickle": 0,
        "cache_profile_rows": 0,
        "cache_linkset_rows": 0,
    }
    if not cache_db_path.exists():
        warnings.append(f"Cache DB not found: {cache_db_path}")
        return stats
    conn = sqlite3.connect(str(cache_db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT key,value,store_time FROM Cache;")
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        warnings.append(f"Failed to read cache DB {cache_db_path}: {exc}")
        return stats
    finally:
        conn.close()
    for raw_key, raw_value, store_time in rows:
        stats["cache_rows_total"] += 1
        fallback_time = to_dt(store_time) or datetime.now(timezone.utc)
        try:
            key = pickle.loads(raw_key)
            value = pickle.loads(raw_value)
        except Exception:
            stats["cache_rows_invalid_pickle"] += 1
            continue
        stats["cache_rows_pickled"] += 1
        if not isinstance(key, tuple) or not key:
            continue
        fn = str(key[0] or "").strip()
        profile_source = infer_source_from_profile_function(fn)
        if profile_source is not None:
            profile = profile_from_cached_object(value, fallback_time=fallback_time)
            if profile is not None:
                acc.add_profile(profile)
                acc.add_link(
                    profile_source, profile["url"], fallback_time, fallback_time, True
                )
                acc.add_status(
                    profile_source,
                    profile["url"],
                    profile["species"],
                    fallback_time,
                    True,
                )
                stats["cache_profile_rows"] += 1
            continue
        link_source = infer_source_from_link_function(fn)
        if link_source is None or not isinstance(value, (set, list, tuple)):
            continue
        inserted = False
        for candidate in value:
            link = str(candidate or "").strip()
            if not link:
                continue
            acc.add_link(link_source, link, fallback_time, fallback_time, True)
            acc.add_status(
                link_source, link, infer_species_from_link(link), fallback_time, True
            )
            inserted = True
        if inserted:
            stats["cache_linkset_rows"] += 1
    return stats


def ensure_target_schema(target_conn: psycopg.Connection[Any]) -> None:
    ensure_schema(target_conn)
    ensure_app_schema(target_conn)


def fetch_target_counts(target_conn: psycopg.Connection[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with target_conn.cursor() as cur:
        for table in (
            "pet_profiles",
            "pet_status",
            "cached_links",
            "users",
            "pet_swipes",
            "pet_likes",
        ):
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            out[table] = int(cur.fetchone()[0])
        cur.execute(
            "SELECT source,COUNT(*) FROM pet_status GROUP BY source ORDER BY source;"
        )
        out["pet_status_by_source"] = {
            str(source): int(total) for source, total in cur.fetchall()
        }
        cur.execute(
            "SELECT source,COUNT(*) FROM cached_links WHERE is_active=true GROUP BY source ORDER BY source;"
        )
        out["cached_links_active_by_source"] = {
            str(source): int(total) for source, total in cur.fetchall()
        }
    return out


def fetch_existing_keys(
    target_conn: psycopg.Connection[Any],
) -> tuple[set[tuple[int, str, datetime]], set[str], set[str]]:
    with target_conn.cursor() as cur:
        cur.execute("SELECT pet_id,species,scraped_at_utc FROM pet_profiles;")
        profile_keys = {
            (int(pet_id), str(species), to_dt(scraped_at_utc))
            for pet_id, species, scraped_at_utc in cur.fetchall()
        }
        profile_keys = {key for key in profile_keys if key[2] is not None}
        cur.execute("SELECT id FROM cached_links;")
        link_ids = {str(row[0]) for row in cur.fetchall()}
        cur.execute("SELECT id FROM pet_status;")
        status_ids = {str(row[0]) for row in cur.fetchall()}
    return profile_keys, link_ids, status_ids


def build_projection(
    target_conn: psycopg.Connection[Any], acc: Accumulator
) -> dict[str, Any]:
    existing_profiles, existing_links, existing_status = fetch_existing_keys(
        target_conn
    )
    candidate_profiles = set(acc.pet_profiles.keys())
    candidate_links = set(acc.cached_links.keys())
    candidate_status = set(acc.pet_status.keys())
    return {
        "candidate_counts": {
            "pet_profiles": len(candidate_profiles),
            "cached_links": len(candidate_links),
            "pet_status": len(candidate_status),
        },
        "projected": {
            "pet_profiles_new_rows": len(candidate_profiles - existing_profiles),
            "pet_profiles_existing_rows": len(candidate_profiles & existing_profiles),
            "cached_links_new_rows": len(candidate_links - existing_links),
            "cached_links_existing_rows": len(candidate_links & existing_links),
            "pet_status_new_rows": len(candidate_status - existing_status),
            "pet_status_existing_rows": len(candidate_status & existing_status),
        },
    }


def reconcile_active_flags(
    target_conn: psycopg.Connection[Any], sources_seen: list[str]
) -> None:
    with target_conn.cursor() as cur:
        cur.execute(
            "UPDATE cached_links SET last_active_utc=COALESCE(last_active_utc,fetched_at_utc);"
        )
        cur.execute("""
            UPDATE pet_status
            SET species = CASE
                WHEN LOWER(link) LIKE '%/showcat/%' THEN 'cat'
                WHEN LOWER(link) LIKE '%/showdog/%' THEN 'dog'
                ELSE COALESCE(NULLIF(species,''), 'unknown')
            END
            WHERE species IS NULL OR species='' OR species='unknown';
            """)
        if sources_seen:
            cur.execute(
                """
                WITH link_state AS (
                    SELECT source,link,BOOL_OR(is_active) AS is_active,MAX(last_active_utc) AS last_active_utc
                    FROM cached_links
                    WHERE source = ANY(%s::text[])
                    GROUP BY source,link
                )
                UPDATE pet_status ps
                SET is_active = COALESCE(ls.is_active,false),
                    last_active_utc = COALESCE(
                        GREATEST(COALESCE(ps.last_active_utc, ls.last_active_utc), COALESCE(ls.last_active_utc, ps.last_active_utc)),
                        ps.last_active_utc,
                        ls.last_active_utc
                    )
                FROM link_state ls
                WHERE ps.source = ls.source
                  AND ps.link = ls.link;
                """,
                (sources_seen,),
            )
            cur.execute(
                """
                UPDATE pet_status ps
                SET is_active=false
                WHERE ps.source = ANY(%s::text[])
                  AND NOT EXISTS (
                      SELECT 1
                      FROM cached_links c
                      WHERE c.source=ps.source
                        AND c.link=ps.link
                        AND c.is_active=true
                  );
                """,
                (sources_seen,),
            )


def apply_recovery(
    target_conn: psycopg.Connection[Any], acc: Accumulator
) -> dict[str, int]:
    out = {
        "pet_profiles_attempted": 0,
        "cached_links_attempted": 0,
        "pet_status_attempted": 0,
    }
    profile_rows = list(acc.pet_profiles.values())
    if profile_rows:
        with target_conn.cursor() as cur:
            payload = []
            for row in profile_rows:
                payload.append(
                    {
                        "pet_id": row["pet_id"],
                        "species": row["species"],
                        "url": row["url"],
                        "name": row["name"],
                        "breed": row["breed"],
                        "gender": row["gender"],
                        "age_raw": row["age_raw"],
                        "age_months": row["age_months"],
                        "weight_lbs": row["weight_lbs"],
                        "location": row["location"],
                        "status": row["status"],
                        "ratings": Json(row["ratings"] or {}),
                        "description": row["description"],
                        "media": Json(
                            row["media"] or {"images": [], "videos": [], "embeds": []}
                        ),
                        "scraped_at_utc": row["scraped_at_utc"],
                    }
                )
            cur.executemany(
                """
                INSERT INTO pet_profiles (
                    pet_id,species,url,name,breed,gender,age_raw,age_months,weight_lbs,location,status,ratings,description,media,scraped_at_utc
                )
                VALUES (
                    %(pet_id)s,%(species)s,%(url)s,%(name)s,%(breed)s,%(gender)s,%(age_raw)s,%(age_months)s,%(weight_lbs)s,%(location)s,%(status)s,%(ratings)s,%(description)s,%(media)s,%(scraped_at_utc)s
                )
                ON CONFLICT (pet_id,species,scraped_at_utc) DO NOTHING;
                """,
                payload,
            )
        target_conn.commit()
        out["pet_profiles_attempted"] = len(profile_rows)
    link_rows = list(acc.cached_links.values())
    if link_rows:
        with target_conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO cached_links (id,source,link,fetched_at_utc,is_active,last_active_utc)
                VALUES (%(id)s,%(source)s,%(link)s,%(fetched_at_utc)s,%(is_active)s,%(last_active_utc)s)
                ON CONFLICT (id) DO UPDATE
                SET source=EXCLUDED.source,
                    link=EXCLUDED.link,
                    fetched_at_utc=GREATEST(cached_links.fetched_at_utc,EXCLUDED.fetched_at_utc),
                    is_active=(cached_links.is_active OR EXCLUDED.is_active),
                    last_active_utc=GREATEST(COALESCE(cached_links.last_active_utc,EXCLUDED.last_active_utc),EXCLUDED.last_active_utc);
                """,
                link_rows,
            )
        target_conn.commit()
        out["cached_links_attempted"] = len(link_rows)
    status_rows = list(acc.pet_status.values())
    if status_rows:
        with target_conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO pet_status (id,source,link,species,is_active,last_active_utc)
                VALUES (%(id)s,%(source)s,%(link)s,%(species)s,%(is_active)s,%(last_active_utc)s)
                ON CONFLICT (id) DO UPDATE
                SET source=EXCLUDED.source,
                    link=EXCLUDED.link,
                    species=COALESCE(NULLIF(EXCLUDED.species,''),pet_status.species),
                    is_active=(pet_status.is_active OR EXCLUDED.is_active),
                    last_active_utc=GREATEST(COALESCE(pet_status.last_active_utc,EXCLUDED.last_active_utc),EXCLUDED.last_active_utc);
                """,
                status_rows,
            )
        target_conn.commit()
        out["pet_status_attempted"] = len(status_rows)
    reconcile_active_flags(target_conn, sorted(acc.sources_seen))
    target_conn.commit()
    return out


def connect_pg(
    host: str, port: int, dbname: str, user: str, password: str
) -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=host, port=port, dbname=dbname, user=user, password=password
    )


def write_report(report_path: str | None, report: dict[str, Any]) -> None:
    if not report_path:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report,
            indent=2,
            default=lambda obj: (
                obj.isoformat() if isinstance(obj, datetime) else str(obj)
            ),
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover available PuppyPing data into a target Postgres DB."
    )
    parser.add_argument("--source-host", required=True)
    parser.add_argument("--source-port", required=True, type=int)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--source-user", required=True)
    parser.add_argument("--source-password", required=True)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--target-port", required=True, type=int)
    parser.add_argument("--target-db", required=True)
    parser.add_argument("--target-user", required=True)
    parser.add_argument("--target-password", required=True)
    parser.add_argument(
        "--cache-db",
        action="append",
        default=[],
        help="SQLite cache DB path; repeatable.",
    )
    parser.add_argument("--mode", choices=("dry-run", "apply"), required=True)
    parser.add_argument("--report-path")
    return parser.parse_args()


def run() -> int:
    args = parse_args()
    report: dict[str, Any] = {
        "mode": args.mode,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "source": {
                "host": args.source_host,
                "port": args.source_port,
                "db": args.source_db,
                "user": args.source_user,
            },
            "target": {
                "host": args.target_host,
                "port": args.target_port,
                "db": args.target_db,
                "user": args.target_user,
            },
            "cache_dbs": [str(Path(path)) for path in args.cache_db],
        },
        "warnings": [],
    }
    warnings = report["warnings"]
    acc = Accumulator()
    source_conn = connect_pg(
        args.source_host,
        args.source_port,
        args.source_db,
        args.source_user,
        args.source_password,
    )
    target_conn = connect_pg(
        args.target_host,
        args.target_port,
        args.target_db,
        args.target_user,
        args.target_password,
    )
    try:
        ensure_target_schema(target_conn)
        report["target_before"] = fetch_target_counts(target_conn)
        report["legacy_source_extract"] = extract_legacy_source(
            source_conn, acc, warnings
        )
        cache_extract: dict[str, dict[str, int]] = {}
        for raw_path in args.cache_db:
            cache_path = Path(raw_path)
            cache_extract[str(cache_path)] = extract_cache_db(cache_path, acc, warnings)
        report["cache_extract"] = cache_extract
        report["candidate_counts"] = {
            "pet_profiles": len(acc.pet_profiles),
            "cached_links": len(acc.cached_links),
            "pet_status": len(acc.pet_status),
            "sources_seen": sorted(acc.sources_seen),
        }
        report.update(build_projection(target_conn, acc))
        if args.mode == "apply":
            report["applied"] = apply_recovery(target_conn, acc)
            report["target_after"] = fetch_target_counts(target_conn)
        else:
            report["applied"] = {"skipped": True}
            report["target_after"] = report["target_before"]
    finally:
        source_conn.close()
        target_conn.close()
    write_report(args.report_path, report)
    print(f"MODE={args.mode}")
    print(
        "CANDIDATES "
        f"pet_profiles={report['candidate_counts']['pet_profiles']} "
        f"cached_links={report['candidate_counts']['cached_links']} "
        f"pet_status={report['candidate_counts']['pet_status']}"
    )
    projected = report["projected"]
    print(
        "PROJECTED "
        f"pet_profiles_new={projected['pet_profiles_new_rows']} "
        f"cached_links_new={projected['cached_links_new_rows']} "
        f"pet_status_new={projected['pet_status_new_rows']}"
    )
    if args.mode == "apply":
        after = report["target_after"]
        print(
            "TARGET_AFTER "
            f"pet_profiles={after['pet_profiles']} "
            f"cached_links={after['cached_links']} "
            f"pet_status={after['pet_status']}"
        )
    if warnings:
        print(f"WARNINGS={len(warnings)}")
        for warning in warnings:
            print(f"WARNING {warning}")
    if args.report_path:
        print(f"REPORT={args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
