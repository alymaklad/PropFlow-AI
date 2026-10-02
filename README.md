# PropFlow AI

Autonomous real-estate lead management: intake, AI qualification, deterministic scoring,
property matching, Odoo CRM sync, follow-up, human escalation and reporting.

- Scope: [PropFlow_AI_Project_Description.md](PropFlow_AI_Project_Description.md)
- Plan: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- Decisions: [docs/architecture.md](docs/architecture.md)

## Quick start (development)

Requires Docker with the Compose plugin.

```bash
cp .env.example .env        # then replace every change-me value
make up                     # build and start the stack
make odoo-init              # one-time: create the Odoo database and install CRM
make odoo-bootstrap         # integration user + API key (written into .env)
```

Details and a manual fallback: [odoo/README.md](odoo/README.md). If you just installed Docker and
get "permission denied" on the socket, log out and back in (or prefix commands with `sg docker -c`).

| Service | URL |
|---|---|
| n8n | http://localhost:5678 |
| Odoo | http://localhost:8069 |
| AI service | http://localhost:8000/healthz |
| Mailpit | http://localhost:8025 |

## Development without Docker

```bash
pip install -r services/ai-qualification/requirements-dev.txt
make lint
make test                                   # migration tests skip without a database
make test-db TEST_DATABASE_URL=postgresql://postgres@localhost:5432/propflow_test
```

The Phase 0 status is tracked in the plan. Everything uses synthetic data.
