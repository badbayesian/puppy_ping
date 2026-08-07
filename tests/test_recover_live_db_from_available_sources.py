import importlib.util
import pickle
import sqlite3
from pathlib import Path

from puppyping.models import PetMedia, PetProfile

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "recover_live_db_from_available_sources.py"
)
SPEC = importlib.util.spec_from_file_location(
    "recover_live_db_from_available_sources", SCRIPT_PATH
)
RECOVER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RECOVER)


def test_infer_species_from_link():
    assert RECOVER.infer_species_from_link("https://x/showcat/12") == "cat"
    assert RECOVER.infer_species_from_link("https://x/showdog/12") == "dog"
    assert RECOVER.infer_species_from_link("https://x/anything") == "unknown"


def test_function_source_mappings():
    assert (
        RECOVER.infer_source_from_profile_function("fetch_dog_profile")
        == "paws_chicago"
    )
    assert (
        RECOVER.infer_source_from_profile_function("fetch_pet_profile_wrightway")
        == "wright_way"
    )
    assert (
        RECOVER.infer_source_from_link_function(
            "fetch_adoptable_pet_profile_links_anti_cruelty"
        )
        == "anti_cruelty"
    )
    assert RECOVER.infer_source_from_profile_function("unknown_fn") is None
    assert RECOVER.infer_source_from_link_function("unknown_fn") is None


def test_extract_cache_db_parses_profile_and_linkset_and_skips_invalid(tmp_path):
    cache_db = tmp_path / "cache.db"
    conn = sqlite3.connect(str(cache_db))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE Cache (key BLOB NOT NULL, value BLOB NOT NULL, store_time REAL NOT NULL)"
    )

    profile = PetProfile(
        dog_id=123,
        url="https://www.pawschicago.org/pet-available-for-adoption/showdog/123",
        species="dog",
        name="Milo",
        media=PetMedia(),
        scraped_at_utc="",  # force fallback to sqlite store_time
    )
    cur.execute(
        "INSERT INTO Cache (key, value, store_time) VALUES (?, ?, ?)",
        (
            pickle.dumps(("fetch_pet_profile_paws", ("url",), ())),
            pickle.dumps(profile),
            1700000000.0,
        ),
    )
    cur.execute(
        "INSERT INTO Cache (key, value, store_time) VALUES (?, ?, ?)",
        (
            pickle.dumps(("fetch_adoptable_pet_profile_links_wrightway", (), ())),
            pickle.dumps(
                {
                    "https://example.com/wsAdoptableAnimalDetails.aspx?id=1",
                    "https://example.com/showcat/44",
                }
            ),
            1700000100.0,
        ),
    )
    cur.execute(
        "INSERT INTO Cache (key, value, store_time) VALUES (?, ?, ?)",
        (b"not-a-pickle", b"still-not-a-pickle", 1700000200.0),
    )
    conn.commit()
    conn.close()

    acc = RECOVER.Accumulator()
    warnings: list[str] = []
    stats = RECOVER.extract_cache_db(cache_db, acc, warnings)

    assert warnings == []
    assert stats["cache_rows_total"] == 3
    assert stats["cache_rows_pickled"] == 2
    assert stats["cache_rows_invalid_pickle"] == 1
    assert stats["cache_profile_rows"] == 1
    assert stats["cache_linkset_rows"] == 1

    assert len(acc.pet_profiles) == 1
    profile_row = next(iter(acc.pet_profiles.values()))
    assert profile_row["pet_id"] == 123
    assert profile_row["species"] == "dog"
    assert profile_row["scraped_at_utc"] == RECOVER.to_dt(1700000000.0)

    links = {row["link"] for row in acc.cached_links.values()}
    assert "https://www.pawschicago.org/pet-available-for-adoption/showdog/123" in links
    assert "https://example.com/wsAdoptableAnimalDetails.aspx?id=1" in links

    cat_status_rows = [
        row
        for row in acc.pet_status.values()
        if row["link"] == "https://example.com/showcat/44"
    ]
    assert len(cat_status_rows) == 1
    assert cat_status_rows[0]["species"] == "cat"
