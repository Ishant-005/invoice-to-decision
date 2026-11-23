"""Adding a vendor by hand: the validation rules, the look-alike warning, the reset, and one
invoice from a new vendor against a new PO approved end to end (the AI call is stood in)."""

import hashlib

from app import config
from tests.answer_key import CASES
from tests.integration import conftest
from tests.integration.conftest import flagged, purchase_order, submit

GSTIN = "06AAACN1234A1Z5"  # a well-formed GSTIN that no seed vendor uses


def add(api, name="Northwind Traders Pvt Ltd", gstin="", **more):
    return api.client.post("/api/vendors", json={"name": name, "gstin": gstin, **more})


def check(api, name="Northwind Traders Pvt Ltd", gstin="") -> dict:
    return api.client.post("/api/vendors/check", json={"name": name, "gstin": gstin}).json()


def errors(api, **fields) -> dict[str, str]:
    response = add(api, **fields)
    assert response.status_code == 422, response.text
    assert response.json()["errors"] == check(api, **fields)["errors"]  # same rules either way
    return response.json()["errors"]


# --- A good vendor -----------------------------------------------------------------------


def test_a_new_vendor_is_active_and_gets_the_next_free_v_number(api):
    assert check(api) == {"vendor_id": "V-006", "errors": {}, "similar": None}

    response = add(api, name="  Northwind   Traders Pvt Ltd ", gstin=" 06aaacn1234a1z5 ")
    assert response.status_code == 201, response.text
    assert response.json() == {
        "id": "V-006", "name": "Northwind Traders Pvt Ltd", "tax_id": GSTIN, "status": "active",
        "city": "", "state": "", "purchase_order_ids": []}
    assert response.json() in api.client.get("/api/vendors").json()
    assert add(api, name="Second Supplier").json()["id"] == "V-007"


def test_the_gstin_is_optional(api):
    response = add(api, gstin="")
    assert response.status_code == 201 and response.json()["tax_id"] == ""
    # Two vendors may both have no GSTIN on file.
    assert add(api, name="Second Supplier", gstin="").status_code == 201


# --- The validation rules ----------------------------------------------------------------


def test_the_name_is_required(api):
    assert errors(api, name="") == {"name": "Enter the vendor's name."}
    assert errors(api, name="   ") == {"name": "Enter the vendor's name."}
    assert "more than a company suffix" in errors(api, name="Pvt. Ltd.")["name"]
    assert "under 120" in errors(api, name="x" * 121)["name"]


def test_a_name_that_matches_an_existing_vendor_once_cleaned_is_refused(api):
    for same in ("Acme Packaging Pvt Ltd", "ACME PACKAGING PRIVATE LIMITED", "acme-packaging",
                 "Acme Packaging Co."):
        assert errors(api, name=same) == {
            "name": "Acme Packaging Pvt Ltd (V-001) already has this name."}, same
    # Ticking the look-alike box does not get round an exact match.
    assert add(api, name="Acme Packaging", confirm_similar=True).status_code == 422


def test_a_gstin_must_have_the_standard_15_character_form(api):
    for bad in ("06AAACN1234A1Z", "06AAACN1234A1Z55", "ABCDEFGHIJKLMNO", "06AAACN1234A1X5",
                "06aaacn-1234a1z5"):
        assert "15 characters" in errors(api, gstin=bad)["gstin"], bad


def test_a_gstin_that_is_already_used_is_refused(api):
    for used in ("06AAACA0001A1Z1", "06aaaca 0001a1z1"):
        assert errors(api, gstin=used) == {
            "gstin": "This GSTIN is already used by Acme Packaging Pvt Ltd (V-001)."}
    assert len(api.client.get("/api/vendors").json()) == 5  # nothing was saved


# --- The look-alike warning --------------------------------------------------------------


def test_a_look_alike_name_is_warned_about_and_needs_a_tick_to_save(api):
    found = check(api, name="Acme Packagng Pvt Ltd")  # one letter missing
    assert found["errors"] == {}
    assert found["similar"]["id"] == "V-001"
    assert found["similar"]["name"] == "Acme Packaging Pvt Ltd"
    assert found["similar"]["score"] >= 88

    refused = add(api, name="Acme Packagng Pvt Ltd")
    assert refused.status_code == 409
    assert refused.json()["similar"]["id"] == "V-001"
    assert "Acme Packaging Pvt Ltd (V-001)" in refused.json()["detail"]
    assert len(api.client.get("/api/vendors").json()) == 5

    confirmed = add(api, name="Acme Packagng Pvt Ltd", confirm_similar=True)
    assert confirmed.status_code == 201 and confirmed.json()["id"] == "V-006"


def test_a_name_that_is_not_alike_gets_no_warning(api):
    assert check(api, name="Acme Paper Mills")["similar"] is None
    assert check(api, name="Northwind Traders")["similar"] is None


# --- Reset -------------------------------------------------------------------------------


def test_reset_demo_data_removes_added_vendors_and_their_purchase_orders(api):
    assert add(api).status_code == 201
    assert api.client.post("/api/purchase-orders", json={
        "vendor_id": "V-006", "po_number": "2310", "po_date": "2026-11-10",
        "lines": [{"description": "Tape", "quantity": "1", "unit_price": "1"}]}).status_code == 201

    assert api.client.post("/api/demo/reset").json()["vendors"] == 5
    assert [v["id"] for v in api.client.get("/api/vendors").json()] == [
        "V-001", "V-002", "V-003", "V-004", "V-005"]
    assert api.client.get("/api/purchase-orders/PO-2310").status_code == 404
    assert check(api)["vendor_id"] == "V-006"  # the ID is free again


# --- End to end --------------------------------------------------------------------------


def new_vendor_invoice(api, monkeypatch, **changes) -> dict:
    """Run sample 1 with the stand-in reader returning it as an invoice from Northwind
    Traders against PO-2310, then return the finished run."""
    sample = "acme_2026-11-05.pdf"
    file_hash = hashlib.sha256((config.INVOICE_DIR / sample).read_bytes()).hexdigest()
    truth = {**CASES[sample]["truth"], "vendor_name": "Northwind Traders Private Limited",
             "vendor_tax_id": GSTIN, "po_reference": "PO-2310", **changes}
    monkeypatch.setitem(conftest.TRUTH_BY_HASH, file_hash, truth)
    return submit(api, sample)


def add_po_for(api, vendor_id: str):
    response = api.client.post("/api/purchase-orders", json={
        "vendor_id": vendor_id, "po_number": "PO-2310", "po_date": "2026-11-01",
        "lines": [
            {"description": "Corrugated box 12x10x8", "quantity": "500", "unit_price": "180"},
            {"description": "Bubble wrap roll", "quantity": "200", "unit_price": "450"}]})
    assert response.status_code == 201, response.text


def test_an_invoice_from_a_new_vendor_against_a_new_po_is_approved_end_to_end(api, monkeypatch):
    # Before the vendor exists, the same invoice is rejected: the vendor is unknown.
    before = new_vendor_invoice(api, monkeypatch, invoice_number="NT-0001")
    assert before["decision"] == "REJECT" and "VENDOR_NOT_FOUND" in flagged(before)

    vendor = add(api, gstin=GSTIN).json()
    add_po_for(api, vendor["id"])

    run = new_vendor_invoice(api, monkeypatch, invoice_number="NT-0002")

    assert run["status"] == "completed", run["error_message"]
    assert run["decision"] == "APPROVE" and run["state"] == "approved"
    assert (run["vendor_id"], run["vendor_name"]) == ("V-006", "Northwind Traders Pvt Ltd")
    assert run["po_id"] == "PO-2310"
    po = purchase_order(api, "PO-2310")
    assert (po["value"], po["billed_to_date"], po["remaining"]) == (
        "180000.00", "180000.00", "0.00")


def test_a_vendor_without_a_gstin_on_file_goes_to_review_if_the_invoice_prints_one(
        api, monkeypatch):
    vendor = add(api, gstin="").json()
    add_po_for(api, vendor["id"])

    run = new_vendor_invoice(api, monkeypatch)

    assert run["decision"] == "REVIEW" and "VENDOR_TAX_ID_CONFLICT" in flagged(run)
    messages = [f["message"] for s in run["stages"] for f in s["findings"]
                if f["code"] == "VENDOR_TAX_ID_CONFLICT"]
    assert "the vendor master has no GSTIN on file" in messages[0]
