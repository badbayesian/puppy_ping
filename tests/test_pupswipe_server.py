from contextlib import contextmanager
import hashlib
import hmac
import http.client
from http.cookies import SimpleCookie
import threading
from types import SimpleNamespace

import puppyping.pupswipe.server as pupswipe


class DummyCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.description = []

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if "SELECT *" in query or "SELECT active.*" in query:
            self.description = [
                SimpleNamespace(name="dog_id"),
                SimpleNamespace(name="species"),
                SimpleNamespace(name="url"),
                SimpleNamespace(name="name"),
                SimpleNamespace(name="breed"),
                SimpleNamespace(name="gender"),
                SimpleNamespace(name="age_raw"),
                SimpleNamespace(name="age_months"),
                SimpleNamespace(name="weight_lbs"),
                SimpleNamespace(name="location"),
                SimpleNamespace(name="status"),
                SimpleNamespace(name="ratings"),
                SimpleNamespace(name="description"),
                SimpleNamespace(name="media"),
                SimpleNamespace(name="scraped_at_utc"),
                SimpleNamespace(name="source"),
            ]

    def fetchall(self):
        rows = self.rows
        self.rows = []
        return rows

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyConn:
    def __init__(self, rows=None):
        self.cursor_obj = DummyCursor(rows=rows)

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_get_pupswipe_sources_default(monkeypatch):
    monkeypatch.delenv("PUPSWIPE_SOURCES", raising=False)
    assert pupswipe._get_pupswipe_sources() == (
        "paws_chicago",
        "wright_way",
        "anti_cruelty",
    )


def test_get_pupswipe_sources_env_override(monkeypatch):
    monkeypatch.setenv("PUPSWIPE_SOURCES", "wright_way, paws_chicago, wright_way")
    assert pupswipe._get_pupswipe_sources() == ("wright_way", "paws_chicago")


def test_fetch_puppies_queries_multiple_sources(monkeypatch):
    row = (
        1,
        "dog",
        "https://example.com/dog/1",
        "Paloma",
        "Lab Mix",
        "Female",
        "3 months 1 day",
        3.03,
        None,
        "Murphysboro, IL",
        "Available",
        {},
        "A sweet lab mix puppy.",
        {"images": ["https://g.petango.com/photos/364/a.jpg"]},
        "2026-02-12T00:00:00+00:00",
        "wright_way",
    )
    conn = DummyConn(rows=[row])
    monkeypatch.setattr(pupswipe, "get_connection", lambda: conn)
    monkeypatch.setattr(pupswipe, "_ensure_app_schema", lambda _conn: None)
    monkeypatch.setattr(pupswipe, "PUPSWIPE_SOURCES", ("paws_chicago", "wright_way"))

    puppies = pupswipe._fetch_puppies(limit=1)

    assert len(puppies) == 1
    assert puppies[0]["primary_image"] == "https://g.petango.com/photos/364/a.jpg"
    query, params = conn.cursor_obj.executed[-1]
    assert "pet_status.source = ANY(%s::text[])" in query
    assert "SELECT DISTINCT ON (url)" in query
    assert "COALESCE(species, '') = %s" in query
    assert "COALESCE(breed, '') ILIKE %s ESCAPE '\\'" in query
    assert params[0] == ["paws_chicago", "wright_way"]
    assert params[1] == 8.0
    assert "AND (%s = '' OR source = %s)" in query
    assert "COALESCE(name, '') ILIKE %s ESCAPE '\\'" in query
    assert params[2] == ""
    assert params[4] == ""
    assert params[6] == ""
    assert params[8] == ""


def test_fetch_puppies_can_pin_current_profile_url(monkeypatch):
    row = (
        1,
        "dog",
        "https://example.com/dog/1",
        "Paloma",
        "Lab Mix",
        "Female",
        "3 months 1 day",
        3.03,
        None,
        "Murphysboro, IL",
        "Available",
        {},
        "A sweet lab mix puppy.",
        {"images": ["https://g.petango.com/photos/364/a.jpg"]},
        "2026-02-12T00:00:00+00:00",
        "wright_way",
    )
    conn = DummyConn(rows=[row])
    monkeypatch.setattr(pupswipe, "get_connection", lambda: conn)
    monkeypatch.setattr(pupswipe, "_ensure_app_schema", lambda _conn: None)
    monkeypatch.setattr(pupswipe, "PUPSWIPE_SOURCES", ("paws_chicago", "wright_way"))

    puppies = pupswipe._fetch_puppies(
        limit=1,
        pinned_profile_url="https://example.com/dog/1",
    )

    assert len(puppies) == 1
    query, params = conn.cursor_obj.executed[-1]
    assert "AND active.url = %s" in query
    assert params[-1] == "https://example.com/dog/1"


def test_fetch_puppies_can_exclude_current_profile_url_for_random(monkeypatch):
    row = (
        2,
        "dog",
        "https://example.com/dog/2",
        "Duke",
        "Mix",
        "Male",
        "4 months",
        4.0,
        None,
        "Chicago, IL",
        "Available",
        {},
        "Friendly pup.",
        {"images": ["https://example.com/duke.jpg"]},
        "2026-02-12T00:00:00+00:00",
        "paws_chicago",
    )
    conn = DummyConn(rows=[row])
    monkeypatch.setattr(pupswipe, "get_connection", lambda: conn)
    monkeypatch.setattr(pupswipe, "_ensure_app_schema", lambda _conn: None)
    monkeypatch.setattr(pupswipe, "PUPSWIPE_SOURCES", ("paws_chicago", "wright_way"))

    puppies = pupswipe._fetch_puppies(
        limit=1,
        randomize=True,
        excluded_profile_url="https://example.com/dog/1",
    )

    assert len(puppies) == 1
    query, params = conn.cursor_obj.executed[-1]
    assert "AND (%s = '' OR active.url <> %s)" in query
    assert params[-3] == "https://example.com/dog/1"
    assert params[-2] == "https://example.com/dog/1"


def test_count_puppies_queries_multiple_sources(monkeypatch):
    conn = DummyConn(rows=[(7,)])
    monkeypatch.setattr(pupswipe, "get_connection", lambda: conn)
    monkeypatch.setattr(pupswipe, "_ensure_app_schema", lambda _conn: None)
    monkeypatch.setattr(pupswipe, "PUPSWIPE_SOURCES", ("paws_chicago", "wright_way"))

    total = pupswipe._count_puppies()

    assert total == 7
    query, params = conn.cursor_obj.executed[-1]
    assert "pet_status.source = ANY(%s::text[])" in query
    assert "SELECT DISTINCT ON (url)" in query
    assert "COALESCE(species, '') = %s" in query
    assert "COALESCE(breed, '') ILIKE %s ESCAPE '\\'" in query
    assert params[0] == ["paws_chicago", "wright_way"]
    assert params[3] == 8.0
    assert "AND (%s = '' OR pet_status.source = %s)" in query
    assert "COALESCE(name, '') ILIKE %s ESCAPE '\\'" in query
    assert params[1] == ""
    assert params[4] == ""
    assert params[6] == ""
    assert params[8] == ""


def test_render_page_has_uniform_card_structure_for_paws(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, **_kwargs: [
            {
                "dog_id": 1,
                "url": "https://www.pawschicago.org/pet-available-for-adoption/showdog/123",
                "name": "Skye",
                "breed": "Retriever, Labrador/Mix",
                "gender": "Female",
                "age_raw": "6 months",
                "location": "Murphysboro, IL",
                "status": "Available",
                "description": "A sweet PAWS puppy profile description.",
                "media": {"images": ["https://pawschicago.canto.com/direct/image/abc"]},
                "source": "paws_chicago",
            }
        ],
    )

    html = pupswipe._render_page().decode("utf-8")
    assert "<h2>Skye</h2>" in html
    assert "Description" in html
    assert "A sweet PAWS puppy profile description." in html
    assert "Provider link" in html
    assert "View on PAWS Chicago" in html
    assert 'name="species" value="dog"' in html
    assert 'name="source" value="paws_chicago"' in html


def test_render_page_has_uniform_card_structure_for_wright_way(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, **_kwargs: [
            {
                "dog_id": 2,
                "url": "http://ws.petango.com/webservices/adoptablesearch/wsAdoptableAnimalDetails.aspx?id=60044823",
                "name": "Paloma",
                "breed": "Retriever, Labrador/Mix",
                "gender": "Female",
                "age_raw": "3 months 1 day",
                "location": "Murphysboro, IL",
                "status": "Available",
                "description": "A sweet lab mix puppy from Mississippi.",
                "media": {"images": ["https://g.petango.com/photos/364/1303e64e.jpg"]},
                "source": "wright_way",
            }
        ],
    )

    html = pupswipe._render_page().decode("utf-8")
    assert "<h2>Paloma</h2>" in html
    assert "Description" in html
    assert "A sweet lab mix puppy from Mississippi." in html
    assert "Provider link" in html
    assert "View on Wright-Way Rescue" in html
    assert 'name="species" value="dog"' in html
    assert 'name="source" value="wright_way"' in html


def test_render_page_swipe_forms_include_cat_species(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, **_kwargs: [
            {
                "dog_id": 22,
                "species": "cat",
                "url": "https://www.pawschicago.org/pet-available-for-adoption/showcat/22",
                "name": "Mochi",
                "breed": "Domestic Shorthair",
                "gender": "Female",
                "age_raw": "7 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Cat profile",
                "media": {"images": ["https://example.com/cat.jpg"]},
                "source": "paws_chicago",
            }
        ],
    )

    html = pupswipe._render_page().decode("utf-8")
    assert 'name="species" value="cat"' in html
    assert 'name="source" value="paws_chicago"' in html


def test_count_unseen_puppies_scopes_seen_swipes_by_source(monkeypatch):
    conn = DummyConn(rows=[(3,)])
    monkeypatch.setattr(pupswipe, "get_connection", lambda: conn)
    monkeypatch.setattr(pupswipe, "_ensure_app_schema", lambda _conn: None)
    monkeypatch.setattr(
        pupswipe, "PUPSWIPE_SOURCES", ("paws_chicago", "wright_way", "anti_cruelty")
    )

    total = pupswipe._count_unseen_puppies(
        viewer_user_key="abc123",
        provider_filter="anti_cruelty",
    )

    assert total == 3
    query, _params = conn.cursor_obj.executed[-1]
    assert "COALESCE(seen.source, '') = COALESCE(active.source, '')" in query
    assert "SELECT DISTINCT ON (url)" in query


def test_fetch_puppies_review_passed_scopes_swipes_by_source(monkeypatch):
    row = (
        9,
        "dog",
        "https://example.com/anti/9",
        "Saga",
        "Shepherd",
        "Male",
        "2 years 5 months",
        29.47,
        55.0,
        "Chicago, IL",
        "Available",
        {},
        "Friendly dog",
        {"images": ["https://example.com/saga.jpg"]},
        "2026-02-15T00:00:00+00:00",
        "anti_cruelty",
    )
    conn = DummyConn(rows=[row])
    monkeypatch.setattr(pupswipe, "get_connection", lambda: conn)
    monkeypatch.setattr(pupswipe, "_ensure_app_schema", lambda _conn: None)
    monkeypatch.setattr(
        pupswipe, "PUPSWIPE_SOURCES", ("paws_chicago", "wright_way", "anti_cruelty")
    )

    puppies = pupswipe._fetch_puppies(
        limit=1,
        viewer_user_key="anon",
        review_passed=True,
        provider_filter="anti_cruelty",
    )

    assert len(puppies) == 1
    query, _params = conn.cursor_obj.executed[-1]
    assert "viewer_last_swipes.source_key = COALESCE(active.source, '')" in query


def test_render_page_shows_random_button(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, **_kwargs: [
            {
                "dog_id": 3,
                "url": "https://example.com/dog/3",
                "name": "Ranger",
                "breed": "Mix",
                "gender": "Male",
                "age_raw": "4 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Ready for a home.",
                "media": {"images": ["https://example.com/photo.jpg"]},
                "source": "paws_chicago",
            }
        ],
    )

    html = pupswipe._render_page(
        breed_filter="Labrador",
        name_filter="Nova",
        provider_filter="wright_way",
        species_filter="cat",
        max_age_months=6.5,
    ).decode("utf-8")
    assert ">Random</button>" in html
    assert 'name="random" value="1"' in html
    assert 'id="breed-filter"' in html
    assert 'id="name-filter"' in html
    assert 'id="species-filter"' in html
    assert 'id="provider-filter"' in html
    assert 'name="f"' in html
    assert 'id="max-age-filter"' in html
    assert 'name="max_age"' in html
    assert 'value="6.5"' in html
    assert 'data-auto-submit-delay-ms="1200"' in html
    assert 'name="skip_url" value="https://example.com/dog/3"' in html
    assert 'name="offset"' not in html
    assert 'id="auto-filter-form"' in html
    assert 'data-auto-filter="1"' in html
    assert 'option value="cat" selected' in html
    assert 'option value="wright_way" selected' in html
    assert ">Filter</button>" not in html


def test_render_page_empty_state_matches_species_filter(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 0,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, **_kwargs: [],
    )

    html = pupswipe._render_page(species_filter="cat", max_age_months=6).decode("utf-8")
    assert "No cats match those filters. Try different filters." in html


def test_render_page_randomize_fetches_unseen_with_random_order(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 5,
    )
    monkeypatch.setattr(
        pupswipe,
        "_count_unseen_puppies",
        lambda **_kwargs: 4,
    )

    captured = {}

    def fake_fetch(
        limit,
        breed_filter="",
        name_filter="",
        provider_filter="",
        species_filter="",
        max_age_months=8.0,
        viewer_user_id=None,
        viewer_user_key=None,
        randomize=False,
        review_passed=False,
    ):
        captured["breed_filter"] = breed_filter
        captured["name_filter"] = name_filter
        captured["provider_filter"] = provider_filter
        captured["species_filter"] = species_filter
        captured["max_age_months"] = max_age_months
        captured["viewer_user_id"] = viewer_user_id
        captured["viewer_user_key"] = viewer_user_key
        captured["randomize"] = randomize
        captured["review_passed"] = review_passed
        return [
            {
                "dog_id": 4,
                "url": "https://example.com/dog/4",
                "name": "Nova",
                "breed": "Mix",
                "gender": "Female",
                "age_raw": "5 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Happy puppy.",
                "media": {"images": ["https://example.com/photo2.jpg"]},
                "source": "wright_way",
            }
        ]

    monkeypatch.setattr(pupswipe, "_fetch_puppies", fake_fetch)
    pupswipe._render_page(
        randomize=True,
        breed_filter="lab",
        name_filter="nova",
        provider_filter="paws_chicago",
        species_filter="cat",
        max_age_months=4.5,
    )

    assert captured["breed_filter"] == "lab"
    assert captured["name_filter"] == "nova"
    assert captured["provider_filter"] == "paws_chicago"
    assert captured["species_filter"] == "cat"
    assert captured["max_age_months"] == 4.5
    assert captured["randomize"] is True
    assert captured["review_passed"] is False


def test_render_page_carousel_pins_profile_url(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, **_kwargs: [
            {
                "dog_id": 404,
                "url": "https://example.com/dog/404",
                "name": "Daisy",
                "breed": "Mix",
                "gender": "Female",
                "age_raw": "6 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Photo carousel test.",
                "media": {
                    "images": [
                        "https://example.com/404-1.jpg",
                        "https://example.com/404-2.jpg",
                    ]
                },
                "source": "paws_chicago",
            }
        ],
    )

    html = pupswipe._render_page().decode("utf-8")
    assert html.count('name="pin_url" value="https://example.com/dog/404"') == 2


def test_render_page_forwards_pinned_profile_url_to_fetch(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 1,
    )
    captured: dict[str, str] = {}

    def fake_fetch(limit, **kwargs):
        captured["pinned_profile_url"] = str(kwargs.get("pinned_profile_url") or "")
        return [
            {
                "dog_id": 91,
                "url": "https://example.com/dog/91",
                "name": "Milo",
                "breed": "Mix",
                "gender": "Male",
                "age_raw": "5 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Pinned profile test.",
                "media": {"images": ["https://example.com/91.jpg"]},
                "source": "wright_way",
            }
        ]

    monkeypatch.setattr(pupswipe, "_fetch_puppies", fake_fetch)

    pupswipe._render_page(pinned_profile_url="https://example.com/dog/91")
    assert captured["pinned_profile_url"] == "https://example.com/dog/91"


def test_render_page_random_forwards_skip_url_as_excluded_profile(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 2,
    )
    monkeypatch.setattr(
        pupswipe,
        "_count_unseen_puppies",
        lambda **_kwargs: 2,
    )
    captured: dict[str, str] = {}

    def fake_fetch(limit, **kwargs):
        captured["excluded_profile_url"] = str(kwargs.get("excluded_profile_url") or "")
        return [
            {
                "dog_id": 11,
                "url": "https://example.com/dog/11",
                "name": "Poppy",
                "breed": "Mix",
                "gender": "Female",
                "age_raw": "5 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Random skip test.",
                "media": {"images": ["https://example.com/d11.jpg"]},
                "source": "paws_chicago",
            }
        ]

    monkeypatch.setattr(pupswipe, "_fetch_puppies", fake_fetch)
    pupswipe._render_page(
        randomize=True,
        skip_profile_url="https://example.com/dog/10",
    )
    assert captured["excluded_profile_url"] == "https://example.com/dog/10"


def test_render_page_start_over_switches_to_passed_review_mode(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 2,
    )
    monkeypatch.setattr(
        pupswipe,
        "_count_unseen_puppies",
        lambda **_kwargs: 0,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, **_kwargs: [],
    )

    html = pupswipe._render_page().decode("utf-8")
    assert ">Start over</button>" in html
    assert 'name="review" value="passed"' in html


def test_render_page_review_passed_fetches_passed_profiles(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 3,
    )
    monkeypatch.setattr(
        pupswipe,
        "_count_passed_puppies",
        lambda **_kwargs: 1,
    )
    captured = {}

    def fake_fetch(limit, review_passed=False, **_kwargs):
        captured["review_passed"] = review_passed
        return [
            {
                "dog_id": 88,
                "species": "dog",
                "url": "https://example.com/dog/88",
                "name": "River",
                "breed": "Mix",
                "gender": "Female",
                "age_raw": "7 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Ready again.",
                "media": {"images": ["https://example.com/dog88.jpg"]},
                "source": "paws_chicago",
            }
        ]

    monkeypatch.setattr(pupswipe, "_fetch_puppies", fake_fetch)
    html = pupswipe._render_page(review_passed=True).decode("utf-8")
    assert captured["review_passed"] is True
    assert "<h2>River</h2>" in html


def test_render_page_shows_completion_celebration(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 2,
    )
    monkeypatch.setattr(
        pupswipe,
        "_count_unseen_puppies",
        lambda **_kwargs: 0,
    )
    called = {"fetch": False}

    def fake_fetch(limit, **_kwargs):
        called["fetch"] = True
        return [
            {
                "dog_id": 9,
                "species": "cat",
                "url": "https://example.com/cat/9",
                "name": "Luna",
                "breed": "Mix",
                "gender": "Female",
                "age_raw": "5 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Friendly.",
                "media": {"images": ["https://example.com/cat9.jpg"]},
                "source": "paws_chicago",
            }
        ]

    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        fake_fetch,
    )

    html = pupswipe._render_page(species_filter="cat").decode("utf-8")
    assert "All pets reviewed" in html
    assert "swiped through all cats in this filter." in html
    assert "celebrate-burst" in html
    assert ">Start over</button>" in html
    assert called["fetch"] is False


def test_render_page_stats_show_remaining_unseen_not_offset(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 10,
    )
    monkeypatch.setattr(
        pupswipe,
        "_count_unseen_puppies",
        lambda **_kwargs: 3,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, **_kwargs: [
            {
                "dog_id": 55,
                "url": "https://example.com/dog/55",
                "name": "Scout",
                "breed": "Mix",
                "gender": "Male",
                "age_raw": "6 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Friendly pup.",
                "media": {"images": ["https://example.com/scout.jpg"]},
                "source": "paws_chicago",
            }
        ],
    )

    html = pupswipe._render_page().decode("utf-8")
    assert "3 left of 10" in html


def test_normalize_next_path_allows_only_local_paths():
    assert pupswipe._normalize_next_path("/likes", "/") == "/likes"
    assert pupswipe._normalize_next_path("likes", "/") == "/"
    assert pupswipe._normalize_next_path("https://evil.example", "/") == "/"
    assert pupswipe._normalize_next_path("//evil.example", "/") == "/"


def test_session_cookie_value_round_trip_and_tamper(monkeypatch):
    monkeypatch.setenv("PUPSWIPE_SESSION_SECRET", "unit-test-secret")
    encoded = pupswipe._encode_session_value(42)
    assert pupswipe._decode_session_value(encoded) == 42
    assert pupswipe._decode_session_value(f"42.{encoded.split('.', 1)[1]}x") is None
    assert pupswipe._decode_session_value("not-a-cookie") is None


def test_render_page_shows_auth_links_by_signin_state(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda **_kwargs: 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, **_kwargs: [
            {
                "dog_id": 99,
                "url": "https://example.com/dog/99",
                "name": "Maple",
                "breed": "Mix",
                "gender": "Female",
                "age_raw": "4 months",
                "location": "Chicago, IL",
                "status": "Available",
                "description": "Sweet puppy.",
                "media": {"images": ["https://example.com/maple.jpg"]},
                "source": "paws_chicago",
            }
        ],
    )

    signed_out_html = pupswipe._render_page().decode("utf-8")
    assert "Sign in to save likes" in signed_out_html
    assert 'href="/catalog"' in signed_out_html
    assert "/signin?next=%2F" in signed_out_html

    signed_in_html = pupswipe._render_page(signed_in_email="person@gmail.com").decode(
        "utf-8"
    )
    assert "person@gmail.com" in signed_in_html
    assert 'href="/catalog"' in signed_in_html
    assert "Liked pups" in signed_in_html
    assert "Reset password" in signed_in_html
    assert "Sign out" in signed_in_html


def test_render_catalog_page_shows_cards_and_filters():
    html = pupswipe._render_catalog_page(
        puppies=[
            {
                "pet_id": 501,
                "species": "cat",
                "url": "https://example.com/cat/501",
                "name": "Mochi",
                "breed": "Domestic Shorthair",
                "age_raw": "10 months",
                "location": "Chicago, IL",
                "status": "Available",
                "media": {"images": ["https://example.com/mochi.jpg"]},
                "source": "paws_chicago",
                "scraped_at_utc": "2026-02-15T12:00:00+00:00",
            }
        ],
        total_available=12,
        breed_filter="shorthair",
        species_filter="cat",
        max_age_months=12,
        signed_in_email="me@example.com",
    ).decode("utf-8")

    assert "<h1>Pet Catalog</h1>" in html
    assert "1 shown of 12 available" in html
    assert 'id="catalog-filter-form"' in html
    assert 'class="liked-grid catalog-grid"' in html
    assert 'id="catalog-name-filter"' in html
    assert 'id="catalog-breed-filter"' in html
    assert 'id="catalog-species-filter"' in html
    assert 'id="catalog-provider-filter"' in html
    assert 'id="catalog-max-age-filter"' in html
    assert 'data-auto-submit-delay-ms="1200"' in html
    assert "Mochi" in html
    assert "Open adoption site" in html
    assert 'action="/catalog/like"' in html
    assert 'name="pet_id" value="501"' in html
    assert 'name="pet_species" value="cat"' in html
    assert 'href="/catalog?clear_filters=1"' in html


def test_render_catalog_page_empty_state_matches_species_filter():
    html = pupswipe._render_catalog_page(
        puppies=[],
        total_available=0,
        species_filter="cat",
        name_filter="mochi",
    ).decode("utf-8")
    assert "No cats match those filters. Try different filters." in html


def test_render_likes_page_shows_filters_and_filtered_stats():
    html = pupswipe._render_likes_page(
        email="person@gmail.com",
        puppies=[],
        total_likes=10,
        filtered_likes=3,
        name_filter="Nova",
        breed_filter="Lab",
        species_filter="cat",
        provider_filter="wright_way",
    ).decode("utf-8")
    assert "3 shown of 10 liked" in html
    assert 'id="likes-name-filter"' in html
    assert 'id="likes-breed-filter"' in html
    assert 'id="likes-species-filter"' in html
    assert 'id="likes-provider-filter"' in html
    assert 'option value="cat" selected' in html
    assert 'option value="wright_way" selected' in html
    assert 'href="/likes">Clear</a>' in html
    assert "Remove unavailable" in html
    assert "Remove all shown" in html
    assert 'action="/likes/remove-all"' in html
    assert "No liked pets match those filters." in html


def test_render_likes_page_has_share_actions():
    html = pupswipe._render_likes_page(
        email="person@gmail.com",
        puppies=[
            {
                "dog_id": 7,
                "species": "dog",
                "name": "Maple",
                "breed": "Mix",
                "age_raw": "6 months",
                "location": "Chicago, IL",
                "status": "Available",
                "liked_at_utc": "2026-02-14T00:00:00+00:00",
                "url": "https://example.com/pets/7",
                "source": "wright_way",
                "media": {"images": ["https://example.com/maple.jpg"]},
            }
        ],
        total_likes=1,
    ).decode("utf-8")
    assert 'class="btn subtle share-btn"' in html
    assert 'data-share-url="https://example.com/pets/7"' in html
    assert (
        'data-share-text="I found a cute dog on PupSwipe. Adoption site: '
        'https://example.com/pets/7"'
    ) in html
    assert "Copy Share" in html
    assert "mailto:?" in html
    assert "Open on Wright-Way Rescue" in html
    assert 'action="/likes/remove"' in html
    assert 'name="pet_id" value="7"' in html
    assert 'name="pet_species" value="dog"' in html
    assert "Remove</button>" in html


def test_render_likes_page_marks_unavailable_cards():
    html = pupswipe._render_likes_page(
        email="person@gmail.com",
        puppies=[
            {
                "pet_id": 9,
                "species": "dog",
                "name": "Scout",
                "breed": "Mix",
                "age_raw": "2 years",
                "location": "Chicago, IL",
                "status": "Available",
                "is_active": False,
                "liked_at_utc": "2026-02-14T00:00:00+00:00",
                "url": "https://example.com/pets/9",
                "source": "paws_chicago",
                "media": {"images": ["https://example.com/scout.jpg"]},
            }
        ],
        total_likes=1,
    ).decode("utf-8")
    assert 'class="liked-card is-unavailable"' in html
    assert "No longer available" in html


def test_password_hash_round_trip():
    password = "supersecret123"
    password_hash = pupswipe._hash_password(password)
    assert pupswipe._verify_password(password, password_hash)
    assert not pupswipe._verify_password("wrongpassword", password_hash)


def test_password_error_enforces_min_length():
    assert pupswipe._password_error("short")
    assert pupswipe._password_error("s" * pupswipe.PASSWORD_MIN_LENGTH) is None


def test_new_password_error_validates_confirmation():
    assert pupswipe._new_password_error("short", "short")
    assert pupswipe._new_password_error("validpass123", "different")
    assert pupswipe._new_password_error("validpass123", "validpass123") is None


def test_password_reset_error_validates_inputs():
    assert pupswipe._password_reset_error("", "newpassword", "newpassword")
    assert pupswipe._password_reset_error("old", "short", "short")
    assert pupswipe._password_reset_error("oldpassword", "newpassword", "different")
    assert pupswipe._password_reset_error(
        "samepassword", "samepassword", "samepassword"
    )
    assert (
        pupswipe._password_reset_error("oldpassword", "newpassword", "newpassword")
        is None
    )


def test_render_signin_page_has_password_field():
    html = pupswipe._render_signin_page().decode("utf-8")
    assert '<body class="signin-page">' in html
    assert 'name="password"' in html
    assert 'type="password"' in html
    assert 'class="auth-links"' in html
    assert "Forgot password?" in html


def test_render_reset_password_page_has_fields():
    html = pupswipe._render_reset_password_page("person@gmail.com").decode("utf-8")
    assert "Reset password" in html
    assert 'name="current_password"' in html
    assert 'name="new_password"' in html
    assert 'name="confirm_password"' in html


def test_render_forgot_password_pages_have_expected_fields():
    request_html = pupswipe._render_forgot_password_page().decode("utf-8")
    assert 'name="email"' in request_html
    assert "Send reset link" in request_html

    reset_html = pupswipe._render_forgot_password_reset_page("abc123").decode("utf-8")
    assert 'name="token" value="abc123"' in reset_html
    assert 'name="new_password"' in reset_html
    assert 'name="confirm_password"' in reset_html


def test_password_reset_token_hash_is_deterministic():
    token = "my-token"
    assert pupswipe._password_reset_token_hash(
        token
    ) == pupswipe._password_reset_token_hash(token)


@contextmanager
def _running_pupswipe_server():
    server = pupswipe.ThreadingHTTPServer(("127.0.0.1", 0), pupswipe.AppHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request_once(
    port: int,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, resp.headers, data
    finally:
        conn.close()


def test_static_asset_allowlist_blocks_source_files_and_sets_security_headers():
    with _running_pupswipe_server() as server:
        port = server.server_port

        status_css, headers_css, body_css = _request_once(port, "GET", "/styles.css")
        assert status_css == 200
        assert headers_css.get("Content-Type", "").startswith("text/css")
        assert headers_css.get("X-Content-Type-Options") == "nosniff"
        assert headers_css.get("X-Frame-Options") == "DENY"
        assert headers_css.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert len(body_css) > 0

        status_js, headers_js, body_js = _request_once(port, "GET", "/swipe.js")
        assert status_js == 200
        assert headers_js.get("Content-Type", "").startswith("application/javascript")
        assert len(body_js) > 0

        status_head_css, _, body_head_css = _request_once(port, "HEAD", "/styles.css")
        assert status_head_css == 200
        assert body_head_css == b""

        for blocked_path in (
            "/config.py",
            "/auth.py",
            "/server.py",
            "/__init__.py",
            "/repository.py",
            "/../pyproject.toml",
            "/nonexistent",
        ):
            status, _headers, payload = _request_once(port, "GET", blocked_path)
            assert status == 404, blocked_path
            assert b"DEFAULT_SESSION_SECRET" not in payload
            assert b"AppHandler" not in payload

        head_py_status, _, head_py_body = _request_once(port, "HEAD", "/config.py")
        assert head_py_status == 404
        assert head_py_body == b""


def test_head_health_returns_200(monkeypatch):
    monkeypatch.setattr(pupswipe, "_fetch_puppies", lambda _limit: [])
    with _running_pupswipe_server() as server:
        status, headers, body = _request_once(server.server_port, "HEAD", "/api/health")
        assert status == 200
        assert headers.get("Content-Type") == "application/json"
        assert body == b""


def test_session_cookie_expiration_legacy_rejection_and_revocation(monkeypatch):
    monkeypatch.setenv("PUPSWIPE_SESSION_SECRET", "unit-test-secret")
    token = pupswipe._encode_session_value(
        7, session_version=2, now=1000, ttl_seconds=60
    )
    assert pupswipe._decode_session_token(token, now=1059) == (7, 2)
    assert pupswipe._decode_session_token(token, now=1060) is None
    assert pupswipe._decode_session_value(token, now=1060) is None

    legacy_sig = hmac.new(b"unit-test-secret", b"7", hashlib.sha256).hexdigest()
    assert pupswipe._decode_session_token(f"7.{legacy_sig}") is None

    fresh_cookie = pupswipe._encode_session_value(7, session_version=2)
    handler = pupswipe.AppHandler.__new__(pupswipe.AppHandler)
    handler.headers = {"Cookie": f"{pupswipe.SESSION_COOKIE_NAME}={fresh_cookie}"}

    current_version = 2
    monkeypatch.setattr(
        pupswipe,
        "_get_user_by_id",
        lambda uid: {
            "id": uid,
            "email": "user@example.com",
            "session_version": current_version,
        },
    )
    assert handler._signed_in_user()["id"] == 7

    current_version = 3
    assert handler._signed_in_user() is None


def test_post_reset_password_issues_updated_session_cookie(monkeypatch):
    monkeypatch.setenv("PUPSWIPE_SESSION_SECRET", "unit-test-secret")
    old_cookie = pupswipe._encode_session_value(7, session_version=1)
    monkeypatch.setattr(
        pupswipe,
        "_get_user_by_id",
        lambda uid: {
            "id": uid,
            "email": "user@example.com",
            "session_version": 1,
        },
    )
    monkeypatch.setattr(
        pupswipe,
        "_update_user_password",
        lambda _uid, _cur, _new: 2,
    )

    with _running_pupswipe_server() as server:
        body = (
            b"current_password=oldpassword1"
            b"&new_password=newpassword2"
            b"&confirm_password=newpassword2"
        )
        status, headers, _data = _request_once(
            server.server_port,
            "POST",
            "/reset-password",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": f"{pupswipe.SESSION_COOKIE_NAME}={old_cookie}",
            },
        )

        assert status == 303
        assert headers.get("Location") == "/likes?msg=Password+updated."
        jar = SimpleCookie()
        jar.load(headers.get("Set-Cookie", ""))
        new_token = jar[pupswipe.SESSION_COOKIE_NAME].value
        assert pupswipe._decode_session_token(new_token) == (7, 2)


def test_post_forgot_password_reset_clears_session_cookie(monkeypatch):
    monkeypatch.setattr(pupswipe, "_consume_password_reset_token", lambda _t, _p: 7)
    with _running_pupswipe_server() as server:
        body = (
            b"token=validtoken"
            b"&new_password=newpassword2"
            b"&confirm_password=newpassword2"
        )
        status, headers, _data = _request_once(
            server.server_port,
            "POST",
            "/forgot-password/reset",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        assert status == 303
        set_cookie = headers.get("Set-Cookie", "")
        assert f"{pupswipe.SESSION_COOKIE_NAME}=;" in set_cookie
        assert "Max-Age=0" in set_cookie


def test_post_rejects_oversized_and_invalid_content_length():
    with _running_pupswipe_server() as server:
        port = server.server_port

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.putrequest("POST", "/api/swipes")
            conn.putheader("Content-Length", str(pupswipe.MAX_REQUEST_BODY_BYTES + 1))
            conn.endheaders()
            resp = conn.getresponse()
            resp.read()
            assert resp.status == 413
        finally:
            conn.close()

        conn_bad = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn_bad.putrequest("POST", "/swipe")
            conn_bad.putheader("Content-Length", "notanumber")
            conn_bad.endheaders()
            resp_bad = conn_bad.getresponse()
            resp_bad.read()
            assert resp_bad.status == 400
        finally:
            conn_bad.close()
