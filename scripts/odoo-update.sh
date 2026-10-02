#!/usr/bin/env bash
# Apply propflow_crm code/data changes to the dev database, then restart Odoo.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
docker compose run --rm -T odoo odoo -d "${ODOO_DB_NAME:-propflow_odoo}" -u propflow_crm \
  --stop-after-init --log-level=warn
docker compose restart odoo
echo "propflow_crm updated."
