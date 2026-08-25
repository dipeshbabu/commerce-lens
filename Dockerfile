FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY commercelens ./commercelens

RUN pip install --upgrade pip && pip install ".[postgres]"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl --fail --silent "http://127.0.0.1:${PORT:-8000}/ready" >/dev/null || exit 1

CMD ["sh", "-c", "uvicorn commercelens.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
