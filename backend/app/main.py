"""The FastAPI application. Run with: uv run uvicorn app.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from app.api import demo, health
from app.db import create_tables, engine
from app.seed import seed_if_empty


@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: make sure the tables exist and, if the database is empty, load the seed data.
    create_tables()
    with Session(engine) as session:
        seed_if_empty(session)
    yield


app = FastAPI(title="Invoice-to-Decision", lifespan=lifespan)

# Every API route lives under /api so the built frontend can later be served from "/".
app.include_router(health.router, prefix="/api")
app.include_router(demo.router, prefix="/api")
