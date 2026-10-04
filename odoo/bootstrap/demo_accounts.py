# Runs inside `odoo shell` (see scripts/odoo-accounts.sh); `env` is provided by the shell.
# Idempotent. For the public demo, where Odoo is reachable from the internet:
#  - replaces the default admin password ("admin") with ADMIN_PASSWORD, if it is still the
#    default (a password someone has already changed is left alone);
#  - creates or refreshes the read-only "reviewer" user with REVIEWER_PASSWORD, so a reviewer
#    who changes it cannot lock the others out for longer than until the next deploy;
#  - shows dates as day/month/year.
import os

from odoo.exceptions import AccessDenied

admin = env.ref("base.user_admin")
try:
    admin.with_user(admin)._check_credentials("admin", {"interactive": False})
    default_admin = True
except AccessDenied:
    default_admin = False
if default_admin:
    admin.password = os.environ["ADMIN_PASSWORD"]
print(f"PROPFLOW_ADMIN_ROTATED={int(default_admin)}")

# Dates as day/month/year (the demo is set in Egypt); en_US defaults to month/day.
env["res.lang"]._lang_get("en_US").write({"date_format": "%d/%m/%Y"})

LOGIN = "reviewer"
Users = env["res.users"].with_context(no_reset_password=True)
user = Users.search([("login", "=", LOGIN), ("active", "in", [True, False])], limit=1)
values = {
    "name": "Reviewer (read-only)",
    "email": "reviewer@example.com",
    "groups_id": [(6, 0, [env.ref("propflow_crm.group_propflow_reviewer").id])],
    "active": True,
    "tz": "Africa/Cairo",
}
if user:
    user.write(values)
else:
    user = Users.create({"login": LOGIN, **values})
user.password = os.environ["REVIEWER_PASSWORD"]
env.cr.commit()
print(f"PROPFLOW_REVIEWER_UID={user.id}")
