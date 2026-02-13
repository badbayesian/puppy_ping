from bs4 import BeautifulSoup

import puppyping.providers.paws as paws


def test_fetch_adoptable_pet_profile_links_paws_includes_multiple_species(monkeypatch):
    html = """
    <a href="/pet-available-for-adoption/showdog/1">Dog</a>
    <a href="/pet-available-for-adoption/showcat/2">Cat</a>
    <a href="/pet-available-for-adoption/showrabbit/3">Rabbit</a>
    <a href="/pet-available-for-adoption/showpet/4">Other</a>
    <a href="/pet-available-for-adoption/not-a-profile/5">Ignore</a>
    """
    monkeypatch.setattr(paws, "_get_soup", lambda _: BeautifulSoup(html, "html.parser"))
    monkeypatch.setattr(paws, "get_cached_links", lambda *args, **kwargs: None)
    monkeypatch.setattr(paws, "store_cached_links", lambda *args, **kwargs: None)

    links = paws.fetch_adoptable_pet_profile_links_paws(store_in_db=False)
    assert "https://www.pawschicago.org/pet-available-for-adoption/showdog/1" in links
    assert "https://www.pawschicago.org/pet-available-for-adoption/showcat/2" in links
    assert "https://www.pawschicago.org/pet-available-for-adoption/showrabbit/3" in links
    assert "https://www.pawschicago.org/pet-available-for-adoption/showpet/4" in links
    assert all("not-a-profile" not in link for link in links)


def test_fetch_pet_profile_paws_parses_species_and_id_from_showcat(monkeypatch):
    paws.cache.clear()
    html = """
    <html>
      <title>Mochi | PAWS</title>
      <div>Breed: Domestic Shorthair</div>
      <div>Gender: Female</div>
      <div>Age: 6 months</div>
      <div>Weight: 8 lbs</div>
      <div>Location: Chicago</div>
      <div>Status: Available</div>
      <div class="grey-bg children clearfix">
        <span class="icon">Children</span>
        <span class="rating_default"><span class="active r4"></span></span>
      </div>
      <div class="light-grey-bg dogs clearfix">
        <span class="icon">Dogs</span>
        <span class="rating_default"><span></span></span>
        UNKNOWN
      </div>
      <div class="grey-bg cats clearfix">
        <span class="icon">Cats</span>
        <span class="rating_default"><span class="active r5"></span></span>
      </div>
      <div class="light-grey-bg enrichment clearfix">
        <span class="icon">Human Sociability</span>
        <span class="rating_default"><span class="active r3"></span></span>
      </div>
      <div class="grey-bg human clearfix">
        <span class="icon">Enrichment</span>
        <span class="rating_default"><span class="active r2"></span></span>
      </div>
      <p>This is a long cat profile description that is intentionally verbose to pass parsing.</p>
    </html>
    """
    monkeypatch.setattr(paws, "_get_soup", lambda _: BeautifulSoup(html, "html.parser"))

    profile = paws.fetch_pet_profile_paws(
        "https://www.pawschicago.org/pet-available-for-adoption/showcat/156549"
    )
    assert profile.pet_id == 156549
    assert profile.dog_id == 156549
    assert profile.species == "cat"
    assert profile.name == "Mochi"
    assert profile.breed == "Domestic Shorthair"
    assert profile.ratings.get("children") == 4
    assert profile.ratings.get("dogs") == 0
    assert profile.ratings.get("cats") == 5
    assert profile.ratings.get("human_sociability") == 3
    assert profile.ratings.get("enrichment") == 2


def test_fetch_pet_profile_paws_parses_species_and_id_from_showdog(monkeypatch):
    paws.cache.clear()
    html = """
    <html>
      <title>Buddy | PAWS</title>
      <div>Breed: Labrador Retriever</div>
      <div>Status: Available</div>
      <p>This is a long dog profile description that is intentionally verbose to pass parsing.</p>
    </html>
    """
    monkeypatch.setattr(paws, "_get_soup", lambda _: BeautifulSoup(html, "html.parser"))

    profile = paws.fetch_pet_profile_paws(
        "https://www.pawschicago.org/pet-available-for-adoption/showdog/156738"
    )
    assert profile.pet_id == 156738
    assert profile.species == "dog"
