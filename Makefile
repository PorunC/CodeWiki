.DEFAULT_GOAL := help

PYTHON_VERSION ?= 3.12
ifeq ($(OS),Windows_NT)
PYTHON ?= $(or $(wildcard .venv/Scripts/python.exe),py -$(PYTHON_VERSION))
else
PYTHON ?= $(or $(wildcard .venv/bin/python),python$(PYTHON_VERSION))
endif
NPM ?= npm

BACKEND_APP ?= backend.app.main:app
BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173
FRONTEND_DIR := frontend
FRONTEND_NPM := $(PYTHON) scripts/frontend_npm.py

export BACKEND_APP
export BACKEND_HOST
export BACKEND_PORT
export FRONTEND_DIR
export FRONTEND_PORT
export NPM
export PYTHON_VERSION

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
	@echo "Supported platforms: Linux, macOS, and Windows with GNU Make"
	@echo ""
	@echo "Overrides:"
	@echo "  make start PYTHON=python3.12 BACKEND_PORT=8000"

install: install-backend install-frontend

install-backend: ensure-backend-python ensure-backend-pip
	$(PYTHON) -m pip install -e ".[dev]"

ensure-backend-python:
	$(PYTHON) scripts/check_python.py

ensure-backend-pip:
	$(PYTHON) scripts/ensure_pip.py

install-frontend:
	$(FRONTEND_NPM) install

start: dev

dev: ensure-backend-python
	$(PYTHON) scripts/dev.py

backend: ensure-backend-python
	$(PYTHON) -m uvicorn $(BACKEND_APP) --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend:
	$(FRONTEND_NPM) run dev -- --host 127.0.0.1 --port $(FRONTEND_PORT)

kill: ensure-backend-python
	$(PYTHON) scripts/kill_ports.py $(BACKEND_PORT) $(FRONTEND_PORT)

test: ensure-backend-python
	$(PYTHON) -m pytest -q

lint: lint-backend lint-frontend

lint-backend: ensure-backend-python
	$(PYTHON) -m ruff check backend tests

lint-frontend:
	$(FRONTEND_NPM) run lint

build:
	$(FRONTEND_NPM) run build

clean:
	$(PYTHON) scripts/clean.py
