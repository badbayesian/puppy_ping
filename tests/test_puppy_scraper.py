from bs4 import BeautifulSoup

import puppyping.puppy_scraper as scraper
from puppyping.models import DogMedia, DogProfile


def test_parse_age_to_months():
    assert scraper._parse_age_to_months("2 years 3 months") == 27.0
    assert scraper._parse_age_to_months("6 months") == 6.0
    assert scraper._parse_age_to_months("1 year") == 12.0
    assert scraper._parse_age_to_months(None) is None


def test_parse_weight_lbs():
    assert scraper._parse_weight_lbs("35 lbs") == 35.0
    assert scraper._parse_weight_lbs("7.5") == 7.5
    assert scraper._parse_weight_lbs(None) is None


def test_clean_text():
    assert scraper._clean_text("  hello   world \n") == "hello world"


def test_find_label_value():
    soup = BeautifulSoup("<div>Breed: Terrier</div>", "html.parser")
    assert scraper._find_label_value(soup, "Breed") == "Terrier"


def test_extract_single_rating():
    html = """
    <div class="children">
      <span class="rating_default">
        <span class="active r4"></span>
      </span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert scraper._extract_single_rating(soup, "children") == 4


def test_extract_description():
    html = "<p>short</p><p>This is a long paragraph " + ("x" * 100) + "</p>"
    soup = BeautifulSoup(html, "html.parser")
    desc = scraper._extract_description(soup)
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
    media = scraper._extract_media("https://example.com", soup)
    assert isinstance(media, DogMedia)
    assert any("canto.com" in u for u in media.images)
    assert any(u.endswith(".mp4") for u in media.videos)
    assert any("embed" in u for u in media.embeds)


def test_fetch_links_from_cache(monkeypatch):
    monkeypatch.setattr(scraper, "get_cached_links", lambda ttl, logger=None: ["a", "b"])
    monkeypatch.setattr(scraper, "_get_soup", lambda _: (_ for _ in ()).throw(RuntimeError("should not call")))
    assert scraper.fetch_adoptable_dog_profile_links() == {"a", "b"}


def test_fetch_links_live(monkeypatch):
    html = """
    <a href="/pet-available-for-adoption/showdog/1">Dog 1</a>
    <a href="/pet-available-for-adoption/showdog/2">Dog 2</a>
    """
    monkeypatch.setattr(scraper, "get_cached_links", lambda ttl, logger=None: None)
    monkeypatch.setattr(
        scraper,
        "_get_soup",
        lambda _: BeautifulSoup(html, "html.parser"),
    )
    stored = {}
    monkeypatch.setattr(scraper, "store_cached_links", lambda links, logger=None: stored.update({"links": links}))
    links = scraper.fetch_adoptable_dog_profile_links()
    assert len(links) == 2
    assert stored["links"]


def test_fetch_links_fallback(monkeypatch):
    calls = {"count": 0}

    def fake_cached(ttl, logger=None):
        calls["count"] += 1
        return None if calls["count"] == 1 else ["cached"]

    monkeypatch.setattr(scraper, "get_cached_links", fake_cached)
    monkeypatch.setattr(scraper, "_get_soup", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    links = scraper.fetch_adoptable_dog_profile_links()
    assert links == {"cached"}


def test_fetch_dog_profile_parses_fields(monkeypatch):
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
    monkeypatch.setattr(scraper, "_get_soup", lambda _: BeautifulSoup(html, "html.parser"))
    profile = scraper.fetch_dog_profile("https://example.com/pet-available-for-adoption/showdog/123")
    assert isinstance(profile, DogProfile)
    assert profile.dog_id == 123
    assert profile.name == "Buddy"
    assert profile.breed == "Labrador"
    assert profile.gender == "Male"
    assert profile.age_months == 27.0
    assert profile.weight_lbs == 45.0
    assert profile.location == "Chicago"
    assert profile.status == "Available"
    assert profile.ratings.get("children") == 5
