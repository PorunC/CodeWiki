.DEFAULT_GOAL := help

PYTHON_VERSION ?= 3.12
PYTHON ?= $(or $(wildcard .venv/bin/python),$(wildcard .venv/Scripts/python.exe),python$(PYTHON_VERSION))
NPM ?= npm

BACKEND_APP ?= backend.app.main:app
BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173
FRONTEND_DIR := frontend

.PHONY: help install install-backend ensure-backend-python ensure-backend-pip install-frontend start dev backend frontend kill test lint lint-backend lint-frontend build clean

help:
	@echo "Code Wiki Platform"
	@echo ""
	@echo "Usage:"
	@echo "  make install          Install backend and frontend dependencies"
	@echo "  make start            Start FastAPI and Vite together"
	@echo "  make backend          Start only the FastAPI backend"
	@echo "  make frontend         Start only the Vite frontend"
	@echo "  make kill             Kill processes listening on ports 8000 and 5173"
	@echo "  make test             Run backend tests"
	@echo "  make lint             Run backend and frontend lint checks"
	@echo "  make build            Build the frontend"
	@echo "  make clean            Remove local build/test caches"
	@echo ""
	@echo "Overrides:"
	@echo "  make start PYTHON=python3.12 BACKEND_PORT=8000"

install: install-backend install-frontend

install-backend: ensure-backend-python ensure-backend-pip
	$(PYTHON) -m pip install -e ".[dev]"

ensure-backend-python:
	@$(PYTHON) -c 'import sys; expected=(3, 12); actual=sys.version_info[:2]; raise SystemExit(0 if actual == expected else "Python 3.12 is required for graspologic Leiden community detection; {} is {}.{}. Recreate .venv with `python3.12 -m venv .venv` or pass `PYTHON=python3.12`.".format(sys.executable, *actual))'

ensure-backend-pip:
	@$(PYTHON) -m pip --version >/dev/null 2>&1 || { \
		echo "pip is missing for $(PYTHON); bootstrapping it with ensurepip"; \
		$(PYTHON) -m ensurepip --upgrade; \
	}

install-frontend:
	$(NPM) --prefix $(FRONTEND_DIR) install

start: dev

dev: ensure-backend-python
	@set -e; \
	echo "Starting backend on http://$(BACKEND_HOST):$(BACKEND_PORT)"; \
	$(PYTHON) -m uvicorn $(BACKEND_APP) --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT) & \
	backend_pid=$$!; \
	trap 'kill $$backend_pid 2>/dev/null || true' INT TERM EXIT; \
	echo "Starting frontend on http://127.0.0.1:$(FRONTEND_PORT)"; \
	$(NPM) --prefix $(FRONTEND_DIR) run dev -- --host 127.0.0.1 --port $(FRONTEND_PORT)

backend: ensure-backend-python
	$(PYTHON) -m uvicorn $(BACKEND_APP) --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend:
	$(NPM) --prefix $(FRONTEND_DIR) run dev -- --host 127.0.0.1 --port $(FRONTEND_PORT)

kill: ensure-backend-python
	$(PYTHON) scripts/kill_ports.py $(BACKEND_PORT) $(FRONTEND_PORT)

test: ensure-backend-python
	$(PYTHON) -m pytest -q

lint: lint-backend lint-frontend

lint-backend: ensure-backend-python
	$(PYTHON) -m ruff check backend tests

lint-frontend:
	$(NPM) --prefix $(FRONTEND_DIR) run lint

build:
	$(NPM) --prefix $(FRONTEND_DIR) run build

clean:
	rm -rf .pytest_cache .ruff_cache $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/.vite $(FRONTEND_DIR)/tsconfig.tsbuildinfo
