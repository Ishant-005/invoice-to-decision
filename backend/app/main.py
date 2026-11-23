"""The FastAPI application. Run with: uv run uvicorn app.main:app --reload"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from app.api import demo, health, purchase_orders, reference, runs, vendors
from app.db import create_tables, engine
from app.pipeline.runner import fail_interrupted_runs
from app.seed import seed_if_empty

# One line per event, with the time first. Every line about a run carries "run=<id>", so
# `grep run=<id>` on the server log tells the story of that run.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: make sure the tables exist and, if the database is empty, load the seed
    # data. Then close off any run that an earlier server process left unfinished.
    create_tables()
    with Session(engine) as session:
        if seed_if_empty(session):
            logging.getLogger("invoice.api").info("empty database: seed data loaded")
        fail_interrupted_runs(session)
    yield


app = FastAPI(title="Invoice-to-Decision", lifespan=lifespan)

# Every API route lives under /api so the built frontend can later be served from "/".
app.include_router(health.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(reference.router, prefix="/api")
app.include_router(purchase_orders.router, prefix="/api")
app.include_router(vendors.router, prefix="/api")
app.include_router(demo.router, prefix="/api")
