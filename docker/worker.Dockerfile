FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel

COPY ckg/__init__.py ckg/__init__.py
RUN pip install -e '.[server]'

COPY ckg ./ckg

RUN mkdir -p /var/lib/ckg/repos

CMD ["celery", "-A", "ckg.worker.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
