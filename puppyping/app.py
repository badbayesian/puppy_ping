"""
PAWS Chicago scraper with:
- Disk-backed caching (diskcache) + TTL
- Readable dataclass print output
- argparse support with --clear-cache
"""

from __future__ import annotations

from dotenv import load_dotenv
import argparse
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from diskcache import Cache

from typing import Optional

import os, smtplib
from email.message import EmailMessage
from datetime import datetime
from html import escape


load_dotenv() 

# ===========================
# Constants
# ===========================

PAWS_AVAILABLE_URL = "https://www.pawschicago.org/our-work/pets-adoption/pets-available"
DOG_PROFILE_PATH_RE = re.compile(r"^/pet-available-for-adoption/showdog/\d+$")
CANTO_IMAGE_PREFIX = "https://pawschicago.canto.com/direct/image/"
CACHE_TIME = 24 * 60 * 60  # 24 hours


# ===========================
# Dataclasses
# ===========================


@dataclass(frozen=True)
class DogMedia:
    images: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    embeds: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"{len(self.images)} images, {len(self.videos)} videos, {len(self.embeds)} embeds"


@dataclass(frozen=True)
class DogProfile:
    dog_id: int
    url: str

    name: Optional[str] = None
    breed: Optional[str] = None
    gender: Optional[str] = None
    age_raw: Optional[str] = None
    age_months: Optional[float] = None
    weight_lbs: Optional[float] = None

    location: Optional[str] = None
    status: Optional[str] = None

    ratings: dict[str, Optional[int]] = field(default_factory=dict)
    description: Optional[str] = None
    media: DogMedia = field(default_factory=DogMedia)

    scraped_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __str__(self) -> str:
        def fmt(v):
            return v if v is not None else "—"

        order = ["children", "dogs", "cats", "home_alone", "activity", "environment"]
        ratings_str = ", ".join(
            f"{k.replace('_', ' ').title()}: {self.ratings.get(k) if self.ratings.get(k) is not None else '—'}"
            for k in order
            if k in self.ratings
        ) or "—"

        return (
            f"DogProfile #{self.dog_id}\n"
            f"{'-' * 88}\n"
            f"Name       : {fmt(self.name)}\n"
            f"Breed      : {fmt(self.breed)}\n"
            f"Gender     : {fmt(self.gender)}\n"
            f"Age        : {fmt(self.age_months)} months\n"
            f"Weight     : {fmt(self.weight_lbs)} lbs\n"
            f"Location   : {fmt(self.location)}\n"
            f"Status     : {fmt(self.status)}\n\n"
            f"Ratings    : {ratings_str}\n"
            f"Media      : {self.media.summary()}\n\n"
            f"URL        : {self.url}\n"
            f"Scraped At : {self.scraped_at_utc}\n"
        )


# ===========================
# Cache
# ===========================

cache = Cache("./.cache/paws")


def cached(ttl_seconds: int):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            key = (fn.__name__, args, tuple(sorted(kwargs.items())))
            hit = cache.get(key)
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


def send_email(profiles: list[DogProfile], send: bool = True) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H")
    msg = EmailMessage()
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = os.environ["EMAIL_TO"]
    msg["Subject"] = f"PAWS Chicago - {len(profiles)} Adoptable Dogs as of {ts}"

    # -------- text version --------
    text_body = "\n\n".join(str(p) for p in profiles) if profiles else "No profiles found."
    msg.set_content(text_body)

    # -------- html version --------
    def fmt(v):
        return "—" if v is None else str(v)

    order = ["children", "dogs", "cats", "home_alone", "activity", "environment"]

    cards = []
    for p in profiles:
        ratings_html = "".join(
            f"<li><b>{escape(k.replace('_', ' ').title())}:</b> {escape(str(p.ratings.get(k)) if p.ratings.get(k) is not None else '—')}</li>"
            for k in order
            if k in p.ratings
        ) or "<li>—</li>"

        # show up to 3 images (email clients may block remote images until user clicks "display images")
        imgs = "".join(
            f'<div style="margin:8px 0;"><img src="{escape(u)}" style="max-width:480px;width:100%;height:auto;border-radius:8px;" /></div>'
            for u in (p.media.images[:3] if p.media and p.media.images else [])
        )

        desc = (p.description or "").strip()
        if len(desc) > 600:
            desc = desc[:599].rstrip() + "…"

        cards.append(f"""
        <div style="border:1px solid #e5e5e5;border-radius:12px;padding:14px;margin:14px 0;">
          <div style="font-size:18px;font-weight:700;margin-bottom:6px;">
            {escape(fmt(p.name))} <span style="color:#666;font-weight:400;">(#{p.dog_id})</span>
          </div>

          <div style="color:#333;line-height:1.4;">
            <div><b>Breed:</b> {escape(fmt(p.breed))}</div>
            <div><b>Gender:</b> {escape(fmt(p.gender))}</div>
            <div><b>Age:</b> {escape(fmt(p.age_months))} months</div>
            <div><b>Weight:</b> {escape(fmt(p.weight_lbs))} lbs</div>
            <div><b>Location:</b> {escape(fmt(p.location))}</div>
            <div><b>Status:</b> {escape(fmt(p.status))}</div>
          </div>

          <div style="margin-top:10px;">
            <div style="font-weight:700;">Ratings</div>
            <ul style="margin:6px 0 0 18px;padding:0;">{ratings_html}</ul>
          </div>

          {imgs}

          <div style="margin-top:10px;">
            <div style="font-weight:700;">Profile</div>
            <a href="{escape(p.url)}">{escape(p.url)}</a>
          </div>

          <div style="margin-top:10px;color:#666;font-size:12px;">
            Scraped at: {escape(fmt(p.scraped_at_utc))} • Media: {escape(p.media.summary() if p.media else "—")}
          </div>

          {"<div style='margin-top:10px;'><div style='font-weight:700;'>Notes</div><div style='white-space:pre-wrap;'>" + escape(desc) + "</div></div>" if desc else ""}
        </div>
        """)

    html_body = f"""
    <html>
      <body style="font-family:Arial,Helvetica,sans-serif;max-width:780px;margin:0 auto;padding:10px;">
        <h2 style="margin:8px 0;">PAWS Chicago — Adoptable Dogs</h2>
        <div style="color:#666;margin-bottom:14px;">{len(profiles)} profiles • generated {escape(ts)}</div>
        {''.join(cards) if cards else '<div>No profiles found.</div>'}
      </body>
    </html>
    """

    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP_SSL(os.environ["EMAIL_HOST"], int(os.environ["EMAIL_PORT"])) as smtp:
        smtp.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASS"])
        if send:
            smtp.send_message(msg)
        else:
            print(msg)
    

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
