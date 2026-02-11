import argparse
import os
import time
from datetime import date, datetime, timedelta
import logging
from typing import Optional

from .db import get_email_subscribers, store_dog_status, store_profiles_in_db
from .emailer import send_email
from .providers import (
    fetch_adoptable_dog_profile_links,
    fetch_dog_profile,
)
from tqdm import tqdm

logger = logging.getLogger(__name__)

SOURCES = ("paws_chicago", "wright_way")
DAILY_RUN_HOUR = 13
DAILY_RUN_MINUTE = 0
SCHEDULER_POLL_SECONDS = 30


def __safe_less_than(a: Optional[float], b: float | int) -> bool:
    """Return True when a is not None and less than b.

    Args:
        a: Value that may be None.
        b: Threshold value.

    Returns:
        True if a is not None and a < b.
    """
    return a is not None and a < b


def run(
    send_ping: bool = True, store_in_db: bool = True, max_age: float = 8.0
) -> None:
    """Run one scrape/email cycle."""
    logger.info(f"Starting scrape run.")

    links_by_source = {
        source: fetch_adoptable_dog_profile_links(source, store_in_db) for source in SOURCES
    }
    if store_in_db:
        for source, urls in links_by_source.items():
            store_dog_status(source, list(urls), logger=logger)
    profiles = [
        fetch_dog_profile(source, url)
        for source, urls in links_by_source.items()
        for url in tqdm(urls, desc=f"Fetching profiles for {source}")
    ]

    filtered_profiles = [p for p in profiles if __safe_less_than(p.age_months, max_age)]
    if store_in_db:
        # Store all scraped profiles; email filtering happens separately.
        store_profiles_in_db(profiles, logger=logger)
    if send_ping:
        configured = [
            email.strip()
            for email in os.environ.get("EMAILS_TO", "").split(",")
            if email.strip()
        ]
        recipients = configured
        if store_in_db:
            try:
                subscribers = get_email_subscribers(logger=logger)
            except Exception as exc:
                logger.warning(f"Could not load DB subscribers: {exc}")
                subscribers = []
            recipients = list(
                dict.fromkeys([*configured, *[email for email in subscribers if email]])
            )

        _ = [send_email(filtered_profiles, send_to=sending) for sending in recipients]
        logger.info(
            f"Sent email to {len(recipients)} recipients."
        )


def _daily_run_time(now: datetime) -> datetime:
    """Return today's scheduled daily run timestamp in local time."""
    return now.replace(
        hour=DAILY_RUN_HOUR,
        minute=DAILY_RUN_MINUTE,
        second=0,
        microsecond=0,
    )


def _startup_daily_run_marker(now: datetime) -> date | None:
    """Mark startup run as today's daily run when startup is after 1:00 PM."""
    if now >= _daily_run_time(now):
        return now.date()
    return None


def _should_run_daily(now: datetime, last_daily_run_date: date | None) -> bool:
    """Return True when today's 1:00 PM run is due."""
    return now >= _daily_run_time(now) and last_daily_run_date != now.date()


def _sleep_seconds(now: datetime, last_daily_run_date: date | None) -> float:
    """Return a bounded scheduler sleep duration.

    This avoids a single long sleep so suspend/resume does not defer the run
    for hours after wake.
    """
    if _should_run_daily(now, last_daily_run_date):
        return 0.0

    today_run = _daily_run_time(now)
    if now < today_run and last_daily_run_date != now.date():
        remaining = (today_run - now).total_seconds()
    else:
        remaining = ((today_run + timedelta(days=1)) - now).total_seconds()

    return max(1.0, min(float(SCHEDULER_POLL_SECONDS), remaining))


def main() -> None:
    """CLI entrypoint for scraping and optional email output."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
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
        help="Run a single scrape/email cycle and exit",
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
    args = parser.parse_args()

    if args.clear_cache:
        cache.clear()
        print("Cache cleared.")

    store_in_db = not args.no_storage
    send_ping = not args.no_email
    

    run(send_ping=send_ping, store_in_db=store_in_db)

    if args.once:
        return

    # If startup completes after 1:00 PM, treat that startup run as today's
    # daily run and wait until tomorrow's 1:00 PM window.
    last_daily_run_date = _startup_daily_run_marker(datetime.now().astimezone())

    while True:
        now = datetime.now().astimezone()

        if not _should_run_daily(now, last_daily_run_date):
            time.sleep(_sleep_seconds(now, last_daily_run_date))
            continue

        try:
            run(send_ping=send_ping, store_in_db=store_in_db)
        except Exception as exc:
            print(f"Run failed: {exc}")
        finally:
            # Prevent retries every poll interval after a failed daily run.
            last_daily_run_date = now.date()


if __name__ == "__main__":
    main()
