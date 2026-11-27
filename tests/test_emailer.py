import smtplib
import pytest

import puppyping.emailer as emailer
from puppyping.models import PetMedia, PetProfile


class DummySMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.logged_in = False
        self.sent = False
        self.msg = None

    def login(self, user, password):
        self.logged_in = True

    def send_message(self, msg):
        self.sent = True
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_send_email_no_send(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "From <from@example.com>")
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_PORT", "465")
    monkeypatch.setenv("EMAIL_USER", "user")
    monkeypatch.setenv("EMAIL_PASS", "pass")
    monkeypatch.setenv("EMAILS_TO", "to@example.com")

    monkeypatch.setattr(
        smtplib,
        "SMTP_SSL",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("preview email should not open SMTP")
        ),
    )

    profile = PetProfile(dog_id=1, url="u", media=PetMedia())
    emailer.send_email([profile], send_to="to@example.com", send=False)


def test_send_email_rejects_invalid_recipient(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "From <from@example.com>")
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_PORT", "465")
    monkeypatch.setenv("EMAIL_USER", "user")
    monkeypatch.setenv("EMAIL_PASS", "pass")

    monkeypatch.setattr(
        smtplib,
        "SMTP_SSL",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not connect")
        ),
    )

    profile = PetProfile(dog_id=1, url="u", media=PetMedia())
    with pytest.raises(ValueError, match="Invalid recipient email"):
        emailer.send_email([profile], send_to="Name <to@example.com>", send=False)


def test_send_email_includes_cat_species_and_pet_subject(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "From <from@example.com>")
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_PORT", "465")
    monkeypatch.setenv("EMAIL_USER", "user")
    monkeypatch.setenv("EMAIL_PASS", "pass")

    dummy = {}

    def fake_smtp(host, port):
        smtp = DummySMTP(host, port)
        dummy["smtp"] = smtp
        return smtp

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_smtp)

    profile = PetProfile(
        dog_id=156549,
        url="https://www.pawschicago.org/pet-available-for-adoption/showcat/156549",
        species="cat",
        name="Mochi",
        breed="Domestic Shorthair",
        media=PetMedia(),
    )
    monkeypatch.setattr(emailer, "get_sent_pet_keys", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(
        emailer, "mark_pet_profiles_emailed", lambda *_args, **_kwargs: None
    )

    emailer.send_email([profile], send_to="to@example.com", send=True)

    smtp = dummy["smtp"]
    html_part = smtp.msg.get_body(preferencelist=("html",)).get_content()
    text_part = smtp.msg.get_body(preferencelist=("plain",)).get_content()
    assert smtp.sent is True
    assert "adoptable pets" in str(smtp.msg["Subject"]).lower()
    assert "PuppyPing" in html_part
    assert "Mochi" in html_part
    assert "Cat" in html_part
    assert "Domestic Shorthair" in html_part
    assert "View on PAWS Chicago" in html_part
    assert "Species    : Cat" in text_part


def test_send_email_consolidates_new_and_seen(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "From <from@example.com>")
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_PORT", "465")
    monkeypatch.setenv("EMAIL_USER", "user")
    monkeypatch.setenv("EMAIL_PASS", "pass")

    dummy = {}

    def fake_smtp(host, port):
        smtp = DummySMTP(host, port)
        dummy["smtp"] = smtp
        return smtp

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_smtp)
    monkeypatch.setattr(
        emailer, "get_sent_pet_keys", lambda *_args, **_kwargs: {(2, "cat")}
    )
    recorded = {}
    monkeypatch.setattr(
        emailer,
        "mark_pet_profiles_emailed",
        lambda recipient, profiles: recorded.update(
            {
                "recipient": recipient,
                "count": len(list(profiles)),
            }
        ),
    )

    profiles = [
        PetProfile(
            dog_id=1,
            species="dog",
            name="New Pup",
            url="https://example.com/d/1",
            media=PetMedia(),
        ),
        PetProfile(
            dog_id=2,
            species="cat",
            name="Seen Cat",
            url="https://example.com/c/2",
            media=PetMedia(),
        ),
    ]
    emailer.send_email(profiles, send_to="to@example.com", send=True)

    smtp = dummy["smtp"]
    raw = smtp.msg.as_string()
    assert "New pets (full details)" in raw
    assert "Previously sent pets (summary)" in raw
    assert "1 new, 1 seen adoptable pets" in str(smtp.msg["Subject"])
    assert recorded["recipient"] == "to@example.com"
    assert recorded["count"] == 2


def test_send_email_preview_does_not_update_history(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "From <from@example.com>")
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_PORT", "465")
    monkeypatch.setenv("EMAIL_USER", "user")
    monkeypatch.setenv("EMAIL_PASS", "pass")
    monkeypatch.setattr(
        smtplib, "SMTP_SSL", lambda *_args, **_kwargs: DummySMTP("host", 465)
    )
    monkeypatch.setattr(emailer, "get_sent_pet_keys", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(
        emailer,
        "mark_pet_profiles_emailed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("history should not be written when send=False")
        ),
    )

    profile = PetProfile(
        dog_id=3, species="cat", name="Preview Cat", url="u", media=PetMedia()
    )
    emailer.send_email([profile], send_to="to@example.com", send=False)


def test_send_email_renders_magazine_photos_ratings_and_seen_thumbnails(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "From <from@example.com>")
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_PORT", "465")
    monkeypatch.setenv("EMAIL_USER", "user")
    monkeypatch.setenv("EMAIL_PASS", "pass")

    dummy = {}

    def fake_smtp(host, port):
        smtp = DummySMTP(host, port)
        dummy["smtp"] = smtp
        return smtp

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_smtp)
    monkeypatch.setattr(
        emailer,
        "get_sent_pet_keys",
        lambda *_args, **_kwargs: {(2, "dog"), (3, "cat")},
    )
    monkeypatch.setattr(
        emailer, "mark_pet_profiles_emailed", lambda *_args, **_kwargs: None
    )

    profiles = [
        PetProfile(
            dog_id=1,
            species="dog",
            name="Freddy",
            breed="Sheep Dog, Mix",
            gender="Male",
            age_raw="2 months",
            weight_lbs=23.2,
            location="Adoption Event",
            status="Available",
            ratings={"children": 5, "cats": None, "dogs": 4},
            description="Playful puppy looking for a warm home.",
            url="https://www.pawschicago.org/pet-available-for-adoption/showdog/1",
            media=PetMedia(
                images=[
                    "https://example.com/hero.jpg",
                    "https://example.com/thumb1.jpg",
                    "https://example.com/thumb2.jpg",
                    "https://example.com/ignored4.jpg",
                    "javascript:alert(1)",
                ]
            ),
        ),
        PetProfile(
            dog_id=2,
            species="dog",
            name="Zeus",
            breed="Mixed Breed",
            age_months=4.3,
            status="Available",
            url="https://new.shelterluv.com/embed/animal/ACIL-A-2",
            media=PetMedia(images=["https://example.com/zeus.jpg"]),
        ),
        PetProfile(
            dog_id=3,
            species="cat",
            name="Scrappy Cat",
            breed="Domestic Shorthair",
            age_months=4.0,
            status="Available",
            url="https://new.shelterluv.com/embed/animal/ACIL-A-3",
            media=PetMedia(),
        ),
    ]
    emailer.send_email(profiles, send_to="to@example.com", send=True)

    html_part = dummy["smtp"].msg.get_body(preferencelist=("html",)).get_content()
    assert "https://example.com/hero.jpg" in html_part
    assert "https://example.com/thumb1.jpg" in html_part
    assert "https://example.com/thumb2.jpg" in html_part
    assert "https://example.com/ignored4.jpg" not in html_part
    assert "javascript:" not in html_part
    assert "Children" in html_part
    assert "5/5" in html_part
    assert "Dogs" in html_part
    assert "4/5" in html_part
    assert "Cats" not in html_part
    assert "Scraped at:" not in html_part
    assert "View on PAWS Chicago" in html_part
    assert "https://example.com/zeus.jpg" in html_part
    assert ">SC<" in html_part


def test_send_email_uses_pupswipe_public_url_or_default(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "From <from@example.com>")
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_PORT", "465")
    monkeypatch.setenv("EMAIL_USER", "user")
    monkeypatch.setenv("EMAIL_PASS", "pass")

    sent_messages = []

    def fake_smtp(host, port):
        smtp = DummySMTP(host, port)
        sent_messages.append(smtp)
        return smtp

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_smtp)
    monkeypatch.setattr(emailer, "get_sent_pet_keys", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(
        emailer, "mark_pet_profiles_emailed", lambda *_args, **_kwargs: None
    )

    profile = PetProfile(
        dog_id=10,
        species="dog",
        name="Daisy",
        url="https://example.com/d/10",
        media=PetMedia(),
    )

    monkeypatch.delenv("PUPSWIPE_PUBLIC_URL", raising=False)
    emailer.send_email([profile], send_to="to@example.com", send=True)
    default_html = (
        sent_messages[-1].msg.get_body(preferencelist=("html",)).get_content()
    )
    assert 'href="https://puppyping.com"' in default_html
    assert "10 lbs" not in default_html

    monkeypatch.setenv("PUPSWIPE_PUBLIC_URL", "https://custom.puppyping.example/")
    emailer.send_email([profile], send_to="to@example.com", send=True)
    custom_html = sent_messages[-1].msg.get_body(preferencelist=("html",)).get_content()
    assert 'href="https://custom.puppyping.example"' in custom_html
    assert "custom.puppyping.example/" not in custom_html
