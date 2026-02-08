from __future__ import annotations

from typing import Callable

from .paws import fetch_adoptable_dog_profile_links_paws, fetch_dog_profile_paws
from .wrightway import fetch_adoptable_dog_profile_links_wrightway, fetch_dog_profile_wrightway
from ..models import DogProfile


FETCH_LINKS: dict[str, Callable[[], set[str]]] = {
    "paws_chicago": fetch_adoptable_dog_profile_links_paws,
    "wright_way": fetch_adoptable_dog_profile_links_wrightway,
}

FETCH_PROFILE: dict[str, Callable[[str], object]] = {
    "paws_chicago": fetch_dog_profile_paws,
    "wright_way": fetch_dog_profile_wrightway,
}


def fetch_adoptable_dog_profile_links(source: str, store_in_db: bool) -> set[str]:
    try:
        return FETCH_LINKS[source](store_in_db=store_in_db)
    except KeyError as e:
        raise ValueError(f"Unknown source='{source}'. Options: {sorted(FETCH_LINKS)}") from e


def fetch_dog_profile(source: str, url: str) -> DogProfile:
    try:
        return FETCH_PROFILE[source](url)
    except KeyError as e:
        raise ValueError(f"Unknown source='{source}'. Options: {sorted(FETCH_PROFILE)}") from e
