"""Small made-up data for the unit tests: one clean invoice and one tiny set of books.

Each test changes only the field it is about, so it is obvious what is being tested.
"""

from datetime import date
from decimal import Decimal

from app.models import Invoice, POLine, PurchaseOrder, Vendor
from app.pipeline.assess import Assessment, assess
from app.pipeline.record import Books, InvoiceRecord

TODAY = date(2026, 11, 18)
ACME_TAX_ID = "06AAACA0001A1Z1"
FILE_HASH = "hash-of-this-file"


def make_record(**changes) -> InvoiceRecord:
    """A clean invoice: 10 widgets at ₹1,000 = ₹10,000 + ₹1,800 GST = ₹11,800, on PO-100."""
    fields = {
        "document_type": "invoice",
        "vendor_name": "Acme Packaging Pvt Ltd",
        "vendor_tax_id": ACME_TAX_ID,
        "invoice_number": "INV-500",
        "invoice_date": "2026-11-10",
        "po_reference": "PO-100",
        "currency": "INR",
        "line_items": [{"description": "Steel widget", "quantity": "10", "unit_price": "1000",
                        "amount": "10000"}],
        "subtotal": "10000",
        "tax_amount": "1800",
        "tax_rate_percent": "18",
        "total": "11800",
    }
    fields.update(changes)
    return InvoiceRecord.model_validate(fields)


def make_po(po_id: str = "PO-100", vendor_id: str = "V-1", value: str = "100000",
            billed: str = "0", status: str = "open",
            po_date: date = date(2026, 10, 1)) -> PurchaseOrder:
    return PurchaseOrder(id=po_id, vendor_id=vendor_id, po_date=po_date, value=Decimal(value),
                         billed_to_date=Decimal(billed), status=status)


def make_line(po_id: str = "PO-100", description: str = "Steel widget",
              unit_price: str = "1000", quantity: str = "100", line_no: int = 1) -> POLine:
    return POLine(po_id=po_id, line_no=line_no, description=description,
                  quantity=Decimal(quantity), unit_price=Decimal(unit_price),
                  amount=Decimal(quantity) * Decimal(unit_price))


def make_books(purchase_orders=None, po_lines=None, invoices=None, vendors=None) -> Books:
    """Two vendors. By default one open purchase order, PO-100 for V-1, worth ₹1,00,000."""
    return Books(
        vendors=vendors or [
            Vendor(id="V-1", name="Acme Packaging Pvt Ltd", tax_id=ACME_TAX_ID, city="Gurugram",
                   state="Haryana"),
            Vendor(id="V-2", name="Brightline Logistics LLP", tax_id="07AAAFB0002B1ZP",
                   city="New Delhi", state="Delhi"),
        ],
        purchase_orders=[make_po()] if purchase_orders is None else purchase_orders,
        po_lines=[make_line()] if po_lines is None else po_lines,
        invoices=invoices or [],
    )


def earlier_invoice(number: str | None = "INV-400", total: str = "11800",
                    invoice_date: date = date(2026, 10, 10), state: str = "approved",
                    vendor_id: str = "V-1", file_hash: str = "another-file") -> Invoice:
    return Invoice(id=1, vendor_id=vendor_id, po_id="PO-100", invoice_number=number,
                   invoice_date=invoice_date, pretax_amount=Decimal(10000),
                   gross_amount=Decimal(total), state=state, file_name="earlier.pdf",
                   file_hash=file_hash)


def run(record: InvoiceRecord | None = None, books: Books | None = None,
        file_hash: str = FILE_HASH) -> Assessment:
    return assess(record or make_record(), books or make_books(), file_hash, TODAY)


def finding(result, code: str):
    """The one finding with this code (works on an Assessment or a single stage's result)."""
    matches = [f for f in result.findings if f.code == code]
    assert len(matches) == 1, f"expected exactly one {code} finding, got {len(matches)}"
    return matches[0]
