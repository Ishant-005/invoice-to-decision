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
    assert decision.next_action == ("Schedule payment of ₹11,800 including tax. PO-100 now has "
                                    "₹10,000 of ₹1,00,000 billed before tax, ₹90,000 remaining.")


def test_an_approval_lists_what_passed_in_plain_english():
    assert run().decision.passed == [
        "The document is an invoice.",
        "Invoice number, vendor name, invoice date and total are all present.",
        "Quantity × unit price equals the amount on every line checked (1 line).",
        ("The invoice's figures add up: the lines sum to the subtotal of ₹10,000 before tax; "
        "subtotal ₹10,000 + tax ₹1,800 = ₹11,800 including tax, as printed."),
        "The invoice date 10 Nov 2026 is valid and not in the future.",
        "All amounts are positive and in INR.",
        "GSTIN 06AAACA0001A1Z1 has the standard 15-character form.",
        "The amount before tax is the printed subtotal, ₹10,000.",
        ("Vendor confirmed as Acme Packaging Pvt Ltd (V-1) by tax ID: the GSTIN 06AAACA0001A1Z1 "
        "on the invoice matches the vendor master."),
        ("Purchase order confirmed as PO-100: it is quoted on the invoice ('PO-100') and belongs "
        "to Acme Packaging Pvt Ltd."),
        "Every invoice line corresponds to a line on PO-100 (1 line).",
        ("No duplicate found: no earlier invoice is the same file or has the same vendor and "
        "invoice number."),
        ("No likely duplicate found: no earlier invoice from this vendor has the same total "
        "(₹11,800 including tax) together with the same date or a nearly identical number."),
        "PO-100 is open.",
        ("Fits the purchase order balance: this invoice is ₹10,000 before tax and PO-100 has "
        "₹1,00,000 remaining. With this invoice, PO-100 would have ₹10,000 of ₹1,00,000 billed "
        "before tax, ₹90,000 remaining."),
        "Unit prices are within 2% of the purchase order price on every matched line (1 line).",
    ]


def test_vendor_confirmed_by_name_is_worded_as_such_in_what_passed():
    decision = run(make_record(vendor_name="ACME PACKAGING PRIVATE LIMITED",
                               vendor_tax_id=None)).decision
    assert ("Vendor confirmed as Acme Packaging Pvt Ltd (V-1) by name: 'ACME PACKAGING PRIVATE "
            "LIMITED' is the same name once company suffixes such as Pvt Ltd are set aside."
            ) in decision.passed


def test_an_approval_that_uses_up_the_po_says_it_is_fully_billed():
    books = make_books(purchase_orders=[make_po(value="10000")])
    assert run(books=books).decision.next_action == (
        "Schedule payment of ₹11,800 including tax. PO-100 is now fully billed: ₹10,000 of "
        "₹10,000 before tax.")


def test_an_approval_within_tolerance_says_how_far_over_the_po_now_is():
    books = make_books(purchase_orders=[make_po(value="100000", billed="91000")])
    assert run(books=books).decision.next_action == (
        "Schedule payment of ₹11,800 including tax. PO-100 now has ₹1,01,000 billed against a "
        "value of ₹1,00,000 before tax, ₹1,000 over.")


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
