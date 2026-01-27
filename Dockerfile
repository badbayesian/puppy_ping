FROM python:3.12-slim

# Install cron
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scrape.py crontab ./

# Register cron job
RUN crontab crontab

# Persistent cache + logs
VOLUME ["/data", "/var/log"]

CMD ["cron", "-f"]
