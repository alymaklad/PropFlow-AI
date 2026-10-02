#!/usr/bin/env bash
# Seed the demo sales team (fictional reps) and point round-robin at it via .env.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

out=$(docker compose exec -T odoo sh -c \
  'odoo shell --no-http --db_host "$HOST" --db_user "$USER" --db_password "$PASSWORD" -d "$0" --log-level=warn' \
  "${ODOO_DB_NAME:-propflow_odoo}" < odoo/bootstrap/seed_demo_sales_team.py)
team=$(printf '%s\n' "$out" | sed -n 's/^PROPFLOW_TEAM_ID=//p' | tail -1)
[ -n "$team" ] || { printf 'seeding failed:\n%s\n' "$out" >&2; exit 1; }

if grep -q '^ODOO_SALES_TEAM_ID=' .env; then
  sed -i "s/^ODOO_SALES_TEAM_ID=.*/ODOO_SALES_TEAM_ID=$team/" .env
else
  echo "ODOO_SALES_TEAM_ID=$team" >> .env
fi
ODOO_SALES_TEAM_ID="$team" docker compose up -d ai-service >/dev/null 2>&1
echo "Demo team 'PropFlow Leads' (id $team) seeded; ODOO_SALES_TEAM_ID set and ai-service restarted."
