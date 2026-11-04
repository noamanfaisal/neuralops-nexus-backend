#!/usr/bin/env bash
# =============================================================================
# NeuralOps Nexus — one-command installer for Linux servers.
#
#   curl -fsSL https://raw.githubusercontent.com/noamanfaisal/neuralops-get/main/install.sh | bash
#
# What it does, in order (every step is safe to re-run):
#   1. checks the machine (Linux, x86_64/arm64, memory, disk), installs Docker if
#      missing (asks first);
#   2. asks ONE question — how the team reaches this server:
#        (1) this server has a public IP (AWS, Azure, Google, any cloud server)
#            -> we give it a FREE random https address <xxxxxx>.on.neuralopsnexus.ai
#               (default; certificate by Caddy). A fresh install may get a
#               different address; updates and restarts keep it.
#        (2) Tailscale      -> permanent HTTPS address via Tailscale Funnel
#      (Your own domain: --domain team.example.com — not part of the question.)
#   3. downloads the compose file + nginx config, writes the env files,
#      generates this install's secrets ONCE (never regenerated — that would
#      replace the live database password), fixes the projects folder owner;
#   4. configures Tailscale if chosen, starts everything, creates the vector
#      database, runs migrate + seed_permissions + seed_catalog, waits until
#      the server answers;
#   5. installs the `neuralops` command (status / update / logs / address /
#      backup / restart / stop / start / uninstall) and prints the address.
#
# Settings (environment variables or CLI arguments):
#   NEURALOPS_MODE=public (default), tailscale, or domain (your own domain)
#   NEURALOPS_PUBLIC_IP=1.2.3.4 (public mode: only when the server's public IP
#     differs from the one it reaches the internet from, e.g. a NAT gateway)
#   NEURALOPS_DOMAIN=team.example.com (for domain mode; or --domain <domain>)
#   NEURALOPS_OWNER_EMAIL=person@example.com (reserves demo ownership; or --email <email>)
#   NEURALOPS_TS_REACH=funnel (default) or serve
#   NEURALOPS_TS_AUTHKEY=tskey-auth-... (optional auth key for unattended installs)
#   NEURALOPS_TS_HOSTNAME=name (default neuralops)
#   NEURALOPS_YES=1 (unattended — never ask, take defaults; or -y/--yes)
#
# Testing from a local checkout (no network fetch of the files):
#   NEURALOPS_RAW=file:///path/to/neuralops-nexus bash install.sh
#
# Record: docs/MISSING.md (Stage 4, easy install — ruled 2026-10-24/25).
# =============================================================================
set -euo pipefail

# Detect Operating System & Architecture
OS_NAME="$(uname -s)"
ARCH="$(uname -m)"
OS_FAMILY="linux"

case "$OS_NAME" in
  Darwin*)
    OS_FAMILY="darwin"
    ;;
  Linux*)
    if grep -qi microsoft /proc/version 2>/dev/null; then
      OS_FAMILY="wsl"
    else
      OS_FAMILY="linux"
    fi
    ;;
  MINGW*|MSYS*|CYGWIN*)
    OS_FAMILY="windows"
    ;;
  *)
    OS_FAMILY="unknown"
    ;;
esac

NEURALOPS_VERSION="${NEURALOPS_VERSION:-1.1.6}"
NEURALOPS_REF="${NEURALOPS_REF:-main}"
# The installer's public home: ONLY install.sh, the compose file, the nginx
# config and the neuralops command — no app code (the code ships compiled in
# the image). Published from the private repo by hand.
NEURALOPS_RAW="${NEURALOPS_RAW:-https://raw.githubusercontent.com/noamanfaisal/neuralops-get/${NEURALOPS_REF}}"

if [ -z "${NEURALOPS_DIR:-}" ]; then
  case "$OS_FAMILY" in
    darwin|windows) NEURALOPS_DIR="$HOME/.neuralops" ;;
    *)              NEURALOPS_DIR="/opt/neuralops" ;;
  esac
fi

NEURALOPS_IMAGE_REPO="${NEURALOPS_IMAGE_REPO:-noamanfaisal/neuralops}"
NEURALOPS_MODE="${NEURALOPS_MODE:-}"
NEURALOPS_DOMAIN="${NEURALOPS_DOMAIN:-}"
NEURALOPS_OWNER_EMAIL="${NEURALOPS_OWNER_EMAIL:-}"
NEURALOPS_TS_REACH="${NEURALOPS_TS_REACH:-funnel}"
NEURALOPS_TS_AUTHKEY="${NEURALOPS_TS_AUTHKEY:-}"
NEURALOPS_TS_HOSTNAME="${NEURALOPS_TS_HOSTNAME:-neuralops}"
NEURALOPS_YES="${NEURALOPS_YES:-}"
NEURALOPS_PUBLIC_IP="${NEURALOPS_PUBLIC_IP:-}"
# Where Caddy (ports 80/443) listens: all addresses, unless another program
# holds 80/443 on a DIFFERENT address (see web_ports_free).
CADDY_BIND="${CADDY_BIND:-0.0.0.0}"
# The free-address service (portal/supabase/functions/claim-address).
NEURALOPS_ADDRESS_URL="${NEURALOPS_ADDRESS_URL:-https://xgfsxikypxjhqlutiepw.supabase.co/functions/v1/claim-address}"
# Supabase's PUBLIC anon key (the same one baked into every image and the web
# app; safe to publish, it grants nothing by itself) — so the function works
# whether or not "Verify JWT" is on.
NEURALOPS_ADDRESS_KEY="${NEURALOPS_ADDRESS_KEY:-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhnZnN4aWt5cHhqaHFsdXRpZXB3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIyNDg3MDcsImV4cCI6MjA5NzgyNDcwN30.2_OUNTHuKSeDJh6S-aUW16IqvDTmew8ZcFuKvFkt3Dk}"

MIN_MEM_KB=$((3500 * 1024))   # ~3.5 GB — the engine's ML stack needs room
MIN_DISK_KB=$((15 * 1024 * 1024))

# ── output ────────────────────────────────────────────────────────────────────
bold() { printf '\033[1m%s\033[0m\n' "$*"; }
say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n  \033[31m✘ %s\033[0m\n\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

# Questions read from the terminal, not stdin — stdin IS this script when it
# arrives through `curl | bash`.
ask() {  # ask "Question" "default" -> echoes the answer
  local question="$1" default="${2:-}" answer=""
  if [ -n "$NEURALOPS_YES" ] || [ ! -r /dev/tty ]; then
    printf '%s' "$default"; return
  fi
  if [ -n "$default" ]; then
    printf '  %s [%s]: ' "$question" "$default" > /dev/tty
  else
    printf '  %s: ' "$question" > /dev/tty
  fi
  read -r answer < /dev/tty || true
  printf '%s' "${answer:-$default}"
}
confirm() {  # confirm "Question" -> returns 0 on yes (default yes)
  local a
  a="$(ask "$1 (Y/n)" "y")"
  case "$a" in [Nn]*) return 1 ;; *) return 0 ;; esac
}

# ── privileges ────────────────────────────────────────────────────────────────
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  fi
fi

DOCKER=""
docker_cmd() {
  if docker info >/dev/null 2>&1; then DOCKER="docker"; elif [ -n "$SUDO" ]; then DOCKER="$SUDO docker"; else DOCKER="docker"; fi
}

# The compose invocation every step (and the `neuralops` helper) uses.
PROFILES=""
compose() {
  local profile_args=()
  local old_ifs="$IFS"
  IFS=','
  for p in $PROFILES; do
    [ -n "$p" ] && profile_args+=(--profile "$p")
  done
  IFS="$old_ifs"
  # shellcheck disable=SC2086  # $DOCKER is "docker" or "sudo docker" on purpose
  (cd "$NEURALOPS_DIR" && $DOCKER compose \
    "${profile_args[@]}" \
    -f docker-compose.neuralops.yaml \
    --env-file neuralops/infra.env --env-file neuralops/app.env --env-file neuralops/secrets.env \
    "$@")
}

fetch() {  # fetch <path-in-repo> <destination>
  curl -fsSL "$NEURALOPS_RAW/$1" -o "$2.tmp" || die "Could not download $1 from $NEURALOPS_RAW"
  mv "$2.tmp" "$2"
}

# ── 1. the machine ───────────────────────────────────────────────────────────
check_machine() {
  step "Checking this machine"
  case "$OS_FAMILY" in
    linux)   ok "OS: Linux ($ARCH)" ;;
    wsl)     ok "OS: Windows WSL2 ($ARCH)" ;;
    darwin)  ok "OS: macOS ($ARCH)" ;;
    windows) ok "OS: Windows ($ARCH)" ;;
    *) die "NeuralOps installer supports Linux, macOS, and Windows. Unknown OS: $OS_NAME" ;;
  esac

  case "$ARCH" in
    x86_64|amd64) ok "Architecture: $ARCH" ;;
    # 1.1.0 ships for Intel/AMD only; the ARM build follows.
    aarch64|arm64) die "This server is ARM ($ARCH). This version of NeuralOps ships for x86_64 (Intel/AMD) servers; ARM support is coming. Please use an x86_64 server." ;;
    *) die "This server is $ARCH. NeuralOps currently ships for x86_64 (Intel/AMD) and aarch64 (ARM64) servers only." ;;
  esac

  local mem_kb=0
  if [ "$OS_FAMILY" = "darwin" ]; then
    local mem_bytes
    mem_bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
    mem_kb=$((mem_bytes / 1024))
  elif [ -f /proc/meminfo ]; then
    mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
  fi

  if [ "$mem_kb" -gt 0 ]; then
    if [ "$mem_kb" -lt "$MIN_MEM_KB" ]; then
      warn "This machine has $((mem_kb / 1024)) MB of memory; NeuralOps wants at least 4 GB."
      confirm "Continue anyway?" || die "Stopped. Pick a machine with 4 GB of memory or more."
    else
      ok "Memory: $((mem_kb / 1024 / 1024)) GB"
    fi
  else
    ok "Memory: checked"
  fi

  local parent
  parent="$(dirname "$NEURALOPS_DIR")"
  mkdir -p "$parent" 2>/dev/null || true
  local disk_kb
  disk_kb="$(df -Pk "$parent" 2>/dev/null | awk 'END {print $4}' || echo 0)"
  if [ "$disk_kb" -gt 0 ] && [ "$disk_kb" -lt "$MIN_DISK_KB" ]; then
    warn "Only $((disk_kb / 1024 / 1024)) GB free at $parent; NeuralOps wants at least 15 GB."
    confirm "Continue anyway?" || die "Stopped. Free up disk space first."
  else
    ok "Disk: space available"
  fi
}

check_existing() {
  if [ -f "$NEURALOPS_DIR/neuralops/.installed" ]; then
    bold ""
    bold "  NeuralOps is already installed in $NEURALOPS_DIR."
    say "To upgrade: neuralops update · To see its address: neuralops address"
    echo
    exit 0
  fi

  if [ -f "$NEURALOPS_DIR/neuralops/secrets.env" ]; then
    warn "A previous install stopped part-way. Continuing it (your secrets are kept)."
    if [ -z "$NEURALOPS_MODE" ] && [ -f "$NEURALOPS_DIR/neuralops/install.conf" ]; then
      NEURALOPS_MODE="$(sed -n 's/^NEURALOPS_MODE=//p' "$NEURALOPS_DIR/neuralops/install.conf" || true)"
    fi
    if [ -z "$NEURALOPS_DOMAIN" ] && [ -f "$NEURALOPS_DIR/neuralops/infra.env" ]; then
      NEURALOPS_DOMAIN="$(sed -n 's/^NEURALOPS_DOMAIN=//p' "$NEURALOPS_DIR/neuralops/infra.env" || true)"
    fi
  fi
}

ensure_docker() {
  step "Docker"
  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker is not installed. NeuralOps runs inside Docker."
    case "$OS_FAMILY" in
      linux)
        confirm "Install Docker now (official script from get.docker.com)?" || die "Stopped. Install Docker, then run this again."
        curl -fsSL https://get.docker.com | ${SUDO:-} sh >/dev/null || die "Docker installation failed."
        if [ -n "$SUDO" ] && command -v systemctl >/dev/null 2>&1; then
          $SUDO systemctl enable --now docker >/dev/null 2>&1 || true
        fi
        ;;
      darwin)
        die "Docker is not installed. Please install Docker Desktop (https://www.docker.com/products/docker-desktop) or OrbStack (https://orbstack.dev), launch it, and run this installer again."
        ;;
      wsl|windows)
        die "Docker is not installed. Please install Docker Desktop for Windows with WSL2 enabled (https://www.docker.com/products/docker-desktop), launch it, and run this installer again."
        ;;
      *)
        die "Please install Docker and run this installer again."
        ;;
    esac
  fi

  docker_cmd

  if ! $DOCKER info >/dev/null 2>&1; then
    die "Docker daemon is not running. Please start Docker (e.g. launch Docker Desktop or start the docker service) and run this installer again."
  fi

  $DOCKER compose version >/dev/null 2>&1 || die "Docker is installed but 'docker compose' is missing. Install the Docker Compose plugin, then run this again."
  ok "$($DOCKER --version)"
}

is_port_busy() {
  local p="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$p$"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | grep -Eq "(LISTEN|LISTENING).*[:.]${p}[[:space:]]"
  else
    return 1
  fi
}

# The address this machine's internet traffic leaves from (on a cloud server
# behind 1:1 NAT, like AWS, the private address its public IP forwards to).
main_ip() {
  ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1
}

# Ports 80 + 443 for Caddy. Taken for us = something holds them on ALL
# addresses or on the main address. Held only on ANOTHER address (Tailscale's
# own 443 on its 100.x address, say) = still usable: Caddy then listens on the
# main address only (CADDY_BIND), which is where the public traffic arrives.
web_ports_free() {
  CADDY_BIND="0.0.0.0"
  if ! command -v ss >/dev/null 2>&1; then
    if is_port_busy 80 || is_port_busy 443; then return 1; fi
    return 0
  fi
  local p addrs main held_all=0 held_other=0
  main="$(main_ip)"
  for p in 80 443; do
    addrs="$(ss -ltnH 2>/dev/null | awk '{print $4}' | grep -E ":${p}\$" || true)"
    [ -n "$addrs" ] || continue
    if printf '%s\n' "$addrs" | grep -Eq "^(0\\.0\\.0\\.0|\\*|\\[::\\]|${main//./\\.}):${p}\$"; then
      held_all=1
    else
      held_other=1
    fi
  done
  [ "$held_all" -eq 0 ] || return 1
  if [ "$held_other" -eq 1 ]; then
    [ -n "$main" ] || return 1
    CADDY_BIND="$main"
  fi
  return 0
}

# ── 2. how the team reaches it ───────────────────────────────────────────────
choose_access() {
  step "How will you reach NeuralOps?"
  if [ -z "$NEURALOPS_MODE" ]; then
    say "  1) This server has a public IP (AWS, Azure, Google, DigitalOcean, any cloud server)"
    say "     we give it a free https address; ports 80 and 443 must be open"
    say "  2) Tailscale (for a machine at home or in the office)"
    say "     a permanent secure address; needs a free Tailscale account"
    case "$(ask "Choose 1 or 2" "1")" in
      2) NEURALOPS_MODE="tailscale" ;;
      *) NEURALOPS_MODE="public" ;;
    esac
  fi

  case "$NEURALOPS_MODE" in
    public)
      $DOCKER rm -f neuralops-claim-check >/dev/null 2>&1 || true  # a stopped earlier run's check
      if ! web_ports_free; then
        if [ -n "$($DOCKER ps -q --filter "name=neuralops-caddy" 2>/dev/null || true)" ]; then
          $DOCKER stop neuralops-caddy >/dev/null 2>&1 || true
        fi
        web_ports_free || die "Something on this machine already uses port 80 or 443 (another web server?). Stop it, or use option 2 (Tailscale)."
      fi
      if [ "$CADDY_BIND" != "0.0.0.0" ]; then
        ok "Ports 80/443 are used elsewhere on another address; NeuralOps will listen on $CADDY_BIND"
      fi
      PROFILES="production,https"
      SERVER_URL=""   # known once the address is claimed
      ok "A free address will be set up for this server"
      ;;
    tailscale)
      PROFILES="production"
      SERVER_URL=""   # known once Tailscale is configured
      ok "Tailscale address will be configured"
      ;;
    domain)
      if [ -z "$NEURALOPS_DOMAIN" ]; then
        NEURALOPS_DOMAIN="$(ask "Your domain (e.g. team.example.com)" "")"
      fi
      NEURALOPS_DOMAIN="${NEURALOPS_DOMAIN#http://}"
      NEURALOPS_DOMAIN="${NEURALOPS_DOMAIN#https://}"
      NEURALOPS_DOMAIN="${NEURALOPS_DOMAIN%%/*}"
      [ -n "$NEURALOPS_DOMAIN" ] || die "A domain is needed for option 2."
      if ! web_ports_free; then
        if [ -n "$($DOCKER ps -q --filter "name=neuralops-caddy" 2>/dev/null || true)" ]; then
          $DOCKER stop neuralops-caddy >/dev/null 2>&1 || true
        fi
        web_ports_free || die "Something on this machine already uses port 80 or 443 (another web server?). Stop it, or use Tailscale."
      fi
      PROFILES="production,https"
      SERVER_URL="https://$NEURALOPS_DOMAIN"
      ok "Domain: $NEURALOPS_DOMAIN (its DNS must point at this server for the certificate)"
      ;;
    *) die "NEURALOPS_MODE must be 'public', 'tailscale' or 'domain'." ;;
  esac
}

# ── 3. files, env, secrets ───────────────────────────────────────────────────
prepare_files() {
  step "Preparing $NEURALOPS_DIR"
  local me
  me="$(id -u):$(id -g)"

  local parent
  parent="$(dirname "$NEURALOPS_DIR")"
  if [ -w "$parent" ] || { [ ! -d "$parent" ] && [ -w "$(dirname "$parent" 2>/dev/null || echo .)" ]; }; then
    mkdir -p "$NEURALOPS_DIR/neuralops" "$NEURALOPS_DIR/projects" "$NEURALOPS_DIR/backups"
  elif [ -n "$SUDO" ]; then
    $SUDO mkdir -p "$NEURALOPS_DIR/neuralops" "$NEURALOPS_DIR/projects" "$NEURALOPS_DIR/backups"
    $SUDO chown "$me" "$NEURALOPS_DIR" "$NEURALOPS_DIR/neuralops" "$NEURALOPS_DIR/backups" 2>/dev/null || true
  else
    mkdir -p "$NEURALOPS_DIR/neuralops" "$NEURALOPS_DIR/projects" "$NEURALOPS_DIR/backups"
  fi
  chmod 700 "$NEURALOPS_DIR/backups"

  fetch docker-compose.neuralops.yaml "$NEURALOPS_DIR/docker-compose.neuralops.yaml"
  fetch neuralops/nginx.conf "$NEURALOPS_DIR/neuralops/nginx.conf"
  ok "Downloaded the compose file and nginx config"

  # The free address comes first in public mode: infra.env and app.env below
  # carry it (Caddy's certificate and the server's own URL).
  if [ "$NEURALOPS_MODE" = "public" ]; then claim_address; fi

  cat > "$NEURALOPS_DIR/neuralops/infra.env" <<EOF
# Written by install.sh — the installer's settings for this server.
COMPOSE_PROJECT_NAME=neuralops
NEURALOPS_IMAGE=${NEURALOPS_IMAGE_REPO}:${NEURALOPS_VERSION}
POSTGRES_DB=neuralops
POSTGRES_USER=neuralops
NEURALOPS_DOMAIN=${NEURALOPS_DOMAIN}
# nginx answers on this machine only: Caddy (domain mode) or Tailscale front it.
NGINX_BIND=127.0.0.1
# Where Caddy listens for 80/443 (0.0.0.0 = every address).
CADDY_BIND=${CADDY_BIND}
EOF
  # The helper reads these back; profiles travel in the shell, never relying
  # on an env file to pick them.
  cat > "$NEURALOPS_DIR/neuralops/install.conf" <<EOF
NEURALOPS_DIR=${NEURALOPS_DIR}
NEURALOPS_RAW=${NEURALOPS_RAW}
NEURALOPS_IMAGE_REPO=${NEURALOPS_IMAGE_REPO}
NEURALOPS_MODE=${NEURALOPS_MODE}
PROFILES=${PROFILES}
NEURALOPS_ADDRESS_URL=${NEURALOPS_ADDRESS_URL}
NEURALOPS_ADDRESS_KEY=${NEURALOPS_ADDRESS_KEY}
NEURALOPS_PUBLIC_IP=${NEURALOPS_PUBLIC_IP}
EOF
  write_app_env "${SERVER_URL:-http://localhost:8095}"

  # Secrets: generated ONCE. An existing file is never touched.
  if [ ! -f "$NEURALOPS_DIR/neuralops/secrets.env" ]; then
    # An old database volume WITHOUT its secrets file would refuse the new
    # password (postgres keeps the one it was created with). Nothing is ever
    # deleted: the old database is copied into a dated backup volume, and
    # only then is the original cleared so this install starts fresh.
    set_aside_old_database neuralops_neuralops_postgres_data
    step "Downloading NeuralOps (a few GB the first time; this takes a few minutes)"
    $DOCKER pull "${NEURALOPS_IMAGE_REPO}:${NEURALOPS_VERSION}"
    ( umask 077
      $DOCKER run --rm "${NEURALOPS_IMAGE_REPO}:${NEURALOPS_VERSION}" init-secrets > "$NEURALOPS_DIR/neuralops/secrets.env.tmp" )
    grep -q '^SECRET_KEY=' "$NEURALOPS_DIR/neuralops/secrets.env.tmp" || die "Generating this install's secrets failed."
    mv "$NEURALOPS_DIR/neuralops/secrets.env.tmp" "$NEURALOPS_DIR/neuralops/secrets.env"
    ok "Generated this install's own secrets (kept in neuralops/secrets.env, never regenerated)"
  fi

  # The engine runs as UID 1000 and writes project files here.
  if [ "$OS_FAMILY" = "linux" ] || [ "$OS_FAMILY" = "wsl" ]; then
    if [ -n "$SUDO" ]; then
      $SUDO chown -R 1000:1000 "$NEURALOPS_DIR/projects" 2>/dev/null || true
    fi
  fi
  ok "Projects folder ready"
}

set_aside_old_database() {  # <the database volume>
  local old="$1" backup holders
  $DOCKER volume inspect "$old" >/dev/null 2>&1 || return 0
  backup="neuralops_old_postgres_$(date +%Y%m%d-%H%M%S)"
  warn "An earlier NeuralOps database is on this machine, but its secrets file is gone, so it cannot be opened."
  say "It will be KEPT as a backup (Docker volume $backup), and this install starts with a fresh database."
  confirm "Continue?" || die "Stopped. Nothing was changed."

  # A stopped container from that earlier install still holds the volume;
  # it is recreated below anyway. A RUNNING one means NeuralOps is in use.
  holders="$($DOCKER ps -aq --filter "volume=$old" 2>/dev/null || true)"
  if [ -n "$($DOCKER ps -q --filter "volume=$old" 2>/dev/null || true)" ]; then
    die "That earlier database is in use by a running container ($($DOCKER ps --filter "volume=$old" --format '{{.Names}}' | tr '\n' ' ')). Stop it first, then run this installer again."
  fi

  $DOCKER volume create "$backup" >/dev/null || die "Could not create the backup volume; nothing was changed."
  $DOCKER run --rm -v "$old:/from:ro" -v "$backup:/to" alpine:3.20 sh -c 'cp -a /from/. /to/' >/dev/null \
    || die "Could not copy the earlier database aside; nothing was removed."
  if [ -n "$holders" ]; then
    # shellcheck disable=SC2086  # one id per word on purpose
    $DOCKER rm $holders >/dev/null || die "Could not remove the stopped containers of the earlier install; the database backup is in $backup."
  fi
  $DOCKER volume rm "$old" >/dev/null || die "Could not clear the earlier database; it is also backed up in $backup."
  ok "Earlier database kept as Docker volume $backup (remove it when you no longer need it: docker volume rm $backup)"
}

write_app_env() {
  cat > "$NEURALOPS_DIR/neuralops/app.env" <<EOF
# Written by install.sh. The public address of THIS server.
NEURALOPS_SERVER_URL=$1
CENTRIFUGO_ALLOWED_ORIGINS=$1
EOF
}

# ── 3b. the free address (public mode) ──────────────────────────────────────
# Our address service (portal/supabase/functions/claim-address) gives this
# server a random <xxxxxx>.on.neuralopsnexus.ai. To prove the IP is really
# this server and that port 80 is open, a throwaway web server answers one
# random token on port 80 while the service checks. The answer is kept in
# neuralops/address.env (with the private code that lets this server move
# the name when its IP changes, and give it back on uninstall) — so a
# resumed install, an update or a restart keeps the same address.
claim_address() {
  step "Getting this server's address"
  local addr_file="$NEURALOPS_DIR/neuralops/address.env"
  local ip=""
  if [ -f "$addr_file" ]; then
    NEURALOPS_DOMAIN="$(sed -n 's/^NEURALOPS_DOMAIN=//p' "$addr_file")"
    ip="$(sed -n 's/^NEURALOPS_PUBLIC_IP=//p' "$addr_file")"
  fi

  if [ -z "$NEURALOPS_DOMAIN" ]; then
    local token webroot body answer status reason
    token="$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    webroot="$NEURALOPS_DIR/neuralops/claim-check"
    mkdir -p "$webroot/.well-known/neuralops-claim"
    printf '%s' "$token" > "$webroot/.well-known/neuralops-claim/$token"
    chmod -R a+rX "$webroot"
    $DOCKER rm -f neuralops-claim-check >/dev/null 2>&1 || true
    $DOCKER run -d --rm --name neuralops-claim-check -p "$CADDY_BIND:80:80" \
      -v "$webroot:/usr/share/nginx/html:ro" nginx:alpine >/dev/null \
      || die "Could not open port 80 on this machine for the address check."
    sleep 2

    body="{\"action\":\"claim\",\"format\":\"env\",\"token\":\"$token\""
    if [ -n "$NEURALOPS_PUBLIC_IP" ]; then body="$body,\"ip\":\"$NEURALOPS_PUBLIC_IP\""; fi
    body="$body}"
    # -4: the address is an IPv4 (A) record, so ask over IPv4.
    answer="$(curl -4 -sS --max-time 60 -X POST -H 'Content-Type: application/json' \
      -H "Authorization: Bearer $NEURALOPS_ADDRESS_KEY" \
      -d "$body" -w '\n%{http_code}' "$NEURALOPS_ADDRESS_URL" 2>&1 || true)"
    status="${answer##*$'\n'}"
    answer="${answer%$'\n'*}"
    $DOCKER rm -f neuralops-claim-check >/dev/null 2>&1 || true
    rm -rf "$webroot"

    if [ "$status" != "200" ]; then
      reason="$(printf '%s\n' "$answer" | sed -n 's/^ERROR=//p' | head -1)"
      [ -n "$reason" ] || reason="The address service could not be reached ($(printf '%s' "$answer" | head -c 200))."
      die "$reason"
    fi
    NEURALOPS_DOMAIN="$(printf '%s\n' "$answer" | sed -n 's/^NEURALOPS_DOMAIN=//p')"
    ip="$(printf '%s\n' "$answer" | sed -n 's/^NEURALOPS_PUBLIC_IP=//p')"
    local code
    code="$(printf '%s\n' "$answer" | sed -n 's/^NEURALOPS_ADDRESS_CODE=//p')"
    case "$NEURALOPS_DOMAIN" in
      *.on.neuralopsnexus.ai) ;;
      *) die "The address service gave an unexpected answer. Try again in a few minutes, or use option 2 (Tailscale)." ;;
    esac
    ( umask 077
      printf 'NEURALOPS_DOMAIN=%s\nNEURALOPS_PUBLIC_IP=%s\nNEURALOPS_ADDRESS_CODE=%s\n' \
        "$NEURALOPS_DOMAIN" "$ip" "$code" > "$addr_file" )
    ok "Address: https://$NEURALOPS_DOMAIN (points at $ip)"
  else
    ok "Address kept from the earlier run: https://$NEURALOPS_DOMAIN"
  fi
  SERVER_URL="https://$NEURALOPS_DOMAIN"

  # Caddy asks for the certificate as soon as it starts; give the new name a
  # moment to be visible first (it usually is within a minute). Caddy keeps
  # retrying by itself if it is not.
  if command -v getent >/dev/null 2>&1 && [ -n "$ip" ]; then
    printf '  Waiting for the address to go live'
    local live=0
    for _ in $(seq 1 60); do
      if getent hosts "$NEURALOPS_DOMAIN" 2>/dev/null | grep -qF "$ip"; then live=1; break; fi
      printf '.'
      sleep 3
    done
    echo
    if [ "$live" -eq 0 ]; then warn "The address is not visible yet; the certificate will follow once it is."; fi
  fi
}

# Public mode: a cloud server's IP can change (AWS gives a new one after every
# stop/start). A small timer runs `neuralops address --quiet` at boot and every
# 6 hours (most IP changes come with a reboot, which the boot run catches);
# it moves the name to the new IP when needed and does nothing otherwise.
setup_address_sync() {
  [ "$NEURALOPS_MODE" = "public" ] || return 0
  local cli="$NEURALOPS_DIR/neuralops/neuralops-cli.sh"
  if [ "$OS_FAMILY" = "linux" ] && command -v systemctl >/dev/null 2>&1 && [ -d /etc/systemd/system ]; then
    if printf '[Unit]\nDescription=Keep the NeuralOps address pointed at this server\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=oneshot\nExecStart=%s address --quiet\n' "$cli" \
         | ${SUDO:-} tee /etc/systemd/system/neuralops-address.service >/dev/null \
      && printf '[Unit]\nDescription=Check the NeuralOps address at boot and every 6 hours\n\n[Timer]\nOnBootSec=1min\nOnUnitActiveSec=6h\n\n[Install]\nWantedBy=timers.target\n' \
         | ${SUDO:-} tee /etc/systemd/system/neuralops-address.timer >/dev/null \
      && ${SUDO:-} systemctl daemon-reload >/dev/null 2>&1 \
      && ${SUDO:-} systemctl enable --now neuralops-address.timer >/dev/null 2>&1; then
      ok "The address follows this server if its IP changes (checked at boot and every 6 hours)"
      return 0
    fi
  fi
  warn "If this server's IP ever changes, run:  neuralops address"
}

# ── 4. Tailscale setup ────────────────────────────────────────────────────────
setup_tailscale() {
  step "Setting up Tailscale"
  local ts_cmd="tailscale"
  if [ "$OS_FAMILY" = "linux" ] && [ -n "$SUDO" ]; then
    ts_cmd="$SUDO tailscale"
  fi

  if ! command -v tailscale >/dev/null 2>&1; then
    case "$OS_FAMILY" in
      linux)
        say "Installing Tailscale (official script from tailscale.com)"
        curl -fsSL https://tailscale.com/install.sh | ${SUDO:-} sh >/dev/null || die "Tailscale installation failed."
        if [ -n "$SUDO" ] && command -v systemctl >/dev/null 2>&1; then
          $SUDO systemctl enable --now tailscaled >/dev/null 2>&1 || true
        fi
        ;;
      darwin)
        die "Tailscale is not installed. Please install Tailscale for Mac (https://tailscale.com/download/mac), launch and sign in, then run this installer again."
        ;;
      wsl|windows)
        die "Tailscale is not installed. Please install Tailscale for Windows (https://tailscale.com/download/windows), launch and sign in, then run this installer again."
        ;;
      *)
        die "Tailscale is not installed. Please install Tailscale (https://tailscale.com/download) and run this installer again."
        ;;
    esac
  fi

  local state
  state="$($ts_cmd status --json 2>/dev/null | grep -m1 '"BackendState"' | sed -nE 's/.*"BackendState": *"([^"]+)".*/\1/p' || true)"
  if [ "$state" != "Running" ]; then
    if [ -n "$NEURALOPS_TS_AUTHKEY" ]; then
      $ts_cmd up --authkey="$NEURALOPS_TS_AUTHKEY" --hostname="$NEURALOPS_TS_HOSTNAME" || die "Tailscale connection failed."
    else
      if [ -n "$NEURALOPS_YES" ]; then
        say "An unattended install without an auth key cannot sign in by itself. Please open the link below:"
      fi
      $ts_cmd up --hostname="$NEURALOPS_TS_HOSTNAME" >/dev/null 2>&1 &
      local up_pid=$!
      local auth_url=""
      local start_time
      start_time="$(date +%s)"
      local now

      while true; do
        now="$(date +%s)"
        if [ $((now - start_time)) -gt 600 ]; then
          kill "$up_pid" 2>/dev/null || true
          die "Waiting for the Tailscale sign-in timed out. Run the installer again; it will continue where it stopped."
        fi
        auth_url="$($ts_cmd status --json 2>/dev/null | grep -m1 '"AuthURL"' | sed -nE 's/.*"AuthURL": *"(https:\/\/[^"]+)".*/\1/p' || true)"
        if [ -n "$auth_url" ]; then
          break
        fi
        state="$($ts_cmd status --json 2>/dev/null | grep -m1 '"BackendState"' | sed -nE 's/.*"BackendState": *"([^"]+)".*/\1/p' || true)"
        if [ "$state" = "Running" ]; then
          break
        fi
        sleep 2
      done

      if [ -n "$auth_url" ]; then
        echo
        bold "  ┌──────────────────────────────────────────────────────────────┐"
        bold "  │  Sign in to Tailscale to connect this machine:               │"
        bold "  │  $auth_url"
        bold "  │  Open it on your phone or laptop. No account yet? It's free. │"
        bold "  └──────────────────────────────────────────────────────────────┘"
        echo
        printf '  Waiting for Tailscale sign-in'
        while true; do
          now="$(date +%s)"
          if [ $((now - start_time)) -gt 600 ]; then
            kill "$up_pid" 2>/dev/null || true
            echo
            die "Waiting for the Tailscale sign-in timed out. Run the installer again; it will continue where it stopped."
          fi
          state="$($ts_cmd status --json 2>/dev/null | grep -m1 '"BackendState"' | sed -nE 's/.*"BackendState": *"([^"]+)".*/\1/p' || true)"
          if [ "$state" = "Running" ]; then
            echo
            break
          fi
          printf '.'
          sleep 3
        done
      fi
    fi
  fi

  case "$NEURALOPS_TS_REACH" in
    serve)
      $ts_cmd serve --bg 8095 >/dev/null 2>&1 || die "Tailscale serve failed."
      ;;
    *)
      if ! $ts_cmd funnel status 2>&1 | grep -q "8095"; then
        local fn_tmp
        fn_tmp="$(mktemp)"
        $ts_cmd funnel --bg 8095 > "$fn_tmp" 2>&1 &
        local fn_pid=$!
        local fn_start
        fn_start="$(date +%s)"
        local fn_url=""
        local fn_now

        while true; do
          fn_now="$(date +%s)"
          if [ $((fn_now - fn_start)) -gt 600 ]; then
            kill "$fn_pid" 2>/dev/null || true
            rm -f "$fn_tmp"
            die "Waiting for the Tailscale sign-in timed out. Run the installer again; it will continue where it stopped."
          fi

          if $ts_cmd funnel status 2>&1 | grep -qE "8095|https://"; then
            break
          fi

          fn_url="$(grep -o 'https://login\.tailscale\.com/[^ ]*' "$fn_tmp" | head -1 || true)"
          if [ -n "$fn_url" ]; then
            echo
            bold "  ┌──────────────────────────────────────────────────────────────┐"
            bold "  │  Allow this machine to be reached with a link:               │"
            bold "  │  $fn_url"
            bold "  │  Open it on your phone or laptop to enable Tailscale Funnel. │"
            bold "  └──────────────────────────────────────────────────────────────┘"
            echo
            printf '  Waiting for Funnel approval'
            while true; do
              fn_now="$(date +%s)"
              if [ $((fn_now - fn_start)) -gt 600 ]; then
                kill "$fn_pid" 2>/dev/null || true
                rm -f "$fn_tmp"
                echo
                die "Waiting for the Tailscale sign-in timed out. Run the installer again; it will continue where it stopped."
              fi
              if $ts_cmd funnel status 2>&1 | grep -qE "8095|https://"; then
                echo
                break
              fi
              printf '.'
              sleep 3
            done
            break
          fi
          sleep 2
        done
        rm -f "$fn_tmp"
      fi
      ;;
  esac

  local name
  name="$($ts_cmd status --json 2>/dev/null | grep -m1 '"DNSName"' | sed -nE 's/.*"DNSName": *"([^"]+)".*/\1/p' | sed 's/\.$//' || true)"
  [ -n "$name" ] || die "Tailscale is connected but has no name for this machine. Check MagicDNS is on in the Tailscale admin page, then run the installer again."
  SERVER_URL="https://$name"
  write_app_env "$SERVER_URL"
  ok "Address: $SERVER_URL"
}

wait_for() {  # wait_for "what" seconds command...
  local what="$1" secs="$2"; shift 2
  for _ in $(seq 1 "$secs"); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  die "Timed out waiting for $what. See: neuralops logs"
}

first_run_setup() {
  step "Starting NeuralOps"
  compose up -d postgres redis nucleus
  ok "Core services started"

  # shellcheck disable=SC2086  # $DOCKER is one or two words on purpose
  wait_for "the database" 120 $DOCKER exec neuralops-postgres pg_isready -U neuralops
  # shellcheck disable=SC2016,SC2086  # the $VARS expand inside the container, on purpose
  wait_for "the vector store" 60 $DOCKER exec neuralops-postgres sh -c '
    psql -U "$POSTGRES_USER" -lqt | cut -d"|" -f1 | grep -qw nexus_vectors \
      || psql -U "$POSTGRES_USER" -q -c "CREATE DATABASE nexus_vectors"
    psql -U "$POSTGRES_USER" -d nexus_vectors -q -c "CREATE EXTENSION IF NOT EXISTS vector"
  '
  ok "Database ready (with the vector store)"

  # Single-process bootstrap: loads Django once, runs check, migrate, permissions, catalog & owner reservation
  wait_for "the server process" 60 $DOCKER exec neuralops-nucleus sh -c 'test -f /nexus/nucleus/manage.py'
  $DOCKER exec -w /nexus/nucleus -e PYTHONPATH=/nexus/nucleus -e DJANGO_SETTINGS_MODULE=core.settings neuralops-nucleus /opt/venv/nucleus-env/bin/python -c '
import os, sys, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()
from django.core.management import call_command

call_command("check")
call_command("migrate", interactive=False)
call_command("seed_permissions")
try:
    call_command("seed_catalog")
except Exception as e:
    print("Warning: seed_catalog failed:", e, file=sys.stderr)

email = sys.argv[1].strip() if len(sys.argv) > 1 else ""
if email:
    try:
        call_command("create_owner", email=email)
    except Exception as e:
        print("Warning: create_owner failed:", e, file=sys.stderr)
' "$NEURALOPS_OWNER_EMAIL" >/dev/null || die "Setting up the database tables failed. See: neuralops logs nucleus"
  ok "Database set up"

  # Start the remaining services (workers, AI engine, proxy)
  compose up -d
  ok "All services started"

  wait_for "the server to answer" 120 sh -c \
    "curl -s -o /dev/null -w '%{http_code}' http://localhost:8095/api/v1/projects/ | grep -Eq '^(401|403)$'"
  ok "Server is answering"
}

# ── 5. the helper command ────────────────────────────────────────────────────
install_helper() {
  step "Installing the 'neuralops' command"
  fetch neuralops/neuralops-cli.sh "$NEURALOPS_DIR/neuralops/neuralops-cli.sh"
  chmod 755 "$NEURALOPS_DIR/neuralops/neuralops-cli.sh"

  local bin_dir=""
  for d in /usr/local/bin /opt/homebrew/bin "${HOME:-/root}/.local/bin" "${HOME:-/root}/bin"; do
    if [ -d "$d" ]; then
      bin_dir="$d"
      break
    fi
  done

  local linked=0
  if [ -n "$bin_dir" ]; then
    if [ -w "$bin_dir" ]; then
      ln -sf "$NEURALOPS_DIR/neuralops/neuralops-cli.sh" "$bin_dir/neuralops" && linked=1
    elif [ -n "$SUDO" ]; then
      $SUDO ln -sf "$NEURALOPS_DIR/neuralops/neuralops-cli.sh" "$bin_dir/neuralops" 2>/dev/null && linked=1
    fi
  fi

  if [ "$linked" -eq 1 ]; then
    ok "Installed neuralops to $bin_dir/neuralops"
  else
    warn "Could not create global symlink in PATH. You can run: $NEURALOPS_DIR/neuralops/neuralops-cli.sh"
  fi
  ok "Try: neuralops status"
}

finish() {
  local url="$SERVER_URL"
  echo
  bold "  ┌────────────────────────────────────────────────────────────┐"
  bold "  │  ✅  NeuralOps Nexus is running                             │"
  bold "  └────────────────────────────────────────────────────────────┘"
  echo
  say "Your server address:   $url"
  if [ "$NEURALOPS_MODE" = "public" ]; then
    say "(A free address. Updates and restarts keep it; a fresh install gets a new one."
    say " The HTTPS certificate is fetched on the first visit and can take a minute.)"
  elif [ "$NEURALOPS_MODE" = "domain" ]; then
    say "(The HTTPS certificate is fetched on the first visit and can take a minute.)"
  elif [ "$NEURALOPS_MODE" = "tailscale" ]; then
    say "Anyone with this address can open the sign-in page; only people you invite can get in."
  fi
  echo
  say "Next:"
  say "  1. Open  https://neuralopsnexus.ai  and sign in (or create an account)."
  say "  2. Add a server and paste:  $url"
  if [ -n "$NEURALOPS_OWNER_EMAIL" ]; then
    say "  3. This server is reserved for $NEURALOPS_OWNER_EMAIL (you become the owner upon sign-in)."
  else
    say "  3. The app shows a short code. Claim the server with it; you become its owner."
  fi
  echo
  say "Useful commands:  neuralops status | neuralops update | neuralops logs | neuralops backup"
  echo
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --email|--owner-email)
        NEURALOPS_OWNER_EMAIL="${2:-}"
        shift 2 || true
        ;;
      --email=*)
        NEURALOPS_OWNER_EMAIL="${1#*=}"
        shift
        ;;
      --owner-email=*)
        NEURALOPS_OWNER_EMAIL="${1#*=}"
        shift
        ;;
      --domain)
        NEURALOPS_DOMAIN="${2:-}"
        NEURALOPS_MODE="domain"
        shift 2 || true
        ;;
      --domain=*)
        NEURALOPS_DOMAIN="${1#*=}"
        NEURALOPS_MODE="domain"
        shift
        ;;
      --yes|-y)
        NEURALOPS_YES=1
        shift
        ;;
      *)
        shift
        ;;
    esac
  done

  echo
  bold "  NeuralOps Nexus — installer (version $NEURALOPS_VERSION)"
  check_existing
  check_machine
  ensure_docker
  choose_access
  prepare_files
  if [ "$NEURALOPS_MODE" = "tailscale" ]; then setup_tailscale; fi
  first_run_setup
  install_helper
  setup_address_sync
  date -u +"%Y-%m-%dT%H:%M:%SZ" > "$NEURALOPS_DIR/neuralops/.installed"
  finish
}

# A test may source this file to run one step (NEURALOPS_TEST_SOURCE=1);
# every real run — including `curl | bash` — starts main.
if [ "${NEURALOPS_TEST_SOURCE:-}" != "1" ]; then main "$@"; fi
