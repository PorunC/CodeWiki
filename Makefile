.DEFAULT_GOAL := help

PYTHON ?= $(or $(wildcard .venv/bin/python),$(wildcard .venv/Scripts/python.exe),python)
NPM ?= npm

BACKEND_APP ?= backend.app.main:app
BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173
FRONTEND_DIR := frontend

.PHONY: help install install-backend install-frontend start dev backend frontend test lint lint-backend lint-frontend build clean

help:
	@echo "Code Wiki Platform"
	@echo ""
	@echo "Usage:"
	@echo "  make install          Install backend and frontend dependencies"
	@echo "  make start            Start FastAPI and Vite together"
	@echo "  make backend          Start only the FastAPI backend"
	@echo "  make frontend         Start only the Vite frontend"
	@echo "  make test             Run backend tests"
	@echo "  make lint             Run backend and frontend lint checks"
	@echo "  make build            Build the frontend"
	@echo "  make clean            Remove local build/test caches"
	@echo ""
	@echo "Overrides:"
	@echo "  make start PYTHON=.venv/Scripts/python.exe BACKEND_PORT=8001"

install: install-backend install-frontend

install-backend:
	$(PYTHON) -m pip install -e ".[dev]"

install-frontend:
	$(NPM) --prefix $(FRONTEND_DIR) install

start: dev

dev:
	@set -e; \
	echo "Starting backend on http://$(BACKEND_HOST):$(BACKEND_PORT)"; \
	$(PYTHON) -m uvicorn $(BACKEND_APP) --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT) & \
	backend_pid=$$!; \
	trap 'kill $$backend_pid 2>/dev/null || true' INT TERM EXIT; \
	echo "Starting frontend on http://127.0.0.1:$(FRONTEND_PORT)"; \
	$(NPM) --prefix $(FRONTEND_DIR) run dev -- --host 127.0.0.1 --port $(FRONTEND_PORT)

backend:
	$(PYTHON) -m uvicorn $(BACKEND_APP) --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend:
	$(NPM) --prefix $(FRONTEND_DIR) run dev -- --host 127.0.0.1 --port $(FRONTEND_PORT)

test:
	$(PYTHON) -m pytest -q

lint: lint-backend lint-frontend

lint-backend:
	$(PYTHON) -m ruff check backend tests

lint-frontend:
	$(NPM) --prefix $(FRONTEND_DIR) run lint

build:
	$(NPM) --prefix $(FRONTEND_DIR) run build

clean:
	rm -rf .pytest_cache .ruff_cache $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/.vite $(FRONTEND_DIR)/tsconfig.tsbuildinfo
