# PuppyPing

Scrapes adoptable dog profiles from PAWS Chicago.

## Quick start

Create a virtual environment, install deps, and run once:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install .
docker compose up -d postgres
.\.venv\Scripts\python -m puppyping --once
```

Clear the on-disk cache before running:

```powershell
.\.venv\Scripts\python -m puppyping --clear-cache
```

Run a single cycle without sending email:

```powershell
.\.venv\Scripts\python -m puppyping --once --no-email
```

Bring up pgAdmin for a UI:

```powershell
docker compose up -d pgadmin
```

Open http://localhost:5050 and log in with `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` from `.env`.
pgAdmin auto-registers the Postgres server; if it does not appear, wipe the pgAdmin volume
(`docker compose down -v`) and start it again.

Healthcheck (verifies DB connectivity + schema):

```powershell
.\.venv\Scripts\python -m puppyping.healthcheck
```

Run the full test suite:

```powershell
.\.venv\Scripts\python -m pip install -e .[dev]
.\.venv\Scripts\python -m pytest
```

Docker defaults to a single run without email. If you want the daily schedule at 1 PM, remove `--once --no-email` from the `puppyping` service command in `compose.yml`.

## Structure

- `puppyping/server.py` - scheduler loop + persistence + email dispatch.
- `puppyping/models.py` - dataclasses for `DogProfile` and `DogMedia`.
- `puppyping/emailer.py` - email rendering/sending.
- `puppyping/db.py` - Postgres persistence + cached links/status.
- `puppyping/providers/` - source-specific scraping (PAWS, Wright-Way) + helpers.
- `puppyping/healthcheck.py` - DB connectivity check.
- `tests/` - pytest suite.

## Output

The scraper prints a summary and stores results in Postgres:
- `dog_profiles` stores historical profile snapshots.
- `cached_links` stores one row per link with `source`, `is_active`, and `last_active_utc`.
- `dog_status` stores current active links per source.

## Delta Updates

Each scrape run performs delta-style updates to the link/status tables:
- `cached_links` uses a stable hash ID (md5 of `link`) and upserts rows. Links in the latest batch are marked active and get `last_active_utc` updated.
- Links not seen in the latest batch for a given `source` are marked inactive (`is_active = false`).
- `dog_status` mirrors the same pattern for “current active links” per source, while `dog_profiles` remains append-only history.

