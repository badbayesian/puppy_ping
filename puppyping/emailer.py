from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from html import escape

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import DogProfile


def send_email(profiles: list["DogProfile"], send: bool = True) -> None:
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
        return "--" if v is None else str(v)

    order = ["children", "dogs", "cats", "home_alone", "activity", "environment"]

    cards = []
    for p in profiles:
        ratings_html = "".join(
            f"<li><b>{escape(k.replace('_', ' ').title())}:</b> {escape(str(p.ratings.get(k)) if p.ratings.get(k) is not None else '--')}</li>"
            for k in order
            if k in p.ratings
        ) or "<li>--</li>"

        # show up to 3 images (email clients may block remote images until user clicks "display images")
        imgs = "".join(
            f'<div style="margin:8px 0;"><img src="{escape(u)}" style="max-width:480px;width:100%;height:auto;border-radius:8px;" /></div>'
            for u in (p.media.images[:3] if p.media and p.media.images else [])
        )

        desc = (p.description or "").strip()
        if len(desc) > 600:
            desc = desc[:599].rstrip() + "..."

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
            Scraped at: {escape(fmt(p.scraped_at_utc))} * Media: {escape(p.media.summary() if p.media else "--")}
          </div>

          {"<div style='margin-top:10px;'><div style='font-weight:700;'>Notes</div><div style='white-space:pre-wrap;'>" + escape(desc) + "</div></div>" if desc else ""}
        </div>
        """)

    html_body = f"""
    <html>
      <body style="font-family:Arial,Helvetica,sans-serif;max-width:780px;margin:0 auto;padding:10px;">
        <h2 style="margin:8px 0;">PAWS Chicago -- Adoptable Dogs</h2>
        <div style="color:#666;margin-bottom:14px;">{len(profiles)} profiles * generated {escape(ts)}</div>
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
