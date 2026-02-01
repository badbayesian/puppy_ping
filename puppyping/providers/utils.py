from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from ..models import DogMedia
except ImportError:  # Allows running as a script: python puppyping/providers/utils.py
    from models import DogMedia

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
        "User-Agent": "puppy-ping/1.0 (+respectful; non-commercial)",
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


def _extract_media(
    url: str, soup: BeautifulSoup, image_prefixes: tuple[str, ...] | None = None
) -> DogMedia:
    """Collect image, video, and embed URLs from the page.

    Args:
        url: Base page URL.
        soup: Parsed HTML document.
        image_prefixes: Optional tuple of allowed image URL prefixes.

    Returns:
        DogMedia with collected URLs.
    """
    images, videos, embeds = set(), set(), set()

    for img in soup.select("img[src]"):
        src = urljoin(url, img["src"])
        if image_prefixes is None or src.startswith(image_prefixes):
            images.add(src)

    for v in soup.select("video[src], video source[src]"):
        videos.add(urljoin(url, v["src"]))

    for iframe in soup.select("iframe[src]"):
        embeds.add(urljoin(url, iframe["src"]))

    for a in soup.select("a[href]"):
        if re.search(r"\.(mp4|mov|m4v)$", a["href"], re.I):
            videos.add(urljoin(url, a["href"]))

    return DogMedia(sorted(images), sorted(videos), sorted(embeds))
