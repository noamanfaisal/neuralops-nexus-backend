# =============================================================================
# neuralops/Dockerfile — the unified "neuralops" image.
#
# One image, three app processes: nucleus (Django), nexus-ai (FastAPI),
# centrifugo (compiled Go binary, aka nexus-transport). Each runs as its own
# compose service/container from this SAME image, selected at `docker run`/
# compose time via entrypoint.sh's first argument + a `command:` override —
# see docker-compose.neuralops.yaml.
#
# Deliberately NOT in this image: postgres, redis, nginx (separate services
# using their official images — see docker-compose.neuralops.yaml; postgres
# is the pgvector build, carrying the vector store since Step 8a — chromadb
# is gone), and the rest of nexus-mcp (SerpAPI/Odoo — separate
# docker/compose, added later).
#
# ONE PYTHON (3.13) FOR BOTH (owner's ruling, 2026-10-15): nucleus moved
# from its historical 3.11 to the engine's 3.13 — Django 5.2 supports
# 3.13, and one interpreter is simpler than copying a second one into the
# final image. The 457-test nucleus suite is the proof the move is safe.
# All python stages stay pinned to the same Debian release (bookworm).
#
# nucleus and nexus-ai get their OWN separate venvs (nucleus-env /
# nexus-ai-env) rather than one shared/merged environment — Django+pydantic 2
# (nucleus) and pydantic-ai-slim/litellm (nexus-ai) pin different transitive
# dependency versions; one shared site-packages risks one module's install
# silently breaking the other's. Small extra image weight, real reduction in
# "works differently depending on install order" risk.
#
# Build context is the REPO ROOT (not this directory) — every COPY below is
# rooted there so it can reach modules/nexus-nucleus, modules/nexus-ai, and
# modules/nexus-transport in one build. Build with:
#   docker build -f neuralops/Dockerfile -t neuralops:local .
# =============================================================================

# ── Stage 1: nucleus deps ────────────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS nucleus-builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential libpq-dev && \
  rm -rf /var/lib/apt/lists/*
ENV VIRTUAL_ENV=/opt/venv/nucleus-env
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
COPY modules/nexus-nucleus/docker/dev/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: nexus-ai deps ───────────────────────────────────────────────────
# The REBUILT engine's venv, on Python 3.13 (the legacy engine and its venv
# are gone — modules/nexus-ai-legacy was deleted at Step 8a). requirements.lock
# is the frozen `pip freeze` of requirements.txt — regenerate it, never
# hand-edit (docs/CHANGE-PROMPT.md lesson 14). It carries torch==…+cpu,
# which only exists on PyTorch's own index — hence the extra-index-url.
# pytest is baked in on purpose: the engine suite must be runnable in any
# container of this image with no network install step; the distribution
# half may strip it.
FROM python:3.13-slim-bookworm AS nexus-ai-builder
WORKDIR /build
ENV VIRTUAL_ENV=/opt/venv/nexus-ai-env
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
COPY modules/nexus-ai/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock \
    --extra-index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir pytest==9.1.1 pytest-asyncio==1.4.0

# ── Stage 2b: app code, compiled to NATIVE code (Cython) ──────────────────
# The release image CARRIES the code (owner's plan, 2026-10-22) and, since
# 1.1.0, carries it as NATIVE MACHINE CODE (owner, 2026-11-01: the code goes
# closed until launch traction — "make sure the docker contains no code but
# compiled one"). Bytecode (.pyc, 1.0.0's road) is easy to decompile; Cython
# turns each module into a .so extension BESIDE where its .py was, so Django's
# discovery, celery's -A core and uvicorn's "module:app" strings keep working.
# Cython over Nuitka (ruled 2026-11-01): per-file modules keep Django's
# file-based discovery of migrations and management commands intact.
# neuralops/cython_build.py says what stays bytecode and why (manage.py,
# package __init__ files, migrations). The suites run against this image are
# the proof nothing changed behaviour.
# What never enters the image: tests, the .step0-removed/_attic parking lots,
# dev docker files, pytest caches and reports, internal notes.
FROM python:3.13-slim-bookworm AS code-builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir cython==3.1.2 setuptools==80.9.0
COPY modules/nexus-nucleus /code/nucleus
COPY modules/nexus-ai /code/ai
COPY neuralops/cython_build.py /build/cython_build.py
# Second fence (the first is .dockerignore): runtime data must never ship.
# Found 2026-11-01 in the published 1.0.0 image — the dev log (27 email
# addresses) and an uploaded document. Only the avatar POOL is kept from
# media/, and the build FAILS if anything else is left there or in logs/.
RUN find /code/nucleus/media -mindepth 1 -maxdepth 1 ! -name avatars -exec rm -rf {} + 2>/dev/null || true && \
    find /code/nucleus/media/avatars -mindepth 1 -maxdepth 1 ! -name pool -exec rm -rf {} + 2>/dev/null || true && \
    rm -rf /code/nucleus/logs /code/nucleus/debug_playground.py && \
    find /code -name ".*" -type f -name "*.py" -delete && \
    find /code -name ".vscode" -type d -exec rm -rf {} + && \
    test -z "$(find /code/nucleus/media -type f ! -path '*/avatars/pool/*' 2>/dev/null)" || \
      (echo "runtime data left in /code/nucleus/media" && exit 1)
RUN rm -rf \
      /code/nucleus/.step0-removed \
      /code/nucleus/docker \
      /code/ai/tests \
      /code/ai/trial-c \
      /code/ai/docker \
      /code/ai/.pytest_cache \
      /code/ai/.vscode && \
    rm -f /code/ai/test-output.txt /code/ai/pytest.ini \
      /code/ai/requirements-dev.txt /code/ai/RULES.md && \
    find /code -type d -name "__pycache__" -exec rm -rf {} + && \
    find /code/nucleus -name "tests.py" -delete && \
    find /code/nucleus -name "tests_*.py" -delete
# Native code first (every module that compiles fails the build if it does
# not), symbols stripped so the .so files carry no C-level names; then the few
# files that stay bytecode: -b writes each .pyc BESIDE its source, the find
# removes every remaining .py except manage.py.
RUN python /build/cython_build.py /code/nucleus /code/ai && \
    find /code -name "*.so" -exec strip --strip-unneeded {} + && \
    python -m compileall -b -q /code && \
    find /code -name "*.py" ! -name "manage.py" -delete
# The proof, at build time: no readable Python except manage.py, no C sources,
# and native modules where the code is.
RUN set -e; \
    if [ -n "$(find /code -name '*.py' ! -name manage.py)" ]; then echo 'readable .py left in the image'; exit 1; fi; \
    if [ -n "$(find /code -name '*.c')" ]; then echo 'C sources left in the image'; exit 1; fi; \
    native="$(find /code -name '*.so' | wc -l)"; \
    if [ "$native" -lt 100 ]; then echo "only $native native modules - compile step skipped?"; exit 1; fi; \
    echo "native: $native  bytecode: $(find /code -name '*.pyc' | wc -l)"

# ── Stage 3: centrifugo / nexus-transport binary ────────────────────────────
# Same build this repo already uses for modules/nexus-transport/Dockerfile —
# replicated here (not COPY --from an external image) so the whole neuralops
# image builds from one `docker build` with no separate image to pull first.
FROM golang:1.26-alpine AS transport-builder
RUN apk add --no-cache git
WORKDIR /app
COPY modules/nexus-transport/go.mod modules/nexus-transport/go.sum ./
RUN go mod download
COPY modules/nexus-transport/ .
ENV CGO_ENABLED=0
RUN go build -ldflags="-s -w -X 'github.com/centrifugal/centrifugo/v6/internal/build.Version=v6.6.2-nexus'" \
  -o nexus-transport .

# ── Stage 4: final image ─────────────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS final

RUN apt-get update && apt-get install -y --no-install-recommends \
  ca-certificates libpq-dev curl nodejs npm git openssh-client && \
  rm -rf /var/lib/apt/lists/*

# Filesystem MCP — installed globally at build time (not left to `npx` to
# fetch on first run), same reasoning as the old Fat-Docker image: works
# offline, starts instantly. This is the one MCP server baked into the
# image; the rest of nexus-mcp (SerpAPI, Odoo ERP) stays out, per plan.
RUN npm install -g @modelcontextprotocol/server-filesystem
RUN pip install --no-cache-dir uv
# UV_TOOL_DIR as well as UV_TOOL_BIN_DIR: the BIN dir only relocates the
# launcher, while the tool's own venv defaults to $HOME/.local/share/uv/tools
# -- which, since this runs as root, is /root (mode 0700). The launcher would
# resolve into a directory USER nexus cannot traverse, and every call fails
# with "Permission denied".
ENV UV_TOOL_DIR=/opt/uv-tools \
    UV_TOOL_BIN_DIR=/usr/local/bin
RUN uv tool install mcp-server-git && chmod -R a+rX /opt/uv-tools


ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID nexus && useradd -m -u $UID -g $GID -s /bin/bash nexus
# No passwordless sudo here on purpose — this stage is what production runs.
# The existing dev Dockerfiles (modules/*/docker/dev/Dockerfile.*) grant the
# "ubuntu" user passwordless sudo for interactive convenience; not carrying
# that into an image meant to also run as the default production build.

# ── Baked-in values, common to every deployment ─────────────────────────
# Only genuinely shared, non-secret (or safe-to-be-public) values live here
# now. SUPABASE_URL/SUPABASE_ANON_KEY point at one real Supabase project
# every deployment's login flow shares -- not per-install secrets, and
# ANON_KEY is designed to be public (protected by Supabase RLS).
# NEURALOPS_PORTAL_URL/VERSION are just informational/fixed.
#
# NEURALOPS_VERSION is ONE number for the whole image on purpose: nucleus,
# nexus-ai, and centrifugo are built together in this same Dockerfile from
# the same COPY of the repo, so there's no such thing as a real deployed
# state where they're at different versions from each other -- one build,
# one tag, one version. This is also the exact string the frontend compares
# itself against (see modules/neuralops-web-app/src/lib/version.ts,
# COMPATIBLE_SERVER_VERSION) -- that parser expects a plain MAJOR.MINOR(.PATCH)
# string, so keep bumps here in sync with that file, and with
# NEURALOPS_IMAGE in neuralops/infra.env.example, every time this changes.
#
# Explicitly NOT baked here:
#   - NEURALOPS_SERVER_URL -- genuinely different per deployment (the
#     public URL THIS box is reachable at), stays required/user-supplied.
#   - OPENAI_API_KEY / ANTHROPIC_API_KEY -- no shared default, ever;
#     nucleus's /add-model flow stores each one encrypted per-row in the
#     DB instead.
#   - SUPABASE_SERVICE_KEY -- removed once this repo went public. It's a
#     full-admin key for the whole shared Supabase project (bypasses RLS,
#     full Auth Admin API), and traced usage showed nothing in the app
#     actually needs it: neither POST /api/v1/members/invite/
#     (members_services.py:send_invite) nor the /invite slash command
#     (team_services.py:invite_to_project) call authn/supabase.py's
#     invite_user_by_email() -- both just create a pending Invitation row
#     and leave the person to share the link manually. settings.py
#     already defaults it to "" via os.getenv(), so leaving it unset here
#     is safe.
#   - FIELD_ENCRYPTION_KEY / INTERNAL_API_KEY / CENTRIFUGO_API_KEY /
#     CENTRIFUGO_HMAC_SECRET -- used to be baked as one shared default
#     here too, but that stopped being safe once this image went public:
#     INTERNAL_API_KEY in particular gates nucleus's /api/v1/internal/
#     endpoints (decrypted AI-model API keys, raw chat history), which
#     nginx proxies under the same public /api/ prefix as everything else
#     -- a baked, publicly-known INTERNAL_API_KEY would let anyone with a
#     deployment's URL pull that data out. These four are now generated
#     fresh per deployment instead -- run
#     `docker run --rm <image> init-secrets > neuralops/secrets.env` once
#     per install (see entrypoint.sh's init-secrets mode), then pass that
#     file as a third --env-file alongside infra.env/app.env. Referenced
#     in docker-compose.neuralops.yaml via ${VAR} in each service that
#     needs it -- NOT set here, so there's no shared value to fall back to.
ENV SUPABASE_URL="https://xgfsxikypxjhqlutiepw.supabase.co" \
  SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhnZnN4aWt5cHhqaHFsdXRpZXB3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIyNDg3MDcsImV4cCI6MjA5NzgyNDcwN30.2_OUNTHuKSeDJh6S-aUW16IqvDTmew8ZcFuKvFkt3Dk" \
  NEURALOPS_PORTAL_URL="https://neuralopsnexus.ai/add_code" \
  NEURALOPS_VERSION="1.1.8"

COPY --from=nucleus-builder /opt/venv/nucleus-env /opt/venv/nucleus-env
COPY --from=transport-builder /app/nexus-transport /usr/local/bin/nexus-transport
# NOTE: no /nexus/transport-version file -- modules/nexus-transport has no
# VERSION file at its root (checked, doesn't exist), unlike what the old
# Fat-Docker Dockerfile snippet assumed. Double-checked: no authn/versions.py
# or anything else in modules/nexus-nucleus reads a file at this path either
# (searched, no matches) -- safe to leave out, nothing depends on it.
RUN chmod +x /usr/local/bin/nexus-transport

# The engine's venv — same Python 3.13 as the final image's own interpreter
# (both from python:3.13-slim-bookworm), so the venv's symlinks resolve
# as-is and NO second interpreter needs copying.
COPY --from=nexus-ai-builder /opt/venv/nexus-ai-env /opt/venv/nexus-ai-env
# Build-time sanity check — a broken copy fails HERE, loudly, not at the
# first chat message: the copied interpreter must import the heavy deps.
RUN /opt/venv/nexus-ai-env/bin/python -c "import fastapi, sqlalchemy, pgvector, fastembed, torch; print('nexus-ai venv OK')"

# ── The local model, baked in (owner, 2026-11-01: "make sure that docker
# contains embedders") ─────────────────────────────────────────────────────
# nomic-embed-text-v1.5 (fastembed/ONNX) is the ONE model the engine runs
# locally: the vector store AND the output-type classifier use it
# (vector_db/embedder.py DEFAULT_EMBEDDER, core/config.py CLASSIFIER_EMBEDDER).
# Everything else that "thinks" (topics, memory, replies) uses the persona's
# own model through its API. Before 1.1.0 it was downloaded on first use into
# fastembed's default /tmp/fastembed_cache — inside the container, so every
# recreate fetched ~0.5 GB again and an offline server could not embed at
# all. FASTEMBED_CACHE_PATH points fastembed at the baked copy; a team that
# picks another fastembed model still downloads that one here on first use.
# Placed BEFORE the app code so a code change does not re-download it.
ENV FASTEMBED_CACHE_PATH=/opt/models/fastembed
RUN mkdir -p /opt/models/fastembed && \
    /opt/venv/nexus-ai-env/bin/python -c "from fastembed import TextEmbedding; m = TextEmbedding('nomic-ai/nomic-embed-text-v1.5'); v = next(iter(m.embed(['ok']))); assert len(v) == 768, len(v); print('embedder baked:', len(v), 'dims')" && \
    chown -R nexus:nexus /opt/models

# ── The live browser's engine ────────────────────────────────────────────────
# Chromium plus the system libraries it needs, ~450 MB, installed with the
# worker's own venv (which now carries playwright). Worth it when the team
# wants a real browser beside the chat — tabs, logins, JavaScript; an iframe
# cannot show google.com at all. Skip it with --build-arg BROWSER=0 and the
# worker reports the pane as unavailable instead of failing at it.
# (playwright/Chromium block REMOVED with the venv it lived in — the live
# browser returns with the rebuilt engine's image in the distribution half.)


# APP CODE IS IN THE IMAGE since 1.0.0 (Stage 2b above): the production
# profile runs the baked bytecode with no source tree on the host. The DEV
# profile keeps working unchanged — its bind mounts (modules/nexus-nucleus →
# /nexus/nucleus, modules/nexus-ai → /nexus/ai) simply SHADOW the baked
# code, so dev still runs live source and a dev code change still needs no
# rebuild (only a dependency change does).

# Shared project folders — filesystem MCP is pointed at a per-project
# subfolder here (see readme's MCP section); mounted as an external volume
# at /nexus/projects in compose so it survives image rebuilds/upgrades.
#
# /home/nexus/.cache is ALSO a named-volume mount target in compose
# (fastembed's model cache) -- pre-creating + chowning it here matters for
# the exact same reason /nexus/projects does: a named volume only inherits
# the image's ownership on first mount if the target directory already
# exists in the image. Without this, Docker auto-creates the mount point
# as root-owned and fastembed's HuggingFace download fails with
# "Permission denied" the first time nexus-ai actually tries to embed
# something -- confirmed, this is exactly the bug that was hit.
COPY --from=code-builder /code/nucleus /nexus/nucleus
COPY --from=code-builder /code/ai /nexus/ai
# /nexus/catalog: the downloaded model catalog (intelligence/models_catalog.py),
# a named volume in compose -- created here so the volume inherits nexus's
# ownership on first mount.
RUN mkdir -p /nexus/projects /nexus/catalog /nexus/logs/nucleus /nexus/logs/ai /home/nexus/.cache/fastembed && \
  chown -R nexus:nexus /nexus /home/nexus/.cache

COPY neuralops/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER nexus
WORKDIR /nexus
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
