#!/usr/bin/env bash
# =============================================================================
# neuralops — manage this NeuralOps Nexus install. Installed by install.sh as
# /usr/local/bin/neuralops (a link to neuralops/neuralops-cli.sh in the
# install folder). Reads the install's settings from neuralops/install.conf.
#
#   neuralops status      what is running, the address, the version
#   neuralops address     the current address (tailscale: re-syncs if renamed;
#                         free address: moves it to this server's IP if that
#                         changed — a timer runs `address --quiet` at boot
#                         and every 6 hours)
#   neuralops update [V]  back up, then upgrade to version V (default: latest)
#   neuralops backup      database + secrets + project files into backups/
#   neuralops restore D   put a backup folder back: database + project files
#                         (secrets only onto a fresh install, or with --use-backup-secrets)
#   neuralops logs [svc]  follow the logs (all services, or one: nucleus, nexus-ai…)
#   neuralops restart | stop | start
#   neuralops uninstall   remove the containers; data is kept unless you ask
#
# Never runs `docker compose down -v`: data volumes are only ever removed by
# name, inside uninstall, after the person types DELETE.
# =============================================================================
set -euo pipefail

resolve_symlink() {
  local target="$1"
  while [ -L "$target" ]; do
    local link
    link="$(readlink "$target")"
    case "$link" in
      /*) target="$link" ;;
      *) target="$(dirname "$target")/$link" ;;
    esac
  done
  echo "$target"
}
REAL_SCRIPT="$(resolve_symlink "$0")"
SELF_DIR="$(cd "$(dirname "$REAL_SCRIPT")" && pwd)"
# shellcheck source=/dev/null
. "$SELF_DIR/install.conf"

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi
if docker info >/dev/null 2>&1; then DOCKER="docker"; elif [ -n "$SUDO" ]; then DOCKER="$SUDO docker"; else DOCKER="docker"; fi

TS_CMD="tailscale"
if [ "$(uname -s)" = "Linux" ] && [ -n "$SUDO" ]; then
  TS_CMD="$SUDO tailscale"
fi

say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n  \033[31m✘ %s\033[0m\n\n' "$*" >&2; exit 1; }

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
manage() {
  # shellcheck disable=SC2086
  $DOCKER exec -w /nexus/nucleus -e PYTHONPATH=/nexus/nucleus neuralops-nucleus \
    /opt/venv/nucleus-env/bin/python manage.py "$@"
}
server_url() { sed -n 's/^NEURALOPS_SERVER_URL=//p' "$NEURALOPS_DIR/neuralops/app.env"; }
ADDRESS_URL="${NEURALOPS_ADDRESS_URL:-https://xgfsxikypxjhqlutiepw.supabase.co/functions/v1/claim-address}"
ADDRESS_FILE="$NEURALOPS_DIR/neuralops/address.env"
# Supabase's PUBLIC anon key (see install.sh) — grants nothing by itself.
ADDRESS_KEY="${NEURALOPS_ADDRESS_KEY:-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhnZnN4aWt5cHhqaHFsdXRpZXB3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIyNDg3MDcsImV4cCI6MjA5NzgyNDcwN30.2_OUNTHuKSeDJh6S-aUW16IqvDTmew8ZcFuKvFkt3Dk}"

# address_call <action> → POSTs to the free-address service with this
# server's name and private code; prints the answer's KEY=value lines, or the
# service's reason on stderr and returns 1.
address_call() {
  local action="$1" host code body answer status reason
  host="$(sed -n 's/^NEURALOPS_DOMAIN=//p' "$ADDRESS_FILE")"
  code="$(sed -n 's/^NEURALOPS_ADDRESS_CODE=//p' "$ADDRESS_FILE")"
  body="{\"action\":\"$action\",\"format\":\"env\",\"hostname\":\"$host\",\"claim_code\":\"$code\""
  if [ "$action" = "update" ] && [ -n "${NEURALOPS_PUBLIC_IP:-}" ]; then
    body="$body,\"ip\":\"$NEURALOPS_PUBLIC_IP\""
  fi
  body="$body}"
  answer="$(curl -4 -sS --max-time 30 -X POST -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $ADDRESS_KEY" -d "$body" -w '\n%{http_code}' "$ADDRESS_URL" 2>&1 || true)"
  status="${answer##*$'\n'}"
  answer="${answer%$'\n'*}"
  if [ "$status" != "200" ]; then
    reason="$(printf '%s\n' "$answer" | sed -n 's/^ERROR=//p' | head -1)"
    printf '%s\n' "${reason:-The address service could not be reached.}" >&2
    return 1
  fi
  printf '%s\n' "$answer"
}
image()      { sed -n 's/^NEURALOPS_IMAGE=//p' "$NEURALOPS_DIR/neuralops/infra.env"; }

wait_for() {  # wait_for "what" seconds command...
  local what="$1" secs="$2"; shift 2
  for _ in $(seq 1 "$secs"); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  die "Timed out waiting for $what. See: neuralops logs"
}

fetch() {
  curl -fsSL "$NEURALOPS_RAW/$1" -o "$2.tmp" || die "Could not download $1"
  mv "$2.tmp" "$2"
}

# The database setup every start-from-new-code needs. All steps are safe to repeat.
setup_database() {
  # shellcheck disable=SC2086
  wait_for "the database" 120 $DOCKER exec neuralops-postgres pg_isready -U neuralops
  # shellcheck disable=SC2016,SC2086
  $DOCKER exec neuralops-postgres sh -c '
    psql -U "$POSTGRES_USER" -lqt | cut -d"|" -f1 | grep -qw nexus_vectors \
      || psql -U "$POSTGRES_USER" -q -c "CREATE DATABASE nexus_vectors"
    psql -U "$POSTGRES_USER" -d nexus_vectors -q -c "CREATE EXTENSION IF NOT EXISTS vector"
  ' >/dev/null
  wait_for "the server process" 60 manage check
  manage migrate --noinput >/dev/null || die "Upgrading the database failed. See: neuralops logs nucleus"
  manage seed_permissions >/dev/null || die "Loading the permissions failed. See: neuralops logs nucleus"
  manage seed_catalog >/dev/null || warn "The model catalog did not refresh; it refreshes by itself daily."
  compose restart nucleus nucleus-celery nucleus-celery-beat nexus-ai >/dev/null
  wait_for "the server to answer" 120 sh -c \
    "curl -s -o /dev/null -w '%{http_code}' http://localhost:8095/api/v1/projects/ | grep -Eq '^(401|403)$'"
}

cmd_status() {
  compose ps
  echo
  say "Address: $(server_url)"
  say "Version: $(image)"
  if [ "${NEURALOPS_MODE:-}" = "tailscale" ]; then
    if command -v tailscale >/dev/null 2>&1; then
      local state
      state="$($TS_CMD status --json 2>/dev/null | grep -m1 '"BackendState"' | sed -nE 's/.*"BackendState": *"([^"]+)".*/\1/p' || true)"
      if [ "$state" = "Running" ]; then
        local funnel="off"
        if $TS_CMD funnel status 2>&1 | grep -qiE "8095|https://"; then
          funnel="on"
        fi
        say "Tailscale: connected (Funnel $funnel)"
      else
        say "Tailscale: not connected"
      fi
    else
      say "Tailscale: not installed"
    fi
  fi
}

cmd_address_public() {
  local quiet="${1:-}" answer newip host code
  [ -f "$ADDRESS_FILE" ] || die "This server has no free address on record ($ADDRESS_FILE is missing)."
  if ! answer="$(address_call update 2>&1)"; then die "Could not check the address: $answer"; fi
  newip="$(printf '%s\n' "$answer" | sed -n 's/^NEURALOPS_PUBLIC_IP=//p')"
  host="$(sed -n 's/^NEURALOPS_DOMAIN=//p' "$ADDRESS_FILE")"
  if printf '%s\n' "$answer" | grep -qx 'CHANGED=yes'; then
    code="$(sed -n 's/^NEURALOPS_ADDRESS_CODE=//p' "$ADDRESS_FILE")"
    # Rewritten IN PLACE: the address timer runs as root, and a new file would
    # leave the install's own user unable to read it.
    printf 'NEURALOPS_DOMAIN=%s\nNEURALOPS_PUBLIC_IP=%s\nNEURALOPS_ADDRESS_CODE=%s\n' \
      "$host" "$newip" "$code" > "$ADDRESS_FILE"
    ok "This server's IP changed; https://$host now points at $newip (live within a few minutes)."
  elif [ -z "$quiet" ]; then
    say "Address: https://$host (points at $newip)"
  fi
}

cmd_address() {
  if [ "${NEURALOPS_MODE:-}" = "public" ]; then
    cmd_address_public "${1:-}"
    return
  fi
  if [ "${NEURALOPS_MODE:-}" = "domain" ]; then
    say "Address: $(server_url)"
    return
  fi
  if ! command -v tailscale >/dev/null 2>&1; then
    die "Tailscale is not installed on this machine."
  fi
  local state
  state="$($TS_CMD status --json 2>/dev/null | grep -m1 '"BackendState"' | sed -nE 's/.*"BackendState": *"([^"]+)".*/\1/p' || true)"
  if [ "$state" != "Running" ]; then
    die "Tailscale is not connected on this machine. Run: tailscale up"
  fi
  local name
  name="$($TS_CMD status --json 2>/dev/null | grep -m1 '"DNSName"' | sed -nE 's/.*"DNSName": *"([^"]+)".*/\1/p' | sed 's/\.$//' || true)"
  [ -n "$name" ] || die "Tailscale is connected but has no name for this machine. Check MagicDNS is on in the Tailscale admin page, then run the installer again."
  local url="https://$name"
  if [ "$url" != "$(server_url)" ]; then
    printf 'NEURALOPS_SERVER_URL=%s\nCENTRIFUGO_ALLOWED_ORIGINS=%s\n' "$url" "$url" > "$NEURALOPS_DIR/neuralops/app.env"
    compose up -d --force-recreate --no-deps nucleus centrifugo >/dev/null
    warn "The address changed. Update it in the app:"
  fi
  say "Address: $url"
}

cmd_backup() {
  local ts dir
  ts="$(date +%Y%m%d-%H%M%S)"
  dir="$NEURALOPS_DIR/backups/neuralops-$ts"
  mkdir -p "$dir" && chmod 700 "$dir"
  say "Backing up to $dir"
  # shellcheck disable=SC2086
  $DOCKER exec neuralops-postgres pg_dumpall -U neuralops | gzip > "$dir/database.sql.gz"
  ok "Database (both databases, roles included)"
  # The secrets are part of the backup on purpose: stored model keys are
  # encrypted with FIELD_ENCRYPTION_KEY and cannot be read back without it.
  ( umask 077; cp "$NEURALOPS_DIR/neuralops/secrets.env" "$dir/secrets.env" )
  ok "Secrets"
  tar -czf "$dir/projects.tar.gz" -C "$NEURALOPS_DIR" projects
  ok "Project files"
  warn "This backup holds your secrets. Keep it somewhere safe."
}

cmd_restore() {
  # 1.3.0 backup & restore: put a `neuralops backup` folder back, onto THIS
  # install — typically a fresh one. Replaces the database (both databases)
  # and the project files. Secrets follow the append-only rule: an existing
  # secrets.env is never overwritten unless --use-backup-secrets is passed —
  # but a database restored from a DIFFERENT deployment cannot decrypt its
  # stored model keys without the backup's FIELD_ENCRYPTION_KEY, so a
  # mismatch refuses loudly instead of restoring unreadable data.
  local dir="${1:-}" use_backup_secrets="${2:-}" answer="" ts
  [ -n "$dir" ] || die "Usage: neuralops restore <backup folder> [--use-backup-secrets]"
  [ -d "$dir" ] || die "No such backup folder: $dir"
  [ -f "$dir/database.sql.gz" ] || die "That folder has no database.sql.gz — not a neuralops backup."
  [ -f "$dir/projects.tar.gz" ] || die "That folder has no projects.tar.gz — not a neuralops backup."
  ts="$(date +%Y%m%d-%H%M%S)"

  # ── secrets first: they decide whether the restored data is readable ────
  if [ -f "$dir/secrets.env" ]; then
    if [ ! -s "$NEURALOPS_DIR/neuralops/secrets.env" ]; then
      ( umask 077; cp "$dir/secrets.env" "$NEURALOPS_DIR/neuralops/secrets.env" )
      ok "Secrets restored (this install had none yet)."
    elif cmp -s "$dir/secrets.env" "$NEURALOPS_DIR/neuralops/secrets.env"; then
      say "Secrets already match the backup."
    elif [ "$use_backup_secrets" = "--use-backup-secrets" ]; then
      ( umask 077; cp "$NEURALOPS_DIR/neuralops/secrets.env" "$NEURALOPS_DIR/neuralops/secrets.env.replaced-$ts" )
      ( umask 077; cp "$dir/secrets.env" "$NEURALOPS_DIR/neuralops/secrets.env" )
      warn "This install's secrets were REPLACED by the backup's (the old file is secrets.env.replaced-$ts)."
    else
      die "This install already has different secrets. The backup's database cannot be read without the backup's keys — re-run with --use-backup-secrets to use them (the current file is kept aside)."
    fi
  fi

  warn "This REPLACES this server's database and project files with the backup."
  read -r -p "  Type RESTORE to continue: " answer < /dev/tty || true
  [ "$answer" = "RESTORE" ] || { say "Nothing restored."; return; }

  say "Stopping the app while the data is swapped (the database stays up)…"
  compose stop nucleus nucleus-celery nucleus-celery-beat nexus-ai centrifugo >/dev/null 2>&1 || true
  compose up -d postgres >/dev/null
  # shellcheck disable=SC2086
  wait_for "the database" 120 $DOCKER exec neuralops-postgres pg_isready -U neuralops

  say "Restoring the database (both databases)…"
  # pg_dumpall carries CREATE DATABASE, so the old ones must go first.
  # shellcheck disable=SC2016,SC2086
  $DOCKER exec neuralops-postgres sh -c '
    psql -U "$POSTGRES_USER" -d postgres -q -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\""
    psql -U "$POSTGRES_USER" -d postgres -q -c "DROP DATABASE IF EXISTS nexus_vectors"
  ' >/dev/null
  # shellcheck disable=SC2016,SC2086
  gunzip -c "$dir/database.sql.gz" | $DOCKER exec -i neuralops-postgres \
    sh -c 'psql -U "$POSTGRES_USER" -d postgres -q' >/dev/null || die "The database restore failed — nothing further was touched. See the output above."
  ok "Database"

  say "Restoring the project files…"
  if [ -d "$NEURALOPS_DIR/projects" ]; then
    mv "$NEURALOPS_DIR/projects" "$NEURALOPS_DIR/projects.replaced-$ts" 2>/dev/null \
      || $SUDO mv "$NEURALOPS_DIR/projects" "$NEURALOPS_DIR/projects.replaced-$ts"
  fi
  tar -xzf "$dir/projects.tar.gz" -C "$NEURALOPS_DIR" 2>/dev/null \
    || $SUDO tar -xzf "$dir/projects.tar.gz" -C "$NEURALOPS_DIR"
  chown -R 1000:1000 "$NEURALOPS_DIR/projects" 2>/dev/null \
    || $SUDO chown -R 1000:1000 "$NEURALOPS_DIR/projects" 2>/dev/null || true
  ok "Project files (the old folder, if any, is projects.replaced-$ts)"

  say "Starting everything and bringing the database up to this version…"
  compose up -d >/dev/null
  setup_database
  ok "Restored. Sign in and check a project — chats, models and files should all be back."
}

cmd_update() {
  local target="${1:-latest}"
  say "Updating to ${NEURALOPS_IMAGE_REPO}:${target}"
  say "Step 1: a backup first, in case anything goes wrong."
  cmd_backup
  fetch docker-compose.neuralops.yaml "$NEURALOPS_DIR/docker-compose.neuralops.yaml"
  fetch neuralops/nginx.conf "$NEURALOPS_DIR/neuralops/nginx.conf"
  fetch neuralops/neuralops-cli.sh "$NEURALOPS_DIR/neuralops/neuralops-cli.sh.new"
  sed -i.bak "s|^NEURALOPS_IMAGE=.*|NEURALOPS_IMAGE=${NEURALOPS_IMAGE_REPO}:${target}|" "$NEURALOPS_DIR/neuralops/infra.env" && rm -f "$NEURALOPS_DIR/neuralops/infra.env.bak"
  compose pull
  compose up -d
  setup_database
  # Swap in the newer helper last, so this running copy is never edited mid-run.
  chmod 755 "$NEURALOPS_DIR/neuralops/neuralops-cli.sh.new"
  mv "$NEURALOPS_DIR/neuralops/neuralops-cli.sh.new" "$NEURALOPS_DIR/neuralops/neuralops-cli.sh"
  if [ ! -f "$NEURALOPS_DIR/neuralops/.installed" ]; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$NEURALOPS_DIR/neuralops/.installed"
  fi
  ok "Updated. Now running $(image)"
}

cmd_uninstall() {
  local a="" b=""
  read -r -p "  Remove NeuralOps from this server? (y/N): " a < /dev/tty || true
  case "$a" in [Yy]*) ;; *) say "Nothing removed."; return ;; esac
  compose down
  ok "Containers removed. Your data is still here: $NEURALOPS_DIR and its Docker volumes."
  read -r -p "  ALSO delete ALL data (database, project files, secrets)? Type DELETE to confirm: " b < /dev/tty || true
  if [ "$b" = "DELETE" ]; then
    # By NAME only: never `down -v`, which would take any other stack's
    # volumes in the same compose project with it.
    # shellcheck disable=SC2086
    $DOCKER volume rm -f neuralops_neuralops_postgres_data neuralops_neuralops_redis_data \
      neuralops_neuralops_fastembed_cache neuralops_neuralops_caddy_data \
      neuralops_neuralops_caddy_config >/dev/null 2>&1 || true
    if [ "${NEURALOPS_MODE:-}" = "tailscale" ] && command -v tailscale >/dev/null 2>&1; then
      $TS_CMD serve reset >/dev/null 2>&1 || true
    fi
    if [ "${NEURALOPS_MODE:-}" = "public" ]; then
      # Give the free address back, and stop the address check.
      if [ -f "$ADDRESS_FILE" ] && address_call release >/dev/null 2>&1; then
        ok "Address released."
      fi
      if command -v systemctl >/dev/null 2>&1; then
        ${SUDO:-} systemctl disable --now neuralops-address.timer >/dev/null 2>&1 || true
        ${SUDO:-} rm -f /etc/systemd/system/neuralops-address.timer /etc/systemd/system/neuralops-address.service 2>/dev/null || true
        ${SUDO:-} systemctl daemon-reload >/dev/null 2>&1 || true
      fi
    fi
    rm -rf "$NEURALOPS_DIR" 2>/dev/null || ($SUDO rm -rf "$NEURALOPS_DIR")
    for d in /usr/local/bin /opt/homebrew/bin "$HOME/.local/bin" "$HOME/bin"; do
      if [ -f "$d/neuralops" ]; then
        if [ -w "$d/neuralops" ]; then
          rm -f "$d/neuralops"
        elif [ -n "$SUDO" ]; then
          $SUDO rm -f "$d/neuralops" 2>/dev/null || true
        fi
      fi
    done
    ok "Everything deleted."
    if [ "${NEURALOPS_MODE:-}" = "tailscale" ]; then
      say "Tailscale is still installed. To disconnect this machine from your Tailscale account: tailscale logout"
    fi
  else
    say "Data kept. To bring NeuralOps back:  neuralops start"
  fi
}

case "${1:-help}" in
  status)    cmd_status ;;
  address)   shift; cmd_address "${1:-}" ;;
  update)    shift; cmd_update "${1:-latest}" ;;
  backup)    cmd_backup ;;
  restore)   shift; cmd_restore "${1:-}" "${2:-}" ;;
  logs)      shift; compose logs --tail 100 -f "$@" ;;
  restart)   compose restart ;;
  stop)      compose stop ;;
  start)     compose up -d ;;
  uninstall) cmd_uninstall ;;
  *)
    echo
    say "neuralops: manage this NeuralOps Nexus server"
    echo
    say "  status          what is running, the address, the version"
    say "  address         the server's current address"
    say "  update [ver]    back up, then upgrade (default: latest)"
    say "  backup          database + secrets + project files into backups/"
    say "  restore <dir>   put a backup back (database + project files)"
    say "  logs [service]  follow the logs"
    say "  restart | stop | start"
    say "  uninstall       remove it (data kept unless you type DELETE)"
    echo
    ;;
esac
