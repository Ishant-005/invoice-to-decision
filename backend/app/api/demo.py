"""Demo controls. The process is stateful (PO balances change with every run), so a demo
needs a way back to the starting point."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app import config, db
from app.db import get_session
from app.models import Invoice, PurchaseOrder, Vendor
from app.seed import reset_demo

log = logging.getLogger("invoice.api")
router = APIRouter()


@router.post("/demo/reset")
def reset(session: Annotated[Session, Depends(get_session)]) -> dict[str, int | str]:
    """Wipe all runs and restore vendors, POs, balances and seeded history. Saved AI
    readings are kept. A run still in progress is abandoned: it notices its row is gone
    and stops without writing anything."""
    with db.STATE_LOCK:  # never in the middle of another run's decision
        reset_demo(session)
        # The stored PDFs belong to the runs that were just wiped.
        if config.UPLOADS_DIR.is_dir():
            for pdf in config.UPLOADS_DIR.glob("*.pdf"):
                pdf.unlink(missing_ok=True)
    log.info("demo reset: runs wiped, seed state restored")

    def count(table) -> int:
        return session.exec(select(func.count()).select_from(table)).one()

    return {"status": "reset", "vendors": count(Vendor), "purchase_orders": count(PurchaseOrder),
            "seeded_invoices": count(Invoice)}
