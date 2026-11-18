"""Stage 6, Decide: the worst finding sets the decision; all wording comes from templates."""

from datetime import date

from app.pipeline.decide import TEMPLATES
from tests.unit.builders import earlier_invoice, make_books, make_po, make_record, run


def test_no_problems_means_approve_with_no_owner():
    decision = run().decision
    assert decision.decision == "APPROVE"
    assert decision.owner == "none"
    assert decision.reasons == []
    assert decision.headline == "Approved: the invoice matches PO-100 and every check passed."
    assert decision.next_action == ("Schedule payment of ₹11,800. PO-100 billed-to-date rises "
                                    "by ₹10,000 to ₹10,000.")
    assert len(decision.passed) > 10


def test_warnings_alone_still_approve_and_are_listed_as_notes():
    books = make_books(purchase_orders=[make_po(value="100000", billed="91000")])
    decision = run(books=books).decision
    assert decision.decision == "APPROVE"
    assert [r.code for r in decision.reasons] == ["PO_BALANCE"]
    assert decision.headline.startswith("Approved with 1 note:")


def test_any_review_finding_means_review():
    decision = run(make_record(total="12800")).decision
    assert decision.decision == "REVIEW"
    assert decision.owner == "vendor"
    assert decision.headline == "Needs review: the invoice's own figures do not add up."
    assert decision.next_action == TEMPLATES["TOTALS"][1]


def test_any_reject_finding_means_reject_even_with_review_findings_present():
    result = run(make_record(vendor_name="Quickfix Hardware Co.", vendor_tax_id=None,
                             po_reference="PO-9999", total="12800"))
    decision = result.decision
    assert decision.decision == "REJECT"
    assert decision.owner == "procurement"
    # The reject reason leads; the review-level problems are still all listed.
    assert [r.code for r in decision.reasons] == ["VENDOR_NOT_FOUND", "TOTALS", "PO_NOT_FOUND"]
    assert decision.headline == ("Rejected: the vendor is not in the vendor master "
                                 "(and 2 more issues).")


def test_reasons_put_problems_before_notes():
    # Over the PO beyond tolerance (problem) with an old date (note).
    books = make_books(purchase_orders=[make_po(value="100000", billed="95000",
                                                po_date=date(2026, 1, 1))])
    decision = run(make_record(invoice_date="2026-03-01"), books).decision
    assert [(r.code, r.status) for r in decision.reasons] == [("PO_BALANCE", "fail"),
                                                               ("DATE_SANITY", "warn")]


def test_the_owner_is_whoever_owns_the_first_blocking_problem():
    # A probable duplicate (AP) and a PO overage (procurement): pipeline order puts AP first.
    books = make_books(purchase_orders=[make_po(value="100000", billed="95000")],
                       invoices=[earlier_invoice(invoice_date=date(2026, 11, 10))])
    decision = run(books=books).decision
    assert [r.code for r in decision.reasons] == ["DUPLICATE_PROBABLE", "PO_BALANCE"]
    assert decision.owner == "ap"
    assert decision.headline.endswith("(and 1 more issue).")


def test_checks_that_could_not_run_are_listed_as_not_checked():
    decision = run(make_record(po_reference="PO-9999")).decision
    assert any(line.startswith("PO_BALANCE:") for line in decision.not_checked)


def test_same_inputs_always_give_the_same_decision():
    assert run().model_dump() == run().model_dump()


def test_every_finding_that_can_block_has_a_headline_and_a_next_action():
    """Run a spread of bad invoices and check no blocking code falls back to generic text."""
    bad = [make_record(document_type="other"), make_record(invoice_number=None),
           make_record(total="12800"), make_record(invoice_date="2027-01-01"),
           make_record(currency="USD"), make_record(vendor_name="Nobody", vendor_tax_id=None),
           make_record(vendor_name="Acme Packagng", vendor_tax_id=None),
           make_record(vendor_tax_id="27AAACX9999X1Z5"), make_record(po_reference="PO-9999"),
           make_record(po_reference=None), make_record(line_items=[], subtotal=None,
                                                       tax_amount=None)]
    for record in bad:
        result = run(record)
        blocking = [f.code for f in result.findings if f.severity != "info"]
        assert blocking, record
        assert set(blocking) <= set(TEMPLATES), blocking
