# Docker — content factory container

## Why containerize

The factory depends on heavy, fragile things: `sentence-transformers` (torch), `playwright` (a real Chromium for the perf gate), a specific Python version. A container freezes code + deps + OS userspace into one portable artifact, so laptop, CI runners, and cluster nodes all run the identical filesystem. "Works on my machine" stops being a category.

## The image (`Dockerfile` at repo root)

- **Base:** `python:3.12-slim` — matches the dev Python version; slim Debian userspace.
- **Layer order:** `requirements.txt` installed *before* code is copied, so code edits reuse the cached dependency layer (rebuilds take seconds).
- **CPU-only torch:** installed from `download.pytorch.org/whl/cpu` first. The default PyPI torch wheel bundles ~2 GB of CUDA libraries the pipeline never uses (`retrieval.device: "cpu"`).
- **Playwright:** `playwright install --with-deps chromium` bakes Chromium + its OS libraries into the image; browsers live at `/opt/playwright` (fixed path readable by the non-root user).
- **Non-root:** build runs as root, but `useradd app` + `USER app` makes the container run unprivileged.
- **`ENV PYTHONPATH=/app`:** Python sets `sys.path[0]` to the *script's* directory, so scripts outside the repo root (e.g. `docker/smoke_test.py`) can't see `factory/` without this. Placed after the pip layer so changing it doesn't invalidate the dependency cache.
- **Default CMD:** `python docker/smoke_test.py` — imports all 19 factory modules, the `pipeline.py` entry point, and the heavy deps. A broken image fails in seconds, locally and in CI.

Image size: ~3.8 GB uncompressed; the pip layer is ~2.7 GB of it. Slimming (e.g. splitting the Playwright perf gate into a separate image) is a known future optimization, not a blocker.

## `.dockerignore`

Excludes `.git`, secrets (`.env*`, `*.key`, `*.pem`), local caches (`runs/`, `sources/pdfs/`, `sources/cache/`), posts/skills media, and Python/Node junk. The runtime-needed files stay: `config.json`, `factory/`, `sources/catalog.json`, `docs/frontend/` (the factory reads the design doctrine at runtime). Result: the `COPY . .` layer is ~217 kB despite a ~100 MB repo.

## Local workflow

```bash
docker build -t zivon-factory:0.2.0 .
docker run --rm zivon-factory:0.2.0                          # smoke test
docker run --rm -it zivon-factory:0.2.0 bash                 # explore inside
docker history zivon-factory:0.2.0                           # per-layer sizes
docker compose run --rm factory python pipeline.py "Motion" --class 9   # full pipeline run
```

`docker-compose.yml` is the local runner: builds the image, passes `ZIVON_API_KEY` from the shell, mounts pipeline **output** (`runs/`, generated pages in `frontend/`) plus download caches (PDFs, text, HuggingFace) as volumes — containers stay disposable while output and caches survive.

## Rules

- API keys enter only via environment at runtime (`ZIVON_API_KEY`), never via image or `COPY`.
- Version tags: `name:semver` locally; CI will add commit-SHA tags in the registry.
- Any new runtime dependency goes into `requirements.txt` (CI's pip-audit and trivy watch it).
