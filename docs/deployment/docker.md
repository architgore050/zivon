# Docker — content factory container

## Why containerize

The factory depends on heavy, fragile things: `sentence-transformers` (torch), `playwright` (a real Chromium for the perf gate), a specific Python version. A container freezes code + deps + OS userspace into one portable artifact, so laptop, CI runners, and cluster nodes all run the identical filesystem. "Works on my machine" stops being a category.

## The image (`Dockerfile` at repo root)

- **Base:** `python:3.12-slim` — matches the dev Python version; slim Debian userspace.
- **OS-layer freshening:** `apt-get update && apt-get upgrade -y --no-install-recommends` (then clean + drop the lists) runs before the pip layer. The base freezes its apt index at build date, so security fixes published afterwards are invisible: the newest `3.12-slim` build (2026-11-08) still ships zlib1g `1:1.3.dfsg+really1.3.1-1+b1`, which trivy flags HIGH with fixes out (CVE-2026-85091, CVE-2026-76844). Whole-tree and unpinned on purpose — Debian drops old point revisions from the archive, so pins rot. `Dockerfile.llm-manager` carries the same layer for the same reason.
- **Layer order:** `requirements.txt` installed *before* code is copied, so code edits reuse the cached dependency layer (rebuilds take seconds).
- **CPU-only torch:** installed from `download.pytorch.org/whl/cpu` first, pinned to the exact wheel (`torch==2.15.0+cpu`) so the Python-dependency layer of a rebuild is reproducible (hadolint DL3013); the OS layer above it is deliberately unpinned, so a rebuild is package-fresh rather than bit-identical. The default PyPI torch wheel bundles ~2 GB of CUDA libraries the pipeline never uses (`retrieval.device: "cpu"`).
- **trivy-pinned Python packages:** `setuptools==84.2.1 wheel==0.46.2 jaraco.context==6.1.0` after the requirements install. torch pins `setuptools==78.1.0` exactly, and 78.1.0 + its vendored `jaraco.context`/`wheel` copies carry HIGH CVEs; 84.2.1 is clean and vendors the fixed copies. The torch pin conflict is a pip warning only (setuptools is a build-time dep for torch).
- **Playwright:** `playwright install --with-deps chromium` bakes Chromium + its OS libraries into the image; browsers live at `/opt/playwright` (fixed path readable by the non-root user). **libatomic1 gotcha (2026-11-10):** `playwright>=1.45` floats, and playwright ≥1.65's bundled Node driver links `libatomic.so.1`, which slim does not ship — and `playwright install --with-deps` must run the driver BEFORE it can enumerate its own apt deps, so the whole RUN died with exit 127 (`libatomic.so.1: cannot open shared object file`). Fix: `libatomic1` is installed explicitly in the apt layer above (works at any playwright version), and the playwright step is its own `RUN` layer so a playwright-side failure does not re-download the pip wheels layer.
- **Non-root:** build runs as root, but `useradd --uid 1000 app` + numeric `USER 1000` makes the container run unprivileged. The numeric form is deliberate: kubelets cannot verify non-root for a named user (gotcha 1 in `kubernetes.md`) and hadolint flags it too (DL3066).
- **`ENV PYTHONPATH=/app`:** Python sets `sys.path[0]` to the *script's* directory, so scripts outside the repo root (e.g. `docker/smoke_test.py`) can't see `factory/` without this. Placed after the pip layer so changing it doesn't invalidate the dependency cache.
- **Default CMD:** `python docker/smoke_test.py` — imports all 19 factory modules, the `pipeline.py` entry point, and the heavy deps. A broken image fails in seconds, locally and in CI.

Image size: ~3.8 GB uncompressed; the pip layer is ~2.7 GB of it. Slimming (e.g. splitting the Playwright perf gate into a separate image) is a known future optimization, not a blocker.

## `.dockerignore`

Excludes `.git`, secrets (`.env*`, `*.key`, `*.pem`), local caches (`runs/`, `sources/pdfs/`, `sources/cache/`), posts/skills media, and Python/Node junk. The runtime-needed files stay: `config.json`, `factory/`, `sources/catalog.json`, `docs/frontend/` (the factory reads the design doctrine at runtime). Result: the `COPY . .` layer is ~217 kB despite a ~100 MB repo.

## Local workflow

```bash
docker build -t zivon-factory:0.3.22 .
docker run --rm zivon-factory:0.3.22                          # smoke test
docker run --rm -it zivon-factory:0.3.22 bash                 # explore inside
docker history zivon-factory:0.3.22                           # per-layer sizes
docker compose run --rm factory python pipeline.py "Motion" --class 9   # full pipeline run
```

`docker-compose.yml` is the local runner: builds the image, passes the server env (`ZIVON_BASE_URL`, `ZIVON_MODEL`, `ZIVON_API_KEY`) from the shell, mounts pipeline **output** (`runs/`, generated pages in `frontend/`) plus download caches (PDFs, text, HuggingFace) as volumes — containers stay disposable while output and caches survive.

## Frontend image (`Dockerfile.frontend`)

The static site ships as its own small nginx image — hosting the frontend is separate from the factory that generates it.

```bash
docker build -f Dockerfile.frontend -t zivon-frontend:0.1.6 .
docker compose up web                                       # serve ./frontend on http://localhost:8081
docker run --rm -p 8081:8080 -v "$PWD/frontend:/usr/share/nginx/html" zivon-frontend:0.1.6
```

- **Base:** `nginxinc/nginx-unprivileged:1.31.7-alpine3.24` — the official non-root nginx variant (UID 101, port 8080), matching the repo's non-root rule. A targeted `apk update && apk upgrade` (as a `USER 0`/`USER 101` sandwich — apk needs root; the final user stays non-root) freshens the packages whose fixes landed after the base's frozen index: round 1 brotli/curl/libcurl/libexpat, round 2 (2026-11-09) musl + musl-utils (CVE-2026-107891) and zlib (CVE-2026-85091). Bumping the tag is not an option here: 1.31.7-alpine3.24 is still the newest micro build of this base. nginx itself is not upgraded.
- **Baked:** only the hand-maintained shell — `index.html`, `assets/` (shared CSS/JS, local fonts) and `docker/nginx.conf`. Generated pipeline output (`courses/`, `courses.js`) is **never baked into an image** (repo rule): it arrives at runtime on a mounted volume (compose) or PVC (cluster) at the same html root. The shell is staged at `/opt/zivon-shell` so the served root can be a volume without losing it.
- **Site config:** CSP + `nosniff` + `no-referrer` headers site-wide (topic pages keep their own stricter meta CSP); `no-store` for HTML and `courses.js` (demo-day freshness), 5-min revalidation otherwise; gzip; `/healthz` probe; autoindex off.
- CI builds it, serves it, curls it, and trivy-scans it (`frontend-image` job in `cicd.md`). The CI smoke reproduces the cluster serving path: the html root is a writable tmpfs (the PVC + fsGroup stand-in) seeded from `/opt/zivon-shell` with the same `cp -rn` glob copy the initContainer uses. A bare `docker run` of this image serves nginx's default page — the shell only appears in the root via mount or seed, so a smoke that curls the unseeded image can never see the site.

## Rules

- API keys and all server wiring enter only via environment at runtime (`ZIVON_BASE_URL`, `ZIVON_MODEL`, `ZIVON_API_KEY` — see `.env.example`), never via image or `COPY`.
- Dev-only exception to "no extra images": the **inference router** (`docker/inference-router.Dockerfile`, alpine+socat, `network_mode: host`) bridges the host's loopback-only inference server to containers and cluster pods (`192.168.49.1:18080 → 127.0.0.1:8080`). It is a dev tool: not a product image, not in CI, never deployed to real clusters.
- Version tags: `name:semver` locally; CI will add commit-SHA tags in the registry.
- Any new runtime dependency goes into `requirements.txt` (CI's pip-audit and trivy watch it).

## Voice backend mounts into the core-backend image (no `Dockerfile.voice`)

The voice tutor (`voice/` package, spec: `docs/specs/voice-agent/`) is **not** a separate image in
P0 (ADR-0020): `voice/ws_api.mount_voice(app)` registers the `/voice/ws` route on the core
backend's FastAPI app, so the "voice-backend" Deployment + Service (backend-spec §4.2, manifests
25–27, owner: core-backend agent) is simply that monolith image with the router mounted.

Gotchas for whoever folds the deps (merge agent):

- `voice/requirements.txt` (google-genai, websockets, httpx) must be appended to the core
  backend image's install list — `voice/` is a top-level package, so a plain `pip install -r` at
  the repo root covers it only if the monolith Dockerfile copies `voice/` alongside `factory/`.
  The image stays slim: no torch/pdfplumber/playwright — the brain is remote (ADR-0017).
- `websockets` is pinned `>=12,<16` per the frozen spec; the client code imports the new asyncio
  API first and falls back to the legacy name, so either line works.
- Secrets (`ZIVON_VOICE_GEMINI_API_KEY`/`GEMINI_API_KEY`, `GNANI_PRISMA_API_KEY`,
  `GNANI_TIMBRE_API_KEY`) are runtime env from the `zivon-voice-env` Secret (GAP-001 registry) —
  never baked. CI stays key-free: the whole voice test suite runs on mocks
  (`python -m unittest discover -s testing/voice -t .`).
- Credit-guard knobs (`ZIVON_VOICE_CREDIT_*`) are unit-placeholder until OQ-06 pins the Gnani
  vendor unit — the founder calibrates the defaults after the first live sessions; the guard
  math itself is unit-agnostic.
