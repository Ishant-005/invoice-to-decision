"""Shared setup for the API tests: the real app and the real pipeline on a throwaway
database, with one thing replaced: the AI call. No API key or network is needed."""

import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import clock, config
from app.db import create_tables, get_session, make_engine
from app.main import app
from app.pipeline import extract as extract_module
from app.pipeline.extract import ExtractionError, ModelReading
from app.pipeline.record import InvoiceRecord
from app.seed import seed_database
from tests.answer_key import CASES, TODAY

# file hash -> the answer key's ground truth for that sample
TRUTH_BY_HASH = {
    hashlib.sha256((config.INVOICE_DIR / name).read_bytes()).hexdigest(): case["truth"]
    for name, case in CASES.items()
}


class StandInReader:
    """Takes the place of the live AI call. For a sample PDF it returns the answer key's
    ground truth, as if the model had read it perfectly. Tests can make it fail
    (`error`), or run some code at the moment the "AI call" happens (`during_call`)."""

    def __init__(self):
        self.calls = 0
        self.error: Exception | None = None
        self.during_call = None

    def __call__(self, pdf_bytes: bytes) -> ModelReading:
        self.calls += 1
        if self.during_call:
            self.during_call()
        if self.error:
            raise self.error
        truth = TRUTH_BY_HASH.get(hashlib.sha256(pdf_bytes).hexdigest())
        if truth is None:
            raise ExtractionError("The stand-in reader only knows the sample invoices.")
        return ModelReading(record=InvoiceRecord.model_validate(truth), model="stand-in",
                            input_tokens=0, output_tokens=0)


@pytest.fixture
def api(tmp_path, monkeypatch):
    """The app on a freshly seeded temporary database. Gives the test:
    api.client  to make HTTP requests      api.engine  to look into the database
    api.reader  the stand-in for the AI call"""
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    create_tables(engine)
    with Session(engine) as session:
        seed_database(session)

    monkeypatch.setattr(config, "PAGES_DIR", tmp_path / "pages")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setenv("EXTRACTION_CACHE_MODE", "fallback")
    monkeypatch.delenv("MAX_LIVE_EXTRACTIONS_PER_DAY", raising=False)
    monkeypatch.setattr(clock, "today", lambda: TODAY)  # the same date on any day
    reader = StandInReader()
    monkeypatch.setattr(extract_module, "read_with_model", reader)

    def session_for_request():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_for_request
    try:
        yield SimpleNamespace(client=TestClient(app), engine=engine, reader=reader)
    finally:
        app.dependency_overrides.clear()


def submit(api, sample: str) -> dict:
    """Start a run for a sample the way the browser does, poll until it has finished,
    and return the finished run."""
    response = api.client.post("/api/runs", data={"sample": sample})
    assert response.status_code == 202, response.text
    return poll(api, response.json()["id"])


def poll(api, run_id: str) -> dict:
    for _ in range(100):
        run = api.client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("completed", "failed"):
            return run
    raise AssertionError("the run did not finish")


def purchase_order(api, po_id: str) -> dict:
    return api.client.get(f"/api/purchase-orders/{po_id}").json()


def flagged(run: dict) -> set[str]:
    """Codes of the findings that came out as a warning or a failure."""
    return {finding["code"] for stage in run["stages"] for finding in stage["findings"]
            if finding["status"] in ("warn", "fail")}


def stage(run: dict, name: str) -> dict:
    return next(s for s in run["stages"] if s["stage"] == name)
