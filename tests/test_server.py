import puppyping.server as server
from puppyping.models import PetMedia, PetProfile


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
    profile = PetProfile(
        dog_id=-1,
        url="u",
        age_months=6,
        media=PetMedia(),
    )

    monkeypatch.setattr(
        server,
        "fetch_adoptable_pet_profile_links",
        lambda source, store_in_db: {f"https://example.com/{source}/u"},
    )
    monkeypatch.setattr(
        server,
        "fetch_pet_profile",
        lambda source, url: profile,
    )
    monkeypatch.setattr(server, "tqdm", lambda items, desc=None: items)
    monkeypatch.setattr(
        server,
        "_load_scraped_profiles_for_source_today",
        lambda source: [],
    )

    status_calls = []
    monkeypatch.setattr(
        server,
        "store_pet_status",
        lambda source, links, logger=None: status_calls.append((source, links)),
    )

    stored = {}
    monkeypatch.setattr(
        server,
        "store_pet_profiles_in_db",
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
    profile = PetProfile(
        dog_id=-2,
        url="ok",
        age_months=4,
        media=PetMedia(),
    )

    links_by_source = {
        "paws_chicago": {
            "https://example.com/paws_chicago/ok",
            "https://example.com/paws_chicago/missing",
        },
        "wright_way": {"https://example.com/wright_way/ok"},
        "anti_cruelty": {"https://example.com/anti_cruelty/ok"},
    }

    monkeypatch.setattr(
        server,
        "fetch_adoptable_pet_profile_links",
        lambda source, store_in_db: links_by_source[source],
    )

    def fake_fetch_profile(source, url):
        if url.endswith("/missing"):
            raise RuntimeError("404")
        return profile

    monkeypatch.setattr(server, "fetch_pet_profile", fake_fetch_profile)
    monkeypatch.setattr(server, "tqdm", lambda items, desc=None: items)
    monkeypatch.setattr(
        server,
        "_load_scraped_profiles_for_source_today",
        lambda source: [],
    )
    monkeypatch.setattr(server, "store_pet_status", lambda *args, **kwargs: None)

    stored = {}
    monkeypatch.setattr(
        server,
        "store_pet_profiles_in_db",
        lambda profiles, logger=None: stored.update({"count": len(list(profiles))}),
    )
    monkeypatch.setattr(
        server,
        "send_email",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not send")),
    )

    server.logger = DummyLogger()
    server.run(send_ping=False, max_age=8.0, store_in_db=True)

    assert stored["count"] == 3


def test_run_sanitizes_email_recipients(monkeypatch):
    profile = PetProfile(
        dog_id=-3,
        url="u",
        age_months=6,
        media=PetMedia(),
    )

    monkeypatch.setattr(
        server,
        "fetch_adoptable_pet_profile_links",
        lambda source, store_in_db: {f"https://example.com/{source}/u"},
    )
    monkeypatch.setattr(server, "fetch_pet_profile", lambda source, url: profile)
    monkeypatch.setattr(server, "tqdm", lambda items, desc=None: items)
    monkeypatch.setattr(server, "store_pet_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "store_pet_profiles_in_db", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        server,
        "get_email_subscribers",
        lambda logger=None: [
            "db@example.com",
            "DB@example.com ",
            "not-an-email",
            "Name <bad@example.com>",
            "bad@example.com\r\nbcc:evil@example.com",
        ],
    )
    monkeypatch.setenv(
        "EMAILS_TO",
        " Good@Example.com, bad@@example.com, Name <x@example.com>, good@example.com ",
    )

    sent = []
    monkeypatch.setattr(
        server,
        "send_email",
        lambda profiles, send_to, send=True: sent.append(send_to),
    )

    server.logger = DummyLogger()
    server.run(send_ping=True, max_age=8.0, store_in_db=True)

    assert sent == ["good@example.com", "db@example.com"]


def test_run_sends_cat_profiles(monkeypatch):
    cat_profile = PetProfile(
        dog_id=156549,
        url="https://www.pawschicago.org/pet-available-for-adoption/showcat/156549",
        species="cat",
        name="Mochi",
        age_months=6,
        media=PetMedia(),
    )

    monkeypatch.setattr(
        server,
        "fetch_adoptable_pet_profile_links",
        lambda source, store_in_db: {f"https://example.com/{source}/cat"},
    )
    monkeypatch.setattr(server, "fetch_pet_profile", lambda source, url: cat_profile)
    monkeypatch.setattr(server, "tqdm", lambda items, desc=None: items)
    monkeypatch.setenv("EMAILS_TO", "to@example.com")

    sent_profiles = []

    def fake_send_email(profiles, send_to, send=True):
        sent_profiles.append((profiles, send_to))

    monkeypatch.setattr(server, "send_email", fake_send_email)

    server.logger = DummyLogger()
    server.run(send_ping=True, max_age=8.0, store_in_db=False)

    assert len(sent_profiles) == 1
    profiles, recipient = sent_profiles[0]
    assert recipient == "to@example.com"
    assert profiles
    assert all(p.species == "cat" for p in profiles)


def test_run_logs_remaining_animals_by_provider(monkeypatch):
    profile = PetProfile(
        dog_id=-4,
        url="u",
        age_months=5,
        media=PetMedia(),
    )

    monkeypatch.setattr(
        server,
        "fetch_adoptable_pet_profile_links",
        lambda source, store_in_db: {
            f"https://example.com/{source}/a",
            f"https://example.com/{source}/b",
        },
    )
    monkeypatch.setattr(server, "fetch_pet_profile", lambda source, url: profile)
    monkeypatch.setattr(server, "tqdm", lambda items, desc=None: items)
    monkeypatch.setattr(
        server,
        "_load_scraped_profiles_for_source_today",
        lambda source: [],
    )
    monkeypatch.setattr(server, "store_pet_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "store_pet_profiles_in_db", lambda *args, **kwargs: None)

    logger = DummyLogger()
    server.logger = logger
    server.run(send_ping=False, max_age=8.0, store_in_db=False)

    messages = [str(msg) for msg in logger.messages]
    assert any(
        "[paws_chicago] processed=1 remaining=1" in msg for msg in messages
    )
    assert any(
        "[wright_way] processed=1 remaining=1" in msg for msg in messages
    )


def test_scrape_source_reuses_today_profiles_without_live_scrape(monkeypatch):
    cached_profile = PetProfile(
        dog_id=123,
        url="https://example.com/paws/123",
        species="dog",
        age_months=6,
        media=PetMedia(),
    )
    monkeypatch.setattr(
        server,
        "_load_scraped_profiles_for_source_today",
        lambda source: [cached_profile],
    )
    monkeypatch.setattr(
        server,
        "fetch_adoptable_pet_profile_links",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("live links should not be fetched")
        ),
    )

    source, links, profiles, failed = server._scrape_source(
        "paws_chicago", store_in_db=True, force=False
    )

    assert source == "paws_chicago"
    assert links == {"https://example.com/paws/123"}
    assert profiles == [cached_profile]
    assert failed == 0


def test_scrape_source_force_ignores_today_profiles(monkeypatch):
    cached_profile = PetProfile(
        dog_id=124,
        url="https://example.com/paws/124",
        species="dog",
        age_months=7,
        media=PetMedia(),
    )
    live_profile = PetProfile(
        dog_id=125,
        url="https://example.com/paws/125",
        species="dog",
        age_months=5,
        media=PetMedia(),
    )
    monkeypatch.setattr(
        server,
        "_load_scraped_profiles_for_source_today",
        lambda source: [cached_profile],
    )
    monkeypatch.setattr(
        server,
        "fetch_adoptable_pet_profile_links",
        lambda source, store_in_db: {"https://example.com/paws/125"},
    )
    monkeypatch.setattr(
        server,
        "fetch_pet_profile",
        lambda source, url: live_profile,
    )
    monkeypatch.setattr(server, "tqdm", lambda items, desc=None: items)

    source, links, profiles, failed = server._scrape_source(
        "paws_chicago", store_in_db=True, force=True
    )

    assert source == "paws_chicago"
    assert links == {"https://example.com/paws/125"}
    assert profiles == [live_profile]
    assert failed == 0


def test_run_passes_force_flag_to_source_scrape(monkeypatch):
    captured = []
    monkeypatch.setattr(server, "SOURCES", ("paws_chicago",))
    monkeypatch.setattr(
        server,
        "_scrape_source",
        lambda source, store_in_db, force=False: (
            captured.append((source, store_in_db, force))
            or (source, set(), [], 0)
        ),
    )
    monkeypatch.setattr(server, "store_pet_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "store_pet_profiles_in_db", lambda *args, **kwargs: None)

    server.logger = DummyLogger()
    server.run(send_ping=False, store_in_db=False, force=True)

    assert captured == [("paws_chicago", False, True)]
