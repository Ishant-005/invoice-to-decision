"""The FastAPI application. Run with: uv run uvicorn app.main:app --reload"""

from fastapi import FastAPI

from app.api import health

app = FastAPI(title="Invoice-to-Decision")

# Every API route lives under /api so the built frontend can later be served from "/".
app.include_router(health.router, prefix="/api")
