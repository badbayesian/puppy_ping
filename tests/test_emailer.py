import os

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

    dummy = {}

    def fake_smtp(host, port):
        smtp = DummySMTP(host, port)
        dummy["smtp"] = smtp
        return smtp

    monkeypatch.setattr(smtplib, "SMTP_SSL", fake_smtp)

    profile = PetProfile(dog_id=1, url="u", media=PetMedia())
    emailer.send_email([profile], send_to="to@example.com", send=False)

    smtp = dummy["smtp"]
    assert smtp.logged_in is True
    assert smtp.sent is False


def test_send_email_rejects_invalid_recipient(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "From <from@example.com>")
    monkeypatch.setenv("EMAIL_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_PORT", "465")
    monkeypatch.setenv("EMAIL_USER", "user")
    monkeypatch.setenv("EMAIL_PASS", "pass")

    monkeypatch.setattr(
        smtplib,
        "SMTP_SSL",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not connect")),
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
    monkeypatch.setattr(emailer, "mark_pet_profiles_emailed", lambda *_args, **_kwargs: None)

    emailer.send_email([profile], send_to="to@example.com", send=True)

    smtp = dummy["smtp"]
    assert smtp.sent is True
    assert "adoptable pets" in str(smtp.msg["Subject"]).lower()
    assert "PuppyPing -- Adoptable Pets" in smtp.msg.as_string()
    assert "Species:</b> Cat" in smtp.msg.as_string()
    assert "Species    : Cat" in smtp.msg.as_string()


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
    monkeypatch.setattr(emailer, "get_sent_pet_keys", lambda *_args, **_kwargs: {(2, "cat")})
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
        PetProfile(dog_id=1, species="dog", name="New Pup", url="https://example.com/d/1", media=PetMedia()),
        PetProfile(dog_id=2, species="cat", name="Seen Cat", url="https://example.com/c/2", media=PetMedia()),
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
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *_args, **_kwargs: DummySMTP("host", 465))
    monkeypatch.setattr(emailer, "get_sent_pet_keys", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(
        emailer,
        "mark_pet_profiles_emailed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("history should not be written when send=False")
        ),
    )

    profile = PetProfile(dog_id=3, species="cat", name="Preview Cat", url="u", media=PetMedia())
    emailer.send_email([profile], send_to="to@example.com", send=False)
