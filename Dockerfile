FROM python:3.12-slim
WORKDIR /app

ARG APP_GIT_COMMIT=unknown
ARG APP_GIT_BRANCH=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_GIT_COMMIT=${APP_GIT_COMMIT} \
    APP_GIT_BRANCH=${APP_GIT_BRANCH}

RUN apt-get update \
 && apt-get install --no-install-recommends -y cron tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY puppyping/ ./puppyping/
COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY docker/puppyping.cron /etc/cron.d/puppyping
COPY docker/run_scrape_cron.sh /app/docker/run_scrape_cron.sh

RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir . \
 && date -u +"%Y-%m-%dT%H:%M:%SZ" > /app/.build_updated_at_utc \
 && chmod +x /usr/local/bin/docker-entrypoint.sh /app/docker/run_scrape_cron.sh \
 && chmod 0644 /etc/cron.d/puppyping

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["cron", "-f"]
