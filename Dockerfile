FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY puppyping/ /app/puppyping/

VOLUME ["/data"]
CMD ["python", "-m", "puppyping"]
