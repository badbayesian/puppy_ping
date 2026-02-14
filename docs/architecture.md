# Architecture

## Container Layout

```mermaid
flowchart LR
  U[Browser]

  subgraph Stack[Docker Containers]
    PS[pupswipe]
    SC[scraper]
    PG[postgres]
    PA[pgadmin]
  end

  U --> PS
  U --> PA
  PS --> PG
  SC --> PG
  PA --> PG
```

## Compose Layering

```mermaid
flowchart TB
  subgraph Prod
    PB[compose.yml]
    PE[.env]
    PS[Prod stack]
    PB --> PS
    PE --> PS
  end

  subgraph Dev
    DB[compose.yml]
    DO[compose.dev.yml]
    DE[.env.dev]
    DM[Layered config]
    DS[Dev stack]
    DB --> DM
    DO --> DM
    DM --> DS
    DE --> DS
  end
```

## Scraper Design

- `puppyping/server.py` drives scrape cycles, persistence, and email dispatch.
- Provider logic is registered in `puppyping/providers/__init__.py`.
- Each provider implements the same contracts:
  - `fetch_adoptable_pet_profile_links_*`
  - `fetch_pet_profile_*`
- `puppyping/db.py` owns schema and data persistence for scraped profiles/status.

## PupSwipe Design

`puppyping/pupswipe/` is split into focused modules:

- `server.py`: HTTP routes and request orchestration
- `config.py`: constants and source/provider config helpers
- `auth.py`: password/session/reset helpers
- `repository.py`: schema setup + DB access for PupSwipe
- `pages.py`: server-rendered HTML
