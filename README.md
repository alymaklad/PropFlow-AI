# PropFlow AI

Autonomous real-estate lead management: intake, AI qualification, deterministic scoring,
property matching, Odoo CRM sync, follow-up, human escalation and reporting.

- Scope: [PropFlow_AI_Project_Description.md](PropFlow_AI_Project_Description.md)
- Plan: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- Deployment (free): [plan](docs/deployment-plan.md), [step-by-step guide](docs/deployment-guide.md)
- Decisions: [docs/architecture.md](docs/architecture.md)

## Quick start (development)

Requires Docker with the Compose plugin.

```bash
cp .env.example .env        # then replace every change-me value
make up                     # build and start the stack
make odoo-init              # one-time: create the Odoo database and install CRM
make odoo-bootstrap         # integration user + API key (written into .env)
make odoo-seed              # dev: demo sales team (fictional reps + manager)
make seed-properties        # dev: synthetic property catalog
make n8n-import             # load and publish the n8n workflows
```

Details and a manual fallback: [odoo/README.md](odoo/README.md). If you just installed Docker and
get "permission denied" on the socket, log out and back in (or prefix commands with `sg docker -c`).

| Service | URL |
|---|---|
| Buyer site | http://localhost:3000 |
| Staff dashboard | http://localhost:3000/staff (sign in with `STAFF_TOKEN` from `.env`) |
| n8n | http://localhost:5678 |
| Odoo | http://localhost:8069 |
| AI service | http://localhost:8000/healthz |
| Mailpit (outgoing mail) | http://localhost:8025 |
| GreenMail (leads inbox, dev) | SMTP 127.0.0.1:3025, IMAP 127.0.0.1:3143 |

## Development without Docker

```bash
pip install -r services/ai-qualification/requirements-dev.txt
make lint
make test                                   # migration tests skip without a database
make test-db TEST_DATABASE_URL=postgresql://postgres@localhost:5432/propflow_test
```

## Frontend

`frontend/` is a React + TypeScript app (Vite) with two surfaces: the buyer site (verified
listings, a sentence that is the search, the inquiry form) and the staff dashboard (handoffs
by deadline, report figures with denominators, failed runs with replay, latest inquiries).
In the stack it is the `web` service (nginx), which proxies only `/api/public` and
`/api/staff` to the service. For development with hot reload:

```bash
npm --prefix frontend install
npm --prefix frontend run dev     # http://localhost:5173, proxies /api to localhost:8000
```

## End-to-end scenarios

With the stack running and seeded (`make odoo-seed seed-properties n8n-import`):

```bash
make scenarios                      # all scenarios through the real webhook and inbox
make scenarios ARGS=--with-outage   # also stops Odoo to test dead letters and replay
```

The runner (`tests/scenarios/run_scenarios.py`, standard library only) checks the ledger,
Odoo, Mailpit and the report for each scenario. Scenarios that need the AI are skipped when
`LLM_PROVIDER` is not `groq`.

Everything uses synthetic data. Status by phase is tracked in the plan.
