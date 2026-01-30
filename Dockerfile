FROM python:3.12-slim

# Install cron + tini for proper signal handling
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App + cron schedule
COPY app.py crontab /app/
# Entrypoint writes env -> /etc/environment so cron jobs inherit it
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    # Register cron job
    && crontab /app/crontab \
    # Prep persistent dirs
    && mkdir -p /data/cache /data/logs \
    && touch /data/logs/cron.log

# Persist only the app data area (cache/logs/etc.)
VOLUME ["/data"]

# Use tini as PID 1
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
CMD ["cron", "-f"]
