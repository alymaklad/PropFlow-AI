# Runs inside `odoo shell` (see scripts/odoo-bootstrap.sh); `env` is provided by the shell.
# Idempotent: enables Leads, creates or updates the integration user, and rotates its
# "propflow" API key. The new key is printed once on a marker line for the wrapper to capture.
import os

LOGIN = os.environ.get("PROPFLOW_INTEGRATION_LOGIN", "propflow-integration")
# Odoo refuses to post chatter messages for an author without an email address.
EMAIL = os.environ.get("PROPFLOW_INTEGRATION_EMAIL", "propflow-noreply@example.com")
KEY_NAME = "propflow"

# CRM > Settings > Leads
env["res.config.settings"].create({"group_use_lead": True}).execute()

# Least-privilege group from the propflow_crm module (implies Internal User)
groups = [env.ref("propflow_crm.group_propflow_integration").id]
Users = env["res.users"].with_context(no_reset_password=True)
user = Users.search([("login", "=", LOGIN)], limit=1)
if not user:
    # No password: this account authenticates with its API key only and cannot use the web UI.
    user = Users.create({"name": "PropFlow Integration", "login": LOGIN})
user.write({"groups_id": [(6, 0, groups)], "active": True, "email": EMAIL})

apikeys = env["res.users.apikeys"].sudo()
apikeys.search([("user_id", "=", user.id), ("name", "=", KEY_NAME)]).unlink()
key = env["res.users.apikeys"].with_user(user)._generate(None, KEY_NAME)
env.cr.commit()
print(f"PROPFLOW_UID={user.id}")
print(f"PROPFLOW_API_KEY={key}")
