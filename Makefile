.PHONY: setup dev dev-infra dev-api dev-web dev-cli dev-telegram test lint format doctor migrate

# Load .env into every target's environment (e.g. DATABASE_URL for alembic/pai).
ifneq (,$(wildcard ./.env))
    include .env
    export
endif

COMPOSE := docker compose -f infra/compose/docker-compose.yml

setup:
	uv sync --all-packages
	npm install --workspace=apps/web

dev-infra:
	$(COMPOSE) up -d

API_PORT ?= 8000

dev-api:
	uv run --project apps/api uvicorn personal_ai_api.main:app --reload --host 0.0.0.0 --port $(API_PORT)

dev-web:
	npm run dev --workspace=apps/web

dev-telegram:
	uv run --project apps/telegram-bot python -m personal_ai_telegram.main

dev: dev-infra
	@echo "Infra started. Run 'make dev-api' and 'make dev-web' in separate shells."

migrate:
	uv run --project apps/api alembic -c migrations/alembic.ini upgrade head

test:
	uv run --project apps/api pytest
	npm run test --workspace=apps/web --if-present

PY_SRC := personal_ai apps/api apps/cli apps/telegram-bot

lint:
	uv run --project apps/api ruff check $(PY_SRC)
	uv run --project apps/api ruff format --check $(PY_SRC)
	uv run --project apps/api mypy personal_ai apps/api
	uv run --project apps/api mypy apps/cli
	uv run --project apps/telegram-bot mypy apps/telegram-bot
	npm run lint --workspace=apps/web

format:
	uv run --project apps/api ruff format $(PY_SRC)

doctor:
	uv run --project apps/cli pai doctor
