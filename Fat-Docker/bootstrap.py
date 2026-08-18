#!/usr/bin/env python3
"""
Fat-Docker/bootstrap.py

Two separate steps, run by hand, in order -- Postgres does NOT need to be
running for the first one:

  1. generate-env  -- generates fresh, random, per-deployment credentials
     and secrets (POSTGRES_DB/USER/PASSWORD, CENTRIFUGO_API_KEY,
     CENTRIFUGO_HMAC_SECRET, INTERNAL_API_KEY, FIELD_ENCRYPTION_KEY) and
     writes the complete env -- shared by every module, not just nucleus
     -- to a persisted file. No DB connection made at all. Safe to run
     with Postgres down.

  2. init-db  -- reads that persisted file back, waits for Postgres to be
     ready, then creates the role/database from those values IF they don't
     already exist. Safe to re-run on every container start (checks
     existence first, doesn't blindly re-CREATE).

init-db also starts Postgres itself if it isn't running yet -- runs
initdb on first call if the data directory is empty, starts the server,
and tightens pg_hba.conf so the generated POSTGRES_PASSWORD is actually
enforced (initdb defaults to trust auth, which would make that password
meaningless for TCP connections). You don't need to touch Postgres by
hand at all.

Usage (only two commands, in order):
    docker exec nexus-fat python3 /nexus/bootstrap.py generate-env
    docker exec nexus-fat python3 /nexus/bootstrap.py init-db

Running with no subcommand does both in order (generate-env then init-db),
kept only for convenience -- the two-step flow above is the intended one.
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

POSTGRES_DATA_DIR = Path("/var/lib/postgresql/data")

SECRETS_DIR = Path("/nexus/secrets")
# Shared across every module (nucleus, nexus-ai, ...) -- POSTGRES_* and
# INTERNAL_API_KEY in particular MUST be identical between nucleus and
# nexus-ai (same Postgres, same internal-auth shared secret), so one file
# read by both avoids ever having them drift apart. LOG_DIR is
# deliberately NOT in this file for that same reason, in reverse -- it's
# the one value that has to differ per-service, so it's set per `docker
# exec` command instead (see usage in Dockerfile.nexus / run commands).
ENV_FILE = SECRETS_DIR / "app.env"

# -- DB name/user prefixes -- the actual name+user get a random suffix
# appended at generation time (below), so every deployment gets its own
# identifiers too, not just its own password. Kept prefixed with something
# readable so `\l` / `\du` output still makes sense to a human.
POSTGRES_DB_PREFIX = "neuralops"
POSTGRES_USER_PREFIX = "neuralops"

# -- Internal topology -- single container, so every "host" is loopback.
# Broken into host+port pairs rather than baked into composed URLs, per
# the earlier discussion, so changing a port later means changing one
# variable, not hunting down every string it's embedded in.
NUCLEUS_HOST, NUCLEUS_PORT = "127.0.0.1", "8000"
NEXUS_AI_HOST, NEXUS_AI_PORT = "127.0.0.1", "8002"
CENTRIFUGO_HOST, CENTRIFUGO_PORT = "127.0.0.1", "8001"
REDIS_HOST, REDIS_PORT = "127.0.0.1", "6379"
POSTGRES_HOST, POSTGRES_PORT = "127.0.0.1", "5432"

# Must stay a clean MAJOR.MINOR.PATCH semver string -- this is the one
# field the frontend's compareServerVersion() actually parses and checks
# against COMPATIBLE_SERVER_VERSION (neuralops-react-app/src/lib/version.ts).
# Bump this (and COMPATIBLE_SERVER_VERSION on the frontend, together) only
# when deliberately cutting a real release -- the two are opposite ends of
# the same compatibility contract. Per-module version numbers (nucleus,
# nexus-ai, nexus-transport) are tracked separately via each module's own
# VERSION file -- see authn/versions.py -- and reported alongside this one,
# purely informationally, not folded into it.
NEURALOPS_VERSION = "0.1.1"


def _generate_fernet_key() -> str:
    """FIELD_ENCRYPTION_KEY must be a valid Fernet key, not just any random
    string -- nucleus's encrypted-secrets fields (AIModel.api_key_encrypted,
    MCPServer.secrets_encrypted) decrypt with this exact format."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def _read_env_file() -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if line and "=" in line
    )


def generate_env() -> dict[str, str]:
    """No Postgres connection made here at all -- pure secret generation,
    safe to run before Postgres is even started."""
    if ENV_FILE.exists():
        print(f"{ENV_FILE} already exists -- leaving it alone.")
        return _read_env_file()

    print("Generating credentials...")
    suffix = secrets.token_hex(4)
    env = {
        "POSTGRES_DB": f"{POSTGRES_DB_PREFIX}_{suffix}",
        "POSTGRES_USER": f"{POSTGRES_USER_PREFIX}_{suffix}",
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "POSTGRES_HOST": POSTGRES_HOST,
        "POSTGRES_PORT": POSTGRES_PORT,
        "NUCLEUS_HOST": NUCLEUS_HOST,
        "NUCLEUS_PORT": NUCLEUS_PORT,
        "NEXUS_AI_HOST": NEXUS_AI_HOST,
        "NEXUS_AI_PORT": NEXUS_AI_PORT,
        "NEXUS_AI_URL": f"http://{NEXUS_AI_HOST}:{NEXUS_AI_PORT}",   # nucleus -> nexus-ai
        "NEXUS_NUCLEUS_URL": f"http://{NUCLEUS_HOST}:{NUCLEUS_PORT}", # nexus-ai -> nucleus
        "CENTRIFUGO_HOST": CENTRIFUGO_HOST,
        "CENTRIFUGO_PORT": CENTRIFUGO_PORT,
        "CENTRIFUGO_API_URL": f"http://{CENTRIFUGO_HOST}:{CENTRIFUGO_PORT}/api",
        "CENTRIFUGO_API_KEY": (_centrifugo_api_key := secrets.token_urlsafe(32)),  # nucleus's name for it
        "CENTRIFUGO_HTTP_API_KEY": _centrifugo_api_key,  # Centrifugo's own expected env var name, same value
        "CENTRIFUGO_HMAC_SECRET": secrets.token_urlsafe(32),  # nucleus-side only -- Centrifugo runs with --client.insecure, doesn't check this
        "INTERNAL_API_KEY": secrets.token_urlsafe(32),
        "FIELD_ENCRYPTION_KEY": _generate_fernet_key(),
        "REDIS_HOST": REDIS_HOST,
        "REDIS_PORT": REDIS_PORT,
        "REDIS_URL": f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
        "NEURALOPS_VERSION": NEURALOPS_VERSION,
        "SUPABASE_DEVICE_REQUEST_URL": "https://xgfsxikypxjhqlutiepw.supabase.co/functions/v1/device-request",
        "SUPABASE_DEVICE_POLL_URL": "https://xgfsxikypxjhqlutiepw.supabase.co/functions/v1/device-poll",
        "NEURALOPS_PORTAL_URL": "https://neuralops-nexus-auth.mapax.io",
        # Public anon key for the SAME fixed Supabase project SUPABASE_URL
        # already points at (settings.py) -- deliberately not a secret
        # (Supabase anon keys are meant to be safe to expose client-side),
        # so it's a fixed constant here too, same as the URLs above, not
        # something every self-hoster needs to paste in by hand.
        "SUPABASE_ANON_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhnZnN4aWt5cHhqaHFsdXRpZXB3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIyNDg3MDcsImV4cCI6MjA5NzgyNDcwN30.2_OUNTHuKSeDJh6S-aUW16IqvDTmew8ZcFuKvFkt3Dk",
        # service_role key for the same Supabase project -- full admin
        # access, bypasses RLS entirely (unlike the anon key above). Baked
        # in per explicit instruction; be aware every deployment built
        # from this image carries this same admin power over the one
        # shared Supabase project. Overridable via `docker run -e
        # SUPABASE_SERVICE_KEY=...` if a deployment needs its own.
        "SUPABASE_SERVICE_KEY": os.getenv(
            "SUPABASE_SERVICE_KEY",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhnZnN4aWt5cHhqaHFsdXRpZXB3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MjI0ODcwNywiZXhwIjoyMDk3ODI0NzA3fQ.ErVC4rb7y6L__VhqEeWUc7bx3DcsqkldYBMSvmYYins",
        ),
        # Whatever public URL this deployment is reachable at (Tailscale
        # Funnel, real domain, ...). Can't be generated -- pass it via
        # `docker run -e NEURALOPS_SERVER_URL=...`; empty string (relative
        # avatar/media URLs) if not provided.
        "NEURALOPS_SERVER_URL": os.getenv("NEURALOPS_SERVER_URL", ""),
        "LOG_LEVEL": "INFO",
        # -- nexus-ai --------------------------------------------------------
        # EMBEDDING_DIM must match whatever EMBEDDING_MODEL below actually
        # produces -- 768 is nomic-ai/nomic-embed-text-v1.5's dimension.
        # Change both together if you ever swap the embedding model.
        "AGENT_BACKEND": "pydantic_ai",
        "LLM_PROVIDER": "litellm",
        "LLM_MODEL": "anthropic/claude-haiku-4-5-20251001",
        "EMBEDDING_PROVIDER": "fastembed",
        "EMBEDDING_MODEL": "nomic-ai/nomic-embed-text-v1.5",
        "EMBEDDING_BASE_URL": "",
        "EMBEDDING_DIM": "768",
        "VECTOR_STORE": "pgvector",
        "HISTORY_DEPTH": "20",
        # Not generated here -- these come from you, not randomly:
        # NEURALOPS_INSTALL_TOKEN (currently unused, leftover from a removed
        # device-activation flow), OPENAI_API_KEY, ANTHROPIC_API_KEY. Left
        # out on purpose rather than written as blanks -- add them to the
        # file after this script runs, per AI model, not globally.
    }

    if not env["NEURALOPS_SERVER_URL"]:
        print("NOTE: NEURALOPS_SERVER_URL not set (pass -e NEURALOPS_SERVER_URL=... to `docker run`) -- avatar/media links will be relative until you set it in app.env and restart nucleus.")

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    ENV_FILE.chmod(0o600)  # contains real secrets -- owner read/write only
    subprocess.run(["chown", "-R", "nexus:nexus", str(SECRETS_DIR)], check=True)

    print(f"Wrote {ENV_FILE} ({len(env)} variables). Postgres role/database NOT created yet -- run init-db once Postgres is up.")
    return env


def _pg_isready() -> bool:
    return subprocess.run(["su", "postgres", "-c", "pg_isready"], capture_output=True).returncode == 0


def _su_postgres(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(["su", "postgres", "-c", command], capture_output=True, text=True)


def _pg_bin_dir() -> str:
    version = next(Path("/usr/lib/postgresql").iterdir()).name
    return f"/usr/lib/postgresql/{version}/bin"


def _harden_pg_hba() -> None:
    """initdb defaults to trust auth (no password check at all) for both
    local and host connections -- fine for our own `su postgres -c psql`
    calls over the unix socket, but it would make the generated
    POSTGRES_PASSWORD meaningless for nucleus/nexus-ai's TCP connections.
    Only tightening the host (TCP, 127.0.0.1/::1) lines, leaving local
    (unix socket) as-is since that's what this script itself relies on."""
    hba = POSTGRES_DATA_DIR / "pg_hba.conf"
    text = hba.read_text()
    text = re.sub(r"(host\s+all\s+all\s+127\.0\.0\.1/32\s+)trust", r"\1scram-sha-256", text)
    text = re.sub(r"(host\s+all\s+all\s+::1/128\s+)trust", r"\1scram-sha-256", text)
    hba.write_text(text)


def _ensure_postgres_running(timeout_seconds: int = 30) -> None:
    """Initializes the data directory if empty, starts the server if it
    isn't running, and waits until it's actually accepting connections.
    Safe to call every time -- each step checks first, does nothing if
    already done."""
    if _pg_isready():
        return

    pg_bin = _pg_bin_dir()

    if not (POSTGRES_DATA_DIR / "PG_VERSION").exists():
        print("Initializing Postgres data directory...")
        # Dockerfile.base bakes `chown postgres:postgres` onto this path
        # at image-build time, but that only survives into a *named*
        # volume (Docker copies the image directory's content+ownership
        # into a named volume on first use). A bind-mounted host
        # directory overlays the mount as-is instead -- freshly created
        # by `docker run`, it comes out owned by root on the host, which
        # made initdb's internal `chmod 0700` fail with "Operation not
        # permitted" (the `postgres` user below is neither root nor the
        # owner). Fixing ownership here unconditionally -- this script
        # always runs as root via plain `docker exec` -- makes init-db
        # work the same whether POSTGRES_DATA_DIR is a named volume or a
        # bind mount, instead of silently depending on which one you pick.
        subprocess.run(["chown", "-R", "postgres:postgres", str(POSTGRES_DATA_DIR)], check=True)
        result = _su_postgres(f"{pg_bin}/initdb -D {POSTGRES_DATA_DIR}")
        if result.returncode != 0:
            print(f"ERROR: initdb failed\n{result.stderr}", file=sys.stderr)
            sys.exit(1)
        _harden_pg_hba()

    print("Starting Postgres...")
    result = _su_postgres(f"{pg_bin}/pg_ctl -D {POSTGRES_DATA_DIR} -l {POSTGRES_DATA_DIR}/logfile start")
    if result.returncode != 0:
        print(f"ERROR: pg_ctl start failed\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _pg_isready():
            return
        time.sleep(1)
    print("ERROR: Postgres did not become ready in time.", file=sys.stderr)
    sys.exit(1)


def _psql_scalar(sql: str) -> str:
    result = subprocess.run(
        ["su", "postgres", "-c", f'psql -tAc "{sql}"'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR running: {sql}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def _psql(sql: str) -> None:
    result = subprocess.run(
        ["su", "postgres", "-c", f'psql -v ON_ERROR_STOP=1 -c "{sql}"'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR running: {sql}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def init_db() -> None:
    """Reads the already-generated env file and reconciles the actual
    Postgres role/database against it. Idempotent -- checks existence
    first, so it's safe to call this on every container start."""
    if not ENV_FILE.exists():
        print(f"ERROR: {ENV_FILE} doesn't exist yet -- run generate-env first.", file=sys.stderr)
        sys.exit(1)

    env = _read_env_file()
    user, db, password = env["POSTGRES_USER"], env["POSTGRES_DB"], env["POSTGRES_PASSWORD"]

    _ensure_postgres_running()

    if _psql_scalar(f"SELECT 1 FROM pg_roles WHERE rolname='{user}'") == "1":
        print(f"Role {user} already exists -- leaving it alone.")
    else:
        _psql(f"CREATE ROLE {user} WITH LOGIN PASSWORD '{password}';")
        print(f"Created role {user}.")

    if _psql_scalar(f"SELECT 1 FROM pg_database WHERE datname='{db}'") == "1":
        print(f"Database {db} already exists -- leaving it alone.")
    else:
        _psql(f"CREATE DATABASE {db} OWNER {user};")
        print(f"Created database {db}.")

    print("init-db done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("step", nargs="?", choices=["generate-env", "init-db"], default=None)
    args = parser.parse_args()

    if args.step == "generate-env":
        generate_env()
    elif args.step == "init-db":
        init_db()
    else:
        generate_env()
        init_db()
