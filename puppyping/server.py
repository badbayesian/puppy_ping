import argparse
import concurrent.futures
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .db import (
    ensure_schema,
    get_email_subscribers,
    get_connection,
    store_pet_profiles_in_db,
    store_pet_status,
)
from .email_utils import parse_email_list, sanitize_emails
from .emailer import send_email
from .models import PetMedia, PetProfile
from .providers import (
    fetch_adoptable_pet_profile_links,
    fetch_pet_profile,
)
from tqdm import tqdm

logger = logging.getLogger(__name__)

SOURCES = ("paws_chicago", "wright_way", "anti_cruelty")

# Backward-compatible names for tests/callers that still patch dog-prefixed symbols.
store_dog_status = store_pet_status
store_profiles_in_db = store_pet_profiles_in_db
fetch_adoptable_dog_profile_links = fetch_adoptable_pet_profile_links
fetch_dog_profile = fetch_pet_profile


def __safe_less_than(a: Optional[float], b: float | int) -> bool:
    """Return True when a is not None and less than b.

    Args:
        a: Value that may be None.
        b: Threshold value.

    Returns:
        True if a is not None and a < b.
    """
    return a is not None and a < b


def _local_day_window_utc() -> tuple[datetime, datetime]:
    """Return UTC start/end timestamps for today's local day."""
    tz_name = (os.environ.get("TZ") or "").strip() or "UTC"
    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = timezone.utc
    now_local = datetime.now(local_tz)
    day_start_local = datetime(
        now_local.year,
        now_local.month,
        now_local.day,
        tzinfo=local_tz,
    )
    day_end_local = day_start_local + timedelta(days=1)
    return day_start_local.astimezone(timezone.utc), day_end_local.astimezone(
        timezone.utc
    )


def _load_scraped_profiles_for_source_today(source: str) -> list[PetProfile]:
    """Load today's latest profiles for a source from Postgres."""
    day_start_utc, day_end_utc = _local_day_window_utc()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (p.pet_id, COALESCE(p.species, ''))
                        p.pet_id,
                        COALESCE(p.species, 'dog') AS species,
                        p.url,
                        p.name,
                        p.breed,
                        p.gender,
                        p.age_raw,
                        p.age_months,
                        p.weight_lbs,
                        p.location,
                        p.status,
                        p.ratings,
                        p.description,
                        p.media,
                        p.scraped_at_utc
                    FROM pet_profiles AS p
                    JOIN pet_status AS s
                      ON s.link = p.url
                     AND s.source = %s
                     AND s.is_active = true
                    WHERE p.scraped_at_utc >= %s
                      AND p.scraped_at_utc < %s
                    ORDER BY p.pet_id, COALESCE(p.species, ''), p.scraped_at_utc DESC
                )
                SELECT
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
                FROM latest
                ORDER BY scraped_at_utc DESC, pet_id DESC;
                """,
                (source, day_start_utc, day_end_utc),
            )
            rows = cur.fetchall()

    profiles: list[PetProfile] = []
    for row in rows:
        raw_media = row[13] if isinstance(row[13], dict) else {}
        images = raw_media.get("images") if isinstance(raw_media, dict) else []
        videos = raw_media.get("videos") if isinstance(raw_media, dict) else []
        embeds = raw_media.get("embeds") if isinstance(raw_media, dict) else []
        profiles.append(
            PetProfile(
                dog_id=int(row[0]),
                species=str(row[1] or "dog"),
                url=str(row[2]),
                name=row[3],
                breed=row[4],
                gender=row[5],
                age_raw=row[6],
                age_months=float(row[7]) if row[7] is not None else None,
                weight_lbs=float(row[8]) if row[8] is not None else None,
                location=row[9],
                status=row[10],
                ratings=row[11] if isinstance(row[11], dict) else {},
                description=row[12],
                media=PetMedia(
                    images=[str(v) for v in (images or [])],
                    videos=[str(v) for v in (videos or [])],
                    embeds=[str(v) for v in (embeds or [])],
                ),
                scraped_at_utc=(
                    row[14].isoformat() if hasattr(row[14], "isoformat") else str(row[14])
                ),
            )
        )
    return profiles


def _scrape_source(
    source: str, store_in_db: bool, force: bool = False
) -> tuple[str, set[str], list, int]:
    """Fetch links and profiles for a single provider source.

    Args:
        source: Provider source key.
        store_in_db: Whether DB-related source behavior should be enabled.
        force: When True, scrape live even if source was already scraped today.

    Returns:
        Tuple of source key, fetched links, profiles, and failed profile count.
    """
    if store_in_db and not force:
        try:
            cached_profiles = _load_scraped_profiles_for_source_today(source)
        except Exception as exc:
            logger.warning(
                f"[{source}] Could not check existing same-day scrape; scraping live: {exc}"
            )
            cached_profiles = []
        if cached_profiles:
            cached_links = {profile.url for profile in cached_profiles if profile.url}
            logger.info(
                f"[{source}] Already scraped today; reusing {len(cached_profiles)} stored profiles."
            )
            return source, cached_links, cached_profiles, 0

    links = fetch_adoptable_pet_profile_links(source, store_in_db)
    ordered_links = sorted(links)
    total_links = len(ordered_links)
    if total_links == 0:
        logger.info(f"[{source}] No animals to scrape.")
        return source, links, [], 0

    logger.info(f"[{source}] Starting scrape for {total_links} animals.")
    profiles = []
    failed_profiles = 0
    for processed_count, url in enumerate(
        tqdm(ordered_links, desc=f"Fetching profiles for {source}"),
        start=1,
    ):
        try:
            profiles.append(fetch_pet_profile(source, url))
        except Exception as exc:
            failed_profiles += 1
            logger.warning(f"Skipping profile due to fetch error for {url}: {exc}")
        remaining_count = total_links - processed_count
        logger.info(
            f"[{source}] processed={processed_count} remaining={remaining_count}"
        )
    logger.info(
        f"[{source}] Completed scrape. success={len(profiles)} failed={failed_profiles} remaining=0"
    )
    return source, links, profiles, failed_profiles


def run(
    send_ping: bool = True,
    store_in_db: bool = True,
    max_age: float = 8.0,
    force: bool = False,
) -> None:
    """Run one scrape/email cycle."""
    logger.info(f"Starting scrape run.")
    if force:
        logger.info("Force mode enabled; scraping even if providers were scraped today.")
    if store_in_db:
        # Run schema DDL once before concurrent source work to avoid lock contention.
        with get_connection() as conn:
            ensure_schema(conn)

    links_by_source = {}
    profiles = []
    failed_profiles = 0
    max_workers = max(1, len(SOURCES))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_scrape_source, source, store_in_db, force)
            for source in SOURCES
        ]
        for future in concurrent.futures.as_completed(futures):
            source, links, source_profiles, source_failed_profiles = future.result()
            links_by_source[source] = links
            profiles.extend(source_profiles)
            failed_profiles += source_failed_profiles

    if store_in_db:
        for source, urls in links_by_source.items():
            store_pet_status(source, list(urls), logger=logger)

    if failed_profiles:
        logger.warning(f"Skipped {failed_profiles} profile(s) due to fetch errors.")

    filtered_profiles = [p for p in profiles if __safe_less_than(p.age_months, max_age)]
    if store_in_db:
        # Store all scraped profiles; email filtering happens separately.
        store_pet_profiles_in_db(profiles, logger=logger)
    if send_ping:
        configured = sanitize_emails(parse_email_list(os.environ.get("EMAILS_TO", "")))
        recipients = configured
        if store_in_db:
            try:
                subscribers = get_email_subscribers(logger=logger)
            except Exception as exc:
                logger.warning(f"Could not load DB subscribers: {exc}")
                subscribers = []
            recipients = sanitize_emails([*configured, *subscribers])

        if not recipients:
            logger.info("No valid email recipients configured.")
            return

        delivered = 0
        for sending in recipients:
            try:
                send_email(filtered_profiles, send_to=sending)
                delivered += 1
            except Exception as exc:
                logger.warning(f"Failed to send email to {sending}: {exc}")
        logger.info(
            f"Sent email to {delivered} recipients."
        )


def main() -> None:
    """CLI entrypoint for scraping and optional email output."""
    log_level = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear disk cache before running",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scrape/email cycle and exit (default behavior; flag is optional)",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip sending emails",
    )
    parser.add_argument(
        "--no-storage",
        action="store_true",
        help="Skip storing results in database",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force live scrape even if source was already scraped today",
    )
    args = parser.parse_args()

    if args.clear_cache:
        cache.clear()
        print("Cache cleared.")

    store_in_db = not args.no_storage
    send_ping = not args.no_email
    

    run(send_ping=send_ping, store_in_db=store_in_db, force=args.force)


if __name__ == "__main__":
    main()
