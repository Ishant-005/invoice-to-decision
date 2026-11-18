"""Stage 5, Rules: duplicates, purchase order balance and status, unit prices."""

from datetime import date
from decimal import Decimal

import pytest

from app.pipeline.rules import (
    is_number_extension,
    normalise_invoice_number,
    overage_limit,
    po_position,
)
from app.rules_config import default_rules
from tests.unit.builders import (
    FILE_HASH,
    earlier_invoice,
    finding,
    make_books,
    make_line,
    make_po,
    make_record,
    run,
)

# The standard test invoice is ₹10,000 before tax (₹11,800 gross), dated 2026-11-10.


def invoice_of(pretax: str):
    """A bundled invoice (no lines) for the given pre-tax amount, with 18% GST."""
    tax = Decimal(pretax) * Decimal("0.18")
    return make_record(line_items=[], subtotal=pretax, tax_amount=str(tax),
                       total=str(Decimal(pretax) + tax))


# --- PO balance and the tolerance boundaries (2% of PO value AND ₹5,000) -------------------


@pytest.mark.parametrize(("po_value", "billed", "pretax", "status", "severity", "overage"), [
    # PO of ₹1,00,000: 2% is ₹2,000, so the percentage is the limit that bites.
    ("100000", "0", "100000", "pass", "info", "0"),              # exactly uses the PO up
    ("100000", "90000", "10000.01", "warn", "info", "0.01"),      # a paisa over
    ("100000", "90000", "12000", "warn", "info", "2000"),         # exactly 2%: allowed
    ("100000", "90000", "12000.01", "fail", "review", "2000.01"),  # just over 2%
    # PO of ₹3,00,000: 2% would be ₹6,000, so the ₹5,000 cap is the limit that bites.
    ("300000", "290000", "15000", "warn", "info", "5000"),        # exactly ₹5,000: allowed
    ("300000", "290000", "15000.01", "fail", "review", "5000.01"),  # just over ₹5,000
    ("300000", "290000", "15900", "fail", "review", "5900"),      # under 2% but over ₹5,000
])
def test_po_balance_tolerance(po_value, billed, pretax, status, severity, overage):
    books = make_books(purchase_orders=[make_po(value=po_value, billed=billed)])
    result = run(invoice_of(pretax), books)
    found = finding(result, "PO_BALANCE")
    assert (found.status, found.severity) == (status, severity)
    assert result.ruled.po_overage == Decimal(overage)


def test_po_balance_beyond_tolerance_is_owned_by_procurement():
    books = make_books(purchase_orders=[make_po(value="100000", billed="95000")])
    result = run(books=books)
    found = finding(result, "PO_BALANCE")
    assert found.owner == "procurement"
    # The limit is one figure: the lower of 2% of ₹1,00,000 (₹2,000) and ₹5,000.
    assert found.message == (
        "This invoice is ₹10,000 before tax, but PO-100 has only ₹5,000 remaining of its "
        "₹1,00,000 value before tax, so the invoice takes it ₹5,000 over. The most this "
        "purchase order may be exceeded by is ₹2,000.")
    assert result.decision.decision == "REVIEW"
    assert result.decision.headline == ("Needs review: the invoice takes PO-100 over its value "
                                        "by ₹5,000 before tax.")


@pytest.mark.parametrize(("po_value", "limit"), [
    ("100000", "2000"),     # 2% is the lower limit
    ("250000", "5000"),     # 2% is exactly ₹5,000
    ("300000", "5000"),     # ₹5,000 is the lower limit
    ("72800", "1456"),      # 2% of an uneven value
])
def test_overage_limit_is_the_lower_of_the_two_limits(po_value, limit):
    assert overage_limit(Decimal(po_value), default_rules().rules) == Decimal(limit)


def test_overage_within_tolerance_message_states_the_single_limit():
    books = make_books(purchase_orders=[make_po(value="100000", billed="91000")])
    found = finding(run(books=books), "PO_BALANCE")
    assert found.message == (
        "This invoice is ₹10,000 before tax, but PO-100 has only ₹9,000 remaining of its "
        "₹1,00,000 value before tax, so the invoice takes it ₹1,000 over. That is within the "
        "₹2,000 by which this purchase order may be exceeded.")


def test_po_balance_pass_message_gives_the_po_position():
    found = finding(run(), "PO_BALANCE")
    assert found.message == (
        "Fits the purchase order balance: this invoice is ₹10,000 before tax and PO-100 has "
        "₹1,00,000 remaining. With this invoice, PO-100 would have ₹10,000 of ₹1,00,000 billed "
        "before tax, ₹90,000 remaining.")


@pytest.mark.parametrize(("billed", "now", "expected"), [
    ("180000", True, "PO-1 is now fully billed: ₹1,80,000 of ₹1,80,000 before tax"),
    ("100000", True, "PO-1 now has ₹1,00,000 of ₹1,80,000 billed before tax, ₹80,000 remaining"),
    ("181200", True, ("PO-1 now has ₹1,81,200 billed against a value of ₹1,80,000 before tax, "
                     "₹1,200 over")),
    ("180000", False, "PO-1 would be fully billed: ₹1,80,000 of ₹1,80,000 before tax"),
    ("100000", False, ("PO-1 would have ₹1,00,000 of ₹1,80,000 billed before tax, ₹80,000 "
                      "remaining")),
])
def test_po_position(billed, now, expected):
    assert po_position("PO-1", Decimal(180000), Decimal(billed), now=now) == expected


# --- An overage together with lines that are not on the purchase order -----------------------


def with_extra_line(extra_amount: str):
    """10 widgets (₹10,000, on the PO) plus one 'Site survey' line that is not on the PO."""
    subtotal = Decimal(10000) + Decimal(extra_amount)
    lines = [{"description": "Steel widget", "quantity": "10", "unit_price": "1000",
              "amount": "10000"},
             {"description": "Site survey", "quantity": "1", "unit_price": extra_amount,
              "amount": extra_amount}]
    return make_record(line_items=lines, subtotal=str(subtotal),
                       tax_amount=str(subtotal * Decimal("0.18")),
                       total=str(subtotal * Decimal("1.18")))


def test_overage_caused_by_an_unlisted_line_says_the_invoice_would_fit_without_it():
    # ₹12,000 is left on the PO. The widgets (₹10,000) fit; the ₹8,000 survey does not.
    books = make_books(purchase_orders=[make_po(value="100000", billed="88000")])
    result = run(with_extra_line("8000"), books)
    found = finding(result, "PO_BALANCE")
    assert found.status == "fail"
    assert found.data["fits_without_unlisted_lines"] is True
    assert found.message == (
        "This invoice is ₹18,000 before tax, but PO-100 has only ₹12,000 remaining of its "
        "₹1,00,000 value before tax, so the invoice takes it ₹6,000 over. The most this "
        "purchase order may be exceeded by is ₹2,000. Without 'Site survey' (₹8,000 before "
        "tax), which is not on PO-100, the invoice would be ₹10,000 before tax and would fit.")
    assert result.decision.headline == ("Needs review: the invoice takes PO-100 over its value "
                                        "by ₹6,000 before tax.")


def test_overage_that_remains_without_the_unlisted_line_does_not_say_it_would_fit():
    # Only ₹4,000 is left on the PO, so even the widgets alone (₹10,000) do not fit.
    books = make_books(purchase_orders=[make_po(value="100000", billed="96000")])
    found = finding(run(with_extra_line("8000"), books), "PO_BALANCE")
    assert found.status == "fail"
    assert found.data["fits_without_unlisted_lines"] is False
    assert "Without" not in found.message
    assert "would fit" not in found.message
    assert found.message == (
        "This invoice is ₹18,000 before tax, but PO-100 has only ₹4,000 remaining of its "
        "₹1,00,000 value before tax, so the invoice takes it ₹14,000 over. The most this "
        "purchase order may be exceeded by is ₹2,000.")


def test_two_unlisted_lines_are_both_named():
    lines = [{"description": "Steel widget", "amount": "10000"},
             {"description": "Site survey", "amount": "3000"},
             {"description": "Courier", "amount": "500"}]
    record = make_record(line_items=lines, subtotal="13500", tax_amount="2430", total="15930")
    books = make_books(purchase_orders=[make_po(value="100000", billed="90000")])
    found = finding(run(record, books), "PO_BALANCE")
    assert found.message.endswith(
        "Without 'Site survey' (₹3,000 before tax) and 'Courier' (₹500 before tax), which are "
        "not on PO-100, the invoice would be ₹10,000 before tax and would fit.")


def test_an_overage_with_every_line_on_the_po_has_no_without_sentence():
    books = make_books(purchase_orders=[make_po(value="100000", billed="95000")])
    found = finding(run(books=books), "PO_BALANCE")
    assert "fits_without_unlisted_lines" not in found.data
    assert "Without" not in found.message


def test_overage_within_tolerance_still_approves():
    books = make_books(purchase_orders=[make_po(value="100000", billed="91000")])
    result = run(books=books)
    assert result.ruled.po_overage == Decimal(1000)
    assert result.decision.decision == "APPROVE"


def test_balance_uses_the_pretax_amount_not_the_gross_total():
    # ₹10,000 pre-tax fits exactly; the ₹11,800 gross would not.
    books = make_books(purchase_orders=[make_po(value="10000")])
    assert finding(run(books=books), "PO_BALANCE").status == "pass"


def test_a_closed_po_needs_review():
    books = make_books(purchase_orders=[make_po(status="closed")])
    found = finding(run(books=books), "PO_STATUS")
    assert (found.status, found.severity) == ("fail", "review")


# --- Unit price variance (±2%) --------------------------------------------------------------


def priced_at(unit_price: str):
    amount = Decimal(unit_price) * 10
    return make_record(
        line_items=[{"description": "Steel widget", "quantity": "10", "unit_price": unit_price,
                     "amount": str(amount)}],
        subtotal=str(amount), tax_amount=str(amount * Decimal("0.18")),
        total=str(amount * Decimal("1.18")))


@pytest.mark.parametrize(("unit_price", "status"), [
    ("1000", "pass"),
    ("1020", "pass"),      # exactly +2%: allowed
    ("980", "pass"),       # exactly -2%: allowed
    ("1020.01", "fail"),
    ("979.99", "fail"),    # a price well below the PO is also worth a look
    ("1080", "fail"),
])
def test_price_variance_boundaries(unit_price, status):
    found = finding(run(priced_at(unit_price)), "PRICE_VARIANCE")
    assert found.status == status
    if status == "fail":
        assert (found.severity, found.owner) == ("review", "procurement")


def test_price_variance_message_quotes_both_prices():
    found = finding(run(priced_at("1080")), "PRICE_VARIANCE")
    assert found.message == ("'Steel widget' is billed at ₹1,080 per unit before tax; the "
                             "purchase order price is ₹1,000 (8% above). The allowed "
                             "difference is 2%.")


def test_price_check_is_skipped_when_no_unit_price_is_printed():
    lines = [{"description": "Steel widget", "amount": "10000"}]
    assert finding(run(make_record(line_items=lines)), "PRICE_VARIANCE").status == "skipped"


# --- Duplicates -----------------------------------------------------------------------------


@pytest.mark.parametrize(("number", "normalised"), [
    ("INV-1017", "INV1017"), ("inv 1017", "INV1017"), ("INV/1017", "INV1017"),
    ("BL/26-27/0193", "BL26270193"),
])
def test_normalise_invoice_number(number, normalised):
    assert normalise_invoice_number(number) == normalised


@pytest.mark.parametrize(("a", "b", "expected"), [
    ("INV1017A", "INV1017", True),     # one extra character
    ("INV1017", "INV1017A", True),     # either way round
    ("INV1017AB", "INV1017", True),    # two extra: the limit
    ("INV1017ABC", "INV1017", False),  # three extra: too different
    ("INV1017", "INV1017", False),     # identical is an exact duplicate, not a variation
    ("ZFS0934", "ZFS0911", False),     # unrelated numbers
])
def test_is_number_extension(a, b, expected):
    assert is_number_extension(a, b, max_extra=2) is expected


def duplicates_against(earlier, **record_changes):
    return run(make_record(**record_changes), make_books(invoices=[earlier]))


def test_same_vendor_and_same_number_is_an_exact_duplicate_and_rejected():
    result = duplicates_against(earlier_invoice(number="inv 500"))  # this one is INV-500
    found = finding(result, "DUPLICATE_EXACT")
    assert (found.status, found.severity, found.owner) == ("fail", "reject", "ap")
    assert result.decision.decision == "REJECT"


def test_the_identical_file_is_an_exact_duplicate():
    result = duplicates_against(earlier_invoice(number="OTHER-1", total="999",
                                                file_hash=FILE_HASH))
    assert finding(result, "DUPLICATE_EXACT").status == "fail"


def test_same_number_from_a_different_vendor_is_not_a_duplicate():
    result = duplicates_against(earlier_invoice(number="INV-500", vendor_id="V-2"))
    assert finding(result, "DUPLICATE_EXACT").status == "pass"
    assert finding(result, "DUPLICATE_PROBABLE").status == "pass"


def test_same_total_and_same_date_is_a_probable_duplicate():
    result = duplicates_against(earlier_invoice(number="XYZ-9", invoice_date=date(2026, 11, 10)))
    found = finding(result, "DUPLICATE_PROBABLE")
    assert (found.status, found.severity, found.owner) == ("fail", "review", "ap")
    assert result.ruled.duplicates[0].kind == "probable"
    assert result.decision.decision == "REVIEW"
    assert found.data["amount_at_risk"] == "11800"
    assert found.message == (
        "This looks like the same bill as invoice XYZ-9 from Acme Packaging Pvt Ltd, which is "
        "already approved. Both have the same total (₹11,800 including tax) and the same "
        "invoice date (10 Nov 2026). If both are paid, ₹11,800 including tax would be paid "
        "twice.")


def test_same_total_and_a_lightly_altered_number_is_a_probable_duplicate():
    result = duplicates_against(earlier_invoice(number="INV-500"), invoice_number="INV-500-A")
    assert finding(result, "DUPLICATE_EXACT").status == "pass"
    assert finding(result, "DUPLICATE_PROBABLE").message == (
        "This looks like the same bill as invoice INV-500 from Acme Packaging Pvt Ltd, which is "
        "already approved. Both have the same total (₹11,800 including tax) and nearly the same "
        "invoice number ('INV-500-A' against 'INV-500'). If both are paid, ₹11,800 including "
        "tax would be paid twice.")


def test_probable_duplicate_of_an_invoice_awaiting_review_says_so():
    result = duplicates_against(earlier_invoice(number="INV-500", state="awaiting_review",
                                                invoice_date=date(2026, 11, 10)),
                                invoice_number="INV-500-A")
    assert finding(result, "DUPLICATE_PROBABLE").message == (
        "This looks like the same bill as invoice INV-500 from Acme Packaging Pvt Ltd, which is "
        "awaiting review. Both have the same total (₹11,800 including tax), the same invoice "
        "date (10 Nov 2026) and nearly the same invoice number ('INV-500-A' against 'INV-500'). "
        "If both are paid, ₹11,800 including tax would be paid twice.")


def test_monthly_invoice_same_amount_different_date_and_number_is_not_a_duplicate():
    """The deliberate design point: a monthly service bills the same amount every month."""
    result = duplicates_against(earlier_invoice(number="INV-400", invoice_date=date(2026, 10, 10)))
    assert finding(result, "DUPLICATE_EXACT").status == "pass"
    assert finding(result, "DUPLICATE_PROBABLE").status == "pass"
    assert result.decision.decision == "APPROVE"


def test_same_date_but_a_different_total_is_not_a_duplicate():
    result = duplicates_against(earlier_invoice(total="5900", invoice_date=date(2026, 11, 10)))
    assert finding(result, "DUPLICATE_PROBABLE").status == "pass"


@pytest.mark.parametrize("state", ["approved", "awaiting_review"])
def test_invoices_approved_or_awaiting_review_count_as_earlier(state):
    result = duplicates_against(earlier_invoice(number="INV-500", state=state))
    assert finding(result, "DUPLICATE_EXACT").status == "fail"


def test_a_rejected_earlier_invoice_is_ignored_so_a_corrected_copy_can_be_resubmitted():
    result = duplicates_against(earlier_invoice(number="INV-500", state="rejected",
                                                file_hash=FILE_HASH))
    assert finding(result, "DUPLICATE_EXACT").status == "pass"
    assert result.decision.decision == "APPROVE"


def test_no_invoice_number_makes_the_duplicate_check_partial():
    result = duplicates_against(earlier_invoice(), invoice_number=None)
    found = finding(result, "DUPLICATE_CHECK_PARTIAL")
    assert (found.status, found.severity) == ("warn", "info")


def test_no_invoice_number_still_catches_same_total_and_date():
    result = duplicates_against(earlier_invoice(invoice_date=date(2026, 11, 10)),
                                invoice_number=None)
    assert finding(result, "DUPLICATE_PROBABLE").status == "fail"


def test_rules_that_need_a_po_are_skipped_not_failed_when_there_is_none():
    result = run(make_record(po_reference="PO-9999"),
                 make_books(po_lines=[make_line()]))
    for code in ("PO_STATUS", "PO_BALANCE", "PRICE_VARIANCE"):
        assert finding(result, code).status == "skipped"
