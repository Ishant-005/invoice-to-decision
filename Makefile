# Common commands for the project. Run `make help` to list them.
# `make eval` from the spec does not exist yet; it is added in the milestone that builds it.

.PHONY: help install dev backend frontend test lint build seed invoices check-invoices

help:
	@echo "make install   Install backend and frontend dependencies"
	@echo "make dev       Run backend (port 8000) and frontend (port 5173) together"
	@echo "make test      Run backend tests, then type-check and build the frontend"
	@echo "make lint      Lint backend and frontend"
	@echo "make build     Build the frontend for production"
	@echo "make seed      Reset the database to the seed data (vendors, POs, seeded history)"
	@echo "make invoices  Regenerate the test invoice PDFs and the answer key"
	@echo "make check-invoices  Recompute every invoice figure and check each PDF's text layer"

install:
	cd backend && uv sync
	cd frontend && npm install

# Runs both servers. Ctrl+C stops both.
dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest
	cd frontend && npm run build

lint:
	cd backend && uv run ruff check . && uv run ruff check ../scripts --config pyproject.toml
	cd frontend && npm run lint

build:
	cd frontend && npm run build

# Wipes runs and restores vendors, POs, balances and seeded history (same as the reset button).
seed:
	cd backend && uv run python ../scripts/seed.py

# Rebuilds data/invoices/*.pdf, data/seed/*.pdf, expected.json and seed_invoices.json from
# scripts/invoice_definitions.json. The first line downloads the headless browser if needed.
invoices:
	cd backend && uv run playwright install chromium
	cd backend && uv run python ../scripts/generate_invoices.py
	cd backend && uv run python ../scripts/check_invoices.py

check-invoices:
	cd backend && uv run python ../scripts/check_invoices.py
