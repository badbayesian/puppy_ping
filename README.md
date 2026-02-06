# PuppyPing

Scrapes adoptable dog profiles from a couple different Dog adoption centers in Chicago

## Quick start

### Run locally (recommended for development)

1. Create/activate a virtual environment and install deps:

```powershell
python -m venv .puppyping
python -m pip install -e .[dev]
```

2. Update `puppy_ping/.env` with your info. Note that this repo uses gmail for smtp.

```env
# Email configuration
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=465
EMAIL_USER=YOUR_EMAIL_USER
EMAIL_PASS=YOUR_EMAIL_PASS
EMAIL_FROM="Puppy Ping <YOUR_EMAIL_USER>"
EMAILS_TO=YOUR_EMAILS_COMMA_SEPARATED

# Postgres (docker-compose)
PGHOST=postgres
PGPORT=5432
PGUSER=puppyping
PGPASSWORD=puppyping
PGDATABASE=puppyping

# pgAdmin
PGADMIN_DEFAULT_EMAIL=YOUR_PGADMIN_EMAIL
# Escape $ so docker compose doesn't interpolate. Actual password can include a single $.
PGADMIN_DEFAULT_PASSWORD=YOUR_PGADMIN_PASSWORD
```

3. Run a single scrape cycle:

```powershell
python -m puppyping --once --no-storage
```

### Run with Docker

Build and run the full stack (app + Postgres):

```powershell
docker compose up --build
```

By default the container runs a single cycle without email. If you want the daily schedule at 1 PM,
remove `--once --no-email` from the `puppyping` service command in `compose.yml` and restart the stack.

## PupSwipe (WIP)

PupSwipe is a lightweight web UI for browsing the latest scraped dogs and recording left/right swipes.
It reads from the same Postgres database as `puppyping`, so run a scrape at least once before opening it.

### Run PupSwipe locally

```powershell
python -m puppyping.pupswipe.server --host 127.0.0.1 --port 8000
```

Open http://localhost:8000.

### Run PupSwipe with Docker

The `pupswipe` service is included in `compose.yml`:

```powershell
docker compose up --build pupswipe
```

Open http://localhost:8000.

### PupSwipe API

PupSwipe exposes a small JSON API:
- `GET /api/puppies?limit=40` returns the latest unique dogs.
- `POST /api/swipes` stores a swipe with `{ "dog_id": 123, "swipe": "left|right", "source": "paws" }`.
- `GET /api/health` verifies DB connectivity.

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


Run the full test suite:

```powershell
python -m pip install -e .[dev]
python -m pytest
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
