"""
PAWS Chicago scraper with:
- Disk-backed caching (diskcache) + TTL
- Readable dataclass print output
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import logging
from diskcache import Cache
from dotenv import load_dotenv

from .scrape_helpers import (
    _get_soup,
    _get_name,
    _parse_age_to_months,
    _parse_weight_lbs,
    _find_label_value,
    _extract_ratings,
    _extract_description,
    _extract_media,
)

try:
    from ..models import DogMedia, DogProfile
    from ..db import get_cached_links, store_cached_links
except ImportError:  # Allows running as a script: python puppyping/puppy_scraper.py
    from models import DogMedia, DogProfile
    from db import get_cached_links, store_cached_links


load_dotenv()

logger = logging.getLogger(__name__)

# ===========================
# Constants
# ===========================

DOG_SOURCE = "paws_chicago"
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



def fetch_adoptable_dog_profile_links_paws() -> set[str]:
    """Fetch the adoptable dog profile links from PAWS.

    Returns:
        Set of profile URLs.
    """
    cached_links = None
    try:
        cached_links = get_cached_links(DOG_SOURCE, CACHE_TIME, logger=logger)
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
            store_cached_links(DOG_SOURCE, sorted(links), logger=logger)
            logger.info(f"Stored {len(links)} links in Postgres cache.")
        except Exception:
            logger.exception(f"Failed to store links in Postgres cache.")
            pass
        return links
    except Exception:
        logger.exception(f"Live fetch failed; falling back to cached links.")
        # Fall back to last cached value even if stale or cache read previously failed.
        try:
            cached_links = get_cached_links(DOG_SOURCE, CACHE_TIME * 365, logger=logger)
        except Exception:
            cached_links = None
        if cached_links:
            logger.info(f"Using cached links from Postgres (stale).")
            return set(cached_links)
        raise


@cached(ttl_seconds=CACHE_TIME)
def fetch_dog_profile_paws(url: str) -> DogProfile:
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
        media=_extract_media(url, soup, image_prefixes=(CANTO_IMAGE_PREFIX,)),
    )
   
