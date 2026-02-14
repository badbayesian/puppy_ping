# Operations

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
