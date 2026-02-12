import argparse
import os
import logging
from typing import Optional

from .db import get_email_subscribers, store_dog_status, store_profiles_in_db
from .email_utils import parse_email_list, sanitize_emails
from .emailer import send_email
from .providers import (
    fetch_adoptable_dog_profile_links,
    fetch_dog_profile,
)
from tqdm import tqdm

logger = logging.getLogger(__name__)

SOURCES = ("paws_chicago", "wright_way")


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
    profiles = []
    failed_profiles = 0
    for source, urls in links_by_source.items():
        for url in tqdm(urls, desc=f"Fetching profiles for {source}"):
            try:
                profiles.append(fetch_dog_profile(source, url))
            except Exception as exc:
                failed_profiles += 1
                logger.warning(f"Skipping profile due to fetch error for {url}: {exc}")

    if failed_profiles:
        logger.warning(f"Skipped {failed_profiles} profile(s) due to fetch errors.")

    filtered_profiles = [p for p in profiles if __safe_less_than(p.age_months, max_age)]
    if store_in_db:
        # Store all scraped profiles; email filtering happens separately.
        store_profiles_in_db(profiles, logger=logger)
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
    args = parser.parse_args()

    if args.clear_cache:
        cache.clear()
        print("Cache cleared.")

    store_in_db = not args.no_storage
    send_ping = not args.no_email
    

    run(send_ping=send_ping, store_in_db=store_in_db)


if __name__ == "__main__":
    main()
