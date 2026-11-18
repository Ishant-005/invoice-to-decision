"""Seed data loads exactly as SPEC section 4 describes, and reset restores it."""

from decimal import Decimal

from sqlmodel import select

from app.models import Invoice, POLine, PurchaseOrder, Run, SavedExtraction, StageEvent, Vendor
from app.seed import reset_demo, seed_database, seed_if_empty

# SPEC 4.2: PO -> (vendor, value, billed at seed)
SPEC_POS = {
    "PO-2219": ("V-001", "200000", "100000"),
    "PO-2231": ("V-001", "180000", "0"),
    "PO-2240": ("V-002", "100000", "0"),
    "PO-2252": ("V-003", "72800", "0"),
    "PO-2260": ("V-005", "300000", "100000"),
    "PO-2275": ("V-004", "150000", "0"),
    "PO-2281": ("V-004", "150000", "0"),
    "PO-2290": ("V-003", "195000", "0"),
    "PO-2296": ("V-004", "220000", "0"),
    "PO-2301": ("V-002", "80000", "0"),
}


def all_rows(session, table):
    return session.exec(select(table)).all()


def test_seed_loads_vendors_and_purchase_orders_from_the_spec(session):
    seed_database(session)

    vendors = {v.id: v.name for v in all_rows(session, Vendor)}
    assert vendors == {
        "V-001": "Acme Packaging Pvt Ltd",
        "V-002": "Brightline Logistics LLP",
        "V-003": "Sharma Office Supplies",
        "V-004": "Corelight Electricals Pvt Ltd",
        "V-005": "Zenith Facility Services Pvt Ltd",
    }

    pos = {po.id: po for po in all_rows(session, PurchaseOrder)}
    assert set(pos) == set(SPEC_POS)
    for po_id, (vendor_id, value, billed) in SPEC_POS.items():
        assert pos[po_id].vendor_id == vendor_id
        assert pos[po_id].value == Decimal(value)
        assert pos[po_id].billed_to_date == Decimal(billed)
        assert pos[po_id].status == "open"


def test_money_comes_back_from_the_database_as_exact_decimal(session):
    seed_database(session)
    po = session.get(PurchaseOrder, "PO-2252")
    assert isinstance(po.value, Decimal)
    assert str(po.value) == "72800.00"
    assert po.remaining == Decimal("72800.00")


def test_po_lines_add_up_to_each_po_value(session):
    seed_database(session)
    lines = all_rows(session, POLine)
    assert len(lines) == 12
    for po in all_rows(session, PurchaseOrder):
        own = [line for line in lines if line.po_id == po.id]
        assert all(line.quantity * line.unit_price == line.amount for line in own)
        assert sum(line.amount for line in own) == po.value


def test_po_dates_fall_in_the_window_the_spec_gives(session):
    seed_database(session)
    for po in all_rows(session, PurchaseOrder):
        assert "2026-08-01" <= po.po_date.isoformat() <= "2026-10-15"


def test_seeded_history_matches_the_billed_amounts(session):
    seed_database(session)
    invoices = {i.invoice_number: i for i in all_rows(session, Invoice)}
    assert set(invoices) == {"INV-1017", "ZFS-0911"}

    inv = invoices["INV-1017"]
    assert (inv.vendor_id, inv.po_id, inv.invoice_date.isoformat()) == ("V-001", "PO-2219", "2026-10-03")
    zfs = invoices["ZFS-0911"]
    assert (zfs.vendor_id, zfs.po_id, zfs.invoice_date.isoformat()) == ("V-005", "PO-2260", "2026-09-30")

    for invoice in invoices.values():
        assert invoice.pretax_amount == Decimal(100000)
        assert invoice.gross_amount == Decimal(118000)
        assert invoice.state == "approved" and invoice.is_seeded
        assert len(invoice.file_hash) == 64
        # A PO's billed-to-date is exactly what its seeded invoices add up to.
        assert session.get(PurchaseOrder, invoice.po_id).billed_to_date == invoice.pretax_amount
        # Its reading is stored, so nothing needs the AI model.
        saved = session.get(SavedExtraction, invoice.file_hash)
        assert saved.source == "seed_file"
        assert saved.record["invoice_number"] == invoice.invoice_number


def test_seed_if_empty_seeds_once_only(session):
    assert seed_if_empty(session) is True
    assert seed_if_empty(session) is False
    assert len(all_rows(session, Vendor)) == 5


def test_reset_undoes_changes_wipes_runs_and_keeps_saved_extractions(session):
    seed_database(session)

    # Simulate a demo: a run approved an invoice and moved a PO balance.
    run = Run(file_name="acme_2026-11-05.pdf", file_hash="a" * 64, status="completed", decision="APPROVE")
    session.add(run)
    session.commit()
    session.add(StageEvent(run_id=run.id, stage="receive", status="done", duration_ms=3))
    session.add(Invoice(vendor_id="V-001", po_id="PO-2231", invoice_number="INV-1042",
                        pretax_amount=Decimal(180000), gross_amount=Decimal(212400),
                        state="approved", run_id=run.id, file_name=run.file_name,
                        file_hash=run.file_hash))
    session.add(SavedExtraction(file_hash="a" * 64, file_name=run.file_name,
                                record={"invoice_number": "INV-1042"}, source="live"))
    po = session.get(PurchaseOrder, "PO-2231")
    po.billed_to_date = Decimal(180000)
    session.get(Vendor, "V-003").status = "blocked"
    session.commit()

    reset_demo(session)
    session.expire_all()

    assert all_rows(session, Run) == []
    assert all_rows(session, StageEvent) == []
    assert {i.invoice_number for i in all_rows(session, Invoice)} == {"INV-1017", "ZFS-0911"}
    assert session.get(PurchaseOrder, "PO-2231").billed_to_date == Decimal(0)
    assert session.get(Vendor, "V-003").status == "active"
    assert len(all_rows(session, PurchaseOrder)) == 10
    assert len(all_rows(session, POLine)) == 12
    # The live extraction survives; the two seeded ones are still there, not duplicated.
    assert session.get(SavedExtraction, "a" * 64) is not None
    assert len(all_rows(session, SavedExtraction)) == 3
