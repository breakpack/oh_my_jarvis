.PHONY: setup dev dev-infra dev-api dev-web dev-cli test lint format doctor migrate

COMPOSE := docker compose -f infra/compose/docker-compose.yml

setup:
	uv sync --project apps/api
	uv sync --project apps/cli
	npm install --workspace=apps/web

dev-infra:
	$(COMPOSE) up -d

dev-api:
	uv run --project apps/api uvicorn personal_ai_api.main:app --reload --host 0.0.0.0 --port 8000

dev-web:
	npm run dev --workspace=apps/web

dev: dev-infra
	@echo "Infra started. Run 'make dev-api' and 'make dev-web' in separate shells."

migrate:
	uv run --project apps/api alembic -c migrations/alembic.ini upgrade head

test:
	uv run --project apps/api pytest
	npm run test --workspace=apps/web --if-present

lint:
	uv run --project apps/api ruff check .
	uv run --project apps/api ruff format --check .
	uv run --project apps/api mypy personal_ai apps/api apps/cli
	npm run lint --workspace=apps/web

format:
	uv run --project apps/api ruff format .

doctor:
	uv run --project apps/cli pai doctor
