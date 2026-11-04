# syntax=docker/dockerfile:1
# Zivon content factory image.
#   Build:  docker build -t zivon-factory:0.3.7 .
#   Smoke:  docker run --rm zivon-factory:0.3.7

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
# The third pip line is the trivy HIGH gate: torch pins setuptools==78.1.0
# exactly, but 78.1.0 and its VENDORED jaraco.context/wheel copies carry HIGH
# CVEs. setuptools 84.2.1 is clean and vendors the fixed jaraco.context 6.1.0 +
# wheel 0.46.3; the top-level pins cover base-image drift too. The torch pin
# conflict is a pip warning only - torch uses setuptools at build time, not at
# runtime.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.15.0+cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir setuptools==84.2.1 wheel==0.46.2 jaraco.context==6.1.0 \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /opt/playwright

# Copy the rest of the repo. .dockerignore decides what actually lands here.
COPY . .

# Never run as root: create a plain user and hand it the app directory.
# Fixed UID + numeric USER: a named USER cannot be verified non-root by kubelets
# (deployment gotcha 1) and is flagged by hadolint (DL3066).
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/runs /app/sources/pdfs /app/sources/cache /app/.cache/huggingface \
    && chown -R app:app /app
USER 1000

# Python sets sys.path[0] to the *script's* directory, so a script in docker/
# cannot see the factory/ package at /app without this. Placed here (after the
# slow pip layer) so changing it doesn't invalidate the dependency cache.
ENV PYTHONPATH=/app

# Default command: import-everything smoke test (CI will reuse this).
# Override at runtime for a real pipeline run, e.g.:
#   docker run --rm -e ZIVON_BASE_URL -e ZIVON_MODEL -e ZIVON_API_KEY \
#     zivon-factory:0.2.1 python pipeline.py "Motion" --class 9
CMD ["python", "docker/smoke_test.py"]
