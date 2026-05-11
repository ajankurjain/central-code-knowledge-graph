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

# Install deps first for better layer caching
COPY ckg/__init__.py ckg/__init__.py
RUN pip install -e .

# Now copy the rest of the source
COPY ckg ./ckg
COPY tests ./tests

# Pre-create repo cache dir
RUN mkdir -p /var/lib/ckg/repos

EXPOSE 8080

CMD ["uvicorn", "ckg.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
