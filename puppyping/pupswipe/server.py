"""Server-rendered PupSwipe application.

This module provides a minimal HTTP server for browsing adoptable dogs,
recording swipe actions, and exposing health/data APIs backed by Postgres.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from puppyping.db import add_email_subscriber, ensure_schema, get_connection

APP_DIR = Path(__file__).resolve().parent
DEFAULT_LIMIT = 40
MAX_LIMIT = 200
PAGE_SIZE = 1
MAX_PUPPY_AGE_MONTHS = 8.0
DEFAULT_PUPSWIPE_SOURCES = ("paws_chicago", "wright_way")
PROVIDER_DISCLAIMER = (
    "PuppyPing is not affiliated with any dog rescue, shelter, breeder, "
    "or adoption provider."
)
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)


def _get_pupswipe_sources() -> tuple[str, ...]:
    """Return feed sources for PupSwipe from env, with sensible defaults.

    Returns:
        Tuple of enabled source keys.
    """
    raw = os.environ.get("PUPSWIPE_SOURCES", ",".join(DEFAULT_PUPSWIPE_SOURCES))
    parsed = [item.strip() for item in raw.split(",") if item.strip()]
    deduped = tuple(dict.fromkeys(parsed))
    return deduped or DEFAULT_PUPSWIPE_SOURCES


PUPSWIPE_SOURCES = _get_pupswipe_sources()


def _provider_name(source: str | None, profile_url: str | None = None) -> str:
    """Return a human-readable provider label for a profile.

    Args:
        source: Optional normalized provider source key.
        profile_url: Optional profile URL for fallback detection.

    Returns:
        Provider display name.
    """
    if source == "paws_chicago":
        return "PAWS Chicago"
    if source == "wright_way":
        return "Wright-Way Rescue"

    url = (profile_url or "").lower()
    if "pawschicago.org" in url:
        return "PAWS Chicago"
    if "petango.com" in url or "wright-wayrescue.org" in url:
        return "Wright-Way Rescue"
    return "Adoption Provider"


def _ensure_app_schema(conn) -> None:
    """Create or update tables/indexes needed by the PupSwipe app.

    Args:
        conn: An open psycopg connection.

    Returns:
        None.
    """
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dog_swipes (
                id BIGSERIAL PRIMARY KEY,
                dog_id INTEGER NOT NULL,
                swipe TEXT NOT NULL CHECK (swipe IN ('left', 'right')),
                source TEXT,
                created_at_utc TIMESTAMPTZ NOT NULL,
                user_key TEXT,
                user_ip TEXT,
                user_agent TEXT,
                accept_language TEXT,
                screen_info JSONB
            );
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS user_key TEXT;
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS user_ip TEXT;
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS user_agent TEXT;
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS accept_language TEXT;
            """
        )
        cur.execute(
            """
            ALTER TABLE dog_swipes
            ADD COLUMN IF NOT EXISTS screen_info JSONB;
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_swipes_created_at
            ON dog_swipes (created_at_utc DESC);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_swipes_dog_id
            ON dog_swipes (dog_id);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dog_swipes_user_key
            ON dog_swipes (user_key);
            """
        )
    conn.commit()


def _coerce_json(value):
    """Coerce non-JSON-native values into JSON-serializable values.

    Args:
        value: Any value that may need JSON coercion.

    Returns:
        A JSON-serializable representation of the input value.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _jsonify(obj):
    """Recursively convert an object graph to JSON-safe values.

    Args:
        obj: A primitive, list, or dict to transform.

    Returns:
        A recursively transformed object suitable for JSON serialization.
    """
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    return _coerce_json(obj)


def _fetch_puppies(limit: int, offset: int = 0) -> list[dict]:
    """Load the latest available dog profiles ordered by recency.

    Args:
        limit: Maximum number of profiles to return.
        offset: Number of rows to skip for pagination.

    Returns:
        A list of dog profile dictionaries.
    """
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (dog_id)
                        dog_id,
                        url,
                        name,
                        breed,
                        gender,
                        age_raw,
                        age_months,
                        weight_lbs,
                        location,
                        status,
                        ratings,
                        description,
                        media,
                        scraped_at_utc
                    FROM dog_profiles
                    ORDER BY dog_id, scraped_at_utc DESC
                ), active AS (
                    SELECT
                        latest.*,
                        dog_status.source
                    FROM latest
                    JOIN dog_status
                      ON dog_status.link = latest.url
                     AND dog_status.is_active = true
                     AND dog_status.source = ANY(%s::text[])
                )
                SELECT *
                FROM active
                WHERE COALESCE(status, '') ILIKE 'Available%%'
                  AND age_months IS NOT NULL
                  AND age_months < %s
                ORDER BY scraped_at_utc DESC, dog_id DESC
                LIMIT %s
                OFFSET %s;
                """,
                (list(PUPSWIPE_SOURCES), MAX_PUPPY_AGE_MONTHS, limit, max(0, offset)),
            )
            rows = cur.fetchall()
            columns = [col.name for col in cur.description]

    puppies: list[dict] = []
    for row in rows:
        record = dict(zip(columns, row))
        record = _jsonify(record)
        media = record.get("media") or {}
        images = media.get("images") or []
        record["primary_image"] = images[0] if images else None
        puppies.append(record)
    return puppies


def _count_puppies() -> int:
    """Count latest dog profiles that are currently available.

    Returns:
        The number of available dogs based on each dog's latest record.
    """
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (dog_id)
                        dog_id,
                        url,
                        age_months,
                        status,
                        scraped_at_utc
                    FROM dog_profiles
                    ORDER BY dog_id, scraped_at_utc DESC
                )
                SELECT count(*)
                FROM latest
                WHERE EXISTS (
                    SELECT 1
                    FROM dog_status
                    WHERE dog_status.link = latest.url
                      AND dog_status.source = ANY(%s::text[])
                      AND dog_status.is_active = true
                )
                  AND COALESCE(status, '') ILIKE 'Available%%'
                  AND age_months IS NOT NULL
                  AND age_months < %s;
                """,
                (list(PUPSWIPE_SOURCES), MAX_PUPPY_AGE_MONTHS),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _store_swipe(
    dog_id: int,
    swipe: str,
    source: str | None = None,
    user_key: str | None = None,
    user_ip: str | None = None,
    user_agent: str | None = None,
    accept_language: str | None = None,
    screen_info: dict | None = None,
) -> None:
    """Persist a swipe event for a dog.

    Args:
        dog_id: Dog identifier.
        swipe: Swipe direction, either "left" or "right".
        source: Optional source identifier (for example, "pupswipe").
        user_key: Derived per-user fingerprint key.
        user_ip: Client IP address.
        user_agent: Client user agent string.
        accept_language: Client language header value.
        screen_info: Optional screen/viewport metadata.

    Returns:
        None.
    """
    with get_connection() as conn:
        _ensure_app_schema(conn)
        with conn.cursor() as cur:
            screen_info_json = json.dumps(screen_info, sort_keys=True) if screen_info else None
            cur.execute(
                """
                INSERT INTO dog_swipes (
                    dog_id,
                    swipe,
                    source,
                    created_at_utc,
                    user_key,
                    user_ip,
                    user_agent,
                    accept_language,
                    screen_info
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb);
                """,
                (
                    dog_id,
                    swipe,
                    source,
                    datetime.now(timezone.utc),
                    user_key,
                    user_ip,
                    user_agent,
                    accept_language,
                    screen_info_json,
                ),
            )
        conn.commit()


def _safe_int(value: str | None, default: int = 0) -> int:
    """Safely parse a non-negative integer from text.

    Args:
        value: Input value to parse.
        default: Fallback value when parsing fails.

    Returns:
        A non-negative integer.
    """
    try:
        return max(0, int(value or default))
    except (TypeError, ValueError):
        return default


def _normalize_email(email: str | None) -> str:
    """Normalize an email address for storage and comparisons.

    Args:
        email: Raw email input.

    Returns:
        Lower-cased, trimmed email string.
    """
    return (email or "").strip().lower()


def _is_valid_email(email: str) -> bool:
    """Validate an email address with a pragmatic syntax check.

    Args:
        email: Normalized email address.

    Returns:
        ``True`` when the email looks valid, otherwise ``False``.
    """
    if len(email) > 320:
        return False
    return bool(EMAIL_PATTERN.fullmatch(email))


def _get_primary_image(pup: dict) -> str | None:
    """Extract the primary image URL from a dog record.

    Args:
        pup: Dog profile dictionary.

    Returns:
        The primary image URL if present, otherwise ``None``.
    """
    image = pup.get("primary_image")
    if isinstance(image, str) and image.strip():
        return image
    media = pup.get("media") or {}
    images = media.get("images") if isinstance(media, dict) else None
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str) and first.strip():
            return first
    return None


def _get_photo_urls(pup: dict) -> list[str]:
    """Collect unique photo URLs for a dog record.

    Args:
        pup: Dog profile dictionary.

    Returns:
        An ordered list of unique image URLs.
    """
    urls: list[str] = []
    primary = _get_primary_image(pup)
    if primary:
        urls.append(primary)
    media = pup.get("media") or {}
    images = media.get("images") if isinstance(media, dict) else None
    if isinstance(images, list):
        for item in images:
            if isinstance(item, str) and item.strip() and item not in urls:
                urls.append(item)
    return urls


def _render_page(
    offset: int = 0,
    message: str | None = None,
    photo_index: int = 0,
    randomize: bool = False,
) -> bytes:
    """Render the main HTML page.

    Args:
        offset: Current dog index offset.
        message: Optional info/error message to display.
        photo_index: Selected image index within the current dog carousel.

    Returns:
        UTF-8 encoded HTML document bytes.
    """
    try:
        total = _count_puppies()
        if total > 0 and offset >= total:
            offset = 0
        if total > 1 and randomize:
            current_offset = offset
            random_offset = random.randrange(total - 1)
            if random_offset >= current_offset:
                random_offset += 1
            offset = random_offset
        elif total == 1 and randomize:
            offset = 0
        puppies = _fetch_puppies(PAGE_SIZE, offset=offset)
    except Exception as exc:
        error_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PupSwipe | PuppyPing</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">PS</div>
          <div>
            <h1>PupSwipe</h1>
            <p>By PuppyPing</p>
          </div>
        </div>
      </header>
      <main>
        <section class="stack">
          <div class="state state-error">Failed to load puppies: {escape(str(exc))}</div>
        </section>
      </main>
    </div>
  </body>
</html>"""
        return error_html.encode("utf-8")

    stats = f"{max(total - offset, 0)} left of {total}" if total else "No puppies found"

    if not puppies:
        no_data = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PupSwipe | PuppyPing</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">PS</div>
          <div>
            <h1>PupSwipe</h1>
            <p>By PuppyPing</p>
          </div>
        </div>
        <div class="stats">{escape(stats)}</div>
      </header>
      <main>
        <section class="stack">
          <div class="state state-empty">{escape(message or "No puppies to show yet. Run scraper and refresh.")}</div>
        </section>
        <section class="controls">
          <form method="get" action="/">
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="random" value="1" />
            <button class="btn refresh" type="submit">Random</button>
          </form>
        </section>
        <section class="ecosystem" aria-label="PuppyPing ecosystem">
          <h3>Get PuppyPing Alerts</h3>
          <p class="ecosystem-copy">
            PupSwipe runs inside the PuppyPing ecosystem. Join the PuppyPing email list for new puppy updates.
          </p>
          <p class="ecosystem-copy">
            {escape(PROVIDER_DISCLAIMER)}
          </p>
          <form class="subscribe-form" method="post" action="/subscribe">
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="photo" value="0" />
            <label class="subscribe-label" for="subscribe-email-empty">Email for PuppyPing alerts</label>
            <div class="subscribe-row">
              <input
                id="subscribe-email-empty"
                name="email"
                type="email"
                inputmode="email"
                autocomplete="email"
                placeholder="you@example.com"
                required
              />
              <button class="btn subscribe" type="submit">Join</button>
            </div>
          </form>
        </section>
      </main>
    </div>
  </body>
</html>"""
        return no_data.encode("utf-8")

    pup = puppies[0]
    dog_id = _safe_int(str(pup.get("dog_id")), 0)

    name = escape(str(pup.get("name") or "Unnamed pup"))
    age_raw = escape(str(pup.get("age_raw") or "Age unknown"))
    breed = escape(str(pup.get("breed") or "Unknown breed"))
    gender = escape(str(pup.get("gender") or "Unknown gender"))
    location = escape(str(pup.get("location") or "Unknown location"))
    status = escape(str(pup.get("status") or "Status unknown"))
    description = escape(
        str(
            pup.get("description")
            or "No description available yet. Open profile for full details."
        )
    )
    raw_profile_url = str(pup.get("url") or "").strip()
    profile_url = escape(raw_profile_url or "#")
    source_key = str(pup.get("source")) if pup.get("source") is not None else None
    provider_name = escape(_provider_name(source_key, raw_profile_url))
    if raw_profile_url:
        provider_link_html = (
            f'<a class="profile-link card-profile-link" href="{profile_url}" '
            f'target="_blank" rel="noopener">View on {provider_name}</a>'
        )
    else:
        provider_link_html = f'<span class="provider-missing">{provider_name}</span>'

    photo_urls = _get_photo_urls(pup)
    photo_count = len(photo_urls)
    if photo_count > 0:
        selected_photo = photo_urls[photo_index % photo_count]
        image_block = (
            f'<img src="{escape(selected_photo)}" alt="{name} photo" referrerpolicy="no-referrer" />'
        )
    else:
        initials = "".join(part[0] for part in name.split()[:2]).upper() or "PUP"
        image_block = f'<div class="photo-fallback">{escape(initials)}</div>'
    current_photo_index = photo_index % photo_count if photo_count > 0 else 0

    carousel_controls = ""
    if photo_count > 1:
        prev_photo = (photo_index - 1) % photo_count
        next_photo = (photo_index + 1) % photo_count
        current_index = photo_index % photo_count
        dots = "".join(
            f'<span class="carousel-dot{" is-active" if idx == current_index else ""}" aria-hidden="true"></span>'
            for idx in range(photo_count)
        )
        carousel_controls = f"""
            <div class="carousel-controls" aria-label="Photo carousel controls">
              <form method="get" action="/">
                <input type="hidden" name="offset" value="{offset}" />
                <input type="hidden" name="photo" value="{prev_photo}" />
                <button class="carousel-btn" type="submit" aria-label="Previous photo">Prev</button>
              </form>
              <div class="carousel-middle">
                <div class="carousel-meta">{current_index + 1} / {photo_count}</div>
                <div class="carousel-dots" aria-hidden="true">{dots}</div>
              </div>
              <form method="get" action="/">
                <input type="hidden" name="offset" value="{offset}" />
                <input type="hidden" name="photo" value="{next_photo}" />
                <button class="carousel-btn" type="submit" aria-label="Next photo">Next</button>
              </form>
            </div>
        """

    info_msg = f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    page_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>PupSwipe | PuppyPing</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="background">
      <div class="glow glow-a"></div>
      <div class="glow glow-b"></div>
      <div class="grid"></div>
    </div>

    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">PS</div>
          <div>
            <h1>PupSwipe</h1>
            <p>By PuppyPing</p>
          </div>
        </div>
        <div class="topbar-meta">
          <div class="stats">{escape(stats)}</div>
          <a class="profile-link top-profile-link" href="{profile_url}" target="_blank" rel="noopener">Open profile</a>
        </div>
      </header>

      {info_msg}

      <main>
        <section class="stack">
          <article id="swipe-card" class="card enter" data-swipe-threshold="110">
            <div class="card-photo">
              {image_block}
              <div class="swipe-indicator like">Like</div>
              <div class="swipe-indicator nope">Nope</div>
            </div>
            <div class="card-body">
              <div class="card-title">
                <h2>{name}</h2>
                <span class="age-pill">{age_raw}</span>
              </div>
              <div class="card-facts">
                <span>{breed}</span>
                <span>{gender}</span>
                <span>{location}</span>
              </div>
              <div class="badges">
                <span class="badge">{status}</span>
                <span class="badge badge-provider">{provider_name}</span>
              </div>
              {carousel_controls}
              <div class="description-wrap">
                <h3 class="description-label">Description</h3>
                <p class="description">{description}</p>
              </div>
              <div class="provider-panel">
                <span class="provider-label">Provider link</span>
                {provider_link_html}
              </div>
            </div>
          </article>
        </section>

        <section class="controls" aria-label="Swipe controls">
          <form id="swipe-nope-form" method="post" action="/swipe">
            <input type="hidden" name="dog_id" value="{dog_id}" />
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="swipe" value="left" />
            <button class="btn nope" type="submit">Nope</button>
          </form>
          <form method="get" action="/">
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="random" value="1" />
            <button class="btn refresh" type="submit">Random</button>
          </form>
          <form id="swipe-like-form" method="post" action="/swipe">
            <input type="hidden" name="dog_id" value="{dog_id}" />
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="swipe" value="right" />
            <button class="btn like" type="submit">Like</button>
          </form>
        </section>
      </main>

      <section class="ecosystem" aria-label="PuppyPing ecosystem">
        <h3>Get PuppyPing Alerts</h3>
        <p class="ecosystem-copy">
          PupSwipe is part of the PuppyPing ecosystem. Join PuppyPing email alerts to get fresh puppy updates.
        </p>
        <p class="ecosystem-copy">
          {escape(PROVIDER_DISCLAIMER)}
        </p>
        <form class="subscribe-form" method="post" action="/subscribe">
          <input type="hidden" name="offset" value="{offset}" />
          <input type="hidden" name="photo" value="{current_photo_index}" />
          <label class="subscribe-label" for="subscribe-email">Email for PuppyPing alerts</label>
          <div class="subscribe-row">
            <input
              id="subscribe-email"
              name="email"
              type="email"
              inputmode="email"
              autocomplete="email"
              placeholder="you@example.com"
              required
            />
            <button class="btn subscribe" type="submit">Join</button>
          </div>
        </form>
      </section>

    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
    return page_html.encode("utf-8")


class AppHandler(SimpleHTTPRequestHandler):
    """HTTP handler for PupSwipe API and server-rendered pages."""

    def __init__(self, *args, **kwargs):
        """Initialize the handler with the app directory as static root.

        Args:
            *args: Positional arguments passed to the base handler.
            **kwargs: Keyword arguments passed to the base handler.
        """
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def end_headers(self):
        """Attach client hint headers before completing the response.

        Returns:
            None.
        """
        self.send_header(
            "Accept-CH",
            "Viewport-Width, Sec-CH-Viewport-Width, Width, DPR, Sec-CH-UA, Sec-CH-UA-Platform, Sec-CH-UA-Mobile",
        )
        super().end_headers()

    def _send_json(self, status: int, payload: dict) -> None:
        """Write a JSON response.

        Args:
            status: HTTP status code.
            payload: JSON-serializable response payload.

        Returns:
            None.
        """
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _first_header(self, *names: str) -> str | None:
        """Return the first non-empty header value from a list of names.

        Args:
            *names: Candidate header names to inspect in order.

        Returns:
            The stripped header value if found, otherwise ``None``.
        """
        for name in names:
            value = self.headers.get(name)
            if value:
                return value.strip()
        return None

    def _client_ip(self) -> str | None:
        """Resolve the most likely client IP.

        Returns:
            The client IP address if available, otherwise ``None``.
        """
        forwarded = self._first_header(
            "X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP"
        )
        if forwarded:
            return forwarded.split(",")[0].strip()
        if self.client_address:
            return self.client_address[0]
        return None

    def _screen_info(self, payload: dict | None = None) -> dict | None:
        """Build screen/client-hint metadata from headers and optional payload.

        Args:
            payload: Optional request payload containing client screen values.

        Returns:
            A metadata dictionary, or ``None`` when no values are available.
        """
        info: dict[str, str | int | float | bool] = {}
        header_map = {
            "viewport_width": ("Viewport-Width", "Sec-CH-Viewport-Width", "Width"),
            "pixel_ratio": ("DPR",),
            "ua_platform": ("Sec-CH-UA-Platform",),
            "ua_mobile": ("Sec-CH-UA-Mobile",),
            "ua_hint": ("Sec-CH-UA",),
            "device_memory": ("Device-Memory",),
        }
        for key, names in header_map.items():
            value = self._first_header(*names)
            if value:
                info[key] = value

        if isinstance(payload, dict):
            screen_payload = payload.get("screen_info")
            if isinstance(screen_payload, dict):
                for key, value in screen_payload.items():
                    if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                        info[f"client_{key}"] = value

            for key in (
                "screen_width",
                "screen_height",
                "viewport_width",
                "viewport_height",
                "pixel_ratio",
            ):
                value = payload.get(key)
                if isinstance(value, (str, int, float, bool)):
                    info[f"client_{key}"] = value

        return info or None

    def _user_context(self, payload: dict | None = None) -> dict:
        """Build user context fields used for swipe analytics.

        Args:
            payload: Optional body/form payload.

        Returns:
            A dictionary containing user fingerprint and client metadata.
        """
        user_ip = self._client_ip()
        user_agent = self._first_header("User-Agent")
        accept_language = self._first_header("Accept-Language")
        screen_info = self._screen_info(payload)

        fingerprint_input = "|".join(
            [
                user_ip or "",
                user_agent or "",
                json.dumps(screen_info, sort_keys=True) if screen_info else "",
            ]
        )
        user_key = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()[:32]
        return {
            "user_key": user_key,
            "user_ip": user_ip,
            "user_agent": user_agent,
            "accept_language": accept_language,
            "screen_info": screen_info,
        }

    def do_GET(self):
        """Handle GET requests for APIs, root page, and static assets.

        Returns:
            None.
        """
        parsed = urlparse(self.path)
        if parsed.path == "/api/puppies":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", [DEFAULT_LIMIT])[0])
            except ValueError:
                return self._send_json(400, {"error": "limit must be an integer"})
            limit = max(1, min(MAX_LIMIT, limit))
            try:
                puppies = _fetch_puppies(limit)
            except Exception as exc:
                return self._send_json(
                    500,
                    {"error": "failed to load puppies", "detail": str(exc)},
                )
            return self._send_json(
                200, {"items": puppies, "count": len(puppies)}
            )

        if parsed.path == "/api/health":
            try:
                _fetch_puppies(1)
                return self._send_json(200, {"ok": True})
            except Exception as exc:
                return self._send_json(500, {"ok": False, "detail": str(exc)})

        if parsed.path == "/" or parsed.path == "/index.html":
            query = parse_qs(parsed.query)
            offset = _safe_int(query.get("offset", ["0"])[0], 0)
            photo_index = _safe_int(query.get("photo", ["0"])[0], 0)
            randomize = query.get("random", ["0"])[0].strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            msg = query.get("msg", [None])[0]
            body = _render_page(
                offset=offset,
                message=msg,
                photo_index=photo_index,
                randomize=randomize,
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        return super().do_GET()

    def do_POST(self):
        """Handle POST requests for subscriptions, swipes, and API writes.

        Returns:
            None.
        """
        parsed = urlparse(self.path)
        if parsed.path == "/subscribe":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)

            offset = _safe_int(form.get("offset", ["0"])[0], 0)
            photo_index = _safe_int(form.get("photo", ["0"])[0], 0)
            email = _normalize_email(form.get("email", [""])[0])

            query_params = {"offset": str(offset), "photo": str(photo_index)}
            if not _is_valid_email(email):
                query_params["msg"] = "Enter a valid email address."
                query = urlencode(query_params)
                self.send_response(303)
                self.send_header("Location", f"/?{query}")
                self.end_headers()
                return

            try:
                created = add_email_subscriber(email, source="pupswipe")
            except Exception as exc:
                query_params["msg"] = f"Failed to save subscription: {exc}"
                query = urlencode(query_params)
                self.send_response(303)
                self.send_header("Location", f"/?{query}")
                self.end_headers()
                return

            query_params["msg"] = (
                "Subscribed to PuppyPing email updates."
                if created
                else "Email is already subscribed."
            )
            query = urlencode(query_params)
            self.send_response(303)
            self.send_header("Location", f"/?{query}")
            self.end_headers()
            return

        if parsed.path == "/swipe":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            form = parse_qs(body)
            form_payload = {
                key: values[0]
                for key, values in form.items()
                if isinstance(values, list) and values
            }
            try:
                dog_id = int(form.get("dog_id", [""])[0])
            except (TypeError, ValueError):
                self.send_response(303)
                self.send_header("Location", "/?msg=Invalid+dog+id")
                self.end_headers()
                return

            swipe = form.get("swipe", [""])[0]
            if swipe not in ("left", "right"):
                self.send_response(303)
                self.send_header("Location", "/?msg=Invalid+swipe+value")
                self.end_headers()
                return

            offset = _safe_int(form.get("offset", ["0"])[0], 0)
            try:
                _store_swipe(
                    dog_id,
                    swipe,
                    source="pupswipe",
                    **self._user_context(form_payload),
                )
            except Exception as exc:
                query = urlencode({"msg": f"Failed to store swipe: {exc}"})
                self.send_response(303)
                self.send_header("Location", f"/?{query}")
                self.end_headers()
                return

            query = urlencode({"offset": str(offset + 1)})
            self.send_response(303)
            self.send_header("Location", f"/?{query}")
            self.end_headers()
            return

        if parsed.path != "/api/swipes":
            self.send_error(404, "Not Found")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return self._send_json(400, {"error": "invalid json"})

        try:
            dog_id = int(payload.get("dog_id"))
        except (TypeError, ValueError):
            return self._send_json(400, {"error": "dog_id is required"})

        swipe = payload.get("swipe")
        if swipe not in ("left", "right"):
            return self._send_json(400, {"error": "swipe must be left or right"})

        source = payload.get("source")
        try:
            _store_swipe(
                dog_id,
                swipe,
                source,
                **self._user_context(payload),
            )
        except Exception as exc:
            return self._send_json(500, {"error": "failed to store swipe", "detail": str(exc)})

        return self._send_json(201, {"ok": True})

    def log_message(self, fmt, *args):
        """Suppress default HTTP request logging output.

        Args:
            fmt: Log format string.
            *args: Format arguments.

        Returns:
            None.
        """
        return


def main() -> None:
    """Run the PupSwipe HTTP server from CLI arguments.

    Returns:
        None.
    """
    parser = argparse.ArgumentParser(description="Serve PupSwipe web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"PupSwipe running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
