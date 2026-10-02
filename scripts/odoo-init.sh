#!/usr/bin/env bash
# One-time Odoo bootstrap: create the database and install the CRM app (no demo data).
# Safe to re-run: Odoo upgrades the module list instead of re-creating the database.
# Requires: docker compose stack defined in docker-compose.yml and a populated .env.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; source .env; set +a
DB="${ODOO_DB_NAME:-propflow_odoo}"

docker compose up -d odoo-db
docker compose run --rm odoo \
  odoo -d "$DB" -i base,crm --without-demo=all --stop-after-init
docker compose up -d odoo
echo "Odoo initialised: database '$DB'. Next: create the integration user (odoo/README.md)."
