from puppyping.models import DogMedia, DogProfile


def test_dogmedia_summary_counts():
    media = DogMedia(images=["a", "b"], videos=["v1"], embeds=[])
    assert media.summary() == "2 images, 1 videos, 0 embeds"


def test_dogprofile_str_includes_fields():
    profile = DogProfile(
        dog_id=123,
        url="https://example.com/dog/123",
        name="Fido",
        breed="Terrier",
        gender="Male",
        age_months=6,
        weight_lbs=12.5,
        location="Chicago",
        status="Available",
        ratings={"children": 4, "dogs": 3},
        description="Friendly",
    )
    s = str(profile)
    assert "DogProfile #123" in s
    assert "Fido" in s
    assert "Terrier" in s
    assert "Male" in s
    assert "6" in s
    assert "12.5" in s
    assert "Chicago" in s
    assert "Available" in s
