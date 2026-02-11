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


def test_run_no_email_stores_profiles_and_status(monkeypatch):
    profile = DogProfile(
        dog_id=-1,
        url="u",
        age_months=6,
        media=DogMedia(),
    )

    monkeypatch.setattr(
        server,
        "fetch_adoptable_dog_profile_links",
        lambda source, store_in_db: {f"https://example.com/{source}/u"},
    )
    monkeypatch.setattr(
        server,
        "fetch_dog_profile",
        lambda source, url: profile,
    )
    monkeypatch.setattr(server, "tqdm", lambda items, desc=None: items)

    status_calls = []
    monkeypatch.setattr(
        server,
        "store_dog_status",
        lambda source, links, logger=None: status_calls.append((source, links)),
    )

    stored = {}
    monkeypatch.setattr(
        server,
        "store_profiles_in_db",
        lambda profiles, logger=None: stored.update({"count": len(list(profiles))}),
    )
    monkeypatch.setattr(
        server,
        "send_email",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not send")),
    )

    server.logger = DummyLogger()
    server.run(send_ping=False, max_age=8.0, store_in_db=True)

    assert stored["count"] == len(server.SOURCES)
    assert sorted(source for source, _ in status_calls) == sorted(server.SOURCES)
