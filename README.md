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

Healthcheck (verifies DB connectivity + schema):

```powershell
.\.venv\Scripts\python -m puppyping.healthcheck
```

## Structure

- `puppyping/puppy_scraper.py` — scraping, parsing, and caching.
- `puppyping/server.py` — scheduler loop + persistence + email dispatch.
- `puppyping/models.py` — dataclasses for `DogProfile` and `DogMedia`.
- `puppyping/emailer.py` — email rendering/sending.
- `puppyping/db.py` — Postgres persistence + cached links.
- `puppyping/healthcheck.py` — DB connectivity check.

## Output

The scraper prints a summary and stores results in Postgres. Adoptable links are cached in Postgres, and dog profiles are saved in `dog_profiles`.
