from bs4 import BeautifulSoup

import puppyping.providers.wrightway as wrightway


PHOTO_1 = "https://g.petango.com/photos/364/1303e64e-805e-458b-946f-3403468fc47b.jpg"
PHOTO_2 = "https://g.petango.com/photos/364/1c271c4d-933a-4176-816f-a2514ff1a1f6.jpg"
PHOTO_3 = "https://g.petango.com/photos/364/289e9915-a64d-4222-b791-62ee31cc0e65.jpg"

PROFILE_URL = (
    "http://ws.petango.com/webservices/adoptablesearch/"
    "wsAdoptableAnimalDetails.aspx?id=60044823"
)

PROFILE_HTML = f"""
<html>
  <head>
    <title>Animal Details</title>
    <meta property="og:title" content="Meet Paloma" />
    <meta property="og:image" content="https:http://g.petango.com/photos/364/1303e64e-805e-458b-946f-3403468fc47b.jpg" />
    <meta property="og:description" content="A sweet lab mix puppy from Mississippi with a gentle, loving nature. Born to a stray mom at an animal control facility, this puppy arrived alongside siblings and has been growing up surrounded by care and companionship. THANK YOU FOR YOUR INTEREST IN SAVING A LIFE! Volunteers and staff are excited to assist you." />
  </head>
  <body>
    <div id="DefaultLayoutDiv">
      Meet Paloma
      Click a number to change picture or play to see a video:
      [ 1 ] [ 2 ] [ 3 ]
      Animal ID 60044823
      Species Dog
      Breed Retriever, Labrador/Mix
      Gender Female
      Age 3 months 1 day
      Location Murphysboro, IL
      Stage Available
    </div>

    <table>
      <tr><td>Animal ID</td><td>60044823</td></tr>
      <tr><td>Species</td><td>Dog</td></tr>
      <tr><td>Breed</td><td>Retriever, Labrador/Mix</td></tr>
      <tr><td>Age</td><td>3 months 1 day</td></tr>
      <tr><td>Gender</td><td>Female</td></tr>
      <tr><td>Weight</td><td>--</td></tr>
      <tr><td>Location</td><td>Murphysboro, IL</td></tr>
      <tr><td>Stage</td><td>Available</td></tr>
    </table>

    <div id="DescriptionWrapper" class="group">
      <span id="lbDescription">
        A sweet lab mix puppy from Mississippi with a gentle, loving nature.
        Born to a stray mom at an animal control facility, this puppy arrived
        alongside siblings and has been growing up surrounded by care and companionship.
        THANK YOU FOR YOUR INTEREST IN SAVING A LIFE!
        Volunteers and staff are excited to assist you.
      </span>
    </div>

    <img src="../adoptablesearch/images/PetPlaceLogo.png" />
    <img src="{PHOTO_1}" />
    <a href="{PHOTO_1}" onclick="loadPhoto('{PHOTO_1}'); return false;">1</a>
    <a href="{PHOTO_2}" onclick="loadPhoto('{PHOTO_2}'); return false;">2</a>
    <a href="{PHOTO_3}" onclick="loadPhoto('{PHOTO_3}'); return false;">3</a>
    <img src="http://b.scorecardresearch.com/p?c1=2&amp;c2=6745171" />
  </body>
</html>
"""


def test_extract_media_keeps_only_petango_photos():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    media = wrightway._extract_media(soup, PROFILE_URL)

    assert media.images == [PHOTO_1, PHOTO_2, PHOTO_3]
    assert media.videos == []
    assert media.embeds == []


def test_extract_description_trims_petango_footer():
    soup = BeautifulSoup(PROFILE_HTML, "html.parser")
    description = wrightway._extract_description(soup)

    assert description is not None
    assert description.startswith("A sweet lab mix puppy")
    assert "THANK YOU FOR YOUR INTEREST IN SAVING A LIFE!" not in description
    assert "Click a number to change picture or play to see a video" not in description


def test_fetch_pet_profile_wrightway_parses_name_weight_media(monkeypatch):
    wrightway.cache.clear()
    monkeypatch.setattr(
        wrightway, "_get_soup", lambda _: BeautifulSoup(PROFILE_HTML, "html.parser")
    )

    profile = wrightway.fetch_pet_profile_wrightway(PROFILE_URL + "&test=paloma")

    assert profile.dog_id == 60044823
    assert profile.species == "dog"
    assert profile.name == "Paloma"
    assert profile.breed == "Retriever, Labrador/Mix"
    assert profile.gender == "Female"
    assert profile.age_raw == "3 months 1 day"
    assert profile.weight_lbs is None
    assert profile.location == "Murphysboro, IL"
    assert profile.status == "Available"
    assert profile.media.images == [PHOTO_1, PHOTO_2, PHOTO_3]
    assert profile.description is not None
    assert profile.description.startswith("A sweet lab mix puppy")
    assert "THANK YOU FOR YOUR INTEREST IN SAVING A LIFE!" not in profile.description


def test_fetch_pet_profile_wrightway_parses_cat_species(monkeypatch):
    wrightway.cache.clear()
    cat_html = PROFILE_HTML.replace("Species Dog", "Species Cat").replace(
        "<tr><td>Species</td><td>Dog</td></tr>",
        "<tr><td>Species</td><td>Cat</td></tr>",
    )
    monkeypatch.setattr(
        wrightway, "_get_soup", lambda _: BeautifulSoup(cat_html, "html.parser")
    )

    profile = wrightway.fetch_pet_profile_wrightway(PROFILE_URL + "&test=cat")
    assert profile.species == "cat"
