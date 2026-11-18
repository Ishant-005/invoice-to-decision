"""Read-only views of "the spreadsheet" and the settings: samples, purchase orders, vendors,
dashboard numbers and the rules in force."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app import config
from app.api.runs import run_state, vendor_names_by_id
from app.api.schemas import (
    InvoiceDetail,
    POInvoiceOut,
    POLineOut,
    PurchaseOrderOut,
    RulesOut,
    Stats,
    VendorOut,
)
from app.db import get_session
from app.models import Invoice, POLine, PurchaseOrder, Run, SavedExtraction, Vendor
from app.pipeline.receive import ensure_page_images
from app.pipeline.runner import upload_path
from app.rules_config import default_rules
from app.samples import Sample, load_samples, sample_path

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/samples")
def list_samples() -> list[Sample]:
    """The 13 sample invoices: what each document is, not what should happen to it."""
    return load_samples()


@router.get("/samples/{file_name}/preview.png")
def get_sample_preview(file_name: str) -> FileResponse:
    """The first page of a sample invoice as an image, for the gallery."""
    path = sample_path(file_name)
    if path is None:
        raise HTTPException(404, f"There is no sample called '{file_name}'.")
    file_hash, _ = ensure_page_images(path)
    return FileResponse(config.PAGES_DIR / file_hash / "1.png", media_type="image/png")


# --- Invoice history ---------------------------------------------------------------------


def invoice_pdf_path(invoice: Invoice):
    """Where the PDF of an invoice in the history is kept: the seed folder for seeded
    history, otherwise the stored upload of the run that produced it."""
    if invoice.is_seeded:
        return config.SEED_DIR / invoice.file_name
    return upload_path(invoice.run_id)


def get_invoice_or_404(session: Session, invoice_id: int) -> Invoice:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, "There is no invoice with that ID.")
    return invoice


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, session: SessionDep) -> InvoiceDetail:
    """One invoice from the history (seeded or from a run) with the stored reading of its
    PDF and its page images. Shown beside a suspected duplicate."""
    invoice = get_invoice_or_404(session, invoice_id)
    pdf_path = invoice_pdf_path(invoice)
    page_count = ensure_page_images(pdf_path)[1] if pdf_path.is_file() else 0
    saved = session.get(SavedExtraction, invoice.file_hash)
    return InvoiceDetail(
        id=invoice.id, invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date, pretax_amount=invoice.pretax_amount,
        gross_amount=invoice.gross_amount, state=invoice.state, is_seeded=invoice.is_seeded,
        run_id=invoice.run_id, file_name=invoice.file_name, vendor_id=invoice.vendor_id,
        vendor_name=(vendor_names_by_id(session).get(invoice.vendor_id)
                     or invoice.vendor_name_printed),
        po_id=invoice.po_id,
        pages=[f"/api/invoices/{invoice.id}/pages/{n}.png" for n in range(1, page_count + 1)],
        record=saved.record if saved else None)


@router.get("/invoices/{invoice_id}/pages/{page_number}.png")
def get_invoice_page(invoice_id: int, page_number: int, session: SessionDep) -> FileResponse:
    invoice = get_invoice_or_404(session, invoice_id)
    # page_number is a whole number (FastAPI checks), so this path cannot leave the folder.
    path = config.PAGES_DIR / invoice.file_hash / f"{page_number}.png"
    if not path.is_file():
        raise HTTPException(404, "There is no such page image.")
    return FileResponse(path, media_type="image/png")


def purchase_order_out(session: Session, po: PurchaseOrder,
                       vendor_names: dict[str, str]) -> PurchaseOrderOut:
    lines = session.exec(select(POLine).where(POLine.po_id == po.id).order_by(POLine.line_no))
    invoices = session.exec(select(Invoice).where(Invoice.po_id == po.id).order_by(Invoice.id))
    return PurchaseOrderOut(
        id=po.id, vendor_id=po.vendor_id, vendor_name=vendor_names.get(po.vendor_id, ""),
        po_date=po.po_date, status=po.status, value=po.value,
        billed_to_date=po.billed_to_date, remaining=po.remaining,
        lines=[POLineOut(line_no=line.line_no, description=line.description,
                         quantity=line.quantity, unit_price=line.unit_price,
                         amount=line.amount) for line in lines],
        invoices=[POInvoiceOut(invoice_number=inv.invoice_number, invoice_date=inv.invoice_date,
                               pretax_amount=inv.pretax_amount, gross_amount=inv.gross_amount,
                               state=inv.state, is_seeded=inv.is_seeded, run_id=inv.run_id,
                               file_name=inv.file_name) for inv in invoices])


@router.get("/purchase-orders")
def list_purchase_orders(session: SessionDep) -> list[PurchaseOrderOut]:
    """Every purchase order with its value, billed-to-date, remaining balance, lines and
    the invoices recorded against it (including ones awaiting review or rejected)."""
    names = vendor_names_by_id(session)
    return [purchase_order_out(session, po, names)
            for po in session.exec(select(PurchaseOrder).order_by(PurchaseOrder.id))]


@router.get("/purchase-orders/{po_id}")
def get_purchase_order(po_id: str, session: SessionDep) -> PurchaseOrderOut:
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, f"There is no purchase order {po_id}.")
    return purchase_order_out(session, po, vendor_names_by_id(session))


@router.get("/vendors")
def list_vendors(session: SessionDep) -> list[VendorOut]:
    orders = session.exec(select(PurchaseOrder).order_by(PurchaseOrder.id)).all()
    return [VendorOut(id=v.id, name=v.name, tax_id=v.tax_id, status=v.status, city=v.city,
                      state=v.state,
                      purchase_order_ids=[po.id for po in orders if po.vendor_id == v.id])
            for v in session.exec(select(Vendor).order_by(Vendor.id))]


@router.get("/stats")
def get_stats(session: SessionDep) -> Stats:
    """The dashboard's summary tiles. Counted from the runs made in the app; the seeded
    history is reported separately and is not part of any other number."""
    states = [run_state(run) for run in session.exec(select(Run))]
    count = states.count
    processed = len(states) - count("processing") - count("failed")

    approved = [inv for inv in session.exec(select(Invoice))
                if inv.state == "approved" and not inv.is_seeded]
    # An invoice approved by a reviewer may have no readable total; it is counted in the
    # pre-tax figure and left out of the gross one.
    pretax = sum((inv.pretax_amount for inv in approved if inv.pretax_amount is not None),
                 Decimal(0))
    gross = sum((inv.gross_amount for inv in approved if inv.gross_amount is not None),
                Decimal(0))
    seeded = len(session.exec(select(Invoice).where(Invoice.is_seeded)).all())

    return Stats(
        total_runs=len(states), processed=processed,
        approved=count("approved") + count("approved_by_reviewer"),
        auto_approved=count("approved"),
        auto_approved_percent=round(100 * count("approved") / processed, 1) if processed else None,
        approved_by_reviewer=count("approved_by_reviewer"),
        awaiting_review=count("awaiting_review"),
        rejected=count("rejected") + count("rejected_by_reviewer"),
        rejected_by_process=count("rejected"),
        rejected_by_reviewer=count("rejected_by_reviewer"), failed=count("failed"),
        in_progress=count("processing"), value_approved_pretax=pretax,
        value_approved_gross=gross, seeded_invoices=seeded)


@router.get("/config/rules")
def get_rules() -> RulesOut:
    """The thresholds in config/rules.yaml, exactly as the stages use them."""
    rules = default_rules()
    return RulesOut(validation=rules.validate_.model_dump(mode="json"),
                    match=rules.match.model_dump(mode="json"),
                    rules=rules.rules.model_dump(mode="json"))
