#!/usr/bin/env bash
set -euo pipefail

# Daily logical backup for PuppyPing Postgres.
# Defaults are aligned to compose.yml + .env production values.
CONTAINER_NAME="${CONTAINER_NAME:-puppyping-postgres}"
DB_NAME="${DB_NAME:-puppyping}"
DB_USER="${DB_USER:-puppyping}"
BACKUP_ROOT="${BACKUP_ROOT:-/mnt/thebutler/data/puppyping/postgres}"
BACKUP_DIR="${BACKUP_ROOT}/backups"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but was not found in PATH." >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
  echo "Container '${CONTAINER_NAME}' is not running." >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
umask 077

timestamp="$(date +%Y-%m-%d_%H%M%S)"
tmp_file="${BACKUP_DIR}/${DB_NAME}_${timestamp}.dump.tmp"
out_file="${BACKUP_DIR}/${DB_NAME}_${timestamp}.dump"

docker exec "${CONTAINER_NAME}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" -Fc > "${tmp_file}"
mv "${tmp_file}" "${out_file}"

# Keep most recent backups only.
find "${BACKUP_DIR}" -type f -name '*.dump' -mtime +"${RETENTION_DAYS}" -delete

echo "Backup written: ${out_file}"
