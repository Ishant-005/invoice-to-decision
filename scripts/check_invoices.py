"""Check the generated invoices against the data they were made from.

Part 1 recomputes every line amount, subtotal, tax and total from scratch.
Part 2 opens every PDF and checks its text layer:
  - a digital PDF must contain every figure it is supposed to show;
  - a scanned PDF must contain no text at all (it is one picture), so the only way to read
    it is to look at it, which is exactly what the Extract stage has to do.

Run with:  make check-invoices
"""

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

import pypdfium2
import pypdfium2.raw as pdfium_c

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.money import indian_number

problems: list[str] = []


def check(condition: bool, message: str) -> str:
    if not condition:
        problems.append(message)
    return "ok" if condition else "WRONG"


def rupees(value: Decimal) -> str:
    return indian_number(value)


# ---------------------------------------------------------------- Part 1: arithmetic
print("PART 1: arithmetic, recomputed from scripts/invoice_definitions.json\n")
data = json.loads((REPO / "scripts" / "invoice_definitions.json").read_text(encoding="utf-8"))

for definition in data["invoices"]:
    truth, name = definition["truth"], definition["file"]
    printed_total = definition["print"].get("stained_total", truth["total"])
    notes = []

    for item in truth["line_items"]:
        if item["quantity"] and item["unit_price"]:
            expected = Decimal(item["quantity"]) * Decimal(item["unit_price"])
            notes.append(f"{item['quantity']} x {rupees(Decimal(item['unit_price']))} = "
                         f"{rupees(expected)} "
                         f"{check(expected == Decimal(item['amount']), f'{name}: line amount')}")

    if truth["amounts_tax_inclusive"]:
        total = Decimal(printed_total)
        pretax = total / (1 + Decimal(truth["tax_rate_percent"]) / 100)
        expected_pretax = Decimal(definition["expected"]["pretax_amount"])
        notes.append(f"inclusive total {rupees(total)} / 1.18 = {rupees(pretax)} "
                     f"{check(pretax == expected_pretax, f'{name}: pre-tax')}")
    else:
        subtotal, tax = Decimal(truth["subtotal"]), Decimal(truth["tax_amount"])
        line_sum = sum(Decimal(item["amount"]) for item in truth["line_items"])
        right_tax = subtotal * Decimal(truth["tax_rate_percent"]) / 100
        notes.append(f"lines sum to {rupees(line_sum)} "
                     f"{check(line_sum == subtotal, f'{name}: subtotal')}")
        notes.append(f"18% of {rupees(subtotal)} = {rupees(right_tax)} "
                     f"{check(right_tax == tax, f'{name}: tax')}")
        adds_up = subtotal + tax == Decimal(printed_total)
        if name == "12_brightline_bad_sum.pdf":
            # The one deliberate error in the set: the printed total must be wrong by 1,000.
            verdict = check(Decimal(printed_total) - (subtotal + tax) == 1000, f"{name}: bad sum")
            notes.append(f"{rupees(subtotal)} + {rupees(tax)} = {rupees(subtotal + tax)}, printed "
                         f"{rupees(Decimal(printed_total))} (deliberately wrong) {verdict}")
        else:
            notes.append(f"{rupees(subtotal)} + {rupees(tax)} = {rupees(subtotal + tax)} "
                         f"{check(adds_up, f'{name}: total')}")
    print(f"{name}\n    " + "\n    ".join(notes))

print("\nPurchase orders: lines must add up to the PO value")
with (REPO / "data/seed/po_lines.csv").open(newline="") as file:
    po_lines = list(csv.DictReader(file))
with (REPO / "data/seed/purchase_orders.csv").open(newline="") as file:
    for po in csv.DictReader(file):
        lines = [line for line in po_lines if line["po_id"] == po["po_id"]]
        for line in lines:
            check(Decimal(line["quantity"]) * Decimal(line["unit_price"]) == Decimal(line["amount"]),
                  f"{po['po_id']} line {line['line_no']}")
        total = sum(Decimal(line["amount"]) for line in lines)
        print(f"    {po['po_id']}  {rupees(total):>9}  "
              f"{check(total == Decimal(po['value']), po['po_id'] + ' value')}")


# ---------------------------------------------------------------- Part 2: the PDF files
def must_show(definition: dict) -> list[str]:
    """Every piece of text a digital PDF has to contain."""
    truth = definition["truth"]
    wanted = [truth["vendor_name"], truth["invoice_number"]]
    if truth["po_reference"]:
        wanted.append(truth["po_reference"])
    if truth["vendor_tax_id"]:
        wanted.append(truth["vendor_tax_id"])
    for key in ("subtotal", "tax_amount", "total"):
        if truth[key]:
            wanted.append(rupees(Decimal(truth[key])))
    for item in truth["line_items"]:
        wanted.append(item["description"])
        wanted += [rupees(Decimal(item[key])) for key in ("unit_price", "amount") if item[key]]
    return wanted


print("\nPART 2: what is inside each PDF file\n")
print(f"{'file':34} {'kind':8} {'pages':>5} {'text chars':>10} {'text objs':>9} {'images':>6}  result")
for definition in data["invoices"]:
    name = definition["file"]
    folder = "seed" if "seeded" in definition else "invoices"
    pdf = pypdfium2.PdfDocument(REPO / "data" / folder / name)
    page = pdf[0]
    text = page.get_textpage().get_text_range()
    kinds = [obj.type for obj in page.get_objects(max_depth=5)]
    text_objects = kinds.count(pdfium_c.FPDF_PAGEOBJ_TEXT)
    images = kinds.count(pdfium_c.FPDF_PAGEOBJ_IMAGE)

    if definition["print"].get("scan"):
        kind = "scan"
        fine = len(text.strip()) == 0 and text_objects == 0 and images == 1
        result = "no text layer, one image" if fine else "FAIL: has text"
        check(fine, f"{name}: scan has a text layer")
    else:
        kind = "digital"
        flat = " ".join(text.split())
        missing = [w for w in must_show(definition) if w.upper() not in flat.upper()]
        result = "all figures present" if not missing else f"FAIL: missing {missing}"
        check(not missing, f"{name}: missing {missing}")
    check(len(pdf) == 1, f"{name}: not one page")
    print(f"{name:34} {kind:8} {len(pdf):>5} {len(text.strip()):>10} {text_objects:>9} {images:>6}  {result}")

exact = "Total ₹1,18,000 inclusive of GST @ 18%"
text = pypdfium2.PdfDocument(REPO / "data/invoices/02_brightline_tax_inclusive.pdf")[0]
found = exact in " ".join(text.get_textpage().get_text_range().split())
print(f"\nCase 2 prints the exact phrase '{exact}': {check(found, 'case 2 phrase')}")

print(f"\n{'ALL CHECKS PASSED' if not problems else 'PROBLEMS: ' + '; '.join(problems)}")
sys.exit(1 if problems else 0)
