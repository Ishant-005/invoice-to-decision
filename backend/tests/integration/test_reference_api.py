"""The list, dashboard and reference endpoints."""

from tests.integration.conftest import submit


def test_samples_lists_the_13_invoices_without_their_expected_outcome(api):
    samples = api.client.get("/api/samples").json()

    assert [s["case"] for s in samples] == list(range(1, 14))
    assert samples[0] == {
        "case": 1, "file": "acme_2026-11-05.pdf", "scanned": False,
        "description": "Acme Packaging: corrugated boxes and bubble wrap"}
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
    first = submit(api, "acme_2026-11-05.pdf")  # APPROVE, Acme
    second = submit(api, "corelight_2026-11-10.pdf")  # REVIEW, Corelight
    third = submit(api, "quickfix_2026-11-09.pdf")  # REJECT, not in the vendor master

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

    submit(api, "acme_2026-11-05.pdf")  # APPROVE: 1,80,000 before tax, 2,12,400 with tax
    submit(api, "quickfix_2026-11-09.pdf")  # REJECT
    submit(api, "corelight_2026-11-10.pdf")  # REVIEW, left waiting
    review = submit(api, "sharma_2026-11-08.pdf")  # REVIEW, then approved by a person
    api.client.post(f"/api/runs/{review['id']}/resolve",
                    json={"action": "approve", "comment": "ok"})

    stats = api.client.get("/api/stats").json()
    assert stats == {
        "total_runs": 4, "processed": 4, "approved": 2, "auto_approved": 1,
        "auto_approved_percent": 25.0, "approved_by_reviewer": 1, "awaiting_review": 1,
        "rejected": 1, "rejected_by_process": 1, "rejected_by_reviewer": 0, "failed": 0,
        "in_progress": 0, "value_approved_pretax": "375000.00",
        "value_approved_gross": "442500.00", "seeded_invoices": 2}


def test_the_dashboard_tiles_agree_with_the_runs_listed_under_each_filter(api):
    """The dashboard shows the stats as tiles and filters the runs list by state. For the
    two to agree, each total must equal the number of runs in the matching states, also
    after a reviewer has approved one REVIEW run and rejected another."""

    def check():
        stats = api.client.get("/api/stats").json()
        states = [run["state"] for run in api.client.get("/api/runs").json()["runs"]]
        assert stats["total_runs"] == len(states)
        assert stats["approved"] == sum(s in ("approved", "approved_by_reviewer") for s in states)
        assert stats["awaiting_review"] == states.count("awaiting_review")
        assert stats["rejected"] == sum(s in ("rejected", "rejected_by_reviewer") for s in states)
        assert stats["rejected_by_process"] == states.count("rejected")
        assert stats["rejected_by_reviewer"] == states.count("rejected_by_reviewer")
        return stats

    check()  # nothing run yet
    submit(api, "acme_2026-11-05.pdf")  # APPROVE
    submit(api, "quickfix_2026-11-09.pdf")  # REJECT
    submit(api, "corelight_2026-11-10.pdf")  # REVIEW, left waiting
    to_approve = submit(api, "sharma_2026-11-08.pdf")  # REVIEW
    to_reject = submit(api, "acme_2026-10-03.pdf")  # REVIEW
    api.client.post("/api/runs", files={"file": ("notes.pdf", b"not a pdf")})  # fails
    before = check()
    assert (before["approved"], before["awaiting_review"], before["rejected"]) == (1, 3, 1)

    api.client.post(f"/api/runs/{to_approve['id']}/resolve",
                    json={"action": "approve", "comment": "ok"})
    api.client.post(f"/api/runs/{to_reject['id']}/resolve",
                    json={"action": "reject", "comment": "same bill"})
    after = check()
    assert (after["approved"], after["awaiting_review"], after["rejected"]) == (2, 1, 2)
    assert (after["rejected_by_process"], after["rejected_by_reviewer"]) == (1, 1)
    assert (after["total_runs"], after["failed"]) == (6, 1)


def test_a_sample_preview_is_a_png_and_an_unknown_sample_is_404(api):
    response = api.client.get("/api/samples/acme_2026-11-05.pdf/preview.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert api.client.get("/api/samples/..%2F..%2F.env/preview.png").status_code == 404
    assert api.client.get("/api/samples/nothing.pdf/preview.png").status_code == 404


def test_a_probable_duplicate_links_to_the_earlier_invoice_with_its_reading_and_page(api):
    run = submit(api, "acme_2026-10-03.pdf")
    rules = next(s for s in run["stages"] if s["stage"] == "rules")
    link = rules["result"]["duplicates"][0]

    earlier = api.client.get(f"/api/invoices/{link['invoice_id']}").json()
    assert earlier["invoice_number"] == "INV-1017"
    assert earlier["is_seeded"] is True
    assert earlier["vendor_name"] == "Acme Packaging Pvt Ltd"
    assert earlier["gross_amount"] == "118000.00"  # money stays text
    assert earlier["record"]["line_items"][0]["description"] == "Shipping carton 18x12x10"

    # The seeded invoice never went through a run; its page is rendered when first asked for.
    page = api.client.get(earlier["pages"][0])
    assert page.status_code == 200
    assert page.content.startswith(b"\x89PNG")


def test_an_invoice_from_a_run_can_be_fetched_and_an_unknown_one_is_404(api):
    run = submit(api, "acme_2026-11-05.pdf")
    # The two seeded invoices are numbers 1 and 2, so the first run's invoice is number 3.
    invoice = api.client.get("/api/invoices/3").json()
    assert invoice["run_id"] == run["id"]
    assert invoice["invoice_number"] == "INV-1042"
    assert api.client.get(invoice["pages"][0]).status_code == 200
    assert api.client.get("/api/invoices/9999").status_code == 404
    assert api.client.get("/api/invoices/9999/pages/1.png").status_code == 404
