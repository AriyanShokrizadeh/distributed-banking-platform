.DEFAULT_GOAL := help

PYTHON ?= python
DOCKER ?= docker compose

.PHONY: help install up down ps logs config \
        unit integration lint format typecheck check \
        failover crash-prepared crash-commit \
        demo-sharding demo-replicas demo-concurrency demo-transfers demo-cross-shard


# Help
help:
	@echo Mini Banking - Development Commands
	@echo ===================================
	@echo Usage: make TARGET
	@echo Setup and Docker:
	@echo   install          Install development dependencies
	@echo   start            Start existing services
	@echo   stop             Stop the running services
	@echo   up               Build and start services
	@echo   down             Stop services
	@echo   ps               Show service status
	@echo   logs             Follow service logs
	@echo   config           Validate Compose configuration
	@echo Tests and Quality:
	@echo   unit             Run unit tests
	@echo   integration      Run integration tests
	@echo   lint             Check linting and formatting
	@echo   format           Fix lint issues and format code
	@echo   typecheck        Run static type checking
	@echo   check            Run lint, typecheck and unit tests
	@echo Fault Injection:
	@echo   failover         Demonstrate service failover
	@echo   crash-prepared   Simulate crash after 2PC prepare
	@echo   crash-commit     Simulate crash during 2PC commit



# Setup and Docker
install:
	$(PYTHON) -m pip install -r requirements-dev.txt

start:
	$(DOCKER) start

stop:
	$(DOCKER) stop

up:
	$(DOCKER) up -d --build

down:
	$(DOCKER) down

ps:
	$(DOCKER) ps

logs:
	$(DOCKER) logs -f

config:
	$(DOCKER) config -q


# Tests and Quality
unit:
	$(PYTHON) -m pytest tests/unit -q

integration: export RUN_INTEGRATION := 1
integration:
	$(PYTHON) -m pytest tests/integration -q

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

typecheck:
	$(PYTHON) -m pyright

check: lint typecheck unit


# Fault Injection
failover:
	$(PYTHON) scripts/demo_failover.py

crash-prepared:
	$(PYTHON) scripts/demo_2pc_crash.py --point prepared

crash-commit:
	$(PYTHON) scripts/demo_2pc_crash.py --point commit

# Required experiments
demo-sharding:
	$(PYTHON) -m scripts.demo_sharding

demo-replicas:
	$(PYTHON) -m scripts.demo_load_balancing

demo-concurrency:
	$(PYTHON) -m scripts.demo_concurrency

demo-transfers:
	$(PYTHON) -m scripts.demo_transfers

demo-cross-shard:
	$(PYTHON) -m scripts.demo_cross_shard
