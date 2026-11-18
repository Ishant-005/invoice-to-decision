"""The acceptance test (SPEC section 8, item 2): all 13 cases and the 3 sequences must reach
the decision, match type and finding codes in data/invoices/expected.json."""

import pytest

from tests.answer_key import CASES, SEQUENCES, differences, fresh_books, run_case


@pytest.mark.parametrize("file_name", list(CASES))
def test_case_matches_the_answer_key(session, file_name):
    books = fresh_books(session)
    result = run_case(books, file_name)
    assert differences(result, CASES[file_name]["expected"], books) == []


@pytest.mark.parametrize("sequence", SEQUENCES, ids=lambda s: s["name"])
def test_sequence_matches_the_answer_key(session, sequence):
    """Several invoices in a row with no reset in between; the last one is checked."""
    books = fresh_books(session)
    for file_name in sequence["steps"]:
        result = run_case(books, file_name)
    assert differences(result, sequence["expected_last"], books) == []


def test_differences_reports_a_wrong_decision_and_a_missing_finding(session):
    """Guards the comparison itself: it must not pass everything."""
    books = fresh_books(session)
    result = run_case(books, "acme_2026-11-05.pdf")
    wrong = {"decision": "REJECT", "finding_codes": ["TOTALS"], "absent_codes": []}
    assert differences(result, wrong, books) == [
        "decision: expected REJECT, got APPROVE", "finding TOTALS expected but not raised"]
