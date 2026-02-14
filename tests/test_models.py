from puppyping.models import DogMedia, DogProfile, PetMedia, PetProfile, PetsProfile


def test_petmedia_summary_counts():
    media = PetMedia(images=["a", "b"], videos=["v1"], embeds=[])
    assert media.summary() == "2 images, 1 videos, 0 embeds"


def test_petprofile_str_includes_fields():
    profile = PetProfile(
        dog_id=123,
        url="https://example.com/dog/123",
        species="dog",
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
    assert "PetProfile #123 (dog)" in s
    assert "Species    : dog" in s
    assert "Fido" in s
    assert "Terrier" in s
    assert "Male" in s
    assert "6" in s
    assert "12.5" in s
    assert "Chicago" in s
    assert "Available" in s


def test_petprofile_supports_cat_species_and_pet_id_alias():
    profile = PetProfile(
        dog_id=456,
        url="https://example.com/cat/456",
        species="CAT",
        name="Mochi",
    )
    assert profile.species == "cat"
    assert profile.pet_id == 456
    assert "PetProfile #456 (cat)" in str(profile)


def test_legacy_aliases_resolve_to_petprofile():
    assert DogMedia is PetMedia
    assert DogProfile is PetProfile
    assert PetsProfile is PetProfile
