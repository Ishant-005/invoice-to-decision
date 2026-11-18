"""The shapes the API sends back.

Every response goes through one of these models rather than a hand-built dictionary. One
reason matters most: money. A `Decimal` in these models is sent as text ("180000.00"), so
an amount never becomes a floating-point number on its way to the browser.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


def as_utc(moment: datetime | None) -> datetime | None:
    """Times are stored in UTC, but SQLite hands them back without saying so. Marking
    them as UTC makes the JSON end in "Z", which a browser converts to local time."""
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


# --- Runs --------------------------------------------------------------------------------


class RunCreated(BaseModel):
    id: str
    status: str
    url: str  # where to poll


class Resolution(BaseModel):
    """A person's answer to a REVIEW run."""

    action: str  # approved | rejected
    comment: str
    resolved_at: datetime


class RunSummary(BaseModel):
    """One row of the dashboard's runs table."""

    id: str
    created_at: datetime
    finished_at: datetime | None
    file_name: str
    source: str  # upload | sample
    status: str  # queued | running | completed | failed   (how far the pipeline got)
    # What the run means for the business, in one word: processing | approved |
    # awaiting_review | approved_by_reviewer | rejected_by_reviewer | rejected | failed
    state: str
    decision: str | None  # APPROVE | REVIEW | REJECT, what the pipeline decided
    headline: str | None
    owner: str | None
    owner_label: str | None
    vendor_id: str | None
    vendor_name: str | None  # the vendor master's name, or the printed name if unmatched
    invoice_number: str | None
    invoice_date: date | None
    pretax_amount: Decimal | None
    gross_amount: Decimal | None
    po_id: str | None
    failed_stage: str | None
    error_message: str | None
    resolution: Resolution | None


class StageOut(BaseModel):
    stage: str  # receive | extract | validate | match | rules | decide
    uses_ai: bool
    status: str  # waiting | running | done | failed | not_run
    started_at: datetime | None
    duration_ms: float | None  # the measured time; null until the stage has finished
    result: dict[str, Any] | None
    findings: list[dict[str, Any]]


class RunDetail(RunSummary):
    """Everything the run view needs: the summary, the six stages, the decision."""

    file_hash: str
    pages: list[str]  # URLs of the page images, in page order
    stages: list[StageOut]  # always six, in pipeline order
    total_duration_ms: float | None  # the six stage durations added up
    decision_detail: dict[str, Any] | None  # headline, reasons, owner, next action, passed


class SeededInvoice(BaseModel):
    """An invoice approved before the demo starts. It has no run."""

    invoice_number: str | None
    vendor_id: str | None
    vendor_name: str | None
    po_id: str | None
    invoice_date: date | None
    pretax_amount: Decimal | None
    gross_amount: Decimal | None
    state: str
    file_name: str


class RunList(BaseModel):
    runs: list[RunSummary]  # newest first
    seeded_history: list[SeededInvoice]


class ResolveRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    comment: str = Field(min_length=1, max_length=2000)
    po_id: str | None = None  # approve only: book against this PO instead of the suggested one


# --- Reference data ----------------------------------------------------------------------


class POLineOut(BaseModel):
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class POInvoiceOut(BaseModel):
    invoice_number: str | None
    invoice_date: date | None
    pretax_amount: Decimal | None
    gross_amount: Decimal | None
    state: str  # approved | awaiting_review | rejected
    is_seeded: bool
    run_id: str | None
    file_name: str


class InvoiceDetail(POInvoiceOut):
    """One invoice from the history, with what was read from it and its page images. The
    run view uses this to show an earlier invoice beside a suspected duplicate."""

    id: int
    vendor_id: str | None
    vendor_name: str | None
    po_id: str | None
    pages: list[str]  # URLs of the page images, in page order
    record: dict[str, Any] | None  # the stored reading of the PDF, if there is one


class PurchaseOrderOut(BaseModel):
    id: str
    vendor_id: str
    vendor_name: str
    po_date: date
    status: str
    value: Decimal  # pre-tax
    billed_to_date: Decimal
    remaining: Decimal  # negative if a reviewer approved an invoice over the PO's value
    lines: list[POLineOut]
    invoices: list[POInvoiceOut]


class VendorOut(BaseModel):
    id: str
    name: str
    tax_id: str
    status: str
    city: str
    state: str
    purchase_order_ids: list[str]


class Stats(BaseModel):
    """Dashboard numbers. They count runs made in the app; seeded history is separate.

    The dashboard's filters go by where a run stands now, so the totals here are grouped the
    same way: `approved` and `rejected` each cover both the process and a reviewer."""

    total_runs: int  # every run, including failed ones and ones still in progress
    processed: int  # runs that reached a decision
    approved: int  # approved by the process or by a reviewer
    auto_approved: int  # approved by the process, with no person involved
    auto_approved_percent: float | None  # of processed; null when nothing is processed
    approved_by_reviewer: int
    awaiting_review: int
    rejected: int  # rejected by the process or by a reviewer
    rejected_by_process: int
    rejected_by_reviewer: int
    failed: int
    in_progress: int
    value_approved_pretax: Decimal  # approved by the process or by a reviewer
    value_approved_gross: Decimal
    seeded_invoices: int


class RulesOut(BaseModel):
    """config/rules.yaml, section by section, as currently in force."""

    validation: dict[str, Any] = Field(serialization_alias="validate")
    match: dict[str, Any]
    rules: dict[str, Any]
