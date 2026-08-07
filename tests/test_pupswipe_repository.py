from datetime import datetime, timezone
from types import SimpleNamespace

import puppyping.pupswipe.repository as repository


class DummyCursor:
    def __init__(self, steps=None):
        self.steps = list(steps or [])
        self.executed = []
        self.description = []
        self.rowcount = 0
        self._next_fetchone = None
        self._next_fetchall = []

    def execute(self, query, params=None):
        self.executed.append((query, params))
        step = self.steps.pop(0) if self.steps else {}
        columns = step.get("columns", [])
        self.description = [SimpleNamespace(name=name) for name in columns]
        self.rowcount = int(step.get("rowcount", 0))
        self._next_fetchone = step.get("fetchone")
        self._next_fetchall = list(step.get("fetchall", []))

    def fetchone(self):
        row = self._next_fetchone
        self._next_fetchone = None
        return row

    def fetchall(self):
        rows = self._next_fetchall
        self._next_fetchall = []
        return rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyConn:
    def __init__(self, steps=None):
        self.cursor_obj = DummyCursor(steps=steps)
        self.commits = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_upsert_user_handles_insert_race_by_locking_existing_row(monkeypatch):
    now = datetime(2026, 3, 8, tzinfo=timezone.utc)
    conn = DummyConn(
        steps=[
            {"fetchone": None},
            {
                "columns": [
                    "id",
                    "email",
                    "password_hash",
                    "created_at_utc",
                    "last_seen_at_utc",
                ],
                "fetchone": (7, "person@example.com", "existing-hash", now, now),
            },
            {
                "columns": ["id", "email", "created_at_utc", "last_seen_at_utc"],
                "fetchone": (7, "person@example.com", now, now),
            },
        ]
    )

    monkeypatch.setattr(
        repository, "hash_password", lambda password: f"hashed:{password}"
    )
    monkeypatch.setattr(
        repository,
        "verify_password",
        lambda password, password_hash: password == "secret123"
        and password_hash == "existing-hash",
    )

    user = repository.upsert_user(
        "person@example.com",
        "secret123",
        connection_factory=lambda: conn,
        ensure_schema_fn=None,
    )

    executed_sql = "\n".join(query for query, _params in conn.cursor_obj.executed)
    assert "ON CONFLICT (email) DO NOTHING" in executed_sql
    assert "FOR UPDATE" in executed_sql
    assert "SET last_seen_at_utc = %s" in executed_sql
    assert user["id"] == 7
    assert user["email"] == "person@example.com"
    assert conn.commits == 1


def test_get_user_by_id_is_read_only(monkeypatch):
    now = datetime(2026, 3, 8, tzinfo=timezone.utc)
    conn = DummyConn(
        steps=[
            {
                "columns": ["id", "email", "created_at_utc", "last_seen_at_utc"],
                "fetchone": (9, "reader@example.com", now, now),
            }
        ]
    )

    user = repository.get_user_by_id(
        9,
        connection_factory=lambda: conn,
        ensure_schema_fn=None,
    )

    assert user["id"] == 9
    assert user["email"] == "reader@example.com"
    assert conn.commits == 0
    assert len(conn.cursor_obj.executed) == 1
    query, params = conn.cursor_obj.executed[0]
    assert "SELECT id, email, created_at_utc, last_seen_at_utc" in query
    assert "UPDATE users" not in query
    assert params == (9,)


def test_fetch_liked_puppies_filters_before_limit_and_offset():
    conn = DummyConn(
        steps=[
            {
                "columns": [
                    "pet_id",
                    "species",
                    "liked_at_utc",
                    "source",
                    "is_active",
                    "url",
                    "name",
                    "breed",
                    "gender",
                    "age_raw",
                    "age_months",
                    "location",
                    "status",
                    "description",
                    "media",
                    "scraped_at_utc",
                ],
                "fetchall": [
                    (
                        11,
                        "cat",
                        "2026-03-08T00:00:00+00:00",
                        "paws_chicago",
                        True,
                        "https://example.com/cats/11",
                        "Mochi",
                        "Domestic Shorthair",
                        "Female",
                        "10 months",
                        10.0,
                        "Chicago, IL",
                        "Available",
                        "Friendly cat",
                        {"images": ["https://example.com/mochi.jpg"]},
                        "2026-03-08T00:00:00+00:00",
                    )
                ],
            }
        ]
    )

    puppies = repository.fetch_liked_puppies(
        user_id=12,
        limit=5,
        offset=10,
        name_filter="mochi",
        species_filter="cat",
        sources=("paws_chicago", "wright_way"),
        connection_factory=lambda: conn,
        ensure_schema_fn=None,
    )

    query, params = conn.cursor_obj.executed[0]
    assert "filtered_likes AS" in query
    assert "FROM filtered_likes" in query
    assert "ORDER BY liked_at_utc DESC, pet_id DESC, species ASC" in query
    assert query.index(
        "WHERE (%s = '' OR COALESCE(liked.species, '') = %s)"
    ) < query.index("LIMIT %s")
    assert params[-2:] == (5, 10)
    assert puppies[0]["pet_id"] == 11
    assert puppies[0]["primary_image"] == "https://example.com/mochi.jpg"
