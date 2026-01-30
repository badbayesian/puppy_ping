#!/bin/sh
set -eu

# Export current env so cron jobs can access it.
# (Cron runs with a minimal environment unless you provide one.)
printenv | sed 's/^\(.*\)$/export \1/g' > /etc/profile.d/container_env.sh
chmod +x /etc/profile.d/container_env.sh

# Also write KEY=VALUE lines to /etc/environment (some cron setups read this)
printenv > /etc/environment

# Start cron in foreground (CMD)
exec "$@"
