#!/usr/bin/env bash
# =============================================================================
# neuralops — manage this NeuralOps Nexus install. Installed by install.sh as
# /usr/local/bin/neuralops (a link to neuralops/neuralops-cli.sh in the
# install folder). Reads the install's settings from neuralops/install.conf.
#
#   neuralops status      what is running, the address, the version
#   neuralops address     the current address (tunnel installs: re-syncs it)
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

SELF_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
# shellcheck source=/dev/null
. "$SELF_DIR/install.conf"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi
if docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="$SUDO docker"; fi

say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n  \033[31m✘ %s\033[0m\n\n' "$*" >&2; exit 1; }

compose() {
  # shellcheck disable=SC2086  # $DOCKER is "docker" or "sudo docker" on purpose
  (cd "$NEURALOPS_DIR" && COMPOSE_PROFILES="$PROFILES" $DOCKER compose \
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
}

cmd_address() {
  if [ "$NEURALOPS_MODE" != "tunnel" ]; then
    say "Address: $(server_url)"
    return
  fi
  local url=""
  for _ in $(seq 1 45); do
    # shellcheck disable=SC2086
    url="$($DOCKER logs neuralops-cloudflared 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true)"
    [ -n "$url" ] && break
    sleep 2
  done
  [ -n "$url" ] || die "The secure address is not up yet. Is the server online? Try again in a minute."
  if [ "$url" != "$(server_url)" ]; then
    printf 'NEURALOPS_SERVER_URL=%s\nCENTRIFUGO_ALLOWED_ORIGINS=%s\n' "$url" "$url" > "$NEURALOPS_DIR/neuralops/app.env"
    compose up -d --force-recreate --no-deps nucleus centrifugo >/dev/null
    warn "The address CHANGED (the server restarted). Update it in the app:"
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
  $SUDO tar -czf "$dir/projects.tar.gz" -C "$NEURALOPS_DIR" projects
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
  # shellcheck disable=SC2086
  gunzip -c "$dir/database.sql.gz" | $DOCKER exec -i neuralops-postgres \
    sh -c 'psql -U "$POSTGRES_USER" -d postgres -q' >/dev/null || die "The database restore failed — nothing further was touched. See the output above."
  ok "Database"

  say "Restoring the project files…"
  if [ -d "$NEURALOPS_DIR/projects" ]; then
    $SUDO mv "$NEURALOPS_DIR/projects" "$NEURALOPS_DIR/projects.replaced-$ts"
  fi
  $SUDO tar -xzf "$dir/projects.tar.gz" -C "$NEURALOPS_DIR"
  $SUDO chown -R 1000:1000 "$NEURALOPS_DIR/projects"
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
  sed -i "s|^NEURALOPS_IMAGE=.*|NEURALOPS_IMAGE=${NEURALOPS_IMAGE_REPO}:${target}|" "$NEURALOPS_DIR/neuralops/infra.env"
  compose pull
  compose up -d
  setup_database
  # Swap in the newer helper last, so this running copy is never edited mid-run.
  chmod 755 "$NEURALOPS_DIR/neuralops/neuralops-cli.sh.new"
  mv "$NEURALOPS_DIR/neuralops/neuralops-cli.sh.new" "$NEURALOPS_DIR/neuralops/neuralops-cli.sh"
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
    $SUDO rm -rf "$NEURALOPS_DIR"
    $SUDO rm -f /usr/local/bin/neuralops /etc/systemd/system/neuralops-address.service
    ok "Everything deleted."
  else
    say "Data kept. To bring NeuralOps back:  neuralops start"
  fi
}

case "${1:-help}" in
  status)    cmd_status ;;
  address)   cmd_address ;;
  update)    shift; cmd_update "${1:-latest}" ;;
  backup)    cmd_backup ;;
  restore)   shift; cmd_restore "${1:-}" "${2:-}" ;;
  logs)      shift; compose logs --tail 100 -f "$@" ;;
  restart)   compose restart ;;
  stop)      compose stop ;;
  start)     compose up -d; if [ "$NEURALOPS_MODE" = "tunnel" ]; then cmd_address; fi ;;
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