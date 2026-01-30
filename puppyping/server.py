import argparse
import os
import time
from datetime import datetime, timedelta
import logging

from .db import store_profiles
from .emailer import send_email
from .puppy_scraper import (
    __safe_less_than,
    CACHE_TIME,
    cache,
    fetch_adoptable_dog_profile_links,
    fetch_dog_profile,
)

logger = logging.getLogger(__name__)


def run_once() -> None:
    """Run one scrape/email cycle."""
    logger.info("Starting scrape run.")
    links = fetch_adoptable_dog_profile_links()
    profiles = [fetch_dog_profile(u) for u in links]

    filtered_profiles = [p for p in profiles if __safe_less_than(p.age_months, 8)]
    store_profiles(profiles)
    logger.info("Stored %d profiles.", len(profiles))
    _ = [
        send_email(filtered_profiles, send_to=sending)
        for sending in os.environ["EMAILS_TO"].split(",")
    ]
    logger.info("Sent emails to %d recipients.", len(os.environ["EMAILS_TO"].split(",")))


def run_once_no_email() -> None:
    """Run one scrape/store cycle without sending email."""
    logger.info("Starting scrape run (no email).")
    links = fetch_adoptable_dog_profile_links()
    profiles = [fetch_dog_profile(u) for u in links]

    store_profiles(profiles)
    logger.info("Stored %d profiles.", len(profiles))


def main() -> None:
    """CLI entrypoint for scraping and optional email output."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
    args = parser.parse_args()

    if args.clear_cache:
        cache.clear()
        print("Cache cleared.")

    if args.once:
        run_once() if not args.no_email else run_once_no_email()
        return

    while True:
        now = datetime.now().astimezone()
        next_run = now.replace(hour=13, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)

        sleep_for = (next_run - now).total_seconds()
        time.sleep(max(0, sleep_for))

        try:
            run_once() if not args.no_email else run_once_no_email()
        except Exception as exc:
            print(f"Run failed: {exc}")


if __name__ == "__main__":
    main()
