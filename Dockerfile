FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY commercelens ./commercelens

RUN pip install --upgrade pip && pip install -e ".[postgres]"

EXPOSE 8000

CMD ["sh", "-c", "uvicorn commercelens.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
