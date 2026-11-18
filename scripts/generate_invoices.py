"""Generate the test invoice PDFs and the answer key.

Everything is driven by one data file, scripts/invoice_definitions.json. For each invoice in it:

  1. fill one of four HTML layouts (scripts/invoice_templates/layout_*.html) with the data,
  2. print it to PDF with a headless Chromium browser (Playwright),
  3. if it is marked as a scan: turn the page into a picture, skew it, blur it, add grain,
     and wrap the picture in a PDF that has no text layer at all.

It also writes the two JSON files that are derived from the same data:

  data/invoices/expected.json     the answer key for the 13 test invoices
  data/seed/seed_invoices.json    the 2 already-approved invoices loaded as history

Running it twice produces byte-identical files (fixed random seed, fixed PDF dates), so the
committed PDFs keep the same SHA-256 hash.

Run with:  make invoices
"""

import io
import json
import random
import re
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pypdfium2
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from playwright.sync_api import Page, sync_playwright

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.money import indian_number

DEFINITIONS = REPO / "scripts" / "invoice_definitions.json"
TEMPLATES = REPO / "scripts" / "invoice_templates"
INVOICE_DIR = REPO / "data" / "invoices"
SEED_DIR = REPO / "data" / "seed"

RANDOM_SEED = 2026
SCAN_DPI = 150
CSS_DPI = 96  # browsers measure in CSS pixels, 96 to the inch
FIXED_PDF_TIME = time.struct_time((2026, 11, 15, 10, 0, 0, 6, 319, 0))
INK = (24, 26, 44)  # colour of the ink blot on the damaged scan


# --------------------------------------------------------------------------------------
# Turning the data into the text printed on the page
# --------------------------------------------------------------------------------------

def ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        return f"{day}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def date_text(iso_date: str, layout: str) -> str:
    """Each layout prints dates differently. None of the formats is day/month ambiguous."""
    d = date.fromisoformat(iso_date)
    if layout == "A":
        return d.strftime("%d-%b-%Y")  # 05-Nov-2026
    if layout == "B":
        return f"{d.day} {d.strftime('%B %Y')}"  # 2 November 2026
    if layout == "C":
        return f"{ordinal(d.day)} {d.strftime('%B %Y')}"  # 28th October 2026
    return d.strftime("%d %b %Y")  # 06 Nov 2026


def money_text(value: str | None, layout: str) -> str:
    """Layouts A and D print paise (1,80,000.00); B and C print whole rupees (1,80,000)."""
    if value is None:
        return ""
    return indian_number(Decimal(value), decimals=2 if layout in ("A", "D") else 0)


def amount_in_words(amount: Decimal) -> str:
    """212400 -> 'Two Lakh Twelve Thousand Four Hundred'. Whole rupees only."""
    ones = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
            "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
            "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def below_hundred(n: int) -> str:
        if n < 20:
            return ones[n]
        return tens[n // 10] + ("" if n % 10 == 0 else " " + ones[n % 10])

    n = int(amount)
    parts = []
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand"), (100, "Hundred")):
        if n >= size:
            parts.append(f"{below_hundred(n // size)} {name}")
            n %= size
    if n or not parts:
        parts.append(below_hundred(n))
    return " ".join(parts)


def build_context(definition: dict, data: dict) -> dict:
    """Everything a layout template needs, already formatted as text."""
    truth = definition["truth"]
    options = definition["print"]
    letterhead = dict(data["letterheads"][definition["letterhead"]])
    layout = letterhead["layout"]
    letterhead["name"] = options.get("vendor_name", letterhead["name"])

    lines = []
    for index, item in enumerate(truth["line_items"]):
        lines.append({
            "n": index + 1,
            "description": item["description"],
            "quantity": item["quantity"] or "",
            "rate": money_text(item["unit_price"], layout),
            "amount": money_text(item["amount"], layout),
            "hsn": options.get("hsn", [""] * 9)[index],
            "unit": options.get("units", ["NOS"] * 9)[index],
        })

    # The damaged scan prints its real total; the ink blot hides it afterwards.
    printed_total = options.get("stained_total", truth["total"])
    tax = Decimal(truth["tax_amount"]) if truth["tax_amount"] else None
    rate = Decimal(truth["tax_rate_percent"])

    # Layout D ends with a tax summary per HSN code, as dense GST invoices do.
    hsn_summary = []
    if layout == "D":
        for item, line in zip(truth["line_items"], lines):
            taxable = Decimal(item["amount"])
            hsn_summary.append({
                "hsn": line["hsn"],
                "taxable": money_text(str(taxable), layout),
                "tax": money_text(str(taxable * rate / 100), layout),
            })

    return {
        "layout": layout,
        "lh": letterhead,
        "show_gstin": not options.get("hide_gstin", False),
        "buyer": data["buyer"],
        "invoice_number": truth["invoice_number"] or "",
        "date": date_text(truth["invoice_date"], layout),
        "po_reference": truth["po_reference"],
        "lines": lines,
        "inclusive": truth["amounts_tax_inclusive"],
        "subtotal": money_text(truth["subtotal"], layout),
        "tax": money_text(truth["tax_amount"], layout),
        # Layout A splits GST into two equal halves: CGST and SGST.
        "half_tax": money_text(str(tax / 2), layout) if tax else "",
        "rate": str(rate),
        "half_rate": str(rate / 2),
        "total": money_text(printed_total, layout),
        "total_in_words": amount_in_words(Decimal(printed_total)),
        "hsn_summary": hsn_summary,
    }


# --------------------------------------------------------------------------------------
# HTML -> PDF
# --------------------------------------------------------------------------------------

def html_to_pdf(page: Page, html: str) -> tuple[bytes, dict | None]:
    """Print the HTML to a one-page A4 PDF. Also returns where the total sits on the page
    (in CSS pixels), which the damaged scan needs so the ink blot lands on it."""
    page.set_content(html)
    page.emulate_media(media="print")
    page.evaluate("document.fonts.ready")
    total_box = page.locator("#total-value").bounding_box()
    pdf = page.pdf(format="A4", print_background=True,
                   margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
    return fix_pdf_dates(pdf), total_box


def fix_pdf_dates(pdf: bytes) -> bytes:
    """Chromium stamps the current time into the PDF, which would change the file's hash on
    every run. Overwrite it with a fixed time of exactly the same length."""
    def replace(match: re.Match) -> bytes:
        stamp = b"D:20261115100000+00'00'"
        return match.group(1) + stamp.ljust(len(match.group(2)))[: len(match.group(2))] + b")"

    return re.sub(rb"(/(?:CreationDate|ModDate) \()(D:[^)]*)\)", replace, pdf)


# --------------------------------------------------------------------------------------
# PDF -> "scan"
# --------------------------------------------------------------------------------------

def add_ink_blot(image: Image.Image, box: dict, rng: random.Random) -> None:
    """Cover the rectangle `box` (CSS pixels) with an opaque, irregular ink blot."""
    scale = SCAN_DPI / CSS_DPI
    left, top = box["x"] * scale, box["y"] * scale
    width, height = box["width"] * scale, box["height"] * scale
    centre_x, centre_y = left + width / 2, top + height / 2

    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)

    def blob(x: float, y: float, rx: float, ry: float) -> None:
        draw.ellipse((x - rx, y - ry, x + rx, y + ry), fill=255)

    # One wide, flat ellipse that fully contains the box, then lumps and droplets for a natural
    # edge. It is kept flat so the tax row printed just above the total stays readable.
    blob(centre_x, centre_y, width * 0.8, height * 1.0)
    for _ in range(9):
        blob(centre_x + rng.uniform(-0.7, 0.7) * width, centre_y + rng.uniform(-0.35, 0.35) * height,
             rng.uniform(0.2, 0.4) * width, rng.uniform(0.5, 0.8) * height)
    for _ in range(7):
        radius = rng.uniform(2, 8)
        blob(centre_x + rng.uniform(-1.5, 1.5) * width, centre_y + rng.uniform(-2.5, 2.5) * height,
             radius, radius)

    mask = mask.filter(ImageFilter.GaussianBlur(1.2))  # soften only the very edge
    image.paste(INK, mask=mask)

    # Proof, checked on every run: no pixel of the total is still visible.
    covered = image.crop((int(left), int(top), int(left + width) + 1, int(top + height) + 1))
    assert covered.getcolors() == [(covered.width * covered.height, INK)], "total not fully covered"


def scanify(pdf: bytes, rng: random.Random, blot_box: dict | None) -> bytes:
    """Make a clean PDF look like a paper scan and return an image-only PDF."""
    page = pypdfium2.PdfDocument(pdf)[0]
    image = page.render(scale=SCAN_DPI / 72).to_pil().convert("RGB")

    if blot_box:
        add_ink_blot(image, blot_box, rng)

    # Paper is never pure white.
    image = ImageChops.multiply(image, Image.new("RGB", image.size, (250, 247, 240)))
    # Skew 1 to 2 degrees either way; the grey wedges are the scanner bed showing.
    angle = rng.uniform(1.0, 2.0) * rng.choice((-1, 1))
    image = image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=(222, 222, 218))
    image = image.filter(ImageFilter.GaussianBlur(0.7))
    # Grain: blend in a little random speckle.
    speckle = Image.frombytes("L", image.size, rng.randbytes(image.width * image.height))
    image = Image.blend(image, speckle.convert("RGB"), 0.07)

    out = io.BytesIO()
    image.save(out, "PDF", resolution=SCAN_DPI, quality=55,  # quality = JPEG compression
               creationDate=FIXED_PDF_TIME, modDate=FIXED_PDF_TIME)
    return out.getvalue()


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def main() -> None:
    data = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    templates = Environment(loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined,
                            autoescape=True)
    INVOICE_DIR.mkdir(parents=True, exist_ok=True)
    SEED_DIR.mkdir(parents=True, exist_ok=True)

    answer_key, seeded_history = [], []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        # A4 at 96 CSS pixels per inch, so on-screen positions equal positions on the PDF.
        page = browser.new_page(viewport={"width": 794, "height": 1123})

        for definition in data["invoices"]:
            context = build_context(definition, data)
            html = templates.get_template(f"layout_{context['layout'].lower()}.html").render(context)
            pdf, total_box = html_to_pdf(page, html)

            options = definition["print"]
            if options.get("scan"):
                # Each file gets its own random stream, so adding a file never changes another.
                rng = random.Random(f"{RANDOM_SEED}:{definition['file']}")
                pdf = scanify(pdf, rng, total_box if "stained_total" in options else None)

            if "seeded" in definition:
                target = SEED_DIR / definition["file"]
                seeded_history.append({"file": definition["file"], **definition["seeded"],
                                       "extraction": definition["truth"]})
            else:
                target = INVOICE_DIR / definition["file"]
                answer_key.append({
                    "case": definition["case"],
                    "file": definition["file"],
                    "description": definition["description"],
                    "layout": context["layout"],
                    "scanned": bool(options.get("scan")),
                    "truth": definition["truth"],
                    "expected": definition["expected"],
                })
            target.write_bytes(pdf)
            print(f"wrote {target.relative_to(REPO)}")

        browser.close()

    write_json(INVOICE_DIR / "expected.json", {
        "_about": ("Answer key for the 13 test invoices. Generated from "
                   "scripts/invoice_definitions.json by scripts/generate_invoices.py; edit that "
                   "file, not this one. 'truth' is what a perfect reader extracts (amounts are "
                   "strings, read them as Decimal). 'expected' assumes a fresh reset: "
                   "finding_codes must appear as a warning or failure, absent_codes must not."),
        "invoices": answer_key,
        "sequences": data["sequences"],
    })
    write_json(SEED_DIR / "seed_invoices.json", {
        "_about": ("Already-approved invoices loaded as history at seed time. 'extraction' is "
                   "the stored reading of the PDF, so seeding never calls the AI model. Generated "
                   "from scripts/invoice_definitions.json; edit that file, not this one."),
        "invoices": seeded_history,
    })


def write_json(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
