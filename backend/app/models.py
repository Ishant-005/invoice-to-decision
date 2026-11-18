"""Database tables.

Master data (restored on every reset):  Vendor, PurchaseOrder, POLine
History (wiped on reset, then re-seeded): Invoice, Run, StageEvent
Kept across resets:                       SavedExtraction, LiveCallCount

Every money column uses DecimalText (see db.py), so amounts are exact.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.db import DecimalText


def now_utc() -> datetime:
    return datetime.now(UTC)


class Vendor(SQLModel, table=True):
    """A supplier the company has onboarded (vendors.csv)."""

    id: str = Field(primary_key=True)  # "V-001"
    name: str
    tax_id: str  # GSTIN
    status: str = "active"  # active | blocked
    city: str
    state: str


class PurchaseOrder(SQLModel, table=True):
    """What the company agreed to buy (purchase_orders.csv). Values are pre-tax."""

    id: str = Field(primary_key=True)  # "PO-2231"
    vendor_id: str = Field(foreign_key="vendor.id", index=True)
    po_date: date
    value: Decimal = Field(sa_type=DecimalText)
    billed_to_date: Decimal = Field(sa_type=DecimalText)  # grows as invoices are approved
    status: str = "open"  # open | closed

    @property
    def remaining(self) -> Decimal:
        return self.value - self.billed_to_date


class POLine(SQLModel, table=True):
    """One line of a purchase order (po_lines.csv)."""

    id: int | None = Field(default=None, primary_key=True)
    po_id: str = Field(foreign_key="purchaseorder.id", index=True)
    line_no: int
    description: str
    quantity: Decimal = Field(sa_type=DecimalText)
    unit_price: Decimal = Field(sa_type=DecimalText)
    amount: Decimal = Field(sa_type=DecimalText)


class Invoice(SQLModel, table=True):
    """The ledger of invoices the process has seen. Duplicate checks and "earlier invoices
    against this PO" read from here. Most fields can be empty because a damaged invoice may
    have no number or total."""

    id: int | None = Field(default=None, primary_key=True)
    vendor_id: str | None = Field(default=None, foreign_key="vendor.id", index=True)
    po_id: str | None = Field(default=None, foreign_key="purchaseorder.id", index=True)
    invoice_number: str | None = None
    invoice_date: date | None = None
    pretax_amount: Decimal | None = Field(default=None, sa_type=DecimalText)
    gross_amount: Decimal | None = Field(default=None, sa_type=DecimalText)
    state: str  # approved | awaiting_review | rejected
    is_seeded: bool = False  # True for the "seeded history" invoices
    run_id: str | None = Field(default=None, foreign_key="run.id")
    file_name: str
    file_hash: str = Field(index=True)  # SHA-256 of the PDF


class Run(SQLModel, table=True):
    """One trip of one PDF through the pipeline. Filled in by later milestones."""

    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    created_at: datetime = Field(default_factory=now_utc)
    file_name: str
    file_hash: str = Field(index=True)
    status: str = "queued"  # queued | running | completed | failed
    failed_stage: str | None = None
    error_message: str | None = None
    decision: str | None = None  # APPROVE | REVIEW | REJECT
    decision_detail: dict | None = Field(default=None, sa_column=Column(JSON))
    resolution: str | None = None  # a person's approve / reject of a REVIEW run
    resolution_comment: str | None = None
    resolved_at: datetime | None = None


class StageEvent(SQLModel, table=True):
    """What one stage of one run did: status, real duration, result and findings."""

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="run.id", index=True)
    stage: str  # receive | extract | validate | match | rules | decide
    status: str  # running | done | failed
    started_at: datetime = Field(default_factory=now_utc)
    duration_ms: int | None = None
    result: dict | None = Field(default=None, sa_column=Column(JSON))


class SavedExtraction(SQLModel, table=True):
    """The structured record read from a PDF, keyed by the file's SHA-256. Survives a reset,
    so a file that has been read once can still be shown if the live AI call fails."""

    file_hash: str = Field(primary_key=True)
    file_name: str
    record: dict = Field(sa_column=Column(JSON))
    source: str  # "live" = read by the AI model; "seed_file" = loaded from data/seed
    created_at: datetime = Field(default_factory=now_utc)


class LiveCallCount(SQLModel, table=True):
    """How many live AI calls were made on one day (UTC). The Extract stage checks this
    against MAX_LIVE_EXTRACTIONS_PER_DAY so a public link cannot run up the API bill."""

    day: date = Field(primary_key=True)
    calls: int = 0
