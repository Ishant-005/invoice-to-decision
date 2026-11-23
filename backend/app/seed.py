"""Load the seed data into the database, and reset back to it.

"The spreadsheet" is three CSV files in data/seed plus seed_invoices.json (two invoices that
were approved before the demo starts). Seeding never calls the AI model.
"""

import csv
import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, delete, select

from app import config
from app.db import create_tables
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


def load_sample_extractions(session: Session, seed_dir: Path = config.SEED_DIR,
                            invoice_dir: Path = config.INVOICE_DIR) -> int:
    """Store the saved readings of the 13 sample invoices, for any sample that has none yet.
    Returns how many were added.

    These are real readings by the AI model, made earlier and kept in
    data/seed/sample_extractions.json. A fresh server has never read anything, so without
    them a sample could not be shown when the live AI call fails. A reading already in the
    database (for example a newer live one) is never overwritten."""
    saved = json.loads((seed_dir / "sample_extractions.json").read_text(encoding="utf-8"))
    added = 0
    for entry in saved["extractions"]:
        file_hash = sha256_of(invoice_dir / entry["file"])
        if session.get(SavedExtraction, file_hash) is None:
            session.add(SavedExtraction(
                file_hash=file_hash, file_name=entry["file"], record=entry["record"],
                source="live", created_at=datetime.fromisoformat(entry["read_at"]).replace(tzinfo=UTC)))
            added += 1
    session.commit()
    return added


def prepare_database(engine: Engine) -> bool:
    """Called on every startup. Whatever it finds, the app can run afterwards:
    - no database file, or an empty one: the tables are created and the seed data loaded;
    - a database with data in it: left exactly as it is.
    Either way the samples' saved readings are topped up. Returns True if it seeded."""
    create_tables(engine)
    with Session(engine) as session:
        seeded = seed_if_empty(session)
        load_sample_extractions(session)
    return seeded


def reset_demo(session: Session) -> None:
    """Wipe all runs and history, then restore vendors, POs, balances and seeded history.

    Saved extractions are deliberately kept: they are keyed by file hash and are still valid."""
    # Children before parents, so no row is ever left pointing at a deleted one.
    for table in (StageEvent, Invoice, Run, POLine, PurchaseOrder, Vendor):
        session.exec(delete(table))
    seed_database(session)
