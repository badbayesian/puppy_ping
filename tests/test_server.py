import os

import puppyping.server as server
from puppyping.models import DogMedia, DogProfile


class DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(msg)


def test_safe_less_than():
    assert server.__safe_less_than(3, 5) is True
    assert server.__safe_less_than(None, 5) is False
    assert server.__safe_less_than(6, 5) is False


def test_run_no_email(monkeypatch):
    profile = DogProfile(
        dog_id=-1,
        url="u",
        age_months=6,
        media=DogMedia(),
    )
    monkeypatch.setattr(server, "fetch_adoptable_dog_profile_links", lambda: {"u"})
    monkeypatch.setattr(server, "fetch_dog_profile", lambda url: profile)
    stored = {}
    monkeypatch.setattr(server, "store_profiles", lambda profiles, logger=None: stored.update({"count": len(list(profiles))}))
    monkeypatch.setenv("EMAILS_TO", "thebutler.server@gmail.com")
    server.logger = DummyLogger()
    server.run(send_mail=False, max_age=8.0)
    assert stored["count"] == 1
