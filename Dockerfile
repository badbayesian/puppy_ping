FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml README.md ./
COPY puppyping/ /app/puppyping/
RUN pip install --no-cache-dir .

VOLUME ["/data"]
CMD ["python", "-m", "puppyping"]
