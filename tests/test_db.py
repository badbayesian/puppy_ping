from datetime import datetime, timezone, timedelta

import puppyping.db as db
from puppyping.models import DogMedia, DogProfile


class DummyCursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.executemany_calls = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def executemany(self, query, params):
        self.executemany_calls.append((query, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyConn:
    def __init__(self, rows=None):
        self.cursor_obj = DummyCursor(rows=rows)
        self.commits = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, msg):
        self.messages.append(msg)


def test_get_pg_config_defaults(monkeypatch):
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGPORT", raising=False)
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.delenv("PGDATABASE", raising=False)
    cfg = db._get_pg_config()
    assert cfg["host"] == "localhost"
    assert cfg["port"] == 5432
    assert cfg["user"] == "postgres"
    assert cfg["password"] == "postgres"
    assert cfg["dbname"] == "puppyping"


def test_store_profiles(monkeypatch):
    conn = DummyConn()
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    profile = DogProfile(
        dog_id=1,
        url="u",
        name="n",
        media=DogMedia(),
    )
    logger = DummyLogger()
    db.store_profiles([profile], logger=logger)
    assert conn.cursor_obj.executemany_calls
    assert any("Stored 1 profiles." in m for m in logger.messages)


def test_get_cached_links_fresh(monkeypatch):
    fetched_at = datetime.now(timezone.utc)
    conn = DummyConn(rows=[(["a", "b"], fetched_at)])
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    logger = DummyLogger()
    links = db.get_cached_links(60, logger=logger)
    assert links == ["a", "b"]
    assert any("Using cached links" in m for m in logger.messages)


def test_get_cached_links_stale(monkeypatch):
    fetched_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    conn = DummyConn(rows=[(["a"], fetched_at)])
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    logger = DummyLogger()
    links = db.get_cached_links(60, logger=logger)
    assert links is None
    assert any("stale" in m for m in logger.messages)


def test_store_cached_links(monkeypatch):
    conn = DummyConn()
    monkeypatch.setattr(db, "get_connection", lambda: conn)
    logger = DummyLogger()
    db.store_cached_links(["x"], logger=logger)
    assert conn.cursor_obj.executed
    assert any("Stored 1 cached links" in m for m in logger.messages)
