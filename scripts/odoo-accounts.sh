#!/usr/bin/env bash
# Public demo accounts in Odoo (run by deploy/deploy.sh on every deploy):
#  - the read-only "reviewer" login, password ODOO_REVIEWER_PASSWORD in .env (generated once);
#  - a random admin password (ODOO_ADMIN_PASSWORD in .env) if admin still uses "admin".
# Passwords go to Odoo through the environment, never on a command line.
set -euo pipefail
cd "$(dirname "$0")/.."

ensure_secret() {
  grep -q "^$1=." .env && return
  local value; value=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$value|" .env; else echo "$1=$value" >> .env; fi
  chmod 600 .env
}
ensure_secret ODOO_REVIEWER_PASSWORD
ensure_secret ODOO_ADMIN_PASSWORD
set -a; source .env; set +a

out=$(REVIEWER_PASSWORD="$ODOO_REVIEWER_PASSWORD" ADMIN_PASSWORD="$ODOO_ADMIN_PASSWORD" \
  docker compose exec -T -e REVIEWER_PASSWORD -e ADMIN_PASSWORD odoo sh -c \
  'odoo shell --no-http --db_host "$HOST" --db_user "$USER" --db_password "$PASSWORD" -d "$0" --log-level=warn' \
  "${ODOO_DB_NAME:-propflow_odoo}" < odoo/bootstrap/demo_accounts.py)
printf '%s\n' "$out" | grep -q '^PROPFLOW_REVIEWER_UID=' \
  || { printf 'setting up the demo accounts failed:\n%s\n' "$out" >&2; exit 1; }
if printf '%s\n' "$out" | grep -q '^PROPFLOW_ADMIN_ROTATED=1'; then
  echo "Odoo admin still had the default password: replaced (ODOO_ADMIN_PASSWORD in .env)."
fi
echo "Odoo reviewer login ready (user 'reviewer', password ODOO_REVIEWER_PASSWORD in .env)."
