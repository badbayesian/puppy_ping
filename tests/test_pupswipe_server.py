from types import SimpleNamespace

import puppyping.pupswipe.server as pupswipe


class DummyCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.description = []

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if "SELECT *" in query:
            self.description = [
                SimpleNamespace(name="dog_id"),
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
    assert pupswipe._get_pupswipe_sources() == ("paws_chicago", "wright_way")


def test_get_pupswipe_sources_env_override(monkeypatch):
    monkeypatch.setenv("PUPSWIPE_SOURCES", "wright_way, paws_chicago, wright_way")
    assert pupswipe._get_pupswipe_sources() == ("wright_way", "paws_chicago")


def test_fetch_puppies_queries_multiple_sources(monkeypatch):
    row = (
        1,
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

    puppies = pupswipe._fetch_puppies(limit=1, offset=0)

    assert len(puppies) == 1
    assert puppies[0]["primary_image"] == "https://g.petango.com/photos/364/a.jpg"
    query, params = conn.cursor_obj.executed[-1]
    assert "dog_status.source = ANY(%s::text[])" in query
    assert "COALESCE(breed, '') ILIKE %s ESCAPE '\\'" in query
    assert params[0] == ["paws_chicago", "wright_way"]
    assert "AND (%s = '' OR source = %s)" in query
    assert "COALESCE(name, '') ILIKE %s ESCAPE '\\'" in query
    assert params[2] == ""
    assert params[4] == ""
    assert params[6] == ""


def test_count_puppies_queries_multiple_sources(monkeypatch):
    conn = DummyConn(rows=[(7,)])
    monkeypatch.setattr(pupswipe, "get_connection", lambda: conn)
    monkeypatch.setattr(pupswipe, "_ensure_app_schema", lambda _conn: None)
    monkeypatch.setattr(pupswipe, "PUPSWIPE_SOURCES", ("paws_chicago", "wright_way"))

    total = pupswipe._count_puppies()

    assert total == 7
    query, params = conn.cursor_obj.executed[-1]
    assert "dog_status.source = ANY(%s::text[])" in query
    assert "COALESCE(breed, '') ILIKE %s ESCAPE '\\'" in query
    assert params[0] == ["paws_chicago", "wright_way"]
    assert "AND (%s = '' OR dog_status.source = %s)" in query
    assert "COALESCE(name, '') ILIKE %s ESCAPE '\\'" in query
    assert params[1] == ""
    assert params[4] == ""
    assert params[6] == ""


def test_render_page_has_uniform_card_structure_for_paws(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda breed_filter="", name_filter="", provider_filter="": 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, offset=0, breed_filter="", name_filter="", provider_filter="": [
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


def test_render_page_has_uniform_card_structure_for_wright_way(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda breed_filter="", name_filter="", provider_filter="": 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, offset=0, breed_filter="", name_filter="", provider_filter="": [
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


def test_render_page_shows_random_button(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda breed_filter="", name_filter="", provider_filter="": 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, offset=0, breed_filter="", name_filter="", provider_filter="": [
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
        offset=0,
        breed_filter="Labrador",
        name_filter="Nova",
        provider_filter="wright_way",
    ).decode("utf-8")
    assert ">Random</button>" in html
    assert 'name="random" value="1"' in html
    assert 'name="breed" value="Labrador"' in html
    assert 'name="name" value="Nova"' in html
    assert 'name="provider" value="wright_way"' in html
    assert 'id="breed-filter"' in html
    assert 'id="name-filter"' in html
    assert 'id="provider-filter"' in html
    assert 'option value="wright_way" selected' in html


def test_render_page_randomize_uses_random_offset(monkeypatch):
    monkeypatch.setattr(
        pupswipe,
        "_count_puppies",
        lambda breed_filter="", name_filter="", provider_filter="": 5,
    )
    monkeypatch.setattr(pupswipe.random, "randrange", lambda n: 1)

    captured = {}

    def fake_fetch(
        limit,
        offset=0,
        breed_filter="",
        name_filter="",
        provider_filter="",
    ):
        captured["offset"] = offset
        captured["breed_filter"] = breed_filter
        captured["name_filter"] = name_filter
        captured["provider_filter"] = provider_filter
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
        offset=1,
        randomize=True,
        breed_filter="lab",
        name_filter="nova",
        provider_filter="paws_chicago",
    )

    # random.randrange(total - 1) -> 1, then offset shifts to avoid current offset 1.
    assert captured["offset"] == 2
    assert captured["breed_filter"] == "lab"
    assert captured["name_filter"] == "nova"
    assert captured["provider_filter"] == "paws_chicago"


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
        lambda breed_filter="", name_filter="", provider_filter="": 1,
    )
    monkeypatch.setattr(
        pupswipe,
        "_fetch_puppies",
        lambda limit, offset=0, breed_filter="", name_filter="", provider_filter="": [
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
    assert "/signin?next=%2F" in signed_out_html

    signed_in_html = pupswipe._render_page(
        signed_in_email="person@gmail.com"
    ).decode("utf-8")
    assert "person@gmail.com" in signed_in_html
    assert "Liked pups" in signed_in_html
    assert "Sign out" in signed_in_html
