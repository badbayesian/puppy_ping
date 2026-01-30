FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire package + crontab
COPY puppyping/ /app/puppyping/
COPY crontab /app/

# Register cron job
RUN crontab /app/crontab \
    && mkdir -p /data/cache /data/logs \
    && touch /data/logs/cron.log

VOLUME ["/data"]

CMD ["cron", "-f"]
