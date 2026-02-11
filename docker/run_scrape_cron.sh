#!/bin/sh
set -eu

# Export selected runtime vars from PID 1 environment so cron jobs use the
# same DB/email configuration as the container.
for key in \
  TZ \
  LOG_LEVEL \
  EMAIL_HOST \
  EMAIL_PORT \
  EMAIL_USER \
  EMAIL_PASS \
  EMAIL_FROM \
  EMAILS_TO \
  PGHOST \
  PGPORT \
  PGDATABASE \
  PGUSER \
  PGPASSWORD
do
  env_line="$(tr '\0' '\n' < /proc/1/environ | awk -F= -v k="$key" '$1 == k { print; exit }')"
  if [ -n "$env_line" ]; then
    export "$env_line"
  fi
done

cd /app
python -m puppyping --once
