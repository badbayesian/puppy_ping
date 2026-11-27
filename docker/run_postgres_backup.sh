#!/bin/sh
set -eu

umask 077

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${PGDATABASE:?PGDATABASE is required}"
PGUSER="${PGUSER:?PGUSER is required}"
export PGPASSWORD="${PGPASSWORD:?PGPASSWORD is required}"

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_HOUR="${BACKUP_HOUR:-1}"
BACKUP_MINUTE="${BACKUP_MINUTE:-30}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
BACKUP_ON_STARTUP="${BACKUP_ON_STARTUP:-false}"

mkdir -p "${BACKUP_DIR}"

strip_leading_zeros() {
  stripped="$(printf '%s' "$1" | sed 's/^0*//')"
  printf '%s' "${stripped:-0}"
}

run_backup() {
  tries=0
  until pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "${tries}" -ge 30 ]; then
      echo "[backup] ERROR: Postgres not ready at ${PGHOST}:${PGPORT}" >&2
      return 1
    fi
    sleep 2
  done

  timestamp="$(date +%Y-%m-%d_%H%M%S)"
  tmp_file="${BACKUP_DIR}/${PGDATABASE}_${timestamp}.dump.tmp"
  out_file="${BACKUP_DIR}/${PGDATABASE}_${timestamp}.dump"

  if pg_dump -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" -Fc > "${tmp_file}"; then
    mv "${tmp_file}" "${out_file}"
  else
    rm -f "${tmp_file}"
    return 1
  fi

  find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${PGDATABASE}_*.dump" -mtime +"${BACKUP_RETENTION_DAYS}" -delete
  echo "[backup] wrote ${out_file}"
}

if [ "${1:-}" = "--once" ]; then
  run_backup
  exit $?
fi

sleep_pid=""
cleanup() {
  if [ -n "${sleep_pid}" ]; then
    kill "${sleep_pid}" 2>/dev/null || true
  fi
  exit 0
}
trap cleanup TERM INT

if [ "${BACKUP_ON_STARTUP}" = "true" ]; then
  run_backup || echo "[backup] ERROR: startup backup failed" >&2
fi

target_hour="$(strip_leading_zeros "${BACKUP_HOUR}")"
target_min="$(strip_leading_zeros "${BACKUP_MINUTE}")"
target_sec=$((target_hour * 3600 + target_min * 60))

while true; do
  hour_now="$(strip_leading_zeros "$(date +%H)")"
  min_now="$(strip_leading_zeros "$(date +%M)")"
  sec_now="$(strip_leading_zeros "$(date +%S)")"
  now_sec=$((hour_now * 3600 + min_now * 60 + sec_now))

  sleep_sec=$((target_sec - now_sec))
  if [ "${sleep_sec}" -le 0 ]; then
    sleep_sec=$((sleep_sec + 86400))
  fi

  sleep "${sleep_sec}" &
  sleep_pid=$!
  wait "${sleep_pid}" || true
  sleep_pid=""

  run_backup || echo "[backup] ERROR: scheduled backup failed" >&2
done
