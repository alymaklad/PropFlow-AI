#!/usr/bin/env bash
# Run the propflow_crm module tests in a separate database (never the dev database).
# First run creates the database (~1 min); later runs update the module and re-run tests.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; source .env; set +a
TEST_DB="${ODOO_TEST_DB:-propflow_odoo_test}"

state=$(docker compose exec -T odoo-db psql -U "${ODOO_DB_USER:-odoo}" -d "$TEST_DB" -tAc \
  "SELECT state FROM ir_module_module WHERE name = 'propflow_crm'" 2>/dev/null || true)
if [ "$state" = "installed" ]; then mode=(-u propflow_crm); else mode=(-i propflow_crm); fi

log=$(mktemp)
docker compose run --rm -T odoo odoo -d "$TEST_DB" "${mode[@]}" --without-demo=all \
  --test-enable --test-tags /propflow_crm --stop-after-init --log-level=test \
  >"$log" 2>&1 || true

grep -E " ERROR | CRITICAL |FAIL:|Ran [0-9]+ test|odoo.tests.stats|odoo.tests.result" "$log" || true
if grep -qE " ERROR | CRITICAL |FAIL:" "$log"; then
  echo "propflow_crm tests FAILED (full log: $log)" >&2
  exit 1
fi
grep -q "propflow_crm" "$log" || { echo "module not loaded (log: $log)" >&2; exit 1; }
echo "propflow_crm tests passed"
rm -f "$log"
