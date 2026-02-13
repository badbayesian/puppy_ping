from bs4 import BeautifulSoup

import puppyping.providers.paws as paws
import puppyping.providers.scrape_helpers as helpers
from puppyping.models import PetMedia, PetProfile


def test_parse_age_to_months():
    assert helpers._parse_age_to_months("2 years 3 months") == 27.0
    assert helpers._parse_age_to_months("6 months") == 6.0
    assert helpers._parse_age_to_months("1 year") == 12.0
    assert helpers._parse_age_to_months(None) is None


def test_parse_weight_lbs():
    assert helpers._parse_weight_lbs("35 lbs") == 35.0
    assert helpers._parse_weight_lbs("7.5") == 7.5
    assert helpers._parse_weight_lbs(None) is None


def test_clean_text():
    assert helpers._clean_text("  hello   world \n") == "hello world"


def test_find_label_value():
    soup = BeautifulSoup("<div>Breed: Terrier</div>", "html.parser")
    assert helpers._find_label_value(soup, "Breed") == "Terrier"


def test_extract_single_rating():
    html = """
    <div class="children">
      <span class="rating_default">
        <span class="active r4"></span>
      </span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert helpers._extract_single_rating(soup, "children") == 4


def test_extract_description():
    html = "<p>short</p><p>This is a long paragraph " + ("x" * 100) + "</p>"
    soup = BeautifulSoup(html, "html.parser")
    desc = helpers._extract_description(soup)
    assert desc is not None
    assert len(desc) > 80


def test_extract_media():
    html = """
    <img src="https://pawschicago.canto.com/direct/image/abc" />
    <video src="/movie.mp4"></video>
    <iframe src="/embed"></iframe>
    <a href="/clip.mov">clip</a>
    """
    soup = BeautifulSoup(html, "html.parser")
    media = helpers._extract_media("https://example.com", soup)
    assert isinstance(media, PetMedia)
    assert any("canto.com" in u for u in media.images)
    assert any(u.endswith(".mp4") for u in media.videos)
    assert any("embed" in u for u in media.embeds)


def test_fetch_links_from_cache(monkeypatch):
    monkeypatch.setattr(
        paws, "get_cached_links", lambda source, ttl, logger=None: ["a", "b"]
    )
    monkeypatch.setattr(
        paws,
        "_get_soup",
        lambda _: (_ for _ in ()).throw(RuntimeError("should not call")),
    )
    assert paws.fetch_adoptable_pet_profile_links_paws(store_in_db=True) == {"a", "b"}


def test_fetch_links_live(monkeypatch):
    html = """
    <a href="/pet-available-for-adoption/showdog/1">Dog 1</a>
    <a href="/pet-available-for-adoption/showdog/2">Dog 2</a>
    """
    monkeypatch.setattr(
        paws, "get_cached_links", lambda source, ttl, logger=None: None
    )
    monkeypatch.setattr(
        paws,
        "_get_soup",
        lambda _: BeautifulSoup(html, "html.parser"),
    )
    stored = {}
    monkeypatch.setattr(
        paws,
        "store_cached_links",
        lambda source, links, logger=None: stored.update(
            {"source": source, "links": links}
        ),
    )
    links = paws.fetch_adoptable_pet_profile_links_paws(store_in_db=True)
    assert len(links) == 2
    assert stored["source"] == paws.SOURCE
    assert stored["links"]


def test_fetch_links_fallback(monkeypatch):
    calls = {"count": 0}

    def fake_cached(source, ttl, logger=None):
        calls["count"] += 1
        return None if calls["count"] == 1 else ["cached"]

    monkeypatch.setattr(paws, "get_cached_links", fake_cached)
    monkeypatch.setattr(
        paws, "_get_soup", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    links = paws.fetch_adoptable_pet_profile_links_paws(store_in_db=True)
    assert links == {"cached"}


def test_fetch_pet_profile_parses_fields(monkeypatch):
    html = """
    <html>
      <title>Buddy | PAWS</title>
      <div>Breed: Labrador</div>
      <div>Gender: Male</div>
      <div>Age: 2 years 3 months</div>
      <div>Weight: 45 lbs</div>
      <div>Location: Chicago</div>
      <div>Status: Available</div>
      <div class="children"><span class="rating_default"><span class="active r5"></span></span></div>
      <p>This is a long description """ + ("x" * 90) + """</p>
    </html>
    """
    monkeypatch.setattr(paws, "_get_soup", lambda _: BeautifulSoup(html, "html.parser"))
    profile = paws.fetch_pet_profile_paws(
        "https://example.com/pet-available-for-adoption/showdog/123"
    )
    assert isinstance(profile, PetProfile)
    assert profile.dog_id == 123
    assert profile.species == "dog"
    assert profile.name == "Buddy"
    assert profile.breed == "Labrador"
    assert profile.gender == "Male"
    assert profile.age_months == 27.0
    assert profile.weight_lbs == 45.0
    assert profile.location == "Chicago"
    assert profile.status == "Available"
    assert profile.ratings.get("children") == 5
