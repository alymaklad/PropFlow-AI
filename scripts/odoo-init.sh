#!/usr/bin/env bash
# Create the Odoo database (first run) and install CRM + propflow_crm (no demo data).
# Safe to re-run: already-installed modules are left alone; missing ones are installed.
# To apply code changes to propflow_crm, use scripts/odoo-update.sh instead.
# Requires: docker compose stack defined in docker-compose.yml and a populated .env.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; source .env; set +a
DB="${ODOO_DB_NAME:-propflow_odoo}"

docker compose up -d odoo-db
docker compose run --rm odoo \
  odoo -d "$DB" -i base,crm,propflow_crm --without-demo=all --stop-after-init
docker compose up -d odoo
docker compose restart odoo  # reload the registry with any newly installed module
echo "Odoo initialised: database '$DB'. Next: create the integration user (odoo/README.md)."
