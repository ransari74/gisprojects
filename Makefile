.DEFAULT_GOAL := help
SHELL := /bin/bash

COMPOSE ?= docker compose
PY      ?= backend/.venv/bin/python
ALEMBIC ?= backend/.venv/bin/alembic
DB_URL  ?= postgresql+asyncpg://gis:gis@127.0.0.1:5432/gisportfolio

export DATABASE_URL ?= $(DB_URL)

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Docker compose
# ---------------------------------------------------------------------------
.PHONY: up
up: ## Build and start db + api + web (api runs migrations on start)
	$(COMPOSE) up --build -d
	@echo "API  http://localhost:8000/docs"
	@echo "Web  http://localhost:5173"

.PHONY: down
down: ## Stop everything
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop everything and delete the database volume
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail the API logs
	$(COMPOSE) logs -f api

.PHONY: seed
seed: ## Generate and load the demo dataset into the running database
	$(COMPOSE) run --rm etl

.PHONY: test
test: ## Run the backend test suite inside the api container
	$(COMPOSE) run --rm api pytest tests -q

# ---------------------------------------------------------------------------
# Migrations -- Alembic is the single source of truth for the schema
# ---------------------------------------------------------------------------
.PHONY: migrate
migrate: ## Apply all migrations (alembic upgrade head)
	cd backend && $(CURDIR)/$(ALEMBIC) upgrade head

.PHONY: migrate-down
migrate-down: ## Roll back one revision
	cd backend && $(CURDIR)/$(ALEMBIC) downgrade -1

.PHONY: migrate-reset
migrate-reset: ## Roll every migration back to an empty database
	cd backend && $(CURDIR)/$(ALEMBIC) downgrade base

.PHONY: migration
migration: ## Autogenerate a revision: make migration m="add solar column"
	@test -n "$(m)" || (echo 'Usage: make migration m="describe the change"' && exit 1)
	cd backend && $(CURDIR)/$(ALEMBIC) revision --autogenerate -m "$(m)"

.PHONY: migrate-check
migrate-check: ## Fail if the models have drifted from the migrations
	cd backend && $(CURDIR)/$(ALEMBIC) check

.PHONY: migrate-sql
migrate-sql: ## Print the SQL for the whole chain without running it
	cd backend && $(CURDIR)/$(ALEMBIC) upgrade head --sql

.PHONY: migrate-history
migrate-history: ## Show the revision chain
	cd backend && $(CURDIR)/$(ALEMBIC) history --indicate-current

# ---------------------------------------------------------------------------
# Local (no Docker) -- expects a Postgres with PostGIS on localhost:5432
# ---------------------------------------------------------------------------
.PHONY: install
install: ## Create the virtualenvs and install every dependency
	python3 -m venv backend/.venv
	backend/.venv/bin/pip install -q -r backend/requirements-dev.txt -r etl/requirements.txt
	cd frontend && npm install

.PHONY: dev-api
dev-api: ## Run the API locally with reload
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

.PHONY: dev-web
dev-web: ## Run the Vite dev server locally
	cd frontend && npm run dev

.PHONY: dev-seed
dev-seed: ## Generate and load the demo dataset locally
	$(PY) -m etl.load --generate --truncate

.PHONY: dev-test
dev-test: ## Run the backend tests locally
	cd backend && .venv/bin/pytest tests -q

.PHONY: typecheck
typecheck: ## Typecheck the frontend
	cd frontend && npm run typecheck

.PHONY: build-web
build-web: ## Production build of the frontend
	cd frontend && npm run build
