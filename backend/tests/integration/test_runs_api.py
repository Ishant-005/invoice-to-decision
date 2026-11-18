"""Runs over HTTP: submit, poll, state changes, review, sequences, reset and failures.

Everything here is the real app and the real pipeline. Only the AI call is replaced
(see conftest.py)."""

import pytest
from sqlmodel import Session, select

from app import config
from app.models import Invoice, Run, SavedExtraction, StageEvent
from app.pipeline.extract import ExtractionError
from app.pipeline.runner import STAGES, fail_interrupted_runs
from tests.answer_key import CASES, SEQUENCES
from tests.integration.conftest import flagged, poll, purchase_order, stage, submit

# --- A full run --------------------------------------------------------------------------


def test_a_run_is_accepted_at_once_and_can_be_polled_to_completion(api):
    response = api.client.post("/api/runs", data={"sample": "acme_2026-11-05.pdf"})
    assert response.status_code == 202
    created = response.json()
    assert created["status"] == "queued"
    assert created["url"] == f"/api/runs/{created['id']}"

    run = poll(api, created["id"])

    assert run["status"] == "completed"
    assert run["decision"] == "APPROVE"
    assert run["state"] == "approved"
    assert run["headline"] == "Approved: the invoice matches PO-2231 and every check passed."
    assert run["vendor_name"] == "Acme Packaging Pvt Ltd"
    assert run["invoice_number"] == "INV-1042"
    assert run["po_id"] == "PO-2231"
    assert run["decision_detail"]["next_action"].startswith("Schedule payment of ₹2,12,400")
    assert run["error_message"] is None


def test_a_finished_run_shows_six_stages_in_order_with_measured_durations(api):
    run = submit(api, "acme_2026-11-05.pdf")

    assert [s["stage"] for s in run["stages"]] == list(STAGES)
    assert all(s["status"] == "done" for s in run["stages"])
    assert all(isinstance(s["duration_ms"], float) and s["duration_ms"] >= 0
               for s in run["stages"])
    assert run["total_duration_ms"] == pytest.approx(
        sum(s["duration_ms"] for s in run["stages"]), abs=0.05)
    assert [s["uses_ai"] for s in run["stages"]] == [False, True, False, False, False, False]

    assert stage(run, "receive")["result"]["page_count"] == 1
    assert "page_images" not in stage(run, "receive")["result"]  # no server paths leak
    assert stage(run, "extract")["result"]["label"] == "read live by the AI model"
    assert stage(run, "extract")["result"]["record"]["total"] == "212400.00"
    assert stage(run, "validate")["result"]["pretax_amount"] == "180000.00"
    assert stage(run, "match")["result"]["po_match_type"] == "explicit_verified"
    assert stage(run, "decide")["result"]["decision"] == "APPROVE"
    # Findings sit with the stage that produced them.
    for name in ("validate", "match", "rules"):
        assert stage(run, name)["findings"]
        assert {f["stage"] for f in stage(run, name)["findings"]} == {name}


def test_stage_rows_are_written_while_the_run_is_in_progress(api):
    seen = {}

    def look_at_the_database():  # runs at the moment the AI call would be made
        with Session(api.engine) as session:
            seen["run_status"] = session.exec(select(Run)).one().status
            seen["stages"] = {e.stage: (e.status, e.duration_ms)
                              for e in session.exec(select(StageEvent))}

    api.reader.during_call = look_at_the_database
    submit(api, "acme_2026-11-05.pdf")

    assert seen["run_status"] == "running"
    assert set(seen["stages"]) == {"receive", "extract"}
    assert seen["stages"]["receive"][0] == "done"
    assert seen["stages"]["extract"] == ("running", None)  # no duration until it finishes


def test_money_is_sent_as_text_never_as_a_floating_point_number(api):
    run = submit(api, "acme_2026-11-05.pdf")
    assert run["gross_amount"] == "212400.00"
    assert run["pretax_amount"] == "180000.00"
    assert purchase_order(api, "PO-2231")["billed_to_date"] == "180000.00"


def test_the_page_image_of_a_run_is_served(api):
    run = submit(api, "acme_2026-11-05.pdf")
    assert run["pages"] == [f"/api/runs/{run['id']}/pages/1.png"]

    image = api.client.get(run["pages"][0])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")
    assert api.client.get(f"/api/runs/{run['id']}/pages/2.png").status_code == 404


def test_an_uploaded_pdf_goes_through_the_same_pipeline(api):
    pdf = (config.INVOICE_DIR / "brightline_2026-11-02.pdf").read_bytes()
    response = api.client.post(
        "/api/runs", files={"file": ("../../my invoice.pdf", pdf, "application/pdf")})
    assert response.status_code == 202
    run = poll(api, response.json()["id"])

    assert run["decision"] == "APPROVE"
    assert run["source"] == "upload"
    assert run["file_name"] == "my invoice.pdf"  # the folder part of the name is dropped
    assert run["pretax_amount"] == "100000.00"  # derived from the tax-inclusive total
    # Stored under the run's ID, not under the name the user sent.
    assert (config.UPLOADS_DIR / f"{run['id']}.pdf").read_bytes() == pdf


@pytest.mark.parametrize("file_name", list(CASES))
def test_every_sample_reaches_its_expected_decision_over_http(api, file_name):
    expected = CASES[file_name]["expected"]
    run = submit(api, file_name)

    assert run["status"] == "completed"
    assert run["decision"] == expected["decision"]
    assert run["owner"] == expected["owner"]
    assert run["po_id"] == expected["po_id"]
    assert stage(run, "match")["result"]["po_match_type"] == expected["po_match_type"]
    assert set(expected["finding_codes"]) <= flagged(run)
    assert not set(expected["absent_codes"]) & flagged(run)


# --- State updates -----------------------------------------------------------------------


def test_an_approval_adds_the_pretax_amount_to_the_po(api):
    before = purchase_order(api, "PO-2231")
    assert (before["billed_to_date"], before["remaining"]) == ("0.00", "180000.00")

    run = submit(api, "acme_2026-11-05.pdf")
    assert run["decision"] == "APPROVE"

    after = purchase_order(api, "PO-2231")
    assert (after["billed_to_date"], after["remaining"]) == ("180000.00", "0.00")
    assert [(i["invoice_number"], i["state"], i["run_id"]) for i in after["invoices"]] == [
        ("INV-1042", "approved", run["id"])]


def test_a_review_or_a_reject_does_not_change_any_po(api):
    balances = {po["id"]: po["billed_to_date"]
                for po in api.client.get("/api/purchase-orders").json()}

    assert submit(api, "corelight_2026-11-10.pdf")["decision"] == "REVIEW"
    assert submit(api, "quickfix_2026-11-09.pdf")["decision"] == "REJECT"

    assert balances == {po["id"]: po["billed_to_date"]
                        for po in api.client.get("/api/purchase-orders").json()}
    # The invoice waiting for review is still listed against its PO, clearly marked.
    assert purchase_order(api, "PO-2281")["invoices"][0]["state"] == "awaiting_review"


# --- Human review ------------------------------------------------------------------------


def resolve(api, run_id: str, **body):
    return api.client.post(f"/api/runs/{run_id}/resolve", json=body)


def test_approving_a_review_books_the_invoice_against_the_suggested_po(api):
    run = submit(api, "sharma_2026-11-08.pdf")  # no PO printed; PO-2290 is suggested
    assert (run["decision"], run["state"]) == ("REVIEW", "awaiting_review")
    assert purchase_order(api, "PO-2290")["billed_to_date"] == "0.00"

    response = resolve(api, run["id"], action="approve", comment="Confirmed with the buyer.")

    assert response.status_code == 200
    resolved = response.json()
    assert resolved["decision"] == "REVIEW"  # what the pipeline decided is kept
    assert resolved["state"] == "approved_by_reviewer"
    assert resolved["resolution"]["action"] == "approved"
    assert resolved["resolution"]["comment"] == "Confirmed with the buyer."
    assert resolved["resolution"]["resolved_at"].endswith("Z")
    po = purchase_order(api, "PO-2290")
    assert (po["billed_to_date"], po["remaining"]) == ("195000.00", "0.00")
    assert po["invoices"][0]["state"] == "approved"


def test_a_reviewer_may_approve_an_invoice_that_goes_over_the_po(api):
    run = submit(api, "zenith_2026-11-14.pdf")
    assert run["decision"] == "REVIEW"

    assert resolve(api, run["id"], action="approve",
                   comment="Procurement raised the PO.").status_code == 200

    po = purchase_order(api, "PO-2260")  # value 3,00,000; 1,00,000 billed at seed
    assert (po["billed_to_date"], po["remaining"]) == ("340000.00", "-40000.00")


def test_rejecting_a_review_leaves_the_po_alone_and_frees_the_invoice_for_resubmission(api):
    run = submit(api, "corelight_2026-11-10.pdf")

    response = resolve(api, run["id"], action="reject", comment="Price not agreed.")

    assert response.json()["state"] == "rejected_by_reviewer"
    po = purchase_order(api, "PO-2281")
    assert po["billed_to_date"] == "0.00"
    assert po["invoices"][0]["state"] == "rejected"
    # A rejected invoice does not count as an earlier submission: sending the same
    # file again is not flagged as a duplicate.
    again = submit(api, "corelight_2026-11-10.pdf")
    assert again["decision"] == "REVIEW"
    assert "DUPLICATE_EXACT" not in flagged(again)


def test_a_review_needs_a_comment_and_can_only_be_resolved_once(api):
    run = submit(api, "sharma_2026-11-08.pdf")

    assert resolve(api, run["id"], action="approve").status_code == 422
    assert resolve(api, run["id"], action="approve", comment="   ").status_code == 422
    assert resolve(api, run["id"], action="maybe", comment="hm").status_code == 422
    assert purchase_order(api, "PO-2290")["billed_to_date"] == "0.00"

    assert resolve(api, run["id"], action="approve", comment="ok").status_code == 200
    second = resolve(api, run["id"], action="approve", comment="again")
    assert second.status_code == 409
    assert purchase_order(api, "PO-2290")["billed_to_date"] == "195000.00"  # added once


def test_a_reviewer_cannot_book_an_invoice_against_another_vendors_po(api):
    run = submit(api, "sharma_2026-11-08.pdf")  # Sharma Office Supplies

    wrong_vendor = resolve(api, run["id"], action="approve", comment="x", po_id="PO-2231")
    no_such_po = resolve(api, run["id"], action="approve", comment="x", po_id="PO-0000")

    assert (wrong_vendor.status_code, no_such_po.status_code) == (422, 422)
    assert "different vendor" in wrong_vendor.json()["detail"]
    assert purchase_order(api, "PO-2231")["billed_to_date"] == "0.00"
    assert api.client.get(f"/api/runs/{run['id']}").json()["state"] == "awaiting_review"


def test_a_reviewer_can_choose_a_different_po_of_the_same_vendor(api):
    run = submit(api, "sharma_2026-11-08.pdf")  # PO-2290 suggested; PO-2252 is also Sharma's

    assert resolve(api, run["id"], action="approve", comment="Belongs to the stationery PO.",
                   po_id="PO-2252").status_code == 200

    assert purchase_order(api, "PO-2290")["billed_to_date"] == "0.00"
    assert purchase_order(api, "PO-2252")["billed_to_date"] == "195000.00"
    assert api.client.get(f"/api/runs/{run['id']}").json()["po_id"] == "PO-2252"


def test_only_review_runs_can_be_resolved(api):
    approved = submit(api, "acme_2026-11-05.pdf")
    rejected = submit(api, "quickfix_2026-11-09.pdf")

    assert resolve(api, approved["id"], action="reject", comment="x").status_code == 409
    assert resolve(api, rejected["id"], action="approve", comment="x").status_code == 409
    assert resolve(api, "no-such-run", action="approve", comment="x").status_code == 404


# --- The three sequences (no reset between steps) ----------------------------------------


@pytest.mark.parametrize("sequence", SEQUENCES, ids=[s["name"] for s in SEQUENCES])
def test_sequence_from_the_answer_key(api, sequence):
    for file_name in sequence["steps"]:
        run = submit(api, file_name)
    expected = sequence["expected_last"]

    assert run["decision"] == expected["decision"]
    assert set(expected["finding_codes"]) <= flagged(run)
    if "owner" in expected:
        assert run["owner"] == expected["owner"]
    if "po_overage" in expected:
        assert stage(run, "rules")["result"]["po_overage"] == expected["po_overage"]


def test_the_same_file_twice_is_rejected_and_not_read_again(api):
    first = submit(api, "acme_2026-11-05.pdf")
    second = submit(api, "acme_2026-11-05.pdf")

    assert (first["decision"], second["decision"]) == ("APPROVE", "REJECT")
    assert "DUPLICATE_EXACT" in flagged(second)
    assert stage(second, "receive")["result"]["seen_before"] is True
    assert stage(second, "extract")["result"]["label"] == "reused: identical file"
    assert api.reader.calls == 1  # the second run made no AI call
    assert purchase_order(api, "PO-2231")["billed_to_date"] == "180000.00"  # billed once


def test_october_then_over_balance_moves_the_po_only_once(api):
    assert submit(api, "zenith_2026-10-31.pdf")["decision"] == "APPROVE"
    assert purchase_order(api, "PO-2260")["billed_to_date"] == "200000.00"

    over = submit(api, "zenith_2026-11-14.pdf")

    assert over["decision"] == "REVIEW"
    assert "by ₹1,40,000 before tax" in over["headline"]
    assert "DUPLICATE_PROBABLE" not in flagged(over)
    assert purchase_order(api, "PO-2260")["billed_to_date"] == "200000.00"


# --- Reset -------------------------------------------------------------------------------


def test_reset_restores_the_seed_state(api):
    seed_orders = api.client.get("/api/purchase-orders").json()
    submit(api, "acme_2026-11-05.pdf")
    submit(api, "zenith_2026-10-31.pdf")
    review = submit(api, "sharma_2026-11-08.pdf")
    api.client.post(f"/api/runs/{review['id']}/resolve",
                    json={"action": "approve", "comment": "ok"})
    assert api.client.get("/api/purchase-orders").json() != seed_orders
    assert len(list(config.UPLOADS_DIR.glob("*.pdf"))) == 3

    response = api.client.post("/api/demo/reset")

    assert response.json() == {"status": "reset", "vendors": 5, "purchase_orders": 10,
                               "seeded_invoices": 2}
    assert api.client.get("/api/purchase-orders").json() == seed_orders
    listing = api.client.get("/api/runs").json()
    assert listing["runs"] == []
    assert [i["invoice_number"] for i in listing["seeded_history"]] == ["INV-1017", "ZFS-0911"]
    assert api.client.get(f"/api/runs/{review['id']}").status_code == 404
    assert api.client.get("/api/stats").json()["processed"] == 0
    assert list(config.UPLOADS_DIR.glob("*.pdf")) == []
    with Session(api.engine) as session:
        assert session.exec(select(StageEvent)).all() == []
        # Saved AI readings survive: the 2 seeded ones and the 3 read in this test.
        assert len(session.exec(select(SavedExtraction)).all()) == 5


def test_after_a_reset_the_same_invoice_is_approved_again(api):
    assert submit(api, "acme_2026-11-05.pdf")["decision"] == "APPROVE"
    assert submit(api, "acme_2026-11-05.pdf")["decision"] == "REJECT"

    api.client.post("/api/demo/reset")

    assert submit(api, "acme_2026-11-05.pdf")["decision"] == "APPROVE"
    assert purchase_order(api, "PO-2231")["billed_to_date"] == "180000.00"


def test_a_reset_during_a_run_abandons_it_without_touching_the_books(api):
    # The reset arrives while the AI call of a run is in flight.
    api.reader.during_call = lambda: api.client.post("/api/demo/reset")

    response = api.client.post("/api/runs", data={"sample": "acme_2026-11-05.pdf"})

    assert api.client.get(f"/api/runs/{response.json()['id']}").status_code == 404
    assert api.client.get("/api/runs").json()["runs"] == []
    assert purchase_order(api, "PO-2231")["billed_to_date"] == "0.00"
    with Session(api.engine) as session:
        assert session.exec(select(StageEvent)).all() == []
        assert len(session.exec(select(Invoice)).all()) == 2  # only the seeded history


# --- Failures ----------------------------------------------------------------------------


def test_a_run_fails_cleanly_when_extraction_raises_an_error(api):
    api.reader.error = ExtractionError("The AI service could not be reached.")

    run = submit(api, "acme_2026-11-05.pdf")

    assert run["status"] == "failed"
    assert run["state"] == "failed"
    assert run["failed_stage"] == "extract"
    assert run["error_message"] == "The AI service could not be reached."
    assert run["decision"] is None and run["decision_detail"] is None
    assert run["finished_at"] is not None
    assert [(s["stage"], s["status"]) for s in run["stages"]] == [
        ("receive", "done"), ("extract", "failed"), ("validate", "not_run"),
        ("match", "not_run"), ("rules", "not_run"), ("decide", "not_run")]
    assert stage(run, "extract")["duration_ms"] is not None
    # Nothing was recorded: no invoice, no change to the PO.
    po = purchase_order(api, "PO-2231")
    assert (po["billed_to_date"], po["invoices"]) == ("0.00", [])
    assert api.client.get("/api/stats").json()["failed"] == 1


def test_an_unexpected_error_fails_the_run_without_leaking_details(api):
    api.reader.error = RuntimeError("secret internal detail /srv/app/key")

    run = submit(api, "acme_2026-11-05.pdf")

    assert (run["status"], run["failed_stage"], run["decision"]) == ("failed", "extract", None)
    assert run["error_message"] == (
        "Something unexpected went wrong in the Extract stage (RuntimeError). No decision "
        "was made. The details are in the server log.")
    assert purchase_order(api, "PO-2231")["billed_to_date"] == "0.00"


def test_a_failed_run_does_not_block_a_later_successful_one(api):
    api.reader.error = ExtractionError("The AI service could not be reached.")
    assert submit(api, "acme_2026-11-05.pdf")["status"] == "failed"

    api.reader.error = None
    run = submit(api, "acme_2026-11-05.pdf")

    assert run["decision"] == "APPROVE"  # the failed attempt is not an "earlier invoice"
    assert purchase_order(api, "PO-2231")["billed_to_date"] == "180000.00"


def test_the_saved_reading_is_used_and_labelled_when_the_live_call_fails(api):
    submit(api, "corelight_2026-11-10.pdf")  # read once; the reading is saved
    api.client.post("/api/demo/reset")  # saved readings survive a reset
    api.reader.error = ExtractionError("The AI service could not be reached.")

    run = submit(api, "corelight_2026-11-10.pdf")

    assert run["decision"] == "REVIEW"
    result = stage(run, "extract")["result"]
    assert result["label"] == "served from saved result (live call failed)"
    assert result["live_error"] == "The AI service could not be reached."


def test_a_file_that_is_not_a_pdf_fails_in_the_receive_stage(api):
    response = api.client.post(
        "/api/runs", files={"file": ("notes.pdf", b"just some text", "application/pdf")})
    assert response.status_code == 202
    run = poll(api, response.json()["id"])

    assert (run["status"], run["failed_stage"]) == ("failed", "receive")
    assert run["error_message"] == "Only PDF files are accepted. This file is not a PDF."
    assert run["pages"] == []
    assert api.reader.calls == 0  # nothing was sent to the AI model


def test_bad_submissions_are_turned_away(api, monkeypatch):
    assert api.client.post("/api/runs").status_code == 422  # neither file nor sample
    assert api.client.post("/api/runs", data={"sample": "nope.pdf"}).status_code == 404
    assert api.client.post("/api/runs", data={"sample": "../../.env"}).status_code == 404
    assert api.client.post("/api/runs", data={"sample": "expected.json"}).status_code == 404

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1000)
    too_big = api.client.post(
        "/api/runs", files={"file": ("big.pdf", b"%PDF-" + b"0" * 1000, "application/pdf")})
    assert too_big.status_code == 413
    assert api.client.get("/api/runs").json()["runs"] == []  # none of these created a run
    assert api.client.get("/api/runs/unknown").status_code == 404


def test_runs_left_unfinished_by_a_stopped_server_are_marked_failed_on_startup(api):
    with Session(api.engine) as session:
        session.add(Run(id="stuck", file_name="x.pdf", file_hash="h", status="running"))
        session.add(StageEvent(run_id="stuck", stage="receive", status="done", duration_ms=1.0))
        session.add(StageEvent(run_id="stuck", stage="extract", status="running"))
        session.commit()
        assert fail_interrupted_runs(session) == 1

    run = api.client.get("/api/runs/stuck").json()
    assert (run["status"], run["failed_stage"], run["decision"]) == ("failed", "extract", None)
    assert "server restarted" in run["error_message"]
    assert stage(run, "extract")["status"] == "failed"
