#!/usr/bin/env bash
# Deploy a git ref on the server (called by GitHub Actions over SSH as the deploy user):
#   /opt/propflow/deploy/deploy.sh <tag-or-branch>
# Idempotent: the first run initialises Odoo, the demo team, the catalog and n8n; later runs
# rebuild, apply what changed and smoke-test.
#
# Everything is inside main(), which bash parses completely before running it, so this file
# being replaced by the git checkout below cannot change the run in progress.
set -euo pipefail

main() {
  local ref="${1:-main}"
  if [[ ! "$ref" =~ ^[A-Za-z0-9._/-]+$ ]]; then
    echo "refusing suspicious ref: $ref" >&2
    exit 2
  fi
  cd /opt/propflow
  [ -f .env ] || { echo ".env missing: see docs/deployment-guide.md" >&2; exit 2; }
  grep -q '^COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml' .env \
    || { echo ".env must set COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml" >&2; exit 2; }

  local previous
  previous=$(git rev-parse HEAD)
  git fetch --tags --prune --force origin
  if git rev-parse --verify --quiet "refs/tags/$ref" >/dev/null; then
    git checkout --force --detach "refs/tags/$ref"
  else
    git checkout --force --detach "origin/$ref"
  fi
  local current
  current=$(git rev-parse HEAD)
  echo "==> Deploying $ref ($(git log -1 --format='%h %s'))"

  docker compose up -d --build --remove-orphans
  # Caddy reads its config once at start; a new deploy/Caddyfile needs a fresh container
  if ! git diff --quiet "$previous" "$current" -- deploy/Caddyfile; then
    echo "==> Caddyfile changed: restarting Caddy"
    docker compose up -d --force-recreate caddy
  fi
  wait_healthy ai-service
  wait_healthy odoo

  set -a; source .env; set +a
  local initialised
  initialised=$(docker compose exec -T odoo-db psql -U "${ODOO_DB_USER:-odoo}" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '${ODOO_DB_NAME:-propflow_odoo}'" || true)
  if [ "$initialised" != "1" ]; then
    echo "==> First run: Odoo database, integration user, demo team, n8n workflows"
    make -s odoo-init odoo-bootstrap odoo-seed
    make -s n8n-import
  else
    if ! git diff --quiet "$previous" "$current" -- odoo/custom_addons; then
      echo "==> Odoo module changed: updating"
      make -s odoo-update
    fi
    if ! git diff --quiet "$previous" "$current" -- n8n; then
      echo "==> Workflows changed: re-importing"
      make -s n8n-import
    fi
  fi
  # Odoo is public at odoo.PUBLIC_HOST: read-only reviewer login, never the default admin password
  scripts/odoo-accounts.sh
  make -s seed-properties

  echo "==> Smoke test"
  wait_healthy ai-service
  curl -fsS --retry 10 --retry-delay 3 --retry-all-errors http://127.0.0.1:8000/readyz >/dev/null
  curl -fsS --retry 10 --retry-delay 3 --retry-all-errors \
    "https://${PUBLIC_HOST}/api/public/listings" >/dev/null
  curl -fsS --retry 10 --retry-delay 3 --retry-all-errors \
    "https://odoo.${PUBLIC_HOST}/web/login" >/dev/null
  docker image prune -f >/dev/null
  echo "==> Deployed $(git log -1 --format='%h') to https://${PUBLIC_HOST}"
}

wait_healthy() {
  local service="$1" id state
  for _ in $(seq 1 60); do
    id=$(docker compose ps -q "$service")
    state=$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo starting)
    [ "$state" = "healthy" ] && return 0
    sleep 5
  done
  echo "$service did not become healthy" >&2
  docker compose logs --tail 50 "$service" >&2
  return 1
}

main "$@"
exit
