"""Demo controls. The process is stateful (PO balances change with every run), so a demo
needs a way back to the starting point."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app.db import get_session
from app.models import Invoice, PurchaseOrder, Vendor
from app.seed import reset_demo

router = APIRouter()


@router.post("/demo/reset")
def reset(session: Annotated[Session, Depends(get_session)]) -> dict[str, int | str]:
    reset_demo(session)

    def count(table) -> int:
        return session.exec(select(func.count()).select_from(table)).one()

    return {"status": "reset", "vendors": count(Vendor), "purchase_orders": count(PurchaseOrder),
            "seeded_invoices": count(Invoice)}
