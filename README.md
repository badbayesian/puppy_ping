# PuppyPing

PuppyPing scrapes adoptable pet profiles into Postgres and serves `PupSwipe`, a web UI/API for browsing pets and recording likes/nope actions.

## Documentation

For better organization, detailed docs are now split by topic under `docs/`:

- [`docs/README.md`](docs/README.md): documentation index
- [`docs/getting-started.md`](docs/getting-started.md): setup, compose modes, ports, and common commands
- [`docs/architecture.md`](docs/architecture.md): system architecture and module layout
- [`docs/pupswipe.md`](docs/pupswipe.md): PupSwipe routes, auth/reset flows, and filters
- [`docs/operations.md`](docs/operations.md): scheduler and backup operations
- [`docs/database_schema.md`](docs/database_schema.md): Postgres schema and relationships

## Quick Start

1. Copy env templates:

```powershell
cp .env.prod.example .env
cp .env.dev.example .env.dev
```

2. Run production stack:

```powershell
docker compose --env-file .env -f compose.yml up --build -d
```

3. Run development stack:

```powershell
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml up --build
```

## Defaults

- Scraper sources: `paws_chicago`, `wright_way`
- PupSwipe sources (override with `PUPSWIPE_SOURCES`): `paws_chicago`, `wright_way`
- Swipe mapping: `right = Like`, `left = Nope`
- PupSwipe UI filter default: max age `8` months

## Service Access

- Prod PupSwipe: `http://<host-or-domain>:8010` (default)
- Dev PupSwipe: `http://127.0.0.1:8001` (default)
- Prod pgAdmin: `http://localhost:5050`
- Dev pgAdmin: `http://localhost:5051`

## Key Paths

- `docker/puppyping.cron`: production cron schedule for scraper runs
- `docker/run_scrape_cron.sh`: cron task runner that executes one scrape cycle
- `scripts/backup_postgres.sh`: daily Postgres backup helper
- `tests/`: pytest suite
