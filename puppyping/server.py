import argparse
import os
import time
from datetime import datetime, timedelta
import logging
from typing import Optional

from .db import store_profiles_in_db
from .emailer import send_email
from .puppy_scraper import (
    CACHE_TIME,
    cache,
    fetch_adoptable_dog_profile_links,
    fetch_dog_profile,
)
from tqdm import tqdm

logger = logging.getLogger(__name__)


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
    send_mail: bool = True, store_in_db: bool = True, max_age: float = 8.0
) -> None:
    """Run one scrape/email cycle."""
    logger.info(f"Starting scrape run.")
    links = fetch_adoptable_dog_profile_links()
    profiles = [fetch_dog_profile(u) for u in tqdm(links, desc="Fetching profiles")]

    filtered_profiles = [p for p in profiles if __safe_less_than(p.age_months, max_age)]
    if store_in_db:
        store_profiles_in_db(filtered_profiles, logger=logger)
    if send_email:
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
    send_mail = not args.no_email

    if args.once:
        run(send_mail=send_mail, store_in_db=store_in_db)
        return

    while True:
        now = datetime.now().astimezone()
        next_run = now.replace(hour=13, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)

        sleep_for = (next_run - now).total_seconds()
        time.sleep(max(0, sleep_for))

        try:
            run(send_mail=send_mail, store_in_db=store_in_db)
        except Exception as exc:
            print(f"Run failed: {exc}")


if __name__ == "__main__":
    main()
