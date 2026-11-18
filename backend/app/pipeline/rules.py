"""Stage 5, Rules: does the invoice comply with company policy? (SPEC section 3.6)

Duplicates, purchase order status and balance, and unit prices. Thresholds come from
config/rules.yaml.
"""

import re
from decimal import Decimal

from pydantic import BaseModel

from app.models import Invoice
from app.money import format_inr, plain_number
from app.pipeline.findings import Finding, failed, passed, plural, skipped, warned
from app.pipeline.match import LIVE_STATES, PO_IN_PLAY, MatchResult
from app.pipeline.record import Books, InvoiceRecord
from app.pipeline.validate import ValidateResult
from app.rules_config import RulesThresholds

STAGE = "rules"


class DuplicateLink(BaseModel):
    """An earlier invoice this one appears to repeat."""

    kind: str  # "exact" | "probable"
    invoice_id: int | None
    invoice_number: str | None
    file_name: str
    reason: str


class RulesResult(BaseModel):
    duplicates: list[DuplicateLink]
    po_overage: Decimal | None  # how far this invoice takes the PO over its value (0 if not)
    findings: list[Finding]


def apply_rules(record: InvoiceRecord, validated: ValidateResult, matched: MatchResult,
                books: Books, file_hash: str, rules: RulesThresholds) -> RulesResult:
    duplicates, findings = _check_duplicates(record, validated, matched, books, file_hash, rules)
    findings.append(_check_po_status(matched))
    overage, balance_finding = _check_po_balance(validated, matched, rules)
    findings.append(balance_finding)
    findings.append(_check_price_variance(record, matched, books, rules))
    return RulesResult(duplicates=duplicates, po_overage=overage, findings=findings)


# --- Duplicates --------------------------------------------------------------------------


def normalise_invoice_number(number: str) -> str:
    """'inv-1017', 'INV 1017' and 'INV/1017' all become 'INV1017'."""
    return re.sub(r"[^A-Z0-9]", "", number.upper())


def is_number_extension(a: str, b: str, max_extra: int) -> bool:
    """True if one normalised number is the other plus 1..max_extra trailing characters."""
    shorter, longer = sorted((a, b), key=len)
    extra = len(longer) - len(shorter)
    return bool(shorter) and longer.startswith(shorter) and 0 < extra <= max_extra


def _check_duplicates(record: InvoiceRecord, validated: ValidateResult, matched: MatchResult,
                      books: Books, file_hash: str,
                      rules: RulesThresholds) -> tuple[list[DuplicateLink], list[Finding]]:
    # Rejected invoices are left out: a corrected resubmission is legitimate.
    earlier = [inv for inv in books.invoices if inv.state in LIVE_STATES]
    number = normalise_invoice_number(record.invoice_number) if record.invoice_number else None
    vendor_id = matched.vendor_id
    gross = validated.gross_amount

    exact: list[DuplicateLink] = []
    probable: list[DuplicateLink] = []
    for inv in earlier:
        same_vendor = vendor_id is not None and inv.vendor_id == vendor_id
        their_number = normalise_invoice_number(inv.invoice_number) if inv.invoice_number else None
        label = _label(inv)

        if inv.file_hash == file_hash:
            exact.append(_link("exact", inv, f"this is the identical file to {label}"))
        elif same_vendor and number and their_number == number:
            exact.append(_link("exact", inv, "the same vendor and invoice number as "
                                             f"{label}"))
        elif same_vendor and gross is not None and inv.gross_amount == gross:
            same_date = (validated.invoice_date is not None
                         and inv.invoice_date == validated.invoice_date)
            extended = bool(number and their_number) and is_number_extension(
                number, their_number, rules.duplicate_max_extra_characters)
            if same_date or extended:
                clues = [f"same total {format_inr(gross)}"]
                if same_date:
                    clues.append("same invoice date")
                if extended:
                    clues.append(f"number '{record.invoice_number}' is a variation of "
                                 f"'{inv.invoice_number}'")
                probable.append(_link("probable", inv, f"same vendor as {label}, "
                                                       + ", ".join(clues)))

    findings: list[Finding] = []

    if exact:
        findings.append(failed("DUPLICATE_EXACT", STAGE,
                               "Exact duplicate: " + "; ".join(d.reason for d in exact) + ".",
                               severity="reject", owner="ap",
                               duplicates=[d.model_dump() for d in exact]))
    else:
        also = " or has the same vendor and invoice number" if number and vendor_id else ""
        findings.append(passed("DUPLICATE_EXACT", STAGE,
                               f"No earlier invoice is the same file{also}."))

    if vendor_id is None or gross is None:
        missing = "the vendor is not known" if vendor_id is None else "the total could not be read"
        findings.append(skipped("DUPLICATE_PROBABLE", STAGE,
                                f"{missing}, so there is nothing to compare with earlier "
                                "invoices."))
    elif probable:
        findings.append(failed("DUPLICATE_PROBABLE", STAGE,
                               "Probable duplicate: " + "; ".join(d.reason for d in probable)
                               + ".", severity="review", owner="ap",
                               duplicates=[d.model_dump() for d in probable]))
    else:
        findings.append(passed("DUPLICATE_PROBABLE", STAGE,
                               f"No earlier invoice from this vendor has the same total "
                               f"({format_inr(gross)}) with the same date or a similar number."))

    if number is None:
        findings.append(warned("DUPLICATE_CHECK_PARTIAL", STAGE,
                               "The invoice has no readable number, so it could not be compared "
                               "with earlier invoice numbers. The duplicate check is incomplete."))
    return exact + probable, findings


def _label(inv: Invoice) -> str:
    name = inv.invoice_number or inv.file_name
    return f"{name} ({inv.state.replace('_', ' ')})"


def _link(kind: str, inv: Invoice, reason: str) -> DuplicateLink:
    return DuplicateLink(kind=kind, invoice_id=inv.id, invoice_number=inv.invoice_number,
                         file_name=inv.file_name, reason=reason)


# --- Purchase order ----------------------------------------------------------------------


def _check_po_status(matched: MatchResult) -> Finding:
    if matched.po is None or matched.po_match_type not in PO_IN_PLAY:
        return skipped("PO_STATUS", STAGE, "no purchase order has been identified.")
    if matched.po.status != "open":
        return failed("PO_STATUS", STAGE,
                      f"{matched.po.po_id} is {matched.po.status}, not open.",
                      severity="review", owner="procurement", po_id=matched.po.po_id)
    return passed("PO_STATUS", STAGE, f"{matched.po.po_id} is open.")


def _check_po_balance(validated: ValidateResult, matched: MatchResult,
                      rules: RulesThresholds) -> tuple[Decimal | None, Finding]:
    """billed so far + this invoice (pre-tax) must not exceed the PO value, within tolerance."""
    if matched.po is None or matched.po_match_type not in PO_IN_PLAY:
        return None, skipped("PO_BALANCE", STAGE, "no purchase order has been identified.")
    if validated.pretax_amount is None:
        return None, skipped("PO_BALANCE", STAGE, "the pre-tax amount could not be worked out.")

    po = matched.po
    pretax = validated.pretax_amount
    billed_after = po.billed_to_date + pretax
    overage = max(billed_after - po.value, Decimal(0))
    sums = (f"{po.po_id} is worth {format_inr(po.value)} and {format_inr(po.billed_to_date)} "
            f"is already billed. This invoice ({format_inr(pretax)} before tax) takes it to "
            f"{format_inr(billed_after)}")
    data = {"po_id": po.po_id, "po_value": str(po.value),
            "billed_to_date": str(po.billed_to_date), "this_invoice": str(pretax),
            "billed_after": str(billed_after), "overage": str(overage)}

    if overage == 0:
        left = po.value - billed_after
        return overage, passed("PO_BALANCE", STAGE, f"{sums}, leaving {format_inr(left)}.", **data)

    percent = overage / po.value * 100
    limit = (f"{plain_number(rules.po_overage_max_percent)}% and "
             f"{format_inr(rules.po_overage_max_rupees)}")
    over = f"{sums}, which is {format_inr(overage)} ({_percent(percent)}) over"
    within = (percent <= rules.po_overage_max_percent
              and overage <= rules.po_overage_max_rupees)
    if within:
        return overage, warned("PO_BALANCE", STAGE,
                               f"{over}. That is within the allowed tolerance of {limit}.",
                               **data)
    return overage, failed("PO_BALANCE", STAGE,
                           f"{over}. That is beyond the allowed tolerance of {limit}.",
                           severity="review", owner="procurement", **data)


def _check_price_variance(record: InvoiceRecord, matched: MatchResult, books: Books,
                          rules: RulesThresholds) -> Finding:
    """Each paired line's unit price must be within the allowed percentage of the PO price."""
    if matched.po is None or matched.po_match_type not in PO_IN_PLAY:
        return skipped("PRICE_VARIANCE", STAGE, "no purchase order has been identified.")
    po_prices = {line.line_no: line.unit_price for line in books.lines_of(matched.po.po_id)}

    compared = 0
    problems = []
    for pair in matched.line_pairs:
        invoice_price = record.line_items[pair.invoice_line - 1].unit_price
        if pair.po_line_no is None or invoice_price is None:
            continue
        po_price = po_prices[pair.po_line_no]
        compared += 1
        percent = (invoice_price - po_price) / po_price * 100
        if abs(percent) > rules.price_variance_max_percent:
            direction = "above" if percent > 0 else "below"
            problems.append(f"'{pair.description}' is billed at {format_inr(invoice_price)} per "
                            f"unit; the purchase order price is {format_inr(po_price)} "
                            f"({_percent(abs(percent))} {direction})")

    limit = f"{plain_number(rules.price_variance_max_percent)}%"
    if compared == 0:
        return skipped("PRICE_VARIANCE", STAGE,
                       "no invoice line has both a unit price and a matching purchase order "
                       "line.")
    if problems:
        return failed("PRICE_VARIANCE", STAGE,
                      "; ".join(problems) + f". The allowed difference is {limit}.",
                      severity="review", owner="procurement", lines_compared=compared)
    return passed("PRICE_VARIANCE", STAGE,
                  f"Unit prices are within {limit} of the purchase order price on every matched "
                  f"line ({plural(compared, 'line')}).", lines_compared=compared)


def _percent(value: Decimal) -> str:
    """8 -> '8%', 0.8 -> '0.8%', 13.3333 -> '13.33%'."""
    return plain_number(value.quantize(Decimal("0.01"))) + "%"
