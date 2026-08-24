.PHONY: install test lint format-check build audit dev-backend serve-backend dev-frontend schemas

BACKEND_PYTHON ?= backend/.venv/bin/python
UV ?= uv
NPM ?= npm
LOCAL_CONFIG ?= config/local.yaml

install:
	$(UV) sync --project backend --extra dev --python 3.11 --locked
	$(NPM) --prefix frontend ci

test:
	$(BACKEND_PYTHON) -m pytest backend/tests
	$(NPM) --prefix frontend test -- --run

lint:
	$(BACKEND_PYTHON) -m ruff check backend
	MYPYPATH=backend/src $(BACKEND_PYTHON) -m mypy --config-file backend/pyproject.toml backend/src backend/tests backend/scripts
	$(NPM) --prefix frontend run lint
	$(NPM) --prefix frontend run typecheck

format-check:
	$(BACKEND_PYTHON) -m ruff format --check backend

build:
	$(NPM) --prefix frontend run build

audit:
	$(UV) pip check --python $(BACKEND_PYTHON)
	$(BACKEND_PYTHON) -m pip_audit
	$(NPM) --prefix frontend audit --audit-level=high

schemas:
	PYTHONPATH=backend/src $(BACKEND_PYTHON) backend/scripts/generate_schemas.py

dev-backend:
	PYTHONPATH=backend/src $(BACKEND_PYTHON) -m momo.serve --local-config "$(LOCAL_CONFIG)"

serve-backend: dev-backend

dev-frontend:
	$(NPM) --prefix frontend run dev
