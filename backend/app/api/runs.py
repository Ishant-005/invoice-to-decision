"""Runs: submit an invoice, watch it, list history, and resolve a review."""

import hashlib
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app import config, db
from app.api.schemas import (
    Resolution,
    ResolveRequest,
    RunCreated,
    RunDetail,
    RunList,
    RunSummary,
    SeededInvoice,
    StageOut,
    as_utc,
)
from app.db import get_session
from app.ledger import ReviewError, resolve_review
from app.models import Invoice, Run, StageEvent, Vendor
from app.pipeline.runner import STAGES, execute_run, upload_path
from app.samples import sample_path

log = logging.getLogger("invoice.api")
router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


# --- Submit ------------------------------------------------------------------------------


@router.post("/runs", status_code=202)
def create_run(
    background: BackgroundTasks,
    session: SessionDep,
    file: Annotated[UploadFile | None, File()] = None,
    sample: Annotated[str | None, Form()] = None,
) -> RunCreated:
    """Start a run from an uploaded PDF (`file`) or from one of the samples (`sample`, a
    file name from GET /api/samples). Answers at once with the run's ID; the pipeline
    runs in the background and GET /api/runs/{id} shows its progress."""
    if (file is None) == (sample is None):
        raise HTTPException(422, "Send either a PDF in 'file' or a sample name in 'sample'.")

    if sample is not None:
        path = sample_path(sample)
        if path is None:
            raise HTTPException(404, f"There is no sample called '{sample}'.")
        pdf_bytes, file_name, source = path.read_bytes(), sample, "sample"
    else:
        # Read one byte more than the limit: enough to know the file is too big without
        # holding all of an enormous upload in memory.
        pdf_bytes = file.file.read(config.MAX_UPLOAD_BYTES + 1)
        if len(pdf_bytes) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(
                413, f"The file is larger than the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} "
                     "MB limit.")
        # Keep only the last part of the name the browser sent, never a folder path.
        file_name = Path(file.filename or "").name[:200] or "upload.pdf"
        source = "upload"

    run = Run(file_name=file_name, file_hash=hashlib.sha256(pdf_bytes).hexdigest(),
              source=source)
    # The file is stored under the run's ID, never under a name the user chose.
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    upload_path(run.id).write_bytes(pdf_bytes)
    session.add(run)
    session.commit()
    log.info("run=%s status=queued source=%s file=%r bytes=%d", run.id, source, file_name,
             len(pdf_bytes))

    # Runs after this response has been sent, on the same database as this request.
    background.add_task(execute_run, run.id, session.get_bind())
    return RunCreated(id=run.id, status=run.status, url=f"/api/runs/{run.id}")


# --- Read --------------------------------------------------------------------------------


def run_state(run: Run) -> str:
    """One word for where a run stands, combining the pipeline's status, its decision and
    any human resolution."""
    if run.status in ("queued", "running"):
        return "processing"
    if run.status == "failed":
        return "failed"
    if run.decision == "APPROVE":
        return "approved"
    if run.decision == "REJECT":
        return "rejected"
    if run.resolution == "approved":
        return "approved_by_reviewer"
    if run.resolution == "rejected":
        return "rejected_by_reviewer"
    return "awaiting_review"


def summarise(run: Run, invoice: Invoice | None, vendor_names: dict[str, str]) -> RunSummary:
    detail = run.decision_detail or {}
    resolution = None
    if run.resolution is not None:
        resolution = Resolution(action=run.resolution, comment=run.resolution_comment or "",
                                resolved_at=as_utc(run.resolved_at))
    vendor_name = None
    if invoice is not None:
        vendor_name = vendor_names.get(invoice.vendor_id) or invoice.vendor_name_printed
    return RunSummary(
        id=run.id, created_at=as_utc(run.created_at), finished_at=as_utc(run.finished_at),
        file_name=run.file_name, source=run.source, status=run.status, state=run_state(run),
        decision=run.decision, headline=detail.get("headline"), owner=detail.get("owner"),
        owner_label=detail.get("owner_label"),
        vendor_id=invoice.vendor_id if invoice else None, vendor_name=vendor_name,
        invoice_number=invoice.invoice_number if invoice else None,
        invoice_date=invoice.invoice_date if invoice else None,
        pretax_amount=invoice.pretax_amount if invoice else None,
        gross_amount=invoice.gross_amount if invoice else None,
        po_id=invoice.po_id if invoice else None,
        failed_stage=run.failed_stage, error_message=run.error_message, resolution=resolution)


def vendor_names_by_id(session: Session) -> dict[str, str]:
    return {vendor.id: vendor.name for vendor in session.exec(select(Vendor))}


@router.get("/runs")
def list_runs(session: SessionDep, decision: str | None = None, status: str | None = None,
              state: str | None = None, vendor: str | None = None) -> RunList:
    """Every run, newest first. Optional filters: `decision` (APPROVE, REVIEW, REJECT),
    `status` (queued, running, completed, failed), `state` (for example awaiting_review:
    the review queue) and `vendor` (a vendor ID). The seeded history is listed separately
    because those invoices were never run through the app."""
    names = vendor_names_by_id(session)
    invoices = {inv.run_id: inv for inv in session.exec(select(Invoice)) if inv.run_id}
    rows = []
    for run in session.exec(select(Run).order_by(Run.created_at.desc())):
        row = summarise(run, invoices.get(run.id), names)
        if decision and row.decision != decision.upper():
            continue
        if status and row.status != status:
            continue
        if state and row.state != state:
            continue
        if vendor and row.vendor_id != vendor:
            continue
        rows.append(row)

    seeded = [SeededInvoice(invoice_number=inv.invoice_number, vendor_id=inv.vendor_id,
                            vendor_name=names.get(inv.vendor_id), po_id=inv.po_id,
                            invoice_date=inv.invoice_date, pretax_amount=inv.pretax_amount,
                            gross_amount=inv.gross_amount, state=inv.state,
                            file_name=inv.file_name)
              for inv in session.exec(select(Invoice).where(Invoice.is_seeded).order_by(Invoice.id))
              if not vendor or inv.vendor_id == vendor]
    return RunList(runs=rows, seeded_history=seeded)


def run_detail(session: Session, run: Run) -> RunDetail:
    events = {event.stage: event for event in session.exec(
        select(StageEvent).where(StageEvent.run_id == run.id).order_by(StageEvent.id))}
    finished = run.status in ("completed", "failed")

    stages = []
    for name in STAGES:
        event = events.get(name)
        if event is None:
            # Not reached yet, or never reached because an earlier stage failed.
            stages.append(StageOut(stage=name, uses_ai=name == "extract",
                                   status="not_run" if finished else "waiting",
                                   started_at=None, duration_ms=None, result=None, findings=[]))
        else:
            stages.append(StageOut(stage=name, uses_ai=name == "extract", status=event.status,
                                   started_at=as_utc(event.started_at),
                                   duration_ms=event.duration_ms, result=event.result,
                                   findings=event.findings or []))

    durations = [stage.duration_ms for stage in stages if stage.duration_ms is not None]
    receive_result = events["receive"].result if "receive" in events else None
    page_count = (receive_result or {}).get("page_count", 0)
    invoice = session.exec(select(Invoice).where(Invoice.run_id == run.id)).first()

    return RunDetail(
        **summarise(run, invoice, vendor_names_by_id(session)).model_dump(),
        file_hash=run.file_hash,
        pages=[f"/api/runs/{run.id}/pages/{number}.png" for number in range(1, page_count + 1)],
        stages=stages,
        total_duration_ms=round(sum(durations), 1) if durations else None,
        decision_detail=run.decision_detail)


def get_run_or_404(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "There is no run with that ID.")
    return run


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: SessionDep) -> RunDetail:
    """One run with its six stages. The browser polls this while the run is in progress."""
    return run_detail(session, get_run_or_404(session, run_id))


@router.get("/runs/{run_id}/pages/{page_number}.png")
def get_page_image(run_id: str, page_number: int, session: SessionDep) -> FileResponse:
    run = get_run_or_404(session, run_id)
    # page_number is a whole number (FastAPI checks), so this path cannot leave the folder.
    path = config.PAGES_DIR / run.file_hash / f"{page_number}.png"
    if not path.is_file():
        raise HTTPException(404, "There is no such page image.")
    return FileResponse(path, media_type="image/png")


# --- Human review ------------------------------------------------------------------------


@router.post("/runs/{run_id}/resolve")
def resolve_run(run_id: str, body: ResolveRequest, session: SessionDep) -> RunDetail:
    """A person approves or rejects a run that was sent for review. A comment is required.
    Approving adds the invoice's pre-tax amount to the purchase order's billed-to-date."""
    with db.STATE_LOCK:
        try:
            run = resolve_review(session, run_id, body.action, body.comment, body.po_id)
        except ReviewError as error:
            session.rollback()
            raise HTTPException(error.status_code, str(error)) from error
        session.commit()
    log.info("run=%s status=resolved resolution=%s", run.id, run.resolution)
    return run_detail(session, run)
