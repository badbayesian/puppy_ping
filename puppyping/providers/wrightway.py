from __future__ import annotations

import logging
import re

try:
    from ..models import DogMedia, DogProfile
    from ..db import get_cached_links, store_cached_links
except ImportError:  # Allows running as a script: python puppyping/puppy_scraper.py
    from models import DogMedia, DogProfile
    from db import get_cached_links, store_cached_links

from .utils import (
    _get_soup,
    _get_name,
    _parse_age_to_months,
    _parse_weight_lbs,
    _find_label_value,
    _extract_ratings,
    _extract_description,
    _extract_media,
)

logger = logging.getLogger(__name__)


_SHELTER_URL = "https://www.adoptapet.com/shelter/71498-wright-way-rescue-morton-grove-illinois"


def fetch_adoptable_dog_profile_links_wrightway() -> set[str]:
    """Fetch the adoptable dog profile links from Wright-Way Rescue.

    Returns:
        List of dog profile URLs.
    """
    cached = get_cached_links("wright_way")
    if cached is not None:
        return cached

    soup = _get_soup(_SHELTER_URL)
    profile_links = []
    for a in soup.select("a.pet-card-link"):
        href = a.get("href")
        if href and "/pet/" in href:
            profile_links.append(href)

    store_cached_links("wright_way", profile_links)
    return set(profile_links)

def fetch_dog_profile_wrightway(url: str) -> DogProfile:
    """Fetch a dog profile from Wright-Way Rescue.

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
