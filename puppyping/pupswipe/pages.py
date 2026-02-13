"""HTML rendering helpers for PupSwipe."""

from __future__ import annotations

import random
from html import escape
from urllib.parse import urlencode


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
    breed_filter: str = "",
    name_filter: str = "",
    provider_filter: str = "",
    signed_in_email: str | None = None,
) -> bytes:
    """Render the main HTML page.

    Args:
        offset: Current dog index offset.
        message: Optional info/error message to display.
        photo_index: Selected image index within the current dog carousel.
        randomize: Whether to pick a random dog from the current result set.
        breed_filter: Optional breed filter text.
        name_filter: Optional name filter text.
        provider_filter: Optional provider source filter text.
        signed_in_email: Optional signed-in email for account actions.

    Returns:
        UTF-8 encoded HTML document bytes.
    """
    normalized_breed = _normalize_breed_filter(breed_filter)
    normalized_name = _normalize_name_filter(name_filter)
    normalized_provider = _normalize_provider_filter(provider_filter)
    escaped_breed = escape(normalized_breed)
    escaped_name = escape(normalized_name)
    filter_hidden_inputs = _filter_hidden_inputs(
        breed_filter=normalized_breed,
        name_filter=normalized_name,
        provider_filter=normalized_provider,
    )
    escaped_signed_in_email = escape(signed_in_email) if signed_in_email else ""
    if signed_in_email:
        account_actions_html = f"""
          <div class="account-actions">
            <span class="account-email">{escaped_signed_in_email}</span>
            <a class="profile-link" href="/likes">Liked pups</a>
            <a class="profile-link" href="/reset-password">Reset password</a>
            <form class="inline-form" method="post" action="/signout">
              <input type="hidden" name="next" value="/" />
              <button class="btn subtle" type="submit">Sign out</button>
            </form>
          </div>
        """
    else:
        signin_query = urlencode({"next": "/"})
        account_actions_html = (
            f'<a class="profile-link account-link" href="/signin?{signin_query}">'
            "Sign in to save likes"
            "</a>"
        )

    try:
        total = _count_puppies(
            breed_filter=normalized_breed,
            name_filter=normalized_name,
            provider_filter=normalized_provider,
        )
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
        puppies = _fetch_puppies(
            PAGE_SIZE,
            offset=offset,
            breed_filter=normalized_breed,
            name_filter=normalized_name,
            provider_filter=normalized_provider,
        )
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
        {account_actions_html}
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
    active_filters: list[str] = []
    if normalized_breed:
        active_filters.append(f"Breed: {normalized_breed}")
    if normalized_name:
        active_filters.append(f"Name: {normalized_name}")
    if normalized_provider:
        active_filters.append(f"Provider: {_provider_name(normalized_provider)}")
    if active_filters:
        stats = f"{stats} | Filters: {', '.join(active_filters)}"

    clear_filter_html = ""
    if active_filters:
        clear_query = urlencode({"offset": "0"})
        clear_filter_html = f'<a class="clear-filter" href="/?{clear_query}">Clear</a>'

    provider_options = ['<option value="">All providers</option>']
    for source in PUPSWIPE_SOURCES:
        selected_attr = " selected" if source == normalized_provider else ""
        provider_options.append(
            f'<option value="{escape(source)}"{selected_attr}>{escape(_provider_name(source))}</option>'
        )
    provider_options_html = "".join(provider_options)

    filter_bar = f"""
      <section class="filter-strip" aria-label="Pup filters">
        <form class="breed-filter-form" method="get" action="/">
          <input type="hidden" name="offset" value="0" />
          <div class="filter-field">
            <label for="breed-filter">Breed</label>
            <input
              id="breed-filter"
              name="breed"
              type="text"
              value="{escaped_breed}"
              placeholder="e.g. Labrador"
              maxlength="{MAX_BREED_FILTER_LENGTH}"
            />
          </div>
          <div class="filter-field">
            <label for="name-filter">Name</label>
            <input
              id="name-filter"
              name="name"
              type="text"
              value="{escaped_name}"
              placeholder="e.g. Nova"
              maxlength="{MAX_NAME_FILTER_LENGTH}"
            />
          </div>
          <div class="filter-field">
            <label for="provider-filter">Provider</label>
            <select id="provider-filter" name="provider">
              {provider_options_html}
            </select>
          </div>
          <button class="btn filter" type="submit">Filter</button>
          {clear_filter_html}
        </form>
      </section>
    """

    if not puppies:
        empty_msg = (
            message
            or (
                "No puppies match those filters. Try different filters."
                if active_filters
                else "No puppies to show yet. Run scraper and refresh."
            )
        )
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
        {account_actions_html}
      </header>
      <main>
        <section class="stack">
          <div class="state state-empty">{escape(empty_msg)}</div>
        </section>
        <section class="controls">
          <form method="get" action="/">
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="random" value="1" />
            {filter_hidden_inputs}
            <button class="btn refresh" type="submit">Random</button>
          </form>
        </section>
        {filter_bar}
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
            {filter_hidden_inputs}
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
                {filter_hidden_inputs}
                <button class="carousel-btn" type="submit" aria-label="Previous photo">Prev</button>
              </form>
              <div class="carousel-middle">
                <div class="carousel-meta">{current_index + 1} / {photo_count}</div>
                <div class="carousel-dots" aria-hidden="true">{dots}</div>
              </div>
              <form method="get" action="/">
                <input type="hidden" name="offset" value="{offset}" />
                <input type="hidden" name="photo" value="{next_photo}" />
                {filter_hidden_inputs}
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
        {account_actions_html}
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
            {filter_hidden_inputs}
            <input type="hidden" name="swipe" value="left" />
            <button class="btn nope" type="submit">Nope</button>
          </form>
          <form method="get" action="/">
            <input type="hidden" name="offset" value="{offset}" />
            <input type="hidden" name="random" value="1" />
            {filter_hidden_inputs}
            <button class="btn refresh" type="submit">Random</button>
          </form>
          <form id="swipe-like-form" method="post" action="/swipe">
            <input type="hidden" name="dog_id" value="{dog_id}" />
            <input type="hidden" name="offset" value="{offset}" />
            {filter_hidden_inputs}
            <input type="hidden" name="swipe" value="right" />
            <button class="btn like" type="submit">Like</button>
          </form>
        </section>
      </main>

      {filter_bar}

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
          {filter_hidden_inputs}
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


def _render_signin_page(
    message: str | None = None,
    next_path: str = "/likes",
    email_value: str = "",
    signed_in_email: str | None = None,
) -> bytes:
    """Render email sign-in page."""
    safe_next = _normalize_next_path(next_path, "/likes")
    escaped_email = escape(email_value)
    info_msg = f'<div class="flash" role="status">{escape(message)}</div>' if message else ""

    if signed_in_email:
        account_line = f"""
          <p class="auth-copy">
            You are currently signed in as <strong>{escape(signed_in_email)}</strong>.
            <a class="profile-link" href="/likes">View liked puppies</a>
          </p>
        """
    else:
        account_line = (
            '<p class="auth-copy">Use email + password. First sign-in creates your account.</p>'
        )

    page_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Sign In | PupSwipe</title>
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body class="signin-page">
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
            <p>Sign in to save your likes</p>
          </div>
        </div>
      </header>
      {info_msg}
      <main>
        <section class="auth-shell">
          <article class="auth-card">
            <h2>Sign in</h2>
            {account_line}
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
  </body>
</html>"""
    return page_html.encode("utf-8")


def _render_forgot_password_page(
    message: str | None = None,
    email_value: str = "",
) -> bytes:
    """Render forgot-password request page."""
    info_msg = f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    escaped_email = escape(email_value)
    page_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Forgot Password | PupSwipe</title>
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
            <p>Forgot password</p>
          </div>
        </div>
      </header>
      {info_msg}
      <main>
        <section class="auth-shell">
          <article class="auth-card">
            <h2>Reset via email</h2>
            <p class="auth-copy">Enter your account email and we will send a reset link.</p>
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
            <a class="profile-link" href="/signin">Back to sign in</a>
          </article>
        </section>
      </main>
    </div>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _render_forgot_password_reset_page(
    token: str,
    message: str | None = None,
) -> bytes:
    """Render reset-password-by-token page."""
    info_msg = f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    page_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Set New Password | PupSwipe</title>
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
            <p>Set new password</p>
          </div>
        </div>
      </header>
      {info_msg}
      <main>
        <section class="auth-shell">
          <article class="auth-card">
            <h2>Choose a new password</h2>
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
            <a class="profile-link" href="/signin">Back to sign in</a>
          </article>
        </section>
      </main>
    </div>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _render_reset_password_page(
    signed_in_email: str,
    message: str | None = None,
) -> bytes:
    """Render reset-password page for a signed-in user."""
    info_msg = f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    page_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Reset Password | PupSwipe</title>
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
            <p>Reset your password</p>
          </div>
        </div>
      </header>
      {info_msg}
      <main>
        <section class="auth-shell">
          <article class="auth-card">
            <h2>Reset password</h2>
            <p class="auth-copy">Signed in as <strong>{escape(signed_in_email)}</strong></p>
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
            <a class="profile-link" href="/likes">Back to liked puppies</a>
          </article>
        </section>
      </main>
    </div>
  </body>
</html>"""
    return page_html.encode("utf-8")


def _format_liked_time(value) -> str:
    """Format liked timestamp for simple display."""
    text = str(value or "").strip()
    if not text:
        return "Unknown time"
    return text.replace("T", " ").replace("+00:00", " UTC")


def _render_likes_page(
    email: str,
    puppies: list[dict],
    total_likes: int,
    message: str | None = None,
) -> bytes:
    """Render page showing the signed-in user's liked puppies."""
    info_msg = f'<div class="flash" role="status">{escape(message)}</div>' if message else ""
    cards_html = ""
    for pup in puppies:
        dog_id = _safe_int(str(pup.get("dog_id")), 0)
        name = escape(str(pup.get("name") or "Unnamed pup"))
        breed = escape(str(pup.get("breed") or "Unknown breed"))
        age_raw = escape(str(pup.get("age_raw") or "Age unknown"))
        location = escape(str(pup.get("location") or "Unknown location"))
        status = escape(str(pup.get("status") or "Status unknown"))
        liked_at = escape(_format_liked_time(pup.get("liked_at_utc")))
        raw_profile_url = str(pup.get("url") or "").strip()
        profile_url = escape(raw_profile_url or "#")
        source_key = str(pup.get("source")) if pup.get("source") is not None else None
        provider_name = escape(_provider_name(source_key, raw_profile_url))
        photo_url = _get_primary_image(pup)
        if photo_url:
            image_html = (
                f'<img src="{escape(photo_url)}" alt="{name} photo" referrerpolicy="no-referrer" />'
            )
        else:
            initials = "".join(part[0] for part in str(name).split()[:2]).upper() or "PUP"
            image_html = f'<div class="photo-fallback">{escape(initials)}</div>'

        if raw_profile_url:
            link_html = (
                f'<a class="profile-link" href="{profile_url}" target="_blank" rel="noopener">'
                f"Open on {provider_name}</a>"
            )
        else:
            link_html = f'<span class="provider-missing">{provider_name}</span>'

        cards_html += f"""
          <article class="liked-card">
            <div class="liked-photo">{image_html}</div>
            <div class="liked-body">
              <h3>{name}</h3>
              <p class="liked-meta">{breed} &middot; {age_raw} &middot; {location}</p>
              <div class="badges">
                <span class="badge">{status}</span>
                <span class="badge badge-provider">{provider_name}</span>
              </div>
              <p class="liked-time">Liked at {liked_at}</p>
              <p class="liked-id">Dog ID: {dog_id}</p>
              {link_html}
            </div>
          </article>
        """

    if not cards_html:
        cards_html = """
          <div class="state state-empty">
            No liked puppies yet. Swipe right on PupSwipe while signed in.
          </div>
        """

    page_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Liked Puppies | PupSwipe</title>
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
            <h1>Liked Puppies</h1>
            <p>{escape(email)}</p>
          </div>
        </div>
        <div class="topbar-meta">
          <div class="stats">{total_likes} liked</div>
          <a class="profile-link top-profile-link" href="/">Back to PupSwipe</a>
        </div>
        <div class="account-actions">
          <span class="account-email">{escape(email)}</span>
          <a class="profile-link" href="/reset-password">Reset password</a>
          <form class="inline-form" method="post" action="/signout">
            <input type="hidden" name="next" value="/signin" />
            <button class="btn subtle" type="submit">Sign out</button>
          </form>
        </div>
      </header>
      {info_msg}
      <main>
        <section class="likes-shell">
          <div class="liked-grid">
            {cards_html}
          </div>
        </section>
      </main>
    </div>
  </body>
</html>"""
    return page_html.encode("utf-8")


