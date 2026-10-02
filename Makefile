# Developer shortcuts. Requires Docker for the stack targets.
PYTHON ?= python3
SERVICE := services/ai-qualification

.PHONY: help up down logs ps migrate odoo-init odoo-bootstrap lint test test-db dataset

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
	docker compose up -d n8n

lint:
	ruff check .

# Service tests; migration tests are skipped unless TEST_DATABASE_URL is set
test:
	$(PYTHON) -m pytest $(SERVICE) tests/data

# Example: make test-db TEST_DATABASE_URL=postgresql://postgres@localhost:5432/propflow_test
test-db:
	@test -n "$(TEST_DATABASE_URL)" || (echo "set TEST_DATABASE_URL"; exit 2)
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PYTHON) -m pytest $(SERVICE) tests/data

dataset:
	$(PYTHON) sample-data/build_synthetic_leads.py
