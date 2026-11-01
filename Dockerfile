# syntax=docker/dockerfile:1
# Zivon content factory image.
#   Build:  docker build -t zivon-factory:0.1.0 .
#   Smoke:  docker run --rm zivon-factory:0.1.0

FROM python:3.12-slim

# Python writes logs immediately (critical inside containers) and skips .pyc files.
# Playwright browsers and HuggingFace models live in fixed, non-home paths so the
# app user (below) and any mounted volume can reach them.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

# Install dependencies BEFORE copying code.
# Docker caches each instruction as a layer: as long as requirements.txt is
# unchanged, rebuilding after a code edit reuses this (slow) layer instantly.
COPY requirements.txt .
# CPU-only torch first: the default PyPI torch wheel bundles CUDA libraries this
# pipeline never uses (config: retrieval.device=cpu). Saves ~2 GB in the image.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /opt/playwright

# Copy the rest of the repo. .dockerignore decides what actually lands here.
COPY . .

# Never run as root: create a plain user and hand it the app directory.
RUN useradd --create-home app \
    && mkdir -p /app/runs /app/sources/pdfs /app/sources/cache /app/.cache/huggingface \
    && chown -R app:app /app
USER app

# Python sets sys.path[0] to the *script's* directory, so a script in docker/
# cannot see the factory/ package at /app without this. Placed here (after the
# slow pip layer) so changing it doesn't invalidate the dependency cache.
ENV PYTHONPATH=/app

# Default command: import-everything smoke test (CI will reuse this).
# Override at runtime once pipeline.py exists, e.g.:
#   docker run --rm -e ZIVON_API_KEY zivon-factory:0.1.0 python pipeline.py "Motion" --class 9
CMD ["python", "docker/smoke_test.py"]
