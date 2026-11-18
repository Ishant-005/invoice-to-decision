"""Load the seed data into the database, and reset back to it.

"The spreadsheet" is three CSV files in data/seed plus seed_invoices.json (two invoices that
were approved before the demo starts). Seeding never calls the AI model.
"""

import csv
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, delete, select

from app import config
from app.models import Invoice, POLine, PurchaseOrder, Run, SavedExtraction, StageEvent, Vendor


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_database(session: Session, seed_dir: Path = config.SEED_DIR) -> None:
    """Insert vendors, purchase orders, PO lines and the seeded invoice history."""
    for row in read_csv(seed_dir / "vendors.csv"):
        session.add(Vendor(id=row["vendor_id"], name=row["name"], tax_id=row["gstin"],
                           status=row["status"], city=row["city"], state=row["state"]))

    for row in read_csv(seed_dir / "purchase_orders.csv"):
        session.add(PurchaseOrder(id=row["po_id"], vendor_id=row["vendor_id"],
                                  po_date=date.fromisoformat(row["po_date"]),
                                  value=Decimal(row["value"]),
                                  billed_to_date=Decimal(row["billed_to_date"]),
                                  status=row["status"]))

    for row in read_csv(seed_dir / "po_lines.csv"):
        session.add(POLine(po_id=row["po_id"], line_no=int(row["line_no"]),
                           description=row["description"], quantity=Decimal(row["quantity"]),
                           unit_price=Decimal(row["unit_price"]), amount=Decimal(row["amount"])))

    history = json.loads((seed_dir / "seed_invoices.json").read_text(encoding="utf-8"))
    for entry in history["invoices"]:
        record = entry["extraction"]
        file_hash = sha256_of(seed_dir / entry["file"])
        session.add(Invoice(vendor_id=entry["vendor_id"], po_id=entry["po_id"],
                            invoice_number=record["invoice_number"],
                            invoice_date=date.fromisoformat(record["invoice_date"]),
                            pretax_amount=Decimal(record["subtotal"]),
                            gross_amount=Decimal(record["total"]),
                            state=entry["state"], is_seeded=True,
                            file_name=entry["file"], file_hash=file_hash))
        # merge = insert, or overwrite if a row with this hash survived an earlier reset.
        session.merge(SavedExtraction(file_hash=file_hash, file_name=entry["file"],
                                      record=record, source="seed_file"))

    session.commit()


def seed_if_empty(session: Session) -> bool:
    """Seed only when there are no vendors yet. Returns True if it seeded.

    Called on startup, so the app works on a host that wipes its disk on every restart."""
    if session.exec(select(Vendor)).first() is not None:
        return False
    seed_database(session)
    return True


def reset_demo(session: Session) -> None:
    """Wipe all runs and history, then restore vendors, POs, balances and seeded history.

    Saved extractions are deliberately kept: they are keyed by file hash and are still valid."""
    # Children before parents, so no row is ever left pointing at a deleted one.
    for table in (StageEvent, Invoice, Run, POLine, PurchaseOrder, Vendor):
        session.exec(delete(table))
    seed_database(session)
