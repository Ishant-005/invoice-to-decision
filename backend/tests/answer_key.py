"""Helpers for running the answer key (data/invoices/expected.json) through the decision logic.

No AI model is involved: each case's ground-truth extraction ("truth") is fed straight into
Validate -> Match -> Rules -> Decide.
"""

import json
from datetime import date

from sqlmodel import Session

from app import config
from app.models import Invoice
from app.pipeline.assess import Assessment, assess
from app.pipeline.record import Books, InvoiceRecord, load_books
from app.seed import seed_database, sha256_of

ANSWER_KEY = json.loads((config.INVOICE_DIR / "expected.json").read_text(encoding="utf-8"))
CASES = {case["file"]: case for case in ANSWER_KEY["invoices"]}
SEQUENCES = ANSWER_KEY["sequences"]
TODAY = date(2026, 11, 18)  # fixed, so the tests give the same result on any day

STATE_AFTER = {"APPROVE": "approved", "REVIEW": "awaiting_review", "REJECT": "rejected"}


def fresh_books(session: Session) -> Books:
    """The books as they are straight after a reset."""
    seed_database(session)
    return load_books(session)


def run_case(books: Books, file_name: str) -> Assessment:
    """Assess one sample invoice, then record the outcome in the books the way the running
    app will (Milestone 4 does this in the database): an approval adds to the PO's
    billed-to-date, and the invoice joins the history used for duplicate checks."""
    record = InvoiceRecord.model_validate(CASES[file_name]["truth"])
    file_hash = sha256_of(config.INVOICE_DIR / file_name)
    result = assess(record, books, file_hash, TODAY)

    if result.decision.decision == "APPROVE":
        po = next(p for p in books.purchase_orders if p.id == result.matched.po_id)
        po.billed_to_date += result.validated.pretax_amount
    books.invoices.append(Invoice(
        vendor_id=result.matched.vendor_id, po_id=result.matched.po_id,
        invoice_number=record.invoice_number, invoice_date=result.validated.invoice_date,
        pretax_amount=result.validated.pretax_amount,
        gross_amount=result.validated.gross_amount,
        state=STATE_AFTER[result.decision.decision], file_name=file_name, file_hash=file_hash))
    return result


def flagged_codes(result: Assessment) -> set[str]:
    """Codes of the findings that came out as a warning or a failure."""
    return {f.code for f in result.findings if f.status in ("warn", "fail")}
