.DEFAULT_GOAL := help

PYTHON_VERSION ?= 3.12
ifeq ($(OS),Windows_NT)
PYTHON ?= $(or $(wildcard .venv/Scripts/python.exe),py -$(PYTHON_VERSION))
else
PYTHON ?= $(or $(wildcard .venv/bin/python),python$(PYTHON_VERSION))
endif
NPM ?= npm
ifeq ($(OS),Windows_NT)
VENV_PYTHON := .venv/Scripts/python.exe
else
VENV_PYTHON := .venv/bin/python
endif

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

.PHONY: help install ensure-venv-python312 install-backend ensure-backend-python ensure-backend-pip install-frontend start dev restart check-ports backend frontend kill test lint lint-backend typecheck lint-frontend build clean

help:
	@echo "Code Wiki Platform"
	@echo ""
	@echo "Usage:"
	@echo "  make install          Install backend and frontend dependencies"
	@echo "  make start            Start FastAPI and Vite together"
	@echo "  make restart          Kill dev ports, then start FastAPI and Vite"
	@echo "  make check-ports      Check whether dev ports are free"
	@echo "  make backend          Start only the FastAPI backend"
	@echo "  make frontend         Start only the Vite frontend"
	@echo "  make kill             Kill processes listening on ports 8000 and 5173"
	@echo "  make test             Run backend tests"
	@echo "  make lint             Run backend and frontend lint checks"
	@echo "  make typecheck        Run Python type checks with mypy"
	@echo "  make build            Build the frontend"
	@echo "  make clean            Remove local build/test caches"
	@echo ""
	@echo "Supported platforms: Linux, macOS, and Windows with GNU Make"
	@echo ""
	@echo "Overrides:"
	@echo "  make start PYTHON=python3.12 BACKEND_PORT=8000"

install: ensure-venv-python312 install-backend install-frontend

ensure-venv-python312:
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
		echo "No .venv found, creating one with Python $(PYTHON_VERSION)..."; \
		$(if $(filter Windows_NT,$(OS)),py -$(PYTHON_VERSION) -m venv .venv,python$(PYTHON_VERSION) -m venv .venv) || { \
			echo "Error: failed to create .venv with Python $(PYTHON_VERSION). Please ensure python$(PYTHON_VERSION) is installed."; \
			exit 1; \
		}; \
	fi
	@venv_version=`"$(VENV_PYTHON)" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"`; \
	if [ "$$venv_version" != "$(PYTHON_VERSION)" ]; then \
		echo "Error: .venv uses Python $$venv_version, expected $(PYTHON_VERSION)."; \
		exit 1; \
	fi

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

restart: kill dev

check-ports: ensure-backend-python
	$(PYTHON) scripts/kill_ports.py --check $(BACKEND_PORT) $(FRONTEND_PORT)

backend: ensure-backend-python
	$(PYTHON) scripts/kill_ports.py --check $(BACKEND_PORT)
	$(PYTHON) -m uvicorn $(BACKEND_APP) --reload --reload-dir backend --reload-exclude 'storage/*' --reload-exclude 'data/*' --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend:
	$(PYTHON) scripts/kill_ports.py --check $(FRONTEND_PORT)
	$(FRONTEND_NPM) run dev -- --host 127.0.0.1 --port $(FRONTEND_PORT)

kill: ensure-backend-python
	$(PYTHON) scripts/kill_ports.py $(BACKEND_PORT) $(FRONTEND_PORT)

test: ensure-backend-python
	$(PYTHON) -m pytest -q

lint: lint-backend lint-frontend

lint-backend: ensure-backend-python
	$(PYTHON) -m ruff check backend tests

typecheck: ensure-backend-python
	$(PYTHON) -m mypy backend/app

lint-frontend:
	$(FRONTEND_NPM) run lint

build:
	$(FRONTEND_NPM) run build

clean:
	$(PYTHON) scripts/clean.py
