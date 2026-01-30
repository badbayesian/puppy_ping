"""
PAWS Chicago scraper with:
- Disk-backed caching (diskcache) + TTL
- Readable dataclass print output
- argparse support with --clear-cache
"""

from __future__ import annotations

import argparse
import re
from typing import Optional
from urllib.parse import urljoin
import os

import logging
import requests
from bs4 import BeautifulSoup
from diskcache import Cache
from dotenv import load_dotenv

try:
    from .models import DogMedia, DogProfile
    from .db import get_cached_links, store_cached_links
except ImportError:  # Allows running as a script: python puppyping/puppy_scraper.py
    from models import DogMedia, DogProfile
    from db import get_cached_links, store_cached_links


load_dotenv()

logger = logging.getLogger(__name__)

# ===========================
# Constants
# ===========================

PAWS_AVAILABLE_URL = "https://www.pawschicago.org/our-work/pets-adoption/pets-available"
DOG_PROFILE_PATH_RE = re.compile(r"^/pet-available-for-adoption/showdog/\d+$")
CANTO_IMAGE_PREFIX = "https://pawschicago.canto.com/direct/image/"
CACHE_TIME = 24 * 60 * 60  # 24 hours


# ===========================
# Cache
# ===========================

cache = Cache("./data/cache/paws")


def cached(ttl_seconds: int):
    """Return a decorator that caches results for ttl_seconds.

    Args:
        ttl_seconds: Cache TTL in seconds.

    Returns:
        A decorator that caches function results.
    """

    def decorator(fn):
        """Wrap a function with diskcache lookup.

        Args:
            fn: Callable to wrap.

        Returns:
            Wrapped callable using diskcache.
        """

        def wrapper(*args, **kwargs):
            """Return cached value or compute and store it.

            Args:
                *args: Positional args forwarded to the wrapped function.
                **kwargs: Keyword args forwarded to the wrapped function.

            Returns:
                Cached or freshly computed value.
            """
            key = (fn.__name__, args, tuple(sorted(kwargs.items())))
            try:
                hit = cache.get(key)
            except Exception:
                cache.delete(key)
                hit = None
            if hit is not None:
                return hit
            val = fn(*args, **kwargs)
            cache.set(key, val, expire=ttl_seconds)
            return val

        return wrapper

    return decorator


# ===========================
# HTTP + helpers
# ===========================


def _get_soup(url: str) -> BeautifulSoup:
    """Fetch a URL and parse HTML into BeautifulSoup.

    Args:
        url: Page URL to fetch.

    Returns:
        Parsed BeautifulSoup document.
    """
    headers = {
        "User-Agent": "paws-scraper/1.0 (+respectful; non-commercial)",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _get_name(soup: BeautifulSoup) -> Optional[str]:
    """Extract a name from the page title.

    Args:
        soup: Parsed HTML document.

    Returns:
        The extracted name, if available.
    """
    for h in soup.select("title"):
        title_text = h.get_text(strip=True)
        return title_text.split("|", 1)[0].strip()


def _parse_age_to_months(age: str | None) -> float | None:
    """Convert an age string into total months.

    Args:
        age: Raw age text (e.g., "2 years 3 months").

    Returns:
        Age in months, or None if not parseable.
    """
    if not age:
        return None

    s = age.lower()

    patterns = [
        (r"(\d+(?:\.\d+)?)\s*year", 12),
        (r"(\d+(?:\.\d+)?)\s*months", 1),
    ]

    total_months = 0.0
    matched = False

    for pattern, multiplier in patterns:
        for m in re.finditer(pattern, s):
            total_months += float(m.group(1)) * multiplier
            matched = True

    return round(total_months, 2) if matched else None


def _clean_text(s: str) -> str:
    """Normalize whitespace in text.

    Args:
        s: Input string.

    Returns:
        Normalized string with single spaces.
    """
    return re.sub(r"\s+", " ", s).strip()


def _parse_weight_lbs(raw: Optional[str]) -> Optional[float]:
    """Parse the first numeric weight value from text.

    Args:
        raw: Raw weight string (e.g., "35 lbs").

    Returns:
        Weight as float, or None if missing.
    """
    if not raw:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else None


def _find_label_value(soup: BeautifulSoup, label: str) -> Optional[str]:
    """Find a labeled value in page text (Label: Value).

    Args:
        soup: Parsed HTML document.
        label: Label to match.

    Returns:
        The matched value, if found.
    """
    text = soup.get_text("\n", strip=True)
    m = re.search(rf"^{label}\s*:?\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    return _clean_text(m.group(1)) if m else None


def _extract_single_rating(soup: BeautifulSoup, label: str) -> Optional[int]:
    """Extract the rating value for a single category.

    Args:
        soup: Parsed HTML document.
        label: Rating label name.

    Returns:
        Rating value 1-5 or None.
    """
    active = soup.select_one(f"div.{label} span.rating_default span.active")
    try:
        m = re.search(r"\br(\d)\b", " ".join(active.get("class", [])))
        m = int(m.group(1)) if m else None
    except AttributeError:
        m = None
    if m == "=E2=80=94":
        m = None
    return m


def _extract_ratings(soup: BeautifulSoup) -> dict[str, Optional[int]]:
    """Extract all rating categories into a dict.

    Args:
        soup: Parsed HTML document.

    Returns:
        Mapping of rating category to value.
    """
    categories = ["children", "dogs", "cats", "home_alone", "activity", "environment"]

    return {cat: _extract_single_rating(soup, cat) for cat in categories}


def _extract_description(soup: BeautifulSoup) -> Optional[str]:
    """Return the first long paragraph as a description.

    Args:
        soup: Parsed HTML document.

    Returns:
        Description text or None.
    """
    for p in soup.select("p"):
        t = _clean_text(p.get_text())
        if len(t) > 80:
            return t
    return None


def _extract_media(url: str, soup: BeautifulSoup) -> DogMedia:
    """Collect image, video, and embed URLs from the page.

    Args:
        url: Base page URL.
        soup: Parsed HTML document.

    Returns:
        DogMedia with collected URLs.
    """
    images, videos, embeds = set(), set(), set()

    for img in soup.select("img[src]"):
        src = urljoin(url, img["src"])
        if src.startswith(CANTO_IMAGE_PREFIX):
            images.add(src)

    for v in soup.select("video[src], video source[src]"):
        videos.add(urljoin(url, v["src"]))

    for iframe in soup.select("iframe[src]"):
        embeds.add(urljoin(url, iframe["src"]))

    for a in soup.select("a[href]"):
        if re.search(r"\.(mp4|mov|m4v)$", a["href"], re.I):
            videos.add(urljoin(url, a["href"]))

    return DogMedia(sorted(images), sorted(videos), sorted(embeds))


def fetch_adoptable_dog_profile_links() -> set[str]:
    """Fetch the adoptable dog profile links from PAWS.

    Returns:
        Set of profile URLs.
    """
    cached_links = None
    try:
        cached_links = get_cached_links(CACHE_TIME, logger=logger)
    except Exception:
        cached_links = None

    if cached_links:
        logger.info(f"Using cached links from Postgres (fresh).")
        return set(cached_links)

    try:
        soup = _get_soup(PAWS_AVAILABLE_URL)
        links = set(
            sorted(
                urljoin(PAWS_AVAILABLE_URL, a["href"])
                for a in soup.select("a[href]")
                if DOG_PROFILE_PATH_RE.match(a["href"])
            )
        )
        logger.info(f"Fetched {len(links)} live links from PAWS.")
        try:
            store_cached_links(sorted(links), logger=logger)
            logger.info(f"Stored {len(links)} links in Postgres cache.")
        except Exception:
            logger.exception(f"Failed to store links in Postgres cache.")
            pass
        return links
    except Exception:
        logger.exception(f"Live fetch failed; falling back to cached links.")
        # Fall back to last cached value even if stale or cache read previously failed.
        try:
            cached_links = get_cached_links(CACHE_TIME * 365, logger=logger)
        except Exception:
            cached_links = None
        if cached_links:
            logger.info(f"Using cached links from Postgres (stale).")
            return set(cached_links)
        raise


@cached(ttl_seconds=CACHE_TIME)
def fetch_dog_profile(url: str) -> DogProfile:
    """Fetch and parse a single dog profile.

    Args:
        url: Dog profile URL.

    Returns:
        Parsed DogProfile.
    """
    logger.info(f"Fetching dog profile: {url}")
    soup = _get_soup(url)
    dog_id_match = re.search(r"/showdog/(\d+)", url)
    dog_id = int(dog_id_match.group(1))

    return DogProfile(
        dog_id=dog_id,
        url=url,
        name=_get_name(soup),
        breed=_find_label_value(soup, "Breed"),
        gender=_find_label_value(soup, "Gender"),
        age_raw=_find_label_value(soup, "Age"),
        age_months=_parse_age_to_months(_find_label_value(soup, "Age")),
        weight_lbs=_parse_weight_lbs(_find_label_value(soup, "Weight")),
        location=_find_label_value(soup, "Location"),
        status=_find_label_value(soup, "Status"),
        ratings=_extract_ratings(soup),
        description=_extract_description(soup),
        media=_extract_media(url, soup),
    )
