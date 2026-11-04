# Docker — content factory container

## Why containerize

The factory depends on heavy, fragile things: `sentence-transformers` (torch), `playwright` (a real Chromium for the perf gate), a specific Python version. A container freezes code + deps + OS userspace into one portable artifact, so laptop, CI runners, and cluster nodes all run the identical filesystem. "Works on my machine" stops being a category.

## The image (`Dockerfile` at repo root)

- **Base:** `python:3.12-slim` — matches the dev Python version; slim Debian userspace.
- **Layer order:** `requirements.txt` installed *before* code is copied, so code edits reuse the cached dependency layer (rebuilds take seconds).
- **CPU-only torch:** installed from `download.pytorch.org/whl/cpu` first, pinned to the exact wheel (`torch==2.15.0+cpu`) so image rebuilds are reproducible (hadolint DL3013). The default PyPI torch wheel bundles ~2 GB of CUDA libraries the pipeline never uses (`retrieval.device: "cpu"`).
- **trivy-pinned Python packages:** `setuptools==84.2.1 wheel==0.46.2 jaraco.context==6.1.0` after the requirements install. torch pins `setuptools==78.1.0` exactly, and 78.1.0 + its vendored `jaraco.context`/`wheel` copies carry HIGH CVEs; 84.2.1 is clean and vendors the fixed copies. The torch pin conflict is a pip warning only (setuptools is a build-time dep for torch).
- **Playwright:** `playwright install --with-deps chromium` bakes Chromium + its OS libraries into the image; browsers live at `/opt/playwright` (fixed path readable by the non-root user).
- **Non-root:** build runs as root, but `useradd --uid 1000 app` + numeric `USER 1000` makes the container run unprivileged. The numeric form is deliberate: kubelets cannot verify non-root for a named user (gotcha 1 in `kubernetes.md`) and hadolint flags it too (DL3066).
- **`ENV PYTHONPATH=/app`:** Python sets `sys.path[0]` to the *script's* directory, so scripts outside the repo root (e.g. `docker/smoke_test.py`) can't see `factory/` without this. Placed after the pip layer so changing it doesn't invalidate the dependency cache.
- **Default CMD:** `python docker/smoke_test.py` — imports all 19 factory modules, the `pipeline.py` entry point, and the heavy deps. A broken image fails in seconds, locally and in CI.

Image size: ~3.8 GB uncompressed; the pip layer is ~2.7 GB of it. Slimming (e.g. splitting the Playwright perf gate into a separate image) is a known future optimization, not a blocker.

## `.dockerignore`

Excludes `.git`, secrets (`.env*`, `*.key`, `*.pem`), local caches (`runs/`, `sources/pdfs/`, `sources/cache/`), posts/skills media, and Python/Node junk. The runtime-needed files stay: `config.json`, `factory/`, `sources/catalog.json`, `docs/frontend/` (the factory reads the design doctrine at runtime). Result: the `COPY . .` layer is ~217 kB despite a ~100 MB repo.

## Local workflow

```bash
docker build -t zivon-factory:0.3.7 .
docker run --rm zivon-factory:0.3.7                          # smoke test
docker run --rm -it zivon-factory:0.3.7 bash                 # explore inside
docker history zivon-factory:0.3.7                           # per-layer sizes
docker compose run --rm factory python pipeline.py "Motion" --class 9   # full pipeline run
```

`docker-compose.yml` is the local runner: builds the image, passes the server env (`ZIVON_BASE_URL`, `ZIVON_MODEL`, `ZIVON_API_KEY`) from the shell, mounts pipeline **output** (`runs/`, generated pages in `frontend/`) plus download caches (PDFs, text, HuggingFace) as volumes — containers stay disposable while output and caches survive.

## Frontend image (`Dockerfile.frontend`)

The static site ships as its own small nginx image — hosting the frontend is separate from the factory that generates it.

```bash
docker build -f Dockerfile.frontend -t zivon-frontend:0.1.3 .
docker compose up web                                       # serve ./frontend on http://localhost:8081
docker run --rm -p 8081:8080 -v "$PWD/frontend:/usr/share/nginx/html" zivon-frontend:0.1.3
```

- **Base:** `nginxinc/nginx-unprivileged:1.31.7-alpine3.24` — the official non-root nginx variant (UID 101, port 8080), matching the repo's non-root rule. A targeted `apk update && apk upgrade` (as a `USER 0`/`USER 101` sandwich — apk needs root; the final user stays non-root) freshens brotli/curl/libcurl/libexpat to trivy-fixed versions: the base ships a frozen package index from its build date, and the fixes landed after it. nginx itself is not upgraded.
- **Baked:** only the hand-maintained shell — `index.html`, `assets/` (shared CSS/JS, local fonts) and `docker/nginx.conf`. Generated pipeline output (`courses/`, `courses.js`) is **never baked into an image** (repo rule): it arrives at runtime on a mounted volume (compose) or PVC (cluster) at the same html root. The shell is staged at `/opt/zivon-shell` so the served root can be a volume without losing it.
- **Site config:** CSP + `nosniff` + `no-referrer` headers site-wide (topic pages keep their own stricter meta CSP); `no-store` for HTML and `courses.js` (demo-day freshness), 5-min revalidation otherwise; gzip; `/healthz` probe; autoindex off.
- CI builds it, serves it, curls it, and trivy-scans it (`frontend-image` job in `cicd.md`). The CI smoke reproduces the cluster serving path: the html root is a writable tmpfs (the PVC + fsGroup stand-in) seeded from `/opt/zivon-shell` with the same `cp -rn` glob copy the initContainer uses. A bare `docker run` of this image serves nginx's default page — the shell only appears in the root via mount or seed, so a smoke that curls the unseeded image can never see the site.

## Rules

- API keys and all server wiring enter only via environment at runtime (`ZIVON_BASE_URL`, `ZIVON_MODEL`, `ZIVON_API_KEY` — see `.env.example`), never via image or `COPY`.
- Dev-only exception to "no extra images": the **inference router** (`docker/inference-router.Dockerfile`, alpine+socat, `network_mode: host`) bridges the host's loopback-only inference server to containers and cluster pods (`192.168.49.1:18080 → 127.0.0.1:8080`). It is a dev tool: not a product image, not in CI, never deployed to real clusters.
- Version tags: `name:semver` locally; CI will add commit-SHA tags in the registry.
- Any new runtime dependency goes into `requirements.txt` (CI's pip-audit and trivy watch it).
