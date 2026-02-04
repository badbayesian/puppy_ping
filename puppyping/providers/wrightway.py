import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from typing import Optional

try:
    from .scrape_helpers import _get_soup, _clean, _extract_query_id, _get_name
    from ..models import DogMedia, DogProfile
    from ..db import get_cached_links, store_cached_links
except ImportError:  # Allows running as a script
    from scrape_helpers import _get_soup, _clean, _extract_query_id, _get_name
    from models import DogMedia, DogProfile
    from db import get_cached_links, store_cached_links

START_URL = "https://wright-wayrescue.org/adoptable-pets"
PETANGO_BASE = "https://ws.petango.com/webservices/adoptablesearch/"

LABEL_MAP = {
    "Animal ID": "dog_id",
    "Breed": "breed",
    "Gender": "gender",
    "Age": "age_raw",
    "Location": "location",
    "Stage": "status",
}

def fetch_dog_profile_wrightway() -> set[str]:
    session = requests.Session()

    resp = session.get(START_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    iframe = soup.find("iframe")
    if not iframe or not iframe.get("src"):
        raise RuntimeError("Petango iframe not found")

    iframe_src = iframe["src"]

    resp = session.get(iframe_src, timeout=30)
    resp.raise_for_status()
    petango = BeautifulSoup(resp.text, "html.parser")

    return {
        urljoin(PETANGO_BASE, a["href"])
        for a in petango.select('a[href*="wsAdoptableAnimalDetails.aspx"]')
        if a.get("href")
    }

def extract_description(soup: BeautifulSoup) -> Optional[str]:
    """
    Petango descriptions are usually the longest free-text block on the page.
    """
    blocks = [
        _clean(el.get_text(" ", strip=True))
        for el in soup.select("p, div")
        if len(_clean(el.get_text(" ", strip=True))) >= 120
    ]
    return blocks[0] if blocks else None


def extract_name_from_description(description: Optional[str]) -> Optional[str]:
    """
    Extract name from description text starting with:
      'Meet <Name> ...'

    Also removes known Petango boilerplate and trims whitespace.
    """
    if not description:
        return None

    # Remove known noise first
    NAME_NOISE = "Click a number to change picture or play to see a video"
    cleaned = description.replace(NAME_NOISE, "")
    cleaned = _clean(cleaned)

    m = re.search(
        r"\bMeet\s+(.+?)(?:[.!—–-]|$)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not m:
        return None

    name = m.group(1)
    return _clean(name)


def extract_label_values(soup: BeautifulSoup) -> dict[str, str]:
    data: dict[str, str] = {}

    for tr in soup.select("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) >= 2:
            key = _clean(tds[0].get_text()).rstrip(":")
            val = _clean(tds[1].get_text())
            if key and val:
                data[key] = val

    text = soup.get_text("\n", strip=True)
    for label in LABEL_MAP:
        if label not in data:
            m = re.search(rf"{re.escape(label)}\s*:\s*(.+)", text)
            if m:
                data[label] = _clean(m.group(1).split("\n")[0])

    return data


def parse_age_months(age_raw: Optional[str]) -> Optional[float]:
    if not age_raw:
        return None

    s = age_raw.lower()

    def grab(unit: str) -> float:
        m = re.search(rf"(\d+)\s*{unit}", s)
        return float(m.group(1)) if m else 0.0

    years = grab("year") + grab("years")
    months = grab("month") + grab("months")
    weeks = grab("week") + grab("weeks")
    days = grab("day") + grab("days")

    total = years * 12 + months + weeks * (7 / 30) + days * (1 / 30)
    return total if total > 0 else None


def extract_media(soup: BeautifulSoup, page_url: str) -> DogMedia:
    images = {
        urljoin(page_url, img["src"])
        for img in soup.select("img[src]")
    }

    videos = {
        urljoin(page_url, v["src"])
        for v in soup.select("video[src], video source[src]")
    }

    embeds = {
        urljoin(page_url, f["src"])
        for f in soup.select("iframe[src]")
    }

    return DogMedia(
        images=sorted(images),
        videos=sorted(videos),
        embeds=sorted(embeds),
    )


def scrape_dog_profile(url: str, session: requests.Session) -> DogProfile:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    labels = extract_label_values(soup)
    description = extract_description(soup)

    dog_id = (
        int(re.sub(r"[^\d]", "", labels["Animal ID"]))
        if "Animal ID" in labels
        else _extract_query_id(url)
    )
    if dog_id is None:
        raise ValueError(f"Missing dog_id for {url}")

    age_raw = labels.get("Age")

    return DogProfile(
        dog_id=dog_id,
        url=url,
        name=extract_name_from_description(description),
        breed=labels.get("Breed"),
        gender=labels.get("Gender"),
        age_raw=age_raw,
        age_months=parse_age_months(age_raw),
        weight_lbs=None,
        location=labels.get("Location"),
        status=labels.get("Stage"),
        ratings={},
        description=description,
        media=extract_media(soup, url),
    )

def fetch_adoptable_dog_profile_links_wrightway(urls: set[str]) -> list[DogProfile]:
    session = requests.Session()
    profiles: list[DogProfile] = []

    for url in sorted(urls):
        try:
            profiles.append(scrape_dog_profile(url, session))
        except Exception as e:
            print(f"[WARN] Failed {url}: {e}")

    return profiles
