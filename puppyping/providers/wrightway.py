"""Wright-Way Rescue scraper provider."""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from diskcache import Cache

try:
    from .scrape_helpers import _clean, _extract_query_id, _get_soup, _parse_weight_lbs
    from ..db import get_cached_links, store_cached_links
    from ..models import PetMedia, PetProfile
except ImportError:  # Allows running as a script
    from scrape_helpers import _clean, _extract_query_id, _get_soup, _parse_weight_lbs
    from db import get_cached_links, store_cached_links
    from models import PetMedia, PetProfile


logger = logging.getLogger(__name__)

SOURCE = "wright_way"
START_URLS = (
    "https://wright-wayrescue.org/adoptable-pets",
    "https://wright-wayrescue.org/adoptable-kittens",
)
# Backward-compatible constant for older references.
START_URL = START_URLS[0]
CACHE_TIME = 24 * 60 * 60  # 24 hours

PROFILE_PATH_RE = re.compile(r"wsAdoptableAnimalDetails\.aspx", re.IGNORECASE)
LABELS = (
    "Animal ID",
    "Species",
    "Breed",
    "Gender",
    "Age",
    "Weight",
    "Location",
    "Stage",
)
DESCRIPTION_STOP_MARKERS = (
    "THANK YOU FOR YOUR INTEREST IN SAVING A LIFE!",
    "THERE ARE TWO WAYS TO ADOPT FROM WRIGHT-WAY RESCUE:",
)

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
    def _trim_tail(text: str) -> str:
        cleaned = _clean(text)
        lowered = cleaned.lower()
        cut_idx = len(cleaned)
        for marker in DESCRIPTION_STOP_MARKERS:
            idx = lowered.find(marker.lower())
            if idx != -1:
                cut_idx = min(cut_idx, idx)
        return cleaned[:cut_idx].strip()

    selectors = (
        "#lbDescription",
        "#tblDescription",
        ".detail-animal-desc",
        "#DescriptionWrapper",
    )
    candidates = []
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            candidates.append(node.get_text(" ", strip=True))

    meta_description = soup.find("meta", attrs={"property": "og:description"})
    if meta_description and meta_description.get("content"):
        candidates.append(str(meta_description["content"]))

    for candidate in candidates:
        text = _trim_tail(candidate)
        if len(text) >= 60:
            return text

    # Fallback for unexpected markup.
    for node in soup.select("p, div"):
        text = _clean(node.get_text(" ", strip=True))
        if len(text) < 120:
            continue
        if "click a number to change picture or play to see a video" in text.lower():
            continue
        text = _trim_tail(text)
        if len(text) >= 60:
            return text
    return None


def _clean_name(candidate: str) -> Optional[str]:
    """Normalize a candidate name string and discard obvious non-name content."""
    value = _clean(candidate.split("|", 1)[0])
    value = re.sub(r"^meet\s+", "", value, flags=re.IGNORECASE).strip(" :-")
    if not value:
        return None
    if value.lower().startswith("animal details"):
        return None
    if len(value) > 60:
        return None
    if re.search(
        r"click a number|animal id|species|breed|gender|age|location|stage",
        value,
        flags=re.IGNORECASE,
    ):
        return None
    return value


def _extract_name(soup: BeautifulSoup, description: Optional[str]) -> Optional[str]:
    """Extract a likely pet name from heading, title, or description.

    Args:
        soup: Parsed profile document.
        description: Extracted long-form description.

    Returns:
        Name text or None.
    """
    meta_title = soup.find("meta", attrs={"property": "og:title"})
    if meta_title and meta_title.get("content"):
        name = _clean_name(str(meta_title["content"]))
        if name:
            return name

    for selector in ("h1", ".petName", ".pet-name", "title"):
        node = soup.select_one(selector)
        if not node:
            continue
        name = _clean_name(node.get_text(" ", strip=True))
        if name:
            return name

    if description:
        match = re.search(
            r"\bMeet\s+([A-Za-z][A-Za-z' -]{0,40})\b",
            description,
            flags=re.IGNORECASE,
        )
        if match:
            name = _clean_name(match.group(1))
            if name:
                return name
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
            if key in LABELS and val:
                data[key] = val

    lines = [_clean(line) for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    for idx, line in enumerate(lines[:-1]):
        if line in LABELS and line not in data:
            data[line] = lines[idx + 1]

    text = "\n".join(lines)
    for label in LABELS:
        if label in data:
            continue
        match = re.search(rf"{re.escape(label)}\s*:?\s*(.+)", text)
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


def _extract_media(soup: BeautifulSoup, page_url: str) -> PetMedia:
    """Collect image/video/embed URLs from a profile page.

    Args:
        soup: Parsed profile document.
        page_url: Source profile URL.

    Returns:
        Extracted media bundle.
    """
    def _is_petango_photo(url: str) -> bool:
        return "g.petango.com/photos/" in url.lower()

    def _canonical_petango_photo(url: str) -> str:
        normalized = url.strip()
        normalized = normalized.replace("https:http://", "https://")
        normalized = normalized.replace("https:https://", "https://")
        normalized = re.sub(r"^http://g\.petango\.com/", "https://g.petango.com/", normalized)
        return normalized

    images = set()
    for img in soup.select("img[src]"):
        src = _canonical_petango_photo(urljoin(page_url, img["src"]))
        if _is_petango_photo(src):
            images.add(src)

    # Petango often exposes all photos via numbered links [1], [2], [3].
    for a in soup.select("a[href]"):
        href = _canonical_petango_photo(urljoin(page_url, a["href"]))
        onclick = a.get("onclick") or ""
        if _is_petango_photo(href):
            images.add(href)
        photo_match = re.search(r"loadPhoto\('([^']+)'\)", onclick)
        if photo_match:
            photo_url = _canonical_petango_photo(urljoin(page_url, photo_match.group(1)))
            if _is_petango_photo(photo_url):
                images.add(photo_url)

    videos = {
        urljoin(page_url, tag["src"])
        for tag in soup.select("video[src], video source[src]")
    }
    embeds = {urljoin(page_url, frame["src"]) for frame in soup.select("iframe[src]")}

    for tag in soup.select("[onclick]"):
        onclick = tag.get("onclick") or ""
        video_match = re.search(r"loadVideo\('([^']+)'\)", onclick)
        if video_match:
            video_id = video_match.group(1).strip()
            if video_id:
                embeds.add(urljoin(page_url, f"wsYouTubeVideo.aspx?videoid={video_id}"))

    meta_image = soup.find("meta", attrs={"property": "og:image"})
    if meta_image and meta_image.get("content"):
        image_url = _canonical_petango_photo(urljoin(page_url, str(meta_image["content"])))
        if _is_petango_photo(image_url):
            images.add(image_url)

    return PetMedia(images=sorted(images), videos=sorted(videos), embeds=sorted(embeds))


def _fetch_live_links() -> set[str]:
    """Fetch current Wright-Way profile links from listing pages.

    Returns:
        Set of Petango profile URLs.
    """
    links: set[str] = set()
    iframe_missing_pages: list[str] = []
    for start_url in START_URLS:
        soup = _get_soup(start_url)
        iframe = soup.find("iframe")
        if not iframe or not iframe.get("src"):
            iframe_missing_pages.append(start_url)
            continue

        listing_url = urljoin(start_url, iframe["src"])
        listing_soup = _get_soup(listing_url)
        links.update(
            {
                urljoin(listing_url, anchor["href"])
                for anchor in listing_soup.select("a[href]")
                if PROFILE_PATH_RE.search(anchor["href"])
            }
        )

    if iframe_missing_pages:
        message = (
            "Petango iframe not found on Wright-Way pages: "
            + ", ".join(iframe_missing_pages)
        )
        if links:
            logger.warning(message)
        else:
            raise RuntimeError(message)
    return set(sorted(links))


def fetch_adoptable_pet_profile_links_wrightway(store_in_db: bool) -> set[str]:
    """Fetch current Wright-Way pet profile links.

    Args:
        store_in_db: Whether to use and update Postgres cache.

    Returns:
        Set of profile URLs.
    """
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
        logger.info(f"Fetched {len(links)} live links from Wright-Way.")
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


def fetch_adoptable_dog_profile_links_wrightway(store_in_db: bool) -> set[str]:
    """Backward-compatible alias for fetch_adoptable_pet_profile_links_wrightway."""
    return fetch_adoptable_pet_profile_links_wrightway(store_in_db=store_in_db)


def _normalize_species(raw_value: Optional[str]) -> str:
    """Normalize species text from provider pages."""
    normalized = _clean(raw_value or "").lower()
    return normalized or "dog"


@cached(ttl_seconds=CACHE_TIME)
def fetch_pet_profile_wrightway(url: str) -> PetProfile:
    """Fetch and parse a single Wright-Way pet profile.

    Args:
        url: Profile URL.

    Returns:
        Parsed PetProfile.
    """
    logger.info(f"Fetching pet profile: {url}")
    soup = _get_soup(url)

    labels = _extract_label_values(soup)
    description = _extract_description(soup)
    age_raw = labels.get("Age")

    pet_id = _extract_query_id(url)
    if "Animal ID" in labels:
        match = re.search(r"\d+", labels["Animal ID"])
        if match:
            pet_id = int(match.group(0))
    if pet_id is None:
        raise ValueError(f"Missing pet_id for {url}")

    return PetProfile(
        dog_id=pet_id,
        url=url,
        species=_normalize_species(labels.get("Species")),
        name=_extract_name(soup, description),
        breed=labels.get("Breed"),
        gender=labels.get("Gender"),
        age_raw=age_raw,
        age_months=_parse_age_months(age_raw),
        weight_lbs=_parse_weight_lbs(labels.get("Weight")),
        location=labels.get("Location"),
        status=labels.get("Stage"),
        ratings={},
        description=description,
        media=_extract_media(soup, url),
    )


def fetch_dog_profile_wrightway(url: str) -> PetProfile:
    """Backward-compatible alias for fetch_pet_profile_wrightway."""
    return fetch_pet_profile_wrightway(url)
