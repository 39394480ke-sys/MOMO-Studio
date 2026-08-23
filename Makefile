.PHONY: install test lint format-check build dev-backend dev-frontend schemas

BACKEND_PYTHON ?= backend/.venv/bin/python
UV ?= uv
NPM ?= npm

install:
	$(UV) sync --project backend --extra dev --python 3.11 --locked
	$(NPM) --prefix frontend ci

test:
	$(BACKEND_PYTHON) -m pytest backend/tests
	$(NPM) --prefix frontend test -- --run

lint:
	$(BACKEND_PYTHON) -m ruff check backend
	$(BACKEND_PYTHON) -m mypy backend/src backend/tests backend/scripts
	$(NPM) --prefix frontend run lint
	$(NPM) --prefix frontend run typecheck

format-check:
	$(BACKEND_PYTHON) -m ruff format --check backend

build:
	$(NPM) --prefix frontend run build

schemas:
	PYTHONPATH=backend/src $(BACKEND_PYTHON) backend/scripts/generate_schemas.py

dev-backend:
	$(BACKEND_PYTHON) -m uvicorn momo.api.app:create_app --factory --reload --app-dir backend/src

dev-frontend:
	$(NPM) --prefix frontend run dev
