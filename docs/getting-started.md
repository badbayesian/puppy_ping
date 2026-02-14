# Getting Started

## Compose Modes

- `compose.yml` is the production baseline.
- `compose.dev.yml` is a development override layered on top of `compose.yml`.
- `compose.feature.yml` is an optional feature-stack override (for side-by-side branch testing).

Compose applies files in order, so later files override earlier keys.

## Environment Files

Create env files from templates:

```powershell
cp .env.prod.example .env
cp .env.dev.example .env.dev
```

## Run Production

```powershell
docker compose --env-file .env -f compose.yml up --build -d
```

## Run Development

```powershell
docker compose --env-file .env.dev -f compose.yml -f compose.dev.yml up --build
```

## Run Feature Stack (Optional)

```powershell
docker compose --env-file .env.dev -f compose.yml -f compose.feature.yml up --build -d
```

## Default Ports

Production (`compose.yml`):

- PupSwipe: `8010`
- Postgres: `5433`
- pgAdmin: `5050`

Development (`compose.yml` + `compose.dev.yml`):

- PupSwipe: `8001` (mapped to app port `8010` in container)
- Postgres: `5434`
- pgAdmin: `5051`

## Common Commands

Run one scrape without email:

```powershell
docker compose --env-file .env -f compose.yml run --rm --no-deps -T puppyping python -m puppyping --once --no-email
```

Run tests:

```powershell
python -m pip install -e .[dev]
python -m pytest
```
