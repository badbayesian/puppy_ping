import json

from bs4 import BeautifulSoup

import puppyping.providers.anti_cruelty as anti_cruelty


def test_extract_embed_configs_parses_multiple_queries():
    html = """
    <html>
      <body>
        <script>
          var sourceDomain="https://new.shelterluv.com";
          var base_path="";
          var GID = 100000846;
          var filters = {"defaultSort":"random"};
          EmbedAvailablePets("one", GID, filters, 1, sourceDomain, base_path, 2);
        </script>
        <script>
          var sourceDomain="https://new.shelterluv.com";
          var base_path="";
          var GID = 100000846;
          var filters = {"saved_query":13789};
          EmbedAvailablePets("two", GID, filters, 1, sourceDomain, base_path, 2);
        </script>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")

    configs = anti_cruelty._extract_embed_configs(soup)

    assert configs == [
        ("https://new.shelterluv.com", 100000846, {"defaultSort": "random"}),
        ("https://new.shelterluv.com", 100000846, {"saved_query": 13789}),
    ]


def test_fetch_live_links_queries_all_configs(monkeypatch):
    html = """
    <html>
      <body>
        <script>
          var sourceDomain="https://new.shelterluv.com";
          var base_path="";
          var GID = 100000846;
          var filters = {"defaultSort":"random"};
          EmbedAvailablePets("one", GID, filters, 1, sourceDomain, base_path, 2);
        </script>
        <script>
          var sourceDomain="https://new.shelterluv.com";
          var base_path="";
          var GID = 100000846;
          var filters = {"saved_query":13789};
          EmbedAvailablePets("two", GID, filters, 1, sourceDomain, base_path, 2);
        </script>
      </body>
    </html>
    """
    monkeypatch.setattr(
        anti_cruelty, "_get_soup", lambda _: BeautifulSoup(html, "html.parser")
    )

    def fake_fetch_animals(source_domain: str, shelter_id: int, filters: dict):
        assert source_domain == "https://new.shelterluv.com"
        assert shelter_id == 100000846
        if filters == {"defaultSort": "random"}:
            return [
                {
                    "public_url": "https://new.shelterluv.com/embed/animal/ACIL-A-111",
                    "adoptable": 1,
                },
                {
                    "public_url": "https://new.shelterluv.com/embed/animal/ACIL-A-222",
                    "adoptable": 1,
                },
            ]
        return [
            {
                "public_url": "https://new.shelterluv.com/embed/animal/ACIL-A-222",
                "adoptable": 1,
            },
            {
                "public_url": "https://new.shelterluv.com/embed/animal/ACIL-A-333",
                "adoptable": 0,
            },
            {
                "uniqueId": "ACIL-A-444",
                "adoptable": 1,
            },
        ]

    monkeypatch.setattr(anti_cruelty, "_fetch_animals_for_config", fake_fetch_animals)

    links = anti_cruelty._fetch_live_links()

    assert links == {
        "https://new.shelterluv.com/embed/animal/ACIL-A-111",
        "https://new.shelterluv.com/embed/animal/ACIL-A-222",
        "https://new.shelterluv.com/embed/animal/ACIL-A-444",
    }


def test_fetch_pet_profile_anti_cruelty_parses_fields(monkeypatch):
    anti_cruelty.cache.clear()
    animal_payload = {
        "nid": 212845038,
        "name": "Lucky",
        "uniqueId": "ACIL-A-48065",
        "sex": "Male",
        "location": "Dog Adopts, Run 10",
        "weight": 42,
        "weight_units": "lbs",
        "weight_group": "Large (60-99)",
        "birthday": "",
        "age_group": {
            "name": "Adult Dog",
            "name_with_duration": "Adult Dog (5 months-8 years)",
            "age_from": 5,
            "from_unit": "months",
            "age_to": 8,
            "to_unit": "years",
        },
        "species": "Dog",
        "breed": "Terrier, Pit Bull",
        "secondary_breed": "",
        "attributes": ["Kids 6+"],
        "photos": [
            {
                "id": 2,
                "url": "https://example.com/b.jpg",
                "order_column": 2,
            },
            {
                "id": 1,
                "url": "https://example.com/a.jpg",
                "order_column": 1,
            },
        ],
        "videos": [{"id": 3, "url": "https://example.com/v.mp4"}],
        "adoptable": 1,
        "kennel_description": "<p>Very sweet and loves belly rubs.</p>",
    }
    payload_json = json.dumps(animal_payload)
    html = (
        "<html><body><iframe-animal :animal='"
        + payload_json
        + "'></iframe-animal></body></html>"
    )
    monkeypatch.setattr(
        anti_cruelty, "_get_soup", lambda _: BeautifulSoup(html, "html.parser")
    )

    profile = anti_cruelty.fetch_pet_profile_anti_cruelty(
        "https://new.shelterluv.com/embed/animal/ACIL-A-48065?test=lucky"
    )

    assert profile.dog_id == 48065
    assert profile.species == "dog"
    assert profile.name == "Lucky"
    assert profile.breed == "Terrier, Pit Bull"
    assert profile.gender == "Male"
    assert profile.age_raw == "Adult Dog (5 months-8 years)"
    assert profile.age_months == 96.0
    assert profile.weight_lbs == 42.0
    assert profile.location == "Dog Adopts, Run 10"
    assert profile.status == "Available"
    assert profile.description == "Very sweet and loves belly rubs."
    assert profile.media.images == ["https://example.com/a.jpg", "https://example.com/b.jpg"]
    assert profile.media.videos == ["https://example.com/v.mp4"]


def test_fetch_pet_profile_anti_cruelty_prefers_birthday_for_age_raw(monkeypatch):
    anti_cruelty.cache.clear()
    animal_payload = {
        "nid": 212845039,
        "name": "Saga",
        "uniqueId": "ACIL-A-3650",
        "sex": "Male",
        "location": "Dog Adopts",
        "weight": 55,
        "birthday": 1693630800,
        "age_group": {
            "name": "Adult Dog",
            "name_with_duration": "Adult Dog (5 months-8 years)",
            "age_from": 5,
            "from_unit": "months",
            "age_to": 8,
            "to_unit": "years",
        },
        "species": "Dog",
        "breed": "Shepherd, German",
        "photos": [],
        "videos": [],
        "adoptable": 1,
        "kennel_description": "",
    }
    payload_json = json.dumps(animal_payload)
    html = (
        "<html><body><iframe-animal :animal='"
        + payload_json
        + "'></iframe-animal></body></html>"
    )
    monkeypatch.setattr(
        anti_cruelty, "_get_soup", lambda _: BeautifulSoup(html, "html.parser")
    )

    profile = anti_cruelty.fetch_pet_profile_anti_cruelty(
        "https://new.shelterluv.com/embed/animal/ACIL-A-3650"
    )

    assert profile.age_months is not None
    assert profile.age_raw != "Adult Dog (5 months-8 years)"
    assert profile.age_raw == anti_cruelty._age_raw_from_age_months(profile.age_months)
