"""Stage 3, Validate: the invoice checked against itself."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.pipeline.validate import validate
from app.rules_config import default_rules
from tests.unit.builders import TODAY, finding, make_record

RULES = default_rules().validate_


def check(**changes):
    return validate(make_record(**changes), TODAY, RULES)


def line(quantity="10", unit_price="1000", amount="10000"):
    return [{"description": "Steel widget", "quantity": quantity, "unit_price": unit_price,
             "amount": amount}]


def test_clean_invoice_passes_every_check():
    result = check()
    assert {f.status for f in result.findings} == {"pass"}
    assert result.pretax_amount == Decimal(10000)
    assert result.gross_amount == Decimal(11800)


def test_a_missing_po_reference_is_not_a_validation_problem():
    result = check(po_reference=None)
    assert {f.status for f in result.findings} == {"pass"}


# --- DOC_TYPE and REQUIRED_FIELDS ---------------------------------------------------------


def test_a_document_that_is_not_an_invoice_is_rejected():
    found = finding(check(document_type="quotation"), "DOC_TYPE")
    assert (found.status, found.severity) == ("fail", "reject")


def test_missing_required_fields_are_listed_for_the_vendor():
    found = finding(check(invoice_number=None, total=None), "REQUIRED_FIELDS")
    assert (found.status, found.severity, found.owner) == ("fail", "review", "vendor")
    assert found.data["missing"] == ["invoice number", "total"]


# --- Arithmetic, including rounding at ₹1 -------------------------------------------------


@pytest.mark.parametrize(("amount", "status"), [
    ("10000", "pass"),
    ("10001", "pass"),      # off by exactly ₹1: allowed
    ("9999", "pass"),
    ("10001.01", "fail"),   # just over ₹1
    ("9998.99", "fail"),
])
def test_line_arithmetic_allows_one_rupee_of_rounding(amount, status):
    # The subtotal is left out so only the line check is affected by the changed amount.
    result = check(line_items=line(amount=amount), subtotal=None)
    assert finding(result, "LINE_ARITHMETIC").status == status


@pytest.mark.parametrize(("total", "status"), [
    ("11800", "pass"),
    ("11801", "pass"),      # off by exactly ₹1: allowed
    ("11799", "pass"),
    ("11801.01", "fail"),
    ("12800", "fail"),
])
def test_subtotal_plus_tax_allows_one_rupee_of_rounding(total, status):
    assert finding(check(total=total), "TOTALS").status == status


def test_totals_failure_quotes_the_real_figures():
    found = finding(check(total="12800"), "TOTALS")
    assert (found.severity, found.owner) == ("review", "vendor")
    assert found.message == "Subtotal ₹10,000 + tax ₹1,800 = ₹11,800, but the invoice states ₹12,800."


def test_lines_must_add_up_to_the_subtotal():
    two_lines = line(amount="10000") + line(quantity="1", unit_price="500", amount="500")
    found = finding(check(line_items=two_lines), "TOTALS")
    assert found.status == "fail"
    assert "The lines add up to ₹10,500" in found.message


def test_bundled_invoice_with_no_lines_skips_the_line_checks():
    result = check(line_items=[])
    assert finding(result, "LINE_ARITHMETIC").status == "skipped"
    assert finding(result, "TOTALS").status == "pass"  # subtotal + tax = total still checked
    assert all(f.severity == "info" for f in result.findings)


# --- Tax normalisation --------------------------------------------------------------------


def test_pretax_is_derived_from_a_tax_inclusive_total():
    result = check(line_items=[], subtotal=None, tax_amount=None, total="118000",
                   amounts_tax_inclusive=True)
    assert result.pretax_amount == Decimal("100000.00")
    assert result.gross_amount == Decimal(118000)
    assert result.pretax_source == "derived_from_inclusive_total"
    assert finding(result, "TOTALS").status == "skipped"
    assert all(f.severity == "info" for f in result.findings)


def test_derived_pretax_is_rounded_to_the_paisa():
    result = check(line_items=[], subtotal=None, tax_amount=None, total="1000",
                   amounts_tax_inclusive=True)
    assert result.pretax_amount == Decimal("847.46")  # 1000 / 1.18 = 847.4576...


def test_pretax_is_total_minus_tax_when_no_subtotal_is_printed():
    result = check(line_items=[], subtotal=None)
    assert result.pretax_amount == Decimal(10000)
    assert result.pretax_source == "total_minus_tax"


def test_printed_subtotal_is_the_pretax_amount_even_when_the_total_is_unreadable():
    result = check(total=None)
    assert result.pretax_amount == Decimal(10000)
    assert result.gross_amount is None


def test_tax_unresolved_when_only_a_bare_total_is_printed():
    result = check(line_items=[], subtotal=None, tax_amount=None, tax_rate_percent=None)
    assert result.pretax_amount is None
    found = finding(result, "TAX_UNRESOLVED")
    assert (found.status, found.severity) == ("fail", "review")


def test_a_rate_alone_is_not_enough_unless_the_total_is_marked_tax_inclusive():
    result = check(line_items=[], subtotal=None, tax_amount=None, amounts_tax_inclusive=False)
    assert result.pretax_amount is None


# --- Dates ----------------------------------------------------------------------------------


def days_ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


@pytest.mark.parametrize(("invoice_date", "status", "severity"), [
    (days_ago(0), "pass", "info"),      # dated today
    (days_ago(-1), "fail", "review"),   # tomorrow
    (days_ago(180), "pass", "info"),    # exactly 180 days old
    (days_ago(181), "warn", "info"),    # older than 180 days: a note, still approvable
    ("2026-13-45", "fail", "review"),   # not a real date
])
def test_date_sanity(invoice_date, status, severity):
    found = finding(check(invoice_date=invoice_date), "DATE_SANITY")
    assert (found.status, found.severity) == (status, severity)


def test_an_ambiguous_date_needs_review():
    found = finding(check(date_is_ambiguous=True), "DATE_SANITY")
    assert (found.status, found.severity) == ("warn", "review")


def test_a_missing_date_is_reported_once_under_required_fields():
    result = check(invoice_date=None)
    assert finding(result, "DATE_SANITY").status == "skipped"
    assert finding(result, "REQUIRED_FIELDS").data["missing"] == ["invoice date"]


# --- Amounts, currency and tax ID ------------------------------------------------------------


def test_negative_amounts_need_review():
    found = finding(check(total="-11800"), "AMOUNT_SANITY")
    assert (found.status, found.severity) == ("fail", "review")


def test_a_foreign_currency_needs_review():
    found = finding(check(currency="USD"), "AMOUNT_SANITY")
    assert (found.status, found.severity) == ("fail", "review")
    assert "USD" in found.message


def test_no_printed_currency_is_only_a_note():
    found = finding(check(currency=None), "AMOUNT_SANITY")
    assert (found.status, found.severity) == ("warn", "info")


def test_a_malformed_gstin_is_only_a_warning():
    found = finding(check(vendor_tax_id="NOT-A-GSTIN"), "TAX_ID_FORMAT")
    assert (found.status, found.severity) == ("warn", "info")


def test_no_gstin_skips_the_format_check():
    assert finding(check(vendor_tax_id=None), "TAX_ID_FORMAT").status == "skipped"
