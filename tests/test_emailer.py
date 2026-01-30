import os

import smtplib

from puppyping.emailer import send_email
from puppyping.models import DogMedia, DogProfile


class DummySMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.logged_in = False
        self.sent = False

    def login(self, user, password):
        self.logged_in = True

    def send_message(self, msg):
        self.sent = True

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

    profile = DogProfile(dog_id=1, url="u", media=DogMedia())
    send_email([profile], send_to="to@example.com", send=False)

    smtp = dummy["smtp"]
    assert smtp.logged_in is True
    assert smtp.sent is False
