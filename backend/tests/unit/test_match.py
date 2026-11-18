"""Stage 4, Match: vendor, purchase order and lines."""

from datetime import date

import pytest

from app.models import Vendor
from app.pipeline.match import clean_vendor_name, normalise_po_reference
from app.rules_config import default_rules
from tests.unit.builders import (
    ACME_TAX_ID,
    finding,
    make_books,
    make_line,
    make_po,
    make_record,
    run,
)

SUFFIXES = default_rules().match.vendor_name_suffixes


# --- Text clean-up --------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "cleaned"), [
    ("Acme Packaging Pvt Ltd", "acme packaging"),
    ("ACME PACKAGING PRIVATE LIMITED", "acme packaging"),
    ("Acme Packaging Pvt. Ltd.", "acme packaging"),
    ("  acme   packaging  ", "acme packaging"),
    ("Brightline Logistics LLP", "brightline logistics"),
    ("Quickfix Hardware Co.", "quickfix hardware"),
    ("Sharma Office Supplies", "sharma office supplies"),
])
def test_clean_vendor_name(name, cleaned):
    assert clean_vendor_name(name, SUFFIXES) == cleaned


@pytest.mark.parametrize("printed", [
    "PO-2231", "P.O. #2231", "PO 2231", "2231", "po-2231", "PO2231", "PO No. 2231",
    "Purchase Order 2231",
])
def test_po_reference_styles_all_mean_the_same_po(printed):
    assert normalise_po_reference(printed) == "2231"


def test_different_po_numbers_stay_different():
    assert normalise_po_reference("PO-2231") != normalise_po_reference("PO-2232")


# --- Vendor ---------------------------------------------------------------------------------


def test_vendor_confirmed_by_tax_id_whatever_the_name_says():
    result = run(make_record(vendor_name="Some Other Trading Name")).matched
    assert (result.vendor_id, result.vendor_match) == ("V-1", "tax_id")


def test_vendor_confirmed_by_cleaned_name_when_no_tax_id_is_printed():
    result = run(make_record(vendor_name="ACME PACKAGING PRIVATE LIMITED", vendor_tax_id=None))
    assert (result.matched.vendor_id, result.matched.vendor_match) == ("V-1", "name")
    assert result.decision.decision == "APPROVE"


def test_name_match_with_a_different_tax_id_needs_review():
    result = run(make_record(vendor_tax_id="27AAACX9999X1Z5"))
    assert result.matched.vendor_match == "name"
    found = finding(result, "VENDOR_TAX_ID_CONFLICT")
    assert (found.severity, found.owner) == ("review", "ap")


def test_a_similar_name_is_only_suggested_and_never_approves():
    result = run(make_record(vendor_name="Acme Packagng Pvt Ltd", vendor_tax_id=None))
    assert (result.matched.vendor_id, result.matched.vendor_match) == ("V-1", "suggested")
    found = finding(result, "VENDOR_MATCH")
    assert (found.status, found.severity, found.owner) == ("warn", "review", "ap")
    assert result.decision.decision == "REVIEW"


def test_an_unknown_vendor_is_rejected_and_owned_by_procurement():
    result = run(make_record(vendor_name="Quickfix Hardware Co.", vendor_tax_id=None))
    assert (result.matched.vendor_id, result.matched.vendor_match) == (None, "none")
    found = finding(result, "VENDOR_NOT_FOUND")
    assert (found.severity, found.owner) == ("reject", "procurement")


def test_a_blocked_vendor_is_rejected():
    blocked = Vendor(id="V-1", name="Acme Packaging Pvt Ltd", tax_id=ACME_TAX_ID,
                     status="blocked", city="Gurugram", state="Haryana")
    result = run(books=make_books(vendors=[blocked]))
    assert finding(result, "VENDOR_BLOCKED").severity == "reject"
    assert result.decision.decision == "REJECT"


# --- Purchase order quoted on the invoice ---------------------------------------------------


def test_quoted_po_that_belongs_to_the_vendor_is_verified():
    result = run(make_record(po_reference="P.O. #100")).matched
    assert (result.po_id, result.po_match_type) == ("PO-100", "explicit_verified")
    assert result.po.remaining == 100000


def test_quoted_po_of_another_vendor_is_a_conflict_for_ap():
    books = make_books(purchase_orders=[make_po(vendor_id="V-2")])
    result = run(books=books)
    assert result.matched.po_match_type == "explicit_conflict"
    found = finding(result, "PO_VENDOR_CONFLICT")
    assert (found.severity, found.owner) == ("review", "ap")
    assert finding(result, "PO_BALANCE").status == "skipped"


def test_quoted_po_that_does_not_exist_goes_to_procurement():
    result = run(make_record(po_reference="PO-9999"))
    assert (result.matched.po_id, result.matched.po_match_type) == (None, "not_found")
    found = finding(result, "PO_NOT_FOUND")
    assert (found.severity, found.owner) == ("review", "procurement")


# --- No purchase order quoted: search -------------------------------------------------------


def test_one_strong_candidate_is_suggested_but_never_auto_approved():
    result = run(make_record(po_reference=None))
    assert (result.matched.po_id, result.matched.po_match_type) == ("PO-100", "implied_single")
    found = finding(result, "PO_IMPLIED")
    assert (found.severity, found.owner) == ("review", "ap")
    assert result.decision.decision == "REVIEW"
    # Everything else passed: the suggestion alone keeps it from approval.
    assert [f.code for f in result.findings if f.severity != "info"] == ["PO_IMPLIED"]


def test_implied_po_message_states_the_evidence_and_not_the_score():
    found = finding(run(make_record(po_reference=None)), "PO_IMPLIED")
    assert found.message == (
        "No purchase order is quoted on the invoice. PO-100 is the only open purchase order of "
        "Acme Packaging Pvt Ltd that fits: the invoice amount of ₹10,000 before tax fits its "
        "remaining balance of ₹1,00,000, 'Steel widget' matches its line 'Steel widget' and the "
        "invoice date (10 Nov 2026) is on or after the purchase order date (1 Oct 2026). "
        "A person must confirm it.")
    assert "score" not in found.message
    assert found.data["score"] == 100 and isinstance(found.data["score"], int)


def test_implied_po_score_in_the_data_is_rounded_to_a_whole_number():
    # 'Widgets in steel, large' is close to 'Steel widget' but not identical, so the raw
    # score has a fraction (88.2).
    lines = [{"description": "Widgets in steel, large", "quantity": "10", "unit_price": "1000",
              "amount": "10000"}]
    result = run(make_record(po_reference=None, line_items=lines))
    raw = result.matched.candidates[0].score
    found = finding(result, "PO_IMPLIED")
    assert raw == 88.2
    assert found.data["score"] == 88


def test_implied_po_evidence_says_what_does_not_fit_too():
    # The goods match and the date is fine, but the amount is more than the PO has left.
    books = make_books(purchase_orders=[make_po(value="100000", billed="95000")])
    result = run(make_record(po_reference=None), books)
    assert result.matched.candidates[0].evidence[0] == (
        "the invoice amount of ₹10,000 before tax is more than its remaining balance of ₹5,000")


def test_implied_po_headline_names_the_suggested_po():
    decision = run(make_record(po_reference=None)).decision
    assert decision.headline == ("Needs review: the invoice quotes no purchase order; PO-100 "
                                 "is suggested.")


def test_implied_score_is_amount_40_description_40_date_20():
    candidate = run(make_record(po_reference=None)).matched.candidates[0]
    assert (candidate.amount_fits, candidate.description_similarity, candidate.date_ok) == (
        True, 100.0, True)
    assert candidate.score == 100.0


def test_several_strong_candidates_give_a_shortlist():
    books = make_books(purchase_orders=[make_po("PO-100"), make_po("PO-101")],
                       po_lines=[make_line("PO-100"), make_line("PO-101")])
    result = run(make_record(po_reference=None), books)
    assert (result.matched.po_id, result.matched.po_match_type) == (None, "implied_multiple")
    found = finding(result, "PO_IMPLIED")
    assert found.data["shortlist"] == ["PO-100", "PO-101"]
    assert found.data["scores"] == {"PO-100": 100, "PO-101": 100}
    assert "score" not in found.message
    assert result.decision.headline == ("Needs review: the invoice quotes no purchase order; it "
                                        "could be any of PO-100, PO-101.")


def test_no_strong_candidate_goes_to_procurement():
    # Wrong goods, amount does not fit, and the PO is dated after the invoice.
    books = make_books(purchase_orders=[make_po(value="5000", po_date=date(2026, 11, 15))],
                       po_lines=[make_line(description="Printer toner")])
    result = run(make_record(po_reference=None), books)
    assert result.matched.po_match_type == "none"
    found = finding(result, "PO_NOT_IDENTIFIED")
    assert (found.severity, found.owner) == ("review", "procurement")


def test_closed_and_other_vendors_purchase_orders_are_not_searched():
    books = make_books(purchase_orders=[make_po("PO-100", status="closed"),
                                        make_po("PO-200", vendor_id="V-2")],
                       po_lines=[make_line("PO-100"), make_line("PO-200")])
    result = run(make_record(po_reference=None), books)
    assert result.matched.candidates == []
    assert result.matched.po_match_type == "none"


# --- Lines ----------------------------------------------------------------------------------


def test_a_line_that_is_not_on_the_po_is_a_warning_only():
    lines = [{"description": "Steel widget", "quantity": "10", "unit_price": "1000",
              "amount": "10000"},
             {"description": "Freight", "quantity": "1", "unit_price": "500", "amount": "500"}]
    result = run(make_record(line_items=lines, subtotal="10500", tax_amount="1890",
                             total="12390"))
    found = finding(result, "LINE_NOT_ON_PO")
    assert (found.status, found.severity) == ("warn", "info")
    assert found.data["lines"] == [2]
    assert found.message == "1 invoice line is not on PO-100: 'Freight' (₹500 before tax)."
    assert result.decision.decision == "APPROVE"


def test_bundled_invoice_skips_line_matching():
    result = run(make_record(line_items=[]))
    assert finding(result, "LINE_NOT_ON_PO").status == "skipped"
    assert result.decision.decision == "APPROVE"
