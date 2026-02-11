#!/bin/sh
set -eu

# Cron jobs load runtime env from /proc/1/environ in run_scrape_cron.sh.
exec "$@"
