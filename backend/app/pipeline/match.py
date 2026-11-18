"""Stage 4, Match: which vendor and which purchase order does the invoice belong to?
(SPEC section 3.5)

Two rules worth remembering:
- A similar-looking vendor name is only ever SUGGESTED. Look-alike names are a fraud pattern.
- A purchase order found by searching (not printed on the invoice) is only ever SUGGESTED.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from rapidfuzz import fuzz, utils

from app.models import PurchaseOrder, Vendor
from app.money import format_inr
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
from app.pipeline.record import Books, InvoiceRecord
from app.pipeline.validate import ValidateResult
from app.rules_config import MatchConfig

STAGE = "match"

VendorMatch = Literal["tax_id", "name", "suggested", "none"]
POMatchType = Literal["explicit_verified", "explicit_conflict", "not_found", "implied_single",
                      "implied_multiple", "none"]
# Match types where there is one purchase order to check the invoice against.
PO_IN_PLAY = ("explicit_verified", "implied_single")
# Earlier invoices that count: rejected ones are ignored everywhere.
LIVE_STATES = ("approved", "awaiting_review")


class POCandidate(BaseModel):
    """One purchase order considered when the invoice quotes none, with its score out of 100."""

    po_id: str
    score: float
    amount_fits: bool
    description_similarity: float
    date_ok: bool
    strong: bool
    evidence: list[str]  # the three points above as plain-English clauses


class EarlierInvoice(BaseModel):
    invoice_number: str | None
    invoice_date: date | None
    pretax_amount: Decimal | None
    state: str


class POSummary(BaseModel):
    po_id: str
    vendor_id: str
    status: str
    value: Decimal
    billed_to_date: Decimal
    remaining: Decimal
    earlier_invoices: list[EarlierInvoice]


class LinePair(BaseModel):
    """An invoice line and the PO line it was paired with (po_line_no is None if unpaired)."""

    invoice_line: int  # 1-based position on the invoice
    description: str
    po_line_no: int | None
    po_description: str | None
    score: float


class MatchResult(BaseModel):
    vendor_id: str | None
    vendor_name: str | None
    vendor_match: VendorMatch
    po_id: str | None
    po_match_type: POMatchType
    po: POSummary | None
    candidates: list[POCandidate]
    line_pairs: list[LinePair]
    findings: list[Finding]


def match(record: InvoiceRecord, validated: ValidateResult, books: Books,
          rules: MatchConfig) -> MatchResult:
    vendor, vendor_match, findings = _match_vendor(record, books, rules)
    po, po_match_type, candidates, po_findings = _match_po(record, validated, vendor, books,
                                                           rules)
    findings += po_findings

    line_pairs: list[LinePair] = []
    if po is not None and po_match_type in PO_IN_PLAY:
        line_pairs, line_finding = _match_lines(record, po, books, rules)
        findings.append(line_finding)
    else:
        findings.append(skipped("LINE_NOT_ON_PO", STAGE,
                                "there is no purchase order to compare the lines with."))

    return MatchResult(
        vendor_id=vendor.id if vendor else None,
        vendor_name=vendor.name if vendor else None,
        vendor_match=vendor_match,
        po_id=po.id if po else None,
        po_match_type=po_match_type,
        po=_summarise_po(po, books) if po else None,
        candidates=candidates,
        line_pairs=line_pairs,
        findings=findings,
    )


# --- Vendor ------------------------------------------------------------------------------


def clean_vendor_name(name: str, suffixes: list[str]) -> str:
    """'ACME PACKAGING PRIVATE LIMITED' and 'Acme Packaging Pvt. Ltd.' -> 'acme packaging'."""
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    return " ".join(word for word in words if word not in suffixes)


def _clean_tax_id(tax_id: str) -> str:
    return tax_id.replace(" ", "").upper()


def _match_vendor(record: InvoiceRecord, books: Books,
                  rules: MatchConfig) -> tuple[Vendor | None, VendorMatch, list[Finding]]:
    vendor: Vendor | None = None
    how: VendorMatch = "none"
    findings: list[Finding] = []
    printed_tax_id = _clean_tax_id(record.vendor_tax_id) if record.vendor_tax_id else None
    cleaned = (clean_vendor_name(record.vendor_name, rules.vendor_name_suffixes)
               if record.vendor_name else "")

    # 1. Tax ID: the strongest evidence.
    if printed_tax_id:
        vendor = next((v for v in books.vendors if _clean_tax_id(v.tax_id) == printed_tax_id),
                      None)
        if vendor:
            how = "tax_id"
            findings.append(passed("VENDOR_MATCH", STAGE,
                                   f"Vendor confirmed as {vendor.name} ({vendor.id}) by tax "
                                   f"ID: the GSTIN {printed_tax_id} on the invoice matches the "
                                   "vendor master.",
                                   vendor_id=vendor.id, how=how))

    # 2. Exact name once punctuation and company suffixes are removed.
    if vendor is None and cleaned:
        vendor = next((v for v in books.vendors
                       if clean_vendor_name(v.name, rules.vendor_name_suffixes) == cleaned), None)
        if vendor:
            how = "name"
            findings.append(passed("VENDOR_MATCH", STAGE,
                                   f"Vendor confirmed as {vendor.name} ({vendor.id}) by name: "
                                   f"'{record.vendor_name}' is the same name once company "
                                   "suffixes such as Pvt Ltd are set aside.",
                                   vendor_id=vendor.id, how=how))
            if printed_tax_id:
                findings.append(failed(
                    "VENDOR_TAX_ID_CONFLICT", STAGE,
                    f"The name matches {vendor.name}, but the invoice prints GSTIN "
                    f"{printed_tax_id} and the vendor master has {vendor.tax_id}.",
                    severity="review", owner="ap", printed=printed_tax_id, master=vendor.tax_id))

    # 3. A similar name: suggested only, a person must confirm.
    if vendor is None and cleaned:
        scored = [(fuzz.ratio(cleaned, clean_vendor_name(v.name, rules.vendor_name_suffixes)), v)
                  for v in books.vendors]
        best_score, best = max(scored, key=lambda pair: pair[0], default=(0, None))
        if best is not None and best_score >= rules.vendor_fuzzy_min_score:
            vendor, how = best, "suggested"
            findings.append(warned(
                "VENDOR_MATCH", STAGE,
                f"'{record.vendor_name}' is not in the vendor master. It is similar to "
                f"{best.name} ({best.id}), {round(best_score)}% alike. A similar name is never "
                "accepted automatically.",
                severity="review", owner="ap", vendor_id=best.id, how=how,
                score=round(best_score, 1)))

    # 4. Nothing.
    if vendor is None:
        shown = f"'{record.vendor_name}'" if record.vendor_name else "The vendor"
        findings.append(failed("VENDOR_NOT_FOUND", STAGE,
                               f"{shown} is not in the vendor master. The vendor must be "
                               "onboarded first.", severity="reject", owner="procurement"))
    elif vendor.status == "blocked":
        findings.append(failed("VENDOR_BLOCKED", STAGE,
                               f"{vendor.name} ({vendor.id}) is blocked in the vendor master.",
                               severity="reject", owner="procurement", vendor_id=vendor.id))
    return vendor, how, findings


# --- Purchase order ----------------------------------------------------------------------


def normalise_po_reference(reference: str) -> str:
    """'PO-2231', 'P.O. #2231', 'PO 2231' and '2231' all become '2231'."""
    text = re.sub(r"[^A-Z0-9]", "", reference.upper())
    for prefix in ("PURCHASEORDER", "PO", "NO"):
        text = text.removeprefix(prefix)
    return text


def _match_po(
    record: InvoiceRecord, validated: ValidateResult, vendor: Vendor | None, books: Books,
    rules: MatchConfig,
) -> tuple[PurchaseOrder | None, POMatchType, list[POCandidate], list[Finding]]:
    if record.po_reference:
        wanted = normalise_po_reference(record.po_reference)
        po = next((p for p in books.purchase_orders if normalise_po_reference(p.id) == wanted),
                  None)
        if po is None:
            return None, "not_found", [], [failed(
                "PO_NOT_FOUND", STAGE,
                f"The invoice quotes '{record.po_reference}', but there is no such purchase "
                "order.", severity="review", owner="procurement", printed=record.po_reference)]
        if vendor is not None and po.vendor_id == vendor.id:
            return po, "explicit_verified", [], [passed(
                "PO_MATCH", STAGE,
                f"Purchase order confirmed as {po.id}: it is quoted on the invoice "
                f"('{record.po_reference}') and belongs to {vendor.name}.", po_id=po.id)]
        owner_name = next((v.name for v in books.vendors if v.id == po.vendor_id), po.vendor_id)
        invoice_vendor = vendor.name if vendor else "a vendor that is not in the vendor master"
        return po, "explicit_conflict", [], [failed(
            "PO_VENDOR_CONFLICT", STAGE,
            f"The invoice quotes {po.id}, but that purchase order belongs to {owner_name} and "
            f"the invoice is from {invoice_vendor}.",
            severity="review", owner="ap", po_id=po.id, po_vendor_id=po.vendor_id)]

    # No PO printed: search the vendor's open purchase orders.
    if vendor is None:
        return None, "none", [], [skipped(
            "PO_MATCH", STAGE, "no purchase order is quoted and the vendor is not known, so "
            "there is nothing to search.")]

    candidates = [_score_candidate(record, validated, po, books, rules)
                  for po in books.purchase_orders
                  if po.vendor_id == vendor.id and po.status == "open"]
    candidates.sort(key=lambda c: c.score, reverse=True)
    strong = [c for c in candidates if c.strong]

    if len(strong) == 1:
        po = next(p for p in books.purchase_orders if p.id == strong[0].po_id)
        return po, "implied_single", candidates, [warned(
            "PO_IMPLIED", STAGE,
            f"No purchase order is quoted on the invoice. {po.id} is the only open purchase "
            f"order of {vendor.name} that fits: {join_and(strong[0].evidence)}. A person must "
            "confirm it.",
            severity="review", owner="ap", suggested_po_id=po.id, score=round(strong[0].score))]
    if len(strong) > 1:
        options = " ".join(f"{c.po_id}: {join_and(c.evidence)}." for c in strong)
        return None, "implied_multiple", candidates, [warned(
            "PO_IMPLIED", STAGE,
            f"No purchase order is quoted on the invoice and {len(strong)} open purchase orders "
            f"of {vendor.name} fit. {options} A person must choose.",
            severity="review", owner="ap", shortlist=[c.po_id for c in strong],
            scores={c.po_id: round(c.score) for c in strong})]
    return None, "none", candidates, [failed(
        "PO_NOT_IDENTIFIED", STAGE,
        f"No purchase order is quoted on the invoice and none of the open purchase orders of "
        f"{vendor.name} ({len(candidates)} searched) is a strong fit.",
        severity="review", owner="procurement")]


def _score_candidate(record: InvoiceRecord, validated: ValidateResult, po: PurchaseOrder,
                     books: Books, rules: MatchConfig) -> POCandidate:
    """Score one open purchase order out of 100 and say in words what the score rests on."""
    pretax = validated.pretax_amount
    invoice_date = validated.invoice_date

    # 1. Does the invoice amount fit what is left on the purchase order?
    amount_fits = pretax is not None and pretax <= po.remaining
    if pretax is None:
        amount_clause = "the invoice amount before tax is not known"
    else:
        verb = "fits" if amount_fits else "is more than"
        amount_clause = (f"the invoice amount of {format_inr(pretax)} before tax {verb} its "
                         f"remaining balance of {format_inr(po.remaining)}")

    # 2. Which invoice lines look like a line on the purchase order?
    po_lines = books.lines_of(po.id)
    similarity = 0.0
    matched_items = []
    for line in record.line_items:
        if not line.description or not po_lines:
            continue
        best = max(po_lines, key=lambda po_line: _similarity(line.description,
                                                             po_line.description))
        line_similarity = _similarity(line.description, best.description)
        similarity = max(similarity, line_similarity)
        if line_similarity >= rules.line_match_min_score:
            matched_items.append(f"'{line.description}' matches its line '{best.description}'")
    items_clause = (join_and(matched_items) if matched_items
                    else "no invoice line closely matches its lines")

    # 3. Is the invoice dated on or after the purchase order?
    date_ok = invoice_date is not None and invoice_date >= po.po_date
    if invoice_date is None:
        date_clause = "the invoice date is not known"
    else:
        order = "on or after" if date_ok else "before"
        date_clause = (f"the invoice date ({show_date(invoice_date)}) is {order} the purchase "
                       f"order date ({show_date(po.po_date)})")

    score = (rules.implied_po_points_amount_fits * amount_fits
             + rules.implied_po_points_description * similarity / 100
             + rules.implied_po_points_date * date_ok)
    score = round(score, 1)
    return POCandidate(po_id=po.id, score=score, amount_fits=amount_fits,
                       description_similarity=round(similarity, 1), date_ok=date_ok,
                       strong=score >= rules.implied_po_strong_score,
                       evidence=[amount_clause, items_clause, date_clause])


def _summarise_po(po: PurchaseOrder, books: Books) -> POSummary:
    earlier = [EarlierInvoice(invoice_number=inv.invoice_number, invoice_date=inv.invoice_date,
                              pretax_amount=inv.pretax_amount, state=inv.state)
               for inv in books.invoices if inv.po_id == po.id and inv.state in LIVE_STATES]
    return POSummary(po_id=po.id, vendor_id=po.vendor_id, status=po.status, value=po.value,
                     billed_to_date=po.billed_to_date, remaining=po.remaining,
                     earlier_invoices=earlier)


# --- Lines -------------------------------------------------------------------------------


def _similarity(a: str, b: str) -> float:
    """0 to 100. Ignores case, punctuation and word order."""
    return fuzz.token_set_ratio(a, b, processor=utils.default_process)


def describe_line(record: InvoiceRecord, invoice_line: int) -> str:
    """An invoice line for a sentence: 'Freight' (₹1,200 before tax)."""
    line = record.line_items[invoice_line - 1]
    if line.amount is None:
        return f"'{line.description}'"
    tax = "including tax" if record.amounts_tax_inclusive else "before tax"
    return f"'{line.description}' ({format_inr(line.amount)} {tax})"


def _match_lines(record: InvoiceRecord, po: PurchaseOrder, books: Books,
                 rules: MatchConfig) -> tuple[list[LinePair], Finding]:
    """Pair each invoice line with the most similar PO line, if any is similar enough."""
    po_lines = books.lines_of(po.id)
    described = [(number, line.description)
                 for number, line in enumerate(record.line_items, start=1) if line.description]
    if not described or not po_lines:
        return [], skipped("LINE_NOT_ON_PO", STAGE,
                           "the invoice has no itemised lines to compare with the purchase "
                           "order.")

    pairs = []
    for number, description in described:
        best = max(po_lines, key=lambda po_line: _similarity(description, po_line.description))
        score = round(_similarity(description, best.description), 1)
        paired = score >= rules.line_match_min_score
        pairs.append(LinePair(invoice_line=number, description=description,
                              po_line_no=best.line_no if paired else None,
                              po_description=best.description if paired else None, score=score))

    unpaired = [pair for pair in pairs if pair.po_line_no is None]
    if unpaired:
        listed = join_and([describe_line(record, pair.invoice_line) for pair in unpaired])
        return pairs, warned("LINE_NOT_ON_PO", STAGE,
                             f"{plural(len(unpaired), 'invoice line')} "
                             f"{'is' if len(unpaired) == 1 else 'are'} not on {po.id}: "
                             f"{listed}.",
                             lines=[pair.invoice_line for pair in unpaired])
    return pairs, passed("LINE_NOT_ON_PO", STAGE,
                         f"Every invoice line corresponds to a line on {po.id} "
                         f"({plural(len(pairs), 'line')}).")
