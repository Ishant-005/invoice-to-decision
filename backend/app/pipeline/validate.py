"""Stage 3, Validate: is the invoice complete and consistent with itself? (SPEC section 3.4)

Nothing here looks at vendors or purchase orders. Every check runs, whatever the others found.
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app.money import format_inr, plain_number
from app.pipeline.findings import (
    Finding,
    failed,
    passed,
    plural,
    show_date,
    skipped,
    warned,
)
from app.pipeline.record import InvoiceRecord
from app.rules_config import ValidateConfig

STAGE = "validate"
PAISA = Decimal("0.01")
# Standard GSTIN shape: 2-digit state, 10-character PAN, entity character, 'Z', check character.
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class ValidateResult(BaseModel):
    pretax_amount: Decimal | None  # what is compared with the purchase order (POs are pre-tax)
    gross_amount: Decimal | None  # the payable total as printed
    pretax_source: str  # "printed_subtotal" | "derived_from_inclusive_total" | ...
    invoice_date: date | None  # the parsed date, or None if missing or unreadable
    findings: list[Finding]


def validate(record: InvoiceRecord, today: date, rules: ValidateConfig) -> ValidateResult:
    parsed_date = _parse_date(record.invoice_date)
    pretax, source, pretax_finding = _normalise_tax(record)
    findings = [
        _check_document_type(record),
        _check_required_fields(record),
        _check_line_arithmetic(record, rules),
        _check_totals(record, rules),
        _check_date(record, parsed_date, today, rules),
        _check_amounts(record, rules),
        _check_tax_id(record),
        pretax_finding,
    ]
    return ValidateResult(pretax_amount=pretax, gross_amount=record.total, pretax_source=source,
                          invoice_date=parsed_date, findings=findings)


def _parse_date(text: str | None) -> date | None:
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _check_document_type(record: InvoiceRecord) -> Finding:
    if record.document_type == "invoice":
        return passed("DOC_TYPE", STAGE, "The document is an invoice.")
    kind = record.document_type.replace("_", " ")
    return failed("DOC_TYPE", STAGE,
                  f"The document is not an invoice (it reads as: {kind}).",
                  severity="reject", owner="ap", document_type=record.document_type)


def _check_required_fields(record: InvoiceRecord) -> Finding:
    required = {"invoice number": record.invoice_number, "vendor name": record.vendor_name,
                "invoice date": record.invoice_date, "total": record.total}
    missing = [label for label, value in required.items() if value is None]
    if not missing:
        return passed("REQUIRED_FIELDS", STAGE,
                      "Invoice number, vendor name, invoice date and total are all present.")
    return failed("REQUIRED_FIELDS", STAGE,
                  f"Could not be read from the document: {', '.join(missing)}.",
                  severity="review", owner="vendor", missing=missing)


def _check_line_arithmetic(record: InvoiceRecord, rules: ValidateConfig) -> Finding:
    """quantity × unit price = amount on every line that prints all three."""
    checked = 0
    problems = []
    for number, line in enumerate(record.line_items, start=1):
        if line.quantity is None or line.unit_price is None or line.amount is None:
            continue
        checked += 1
        expected = line.quantity * line.unit_price
        if abs(expected - line.amount) > rules.rounding_tolerance_rupees:
            problems.append(
                f"line {number}: {plain_number(line.quantity)} × {format_inr(line.unit_price)} "
                f"= {format_inr(expected)}, but the line states {format_inr(line.amount)}")
    if checked == 0:
        return skipped("LINE_ARITHMETIC", STAGE,
                       "no line shows a quantity, a unit price and an amount together.")
    if problems:
        return failed("LINE_ARITHMETIC", STAGE,
                      "Line amounts do not multiply out (" + "; ".join(problems) + ").",
                      severity="review", owner="vendor", lines_checked=checked)
    return passed("LINE_ARITHMETIC", STAGE,
                  f"Quantity × unit price equals the amount on every line checked "
                  f"({plural(checked, 'line')}).",
                  lines_checked=checked)


def _check_totals(record: InvoiceRecord, rules: ValidateConfig) -> Finding:
    """Two sums: the lines add up to the subtotal, and subtotal + tax = total."""
    problems, confirmed, not_checked = [], [], []

    amounts = [line.amount for line in record.line_items]
    if amounts and all(amount is not None for amount in amounts) and record.subtotal is not None:
        line_sum = sum(amounts, Decimal(0))
        if abs(line_sum - record.subtotal) > rules.rounding_tolerance_rupees:
            problems.append(f"The lines add up to {format_inr(line_sum)}, but the invoice "
                            f"states a subtotal of {format_inr(record.subtotal)} (both before "
                            "tax).")
        else:
            confirmed.append(f"the lines sum to the subtotal of {format_inr(record.subtotal)} "
                             "before tax")
    else:
        not_checked.append("lines against subtotal")

    if record.subtotal is not None and record.tax_amount is not None and record.total is not None:
        computed = record.subtotal + record.tax_amount
        sums = (f"{format_inr(record.subtotal)} + tax {format_inr(record.tax_amount)} = "
                f"{format_inr(computed)}")
        if abs(computed - record.total) > rules.rounding_tolerance_rupees:
            problems.append(f"Subtotal {sums}, but the invoice states a total of "
                            f"{format_inr(record.total)} including tax.")
        else:
            confirmed.append(f"subtotal {sums} including tax, as printed")
    else:
        not_checked.append("subtotal + tax against total")

    data = {"not_checked": not_checked}
    if problems:
        return failed("TOTALS", STAGE, " ".join(problems), severity="review", owner="vendor",
                      **data)
    if not confirmed:
        return skipped("TOTALS", STAGE,
                       "the invoice does not print a subtotal, tax and total to add up.")
    message = "The invoice's figures add up: " + "; ".join(confirmed) + "."
    if not_checked:
        message += f" (Could not check: {', '.join(not_checked)}.)"
    return passed("TOTALS", STAGE, message, **data)


def _check_date(record: InvoiceRecord, parsed: date | None, today: date,
                rules: ValidateConfig) -> Finding:
    if record.invoice_date is None:
        return skipped("DATE_SANITY", STAGE, "no invoice date could be read.")
    if parsed is None:
        return failed("DATE_SANITY", STAGE,
                      f"The invoice date '{record.invoice_date}' is not a valid date.",
                      severity="review", owner="vendor")
    shown = show_date(parsed)
    if parsed > today:
        return failed("DATE_SANITY", STAGE, f"The invoice is dated {shown}, which is in the future.",
                      severity="review", owner="vendor", invoice_date=parsed.isoformat())
    if record.date_is_ambiguous:
        return warned("DATE_SANITY", STAGE,
                      f"The date reads as {shown}, but the day and month could be the other way "
                      "round.", severity="review", owner="ap", invoice_date=parsed.isoformat())
    age_days = (today - parsed).days
    if age_days > rules.max_invoice_age_days:
        return warned("DATE_SANITY", STAGE,
                      f"The invoice is dated {shown}, {age_days} days ago (older than "
                      f"{rules.max_invoice_age_days} days).", invoice_date=parsed.isoformat())
    return passed("DATE_SANITY", STAGE, f"The invoice date {shown} is valid and not in the future.",
                  invoice_date=parsed.isoformat())


def _check_amounts(record: InvoiceRecord, rules: ValidateConfig) -> Finding:
    """Amounts must be positive (tax may be zero) and the currency must be the accepted one."""
    problems = []
    amounts = {"total": record.total, "subtotal": record.subtotal}
    for number, line in enumerate(record.line_items, start=1):
        amounts[f"line {number} quantity"] = line.quantity
        amounts[f"line {number} unit price"] = line.unit_price
        amounts[f"line {number} amount"] = line.amount
    for label, value in amounts.items():
        if value is not None and value <= 0:
            problems.append(f"{label} is {plain_number(value)}")
    if record.tax_amount is not None and record.tax_amount < 0:
        problems.append(f"tax is {plain_number(record.tax_amount)}")
    if record.currency is not None and record.currency.upper() != rules.currency:
        problems.append(f"the currency is {record.currency}, not {rules.currency}")

    if problems:
        return failed("AMOUNT_SANITY", STAGE, "Amounts are not acceptable: " +
                      "; ".join(problems) + ".", severity="review", owner="ap")
    if record.currency is None:
        return warned("AMOUNT_SANITY", STAGE,
                      f"No currency is printed; {rules.currency} is assumed. All amounts are "
                      "positive.")
    return passed("AMOUNT_SANITY", STAGE, f"All amounts are positive and in {rules.currency}.")


def _check_tax_id(record: InvoiceRecord) -> Finding:
    if record.vendor_tax_id is None:
        return skipped("TAX_ID_FORMAT", STAGE, "no GSTIN is printed on the invoice.")
    tax_id = record.vendor_tax_id.replace(" ", "").upper()
    if GSTIN_PATTERN.match(tax_id):
        return passed("TAX_ID_FORMAT", STAGE, f"GSTIN {tax_id} has the standard 15-character form.")
    return warned("TAX_ID_FORMAT", STAGE,
                  f"GSTIN '{record.vendor_tax_id}' does not have the standard 15-character form.",
                  tax_id=record.vendor_tax_id)


def _normalise_tax(record: InvoiceRecord) -> tuple[Decimal | None, str, Finding]:
    """Work out the pre-tax amount, because purchase order values are pre-tax."""
    if record.subtotal is not None:
        return record.subtotal, "printed_subtotal", passed(
            "PRETAX_AMOUNT", STAGE,
            f"The amount before tax is the printed subtotal, {format_inr(record.subtotal)}.",
            pretax_amount=str(record.subtotal))

    if (record.total is not None and record.amounts_tax_inclusive
            and record.tax_rate_percent is not None):
        divisor = 1 + record.tax_rate_percent / 100
        pretax = (record.total / divisor).quantize(PAISA, rounding=ROUND_HALF_UP)
        return pretax, "derived_from_inclusive_total", passed(
            "PRETAX_AMOUNT", STAGE,
            f"Only a total including tax is printed: {format_inr(record.total)} including "
            f"{plain_number(record.tax_rate_percent)}% GST ÷ {plain_number(divisor)} = "
            f"{format_inr(pretax)} before tax.",
            pretax_amount=str(pretax))

    if record.total is not None and record.tax_amount is not None:
        pretax = record.total - record.tax_amount
        return pretax, "total_minus_tax", passed(
            "PRETAX_AMOUNT", STAGE,
            f"No subtotal is printed: total {format_inr(record.total)} including tax − tax "
            f"{format_inr(record.tax_amount)} = {format_inr(pretax)} before tax.",
            pretax_amount=str(pretax))

    return None, "unresolved", failed(
        "TAX_UNRESOLVED", STAGE,
        "The amount before tax cannot be worked out: the invoice prints no subtotal, and no "
        "total with a tax amount or a tax-inclusive rate.",
        severity="review", owner="ap")
