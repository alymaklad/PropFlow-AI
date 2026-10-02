# Runs inside `odoo shell` (see scripts/odoo-seed.sh). Idempotent.
# Creates a "PropFlow Leads" sales team with three fictional salespeople for round-robin
# demos. The users have no password (they cannot log in until an admin sets one) and use
# example.com addresses. Prints the team id on a marker line.
TEAM_NAME = "PropFlow Leads"
REPS = [
    ("Demo Rep One", "demo-rep-1"),
    ("Demo Rep Two", "demo-rep-2"),
    ("Demo Rep Three", "demo-rep-3"),
]

salesman = env.ref("sales_team.group_sale_salesman")
Users = env["res.users"].with_context(no_reset_password=True)
team = env["crm.team"].search([("name", "=", TEAM_NAME)], limit=1) or env["crm.team"].create(
    {"name": TEAM_NAME, "use_leads": True, "use_opportunities": True}
)
for name, login in REPS:
    user = Users.search([("login", "=", login)], limit=1) or Users.create({
        "name": name, "login": login, "email": f"{login}@example.com",
        "groups_id": [(4, salesman.id)],
    })
    if not env["crm.team.member"].search([("crm_team_id", "=", team.id),
                                          ("user_id", "=", user.id)]):
        env["crm.team.member"].create({"crm_team_id": team.id, "user_id": user.id})
env.cr.commit()
print(f"PROPFLOW_TEAM_ID={team.id}")
