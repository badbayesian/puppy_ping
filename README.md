# PuppyPing

Scrapes puppy listings from PAWS Chicago and saves snapshots plus images.

## Quick start

Create a virtual environment, install deps, and run once:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m playwright install
.\.venv\Scripts\python -m puppyping --once
```

Create a `.env` from the template and add your Twilio credentials:

```powershell
Copy-Item .env.example .env
```

Run once now and then every 6 hours:

```powershell
.\.venv\Scripts\python -m puppyping
```

Adjust the interval:

```powershell
.\.venv\Scripts\python -m puppyping --interval-hours 4
```

## Output

Data is stored in `data/pawschicago/`:
- `dogs.json` is the latest snapshot.
- `runs/` contains historical run snapshots.
- `images/` contains downloaded puppy images.
