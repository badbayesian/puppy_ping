"""Anti-Cruelty scraper provider using Shelterluv embeds."""

from __future__ import annotations

import ast
import json
import logging
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup
from diskcache import Cache

try:
    from .scrape_helpers import _clean, _get_soup, _parse_weight_lbs
    from ..db import get_cached_links, store_cached_links
    from ..models import PetMedia, PetProfile
except ImportError:  # Allows running as a script.
    from scrape_helpers import _clean, _get_soup, _parse_weight_lbs
    from db import get_cached_links, store_cached_links
    from models import PetMedia, PetProfile


logger = logging.getLogger(__name__)

SOURCE = "anti_cruelty"
START_URL = "https://anticruelty.org/adoptable"
DEFAULT_SHELTERLUV_DOMAIN = "https://new.shelterluv.com"
DEFAULT_SHELTER_ID = 100000846
CACHE_TIME = 24 * 60 * 60  # 24 hours

EMBED_CONFIG_RE = re.compile(
    r"var\s+sourceDomain\s*=\s*['\"]([^'\"]+)['\"]\s*;.*?"
    r"var\s+GID\s*=\s*(\d+)\s*;.*?"
    r"var\s+filters\s*=\s*(\{.*?\})\s*;.*?"
    r"EmbedAvailablePets\(",
    flags=re.IGNORECASE | re.DOTALL,
)
NUMERIC_SUFFIX_RE = re.compile(r"(\d+)$")
SOURCE_DOMAIN_RE = re.compile(
    r"https?://[^\"' ]*shelterluv\.com", flags=re.IGNORECASE
)

cache = Cache("./data/cache/anti_cruelty")


def cached(ttl_seconds: int):
    """Return a decorator that caches results for ttl_seconds."""

    def decorator(fn):
        def wrapper(*args, **kwargs):
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


def _parse_filters(raw_filters: str) -> dict[str, Any]:
    """Parse filters object text from embedded script into a dict."""
    text = (raw_filters or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(text)
    if not isinstance(parsed, dict):
        raise ValueError("Shelterluv filters payload is not an object.")
    return {str(k): v for k, v in parsed.items()}


def _extract_embed_configs(soup: BeautifulSoup) -> list[tuple[str, int, dict[str, Any]]]:
    """Extract unique Shelterluv embed configs from the anti-cruelty page."""
    configs: list[tuple[str, int, dict[str, Any]]] = []
    seen: set[tuple[str, int, tuple[tuple[str, str], ...]]] = set()

    for script in soup.select("script"):
        script_text = script.get_text()
        if "EmbedAvailablePets" not in script_text:
            continue
        for match in EMBED_CONFIG_RE.finditer(script_text):
            source_domain = match.group(1).strip().rstrip("/")
            shelter_id = int(match.group(2))
            filters = _parse_filters(match.group(3))
            signature = (
                source_domain,
                shelter_id,
                tuple(sorted((k, str(v)) for k, v in filters.items())),
            )
            if signature in seen:
                continue
            seen.add(signature)
            configs.append((source_domain, shelter_id, filters))

    if configs:
        return configs

    # Fallback: infer domain from page text and use default Shelter ID + random sort.
    page_text = soup.get_text(" ", strip=True)
    source_domain_match = SOURCE_DOMAIN_RE.search(page_text)
    source_domain = (
        source_domain_match.group(0).strip().rstrip("/")
        if source_domain_match
        else DEFAULT_SHELTERLUV_DOMAIN
    )
    return [(source_domain, DEFAULT_SHELTER_ID, {"defaultSort": "random"})]


def _request_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch JSON from a URL and return a parsed object."""
    headers = {
        "User-Agent": "puppy-ping/1.0 (+respectful; non-commercial)",
        "Accept": "application/json",
    }
    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from {url}")
    return payload


def _fetch_animals_for_config(
    source_domain: str, shelter_id: int, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Fetch available animals for one Shelterluv embed configuration."""
    endpoint = f"{source_domain.rstrip('/')}/api/v3/available-animals/{shelter_id}"
    payload = _request_json(endpoint, params=filters)
    animals = payload.get("animals") or []
    return [item for item in animals if isinstance(item, dict)]


def _public_url_for_animal(animal: dict[str, Any], source_domain: str) -> str | None:
    """Return a stable public profile URL for an animal payload."""
    url = str(animal.get("public_url") or "").strip()
    if url:
        return url
    unique_id = str(animal.get("uniqueId") or "").strip()
    if unique_id:
        return f"{source_domain.rstrip('/')}/embed/animal/{unique_id}"
    return None


def _fetch_live_links() -> set[str]:
    """Fetch current Anti-Cruelty profile links from Shelterluv."""
    soup = _get_soup(START_URL)
    configs = _extract_embed_configs(soup)
    links: set[str] = set()

    for source_domain, shelter_id, filters in configs:
        animals = _fetch_animals_for_config(source_domain, shelter_id, filters)
        for animal in animals:
            adoptable = animal.get("adoptable")
            if adoptable in (False, 0, "0"):
                continue
            url = _public_url_for_animal(animal, source_domain)
            if url:
                links.add(url)

    if not links:
        raise RuntimeError("No adoptable Anti-Cruelty links were discovered.")
    return set(sorted(links))


def fetch_adoptable_pet_profile_links_anti_cruelty(store_in_db: bool) -> set[str]:
    """Fetch current Anti-Cruelty profile links."""
    cached_links = None
    if store_in_db:
        try:
            cached_links = get_cached_links(SOURCE, CACHE_TIME, logger=logger)
        except Exception:
            cached_links = None

    if cached_links:
        logger.info("Using cached links from Postgres (fresh).")
        return set(cached_links)

    try:
        links = _fetch_live_links()
        logger.info(f"Fetched {len(links)} live links from Anti-Cruelty.")
        if store_in_db:
            try:
                store_cached_links(SOURCE, sorted(links), logger=logger)
                logger.info(f"Stored {len(links)} links in Postgres cache.")
            except Exception:
                logger.exception("Failed to store links in Postgres cache.")
        return links
    except Exception:
        logger.exception("Live fetch failed; falling back to cached links.")
        try:
            cached_links = get_cached_links(SOURCE, CACHE_TIME * 365, logger=logger)
        except Exception:
            cached_links = None
        if cached_links:
            logger.info("Using cached links from Postgres (stale).")
            return set(cached_links)
        raise


def fetch_adoptable_dog_profile_links_anti_cruelty(store_in_db: bool) -> set[str]:
    """Backward-compatible alias for fetch_adoptable_pet_profile_links_anti_cruelty."""
    return fetch_adoptable_pet_profile_links_anti_cruelty(store_in_db=store_in_db)


def _normalize_species(value: str | None) -> str:
    text = _clean(str(value or "")).lower()
    if text in {"dog", "cat"}:
        return text
    return text or "unknown"


def _age_months_from_birthday(value: Any) -> float | None:
    """Compute approximate age in months from a unix timestamp birthday."""
    try:
        raw = str(value).strip()
        if not raw:
            return None
        birthday_ts = float(raw)
    except (TypeError, ValueError):
        return None
    # Some feeds provide milliseconds.
    if birthday_ts > 1_000_000_000_000:
        birthday_ts = birthday_ts / 1000.0
    birthday_ts = int(birthday_ts)
    if birthday_ts <= 0:
        return None
    birthday = datetime.fromtimestamp(birthday_ts, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    if birthday > now:
        return None
    months = (now - birthday).total_seconds() / (60 * 60 * 24 * 30.4375)
    return round(months, 2)


def _unit_to_months(value: Any, unit: str | None) -> float | None:
    """Convert an age value + unit to months."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    normalized_unit = _clean(str(unit or "")).lower()
    if normalized_unit.startswith("day"):
        return amount / 30.4375
    if normalized_unit.startswith("week"):
        return amount * 7 / 30.4375
    if normalized_unit.startswith("month"):
        return amount
    if normalized_unit.startswith("year"):
        return amount * 12
    return None


def _age_months_from_age_group(age_group: Any) -> float | None:
    """Estimate age in months from Shelterluv age-group bounds."""
    if not isinstance(age_group, dict):
        return None
    to_months = _unit_to_months(age_group.get("age_to"), age_group.get("to_unit"))
    if to_months and to_months > 0:
        return round(to_months, 2)
    from_months = _unit_to_months(
        age_group.get("age_from"), age_group.get("from_unit")
    )
    if from_months and from_months > 0:
        return round(from_months, 2)
    return None


def _age_raw_from_age_group(age_group: Any) -> str | None:
    """Extract display-friendly age text from age-group metadata."""
    if not isinstance(age_group, dict):
        return None
    name_with_duration = _clean(str(age_group.get("name_with_duration") or ""))
    if name_with_duration:
        return name_with_duration
    name = _clean(str(age_group.get("name") or ""))
    duration = _clean(str(age_group.get("duration") or ""))
    if name and duration:
        return f"{name} {duration}"
    return name or None


def _age_raw_from_age_months(age_months: float | None) -> str | None:
    """Format normalized age months into a user-friendly age string."""
    if age_months is None or age_months < 0:
        return None
    total_months = int(age_months)
    years = total_months // 12
    months = total_months % 12
    year_label = "year" if years == 1 else "years"
    month_label = "month" if months == 1 else "months"
    if years > 0 and months > 0:
        return f"{years} {year_label} {months} {month_label}"
    if years > 0:
        return f"{years} {year_label}"
    return f"{months} {month_label}"


def _extract_pet_id(animal: dict[str, Any], url: str) -> int:
    """Extract a numeric pet id from unique id, URL, or nid."""
    for value in (animal.get("uniqueId"), url):
        text = str(value or "").strip()
        match = NUMERIC_SUFFIX_RE.search(text)
        if match:
            return int(match.group(1))
    try:
        return int(animal.get("nid"))
    except (TypeError, ValueError):
        raise ValueError(f"Missing numeric pet id for Anti-Cruelty profile: {url}")


def _iter_media_items(raw_media: Any) -> Iterable[dict[str, Any]]:
    if isinstance(raw_media, list):
        return [item for item in raw_media if isinstance(item, dict)]
    if isinstance(raw_media, dict):
        ordered_keys = sorted(
            raw_media,
            key=lambda value: (
                0,
                int(str(value)),
            )
            if str(value).isdigit()
            else (1, str(value)),
        )
        return [
            raw_media[key]
            for key in ordered_keys
            if isinstance(raw_media.get(key), dict)
        ]
    return []


def _extract_description(animal: dict[str, Any]) -> str | None:
    raw_description = str(animal.get("kennel_description") or "").strip()
    if not raw_description:
        return None
    text = BeautifulSoup(raw_description, "html.parser").get_text(" ", strip=True)
    cleaned = _clean(text)
    return cleaned or None


@cached(ttl_seconds=CACHE_TIME)
def fetch_pet_profile_anti_cruelty(url: str) -> PetProfile:
    """Fetch and parse a single Anti-Cruelty profile."""
    logger.info(f"Fetching pet profile: {url}")
    soup = _get_soup(url)
    node = soup.select_one("iframe-animal")
    if node is None:
        raise ValueError(f"Missing Shelterluv animal payload for URL: {url}")

    animal_json = str(node.get(":animal") or "").strip()
    if not animal_json:
        raise ValueError(f"Missing :animal payload for URL: {url}")
    try:
        animal = json.loads(animal_json)
    except json.JSONDecodeError:
        animal = json.loads(unescape(animal_json))
    if not isinstance(animal, dict):
        raise ValueError(f"Invalid animal payload for URL: {url}")

    photos = _iter_media_items(animal.get("photos"))
    images = [
        str(item.get("url")).strip()
        for item in sorted(
            photos,
            key=lambda item: int(item.get("order_column") or 0),
        )
        if str(item.get("url") or "").strip()
    ]
    videos = [
        str(item.get("url")).strip()
        for item in _iter_media_items(animal.get("videos"))
        if str(item.get("url") or "").strip()
    ]
    age_group = animal.get("age_group")
    birthday_age_months = _age_months_from_birthday(animal.get("birthday"))
    age_months = birthday_age_months or _age_months_from_age_group(age_group)
    age_raw = _age_raw_from_age_months(birthday_age_months) or _age_raw_from_age_group(
        age_group
    )

    return PetProfile(
        dog_id=_extract_pet_id(animal, url),
        url=url,
        species=_normalize_species(str(animal.get("species") or "")),
        name=_clean(str(animal.get("name") or "")) or None,
        breed=_clean(str(animal.get("breed") or "")) or None,
        gender=_clean(str(animal.get("sex") or "")) or None,
        age_raw=age_raw,
        age_months=age_months,
        weight_lbs=_parse_weight_lbs(
            str(animal.get("weight") or "")
            or str(animal.get("weight_group") or "")
        ),
        location=_clean(str(animal.get("location") or "")) or None,
        status="Available" if bool(animal.get("adoptable", True)) else "Unavailable",
        ratings={},
        description=_extract_description(animal),
        media=PetMedia(images=images, videos=sorted(videos), embeds=[]),
    )


def fetch_dog_profile_anti_cruelty(url: str) -> PetProfile:
    """Backward-compatible alias for fetch_pet_profile_anti_cruelty."""
    return fetch_pet_profile_anti_cruelty(url)
