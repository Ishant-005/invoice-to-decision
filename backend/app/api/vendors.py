"""Add a vendor by hand. Plain code only: no AI model is involved.

This stands in for the company's vendor onboarding process, which in real life involves
more than a form. The checks live in `check_new_vendor`; the browser asks for them while the
person types (POST /api/vendors/check) and they are made again on save.
"""

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from rapidfuzz import fuzz
from sqlmodel import Session, select

from app import db
from app.api.schemas import VendorOut
from app.db import get_session
from app.models import Vendor
from app.pipeline.match import clean_vendor_name
from app.pipeline.validate import GSTIN_PATTERN
from app.rules_config import default_rules

log = logging.getLogger("invoice.api")
router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


class NewVendor(BaseModel):
    name: str = ""
    gstin: str = ""  # optional
    # Ticked by the person after being warned that the name looks like an existing vendor.
    confirm_similar: bool = False


class SimilarVendor(BaseModel):
    id: str
    name: str
    score: int  # how alike the two cleaned names are, out of 100


class VendorCheck(BaseModel):
    """What the form shows while the person types."""

    vendor_id: str  # the ID the new vendor would get
    errors: dict[str, str]  # {field: plain message}; empty if nothing is wrong
    similar: SimilarVendor | None  # a look-alike existing vendor that must be confirmed


def clean_gstin(gstin: str) -> str:
    return gstin.replace(" ", "").upper()


def next_vendor_id(vendors: list[Vendor]) -> str:
    """One more than the highest V-number: V-005 -> 'V-006'."""
    numbers = [int(found.group(1)) for vendor in vendors
               if (found := re.fullmatch(r"V-(\d+)", vendor.id))]
    return f"V-{max(numbers, default=0) + 1:03d}"


def check_new_vendor(session: Session, new: NewVendor) -> VendorCheck:
    vendors = list(session.exec(select(Vendor).order_by(Vendor.id)))
    rules = default_rules().match
    errors: dict[str, str] = {}
    similar: SimilarVendor | None = None

    def clean(name: str) -> str:
        # The same cleaning the Match stage uses: "Acme Packaging Pvt. Ltd." -> "acme packaging".
        return clean_vendor_name(name, rules.vendor_name_suffixes)

    name, cleaned = new.name.strip(), clean(new.name)
    if not name:
        errors["name"] = "Enter the vendor's name."
    elif len(name) > 120:
        errors["name"] = "Keep the name under 120 characters."
    elif not cleaned:
        errors["name"] = "Enter a name that is more than a company suffix such as Pvt Ltd."
    else:
        same = next((v for v in vendors if clean(v.name) == cleaned), None)
        if same:
            errors["name"] = f"{same.name} ({same.id}) already has this name."
        else:
            # A look-alike name is a fraud pattern, so it is never accepted silently. The
            # score and the threshold are the ones the Match stage uses for invoices.
            scored = [(fuzz.ratio(cleaned, clean(v.name)), v) for v in vendors]
            score, best = max(scored, key=lambda pair: pair[0], default=(0, None))
            if best is not None and score >= rules.vendor_fuzzy_min_score:
                similar = SimilarVendor(id=best.id, name=best.name, score=round(score))

    gstin = clean_gstin(new.gstin)
    if gstin:
        if not GSTIN_PATTERN.match(gstin):
            errors["gstin"] = ("A GSTIN has 15 characters in the standard form, such as "
                               "06AAACA0001A1Z1. Leave it empty if you do not have it.")
        else:
            holder = next((v for v in vendors if clean_gstin(v.tax_id) == gstin), None)
            if holder:
                errors["gstin"] = f"This GSTIN is already used by {holder.name} ({holder.id})."

    return VendorCheck(vendor_id=next_vendor_id(vendors), errors=errors, similar=similar)


@router.post("/vendors/check")
def check_vendor(new: NewVendor, session: SessionDep) -> VendorCheck:
    """Check a new vendor without saving it."""
    return check_new_vendor(session, new)


@router.post("/vendors", status_code=201, response_model=VendorOut)
def add_vendor(new: NewVendor, session: SessionDep):
    """Add a vendor. It is active and gets the next free V-number. "Reset demo data" removes
    it again (the reset restores the seed vendors)."""
    with db.STATE_LOCK:  # so two requests cannot both take the same vendor ID
        check = check_new_vendor(session, new)
        if check.errors:
            return JSONResponse(status_code=422, content={
                "detail": "Some fields need attention.", **check.model_dump()})
        if check.similar and not new.confirm_similar:
            return JSONResponse(status_code=409, content={
                "detail": f"The name looks like {check.similar.name} ({check.similar.id}). "
                          "Confirm that this is a different vendor.", **check.model_dump()})
        # City and state are not asked for; nothing in the process uses them.
        vendor = Vendor(id=check.vendor_id, name=" ".join(new.name.split()),
                        tax_id=clean_gstin(new.gstin), status="active", city="", state="")
        session.add(vendor)
        session.commit()
    log.info("vendor added: %s name=%r similar_to=%s", vendor.id, vendor.name,
             check.similar.id if check.similar else None)
    return VendorOut(id=vendor.id, name=vendor.name, tax_id=vendor.tax_id, status=vendor.status,
                     city=vendor.city, state=vendor.state, purchase_order_ids=[])
