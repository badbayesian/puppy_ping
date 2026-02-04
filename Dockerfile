FROM python:3.12-slim AS base
WORKDIR /app

COPY pyproject.toml README.md ./
COPY puppyping/ /app/puppyping/
RUN pip install --no-cache-dir .

VOLUME ["/data"]
CMD ["python", "-m", "puppyping"]

FROM base AS dev
RUN pip install --no-cache-dir .[dev]
CMD ["python", "-m", "puppyping", "--once", "--no-email"]
