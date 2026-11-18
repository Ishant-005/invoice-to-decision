# Common commands for the project. Run `make help` to list them.
# Targets from the spec that do not exist yet (seed, invoices, eval) are added in the
# milestone that builds them.

.PHONY: help install dev backend frontend test lint build

help:
	@echo "make install   Install backend and frontend dependencies"
	@echo "make dev       Run backend (port 8000) and frontend (port 5173) together"
	@echo "make test      Run backend tests, then type-check and build the frontend"
	@echo "make lint      Lint backend and frontend"
	@echo "make build     Build the frontend for production"

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
	cd backend && uv run ruff check .
	cd frontend && npm run lint

build:
	cd frontend && npm run build
