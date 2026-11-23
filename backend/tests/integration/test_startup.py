"""Startup on a host with no lasting disk: the app must always come up working. A missing or
empty database is created and seeded (including the samples' saved readings); an existing
one is never wiped. Also: DATA_DIR, and FastAPI serving the built web app."""

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import make_engine
from app.frontend import serve_frontend
from app.models import Invoice, POLine, PurchaseOrder, Run, SavedExtraction, Vendor
from app.pipeline.extract import ExtractionError
from app.seed import load_sample_extractions, prepare_database
from tests.answer_key import CASES
from tests.integration.conftest import flagged, stage, submit


def count(session, table) -> int:
    return len(session.exec(select(table)).all())


# --- The database ------------------------------------------------------------------------


def test_a_missing_database_is_created_and_seeded_with_the_samples_saved_readings(tmp_path):
    db_file = tmp_path / "app.db"
    assert not db_file.exists()

    assert prepare_database(make_engine(f"sqlite:///{db_file}")) is True

    assert db_file.is_file()
    with Session(make_engine(f"sqlite:///{db_file}")) as session:
        assert count(session, Vendor) == 5
        assert count(session, PurchaseOrder) == 10
        assert count(session, POLine) > 0
        assert count(session, Invoice) == 2  # the seeded history
        assert count(session, Run) == 0
        saved = session.exec(select(SavedExtraction)).all()
        # the 2 seeded invoices and the 13 samples
        assert len(saved) == 15
        assert {s.file_name for s in saved if s.source == "live"} == set(CASES)


def test_an_empty_database_file_is_seeded_too(tmp_path):
    db_file = tmp_path / "app.db"
    db_file.touch()  # exists, but has no tables and no rows
    assert prepare_database(make_engine(f"sqlite:///{db_file}")) is True
    with Session(make_engine(f"sqlite:///{db_file}")) as session:
        assert count(session, Vendor) == 5


def test_an_existing_database_is_not_wiped(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    prepare_database(engine)
    with Session(engine) as session:
        # Things that happen while the app is used: a run, a balance that moved, an added
        # vendor, and a newer reading of a sample.
        session.add(Run(id="run-1", file_name="x.pdf", file_hash="abc", status="completed",
                        decision="APPROVE"))
        session.get(PurchaseOrder, "PO-2231").billed_to_date = Decimal("180000.00")
        session.add(Vendor(id="V-006", name="Northwind Traders", tax_id="", city="", state=""))
        newer = session.exec(select(SavedExtraction).where(
            SavedExtraction.file_name == "acme_2026-11-05.pdf")).one()
        newer.record = {**newer.record, "invoice_number": "CHANGED"}
        session.commit()

    assert prepare_database(engine) is False  # a second start: nothing to seed

    with Session(engine) as session:
        assert session.get(Run, "run-1").decision == "APPROVE"
        assert session.get(PurchaseOrder, "PO-2231").billed_to_date == Decimal("180000.00")
        assert session.get(Vendor, "V-006") is not None
        assert count(session, Vendor) == 6 and count(session, Invoice) == 2
        assert count(session, SavedExtraction) == 15
        kept = session.exec(select(SavedExtraction).where(
            SavedExtraction.file_name == "acme_2026-11-05.pdf")).one()
        assert kept.record["invoice_number"] == "CHANGED"  # not overwritten


@pytest.mark.parametrize("file_name", list(CASES))
def test_with_the_live_call_failing_every_sample_still_reaches_its_decision(api, file_name):
    """What a freshly started server does if the AI service is down: the saved reading of
    the sample is used, the run says so, and the decision is the expected one."""
    with Session(api.engine) as session:
        assert load_sample_extractions(session) == 13
    api.reader.error = ExtractionError("The AI service could not be reached.")
    expected = CASES[file_name]["expected"]

    run = submit(api, file_name)

    assert run["status"] == "completed", run["error_message"]
    assert stage(run, "extract")["result"]["source"] == "saved_live_failed"
    assert run["decision"] == expected["decision"]
    assert run["po_id"] == expected["po_id"]
    assert set(expected["finding_codes"]) <= flagged(run)
    assert not set(expected["absent_codes"]) & flagged(run)


# --- DATA_DIR ----------------------------------------------------------------------------


def paths_with(env: dict[str, str]) -> list[str]:
    """The folders the app would use if started with these environment variables."""
    code = ("from app import config; print(config.VAR_DIR); print(config.DATABASE_URL); "
            "print(config.UPLOADS_DIR); print(config.PAGES_DIR)")
    clean = {k: v for k, v in os.environ.items() if k not in ("DATA_DIR", "DATABASE_URL")}
    done = subprocess.run([sys.executable, "-c", code], env={**clean, **env}, text=True,
                          capture_output=True, check=True, cwd=Path(__file__).parents[2])
    return done.stdout.split()


def test_data_dir_moves_all_runtime_state_and_defaults_to_var(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    assert paths_with({}) == [
        f"{repo}/var", f"sqlite:///{repo}/var/app.db", f"{repo}/var/uploads", f"{repo}/var/pages"]

    data = tmp_path.resolve() / "data"
    assert paths_with({"DATA_DIR": str(data)}) == [
        f"{data}", f"sqlite:///{data}/app.db", f"{data}/uploads", f"{data}/pages"]


# --- Serving the built web app -----------------------------------------------------------


def test_fastapi_serves_the_built_frontend_beside_the_api(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>the app</html>")
    (dist / "assets" / "app.js").write_text("console.log('app')")
    (tmp_path / "secret.txt").write_text("not for the browser")

    app = FastAPI()
    app.get("/api/health")(lambda: {"status": "ok"})
    assert serve_frontend(app, dist) is True
    client = TestClient(app)

    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/nothing-here").status_code == 404
    assert client.get("/").text == "<html>the app</html>"
    assert client.get("/runs/abc123").text == "<html>the app</html>"  # a screen of the app
    assert client.get("/assets/app.js").text == "console.log('app')"
    # A path that tries to climb out of the build folder gets the app, never the file.
    for sneaky in ("/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt"):
        assert "not for the browser" not in client.get(sneaky).text


def test_without_a_built_frontend_nothing_is_added(tmp_path):
    assert serve_frontend(FastAPI(), tmp_path / "missing") is False
