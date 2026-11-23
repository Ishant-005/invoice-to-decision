"""Add a purchase order by hand. Plain code only: no AI model is involved.

The checks live in `check_new_po`, which returns one plain message per field that is wrong.
The browser makes the same checks while the person types; these are the ones that count.
"""

import logging
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app import clock, db
from app.api.reference import purchase_order_out
from app.api.runs import vendor_names_by_id
from app.api.schemas import PurchaseOrderOut
from app.db import get_session
from app.models import POLine, PurchaseOrder, Vendor
from app.pipeline.match import normalise_po_reference

log = logging.getLogger("invoice.api")
router = APIRouter()

# A quantity or price: digits, optionally a point and one or two more digits. Written as
# text so it becomes a Decimal directly and never passes through a float.
NUMBER = re.compile(r"\d{1,9}(\.\d{1,2})?")
MAX_LINES = 50


class NewPOLine(BaseModel):
    description: str = ""
    quantity: str = ""
    unit_price: str = ""


class NewPurchaseOrder(BaseModel):
    vendor_id: str = ""
    po_number: str = ""  # "PO-2310" or just "2310"
    po_date: str = ""  # YYYY-MM-DD
    lines: list[NewPOLine] = []


def positive_decimal(text: str) -> Decimal | None:
    """The number in `text` if it is a plain positive number, otherwise None."""
    text = text.strip()
    if not NUMBER.fullmatch(text):
        return None
    value = Decimal(text)
    return value if value > 0 else None


def line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Quantity times unit price, rounded to whole paise."""
    return (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def po_id_for(po_number: str) -> str | None:
    """'2310', 'po 2310' and 'PO-2310' all become 'PO-2310'. None if nothing usable is left."""
    key = normalise_po_reference(po_number)
    return f"PO-{key}" if 1 <= len(key) <= 12 else None


def check_new_po(session: Session, new: NewPurchaseOrder, today: date) -> dict[str, str]:
    """Every problem with a new purchase order, as {field: plain message}. Empty if none.
    Line fields are named like "lines.0.quantity" (the first line is 0)."""
    errors: dict[str, str] = {}

    if session.get(Vendor, new.vendor_id) is None:
        errors["vendor_id"] = "Choose a vendor from the list."

    po_id = po_id_for(new.po_number)
    if po_id is None:
        errors["po_number"] = "Enter a PO number of 1 to 12 letters or digits, such as PO-2310."
    else:
        # "PO-2310" and "2310" are the same number, exactly as the Match stage reads them.
        wanted = normalise_po_reference(po_id)
        taken = next((po.id for po in session.exec(select(PurchaseOrder))
                      if normalise_po_reference(po.id) == wanted), None)
        if taken:
            errors["po_number"] = f"{taken} already exists. Choose a different number."

    try:
        po_date = date.fromisoformat(new.po_date)
        if po_date > today:
            errors["po_date"] = "The PO date cannot be in the future."
    except ValueError:
        errors["po_date"] = "Enter the PO date."

    if not new.lines:
        errors["lines"] = "Add at least one line."
    elif len(new.lines) > MAX_LINES:
        errors["lines"] = f"A purchase order can have at most {MAX_LINES} lines."
    for index, line in enumerate(new.lines[:MAX_LINES]):
        if not line.description.strip():
            errors[f"lines.{index}.description"] = "Describe what is being ordered."
        elif len(line.description.strip()) > 200:
            errors[f"lines.{index}.description"] = "Keep the description under 200 characters."
        if positive_decimal(line.quantity) is None:
            errors[f"lines.{index}.quantity"] = (
                "Enter a quantity above zero, with at most 2 decimal places.")
        if positive_decimal(line.unit_price) is None:
            errors[f"lines.{index}.unit_price"] = (
                "Enter a price above zero, with at most 2 decimal places.")
    return errors


@router.post("/purchase-orders", status_code=201, response_model=PurchaseOrderOut)
def add_purchase_order(new: NewPurchaseOrder,
                       session: Annotated[Session, Depends(get_session)]):
    """Add a purchase order. It starts open with nothing billed, and its value is always the
    sum of its lines. "Reset demo data" removes it again (the reset restores the seed POs)."""
    with db.STATE_LOCK:  # so two requests cannot both take the same PO number
        errors = check_new_po(session, new, clock.today())
        if errors:
            return JSONResponse(status_code=422, content={
                "detail": "Some fields need attention.", "errors": errors})

        po_id = po_id_for(new.po_number)
        lines = []
        for number, line in enumerate(new.lines, start=1):
            quantity = Decimal(line.quantity.strip())
            unit_price = Decimal(line.unit_price.strip()).quantize(Decimal("0.01"))  # "1250" -> 1250.00
            lines.append(POLine(po_id=po_id, line_no=number, description=line.description.strip(),
                                quantity=quantity, unit_price=unit_price,
                                amount=line_amount(quantity, unit_price)))
        po = PurchaseOrder(id=po_id, vendor_id=new.vendor_id,
                           po_date=date.fromisoformat(new.po_date),
                           value=sum((line.amount for line in lines), Decimal("0.00")),
                           billed_to_date=Decimal("0.00"), status="open")
        session.add(po)
        session.add_all(lines)
        session.commit()
    log.info("purchase order added: %s vendor=%s value=%s", po.id, po.vendor_id, po.value)
    return purchase_order_out(session, po, vendor_names_by_id(session))
