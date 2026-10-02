# Runs inside `odoo shell` (see scripts/odoo-seed.sh). Idempotent.
# Creates a "PropFlow Leads" sales team with three fictional salespeople for round-robin
# demos, plus a fictional sales manager as team leader. The users have no password (they
# cannot log in until an admin sets one) and use example.com addresses. Prints the team id on
# a marker line.
TEAM_NAME = "PropFlow Leads"
REPS = [
    ("Demo Rep One", "demo-rep-1", "+20 2 0000 0001"),
    ("Demo Rep Two", "demo-rep-2", "+20 2 0000 0002"),
    ("Demo Rep Three", "demo-rep-3", "+20 2 0000 0003"),
]
MANAGER = ("Demo Sales Manager", "demo-manager", "+20 2 0000 0009")

salesman = env.ref("sales_team.group_sale_salesman")
Users = env["res.users"].with_context(no_reset_password=True)
team = env["crm.team"].search([("name", "=", TEAM_NAME)], limit=1) or env["crm.team"].create(
    {"name": TEAM_NAME, "use_leads": True, "use_opportunities": True}
)
for name, login, phone in REPS:
    user = Users.search([("login", "=", login)], limit=1) or Users.create({
        "name": name, "login": login, "email": f"{login}@example.com",
        "groups_id": [(4, salesman.id)],
    })
    user.partner_id.phone = phone
    if not env["crm.team.member"].search([("crm_team_id", "=", team.id),
                                          ("user_id", "=", user.id)]):
        env["crm.team.member"].create({"crm_team_id": team.id, "user_id": user.id})
# Team leader: receives escalations for handoffs that nobody actioned in time.
name, login, phone = MANAGER
manager = Users.search([("login", "=", login)], limit=1) or Users.create({
    "name": name, "login": login, "email": f"{login}@example.com",
    "groups_id": [(4, env.ref("sales_team.group_sale_manager").id)],
})
manager.partner_id.phone = phone
team.user_id = manager
env.cr.commit()
print(f"PROPFLOW_TEAM_ID={team.id}")
