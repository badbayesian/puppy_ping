from __future__ import annotations

from typing import Callable

from .anti_cruelty import (
    fetch_adoptable_pet_profile_links_anti_cruelty,
    fetch_pet_profile_anti_cruelty,
)
from .paws import fetch_adoptable_pet_profile_links_paws, fetch_pet_profile_paws
from .wrightway import (
    fetch_adoptable_pet_profile_links_wrightway,
    fetch_pet_profile_wrightway,
)
from ..models import PetProfile


FETCH_PET_LINKS: dict[str, Callable[[bool], set[str]]] = {
    "anti_cruelty": fetch_adoptable_pet_profile_links_anti_cruelty,
    "paws_chicago": fetch_adoptable_pet_profile_links_paws,
    "wright_way": fetch_adoptable_pet_profile_links_wrightway,
}

FETCH_PET_PROFILE: dict[str, Callable[[str], PetProfile]] = {
    "anti_cruelty": fetch_pet_profile_anti_cruelty,
    "paws_chicago": fetch_pet_profile_paws,
    "wright_way": fetch_pet_profile_wrightway,
}


def fetch_adoptable_pet_profile_links(source: str, store_in_db: bool) -> set[str]:
    try:
        return FETCH_PET_LINKS[source](store_in_db=store_in_db)
    except KeyError as e:
        raise ValueError(
            f"Unknown source='{source}'. Options: {sorted(FETCH_PET_LINKS)}"
        ) from e


def fetch_pet_profile(source: str, url: str) -> PetProfile:
    try:
        return FETCH_PET_PROFILE[source](url)
    except KeyError as e:
        raise ValueError(
            f"Unknown source='{source}'. Options: {sorted(FETCH_PET_PROFILE)}"
        ) from e


def fetch_adoptable_dog_profile_links(source: str, store_in_db: bool) -> set[str]:
    """Backward-compatible alias for fetch_adoptable_pet_profile_links."""
    return fetch_adoptable_pet_profile_links(source=source, store_in_db=store_in_db)


def fetch_dog_profile(source: str, url: str) -> PetProfile:
    """Backward-compatible alias for fetch_pet_profile."""
    return fetch_pet_profile(source=source, url=url)
