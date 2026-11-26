# Operations

## Production Tunnel & Debug Overlay

When deploying PupSwipe behind Cloudflare Tunnel on an existing external `tunnel_public` Docker network, attach `compose.tunnel.yml` alongside `compose.yml` (in Portainer **Additional paths**, list `compose.tunnel.yml`) and keep `PUPSWIPE_BIND_IP=127.0.0.1` so the origin is not exposed on the LAN:

```bash
docker compose --env-file .env -f compose.yml -f compose.tunnel.yml up -d --build
```

`pgadmin` and raw host Postgres ports are disabled by default in `compose.yml`. Start `pgadmin` only on demand over localhost/SSH tunnel using the `debug` profile:

```bash
docker compose --env-file .env -f compose.yml --profile debug up -d pgadmin
```

## Scraper Scheduling

The production scraper container runs cron in foreground and schedules jobs internally.

Files:

- `docker/puppyping.cron`
- `docker/run_scrape_cron.sh`

Schedule (`America/Chicago`):

- `@reboot`
- `0 13 * * *` (`1:00 PM`)

Rebuild/restart scraper after cron/runtime changes:

```bash
docker compose --env-file .env -f compose.yml up -d --build puppyping
```

Inspect scraper logs:

```bash
docker logs puppyping-scraper
```

Force a manual run:

```bash
docker exec puppyping-scraper /app/docker/run_scrape_cron.sh
```

## Postgres Backup

Backup script:

- `scripts/backup_postgres.sh`

Default backup location:

- `/mnt/thebutler/data/puppyping/postgres/backups`

Install:

```bash
sudo install -m 700 scripts/backup_postgres.sh /usr/local/bin/puppyping_pg_backup.sh
```

Run once:

```bash
/usr/local/bin/puppyping_pg_backup.sh
```

Daily schedule example (1:30 AM, 30-day retention):

```bash
(crontab -l 2>/dev/null; echo '30 1 * * * /usr/local/bin/puppyping_pg_backup.sh >> /var/log/puppyping_pg_backup.log 2>&1') | crontab -
```

## Recovery Import to Live DB

Use `scripts/recover_live_db_from_available_sources.py` to merge legacy backup data plus
diskcache sqlite data into the live `puppyping` Postgres schema using append + dedupe.

> Note: Production `compose.yml` no longer publishes host port `5433:5432` by default. For host-side recovery runs targeting `127.0.0.1:5433`, add a temporary `127.0.0.1:5433:5432` override (or SSH port forward) before running steps 5–6 and remove it once finished.

1. Ensure share access:

```powershell
net use P: \\THEBUTLER\puppy_ping /persistent:no
```

2. Create a live DB safety backup:

```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
docker exec puppyping-postgres pg_dump -U puppyping -d puppyping -Fc > "\\THEBUTLER\puppy_ping\postgres\backups\live_pre_recovery_$ts.dump"
```

3. Pause app writers/readers:

```powershell
docker stop puppyping-pupswipe puppyping-scraper
```

4. Stage legacy source and run a temporary source DB:

```powershell
$src = "P:\postgres\backups\postgres_data_backup_20260301_210314"
$dst = "C:\temp\puppyping_recovery_source_$ts"
robocopy $src $dst /E /R:1 /W:1
docker run --name puppyping-source-recovery -d -p 55433:5432 -e POSTGRES_PASSWORD=temp -v "${dst.Replace('\','/')}:/var/lib/postgresql/18/docker" postgres:18
```

5. Dry-run:

```powershell
python scripts/recover_live_db_from_available_sources.py --mode dry-run --source-host 127.0.0.1 --source-port 55433 --source-db puppyping --source-user puppyping --source-password puppyping --target-host 127.0.0.1 --target-port 5433 --target-db puppyping --target-user puppyping --target-password puppyping --cache-db "\\THEBUTLER\puppy_ping\cache\paws\cache.db" --cache-db "data/cache/paws/cache.db" --cache-db "data/cache/wright_way/cache.db" --cache-db "data/cache/anti_cruelty/cache.db" --report-path "\\THEBUTLER\puppy_ping\postgres\backups\recovery_dryrun_$ts.json"
```

6. Apply:

```powershell
python scripts/recover_live_db_from_available_sources.py --mode apply --source-host 127.0.0.1 --source-port 55433 --source-db puppyping --source-user puppyping --source-password puppyping --target-host 127.0.0.1 --target-port 5433 --target-db puppyping --target-user puppyping --target-password puppyping --cache-db "\\THEBUTLER\puppy_ping\cache\paws\cache.db" --cache-db "data/cache/paws/cache.db" --cache-db "data/cache/wright_way/cache.db" --cache-db "data/cache/anti_cruelty/cache.db" --report-path "\\THEBUTLER\puppy_ping\postgres\backups\recovery_apply_$ts.json"
```

7. Validate + restart:

```powershell
docker exec puppyping-postgres psql -U puppyping -d puppyping -c "select count(*) from pet_profiles;"
docker exec puppyping-postgres psql -U puppyping -d puppyping -c "select source,count(*) from pet_status group by source order by source;"
docker exec puppyping-postgres psql -U puppyping -d puppyping -c "select source,count(*) from cached_links where is_active=true group by source order by source;"
docker start puppyping-scraper puppyping-pupswipe
docker rm -f puppyping-source-recovery
```

### Rollback

If import results are not acceptable, restore the pre-recovery dump:

```powershell
docker exec -i puppyping-postgres pg_restore -U puppyping -d puppyping -c < "\\THEBUTLER\puppy_ping\postgres\backups\live_pre_recovery_<timestamp>.dump"
```
