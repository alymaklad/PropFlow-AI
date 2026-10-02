# Security and operations

How PropFlow protects data and how to run it day to day. The stack is a development setup with
synthetic data; the "Before production" list at the end says what must change before real
customers are involved.

## Security model

### Trust boundaries

| Boundary | Control |
|---|---|
| Internet → intake webhook (n8n) | HMAC-SHA256 signature over `timestamp.raw_body`, 5-minute window; unsigned requests are refused and **not stored**. Idempotency keys make replays within the window harmless. |
| Inbound email → service | Treated as untrusted content. Replies are matched only against message ids PropFlow itself sent. New inquiries go through the same signed intake path. |
| n8n ↔ AI service | Shared `X-API-Key` on every `/v1` call; the service fails closed if no key is configured. |
| Service → Odoo | Dedicated integration user with an API key and the **PropFlow Integration** group: create/read/write leads and contacts, read teams/stages/tags. It cannot delete or archive leads, change settings or use other apps. |
| Customer text → LLM | Delimited as data, no tools, schema-only output, deterministic injection and opt-out detection as a backup. Model output never authorises an action: scores are rule-based and n8n decides what happens. |
| Browser → service | Only through nginx, which proxies `/api/public` and `/api/staff` (not `/v1`). Public inquiries: validation, honeypot, 5 per client per 10 minutes, browser-generated idempotency key, signed server-side. Staff API: bearer `STAFF_TOKEN` (development-grade; use SSO in production). CSP, `X-Frame-Options: DENY`, `nosniff`. |
| All published ports | Bound to `127.0.0.1` in development. |

### Secrets

- All secrets live in `.env` (git-ignored, mode 600) and are generated per environment.
  `.env.example` and `.env.production.example` hold placeholders only.
- No secret appears in workflow exports: n8n credentials are referenced by id, and the two
  committed credentials (Mailpit, GreenMail) are dev services without authentication.
- CI scans the full git history with gitleaks and audits Python dependencies with pip-audit.
  Last local run (2026-10-02): no leaks in history (the only findings were in the ignored
  `.env`), no known vulnerabilities in the 52 installed packages.

### Where personal data lives

| Store | What | Retention / removal |
|---|---|---|
| Odoo | Leads, contacts, notes, activities (system of record) | Odoo administrators; erasure returns the affected lead ids |
| PropFlow Postgres | Raw inquiries (audit), AI traces, recipient addresses, reminder sequences, consents | `POST /v1/privacy/retention` (`make retention DAYS=30`) anonymises older data; `POST /v1/privacy/erase` removes one contact |
| n8n | Execution history (inputs and outputs of each run) | Pruned after `N8N_EXECUTIONS_MAX_AGE_HOURS` (168 in dev) |
| Mailpit / GreenMail | Dev mail only | Clear from their UIs; not used in production |
| Logs | No names, emails, phone numbers or message text (reviewed 2026-10-02): only ids, HTTP codes and error classes | Docker log rotation |
| Groq | Prompts containing the inquiry text | Provider terms; synthetic data only until reviewed |

An opt-out survives erasure as a minimal suppression record (the contact key and the fact that
they opted out). Deleting it would let PropFlow email the person again.

### Customer communication safeguards

One code path sends customer email (`/v1/messages/prepare`): consent check, at most 3 emails
per address per 24 hours, fixed templates (no availability promises, opt-out line on every
message), at-most-once delivery through the outbound ledger, business hours only for
reminders, at most 2 reminders, and reminders stop on reply, opt-out, pause, handoff,
conversion or closure.

## Runbooks

All commands run from the repository root. `make help` lists the targets.

### Health check

```bash
docker compose ps                                  # every service "healthy"
curl -s localhost:8000/readyz                      # {"status": "ready", ...}
curl -s -X POST localhost:8000/v1/reports/summary \
  -H "X-API-Key: $AI_SERVICE_API_KEY" -H 'Content-Type: application/json' -d '{"period":"day"}'
```

The daily report (08:00 Sunday to Thursday) also shows open dead letters, overdue handoffs and
CRM sync failures.

### A lead failed (dead letter or "Workflow failed" alert)

1. Read the alert: workflow, failed node, error, correlation id.
2. List open dead letters: `curl -s localhost:8000/v1/dead-letters -H "X-API-Key: ..."`.
3. Fix the cause (Odoo down, bad credentials, a bug).
4. Replay: `curl -s -X POST localhost:8000/v1/dead-letters/<id>/replay -H "X-API-Key: ..."`.
   The original event is re-sent with its original idempotency key, so a partly processed
   lead resumes instead of duplicating. The dead letter closes when the event completes.
5. A dead letter without an event (scheduler, reports) needs no replay: those jobs rerun on
   their own. Discard it: `POST /v1/dead-letters/<id>/discard` with `{"reason": "..."}`.

### Odoo is down

Intake keeps accepting leads (`202`); upserts retry, then the event is marked `failed` and a
dead letter plus an ops alert are created. When Odoo is back, replay the dead letters (above).
Verified with `make scenarios ARGS=--with-outage`.

### Groq is down or rate-limited

Qualification retries (5 attempts, honouring Retry-After up to 20 s), then falls back:
leads whose form already has a location and a budget continue automatically; the others are
handed to a salesperson with reason `ai_unavailable`. Nothing is lost. To turn AI off
deliberately set `LLM_PROVIDER=none` and `docker compose up -d ai-service`.

### Rotate a key

| Key | Steps |
|---|---|
| Odoo integration API key | `make odoo-bootstrap` (issues a new key, writes `.env`, restarts ai-service and n8n; the old key is revoked) |
| `AI_SERVICE_API_KEY` | New value in `.env`, then `docker compose up -d ai-service n8n` |
| `WEBHOOK_HMAC_SECRET` | New value in `.env`, update every sender (form backend), then `docker compose up -d ai-service n8n` |
| `STAFF_TOKEN` | New value in `.env`, then `docker compose up -d ai-service`; staff sign in again |
| `GROQ_API_KEY` | Replace in `.env` (never paste it into chats or tickets), `docker compose up -d ai-service` |
| `N8N_ENCRYPTION_KEY` | Do not rotate casually: stored n8n credentials become unreadable. Export credentials first, re-import after. |

### A customer asks to stop messages

Replying "STOP" works automatically. To record it by hand:

```bash
curl -s -X POST localhost:8000/v1/consents -H "X-API-Key: ..." -H 'Content-Type: application/json' \
  -d '{"contact_keys": ["customer@example.com", "+201000000000"], "status": "opted_out", "source": "phone call"}'
```

Active reminders for that contact stop immediately.

### A customer asks to be forgotten

```bash
curl -s -X POST localhost:8000/v1/privacy/erase -H "X-API-Key: ..." -H 'Content-Type: application/json' \
  -d '{"contact": "customer@example.com"}'
```

Then delete or anonymise the returned `odoo_lead_ids` in Odoo as an administrator, and repeat
with the phone number if the customer used one.

### Backups and restore

```bash
docker compose exec -T propflow-db pg_dump -U propflow -Fc propflow > propflow.dump
docker compose exec -T odoo-db pg_dump -U odoo -Fc propflow_odoo > odoo.dump
docker run --rm -v propflow_n8n_data:/d -v "$PWD:/b" alpine tar czf /b/n8n-data.tgz -C /d .
docker run --rm -v propflow_odoo_web_data:/d -v "$PWD:/b" alpine tar czf /b/odoo-filestore.tgz -C /d .
```

Restore with `pg_restore --clean` into a stopped stack, then `docker compose up -d`. Keep the
n8n encryption key with the n8n backup.

### Add or remove a salesperson

Add the user to the sales team configured in `ODOO_SALES_TEAM_ID` (Odoo: CRM > Configuration >
Sales Teams). Round-robin picks up the change on the next lead; nothing to restart. A
salesperson removed from the team stops receiving new leads; their open handoffs keep their
deadlines and escalate to the team leader if not actioned.

### Change the scoring rules or thresholds

Edit `services/ai-qualification/app/data/scoring_rules.json` **and give it a new `version`**,
update the dataset labels if the reference rules change, run the tests, and rebuild the
service. Scores record the rules version, so old and new scores stay distinguishable.

### Change the qualification prompt

Copy the prompt to a new version file (`qualify-vN.md`), point `PROMPT_VERSION` at it, run
`make eval` before and after, and keep both reports in `docs/eval/`. Do not tune the prompt
against individual records (overfitting); see `docs/evaluation-report.md`.

### Update the Odoo module

`make odoo-update` (applies code and data changes, restarts Odoo) and `make odoo-test`.

### Clean up test data

`make retention DAYS=7` anonymises older ledger data. Test leads in Odoo are archived or
deleted by an Odoo administrator.

## Before production

- Real SMTP and IMAP providers with TLS and authentication (update both n8n credentials);
  SPF/DKIM for the sending domain. Remove Mailpit and GreenMail.
- TLS in front of n8n, Odoo and the frontend; keep the service and databases on a private
  network.
- Secrets from a secrets manager, unique per environment (`.env.production.example`).
- Replace the shared n8n↔service API key with per-client keys if more callers appear.
- n8n reads configuration through `$env`, which needs `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`:
  acceptable only on an n8n instance dedicated to PropFlow, otherwise move to n8n credentials.
- Change the Odoo `admin` password, disable the demo seed, and plan the upgrade from Odoo 17.
- A data-processing review before sending real customer messages to an LLM provider.
- Put the staff dashboard behind SSO instead of the shared `STAFF_TOKEN`, and run the public
  rate limit in a shared store if the service runs as several processes.
- Turn off `saveDataSuccessExecution` in the workflows or shorten n8n retention further.
