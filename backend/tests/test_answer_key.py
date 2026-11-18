"""The acceptance test (SPEC section 8, item 2): all 13 cases and the 3 sequences must reach
the decision, match type and finding codes in data/invoices/expected.json."""

from decimal import Decimal

import pytest

from tests.answer_key import CASES, SEQUENCES, flagged_codes, fresh_books, run_case


@pytest.mark.parametrize("file_name", list(CASES))
def test_case_matches_the_answer_key(session, file_name):
    expected = CASES[file_name]["expected"]
    books = fresh_books(session)

    result = run_case(books, file_name)

    assert result.decision.decision == expected["decision"]
    assert result.decision.owner == expected["owner"]
    assert result.matched.vendor_id == expected["vendor_id"]
    assert result.matched.vendor_match == expected["vendor_match"]
    assert result.matched.po_id == expected["po_id"]
    assert result.matched.po_match_type == expected["po_match_type"]
    assert result.validated.pretax_amount == Decimal(expected["pretax_amount"])

    flagged = flagged_codes(result)
    assert set(expected["finding_codes"]) <= flagged
    assert not set(expected["absent_codes"]) & flagged

    if "po_overage" in expected:
        assert result.ruled.po_overage == Decimal(expected["po_overage"])
    if "duplicate_of" in expected:
        assert [d.invoice_number for d in result.ruled.duplicates] == [expected["duplicate_of"]]
    if "po_billed_after" in expected:
        po = next(p for p in books.purchase_orders if p.id == expected["po_id"])
        assert po.billed_to_date == Decimal(expected["po_billed_after"])


@pytest.mark.parametrize("sequence", SEQUENCES, ids=lambda s: s["name"])
def test_sequence_matches_the_answer_key(session, sequence):
    """Several invoices in a row with no reset in between; the last one is checked."""
    expected = sequence["expected_last"]
    books = fresh_books(session)

    for file_name in sequence["steps"]:
        result = run_case(books, file_name)

    assert result.decision.decision == expected["decision"]
    assert set(expected["finding_codes"]) <= flagged_codes(result)
    if "owner" in expected:
        assert result.decision.owner == expected["owner"]
    if "po_overage" in expected:
        assert result.ruled.po_overage == Decimal(expected["po_overage"])

