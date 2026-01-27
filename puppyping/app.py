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

import requests
from bs4 import BeautifulSoup
from diskcache import Cache
from dotenv import load_dotenv

try:
    from .emailer import send_email
    from .models import DogMedia, DogProfile
except ImportError:  # Allows running as a script: python puppyping/app.py
    from emailer import send_email
    from models import DogMedia, DogProfile


load_dotenv()

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

cache = Cache("./.cache/paws")


def cached(ttl_seconds: int):
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


# ===========================
# HTTP + helpers
# ===========================

def _get_soup(url: str) -> BeautifulSoup:
    headers = {
        "User-Agent": "paws-scraper/1.0 (+respectful; non-commercial)",
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _get_name(soup: BeautifulSoup) -> Optional[str]:
    for h in soup.select("title"):
        title_text = h.get_text(strip=True)
        return title_text.split("|", 1)[0].strip()
    

def _parse_age_to_months(age: str | None) -> float | None:
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
    return re.sub(r"\s+", " ", s).strip()


def _parse_weight_lbs(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else None


def _find_label_value(soup: BeautifulSoup, label: str) -> Optional[str]:
    text = soup.get_text("\n", strip=True)
    m = re.search(rf"^{label}\s*:?\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    return _clean_text(m.group(1)) if m else None


def _extract_single_rating(soup: BeautifulSoup, label: str) -> Optional[int]:
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
    categories = ["children", "dogs", "cats", "home_alone", "activity", "environment"]

    return {cat: _extract_single_rating(soup, cat) for cat in categories}


def _extract_description(soup: BeautifulSoup) -> Optional[str]:
    for p in soup.select("p"):
        t = _clean_text(p.get_text())
        if len(t) > 80:
            return t
    return None


def _extract_media(url: str, soup: BeautifulSoup) -> DogMedia:
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


# ===========================
# Public API
# ===========================

@cached(ttl_seconds=CACHE_TIME)
def fetch_adoptable_dog_profile_links() -> set[str]:
    soup = _get_soup(PAWS_AVAILABLE_URL)
    return set(sorted(
        urljoin(PAWS_AVAILABLE_URL, a["href"])
        for a in soup.select("a[href]")
        if DOG_PROFILE_PATH_RE.match(a["href"])
    ))


@cached(ttl_seconds=CACHE_TIME)
def fetch_dog_profile(url: str) -> DogProfile:
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


def __safe_less_than(a: Optional[float], b: float|int) -> bool:
    return a is not None and a < b


# ===========================
# Main (with argparse)
# ===========================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear disk cache before running"
    )
    args = parser.parse_args()

    if args.clear_cache:
        cache.clear()
        print("Cache cleared.")

    links = fetch_adoptable_dog_profile_links()
    profiles = [fetch_dog_profile(u) for u in links]

    filtered_profiles = [p for p in profiles if __safe_less_than(p.age_months, 8)]
    send_email(filtered_profiles)


if __name__ == "__main__":
    main()
