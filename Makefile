# SUBSIDENCE-NET / MineGuard
#
# Local development runs on SQLite with no services to install:
#   make install && make api      (terminal 1)
#   make gateway                  (terminal 2)
#   make web                      (terminal 3)  ->  http://localhost:5173
#
# `make up` runs the deployed shape instead: TimescaleDB + PostGIS, Mosquitto,
# Redis and the API in containers.

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.DEFAULT_GOAL := help
.PHONY: help install api gateway web test test-proto test-ml test-backend test-firmware up down logs clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Create the venv and install everything
	python3 -m venv $(VENV)
	$(PIP) install -q -r backend/requirements.txt -r ml/requirements.txt pytest pytest-asyncio
	$(PIP) install -q -e packages/subnet-proto
	cd web && npm install

api:  ## Run the API on http://localhost:8000 (SQLite)
	cd backend && ../$(VENV)/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

gateway:  ## Stream physics-backed frames into the API over the real protocol
	cd ml && ../$(VENV)/bin/python -m simulator.virtual_gateway --api http://localhost:8000

web:  ## Run the dashboard on http://localhost:5173
	cd web && npm run dev

demo: ## Warm the database with two simulated days, then stream live
	cd ml && ../$(VENV)/bin/python -m simulator.virtual_gateway \
	  --api http://localhost:8000 --ticks 200 --interval 0.01
	$(MAKE) gateway

test: test-proto test-ml test-backend test-firmware  ## Run every suite

test-proto:  ## Wire-protocol conformance, including the C header
	cd packages/subnet-proto && ../../$(VENV)/bin/python -m pytest -q

test-ml:  ## Physics, sensors, scenarios and mesh routing
	cd ml && ../$(VENV)/bin/python -m pytest -q

test-backend:  ## API, ingest, baselines, alerts and config downlink
	cd backend && ../$(VENV)/bin/python -m pytest -q

test-firmware:  ## The firmware's portable core -- no ESP-IDF, no hardware
	firmware/host_test/run.sh

up:  ## Bring up the deployed stack (TimescaleDB, Mosquitto, Redis, API, web)
	docker compose up -d --build

down:  ## Stop the deployed stack
	docker compose down

logs:  ## Follow the deployed stack's logs
	docker compose logs -f --tail=100

clean:  ## Remove the local database and build artefacts
	rm -f backend/subnet.db
	rm -rf web/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
