FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Real Chromium for live navigation (never a simulated browser).
RUN playwright install --with-deps chromium

COPY ./app ./app
# Tests live in the image so `docker compose exec browser-agent python -m
# pytest -q` works as README §5 states (mirrors the agents service).
COPY ./tests ./tests
COPY ./pytest.ini .

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
