import argparse
import os
import time
from datetime import datetime, timedelta
import logging
from typing import Optional

from .db import store_dog_status, store_profiles_in_db
from .emailer import send_email
from .providers import (
    fetch_adoptable_dog_profile_links,
    fetch_dog_profile,
)
from tqdm import tqdm

logger = logging.getLogger(__name__)

SOURCES = ("paws_chicago",)


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
        source: fetch_adoptable_dog_profile_links(source) for source in SOURCES
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
        _ = [
            send_email(filtered_profiles, send_to=sending)
            for sending in os.environ["EMAILS_TO"].split(",")
        ]
        logger.info(
            f"Sent email to {len(os.environ['EMAILS_TO'].split(','))} recipients."
        )


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

    while True:
        now = datetime.now().astimezone()
        next_run = now.replace(hour=13, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)

        sleep_for = (next_run - now).total_seconds()
        time.sleep(max(0, sleep_for))

        try:
            run(send_ping=send_ping, store_in_db=store_in_db)
        except Exception as exc:
            print(f"Run failed: {exc}")


if __name__ == "__main__":
    main()
