"""The only two places where the books change because of an invoice.

record_outcome()  called once at the end of a run: the invoice joins the history, and if
                  the decision is APPROVE its pre-tax amount is added to the PO's billed-to-date
resolve_review()  a person approves or rejects a run that was sent for review

Neither function commits. The caller commits, so the invoice row, the PO balance and the
run's own status all change together or not at all.
"""

from decimal import Decimal

from sqlmodel import Session, select

from app.models import Invoice, PurchaseOrder, Run, now_utc
from app.pipeline.decide import Decision
from app.pipeline.match import MatchResult
from app.pipeline.record import InvoiceRecord
from app.pipeline.validate import ValidateResult

# What an invoice's state becomes after each decision.
STATE_AFTER = {"APPROVE": "approved", "REVIEW": "awaiting_review", "REJECT": "rejected"}


def record_outcome(session: Session, run: Run, record: InvoiceRecord, validated: ValidateResult,
                   matched: MatchResult, decision: Decision) -> Invoice:
    """Add this run's invoice to the history. Only an APPROVE touches the PO balance; an
    invoice waiting for review or rejected leaves it alone (SPEC 3.7)."""
    invoice = Invoice(
        vendor_id=matched.vendor_id, po_id=matched.po_id,
        vendor_name_printed=record.vendor_name, invoice_number=record.invoice_number,
        invoice_date=validated.invoice_date, pretax_amount=validated.pretax_amount,
        gross_amount=validated.gross_amount, state=STATE_AFTER[decision.decision],
        run_id=run.id, file_name=run.file_name, file_hash=run.file_hash)
    session.add(invoice)
    if decision.decision == "APPROVE":
        add_to_billed(session, matched.po_id, validated.pretax_amount)
    return invoice


def add_to_billed(session: Session, po_id: str, pretax_amount: Decimal) -> PurchaseOrder:
    po = session.get(PurchaseOrder, po_id)
    po.billed_to_date = po.billed_to_date + pretax_amount
    session.add(po)
    return po


class ReviewError(Exception):
    """The review cannot be resolved as asked. `status_code` is the HTTP status to answer
    with; the message is written for the person doing the review."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def resolve_review(session: Session, run_id: str, action: str, comment: str,
                   po_id: str | None = None) -> Run:
    """A person's answer to a REVIEW run (SPEC 3.8): `approve` or `reject`, with a comment.

    Approving books the invoice's pre-tax amount against a purchase order: the one given
    in `po_id`, or else the one the pipeline matched or suggested. A person may approve an
    invoice that takes the PO over its value; deciding that is what the review is for."""
    run = session.get(Run, run_id)
    if run is None:
        raise ReviewError(404, "There is no run with that ID.")
    if run.status != "completed" or run.decision != "REVIEW":
        raise ReviewError(409, "Only a run that was sent for review can be resolved.")
    if run.resolution is not None:
        raise ReviewError(409, f"This run has already been resolved ({run.resolution}).")
    if not comment.strip():
        raise ReviewError(422, "A comment is required.")

    invoice = session.exec(select(Invoice).where(Invoice.run_id == run_id)).one()

    if action == "approve":
        if invoice.pretax_amount is None:
            raise ReviewError(409, "The invoice's pre-tax amount is not known, so it cannot be "
                                   "booked against a purchase order. Reject it and ask the "
                                   "vendor for a corrected invoice.")
        chosen_po_id = po_id or invoice.po_id
        if chosen_po_id is None:
            raise ReviewError(422, "No purchase order was matched for this invoice. Choose "
                                   "the purchase order to book it against.")
        po = session.get(PurchaseOrder, chosen_po_id)
        if po is None:
            raise ReviewError(422, f"There is no purchase order {chosen_po_id}.")
        if po.vendor_id != invoice.vendor_id:
            raise ReviewError(422, f"{po.id} belongs to a different vendor, so this invoice "
                                   "cannot be booked against it.")
        add_to_billed(session, po.id, invoice.pretax_amount)
        invoice.po_id = po.id
        invoice.state = "approved"
        run.resolution = "approved"
    else:
        invoice.state = "rejected"
        run.resolution = "rejected"

    run.resolution_comment = comment.strip()
    run.resolved_at = now_utc()
    session.add(invoice)
    session.add(run)
    return run
