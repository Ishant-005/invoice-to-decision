"""Adding a purchase order by hand: the validation rules, the reset, and one invoice
approved end to end against a newly added PO (the AI call is stood in, as in every API test)."""

import hashlib

from app import config
from tests.answer_key import CASES
from tests.integration import conftest
from tests.integration.conftest import purchase_order, submit

# TODAY in these tests is 18 Nov 2026 (see conftest).
GOOD = {
    "vendor_id": "V-001", "po_number": "PO-2310", "po_date": "2026-11-10",
    "lines": [
        {"description": "Corrugated box 12x10x8", "quantity": "500", "unit_price": "180.00"},
        {"description": "Bubble wrap roll", "quantity": "200", "unit_price": "450.00"},
    ],
}


def add(api, **changes):
    return api.client.post("/api/purchase-orders", json={**GOOD, **changes})


def errors(api, **changes) -> dict[str, str]:
    response = add(api, **changes)
    assert response.status_code == 422, response.text
    return response.json()["errors"]


def line(**changes) -> dict:
    return {"description": "Tape", "quantity": "10", "unit_price": "25.50", **changes}


# --- A good purchase order ---------------------------------------------------------------


def test_a_new_po_starts_open_with_nothing_billed_and_its_value_is_the_sum_of_its_lines(api):
    response = add(api, lines=[line(), line(description="Labels", quantity="2.5",
                                            unit_price="99.99")])
    assert response.status_code == 201, response.text
    po = response.json()

    assert po["id"] == "PO-2310" and po["vendor_name"] == "Acme Packaging Pvt Ltd"
    assert (po["status"], po["billed_to_date"]) == ("open", "0.00")
    # 10 x 25.50 = 255.00; 2.5 x 99.99 = 249.975, rounded to whole paise = 249.98
    assert [ln["amount"] for ln in po["lines"]] == ["255.00", "249.98"]
    assert po["value"] == "504.98" and po["remaining"] == "504.98"
    assert [ln["line_no"] for ln in po["lines"]] == [1, 2]
    assert po["invoices"] == []
    assert purchase_order(api, "PO-2310") == po
    assert len(api.client.get("/api/purchase-orders").json()) == 11


def test_a_bare_number_is_stored_in_the_usual_form(api):
    assert add(api, po_number=" 2310 ").json()["id"] == "PO-2310"


def test_today_is_accepted_as_the_po_date(api):
    assert add(api, po_date="2026-11-18").status_code == 201


# --- The validation rules ----------------------------------------------------------------


def test_the_vendor_must_be_an_existing_one(api):
    assert errors(api, vendor_id="V-999") == {"vendor_id": "Choose a vendor from the list."}
    assert "vendor_id" in errors(api, vendor_id="")


def test_the_po_number_must_be_unique_after_normalisation(api):
    # PO-2231 is in the seed data; all of these are the same number to the Match stage.
    for same in ("PO-2231", "2231", "po 2231", "P.O. #2231"):
        assert errors(api, po_number=same) == {
            "po_number": "PO-2231 already exists. Choose a different number."}

    assert add(api, po_number="PO-2310").status_code == 201
    assert "PO-2310 already exists" in errors(api, po_number="2310")["po_number"]


def test_the_po_number_cannot_be_empty_or_only_punctuation(api):
    for bad in ("", "   ", "PO-", "#", "1234567890123"):
        assert "po_number" in errors(api, po_number=bad)


def test_the_po_date_cannot_be_in_the_future_or_missing(api):
    assert errors(api, po_date="2026-11-19") == {
        "po_date": "The PO date cannot be in the future."}
    assert errors(api, po_date="") == {"po_date": "Enter the PO date."}
    assert errors(api, po_date="19/11/2026") == {"po_date": "Enter the PO date."}


def test_there_must_be_at_least_one_line(api):
    assert errors(api, lines=[]) == {"lines": "Add at least one line."}


def test_quantities_and_prices_must_be_positive_plain_numbers(api):
    for bad in ("0", "0.00", "-5", "", "abc", "1e3", "NaN", "Infinity", "1.234", "1,000"):
        assert set(errors(api, lines=[line(quantity=bad)])) == {"lines.0.quantity"}, bad
        assert set(errors(api, lines=[line(unit_price=bad)])) == {"lines.0.unit_price"}, bad


def test_every_line_needs_a_description_and_errors_name_the_line(api):
    found = errors(api, lines=[line(), line(description="  ", quantity="0")])
    assert found == {
        "lines.1.description": "Describe what is being ordered.",
        "lines.1.quantity": "Enter a quantity above zero, with at most 2 decimal places."}


def test_all_problems_are_reported_together_and_nothing_is_saved(api):
    found = errors(api, vendor_id="V-999", po_number="2231", po_date="2027-01-01", lines=[])
    assert set(found) == {"vendor_id", "po_number", "po_date", "lines"}
    assert len(api.client.get("/api/purchase-orders").json()) == 10


# --- Reset -------------------------------------------------------------------------------


def test_reset_demo_data_removes_added_purchase_orders(api):
    assert add(api).status_code == 201
    assert api.client.post("/api/demo/reset").json()["purchase_orders"] == 10
    assert api.client.get("/api/purchase-orders/PO-2310").status_code == 404
    assert add(api).status_code == 201  # the number is free again


# --- End to end --------------------------------------------------------------------------


def test_an_invoice_against_a_newly_added_po_is_approved_end_to_end(api, monkeypatch):
    assert add(api).status_code == 201  # PO-2310 for Acme: the same goods as sample 1

    # The stand-in reader returns sample 1 as read, except that the invoice now quotes the
    # new purchase order (written without its "PO-" prefix).
    sample = "acme_2026-11-05.pdf"
    file_hash = hashlib.sha256((config.INVOICE_DIR / sample).read_bytes()).hexdigest()
    truth = {**CASES[sample]["truth"], "po_reference": "2310"}
    monkeypatch.setitem(conftest.TRUTH_BY_HASH, file_hash, truth)

    run = submit(api, sample)

    assert run["status"] == "completed", run["error_message"]
    assert run["decision"] == "APPROVE" and run["state"] == "approved"
    assert run["po_id"] == "PO-2310"
    po = purchase_order(api, "PO-2310")
    assert (po["value"], po["billed_to_date"], po["remaining"]) == (
        "180000.00", "180000.00", "0.00")
    assert [(i["invoice_number"], i["state"], i["run_id"]) for i in po["invoices"]] == [
        ("INV-1042", "approved", run["id"])]
    # The seed PO for the same goods was not touched.
    assert purchase_order(api, "PO-2231")["billed_to_date"] == "0.00"
