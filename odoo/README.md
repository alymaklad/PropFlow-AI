# Odoo setup

Odoo Community **17.0** runs from the pinned `odoo:${ODOO_VERSION}` image (see `.env.example`),
with its own PostgreSQL 16 container. Custom modules go in `odoo/custom_addons/` (mounted
read-only at `/mnt/extra-addons`).

## The `propflow_crm` module

Adds the PropFlow fields to `crm.lead` (shown on a **PropFlow** tab, with list and search
filters), a unique constraint on `propflow_correlation_id`, the **PropFlow Integration**
security group, and two RPC helpers: `propflow_schedule_activity` (idempotent To-Do) and
`propflow_post_note` (HTML-escaped note).

| Command | What it does |
|---|---|
| `make odoo-init` | Creates the database if needed and installs CRM + `propflow_crm` |
| `make odoo-update` | Applies module code changes to the dev database |
| `make odoo-test` | Runs the module tests in a separate `propflow_odoo_test` database |
| `make odoo-seed` | Dev only: creates the "PropFlow Leads" team with three fictional reps and points round-robin (`ODOO_SALES_TEAM_ID`) at it |

The integration group can create, read and update leads and contacts, and read sales teams,
stages and tags. It cannot delete or archive leads (archiving marks a lead lost, which is a
sales decision) or change settings.

> **Status:** verified on 2026-10-02 against `odoo:17.0` (server 17.0-20260908).

## 1. Initialise the database

```bash
scripts/odoo-init.sh        # or: make odoo-init
```

Then open http://localhost:8069, log in as `admin` / `admin` (the default for a new database)
and **change that password** (Settings > Users > Administrator).

## 2. Create the integration user (scripted)

```bash
make odoo-bootstrap
```

This runs `odoo/bootstrap/create_integration_user.py` inside `odoo shell`. It:

- enables **Leads** (CRM > Configuration > Settings),
- creates `propflow-integration` (from `ODOO_INTEGRATION_LOGIN`) with **no password**, so it can
  only authenticate with its API key and cannot use the web UI,
- gives it only the **PropFlow Integration** group (least privilege, see above) and an email
  address (Odoo requires one to post chatter messages),
- rotates its `propflow` API key and writes the key into `.env` as `ODOO_API_KEY` without
  printing it, then recreates `ai-service` and `n8n` so they use it.

Re-running is safe and issues a fresh key.

## 3. Manual fallback

If the script fails, do the same in the UI: Settings > Users > New (`propflow-integration`,
with an email address, PropFlow > PropFlow Integration); then, logged in as that user, Preferences > Account Security >
New API Key (activate developer mode if the tab is missing). Put the key in `.env`.

## 4. Verify

Odoo 17's external API is JSON-RPC (or the equivalent XML-RPC) at `/jsonrpc`. The API key is
used wherever the password would go. Load `.env` into your shell first: `set -a; source .env; set +a`.

Get the integration user's id:

```bash
curl -s http://localhost:8069/jsonrpc -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0", "method": "call", "id": 1,
  "params": {"service": "common", "method": "authenticate",
             "args": ["'"$ODOO_DB_NAME"'", "'"$ODOO_INTEGRATION_LOGIN"'", "'"$ODOO_API_KEY"'", {}]}
}'
```

A number in `result` is the uid; `false` means the login or key is wrong. Then create a lead
(replace `UID`):

```bash
curl -s http://localhost:8069/jsonrpc -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0", "method": "call", "id": 2,
  "params": {"service": "object", "method": "execute_kw",
             "args": ["'"$ODOO_DB_NAME"'", UID, "'"$ODOO_API_KEY"'",
                      "crm.lead", "create", [{"name": "PropFlow smoke test", "type": "lead"}]]}
}'
```

`result` is the new lead id. Read it back with method `read`, args `[[LEAD_ID]]` and kwargs
`{"fields": ["name", "type"]}`. Expected: a numeric uid, a new lead id, and the lead read back. A wrong key returns "Access Denied".
