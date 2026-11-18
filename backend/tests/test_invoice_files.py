"""The committed PDFs and the answer key are complete and agree with each other.

These tests read the files in data/; they do not regenerate them and need no browser."""

import csv
import json
import re
from decimal import Decimal

import pypdfium2
import pytest

from app import config
from app.money import indian_number

ANSWER_KEY = json.loads((config.INVOICE_DIR / "expected.json").read_text(encoding="utf-8"))
CASES = ANSWER_KEY["invoices"]
# Standard GSTIN shape: 2-digit state, 10-character PAN, entity digit, 'Z', check character.
GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def page_text(path) -> str:
    return " ".join(pypdfium2.PdfDocument(path)[0].get_textpage().get_text_range().split())


def test_answer_key_covers_13_cases_and_3_sequences():
    assert [case["case"] for case in CASES] == list(range(1, 14))
    assert len(ANSWER_KEY["sequences"]) == 3
    on_disk = sorted(path.name for path in config.INVOICE_DIR.glob("*.pdf"))
    assert on_disk == sorted(case["file"] for case in CASES)
    files = {case["file"] for case in CASES}
    for sequence in ANSWER_KEY["sequences"]:
        assert set(sequence["steps"]) <= files


def test_expected_decisions_match_the_spec():
    decisions = {case["case"]: case["expected"]["decision"] for case in CASES}
    assert decisions == {1: "APPROVE", 2: "APPROVE", 3: "APPROVE", 4: "APPROVE", 5: "REVIEW",
                         6: "APPROVE", 7: "REVIEW", 8: "REVIEW", 9: "REVIEW", 10: "REVIEW",
                         11: "APPROVE", 12: "REVIEW", 13: "REJECT"}
    by_case = {case["case"]: case for case in CASES}
    assert by_case[9]["truth"]["po_reference"] is None
    assert by_case[9]["expected"]["po_match_type"] == "implied_single"
    assert by_case[10]["truth"]["invoice_number"] is None
    assert by_case[10]["truth"]["total"] is None


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["file"])
def test_ground_truth_arithmetic(case):
    truth = case["truth"]
    for item in truth["line_items"]:
        if item["quantity"] and item["unit_price"]:
            assert Decimal(item["quantity"]) * Decimal(item["unit_price"]) == Decimal(item["amount"])
    if truth["subtotal"]:
        subtotal, tax = Decimal(truth["subtotal"]), Decimal(truth["tax_amount"])
        assert sum(Decimal(item["amount"]) for item in truth["line_items"]) == subtotal
        assert subtotal * Decimal("0.18") == tax
        if truth["total"]:
            # Case 12 is the one deliberate error: its printed total is 1,000 too high.
            error = Decimal(1000) if case["case"] == 12 else Decimal(0)
            assert Decimal(truth["total"]) == subtotal + tax + error


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["file"])
def test_pdf_text_layer(case):
    text = page_text(config.INVOICE_DIR / case["file"])
    truth = case["truth"]
    if case["scanned"]:
        assert text == "", "a scan must have no extractable text"
    else:
        assert truth["invoice_number"] in text
        assert indian_number(Decimal(truth["total"])) in text


def test_scanned_cases_are_the_ones_the_spec_names():
    assert [case["case"] for case in CASES if case["scanned"]] == [3, 8, 10]


def test_four_layouts_are_used():
    assert {case["layout"] for case in CASES} == {"A", "B", "C", "D"}


def test_vendor_tax_ids_are_well_formed_and_agree_with_the_vendor_master():
    with (config.SEED_DIR / "vendors.csv").open(newline="", encoding="utf-8") as file:
        master = {row["vendor_id"]: row["gstin"] for row in csv.DictReader(file)}
    assert all(GSTIN.match(gstin) for gstin in master.values())
    assert len(set(master.values())) == 5

    for case in CASES:
        printed = case["truth"]["vendor_tax_id"]
        if printed is None:
            continue
        assert GSTIN.match(printed)
        vendor_id = case["expected"]["vendor_id"]
        if vendor_id:
            assert printed == master[vendor_id]
        else:
            assert printed not in master.values()  # the unknown vendor
