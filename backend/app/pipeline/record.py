"""The inputs the deterministic stages work on.

InvoiceRecord  what the Extract stage read from the PDF (SPEC section 3.3)
Books          a snapshot of "the spreadsheet": vendors, purchase orders and earlier invoices
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.models import Invoice, POLine, PurchaseOrder, Vendor


class LineItem(BaseModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


class InvoiceRecord(BaseModel):
    """Every field except document_type may be null: null means "not printed or unreadable"."""

    document_type: Literal["invoice", "credit_note", "quotation", "statement", "other"]
    vendor_name: str | None = None
    vendor_tax_id: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None  # ISO text; the Validate stage checks that it parses
    date_is_ambiguous: bool = False
    po_reference: str | None = None
    currency: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    tax_rate_percent: Decimal | None = None
    amounts_tax_inclusive: bool = False
    total: Decimal | None = None
    evidence: dict[str, str | None] | None = None
    notes: str | None = None


@dataclass
class Books:
    """Master data and invoice history at the moment a run starts. The stages only read it."""

    vendors: list[Vendor]
    purchase_orders: list[PurchaseOrder]
    po_lines: list[POLine]
    invoices: list[Invoice] = field(default_factory=list)

    def lines_of(self, po_id: str) -> list[POLine]:
        lines = [line for line in self.po_lines if line.po_id == po_id]
        return sorted(lines, key=lambda line: line.line_no)


def load_books(session: Session) -> Books:
    """Read the current vendors, purchase orders and invoice history from the database.

    This is the only place the deterministic stages' input meets the database; the stages
    themselves just receive the Books."""
    return Books(
        vendors=list(session.exec(select(Vendor).order_by(Vendor.id))),
        purchase_orders=list(session.exec(select(PurchaseOrder).order_by(PurchaseOrder.id))),
        po_lines=list(session.exec(select(POLine).order_by(POLine.po_id, POLine.line_no))),
        invoices=list(session.exec(select(Invoice).order_by(Invoice.id))),
    )
