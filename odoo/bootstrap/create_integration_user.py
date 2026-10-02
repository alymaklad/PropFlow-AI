# Runs inside `odoo shell` (see scripts/odoo-bootstrap.sh); `env` is provided by the shell.
# Idempotent: enables Leads, creates or updates the integration user, and rotates its
# "propflow" API key. The new key is printed once on a marker line for the wrapper to capture.
import os

LOGIN = os.environ.get("PROPFLOW_INTEGRATION_LOGIN", "propflow-integration")
KEY_NAME = "propflow"

# CRM > Settings > Leads
env["res.config.settings"].create({"group_use_lead": True}).execute()

groups = [
    env.ref("base.group_user").id,
    # Interim: replaced by a least-privilege PropFlow group in Phase 1 (task 1.1)
    env.ref("sales_team.group_sale_salesman_all_leads").id,
]
Users = env["res.users"].with_context(no_reset_password=True)
user = Users.search([("login", "=", LOGIN)], limit=1)
if not user:
    # No password: this account authenticates with its API key only and cannot use the web UI.
    user = Users.create({"name": "PropFlow Integration", "login": LOGIN})
user.write({"groups_id": [(6, 0, groups)], "active": True})

apikeys = env["res.users.apikeys"].sudo()
apikeys.search([("user_id", "=", user.id), ("name", "=", KEY_NAME)]).unlink()
key = env["res.users.apikeys"].with_user(user)._generate(None, KEY_NAME)
env.cr.commit()
print(f"PROPFLOW_UID={user.id}")
print(f"PROPFLOW_API_KEY={key}")
