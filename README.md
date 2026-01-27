# PuppyPing

Scrapes adoptable dog profiles from PAWS Chicago.

## Quick start

Create a virtual environment, install deps, and run once:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m puppyping
```

Clear the on-disk cache before running:

```powershell
.\.venv\Scripts\python -m puppyping --clear-cache
```

## Structure

- `puppyping/app.py` — scraping, parsing, caching, and CLI entrypoint.
- `puppyping/models.py` — dataclasses for `DogProfile` and `DogMedia`.
- `puppyping/emailer.py` — email rendering/sending.

## Output

The scraper prints a summary and a few example profiles to stdout. Responses are cached on disk in `.cache/paws/` (TTL 24 hours by default).
