.DEFAULT_GOAL := help

NPM ?= npm
PYTHON ?= python

BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173
BACKEND_DIR := backend
BACKEND_STATIC_DIR ?= $(CURDIR)/$(BACKEND_DIR)/static
FRONTEND_DIR := frontend
FRONTEND_NPM := node scripts/frontend-npm.mjs

export BACKEND_HOST
export BACKEND_DIR
export BACKEND_PORT
export BACKEND_STATIC_DIR
export FRONTEND_DIR
export FRONTEND_PORT
export NPM

.PHONY: help install install-backend install-frontend start dev restart check-ports backend frontend kill test test-scripts lint lint-backend lint-scripts typecheck lint-frontend build build-backend build-frontend npm-pack npm-smoke clean

help:
	@echo "Code Wiki Platform"
	@echo ""
	@echo "Usage:"
	@echo "  make install          Install backend and frontend dependencies"
	@echo "  make start            Start the TypeScript backend and Vite together"
	@echo "  make restart          Kill dev ports, then start the TypeScript backend and Vite"
	@echo "  make check-ports      Check whether dev ports are free"
	@echo "  make backend          Start only the TypeScript backend"
	@echo "  make frontend         Start only the Vite frontend"
	@echo "  make kill             Kill processes listening on ports 8000 and 5173"
	@echo "  make test             Run TypeScript backend tests"
	@echo "  make test-scripts     Run Python utility script tests"
	@echo "  make lint             Run backend and frontend lint checks"
	@echo "  make lint-scripts     Run Python utility script lint checks"
	@echo "  make typecheck        Run TypeScript backend type checks"
	@echo "  make build            Build the backend package and frontend"
	@echo "  make npm-pack         Dry-run the npm package contents"
	@echo "  make npm-smoke        Install the packed npm package and smoke-test binaries"
	@echo "  make clean            Remove local build/test caches"
	@echo ""
	@echo "Supported platforms: Linux, macOS, and Windows with GNU Make"
	@echo ""
	@echo "Overrides:"
	@echo "  make start NPM=npm BACKEND_PORT=8000 FRONTEND_PORT=5173"

install: install-backend install-frontend

install-backend:
	$(NPM) --prefix $(BACKEND_DIR) install

install-frontend:
	$(FRONTEND_NPM) install

start: dev

dev:
	node scripts/dev.mjs

restart: kill dev

check-ports:
	node scripts/ports.mjs --check $(BACKEND_PORT) $(FRONTEND_PORT)

backend:
	$(NPM) --prefix $(BACKEND_DIR) run check:ports -- --host $(BACKEND_HOST) $(BACKEND_PORT)
	$(NPM) --prefix $(BACKEND_DIR) run dev -- serve --host $(BACKEND_HOST) --port $(BACKEND_PORT) --static-dir $(BACKEND_STATIC_DIR)

frontend:
	node scripts/ports.mjs --check $(FRONTEND_PORT)
	$(FRONTEND_NPM) run dev -- --host 127.0.0.1 --port $(FRONTEND_PORT)

kill:
	node scripts/ports.mjs $(BACKEND_PORT) $(FRONTEND_PORT)

test:
	$(NPM) --prefix $(BACKEND_DIR) test

test-scripts:
	$(PYTHON) -m pytest -q

lint: lint-backend lint-frontend

lint-backend:
	$(NPM) --prefix $(BACKEND_DIR) run lint

lint-scripts:
	$(PYTHON) -m ruff check scripts tests/scripts

typecheck:
	$(NPM) --prefix $(BACKEND_DIR) run typecheck

lint-frontend:
	$(FRONTEND_NPM) run lint

build: build-backend build-frontend

build-backend:
	$(NPM) --prefix $(BACKEND_DIR) run build

build-frontend:
	$(FRONTEND_NPM) run build

npm-pack:
	$(NPM) --prefix $(BACKEND_DIR) run pack:dry

npm-smoke:
	$(NPM) --prefix $(BACKEND_DIR) run pack:smoke

clean:
	node scripts/clean.mjs
