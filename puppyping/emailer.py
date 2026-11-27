from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape
from typing import TYPE_CHECKING

from .db import get_sent_pet_keys, mark_pet_profiles_emailed
from .email_utils import sanitize_email
from .pupswipe.config import provider_name

if TYPE_CHECKING:
    from .models import PetProfile

_DEFAULT_PUPSWIPE_URL = "https://puppyping.com"
_RATING_ORDER = (
    "children",
    "dogs",
    "cats",
    "home_alone",
    "activity",
    "environment",
    "human_sociability",
    "enrichment",
)


def _profile_key(profile: "PetProfile") -> tuple[int, str]:
    return (int(profile.pet_id), str(profile.species or "dog").strip().lower() or "dog")


def _display_species(species: str | None) -> str:
    """Return species text for user-facing email content."""
    normalized = str(species or "").strip().lower() or "dog"
    return normalized.title()


def _safe_http_url(url: object) -> str | None:
    """Return a clean http(s) URL safe for email href/src attributes."""
    if not isinstance(url, str):
        return None
    candidate = url.strip()
    if not candidate or any(ch.isspace() for ch in candidate):
        return None
    lower = candidate.lower()
    if lower.startswith("https://") or lower.startswith("http://"):
        return candidate
    return None


def _pupswipe_url() -> str:
    """Return the configured public PupSwipe URL with a safe production default."""
    configured = _safe_http_url(os.environ.get("PUPSWIPE_PUBLIC_URL", ""))
    return configured.rstrip("/") if configured else _DEFAULT_PUPSWIPE_URL


def _valid_images(profile: "PetProfile") -> list[str]:
    """Collect unique safe image URLs from a pet profile."""
    if not profile.media or not profile.media.images:
        return []
    urls: list[str] = []
    for raw_url in profile.media.images:
        safe = _safe_http_url(raw_url)
        if safe and safe not in urls:
            urls.append(safe)
    return urls


def _format_age(profile: "PetProfile") -> str | None:
    """Return human-friendly pet age if available."""
    raw = " ".join(str(profile.age_raw or "").split()).strip()
    if raw:
        return raw
    if profile.age_months is None:
        return None
    val = float(profile.age_months)
    formatted = f"{val:.1f}".rstrip("0").rstrip(".")
    return f"{formatted} mo"


def _format_weight(weight_lbs: float | None) -> str | None:
    """Return human-friendly pet weight if available."""
    if weight_lbs is None:
        return None
    val = float(weight_lbs)
    formatted = f"{val:.1f}".rstrip("0").rstrip(".")
    return f"{formatted} lbs"


def _format_rating_value(value: object) -> str:
    """Format compatibility score for badge pills."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        num = float(value)
        num_str = str(int(num)) if num.is_integer() else f"{num:g}"
        if 0 <= num <= 5:
            return f"{num_str}/5"
        return num_str
    return str(value)


def _pet_initials(name: object) -> str:
    """Build two-character uppercase initials for pets without photos."""
    text = str(name or "").strip()
    parts = [part for part in text.split() if part]
    letters: list[str] = []
    for part in parts[:2]:
        for ch in part:
            if ch.isalnum():
                letters.append(ch.upper())
                break
    return "".join(letters)[:2] or "PP"


def _render_full_profile_text(profile: "PetProfile") -> str:
    """Render full profile text with display-friendly species casing."""
    raw_species = str(profile.species or "").strip().lower() or "dog"
    display_species = _display_species(profile.species)
    rendered = str(profile)
    rendered = rendered.replace(f"({raw_species})", f"({display_species})", 1)
    rendered = rendered.replace(
        f"Species    : {raw_species}",
        f"Species    : {display_species}",
        1,
    )
    return rendered


def _partition_profiles_for_recipient(
    profiles: list["PetProfile"],
    recipient: str,
) -> tuple[list["PetProfile"], list["PetProfile"]]:
    """Split profiles into new vs previously emailed for one recipient."""
    try:
        sent_keys = get_sent_pet_keys(recipient)
    except Exception:
        # Fail open: still send full details when DB/history is unavailable.
        return profiles, []

    if not sent_keys:
        return profiles, []

    new_profiles: list["PetProfile"] = []
    seen_profiles: list["PetProfile"] = []
    for profile in profiles:
        if _profile_key(profile) in sent_keys:
            seen_profiles.append(profile)
        else:
            new_profiles.append(profile)
    return new_profiles, seen_profiles


def _render_new_pet_card_html(profile: "PetProfile") -> str:
    """Render a magazine-style card for one newly discovered pet."""
    name_raw = str(profile.name or "Unnamed pet").strip() or "Unnamed pet"
    pet_name = escape(name_raw)
    provider = provider_name(getattr(profile, "source", None), profile.url)
    status_text = " ".join(str(profile.status or "").split()).strip()
    safe_url = _safe_http_url(profile.url)
    images = _valid_images(profile)

    hero_html = ""
    if images:
        hero_src = escape(images[0])
        hero_html = (
            '<tr><td style="padding:0;background-color:#ECE7DF;">'
            f'<img src="{hero_src}" alt="{pet_name}" '
            'style="display:block;width:100%;max-height:320px;'
            'object-fit:cover;object-position:center 22%;border:0;" />'
            "</td></tr>"
        )

    thumbs_html = ""
    extra_images = images[1:3]
    if extra_images:
        thumb_tags = "".join(
            f'<img src="{escape(url)}" alt="{pet_name} extra photo" '
            'width="92" height="68" '
            'style="display:inline-block;width:92px;height:68px;object-fit:cover;'
            'border-radius:8px;margin-right:8px;background-color:#ECE7DF;border:0;" />'
            for url in extra_images
        )
        thumbs_html = (
            f'<tr><td style="padding:12px 22px 0 22px;">{thumb_tags}</td></tr>'
        )

    eyebrow_parts: list[str] = []
    if status_text:
        eyebrow_parts.append(
            '<span style="display:inline-block;width:7px;height:7px;'
            "border-radius:50%;background-color:#2F7A57;"
            'margin-right:6px;vertical-align:middle;"></span>'
            f'<span style="vertical-align:middle;">{escape(status_text)}</span>'
        )
    if provider:
        eyebrow_parts.append(
            f'<span style="vertical-align:middle;">{escape(provider)}</span>'
        )
    eyebrow_html = ""
    if eyebrow_parts:
        joined_eyebrow = ' <span style="color:#C4BBB0;">&middot;</span> '.join(
            eyebrow_parts
        )
        eyebrow_html = (
            '<div style="font-size:12px;font-weight:600;color:#5C544D;'
            f'margin-bottom:4px;">{joined_eyebrow}</div>'
        )

    facts = [
        _display_species(profile.species),
        " ".join(str(profile.breed or "").split()).strip() or None,
        " ".join(str(profile.gender or "").split()).strip() or None,
        _format_age(profile),
        _format_weight(profile.weight_lbs),
        " ".join(str(profile.location or "").split()).strip() or None,
    ]
    fact_line = " &middot; ".join(escape(part) for part in facts if part)

    rating_pills: list[str] = []
    for key in _RATING_ORDER:
        val = profile.ratings.get(key)
        if val is None or str(val).strip() == "":
            continue
        label = escape(key.replace("_", " ").title())
        val_display = escape(_format_rating_value(val))
        rating_pills.append(
            '<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 9px;'
            "border-radius:6px;background-color:#F6F2EC;color:#463F39;"
            'font-size:12px;font-weight:600;">'
            f'<span style="color:#8A8178;font-weight:500;">{label}</span> '
            f"{val_display}</span>"
        )
    ratings_html = (
        f'<div style="margin:0 0 10px 0;">{"".join(rating_pills)}</div>'
        if rating_pills
        else ""
    )

    desc = " ".join(str(profile.description or "").split()).strip()
    if len(desc) > 420:
        desc = desc[:417].rstrip() + "..."
    bio_html = (
        '<p style="margin:0 0 16px 0;font-size:14px;line-height:1.55;'
        f'color:#463F39;">{escape(desc)}</p>'
        if desc
        else ""
    )

    cta_html = ""
    if safe_url:
        cta_label = (
            f"View on {provider}"
            if provider and provider != "Adoption Provider"
            else "View profile"
        )
        cta_html = (
            '<div><a href="' + escape(safe_url) + '" '
            'style="display:inline-block;padding:11px 20px;border-radius:999px;'
            "background-color:#D85A3F;color:#FFFFFF;font-size:13px;"
            'font-weight:600;text-decoration:none;">'
            f"{escape(cta_label)} &rarr;</a></div>"
        )

    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background-color:#FFFFFF;border:1px solid #E8E2D9;border-radius:16px;'
        'overflow:hidden;margin-bottom:18px;border-collapse:separate;">'
        f"{hero_html}"
        f"{thumbs_html}"
        '<tr><td style="padding:18px 22px 22px 22px;">'
        f"{eyebrow_html}"
        "<h3 style=\"margin:0 0 6px 0;font-family:Georgia,'Times New Roman',serif;"
        f'font-size:24px;line-height:1.15;font-weight:700;color:#1F1B18;">{pet_name}</h3>'
        '<div style="font-size:13px;line-height:1.45;color:#5C544D;'
        f'margin-bottom:12px;">{fact_line}</div>'
        f"{ratings_html}"
        f"{bio_html}"
        f"{cta_html}"
        "</td></tr></table>"
    )


def _render_seen_pet_row_html(profile: "PetProfile", *, is_last: bool) -> str:
    """Render one compact list row for a previously sent pet."""
    name_raw = str(profile.name or "Unnamed pet").strip() or "Unnamed pet"
    pet_name = escape(name_raw)
    images = _valid_images(profile)
    safe_url = _safe_http_url(profile.url)

    if images:
        thumb_html = (
            f'<img src="{escape(images[0])}" alt="{pet_name}" '
            'width="44" height="44" '
            'style="display:block;width:44px;height:44px;object-fit:cover;'
            'border-radius:10px;background-color:#ECE7DF;border:0;" />'
        )
    else:
        initials = escape(_pet_initials(name_raw))
        thumb_html = (
            '<div style="width:44px;height:44px;line-height:44px;text-align:center;'
            "border-radius:10px;background-color:#F3EFE9;color:#7A7168;"
            "font-family:Georgia,'Times New Roman',serif;font-size:14px;"
            f'font-weight:700;">{initials}</div>'
        )

    facts = [
        _display_species(profile.species),
        " ".join(str(profile.breed or "").split()).strip() or None,
        _format_age(profile),
        " ".join(str(profile.status or "").split()).strip() or None,
    ]
    fact_line = " &middot; ".join(escape(part) for part in facts if part)

    link_html = (
        '<a href="' + escape(safe_url) + '" '
        'style="color:#C84B31;font-size:12.5px;font-weight:600;'
        'text-decoration:none;white-space:nowrap;">View &rarr;</a>'
        if safe_url
        else ""
    )
    row_border = "" if is_last else "border-bottom:1px solid #F2EDE6;"

    return (
        "<tr>"
        f'<td style="width:56px;padding:12px 0 12px 16px;vertical-align:middle;{row_border}">{thumb_html}</td>'
        f'<td style="padding:12px 12px;vertical-align:middle;{row_border}">'
        '<div style="font-size:14px;font-weight:700;color:#1F1B18;'
        f'line-height:1.25;">{pet_name}</div>'
        '<div style="font-size:12.5px;color:#6B6259;margin-top:2px;'
        f'line-height:1.35;">{fact_line}</div>'
        "</td>"
        f'<td style="padding:12px 16px 12px 4px;vertical-align:middle;text-align:right;{row_border}">'
        f"{link_html}</td>"
        "</tr>"
    )


def send_email(profiles: list["PetProfile"], send_to: str, send: bool = True) -> None:
    """Render and optionally send a summary email for pet profiles.

    Args:
        profiles: Profiles to include in the email.
        send_to: Email address to send the message to.
        send: When True, send via SMTP; otherwise print the message.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H")
    recipient = sanitize_email(send_to)
    if not recipient:
        raise ValueError(f"Invalid recipient email: {send_to!r}")
    profiles = list(profiles)
    new_profiles, seen_profiles = _partition_profiles_for_recipient(profiles, recipient)

    msg = EmailMessage()
    msg["From"] = os.environ["EMAIL_FROM"]
    msg["To"] = recipient
    msg["Subject"] = (
        f"PuppyPing - {len(new_profiles)} new, {len(seen_profiles)} seen "
        f"adoptable pets as of {ts}"
    )

    # -------- text version --------
    text_sections: list[str] = []
    if new_profiles:
        text_sections.append(
            "New pets (full details)\n"
            + "\n\n".join(_render_full_profile_text(p) for p in new_profiles)
        )
    if seen_profiles:
        compact_lines = []
        for p in seen_profiles:
            compact_lines.append(
                f"{p.name or 'Unnamed'} (#{p.pet_id}, {_display_species(p.species)}) | "
                f"{p.breed or '--'} | {p.age_months if p.age_months is not None else '--'} mo | "
                f"{p.status or '--'} | {p.url}"
            )
        text_sections.append(
            "Previously sent pets (summary)\n" + "\n".join(compact_lines)
        )
    text_body = "\n\n".join(text_sections) if text_sections else "No profiles found."
    msg.set_content(text_body)

    # -------- html version --------
    pupswipe_url = _pupswipe_url()
    full_cards_html = "".join(_render_new_pet_card_html(p) for p in new_profiles)
    if not full_cards_html:
        full_cards_html = (
            '<div style="background-color:#FFFFFF;border:1px solid #E8E2D9;'
            "border-radius:16px;padding:18px 20px;font-size:14px;color:#5C544D;"
            'margin-bottom:18px;">No new pets in this run.</div>'
        )

    seen_section_html = ""
    if seen_profiles:
        seen_rows = "".join(
            _render_seen_pet_row_html(p, is_last=(idx == len(seen_profiles) - 1))
            for idx, p in enumerate(seen_profiles)
        )
        seen_section_html = (
            '<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
            'text-transform:uppercase;color:#8A8178;margin:6px 0 10px 4px;">'
            "Previously sent &middot; still available</div>"
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="background-color:#FFFFFF;border:1px solid #E8E2D9;'
            "border-radius:16px;overflow:hidden;border-collapse:separate;"
            f'margin-bottom:18px;">{seen_rows}</table>'
        )

    html_body = (
        "<!doctype html>"
        '<html><body style="margin:0;padding:0;background-color:#F3EFE9;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        'Helvetica,Arial,sans-serif;color:#1F1B18;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background-color:#F3EFE9;padding:24px 12px;">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;width:100%;text-align:left;">'
        '<tr><td style="padding:0 4px 14px 4px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        "<tr>"
        '<td style="vertical-align:middle;">'
        '<span style="display:inline-block;width:26px;height:26px;line-height:26px;'
        "text-align:center;border-radius:8px;background-color:#D85A3F;color:#FFFFFF;"
        'font-size:13px;font-weight:700;vertical-align:middle;margin-right:8px;">'
        "P</span>"
        "<span style=\"font-family:Georgia,'Times New Roman',serif;font-size:22px;"
        'font-weight:700;color:#1F1B18;vertical-align:middle;">PuppyPing</span>'
        "</td>"
        '<td align="right" style="vertical-align:middle;">'
        '<a href="' + escape(pupswipe_url) + '" '
        'style="color:#C84B31;font-size:13px;font-weight:600;text-decoration:none;">'
        "Open PupSwipe &rarr;</a>"
        "</td>"
        "</tr>"
        "</table>"
        '<div style="font-size:13px;color:#6B6259;margin-top:8px;">'
        f"<strong>{len(new_profiles)} new</strong> &middot; "
        f"{len(seen_profiles)} still available &middot; {escape(ts)}"
        "</div>"
        "</td></tr>"
        "<tr><td>"
        '<div style="font-size:11px;font-weight:700;letter-spacing:0.08em;'
        'text-transform:uppercase;color:#8A8178;margin:0 0 10px 4px;">'
        "New pets</div>"
        f"{full_cards_html}"
        f"{seen_section_html}"
        '<div style="padding:8px 4px 0 4px;font-size:12px;color:#8A8178;'
        'text-align:center;">'
        "Sent by PuppyPing &middot; Browse all pets on "
        '<a href="' + escape(pupswipe_url) + '" '
        'style="color:#C84B31;text-decoration:none;font-weight:600;">PupSwipe</a>'
        "</div>"
        "</td></tr>"
        "</table>"
        "</td></tr>"
        "</table>"
        "</body></html>"
    )

    msg.add_alternative(html_body, subtype="html")

    if not send:
        print(msg)
        return

    with smtplib.SMTP_SSL(
        os.environ["EMAIL_HOST"], int(os.environ["EMAIL_PORT"])
    ) as smtp:
        smtp.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASS"])
        smtp.send_message(msg)
        try:
            mark_pet_profiles_emailed(recipient, profiles)
        except Exception:
            pass
