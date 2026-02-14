#!/bin/sh
set -eu

BUILD_UPDATED_AT="$(cat /app/.build_updated_at_utc 2>/dev/null || echo unknown)"
STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "[startup] started_at_utc=${STARTED_AT} updated_at_utc=${BUILD_UPDATED_AT} git_branch=${APP_GIT_BRANCH:-unknown} git_commit=${APP_GIT_COMMIT:-unknown}"

# Cron jobs load runtime env from /proc/1/environ in run_scrape_cron.sh.
exec "$@"
