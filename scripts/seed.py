"""Reset the database to the seed state from the command line.  Run with: make seed"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlmodel import Session, select

from app.db import create_tables, engine
from app.models import Invoice, PurchaseOrder, Vendor
from app.money import format_inr
from app.seed import reset_demo

create_tables()
with Session(engine) as session:
    reset_demo(session)

    print(f"Database: {engine.url}")
    print(f"Vendors: {len(session.exec(select(Vendor)).all())}")
    print("Purchase orders (value / billed / remaining):")
    for po in session.exec(select(PurchaseOrder).order_by(PurchaseOrder.id)).all():
        print(f"  {po.id}  {po.vendor_id}  {format_inr(po.value):>10} / "
              f"{format_inr(po.billed_to_date):>10} / {format_inr(po.remaining):>10}")
    print("Seeded history:")
    for invoice in session.exec(select(Invoice)).all():
        print(f"  {invoice.invoice_number}  {invoice.vendor_id}  {invoice.po_id}  "
              f"{invoice.invoice_date}  {format_inr(invoice.gross_amount)}  {invoice.state}")
