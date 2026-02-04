FROM python:3.12-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY puppyping/ ./puppyping/

RUN pip install --no-cache-dir -U pip \
 && pip install --no-cache-dir .

CMD ["python", "-m", "puppyping"]