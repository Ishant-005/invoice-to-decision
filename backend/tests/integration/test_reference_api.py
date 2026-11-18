"""The list, dashboard and reference endpoints."""

from tests.integration.conftest import submit


def test_samples_lists_the_13_invoices_without_their_expected_outcome(api):
    samples = api.client.get("/api/samples").json()

    assert [s["case"] for s in samples] == list(range(1, 14))
    assert samples[0] == {
        "case": 1, "file": "01_acme_clean.pdf", "scanned": False,
        "description": "Acme Packaging: corrugated boxes and bubble wrap, quoting PO-2231"}
    assert all(set(s) == {"case", "file", "description", "scanned"} for s in samples)
    assert [s["case"] for s in samples if s["scanned"]] == [3, 8, 10]


def test_purchase_orders_show_value_billed_remaining_lines_and_invoices(api):
    orders = api.client.get("/api/purchase-orders").json()
    assert len(orders) == 10

    po = api.client.get("/api/purchase-orders/PO-2260").json()
    assert po == next(o for o in orders if o["id"] == "PO-2260")
    assert po["vendor_name"] == "Zenith Facility Services Pvt Ltd"
    assert (po["value"], po["billed_to_date"], po["remaining"]) == (
        "300000.00", "100000.00", "200000.00")
    assert len(po["lines"]) == 1 and po["lines"][0]["unit_price"] == "100000.00"
    assert [(i["invoice_number"], i["is_seeded"], i["run_id"]) for i in po["invoices"]] == [
        ("ZFS-0911", True, None)]
    assert api.client.get("/api/purchase-orders/PO-0000").status_code == 404


def test_vendors_lists_the_five_vendors_with_their_purchase_orders(api):
    vendors = api.client.get("/api/vendors").json()
    assert [v["id"] for v in vendors] == ["V-001", "V-002", "V-003", "V-004", "V-005"]
    assert vendors[0]["name"] == "Acme Packaging Pvt Ltd"
    assert vendors[0]["purchase_order_ids"] == ["PO-2219", "PO-2231"]


def test_rules_endpoint_returns_the_thresholds_in_force(api):
    rules = api.client.get("/api/config/rules").json()
    assert set(rules) == {"validate", "match", "rules"}
    assert rules["rules"]["po_overage_max_percent"] == "2"
    assert rules["rules"]["po_overage_max_rupees"] == "5000"
    assert rules["match"]["vendor_fuzzy_min_score"] == 88
    assert rules["validate"]["currency"] == "INR"


def test_runs_list_is_newest_first_and_can_be_filtered(api):
    first = submit(api, "01_acme_clean.pdf")  # APPROVE, Acme
    second = submit(api, "07_corelight_price_hike.pdf")  # REVIEW, Corelight
    third = submit(api, "13_unknown_vendor.pdf")  # REJECT, not in the vendor master

    def ids(query: str = "") -> list[str]:
        return [run["id"] for run in api.client.get(f"/api/runs{query}").json()["runs"]]

    assert ids() == [third["id"], second["id"], first["id"]]
    assert ids("?decision=REVIEW") == [second["id"]]
    assert ids("?decision=approve") == [first["id"]]
    assert ids("?state=awaiting_review") == [second["id"]]
    assert ids("?vendor=V-004") == [second["id"]]
    assert ids("?status=completed&decision=REJECT") == [third["id"]]
    assert ids("?status=failed") == []

    rows = {run["id"]: run for run in api.client.get("/api/runs").json()["runs"]}
    assert rows[second["id"]]["headline"] == (
        "Needs review: the invoice takes PO-2281 over its value by ₹12,000 before tax "
        "(and 1 more issue).")
    assert rows[second["id"]]["owner_label"] == "Procurement"
    assert rows[second["id"]]["gross_amount"] == "191160.00"
    # An unknown vendor has no ID; the dashboard shows the name printed on the invoice.
    assert (rows[third["id"]]["vendor_id"], rows[third["id"]]["vendor_name"]) == (
        None, "QUICKFIX HARDWARE CO.")
    assert rows[first["id"]]["created_at"].endswith("Z")

    listing = api.client.get("/api/runs?vendor=V-001").json()
    assert [i["invoice_number"] for i in listing["seeded_history"]] == ["INV-1017"]


def test_stats_count_runs_by_outcome_and_add_up_the_approved_value(api):
    empty = api.client.get("/api/stats").json()
    assert empty["processed"] == 0 and empty["auto_approved_percent"] is None
    assert empty["value_approved_gross"] == "0" and empty["seeded_invoices"] == 2

    submit(api, "01_acme_clean.pdf")  # APPROVE: 1,80,000 before tax, 2,12,400 with tax
    submit(api, "13_unknown_vendor.pdf")  # REJECT
    submit(api, "07_corelight_price_hike.pdf")  # REVIEW, left waiting
    review = submit(api, "09_sharma_no_po.pdf")  # REVIEW, then approved by a person
    api.client.post(f"/api/runs/{review['id']}/resolve",
                    json={"action": "approve", "comment": "ok"})

    stats = api.client.get("/api/stats").json()
    assert stats == {
        "processed": 4, "auto_approved": 1, "auto_approved_percent": 25.0,
        "awaiting_review": 1, "approved_by_reviewer": 1, "rejected": 1,
        "rejected_by_reviewer": 0, "failed": 0, "in_progress": 0,
        "value_approved_pretax": "375000.00", "value_approved_gross": "442500.00",
        "seeded_invoices": 2}
