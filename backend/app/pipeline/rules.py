"""Stage 5, Rules: does the invoice comply with company policy? (SPEC section 3.6)

Duplicates, purchase order status and balance, and unit prices. Thresholds come from
config/rules.yaml.
"""

import re
from decimal import Decimal

from pydantic import BaseModel

from app.models import Invoice
from app.money import format_inr, plain_number
from app.pipeline.findings import (
    Finding,
    failed,
    join_and,
    passed,
    plural,
    show_date,
    skipped,
    warned,
)
from app.pipeline.match import LIVE_STATES, PO_IN_PLAY, MatchResult, describe_line
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
    overage, balance_finding = _check_po_balance(record, validated, matched, rules)
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
                same = [f"the same total ({format_inr(gross)} including tax)"]
                if same_date:
                    same.append(f"the same invoice date ({show_date(inv.invoice_date)})")
                if extended:
                    same.append(f"nearly the same invoice number ('{record.invoice_number}' "
                                f"against '{inv.invoice_number}')")
                earlier_name = (f"invoice {inv.invoice_number}" if inv.invoice_number
                                else f"the earlier file {inv.file_name}")
                status = "already approved" if inv.state == "approved" else "awaiting review"
                probable.append(_link(
                    "probable", inv,
                    f"This looks like the same bill as {earlier_name} from "
                    f"{matched.vendor_name}, which is {status}. Both have {join_and(same)}. "
                    f"If both are paid, {format_inr(gross)} including tax would be paid twice."))

    findings: list[Finding] = []

    if exact:
        findings.append(failed("DUPLICATE_EXACT", STAGE,
                               "Exact duplicate: " + "; ".join(d.reason for d in exact) + ".",
                               severity="reject", owner="ap",
                               duplicates=[d.model_dump() for d in exact]))
    else:
        also = " or has the same vendor and invoice number" if number and vendor_id else ""
        findings.append(passed("DUPLICATE_EXACT", STAGE,
                               f"No duplicate found: no earlier invoice is the same file{also}."))

    if vendor_id is None or gross is None:
        missing = "the vendor is not known" if vendor_id is None else "the total could not be read"
        findings.append(skipped("DUPLICATE_PROBABLE", STAGE,
                                f"{missing}, so there is nothing to compare with earlier "
                                "invoices."))
    elif probable:
        findings.append(failed("DUPLICATE_PROBABLE", STAGE,
                               " ".join(d.reason for d in probable),
                               severity="review", owner="ap", amount_at_risk=str(gross),
                               duplicates=[d.model_dump() for d in probable]))
    else:
        findings.append(passed("DUPLICATE_PROBABLE", STAGE,
                               "No likely duplicate found: no earlier invoice from this "
                               f"vendor has the same total ({format_inr(gross)} including tax) "
                               "together with the same date or a nearly identical number."))

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


def po_position(po_id: str, value: Decimal, billed: Decimal, now: bool = False) -> str:
    """Where a purchase order stands once an invoice is added, e.g. 'PO-2260 would have
    ₹2,00,000 of ₹3,00,000 billed before tax, ₹1,00,000 remaining'. A check words it as
    "would" because nothing is decided yet; an approval passes now=True ("now has")."""
    has, is_ = ("now has", "is now") if now else ("would have", "would be")
    if billed == value:
        return f"{po_id} {is_} fully billed: {format_inr(billed)} of {format_inr(value)} before tax"
    if billed < value:
        return (f"{po_id} {has} {format_inr(billed)} of {format_inr(value)} billed before tax, "
                f"{format_inr(value - billed)} remaining")
    return (f"{po_id} {has} {format_inr(billed)} billed against a value of {format_inr(value)} "
            f"before tax, {format_inr(billed - value)} over")


def overage_limit(po_value: Decimal, rules: RulesThresholds) -> Decimal:
    """The most a purchase order may be exceeded by: the lower of the percentage limit and
    the rupee limit. For a PO of ₹1,50,000 that is min(2% = ₹3,000, ₹5,000) = ₹3,000."""
    return min(po_value * rules.po_overage_max_percent / 100, rules.po_overage_max_rupees)


def _check_po_balance(record: InvoiceRecord, validated: ValidateResult, matched: MatchResult,
                      rules: RulesThresholds) -> tuple[Decimal | None, Finding]:
    """billed so far + this invoice (before tax) must not exceed the PO value, within the limit."""
    if matched.po is None or matched.po_match_type not in PO_IN_PLAY:
        return None, skipped("PO_BALANCE", STAGE, "no purchase order has been identified.")
    if validated.pretax_amount is None:
        return None, skipped("PO_BALANCE", STAGE, "the amount before tax could not be worked out.")

    po = matched.po
    pretax = validated.pretax_amount
    billed_after = po.billed_to_date + pretax
    overage = max(billed_after - po.value, Decimal(0))
    limit = overage_limit(po.value, rules)
    data = {"po_id": po.po_id, "po_value": str(po.value),
            "billed_to_date": str(po.billed_to_date), "this_invoice": str(pretax),
            "billed_after": str(billed_after), "overage": str(overage),
            "overage_limit": str(limit)}

    if overage == 0:
        return overage, passed(
            "PO_BALANCE", STAGE,
            f"Fits the purchase order balance: this invoice is {format_inr(pretax)} before tax "
            f"and {po.po_id} has {format_inr(po.remaining)} remaining. With this invoice, "
            f"{po_position(po.po_id, po.value, billed_after)}.", **data)

    message = (f"This invoice is {format_inr(pretax)} before tax, but {po.po_id} has only "
               f"{format_inr(po.remaining)} remaining of its {format_inr(po.value)} value before "
               f"tax, so the invoice takes it {format_inr(overage)} over.")
    within = overage <= limit
    if within:
        message += (f" That is within the {format_inr(limit)} by which this purchase order may "
                    "be exceeded.")
    else:
        message += f" The most this purchase order may be exceeded by is {format_inr(limit)}."

    # Would it fit if the lines that are not on the purchase order were left out?
    unlisted = [pair.invoice_line for pair in matched.line_pairs if pair.po_line_no is None]
    amounts = [record.line_items[number - 1].amount for number in unlisted]
    if unlisted and None not in amounts and not record.amounts_tax_inclusive:
        without = pretax - sum(amounts, Decimal(0))
        fits_without = po.billed_to_date + without <= po.value
        data["fits_without_unlisted_lines"] = fits_without
        if fits_without:
            names = join_and([describe_line(record, number) for number in unlisted])
            verb = "is" if len(unlisted) == 1 else "are"
            message += (f" Without {names}, which {verb} not on {po.po_id}, the invoice would "
                        f"be {format_inr(without)} before tax and would fit.")

    if within:
        return overage, warned("PO_BALANCE", STAGE, message, **data)
    return overage, failed("PO_BALANCE", STAGE, message, severity="review",
                           owner="procurement", **data)


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
                            f"unit before tax; the purchase order price is {format_inr(po_price)} "
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
