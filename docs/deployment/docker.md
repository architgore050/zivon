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

- **Base:** `nginxinc/nginx-unprivileged:1.31.7-alpine3.24` — the official non-root nginx variant (UID 101, port 8080), matching the repo's non-root rule. A targeted `apk update && apk upgrade` (as a `USER 0`/`USER 101` sandwich — apk needs root; the final user stays non-root) freshens the packages whose fixes landed after the base's frozen index: round 1 brotli/curl/libcurl/libexpat, round 2 (2026-11-09) musl + musl-utils (CVE-2026-107891) and zlib (CVE-2026-85091); round 3 (2026-11-16) libxslt (CVE-2026-125350 / -87636 / -9947). Bumping the tag is not an option here: 1.31.7-alpine3.24 is still the newest micro build of this base (re-checked on Docker Hub 2026-11-17), and its frozen index predates the Alpine fixes. nginx itself is not upgraded.
- **Why libxslt is in the image, and why its fix is an exact pin (2026-11-17, W4 ci-hygiene):** libxslt enters the image as a soname dependency (`so:libxslt.so.1`) of the baked `nginx-module-xslt` module; the base ships `libxslt 1.1.43-r3` (read from the image's apk DB), Trivy flags it HIGH (the three CVEs above), and the fix is `1.1.43-r4` — exactly the build the Alpine v3.24 main repo carries (APKINDEX checked 2026-11-17; the entry's deps are sonames the base already satisfies, so the pinned add pulls nothing else in). The freshening layer therefore upgrades libxslt as `apk add --no-cache libxslt=1.1.43-r4` — an exact pin, unlike the other freshened packages, which stay targeted + unpinned (Alpine keeps only the newest `-r` revision, so unpinned upgrades reach each fix on every rebuild). The pin is deliberate: it encodes the exact Trivy-verified fix build the scan gate reads, and when Alpine supersedes `1.1.43-r4` in v3.24 the pin fails the build loudly instead of silently drifting — bump it to the new `-r` revision in the same PR (the same bump-deliberately ritual as the CI tool pins in `cicd.md`). A digest re-pin of the base was considered and rejected: the tag's current build (digest `sha256:b5047b9b…`, last rebuilt 2026-10-19) freezes an index without the libxslt fix, so only the apk layer can reach it.
- **Baked:** only the hand-maintained shell — `index.html`, the public-site folders (`catalogue/`, `class-9-physics/` … `class-12-physics/`, `method/`, `about/`, `pricing/`, `terms/`, `contact/`, `status/`, `privacy/`), `404.html`, `assets/` (shared CSS/JS, local fonts) and `docker/nginx.conf`. Generated pipeline output (`courses/`, `catalogue.json`, `courses.js`) is **never baked into an image** (repo rule): it arrives at runtime on a mounted volume (compose) or PVC (cluster) at the same html root. The shell is staged at `/opt/zivon-shell` so the served root can be a volume without losing it. The catalogue URL `/courses` is an exact nginx location serving `catalogue/index.html`; the class pages live outside the factory-owned `courses/` tree for the same publish-replacement reason (`docs/frontend/public-site.md`).
- **Publish to the repo snapshot:** `scripts/publish-frontend.sh` copies `courses/`, `catalogue.json`, `courses.js` and the locale hubs from the PVC, then runs the P5 publish gates (`python3 -m factory.catalogue check --strict`): one compatible `pipeline_version`, every href/locale/i18n/locale-manifest resolves, the P1 hook contract is on every page, a `lesson_title` and a usable `chapter.title` exist, every sitemap URL resolves and no dev placeholder base URL survives. SEO is regenerated after the locale-hub copy; `--dry-run --source-dir <tree>` validates a staging tree without touching the repo.
- **Site config:** CSP + `nosniff` + `no-referrer` headers site-wide (topic pages keep their own stricter meta CSP); `no-store` for HTML and `courses.js` (demo-day freshness), 5-min revalidation otherwise; gzip; `/healthz` probe; autoindex off. Redirects are relative (`absolute_redirect off`) because the Service maps port 80 -> container 8080 and an absolute redirect would leak the pod port into the public `Location`.
- CI builds it, serves it, curls it, and trivy-scans it (`frontend-image` job in `cicd.md`). The CI smoke reproduces the cluster serving path: the html root is a writable tmpfs (the PVC + fsGroup stand-in) seeded from `/opt/zivon-shell` with the same `cp -rn` glob copy the initContainer uses. A bare `docker run` of this image serves nginx's default page — the shell only appears in the root via mount or seed, so a smoke that curls the unseeded image can never see the site.

## Server-rendered web shell (`web/`, `/app`)

The authenticated app pages are HTML rendered by the **core-backend** image, not
by the static frontend image. `web/` is a Python package inside that image:
FastAPI routers + Jinja2 templates that `backend.app.create_app` mounts with
`web.mount_web(app)`. `Dockerfile.backend` copies `web/`, and
`backend/requirements.txt` pins `jinja2`; there is no new service, no Node
build, and no second origin.

- **`/app` and `/app/*`:** `docker/nginx.conf` proxies them to
  `core-backend:8000` with the full forwarded-header set. The browser's
  `HttpOnly` session cookie and the backend's `Set-Cookie` pass through
  unchanged (no `proxy_set_header Cookie`, no `proxy_hide_header Set-Cookie`).
- **`/login`:** the app guard redirects guests to `/login?next=...`, so that
  exact location is proxied now; F2 owns the screen and adds the remaining auth
  locations (`/signup`, `/verify-email`, `/reset-password`, `/onboarding`,
  `/auth/google/*`) in its PR.
- **CSP:** the app/login locations are the only non-lesson surface besides
  `/privacy/` with `connect-src 'self'`; the policy is identical to
  `web/render.py` (`CSP_POLICY`) and repeated in full because nginx drops
  inherited `add_header` directives once a location declares its own.
- **Caching and indexing:** `Cache-Control: no-store` and
  `X-Robots-Tag: noindex, nofollow` on every app/login response, plus the
  `meta robots` in the template.
- **Static assets stay on the frontend image:** `/assets/product.css`,
  `/assets/product.js`, and the local fonts are served by the frontend nginx
  root. A bare backend port serves the HTML without CSS; the supported path is
  the same-origin frontend route (compose `:8081`, cluster Service).

## Admin dashboard image (`Dockerfile.dashboard`)

The admin dashboard ships as its own slim image: the FastAPI app (`dashboard/`), the
`logging_manager` contract package it reads through, the two trigger scripts and the
k8s/20 Job template the factory-run button renders. kubectl is baked in because the
run/test views and the two buttons talk to the cluster API (integration note I-1).
Runtime shape is the repo's standard: `python:3.12-slim`, deps-before-code, fixed UID
1000 numeric `USER` (gotcha 1), env-only config, a build-time `kubectl version
--client=true --output=yaml` smoke that CI repeats on the booted container.

- **kubectl is built from source in the image (DEP2, 2026-11-19).** Until this change
  the Dockerfile downloaded the prebuilt `dl.k8s.io` binary, so the trivy gate read
  whatever Go stdlib the upstream release build had embedded. kubectl v1.37.2 was
  released on a `go1.26.10` toolchain (the k8s repo's `.go-version`; confirmed by
  `kubectl version --client=true --output=yaml` on the official artifact), and
  CVE-2026-97054 (GO-2026-6854 — an HTTP/1 server can crash when its handler reads a
  request body past the `MaxBytesReader` limit; HIGH, fix available) flags that
  embedded stdlib. No kubectl release built with the fixed Go exists yet, and the repo
  never weakens a gate to get green: the fix is the compiler, not an ignore. The image
  now has two stages — a **`golang:1.26.11` builder** (stage 1) and the unchanged
  `python:3.12-slim` runtime (stage 2) that receives exactly one file:
  `COPY --from=kubectl-builder --chmod=0555` the static binary.
- **The build recipe is upstream's own.** Stage 1 shallow-clones the exact
  `v1.37.2` tag, pins the dereferenced commit (`KUBECTL_COMMIT=c50e5395…` — the
  `gitCommit` the official binary stamps; the build fails loudly if the tag ever
  moves, the same SHA-over-tag rule as the third-party CI action pins), then runs
  `FORCE_HOST_GO=y make kubectl` — `build/root/Makefile`'s `make kubectl` calls
  `hack/make-rules/build.sh cmd/kubectl`, which stamps `gitVersion`/`gitCommit`/
  `gitTreeState` from the clone and builds kubectl with `CGO_ENABLED=0` (kubectl is
  in `hack/lib/golang.sh`'s `KUBE_STATIC_BINARIES`). **`FORCE_HOST_GO=y` is the load-
  bearing env var**: without it `hack/lib/golang.sh` sets `GOTOOLCHAIN=go1.26.10`
  (the repo's `.go-version`) and downloads that toolchain, rebuilding the very
  stdlib this stage exists to replace; with it the script sets `GOTOOLCHAIN=local`
  and uses the image's go1.26.11. Verified natively 2026-11-19 (same commands as
  stage 1, outside Docker): the built binary reports `gitVersion v1.37.2`,
  `gitCommit c50e5395…`, `gitTreeState clean`, **`goVersion go1.26.11`**, static ELF,
  61,890,722 bytes — the same size as the official v1.37.2 artifact, one patch level
  newer in the only thing that changed, the compiler.
- **Why the prebuilt binary is no longer used:** a prebuilt download freezes the
  release build's toolchain into the image until upstream ships a new kubectl — a
  Go stdlib CVE in it is unfixable by us except through `docker/.trivyignore-dashboard`,
  whose scope rule says prebuilt-binary ignores are the last resort. Building the
  same source tag with a newer Go patch is the upstream-supported equivalent of
  "wait for the patch release", available today: the binary stays v1.37.2 (no
  behavior change), the embedded stdlib is patched (the finding clears), and the
  gate stays untouched — no entry was added to the ignore file for CVE-2026-97054.
  The ignore file's three existing entries remain REQUIRED: they are vendored-module
  findings (x/net 0.57.0, x/text 0.40.0) pinned by the tag's `vendor/`, which a
  compiler bump does not change; its scope rule now covers both code paths
  (source-built tag + prebuilt binary).
- **Determinism and supply chain:** the clone is content-pinned twice (tag for
  humans, `KUBECTL_COMMIT` for the gate — `test "$(git rev-parse HEAD)" = "${KUBECTL_COMMIT}"`),
  `vendor/` ships in the tag so module versions are exactly upstream's, and the
  ldflags version stamping is derived from the clone itself. What varies is build
  metadata only (`buildDate`), same as upstream's own artifacts. The old fetch
  trusted a mutable tag URL on `dl.k8s.io` with TLS and no checksum; the new build
  verifies the commit — strictly stronger. The `golang:1.26.11` builder tag follows
  the repo's tag-pin convention (digest re-pin considered and rejected for the
  same reasons documented on the frontend base above); the builder never ships, so
  its layers are not a runtime CVE surface and need no apt freshening.
- **Cost discipline:** the runtime stage is the old one minus `curl` (kubectl is no
  longer downloaded) — the shipped image loses bytes, gains none. What the builder
  adds is CI build time: a shallow clone of the k8s source plus a single-binary
  compile (minutes on the runner; the `dashboard-image` job's `type=gha` layer cache
  holds the builder layers after the first build).
- **Rebuild ritual (the next stdlib CVE):** bump the builder tag
  (`golang:1.26.11` → the fixed Go patch), rebuild, and let trivy's table name the
  fixed version it no longer sees — the same bump-deliberately ritual as the CI
  tool pins in `cicd.md`. When upstream ships a kubectl release built with the
  fixed vendored modules, re-pin `KUBECTL_VERSION` (staying within ±1 minor of the
  cluster version, together with the cluster upgrade) and re-check the three
  vendored-module ignores.

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

The weld is landed in `Dockerfile.backend` (EX6-CICD):

- `COPY voice/requirements.txt` + `pip install -r backend/requirements.txt -r voice/requirements.txt`
  in one deps layer (deps before code), then `COPY voice ./voice`. `voice/` is a top-level
  package on `PYTHONPATH=/app`, so `from voice.ws_api import mount_voice` resolves in the image.
  `logging_manager/` (EX3's shared event contract, imported by `voice/logging_surface.py` with no
  local fallback) ships in the same COPY block — its JSONL path is stdlib-only and the Postgres
  driver is already in `backend/requirements.txt`.
- `backend/app.py` mounts the real router with `VoiceSettings.from_env()`; the session-token and
  IP-hash-salt secrets fall back to the backend's own config, so the backend-issued
  `session_token` (full HMAC-SHA256 hex digest) validates on the voice channel. The EX0
  `backend/voice_stub.py` fallback is retired — there is one voice code path.
- The image stays slim: no torch/pdfplumber/playwright — the brain is remote (ADR-0017).
- `websockets` is pinned `>=12,<16` per the frozen spec; the client code imports the new asyncio
  API first and falls back to the legacy name, so either line works.
- Secrets (`ZIVON_VOICE_GEMINI_API_KEY`/`GEMINI_API_KEY`, `GNANI_PRISMA_API_KEY`,
  `GNANI_TIMBRE_API_KEY`) are runtime env from the `zivon-voice-env` Secret (GAP-001 registry) —
  never baked. CI stays key-free: the whole voice test suite runs on mocks
  (`python -m unittest discover -s testing/voice -t .`), and the backend suite imports the real
  app via the mocked-factory seams only.
- Credit-guard knobs (`ZIVON_VOICE_CREDIT_*`) are unit-placeholder until OQ-06 pins the Gnani
  vendor unit — the founder calibrates the defaults after the first live sessions; the guard
  math itself is unit-agnostic.
