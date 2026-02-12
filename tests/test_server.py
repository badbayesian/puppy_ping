import puppyping.server as server
from puppyping.models import DogMedia, DogProfile


class DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(msg)

    def warning(self, msg):
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


def test_run_continues_when_profile_fetch_raises(monkeypatch):
    profile = DogProfile(
        dog_id=-2,
        url="ok",
        age_months=4,
        media=DogMedia(),
    )

    links_by_source = {
        "paws_chicago": {
            "https://example.com/paws_chicago/ok",
            "https://example.com/paws_chicago/missing",
        },
        "wright_way": {"https://example.com/wright_way/ok"},
    }

    monkeypatch.setattr(
        server,
        "fetch_adoptable_dog_profile_links",
        lambda source, store_in_db: links_by_source[source],
    )

    def fake_fetch_profile(source, url):
        if url.endswith("/missing"):
            raise RuntimeError("404")
        return profile

    monkeypatch.setattr(server, "fetch_dog_profile", fake_fetch_profile)
    monkeypatch.setattr(server, "tqdm", lambda items, desc=None: items)
    monkeypatch.setattr(server, "store_dog_status", lambda *args, **kwargs: None)

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

    assert stored["count"] == 2
