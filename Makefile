# Common commands for the project. Run `make help` to list them.

.PHONY: help install dev backend frontend test lint build seed invoices check-invoices decisions eval e2e ui-check

help:
	@echo "make install   Install backend and frontend dependencies"
	@echo "make dev       Run backend (port 8000) and frontend (port 5173) together"
	@echo "make test      Run backend tests, then type-check and build the frontend"
	@echo "make lint      Lint backend and frontend"
	@echo "make build     Build the frontend for production"
	@echo "make seed      Reset the database to the seed data (vendors, POs, seeded history)"
	@echo "make invoices  Regenerate the test invoice PDFs and the answer key"
	@echo "make check-invoices  Recompute every invoice figure and check each PDF's text layer"
	@echo "make decisions  Show the decision for each sample invoice (CASES=\"1 5\" for full detail)"
	@echo "make eval      LIVE AI: read all 15 PDFs, compare with the answer key, write docs/EXTRACTION_EVAL.md"
	@echo "make e2e       LIVE AI: 13 cases + 3 sequences through all six stages, write docs/E2E_CHECK.md"
	@echo "make ui-check  LIVE AI: with 'make dev' running, run all 13 samples in a real browser and compare with the answer key"

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

# Runs the answer key's ground-truth extractions through the decision logic (no AI model).
# `make decisions` prints one line per case; `make decisions CASES="1 5 8"` prints those in full.
decisions:
	cd backend && uv run python ../scripts/show_decisions.py $(CASES)

# Both targets below call the real Anthropic API (a few US cents each) and need
# ANTHROPIC_API_KEY in .env. Neither touches the app's database.

# Reads all 15 PDFs with the live model and scores every field against the answer key.
# `make eval NOTE="what changed"` labels the run in the report's history table.
eval:
	cd backend && uv run python ../scripts/eval_extraction.py $(NOTE)

# Live extraction feeding the decision logic: 13 cases and 3 sequences against the answer key.
e2e:
	cd backend && uv run python ../scripts/e2e_check.py

# Drives the web app in a headless browser: reset, run all 13 samples by clicking them, read
# each decision off the screen and compare with the answer key. Needs `make dev` running in
# another terminal. Resets the demo data and makes 13 live AI calls.
ui-check:
	cd backend && uv run python ../scripts/ui_check.py
