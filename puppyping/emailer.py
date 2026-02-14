from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape

from typing import TYPE_CHECKING
from .db import get_sent_pet_keys, mark_pet_profiles_emailed
from .email_utils import sanitize_email

if TYPE_CHECKING:
    from .models import PetProfile


def _profile_key(profile: "PetProfile") -> tuple[int, str]:
    return (int(profile.pet_id), str(profile.species or "dog").strip().lower() or "dog")


def _display_species(species: str | None) -> str:
    """Return species text for user-facing email content."""
    normalized = str(species or "").strip().lower() or "dog"
    return normalized.title()


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
    def fmt(v):
        """Format optional values for display.

        Args:
            v: Value to format.

        Returns:
            Formatted string for HTML display.
        """
        return "--" if v is None else str(v)

    order = [
        "children",
        "dogs",
        "cats",
        "home_alone",
        "activity",
        "environment",
        "human_sociability",
        "enrichment",
    ]

    full_cards = []
    for p in new_profiles:
        ratings_html = (
            "".join(
                f"<li><b>{escape(k.replace('_', ' ').title())}:</b> {escape(str(p.ratings.get(k)) if p.ratings.get(k) is not None else '--')}</li>"
                for k in order
                if k in p.ratings
            )
            or "<li>--</li>"
        )

        # show up to 3 images (email clients may block remote images until user clicks "display images")
        imgs = "".join(
            f'<div style="margin:8px 0;"><img src="{escape(u)}" style="max-width:480px;width:100%;height:auto;border-radius:8px;" /></div>'
            for u in (p.media.images[:3] if p.media and p.media.images else [])
        )

        desc = (p.description or "").strip()
        if len(desc) > 600:
            desc = desc[:599].rstrip() + "..."

        full_cards.append(f"""
        <div style="border:1px solid #e5e5e5;border-radius:12px;padding:14px;margin:14px 0;">
          <div style="font-size:18px;font-weight:700;margin-bottom:6px;">
            {escape(fmt(p.name))} <span style="color:#666;font-weight:400;">(#{p.pet_id})</span>
          </div>

          <div style="color:#333;line-height:1.4;">
            <div><b>Species:</b> {escape(_display_species(p.species))}</div>
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
            Scraped at: {escape(fmt(p.scraped_at_utc))} * Media: {escape(p.media.summary() if p.media else "--")}
          </div>

          {"<div style='margin-top:10px;'><div style='font-weight:700;'>Notes</div><div style='white-space:pre-wrap;'>" + escape(desc) + "</div></div>" if desc else ""}
        </div>
        """)

    compact_cards: list[str] = []
    for p in seen_profiles:
        compact_cards.append(
            f"""
            <div style="border:1px solid #ececec;border-radius:10px;padding:10px;margin:10px 0;">
              <div style="font-size:16px;font-weight:700;">
                {escape(fmt(p.name))} <span style="color:#666;font-weight:400;">(#{p.pet_id}, {escape(_display_species(p.species))})</span>
              </div>
              <div style="color:#333;line-height:1.4;font-size:14px;">
                <b>Breed:</b> {escape(fmt(p.breed))} |
                <b>Age:</b> {escape(fmt(p.age_months))} months |
                <b>Status:</b> {escape(fmt(p.status))}
              </div>
              <div style="margin-top:6px;">
                <a href="{escape(p.url)}">{escape(p.url)}</a>
              </div>
            </div>
            """
        )

    full_section_html = (
        "<h3 style='margin:14px 0 8px;'>New pets (full details)</h3>"
        + "".join(full_cards)
        if full_cards
        else "<h3 style='margin:14px 0 8px;'>New pets (full details)</h3><div>None in this run.</div>"
    )
    compact_section_html = (
        "<h3 style='margin:18px 0 8px;'>Previously sent pets (summary)</h3>"
        + "".join(compact_cards)
        if compact_cards
        else ""
    )

    html_body = f"""
    <html>
      <body style="font-family:Arial,Helvetica,sans-serif;max-width:780px;margin:0 auto;padding:10px;">
        <h2 style="margin:8px 0;">PuppyPing -- Adoptable Pets</h2>
        <div style="color:#666;margin-bottom:14px;">
          {len(profiles)} profiles total * {len(new_profiles)} new * {len(seen_profiles)} previously sent * generated {escape(ts)}
        </div>
        {full_section_html}
        {compact_section_html}
      </body>
    </html>
    """

    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP_SSL(
        os.environ["EMAIL_HOST"], int(os.environ["EMAIL_PORT"])
    ) as smtp:
        smtp.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASS"])
        if send:
            smtp.send_message(msg)
            try:
                mark_pet_profiles_emailed(recipient, profiles)
            except Exception:
                pass
        else:
            print(msg)
