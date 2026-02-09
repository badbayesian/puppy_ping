"""Wright-Way Rescue scraper provider."""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from diskcache import Cache

try:
    from .scrape_helpers import _clean, _extract_query_id, _get_soup
    from ..db import get_cached_links, store_cached_links
    from ..models import DogMedia, DogProfile
except ImportError:  # Allows running as a script
    from scrape_helpers import _clean, _extract_query_id, _get_soup
    from db import get_cached_links, store_cached_links
    from models import DogMedia, DogProfile


logger = logging.getLogger(__name__)

DOG_SOURCE = "wright_way"
START_URL = "https://wright-wayrescue.org/adoptable-pets"
CACHE_TIME = 24 * 60 * 60  # 24 hours

PROFILE_PATH_RE = re.compile(r"wsAdoptableAnimalDetails\.aspx", re.IGNORECASE)
LABELS = ("Animal ID", "Breed", "Gender", "Age", "Location", "Stage")

cache = Cache("./data/cache/wright_way")


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


def _extract_description(soup: BeautifulSoup) -> Optional[str]:
    """Extract the most likely profile description text.

    Args:
        soup: Parsed profile document.

    Returns:
        Profile description or None.
    """
    blocks = [
        _clean(el.get_text(" ", strip=True))
        for el in soup.select("p, div")
        if len(_clean(el.get_text(" ", strip=True))) >= 120
    ]
    return blocks[0] if blocks else None


def _extract_name(soup: BeautifulSoup, description: Optional[str]) -> Optional[str]:
    """Extract a likely dog name from heading, title, or description.

    Args:
        soup: Parsed profile document.
        description: Extracted long-form description.

    Returns:
        Name text or None.
    """
    for selector in ("h1", ".petName", ".pet-name", "title"):
        node = soup.select_one(selector)
        if not node:
            continue
        candidate = _clean(node.get_text(" ", strip=True).split("|", 1)[0])
        if candidate:
            return candidate

    if description:
        cleaned = _clean(
            description.replace(
                "Click a number to change picture or play to see a video", ""
            )
        )
        match = re.search(r"\bMeet\s+(.+?)(?:[.!-]|$)", cleaned, flags=re.IGNORECASE)
        if match:
            return _clean(match.group(1))
    return None


def _extract_label_values(soup: BeautifulSoup) -> dict[str, str]:
    """Extract known label/value fields from a profile page.

    Args:
        soup: Parsed profile document.

    Returns:
        Mapping of label to value text.
    """
    data: dict[str, str] = {}

    for tr in soup.select("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) >= 2:
            key = _clean(tds[0].get_text()).rstrip(":")
            val = _clean(tds[1].get_text())
            if key and val:
                data[key] = val

    text = soup.get_text("\n", strip=True)
    for label in LABELS:
        if label in data:
            continue
        match = re.search(rf"{re.escape(label)}\s*:\s*(.+)", text)
        if match:
            data[label] = _clean(match.group(1).split("\n")[0])

    return data


def _parse_age_months(age_raw: Optional[str]) -> Optional[float]:
    """Parse Petango age text into months.

    Args:
        age_raw: Raw age text from page.

    Returns:
        Age in months, or None if unavailable.
    """
    if not age_raw:
        return None

    text = age_raw.lower()

    def _grab(pattern: str) -> float:
        match = re.search(pattern, text)
        return float(match.group(1)) if match else 0.0

    years = _grab(r"(\d+(?:\.\d+)?)\s*years?")
    months = _grab(r"(\d+(?:\.\d+)?)\s*months?")
    weeks = _grab(r"(\d+(?:\.\d+)?)\s*weeks?")
    days = _grab(r"(\d+(?:\.\d+)?)\s*days?")

    total = years * 12 + months + weeks * (7 / 30) + days * (1 / 30)
    return round(total, 2) if total > 0 else None


def _extract_media(soup: BeautifulSoup, page_url: str) -> DogMedia:
    """Collect image/video/embed URLs from a profile page.

    Args:
        soup: Parsed profile document.
        page_url: Source profile URL.

    Returns:
        Extracted media bundle.
    """
    images = {urljoin(page_url, img["src"]) for img in soup.select("img[src]")}
    videos = {
        urljoin(page_url, tag["src"])
        for tag in soup.select("video[src], video source[src]")
    }
    embeds = {urljoin(page_url, frame["src"]) for frame in soup.select("iframe[src]")}
    return DogMedia(images=sorted(images), videos=sorted(videos), embeds=sorted(embeds))


def _fetch_live_links() -> set[str]:
    """Fetch current Wright-Way profile links from the adoptables page.

    Returns:
        Set of Petango profile URLs.
    """
    soup = _get_soup(START_URL)
    iframe = soup.find("iframe")
    if not iframe or not iframe.get("src"):
        raise RuntimeError("Petango iframe not found on Wright-Way adoptables page.")

    listing_url = urljoin(START_URL, iframe["src"])
    listing_soup = _get_soup(listing_url)
    links = {
        urljoin(listing_url, anchor["href"])
        for anchor in listing_soup.select("a[href]")
        if PROFILE_PATH_RE.search(anchor["href"])
    }
    return set(sorted(links))


def fetch_adoptable_dog_profile_links_wrightway(store_in_db: bool) -> set[str]:
    """Fetch current Wright-Way dog profile links.

    Args:
        store_in_db: Whether to use and update Postgres cache.

    Returns:
        Set of profile URLs.
    """
    cached_links = None
    if store_in_db:
        try:
            cached_links = get_cached_links(DOG_SOURCE, CACHE_TIME, logger=logger)
        except Exception:
            cached_links = None

    if cached_links:
        logger.info("Using cached links from Postgres (fresh).")
        return set(cached_links)

    try:
        links = _fetch_live_links()
        logger.info(f"Fetched {len(links)} live links from Wright-Way.")
        if store_in_db:
            try:
                store_cached_links(DOG_SOURCE, sorted(links), logger=logger)
                logger.info(f"Stored {len(links)} links in Postgres cache.")
            except Exception:
                logger.exception("Failed to store links in Postgres cache.")
        return links
    except Exception:
        logger.exception("Live fetch failed; falling back to cached links.")
        try:
            cached_links = get_cached_links(DOG_SOURCE, CACHE_TIME * 365, logger=logger)
        except Exception:
            cached_links = None
        if cached_links:
            logger.info("Using cached links from Postgres (stale).")
            return set(cached_links)
        raise


@cached(ttl_seconds=CACHE_TIME)
def fetch_dog_profile_wrightway(url: str) -> DogProfile:
    """Fetch and parse a single Wright-Way dog profile.

    Args:
        url: Profile URL.

    Returns:
        Parsed DogProfile.
    """
    logger.info(f"Fetching dog profile: {url}")
    soup = _get_soup(url)

    labels = _extract_label_values(soup)
    description = _extract_description(soup)
    age_raw = labels.get("Age")

    dog_id = _extract_query_id(url)
    if "Animal ID" in labels:
        match = re.search(r"\d+", labels["Animal ID"])
        if match:
            dog_id = int(match.group(0))
    if dog_id is None:
        raise ValueError(f"Missing dog_id for {url}")

    return DogProfile(
        dog_id=dog_id,
        url=url,
        name=_extract_name(soup, description),
        breed=labels.get("Breed"),
        gender=labels.get("Gender"),
        age_raw=age_raw,
        age_months=_parse_age_months(age_raw),
        weight_lbs=None,
        location=labels.get("Location"),
        status=labels.get("Stage"),
        ratings={},
        description=description,
        media=_extract_media(soup, url),
    )
