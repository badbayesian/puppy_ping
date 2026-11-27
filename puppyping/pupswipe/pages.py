"""HTML rendering helpers for PupSwipe."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from typing import Callable
from urllib.parse import urlencode

_FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    "<rect width='64' height='64' rx='18' fill='%23d85a3f'/>"
    "<circle cx='21' cy='25' r='5' fill='%23fff'/>"
    "<circle cx='32' cy='20' r='5' fill='%23fff'/>"
    "<circle cx='43' cy='25' r='5' fill='%23fff'/>"
    "<path d='M20 42c0-7 5-12 12-12s12 5 12 12c0 4-3 7-7 7-3 0-4-1-5-1s-2 1-5 1c-4 0-7-3-7-7z' fill='%23fff'/>"
    "</svg>"
)
_FAVICON_LINK = (
    f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{_FAVICON_SVG}" />'
)

_ICON_PAW = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">'
    '<circle cx="6.5" cy="9.5" r="2.1"/>'
    '<circle cx="12" cy="7.2" r="2.2"/>'
    '<circle cx="17.5" cy="9.5" r="2.1"/>'
    '<path d="M6.4 17.2c0-3.3 2.5-5.6 5.6-5.6s5.6 2.3 5.6 5.6c0 1.9-1.5 3.3-3.4 3.3-1.2 0-1.7-.5-2.2-.5s-1 .5-2.2.5c-1.9 0-3.4-1.4-3.4-3.3z"/>'
    "</svg>"
)
_ICON_PASS = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M18 6 6 18M6 6l12 12"/></svg>'
)
_ICON_HEART = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">'
    '<path d="M12 20.4s-7.4-4.7-9.6-9.1C.8 8.2 2.4 4.5 6 4.1c2-.2 3.8.8 4.9 2.3h2.2C14.2 4.9 16 3.9 18 4.1c3.6.4 5.2 4.1 3.6 7.2-2.2 4.4-9.6 9.1-9.6 9.1z"/>'
    "</svg>"
)
_ICON_HEART_OUTLINE = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 20.4s-7.4-4.7-9.6-9.1C.8 8.2 2.4 4.5 6 4.1c2-.2 3.8.8 4.9 2.3h2.2C14.2 4.9 16 3.9 18 4.1c3.6.4 5.2 4.1 3.6 7.2-2.2 4.4-9.6 9.1-9.6 9.1z"/>'
    "</svg>"
)
_ICON_RANDOM = (
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" '
    'stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/></svg>'
)
_ICON_EXTERNAL = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
    '<path d="M15 3h6v6M10 14 21 3"/></svg>'
)
_ICON_FILTER = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="2.1" stroke-linecap="round" aria-hidden="true">'
    '<path d="M4 6h16M7 12h10M10 18h4"/></svg>'
)
_ICON_CHEVRON_DOWN = (
    '<svg class="filter-chevron" viewBox="0 0 24 24" width="14" height="14" fill="none" '
    'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="m6 9 6 6 6-6"/></svg>'
)
_ICON_CHEVRON_LEFT = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="m15 18-6-6 6-6"/></svg>'
)
_ICON_CHEVRON_RIGHT = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
    'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="m9 18 6-6-6-6"/></svg>'
)
_ICON_SHARE = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>'
    '<path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/></svg>'
)
_ICON_TRASH = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" '
    'stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M3 6h18M8 6V4h8v2M6 6v14a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V6"/></svg>'
)
_ICON_BELL = (
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" '
    'stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>'
    '<path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>'
)
_PAGE_SHELL_BG = ""


@dataclass(frozen=True)
class PageDeps:
    normalize_breed_filter: Callable[[str | None], str]
    normalize_name_filter: Callable[[str | None], str]
    normalize_provider_filter: Callable[[str | None], str]
    normalize_species_filter: Callable[[str | None], str]
    normalize_max_age_filter: Callable[[object], float]
    filter_hidden_inputs: Callable[..., str]
    count_puppies: Callable[..., int]
    count_unseen_puppies: Callable[..., int]
    count_passed_puppies: Callable[..., int]
    fetch_puppies: Callable[..., list[dict]]
    provider_name: Callable[[str | None, str | None], str]
    safe_int: Callable[[str | None, int], int]
    normalize_next_path: Callable[[str | None, str], str]
    pupswipe_sources: tuple[str, ...]
    page_size: int
    max_puppy_age_months: float
    max_breed_filter_length: int
    max_name_filter_length: int
    password_min_length: int
    provider_disclaimer: str


def _safe_initials(raw_name: object, fallback: str = "PUP") -> str:
    """Build two-character fallback initials from raw text before HTML escaping."""
    text = str(raw_name or "").strip()
    parts = [part for part in text.split() if part]
    letters: list[str] = []
    for part in parts[:2]:
        for ch in part:
            if ch.isalnum():
                letters.append(ch.upper())
                break
    initials = "".join(letters)[:2] or fallback
    return escape(initials)


def _head_html(title: str) -> str:
    """Render shared document head markup with inline SVG favicon."""
    return f"""  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    {_FAVICON_LINK}
    <link rel="stylesheet" href="/styles.css" />
  </head>"""


def _render_topbar(
    *,
    active_nav: str,
    title: str,
    subtitle: str,
    signed_in_email: str | None = None,
    signin_next: str = "/",
    signout_next: str = "/",
    show_nav: bool = True,
    show_signin_cta: bool = True,
) -> str:
    """Render consistent top bar with segmented primary nav and compact account menu."""
    escaped_email = escape(signed_in_email) if signed_in_email else ""
    nav_html = ""
    if show_nav:
        swipe_cls = "nav-pill is-active" if active_nav == "swipe" else "nav-pill"
        catalog_cls = "nav-pill is-active" if active_nav == "catalog" else "nav-pill"
        likes_cls = "nav-pill is-active" if active_nav == "likes" else "nav-pill"
        swipe_current = ' aria-current="page"' if active_nav == "swipe" else ""
        catalog_current = ' aria-current="page"' if active_nav == "catalog" else ""
        likes_current = ' aria-current="page"' if active_nav == "likes" else ""
        likes_nav = (
            f'<a class="{likes_cls}" href="/likes"{likes_current}>Liked pups</a>'
            if signed_in_email
            else ""
        )
        nav_html = f"""
        <nav class="primary-nav" aria-label="Primary navigation">
          <a class="{swipe_cls}" href="/"{swipe_current}>Swipe</a>
          <a class="{catalog_cls}" href="/catalog"{catalog_current}>Catalog</a>
          {likes_nav}
        </nav>"""

    if signed_in_email:
        avatar_char = _safe_initials(signed_in_email, "U")[0]
        local_handle = signed_in_email.split("@", 1)[0]
        account_html = f"""
        <div class="account-actions">
          <details class="account-menu">
            <summary class="account-trigger" aria-label="Account menu">
              <span class="account-avatar" aria-hidden="true">{avatar_char}</span>
              <span class="account-handle">{escape(local_handle)}</span>
              {_ICON_CHEVRON_DOWN}
            </summary>
            <div class="account-dropdown">
              <div class="account-dropdown-head">
                <span class="account-role">Signed in</span>
                <span class="account-email">{escaped_email}</span>
              </div>
              <a class="account-menu-item" href="/reset-password">Reset password</a>
              <form class="inline-form" method="post" action="/signout">
                <input type="hidden" name="next" value="{escape(signout_next)}" />
                <button class="btn subtle account-signout-btn" type="submit">Sign out</button>
              </form>
            </div>
          </details>
        </div>"""
    elif show_signin_cta:
        signin_query = urlencode({"next": signin_next})
        account_html = f"""
        <div class="account-actions">
          <a class="profile-link account-link" href="/signin?{signin_query}">Sign in to save likes</a>
        </div>"""
    else:
        account_html = ""

    return f"""
      <header class="topbar">
        <div class="topbar-inner">
          <a class="brand" href="/">
            <div class="brand-mark">{_ICON_PAW}</div>
            <div>
              <h1>{escape(title)}</h1>
              <p>{escape(subtitle)}</p>
            </div>
          </a>
          {nav_html}
          {account_html}
        </div>
      </header>"""


def _provider_options_html(
    sources: tuple[str, ...],
    normalized_provider: str,
    provider_name_fn: Callable[[str | None, str | None], str],
) -> str:
    """Build provider <option> markup."""
    options = ['<option value="">All providers</option>']
    for source in sources:
        selected_attr = " selected" if source == normalized_provider else ""
        options.append(
            f'<option value="{escape(source)}"{selected_attr}>'
            f"{escape(provider_name_fn(source, None))}</option>"
        )
    return "".join(options)


def _species_options_html(normalized_species: str) -> str:
    """Build species <option> markup."""
    species_values = ["", "dog", "cat", "rabbit", "bird", "other"]
    if normalized_species and normalized_species not in species_values:
        species_values.append(normalized_species)
    return "".join(
        (
            f'<option value="{escape(value)}"'
            f'{" selected" if value == normalized_species else ""}>'
            f'{escape("All species" if value == "" else value.title())}</option>'
        )
        for value in species_values
    )


def _render_filter_bar(
    *,
    form_id: str,
    id_prefix: str,
    action: str,
    aria_label: str,
    stats_text: str,
    active_filter_chips: list[str],
    breed_value: str,
    name_value: str,
    species_options_html: str,
    provider_options_html: str,
    max_age_value: str,
    max_breed_len: int,
    max_name_len: int,
    clear_filter_html: str,
    review_mode_hidden_input: str = "",
    open_by_default: bool = False,
) -> str:
    """Render shared collapsible filter drawer with live auto-filter inputs."""
    open_attr = " open" if open_by_default else ""
    active_count = len(active_filter_chips)
    count_badge = (
        f'<span class="filter-count">{active_count}</span>' if active_count else ""
    )
    chips_html = ""
    if active_filter_chips:
        chips_items = "".join(
            f'<span class="filter-chip">{escape(chip)}</span>'
            for chip in active_filter_chips
        )
        chips_html = f'<span class="active-filter-chips">{chips_items}</span>'

    return f"""
      <section class="filter-strip" aria-label="{escape(aria_label)}">
        <details class="filter-drawer"{open_attr}>
          <summary class="filter-drawer-summary">
            <span class="filter-summary-left">
              <span class="stats">{escape(stats_text)}</span>
              {chips_html}
            </span>
            <span class="filter-toggle-pill">
              {_ICON_FILTER}
              <span>Filters</span>
              {count_badge}
              {_ICON_CHEVRON_DOWN}
            </span>
          </summary>
          <form
            id="{escape(form_id)}"
            class="breed-filter-form"
            method="get"
            action="{escape(action)}"
            data-auto-filter="1"
          >
            {review_mode_hidden_input}
            <div class="filter-field">
              <label for="{escape(id_prefix)}breed-filter">Breed</label>
              <input
                id="{escape(id_prefix)}breed-filter"
                name="breed"
                type="text"
                value="{breed_value}"
                placeholder="e.g. Labrador"
                maxlength="{max_breed_len}"
              />
            </div>
            <div class="filter-field">
              <label for="{escape(id_prefix)}name-filter">Name</label>
              <input
                id="{escape(id_prefix)}name-filter"
                name="name"
                type="text"
                value="{name_value}"
                placeholder="e.g. Nova"
                maxlength="{max_name_len}"
              />
            </div>
            <div class="filter-field">
              <label for="{escape(id_prefix)}species-filter">Species</label>
              <select id="{escape(id_prefix)}species-filter" name="species">
                {species_options_html}
              </select>
            </div>
            <div class="filter-field">
              <label for="{escape(id_prefix)}provider-filter">Provider</label>
              <select id="{escape(id_prefix)}provider-filter" name="provider">
                {provider_options_html}
              </select>
            </div>
            <div class="filter-field">
              <label for="{escape(id_prefix)}max-age-filter">Max age (months)</label>
              <input
                id="{escape(id_prefix)}max-age-filter"
                name="max_age"
                type="number"
                min="0.5"
                max="120"
                step="0.5"
                value="{max_age_value}"
                data-auto-submit-delay-ms="1200"
                inputmode="decimal"
              />
            </div>
            {clear_filter_html}
          </form>
        </details>
      </section>
    """


def _render_ecosystem_section(
    *,
    input_id: str,
    current_photo_index: int,
    filter_hidden_inputs: str,
    provider_disclaimer: str,
) -> str:
    """Render subtle editorial PuppyPing alert signup footer."""
    return f"""
      <footer class="ecosystem" aria-label="PuppyPing email alerts">
        <div class="ecosystem-info">
          <div class="ecosystem-head">
            <span class="ecosystem-icon" aria-hidden="true">{_ICON_BELL}</span>
            <h3>Daily PuppyPing Alerts</h3>
          </div>
          <p class="ecosystem-copy">
            Join the PuppyPing email list for newly spotted adoptable puppies. {escape(provider_disclaimer)}
          </p>
        </div>
        <form class="subscribe-form" method="post" action="/subscribe">
          <input type="hidden" name="photo" value="{current_photo_index}" />
          {filter_hidden_inputs}
          <label class="subscribe-label" for="{escape(input_id)}">Email for PuppyPing alerts</label>
          <div class="subscribe-row">
            <input
              id="{escape(input_id)}"
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
      </footer>
    """


def _normalize_safe_photo_url(value: object) -> str | None:
    """Return a trimmed photo URL only when its scheme is safe for img/JS rendering."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    lower = candidate.lower()
    if lower.startswith("https://") or lower.startswith("http://"):
        return candidate
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return None


def _get_primary_image(pup: dict) -> str | None:
    """Extract the primary image URL from a dog record.

    Args:
        pup: Dog profile dictionary.

    Returns:
        The primary image URL if present, otherwise ``None``.
    """
    primary = _normalize_safe_photo_url(pup.get("primary_image"))
    if primary:
        return primary
    media = pup.get("media") or {}
    images = media.get("images") if isinstance(media, dict) else None
    if isinstance(images, list):
        for item in images:
            safe_url = _normalize_safe_photo_url(item)
            if safe_url:
                return safe_url
    return None


def _get_photo_urls(pup: dict) -> list[str]:
    """Collect unique safe photo URLs for a dog record.

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
            safe_url = _normalize_safe_photo_url(item)
            if safe_url and safe_url not in urls:
                urls.append(safe_url)
    return urls


def _filtered_species_label(species_filter: str) -> str:
    """Return copy-friendly plural label for species-filter empty states."""
    normalized = str(species_filter or "").strip().lower()
    if not normalized:
        return "puppies"

    if normalized == "dog":
        return "dogs"
    if normalized == "cat":
        return "cats"
    if normalized == "rabbit":
        return "rabbits"
    if normalized == "bird":
        return "birds"
    if normalized == "other":
        return "pets"
    if normalized.endswith("s"):
        return normalized
    return f"{normalized} profiles"


def _render_page(
    message: str | None = None,
    photo_index: int = 0,
    randomize: bool = False,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = 8.0,
    signed_in_email: str | None = None,
    viewer_user_id: int | None = None,
    viewer_user_key: str | None = None,
    review_passed: bool = False,
    pinned_profile_url: str = "",
    skip_profile_url: str = "",
    *,
    deps: PageDeps,
) -> bytes:
    """Render the main HTML page.

    Args:
        message: Optional info/error message to display.
        photo_index: Selected image index within the current dog carousel.
        randomize: Whether to pick a random dog from the current result set.
        breed_filter: Optional breed filter text.
        name_filter: Optional name filter text.
        provider_filter: Optional provider source filter text.
        species_filter: Optional species filter text.
        max_age_months: Maximum age in months to include.
        signed_in_email: Optional signed-in email for account actions.
        viewer_user_id: Optional signed-in user id for unseen tracking.
        viewer_user_key: Optional anonymous viewer key for unseen tracking.
        review_passed: Whether to review previously passed pets.
        pinned_profile_url: Optional profile URL to keep the current card pinned.
        skip_profile_url: Optional profile URL to exclude from random results.

    Returns:
        UTF-8 encoded HTML document bytes.
    """
    _normalize_breed_filter = deps.normalize_breed_filter
    _normalize_name_filter = deps.normalize_name_filter
    _normalize_provider_filter = deps.normalize_provider_filter
    _normalize_species_filter = deps.normalize_species_filter
    _normalize_max_age_filter = deps.normalize_max_age_filter
    _filter_hidden_inputs = deps.filter_hidden_inputs
    _count_puppies = deps.count_puppies
    _count_unseen_puppies = deps.count_unseen_puppies
    _count_passed_puppies = deps.count_passed_puppies
    _fetch_puppies = deps.fetch_puppies
    _provider_name = deps.provider_name
    _safe_int = deps.safe_int
    PUPSWIPE_SOURCES = deps.pupswipe_sources
    PAGE_SIZE = deps.page_size
    MAX_PUPPY_AGE_MONTHS = deps.max_puppy_age_months
    MAX_BREED_FILTER_LENGTH = deps.max_breed_filter_length
    MAX_NAME_FILTER_LENGTH = deps.max_name_filter_length
    PROVIDER_DISCLAIMER = deps.provider_disclaimer

    normalized_breed = _normalize_breed_filter(breed_filter)
    normalized_name = _normalize_name_filter(name_filter)
    normalized_provider = _normalize_provider_filter(provider_filter)
    normalized_species = _normalize_species_filter(species_filter)
    normalized_max_age_months = _normalize_max_age_filter(max_age_months)
    normalized_pinned_profile_url = " ".join((pinned_profile_url or "").split()).strip()
    normalized_skip_profile_url = " ".join((skip_profile_url or "").split()).strip()
    escaped_breed = escape(normalized_breed)
    escaped_name = escape(normalized_name)
    escaped_max_age = escape(f"{normalized_max_age_months:g}")
    filter_hidden_inputs = _filter_hidden_inputs(
        breed_filter=normalized_breed,
        name_filter=normalized_name,
        provider_filter=normalized_provider,
        species_filter=normalized_species,
        max_age_months=normalized_max_age_months,
        review_mode="passed" if review_passed else "",
    )
    topbar_html = _render_topbar(
        active_nav="swipe",
        title="PupSwipe",
        subtitle="By PuppyPing",
        signed_in_email=signed_in_email,
        signin_next="/",
        signout_next="/",
    )

    try:
        total = _count_puppies(
            breed_filter=normalized_breed,
            name_filter=normalized_name,
            provider_filter=normalized_provider,
            species_filter=normalized_species,
            max_age_months=normalized_max_age_months,
        )
        if review_passed:
            remaining = _count_passed_puppies(
                breed_filter=normalized_breed,
                name_filter=normalized_name,
                provider_filter=normalized_provider,
                species_filter=normalized_species,
                max_age_months=normalized_max_age_months,
                viewer_user_id=viewer_user_id,
                viewer_user_key=viewer_user_key,
            )
        else:
            remaining = _count_unseen_puppies(
                breed_filter=normalized_breed,
                name_filter=normalized_name,
                provider_filter=normalized_provider,
                species_filter=normalized_species,
                max_age_months=normalized_max_age_months,
                viewer_user_id=viewer_user_id,
                viewer_user_key=viewer_user_key,
            )
        completed_cycle = (not review_passed) and total > 0 and remaining <= 0
        if remaining > 0:
            fetch_kwargs = {
                "breed_filter": normalized_breed,
                "name_filter": normalized_name,
                "provider_filter": normalized_provider,
                "species_filter": normalized_species,
                "max_age_months": normalized_max_age_months,
                "viewer_user_id": viewer_user_id,
                "viewer_user_key": viewer_user_key,
                "randomize": randomize,
                "review_passed": review_passed,
            }
            if normalized_pinned_profile_url:
                fetch_kwargs["pinned_profile_url"] = normalized_pinned_profile_url
            if randomize and normalized_skip_profile_url:
                fetch_kwargs["excluded_profile_url"] = normalized_skip_profile_url
            puppies = _fetch_puppies(PAGE_SIZE, **fetch_kwargs)
        else:
            puppies = []
    except Exception as exc:
        error_html = f"""<!doctype html>
<html lang="en">
{_head_html("PupSwipe | PuppyPing")}
  <body class="swipe-page">
    {topbar_html}
    <div class="app">
      <main class="swipe-main">
        <section class="stack">
          <div class="state state-error">Failed to load puppies: {escape(str(exc))}</div>
        </section>
      </main>
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
        return error_html.encode("utf-8")

    if total:
        stats_text = (
            f"{max(remaining, 0)} passed left of {total}"
            if review_passed
            else f"{max(remaining, 0)} left of {total}"
        )
    else:
        stats_text = "No puppies found"

    active_filters: list[str] = []
    if normalized_breed:
        active_filters.append(f"Breed: {normalized_breed}")
    if normalized_name:
        active_filters.append(f"Name: {normalized_name}")
    if normalized_provider:
        active_filters.append(f"Provider: {_provider_name(normalized_provider, None)}")
    if normalized_species:
        active_filters.append(f"Species: {normalized_species.title()}")
    if normalized_max_age_months != MAX_PUPPY_AGE_MONTHS:
        active_filters.append(f"Max age: {normalized_max_age_months:g} mo")

    clear_filter_html = ""
    if active_filters:
        clear_params = {"clear_filters": "1"}
        if review_passed:
            clear_params["review"] = "passed"
        clear_query = urlencode(clear_params)
        clear_filter_html = f'<a class="clear-filter" href="/?{clear_query}">Clear</a>'

    provider_options_html = _provider_options_html(
        PUPSWIPE_SOURCES, normalized_provider, _provider_name
    )
    species_options_html = _species_options_html(normalized_species)
    review_mode_hidden_input = (
        '<input type="hidden" name="review" value="passed" />' if review_passed else ""
    )

    filter_bar = _render_filter_bar(
        form_id="auto-filter-form",
        id_prefix="",
        action="/",
        aria_label="Pup filters",
        stats_text=stats_text,
        active_filter_chips=active_filters,
        breed_value=escaped_breed,
        name_value=escaped_name,
        species_options_html=species_options_html,
        provider_options_html=provider_options_html,
        max_age_value=escaped_max_age,
        max_breed_len=MAX_BREED_FILTER_LENGTH,
        max_name_len=MAX_NAME_FILTER_LENGTH,
        clear_filter_html=clear_filter_html,
        review_mode_hidden_input=review_mode_hidden_input,
        open_by_default=False,
    )

    if completed_cycle and total > 0:
        filtered_species_label = _filtered_species_label(normalized_species)
        completion_copy = (
            message
            or f"You've swiped through all {filtered_species_label} in this filter."
        )
        celebration_html = f"""<!doctype html>
<html lang="en">
{_head_html("PupSwipe | PuppyPing")}
  <body class="swipe-page">
    {topbar_html}
    <div class="app">
      <main class="swipe-main">
        {filter_bar}
        <section class="stack">
          <div class="state state-complete">
            <div class="celebrate-burst" aria-hidden="true">
              <span class="burst-dot dot-a"></span>
              <span class="burst-dot dot-b"></span>
              <span class="burst-dot dot-c"></span>
              <span class="burst-dot dot-d"></span>
              <span class="burst-dot dot-e"></span>
              <span class="burst-dot dot-f"></span>
            </div>
            <h2 class="complete-title">All pets reviewed</h2>
            <p class="complete-copy">{escape(completion_copy)}</p>
          </div>
        </section>
        <section class="controls controls-compact">
          <form method="get" action="/">
            <input type="hidden" name="review" value="passed" />
            {filter_hidden_inputs}
            <button class="btn like" type="submit"><span class="btn-icon" aria-hidden="true">{_ICON_HEART}</span>Start over</button>
          </form>
          <form method="get" action="/">
            <input type="hidden" name="random" value="1" />
            {filter_hidden_inputs}
            <button class="btn refresh" type="submit"><span class="btn-icon" aria-hidden="true">{_ICON_RANDOM}</span>Random</button>
          </form>
        </section>
      </main>
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
        return celebration_html.encode("utf-8")

    if not puppies:
        filtered_species_label = _filtered_species_label(normalized_species)
        empty_msg = message or (
            f"No {filtered_species_label} match those filters. Try different filters."
            if active_filters
            else "No puppies to show yet. Run scraper and refresh."
        )
        if review_passed and not message:
            empty_msg = "No previously passed pets are still available in this filter."
        ecosystem_empty = _render_ecosystem_section(
            input_id="subscribe-email-empty",
            current_photo_index=0,
            filter_hidden_inputs=filter_hidden_inputs,
            provider_disclaimer=PROVIDER_DISCLAIMER,
        )
        no_data = f"""<!doctype html>
<html lang="en">
{_head_html("PupSwipe | PuppyPing")}
  <body class="swipe-page">
    {topbar_html}
    <div class="app">
      <main class="swipe-main">
        {filter_bar}
        <section class="stack">
          <div class="state state-empty">{escape(empty_msg)}</div>
        </section>
        <section class="controls controls-single">
          <form method="get" action="/">
            <input type="hidden" name="random" value="1" />
            {filter_hidden_inputs}
            <button class="btn refresh" type="submit"><span class="btn-icon" aria-hidden="true">{_ICON_RANDOM}</span>Random</button>
          </form>
        </section>
      </main>
      {ecosystem_empty}
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
        return no_data.encode("utf-8")

    pup = puppies[0]
    dog_id = _safe_int(str(pup.get("dog_id")), 0)
    species = escape(
        " ".join(str(pup.get("species") or "dog").split()).strip().lower() or "dog"
    )
    species_display = escape(
        (" ".join(str(pup.get("species") or "dog").split()).strip() or "dog").title()
    )

    raw_name = str(pup.get("name") or "Unnamed pup")
    name = escape(raw_name)
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
    swipe_source = " ".join((source_key or "").split()).strip()
    escaped_swipe_source = escape(swipe_source)
    provider_name = escape(_provider_name(source_key, raw_profile_url))
    if raw_profile_url:
        provider_link_html = (
            f'<a class="profile-link card-profile-link" href="{profile_url}" '
            f'target="_blank" rel="noopener">View on {provider_name}{_ICON_EXTERNAL}</a>'
        )
    else:
        provider_link_html = f'<span class="provider-missing">{provider_name}</span>'

    photo_urls = _get_photo_urls(pup)
    photo_count = len(photo_urls)
    current_photo_index = photo_index % photo_count if photo_count > 0 else 0
    if photo_count > 0:
        selected_photo = photo_urls[current_photo_index]
        image_block = (
            f'<img src="{escape(selected_photo)}" alt="{name} photo" '
            'referrerpolicy="no-referrer" draggable="false" />'
        )
        photo_data_attrs = (
            f' data-photos="{escape(json.dumps(photo_urls))}"'
            f' data-photo-index="{current_photo_index}"'
        )
        card_classes = "card enter has-photo"
    else:
        initials = _safe_initials(raw_name, "PUP")
        image_block = f'<div class="photo-fallback">{initials}</div>'
        photo_data_attrs = ""
        card_classes = "card enter"

    has_carousel = photo_count > 1
    carousel_pin_url_html = (
        f'<input type="hidden" name="pin_url" value="{escape(raw_profile_url)}" />'
        if raw_profile_url
        else ""
    )
    carousel_controls = ""
    if has_carousel:
        prev_photo = (photo_index - 1) % photo_count
        next_photo = (photo_index + 1) % photo_count
        dots = "".join(
            f'<span class="carousel-dot{" is-active" if idx == current_photo_index else ""}" aria-hidden="true"></span>'
            for idx in range(photo_count)
        )
        carousel_controls = f"""
            <div class="carousel-progress" aria-hidden="true">
              <div class="carousel-dots">{dots}</div>
            </div>
            <div class="carousel-controls" aria-label="Photo carousel controls">
              <form method="get" action="/">
                <input type="hidden" name="photo" value="{prev_photo}" />
                {carousel_pin_url_html}
                {filter_hidden_inputs}
                <button class="carousel-btn carousel-btn-prev" type="submit" aria-label="Previous photo" data-carousel-dir="-1">{_ICON_CHEVRON_LEFT}</button>
              </form>
              <form method="get" action="/">
                <input type="hidden" name="photo" value="{next_photo}" />
                {carousel_pin_url_html}
                {filter_hidden_inputs}
                <button class="carousel-btn carousel-btn-next" type="submit" aria-label="Next photo" data-carousel-dir="1">{_ICON_CHEVRON_RIGHT}</button>
              </form>
            </div>
            <div class="carousel-meta">{current_photo_index + 1} / {photo_count}</div>
        """
    photo_container_class = "card-photo has-carousel" if has_carousel else "card-photo"
    random_skip_url_html = (
        f'<input type="hidden" name="skip_url" value="{escape(raw_profile_url)}" />'
        if raw_profile_url
        else ""
    )

    info_msg = (
        f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    )
    ecosystem_html = _render_ecosystem_section(
        input_id="subscribe-email",
        current_photo_index=current_photo_index,
        filter_hidden_inputs=filter_hidden_inputs,
        provider_disclaimer=PROVIDER_DISCLAIMER,
    )
    page_html = f"""<!doctype html>
<html lang="en">
{_head_html("PupSwipe | PuppyPing")}
  <body class="swipe-page">
    {topbar_html}

    <div class="app">
      {info_msg}

      <main class="swipe-main">
        {filter_bar}
        <section class="stack">
          <article id="swipe-card" class="{card_classes}" data-swipe-threshold="110">
            <div class="{photo_container_class}"{photo_data_attrs}>
              {image_block}
              {carousel_controls}
              <div class="swipe-indicator like">Like</div>
              <div class="swipe-indicator nope">Pass</div>
            </div>
            <div class="card-body">
              <div class="card-eyebrow">
                <span class="live-dot" aria-hidden="true"></span>
                <span class="card-status">{status}</span>
                <span class="eyebrow-sep" aria-hidden="true">&middot;</span>
                <span class="card-provider">{provider_name}</span>
              </div>
              <div class="card-identity">
                <div class="card-title">
                  <h2>{name}</h2>
                  <span class="age-pill">{age_raw}</span>
                </div>
                <p class="card-facts-line">
                  <strong>{breed}</strong> &middot; {gender} &middot; {species_display} &middot; {location}
                </p>
              </div>
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
            <input type="hidden" name="species" value="{species}" />
            <input type="hidden" name="source" value="{escaped_swipe_source}" />
            {filter_hidden_inputs}
            <input type="hidden" name="swipe" value="left" />
            <button class="btn nope" type="submit"><span class="btn-icon" aria-hidden="true">{_ICON_PASS}</span>Pass</button>
          </form>
          <form id="swipe-random-form" method="get" action="/">
            <input type="hidden" name="random" value="1" />
            {random_skip_url_html}
            {filter_hidden_inputs}
            <button class="btn refresh" type="submit"><span class="btn-icon" aria-hidden="true">{_ICON_RANDOM}</span>Random</button>
          </form>
          <form id="swipe-like-form" method="post" action="/swipe">
            <input type="hidden" name="dog_id" value="{dog_id}" />
            <input type="hidden" name="species" value="{species}" />
            <input type="hidden" name="source" value="{escaped_swipe_source}" />
            {filter_hidden_inputs}
            <input type="hidden" name="swipe" value="right" />
            <button class="btn like" type="submit"><span class="btn-icon" aria-hidden="true">{_ICON_HEART}</span>Like</button>
          </form>
        </section>
        <p class="kbd-hints" aria-hidden="true">
          <kbd>&larr;</kbd> Pass <span>&middot;</span>
          <kbd>&rarr;</kbd> Like <span>&middot;</span>
          <kbd>R</kbd> Random <span>&middot;</span>
          <kbd>Space</kbd> Photo
        </p>
      </main>

      {ecosystem_html}
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _render_catalog_page(
    puppies: list[dict],
    total_available: int,
    message: str | None = None,
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    species_filter: str = "",
    max_age_months: float = 8.0,
    signed_in_email: str | None = None,
    *,
    deps: PageDeps,
) -> bytes:
    """Render a catalog view of currently available pets."""
    _normalize_breed_filter = deps.normalize_breed_filter
    _normalize_name_filter = deps.normalize_name_filter
    _normalize_provider_filter = deps.normalize_provider_filter
    _normalize_species_filter = deps.normalize_species_filter
    _normalize_max_age_filter = deps.normalize_max_age_filter
    _filter_hidden_inputs = deps.filter_hidden_inputs
    _provider_name = deps.provider_name
    _safe_int = deps.safe_int
    PUPSWIPE_SOURCES = deps.pupswipe_sources
    MAX_PUPPY_AGE_MONTHS = deps.max_puppy_age_months
    MAX_BREED_FILTER_LENGTH = deps.max_breed_filter_length
    MAX_NAME_FILTER_LENGTH = deps.max_name_filter_length

    normalized_breed = _normalize_breed_filter(breed_filter)
    normalized_name = _normalize_name_filter(name_filter)
    normalized_provider = _normalize_provider_filter(provider_filter)
    normalized_species = _normalize_species_filter(species_filter)
    normalized_max_age_months = _normalize_max_age_filter(max_age_months)
    escaped_breed = escape(normalized_breed)
    escaped_name = escape(normalized_name)
    escaped_max_age = escape(f"{normalized_max_age_months:g}")
    catalog_filter_hash_inputs_html = _filter_hidden_inputs(
        breed_filter=normalized_breed,
        name_filter=normalized_name,
        provider_filter=normalized_provider,
        species_filter=normalized_species,
        max_age_months=normalized_max_age_months,
    )
    catalog_filter_hidden_inputs: list[str] = []
    if normalized_name:
        catalog_filter_hidden_inputs.append(
            f'<input type="hidden" name="name" value="{escape(normalized_name)}" />'
        )
    if normalized_breed:
        catalog_filter_hidden_inputs.append(
            f'<input type="hidden" name="breed" value="{escape(normalized_breed)}" />'
        )
    if normalized_species:
        catalog_filter_hidden_inputs.append(
            f'<input type="hidden" name="species" value="{escape(normalized_species)}" />'
        )
    if normalized_provider:
        catalog_filter_hidden_inputs.append(
            f'<input type="hidden" name="provider" value="{escape(normalized_provider)}" />'
        )
    if normalized_max_age_months != MAX_PUPPY_AGE_MONTHS:
        catalog_filter_hidden_inputs.append(
            f'<input type="hidden" name="max_age" value="{escape(f"{normalized_max_age_months:g}")}" />'
        )
    catalog_filter_hidden_inputs_html = "\n                ".join(
        catalog_filter_hidden_inputs
    )

    topbar_html = _render_topbar(
        active_nav="catalog",
        title="Pet Catalog",
        subtitle="PupSwipe by PuppyPing",
        signed_in_email=signed_in_email,
        signin_next="/catalog",
        signout_next="/catalog",
    )

    active_filters: list[str] = []
    if normalized_breed:
        active_filters.append(f"Breed: {normalized_breed}")
    if normalized_name:
        active_filters.append(f"Name: {normalized_name}")
    if normalized_provider:
        active_filters.append(f"Provider: {_provider_name(normalized_provider, None)}")
    if normalized_species:
        active_filters.append(f"Species: {normalized_species.title()}")
    if normalized_max_age_months != MAX_PUPPY_AGE_MONTHS:
        active_filters.append(f"Max age: {normalized_max_age_months:g} mo")

    shown_count = len(puppies)
    stats = (
        f"{shown_count} shown of {total_available} available"
        if active_filters
        else f"{total_available} available"
    )

    clear_filter_html = ""
    if active_filters:
        clear_query = urlencode({"clear_filters": "1"})
        clear_filter_html = (
            f'<a class="clear-filter" href="/catalog?{clear_query}">Clear</a>'
        )

    provider_options_html = _provider_options_html(
        PUPSWIPE_SOURCES, normalized_provider, _provider_name
    )
    species_options_html = _species_options_html(normalized_species)

    filter_bar = _render_filter_bar(
        form_id="catalog-filter-form",
        id_prefix="catalog-",
        action="/catalog",
        aria_label="Catalog filters",
        stats_text=stats,
        active_filter_chips=active_filters,
        breed_value=escaped_breed,
        name_value=escaped_name,
        species_options_html=species_options_html,
        provider_options_html=provider_options_html,
        max_age_value=escaped_max_age,
        max_breed_len=MAX_BREED_FILTER_LENGTH,
        max_name_len=MAX_NAME_FILTER_LENGTH,
        clear_filter_html=clear_filter_html,
        open_by_default=True,
    )

    cards_html = ""
    for pup in puppies:
        pet_id = _safe_int(str(pup.get("pet_id") or pup.get("dog_id")), 0)
        raw_pet_name = str(pup.get("name") or "Unnamed pet")
        pet_name = escape(raw_pet_name)
        pet_species = (
            " ".join(str(pup.get("species") or "pet").split()).strip().lower() or "pet"
        )
        pet_breed = escape(str(pup.get("breed") or "Unknown breed"))
        pet_age = escape(str(pup.get("age_raw") or "Age unknown"))
        pet_location = escape(str(pup.get("location") or "Unknown location"))
        raw_profile_url = str(pup.get("url") or "").strip()
        profile_url = escape(raw_profile_url or "#")
        source_key = str(pup.get("source")) if pup.get("source") is not None else None
        provider_name = escape(_provider_name(source_key, raw_profile_url))
        swipe_source = " ".join((source_key or "").split()).strip()

        photo_url = _get_primary_image(pup)
        if photo_url:
            image_html = (
                f'<img src="{escape(photo_url)}" alt="{pet_name} photo" '
                'loading="lazy" referrerpolicy="no-referrer" />'
            )
        else:
            initials = _safe_initials(raw_pet_name, "PET")
            image_html = f'<div class="photo-fallback">{initials}</div>'

        if raw_profile_url:
            link_html = (
                f'<a class="profile-link" href="{profile_url}" target="_blank" rel="noopener">'
                f"Open adoption site{_ICON_EXTERNAL}</a>"
            )
        else:
            link_html = f'<span class="provider-missing">{provider_name}</span>'

        cards_html += f"""
          <article class="liked-card catalog-card">
            <div class="liked-photo">
              {image_html}
              <form class="inline-form catalog-like-form" method="post" action="/catalog/like">
                <input type="hidden" name="pet_id" value="{pet_id}" />
                <input type="hidden" name="pet_species" value="{escape(pet_species)}" />
                <input type="hidden" name="source" value="{escape(swipe_source)}" />
                {catalog_filter_hidden_inputs_html}
                {catalog_filter_hash_inputs_html}
                <button
                  class="catalog-heart-btn"
                  type="submit"
                  aria-label="Like {pet_name}"
                  title="Like {pet_name}"
                >{_ICON_HEART_OUTLINE}</button>
              </form>
            </div>
            <div class="liked-body">
              <div class="card-title-compact">
                <h3>{pet_name}</h3>
                <span class="age-pill">{pet_age}</span>
              </div>
              <p class="liked-meta">{pet_breed} &middot; {pet_location}</p>
              <div class="liked-actions">
                <span class="card-shelter">{provider_name}</span>
                {link_html}
              </div>
            </div>
          </article>
        """

    has_cards = bool(cards_html)
    if not cards_html:
        filtered_species_label = _filtered_species_label(normalized_species)
        empty_copy = message or (
            f"No {filtered_species_label} match those filters. Try different filters."
            if active_filters
            else "No pets available right now."
        )
        cards_html = f"""
          <div class="state state-empty">
            {escape(empty_copy)}
          </div>
        """

    info_msg = (
        f'<div class="flash" role="status">{escape(message)}</div>'
        if message and has_cards
        else ""
    )
    page_html = f"""<!doctype html>
<html lang="en">
{_head_html("Pet Catalog | PupSwipe")}
  <body class="catalog-page">
    {topbar_html}
    <div class="app">
      {info_msg}
      <main>
        {filter_bar}
        <section class="likes-shell catalog-shell">
          <div class="liked-grid catalog-grid">
            {cards_html}
          </div>
        </section>
      </main>
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _render_signin_page(
    message: str | None = None,
    next_path: str = "/likes",
    email_value: str = "",
    signed_in_email: str | None = None,
    *,
    deps: PageDeps,
) -> bytes:
    """Render email sign-in page."""
    _normalize_next_path = deps.normalize_next_path
    PASSWORD_MIN_LENGTH = deps.password_min_length

    safe_next = _normalize_next_path(next_path, "/likes")
    escaped_email = escape(email_value)
    info_msg = (
        f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    )
    topbar_html = _render_topbar(
        active_nav="signin",
        title="PupSwipe",
        subtitle="Sign in to save your likes",
        signed_in_email=signed_in_email,
        signout_next="/signin",
        show_signin_cta=False,
    )

    if signed_in_email:
        account_line = f"""
          <p class="auth-copy">
            You are currently signed in as <strong>{escape(signed_in_email)}</strong>.
            <a class="profile-link" href="/likes">View liked puppies</a>
          </p>
        """
    else:
        account_line = '<p class="auth-copy">Use email + password. First sign-in creates your account.</p>'

    page_html = f"""<!doctype html>
<html lang="en">
{_head_html("Sign In | PupSwipe")}
  <body class="signin-page">
    {topbar_html}
    <div class="app">
      {info_msg}
      <main>
        <section class="auth-shell">
          <article class="auth-card">
            <div class="auth-header">
              <div class="auth-badge" aria-hidden="true">{_ICON_PAW}</div>
              <div>
                <h2>Sign in</h2>
                {account_line}
              </div>
            </div>
            <form class="auth-form" method="post" action="/signin">
              <input type="hidden" name="next" value="{escape(safe_next)}" />
              <label for="signin-email">Email address</label>
              <input
                id="signin-email"
                name="email"
                type="email"
                inputmode="email"
                autocomplete="email"
                placeholder="you@example.com"
                value="{escaped_email}"
                required
              />
              <label for="signin-password">Password</label>
              <input
                id="signin-password"
                name="password"
                type="password"
                autocomplete="current-password"
                minlength="{PASSWORD_MIN_LENGTH}"
                required
              />
              <button class="btn like" type="submit">Continue</button>
            </form>
            <div class="auth-links">
              <a class="profile-link" href="/forgot-password">Forgot password?</a>
              <a class="profile-link" href="/">Back to PupSwipe</a>
            </div>
          </article>
        </section>
      </main>
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _render_forgot_password_page(
    message: str | None = None,
    email_value: str = "",
) -> bytes:
    """Render forgot-password request page."""
    info_msg = (
        f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    )
    escaped_email = escape(email_value)
    topbar_html = _render_topbar(
        active_nav="auth",
        title="PupSwipe",
        subtitle="Forgot password",
        show_signin_cta=False,
    )
    page_html = f"""<!doctype html>
<html lang="en">
{_head_html("Forgot Password | PupSwipe")}
  <body>
    {topbar_html}
    <div class="app">
      {info_msg}
      <main>
        <section class="auth-shell">
          <article class="auth-card">
            <div class="auth-header">
              <div class="auth-badge" aria-hidden="true">{_ICON_PAW}</div>
              <div>
                <h2>Reset via email</h2>
                <p class="auth-copy">Enter your account email and we will send a reset link.</p>
              </div>
            </div>
            <form class="auth-form" method="post" action="/forgot-password">
              <label for="forgot-email">Email address</label>
              <input
                id="forgot-email"
                name="email"
                type="email"
                inputmode="email"
                autocomplete="email"
                placeholder="you@example.com"
                value="{escaped_email}"
                required
              />
              <button class="btn like" type="submit">Send reset link</button>
            </form>
            <div class="auth-links">
              <a class="profile-link" href="/signin">Back to sign in</a>
              <a class="profile-link" href="/">Back to PupSwipe</a>
            </div>
          </article>
        </section>
      </main>
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _render_forgot_password_reset_page(
    token: str,
    message: str | None = None,
    *,
    deps: PageDeps,
) -> bytes:
    """Render reset-password-by-token page."""
    PASSWORD_MIN_LENGTH = deps.password_min_length

    info_msg = (
        f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    )
    topbar_html = _render_topbar(
        active_nav="auth",
        title="PupSwipe",
        subtitle="Set new password",
        show_signin_cta=False,
    )
    page_html = f"""<!doctype html>
<html lang="en">
{_head_html("Set New Password | PupSwipe")}
  <body>
    {topbar_html}
    <div class="app">
      {info_msg}
      <main>
        <section class="auth-shell">
          <article class="auth-card">
            <div class="auth-header">
              <div class="auth-badge" aria-hidden="true">{_ICON_PAW}</div>
              <div>
                <h2>Choose a new password</h2>
                <p class="auth-copy">Pick a fresh password for your PupSwipe profile.</p>
              </div>
            </div>
            <form class="auth-form" method="post" action="/forgot-password/reset">
              <input type="hidden" name="token" value="{escape(token)}" />
              <label for="new-password">New password</label>
              <input
                id="new-password"
                name="new_password"
                type="password"
                autocomplete="new-password"
                minlength="{PASSWORD_MIN_LENGTH}"
                required
              />
              <label for="confirm-password">Confirm new password</label>
              <input
                id="confirm-password"
                name="confirm_password"
                type="password"
                autocomplete="new-password"
                minlength="{PASSWORD_MIN_LENGTH}"
                required
              />
              <button class="btn like" type="submit">Set password</button>
            </form>
            <div class="auth-links">
              <a class="profile-link" href="/signin">Back to sign in</a>
              <a class="profile-link" href="/">Back to PupSwipe</a>
            </div>
          </article>
        </section>
      </main>
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _render_reset_password_page(
    signed_in_email: str,
    message: str | None = None,
    *,
    deps: PageDeps,
) -> bytes:
    """Render reset-password page for a signed-in user."""
    PASSWORD_MIN_LENGTH = deps.password_min_length

    info_msg = (
        f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    )
    topbar_html = _render_topbar(
        active_nav="auth",
        title="PupSwipe",
        subtitle="Reset your password",
        signed_in_email=signed_in_email,
        signout_next="/signin",
    )
    page_html = f"""<!doctype html>
<html lang="en">
{_head_html("Reset Password | PupSwipe")}
  <body>
    {topbar_html}
    <div class="app">
      {info_msg}
      <main>
        <section class="auth-shell">
          <article class="auth-card">
            <div class="auth-header">
              <div class="auth-badge" aria-hidden="true">{_ICON_PAW}</div>
              <div>
                <h2>Reset password</h2>
                <p class="auth-copy">Signed in as <strong>{escape(signed_in_email)}</strong></p>
              </div>
            </div>
            <form class="auth-form" method="post" action="/reset-password">
              <label for="current-password">Current password</label>
              <input
                id="current-password"
                name="current_password"
                type="password"
                autocomplete="current-password"
                required
              />
              <label for="new-password">New password</label>
              <input
                id="new-password"
                name="new_password"
                type="password"
                autocomplete="new-password"
                minlength="{PASSWORD_MIN_LENGTH}"
                required
              />
              <label for="confirm-password">Confirm new password</label>
              <input
                id="confirm-password"
                name="confirm_password"
                type="password"
                autocomplete="new-password"
                minlength="{PASSWORD_MIN_LENGTH}"
                required
              />
              <button class="btn like" type="submit">Update password</button>
            </form>
            <div class="auth-links">
              <a class="profile-link" href="/likes">Back to liked puppies</a>
            </div>
          </article>
        </section>
      </main>
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _format_liked_time(value) -> str:
    """Format liked timestamp for simple display."""
    text = str(value or "").strip()
    if not text:
        return "Unknown time"
    return text.replace("T", " ").replace("+00:00", " UTC")


def _is_liked_pet_available(pup: dict) -> bool:
    """Return whether a liked pet is currently available."""
    status_text = " ".join(str(pup.get("status") or "").split()).strip().lower()
    status_available = status_text.startswith("available")
    is_active_value = pup.get("is_active")
    if isinstance(is_active_value, bool):
        return status_available and is_active_value
    return status_available


def _render_likes_page(
    email: str,
    puppies: list[dict],
    total_likes: int,
    filtered_likes: int | None = None,
    name_filter: str = "",
    breed_filter: str = "",
    species_filter: str = "",
    provider_filter: str = "",
    message: str | None = None,
    *,
    deps: PageDeps,
) -> bytes:
    """Render page showing the signed-in user's liked puppies."""
    _normalize_breed_filter = deps.normalize_breed_filter
    _normalize_name_filter = deps.normalize_name_filter
    _normalize_provider_filter = deps.normalize_provider_filter
    _normalize_species_filter = deps.normalize_species_filter
    _provider_name = deps.provider_name
    _safe_int = deps.safe_int
    PUPSWIPE_SOURCES = deps.pupswipe_sources
    MAX_BREED_FILTER_LENGTH = deps.max_breed_filter_length
    MAX_NAME_FILTER_LENGTH = deps.max_name_filter_length

    normalized_name = _normalize_name_filter(name_filter)
    normalized_breed = _normalize_breed_filter(breed_filter)
    normalized_species = _normalize_species_filter(species_filter)
    normalized_provider = _normalize_provider_filter(provider_filter)
    escaped_name_filter = escape(normalized_name)
    escaped_breed_filter = escape(normalized_breed)

    active_filters: list[str] = []
    if normalized_name:
        active_filters.append(f"Name: {normalized_name}")
    if normalized_breed:
        active_filters.append(f"Breed: {normalized_breed}")
    if normalized_species:
        active_filters.append(f"Species: {normalized_species.title()}")
    if normalized_provider:
        active_filters.append(f"Provider: {_provider_name(normalized_provider, None)}")

    shown_count = filtered_likes if filtered_likes is not None else len(puppies)
    stats_copy = (
        f"{shown_count} shown of {total_likes} liked"
        if active_filters
        else f"{total_likes} liked"
    )

    provider_options_html = _provider_options_html(
        PUPSWIPE_SOURCES, normalized_provider, _provider_name
    )
    species_options_html = _species_options_html(normalized_species)

    clear_link_html = (
        '<a class="clear-filter" href="/likes">Clear</a>' if active_filters else ""
    )
    likes_filter_hidden_inputs: list[str] = []
    if normalized_name:
        likes_filter_hidden_inputs.append(
            f'<input type="hidden" name="name" value="{escape(normalized_name)}" />'
        )
    if normalized_breed:
        likes_filter_hidden_inputs.append(
            f'<input type="hidden" name="breed" value="{escape(normalized_breed)}" />'
        )
    if normalized_species:
        likes_filter_hidden_inputs.append(
            f'<input type="hidden" name="species" value="{escape(normalized_species)}" />'
        )
    if normalized_provider:
        likes_filter_hidden_inputs.append(
            f'<input type="hidden" name="provider" value="{escape(normalized_provider)}" />'
        )
    likes_filter_hidden_inputs_html = "\n              ".join(
        likes_filter_hidden_inputs
    )
    likes_chips_html = ""
    if active_filters:
        likes_chips_items = "".join(
            f'<span class="filter-chip">{escape(chip)}</span>'
            for chip in active_filters
        )
        likes_chips_html = (
            f'<span class="active-filter-chips">{likes_chips_items}</span>'
        )
    likes_count_badge = (
        f'<span class="filter-count">{len(active_filters)}</span>'
        if active_filters
        else ""
    )

    likes_filter_bar = f"""
      <section class="likes-filter-strip" aria-label="Liked pet filters">
        <details class="filter-drawer" open>
          <summary class="filter-drawer-summary">
            <span class="filter-summary-left">
              <span class="stats">{escape(stats_copy)}</span>
              {likes_chips_html}
            </span>
            <span class="filter-toggle-pill">
              {_ICON_FILTER}
              <span>Filters</span>
              {likes_count_badge}
              {_ICON_CHEVRON_DOWN}
            </span>
          </summary>
          <form class="likes-filter-form" method="get" action="/likes">
            <div class="likes-filter-field">
              <label for="likes-name-filter">Name</label>
              <input
                id="likes-name-filter"
                name="name"
                type="text"
                value="{escaped_name_filter}"
                placeholder="e.g. Nova"
                maxlength="{MAX_NAME_FILTER_LENGTH}"
              />
            </div>
            <div class="likes-filter-field">
              <label for="likes-breed-filter">Breed</label>
              <input
                id="likes-breed-filter"
                name="breed"
                type="text"
                value="{escaped_breed_filter}"
                placeholder="e.g. Labrador"
                maxlength="{MAX_BREED_FILTER_LENGTH}"
              />
            </div>
            <div class="likes-filter-field">
              <label for="likes-species-filter">Species</label>
              <select id="likes-species-filter" name="species">
                {species_options_html}
              </select>
            </div>
            <div class="likes-filter-field">
              <label for="likes-provider-filter">Provider</label>
              <select id="likes-provider-filter" name="provider">
                {provider_options_html}
              </select>
            </div>
            <button class="btn filter" type="submit">Filter</button>
            {clear_link_html}
          </form>
        </details>
      </section>
    """
    bulk_actions_html = f"""
      <section class="likes-bulk-actions" aria-label="Liked pet actions">
        <form method="post" action="/likes/remove-all">
          <input type="hidden" name="mode" value="unavailable" />
          {likes_filter_hidden_inputs_html}
          <button
            class="btn subtle"
            type="submit"
            onclick="return confirm('Remove all unavailable pets from your liked list?');"
          >
            Remove unavailable
          </button>
        </form>
        <form method="post" action="/likes/remove-all">
          <input type="hidden" name="mode" value="all" />
          {likes_filter_hidden_inputs_html}
          <button
            class="btn subtle danger"
            type="submit"
            onclick="return confirm('Remove all pets in this liked view?');"
          >
            Remove all shown
          </button>
        </form>
      </section>
    """

    info_msg = (
        f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    )
    cards_html = ""
    for pup in puppies:
        dog_id = _safe_int(str(pup.get("pet_id") or pup.get("dog_id")), 0)
        raw_name = str(pup.get("name") or "Unnamed pup")
        name = escape(raw_name)
        breed = escape(str(pup.get("breed") or "Unknown breed"))
        age_raw = escape(str(pup.get("age_raw") or "Age unknown"))
        location = escape(str(pup.get("location") or "Unknown location"))
        status = escape(str(pup.get("status") or "Status unknown"))
        is_available_now = _is_liked_pet_available(pup)
        card_class = "liked-card" if is_available_now else "liked-card is-unavailable"
        raw_profile_url = str(pup.get("url") or "").strip()
        profile_url = escape(raw_profile_url or "#")
        source_key = str(pup.get("source")) if pup.get("source") is not None else None
        provider_name = escape(_provider_name(source_key, raw_profile_url))
        pet_species = (
            " ".join(str(pup.get("species") or "dog").split()).strip().lower() or "dog"
        )
        photo_url = _get_primary_image(pup)
        if photo_url:
            image_html = (
                f'<img src="{escape(photo_url)}" alt="{name} photo" '
                'loading="lazy" referrerpolicy="no-referrer" />'
            )
        else:
            initials = _safe_initials(raw_name, "PUP")
            image_html = f'<div class="photo-fallback">{initials}</div>'

        if is_available_now:
            eyebrow_html = (
                f'<div class="card-eyebrow">'
                f'<span class="live-dot" aria-hidden="true"></span>'
                f"<span>{status}</span>"
                f'<span class="eyebrow-sep" aria-hidden="true">&middot;</span>'
                f"<span>{provider_name}</span>"
                f"</div>"
            )
        else:
            eyebrow_html = (
                f'<div class="card-eyebrow">'
                f'<span class="badge badge-unavailable">No longer available</span>'
                f'<span class="eyebrow-sep" aria-hidden="true">&middot;</span>'
                f"<span>{provider_name}</span>"
                f"</div>"
            )

        remove_form_html = f"""
                <form class="inline-form" method="post" action="/likes/remove">
                  <input type="hidden" name="pet_id" value="{dog_id}" />
                  <input type="hidden" name="pet_species" value="{escape(pet_species)}" />
                  {likes_filter_hidden_inputs_html}
                  <button class="btn subtle danger" type="submit"><span class="btn-icon" aria-hidden="true">{_ICON_TRASH}</span>Remove</button>
                </form>"""

        if raw_profile_url:
            link_html = (
                f'<a class="profile-link" href="{profile_url}" target="_blank" rel="noopener">'
                f"Open on {provider_name}{_ICON_EXTERNAL}</a>"
            )
            share_title_raw = str(pup.get("name") or "this pet").strip() or "this pet"
            share_animal_raw = (
                " ".join(str(pup.get("species") or "pet").split()).strip().lower()
                or "pet"
            )
            share_body = (
                f"I found a cute {share_animal_raw} on PupSwipe. "
                f"Adoption site: {raw_profile_url}"
            )
            mailto_query = urlencode(
                {
                    "subject": f"Check out {share_title_raw} on PupSwipe",
                    "body": share_body,
                }
            )
            share_actions_html = f"""
              <div class="liked-actions">
                {link_html}
                <button
                  class="btn subtle share-btn"
                  type="button"
                  data-share-url="{escape(raw_profile_url)}"
                  data-share-title="{escape(share_title_raw)}"
                  data-share-text="{escape(share_body)}"
                ><span class="btn-icon" aria-hidden="true">{_ICON_SHARE}</span><span class="share-label">Copy Share</span></button>
                <a class="profile-link" href="mailto:?{mailto_query}">Email</a>
                {remove_form_html}
              </div>
            """
        else:
            link_html = f'<span class="provider-missing">{provider_name}</span>'
            share_actions_html = f"""
              <div class="liked-actions">
                {link_html}
                {remove_form_html}
              </div>
            """

        cards_html += f"""
          <article class="{card_class}">
            <div class="liked-photo">{image_html}</div>
            <div class="liked-body">
              {eyebrow_html}
              <div class="card-title-compact">
                <h3>{name}</h3>
                <span class="age-pill">{age_raw}</span>
              </div>
              <p class="liked-meta">{breed} &middot; {location}</p>
              {share_actions_html}
            </div>
          </article>
        """

    if not cards_html:
        empty_copy = (
            "No liked pets match those filters."
            if active_filters
            else "No liked puppies yet. Swipe right on PupSwipe while signed in."
        )
        cards_html = f"""
          <div class="state state-empty">
            {escape(empty_copy)}
          </div>
        """

    topbar_html = _render_topbar(
        active_nav="likes",
        title="Liked Puppies",
        subtitle="PupSwipe by PuppyPing",
        signed_in_email=email,
        signout_next="/signin",
    )

    page_html = f"""<!doctype html>
<html lang="en">
{_head_html("Liked Puppies | PupSwipe")}
  <body class="likes-page">
    {topbar_html}
    <div class="app">
      {info_msg}
      <main>
        {likes_filter_bar}
        {bulk_actions_html}
        <section class="likes-shell">
          <div class="liked-grid">
            {cards_html}
          </div>
        </section>
      </main>
    </div>
    <script src="/swipe.js"></script>
  </body>
</html>"""
    return page_html.encode("utf-8")
