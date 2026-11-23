# One image, one service: FastAPI serves the API and the built web app.
# Build:  docker build -t invoice-to-decision .
# Run:    docker run -p 10000:10000 -e ANTHROPIC_API_KEY=... invoice-to-decision

# --- Stage 1: build the web app. Nothing from this stage but frontend/dist is kept. --------
FROM node:24-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# The "How it works" screen bundles this document.
COPY docs/ASSUMPTIONS.md /build/docs/ASSUMPTIONS.md
RUN npm run build

# --- Stage 2: the image that runs. Production Python packages only: no test tools, no
# Playwright or Chromium, no invoice generator (scripts/ is never copied). ------------------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_NO_DEV=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked && rm -rf /root/.cache/uv

COPY backend/app ./app
COPY config /app/config
COPY data/seed /app/data/seed
COPY data/invoices /app/data/invoices
COPY --from=frontend /build/frontend/dist /app/frontend/dist

# Render sets PORT (10000 by default). One worker: the instance is small, and the app keeps
# one lock in memory to guard the purchase order balances.
CMD ["sh", "-c", "exec /app/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
