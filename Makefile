# Developer shortcuts. Requires Docker for the stack targets.
PYTHON ?= python3
SERVICE := services/ai-qualification

.PHONY: help up down logs ps migrate odoo-init odoo-bootstrap odoo-seed odoo-update odoo-test n8n-import n8n-export eval scenarios lint test test-db seed-properties dataset

help:
	@grep -E '^[a-z-]+:' Makefile | cut -d: -f1 | sort

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

migrate:
	docker compose run --rm migrate

odoo-init:
	scripts/odoo-init.sh

# Create/refresh the integration user; rotates its API key into .env
odoo-bootstrap:
	scripts/odoo-bootstrap.sh

# Demo sales team with fictional reps for round-robin (dev only)
odoo-seed:
	scripts/odoo-seed.sh

# Apply propflow_crm code changes to the dev database
odoo-update:
	scripts/odoo-update.sh

# propflow_crm tests in a separate database
odoo-test:
	scripts/odoo-test.sh

# Load n8n credentials + workflows from the repo and publish them
n8n-import:
	scripts/n8n-import.sh

# Save workflows edited in the n8n UI back to n8n/workflows/
n8n-export:
	scripts/n8n-export.sh

# Extraction evaluation against Groq (needs GROQ_API_KEY); report in docs/eval/
eval:
	scripts/eval.sh

# End-to-end scenarios against the running stack (add ARGS=--with-outage to stop/start Odoo)
scenarios:
	$(PYTHON) tests/scenarios/run_scenarios.py $(ARGS)

lint:
	ruff check .

# Service tests; migration tests are skipped unless TEST_DATABASE_URL is set
test:
	$(PYTHON) -m pytest $(SERVICE) tests/data

# Example: make test-db TEST_DATABASE_URL=postgresql://postgres@localhost:5432/propflow_test
test-db:
	@test -n "$(TEST_DATABASE_URL)" || (echo "set TEST_DATABASE_URL"; exit 2)
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PYTHON) -m pytest $(SERVICE) tests/data

# Load the synthetic property catalog (dev only; safe to re-run)
seed-properties:
	docker compose exec -T propflow-db sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < database/seeds/properties.sql

dataset:
	$(PYTHON) sample-data/build_synthetic_leads.py
