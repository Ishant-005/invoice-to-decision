"""Stage 6, Decide: combine every finding into one decision. (SPEC section 3.7)

The decision is the worst severity found: any `reject` means REJECT, otherwise any `review`
means REVIEW, otherwise APPROVE. All wording comes from the templates below and from the
findings' own messages. No AI model writes any of it.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.money import format_inr
from app.pipeline.findings import Finding, Owner
from app.pipeline.match import MatchResult
from app.pipeline.rules import RulesResult, po_position
from app.pipeline.validate import ValidateResult

DecisionType = Literal["APPROVE", "REVIEW", "REJECT"]

SEVERITY_RANK = {"reject": 0, "review": 1, "info": 2}
STATUS_RANK = {"fail": 0, "warn": 1}

OWNER_LABELS = {"ap": "Accounts Payable", "procurement": "Procurement", "vendor": "The vendor",
                "none": "No one"}

# For each finding code that can stop an approval: a short headline, and what to do next.
TEMPLATES: dict[str, tuple[str, str]] = {
    "DOC_TYPE": (
        "the document is not an invoice",
        "Do not pay. Reply to the sender that only invoices are processed here."),
    "REQUIRED_FIELDS": (
        "essential details could not be read from the invoice",
        "Ask the vendor for a clean, complete copy of the invoice."),
    "LINE_ARITHMETIC": (
        "line amounts on the invoice do not multiply out",
        "Ask the vendor to correct the line amounts and send the invoice again."),
    "TOTALS": (
        "the invoice's own figures do not add up",
        "Ask the vendor to correct the figures and send the invoice again."),
    "DATE_SANITY": (
        "the invoice date needs checking",
        "Check the date against the document; ask the vendor to reissue if it is wrong."),
    "AMOUNT_SANITY": (
        "the amounts or currency are not acceptable",
        "Check the amounts and currency against the document before going further."),
    "TAX_UNRESOLVED": (
        "the pre-tax amount cannot be worked out",
        ("Find out the pre-tax amount (ask the vendor for a tax breakdown) so the invoice can "
        "be compared with the purchase order.")),
    "VENDOR_MATCH": (
        "the vendor name is only similar to one in the vendor master",
        ("Confirm with the vendor master whether this is the suggested vendor. Similar names "
        "are a known fraud pattern.")),
    "VENDOR_NOT_FOUND": (
        "the vendor is not in the vendor master",
        "Do not pay. Procurement must onboard the vendor before any invoice can be accepted."),
    "VENDOR_BLOCKED": (
        "the vendor is blocked",
        "Do not pay. Procurement must lift the block before any invoice can be accepted."),
    "VENDOR_TAX_ID_CONFLICT": (
        "the GSTIN on the invoice differs from the vendor master",
        "Verify the vendor's GSTIN with the vendor before paying."),
    "PO_NOT_FOUND": (
        "the purchase order quoted on the invoice does not exist",
        "Procurement to confirm the correct purchase order number with the vendor."),
    "PO_VENDOR_CONFLICT": (
        "the purchase order quoted belongs to a different vendor",
        "Check which purchase order this invoice is really for."),
    "PO_IMPLIED": (
        "the invoice quotes no purchase order, so one has been suggested",
        ("Confirm the suggested purchase order, or choose the right one, then approve or "
        "reject.")),
    "PO_NOT_IDENTIFIED": (
        "no purchase order could be found for this invoice",
        "Procurement to say which purchase order covers this invoice, or raise one."),
    "DUPLICATE_EXACT": (
        "this invoice has already been submitted",
        "Do not pay. No action is needed unless the earlier invoice was entered wrongly."),
    "DUPLICATE_PROBABLE": (
        "this looks like an invoice that was already submitted",
        ("Compare with the earlier invoice. Reject if it is the same bill; approve only if it "
        "is a genuinely separate one.")),
    "PO_STATUS": (
        "the purchase order is closed",
        "Procurement to reopen the purchase order or tell the vendor it is closed."),
    "PO_BALANCE": (
        "the invoice takes the purchase order over its value",
        ("Procurement to either increase the purchase order or ask the vendor to bill the "
        "extra separately.")),
    "PRICE_VARIANCE": (
        "unit prices differ from the purchase order",
        "Procurement to confirm the price with the vendor, or ask for a corrected invoice."),
}
FALLBACK_TEMPLATE = ("a check did not pass", "Review the findings listed.")


def _po_balance_headline(finding: Finding) -> str:
    overage = format_inr(Decimal(finding.data["overage"]))
    return f"the invoice takes {finding.data['po_id']} over its value by {overage} before tax"


def _po_implied_headline(finding: Finding) -> str:
    if "suggested_po_id" in finding.data:
        return (f"the invoice quotes no purchase order; {finding.data['suggested_po_id']} is "
                "suggested")
    shortlist = ", ".join(finding.data["shortlist"])
    return f"the invoice quotes no purchase order; it could be any of {shortlist}"


# Headlines that quote a figure or a PO number from the finding's data. These replace the
# fixed phrase in TEMPLATES for that code.
HEADLINES_WITH_FIGURES = {"PO_BALANCE": _po_balance_headline, "PO_IMPLIED": _po_implied_headline}


class Reason(BaseModel):
    code: str
    text: str  # the finding's message, with the real numbers
    severity: str
    status: str
    owner: Owner


class Decision(BaseModel):
    decision: DecisionType
    headline: str
    reasons: list[Reason]  # problems first, then warnings / notes
    owner: Owner  # who owns the next step
    owner_label: str
    next_action: str
    passed: list[str]  # what passed
    not_checked: list[str]  # checks that could not run, with why


def decide(validated: ValidateResult, matched: MatchResult, ruled: RulesResult) -> Decision:
    findings = validated.findings + matched.findings + ruled.findings

    # Problems and notes, most serious first; within that, in pipeline order.
    flagged = [f for f in findings if f.status in ("fail", "warn")]
    flagged.sort(key=lambda f: (SEVERITY_RANK[f.severity], STATUS_RANK[f.status]))
    reasons = [Reason(code=f.code, text=f.message, severity=f.severity, status=f.status,
                      owner=f.owner) for f in flagged]

    blocking = [f for f in flagged if f.severity == "reject"]
    decision: DecisionType = "REJECT"
    if not blocking:
        blocking = [f for f in flagged if f.severity == "review"]
        decision = "REVIEW" if blocking else "APPROVE"

    if decision == "APPROVE":
        owner: Owner = "none"
        headline, next_action = _approval_text(validated, matched, notes=len(flagged))
    else:
        main = blocking[0]  # the first, most serious problem leads
        owner = main.owner
        phrase, next_action = TEMPLATES.get(main.code, FALLBACK_TEMPLATE)
        if main.code in HEADLINES_WITH_FIGURES:
            phrase = HEADLINES_WITH_FIGURES[main.code](main)
        prefix = "Rejected" if decision == "REJECT" else "Needs review"
        others = len([f for f in flagged if f.severity != "info"]) - 1  # other problems
        more = f" (and {others} more issue{'s' if others > 1 else ''})" if others else ""
        headline = f"{prefix}: {phrase}{more}."

    return Decision(
        decision=decision, headline=headline, reasons=reasons, owner=owner,
        owner_label=OWNER_LABELS[owner], next_action=next_action,
        passed=[f.message for f in findings if f.status == "pass"],
        not_checked=[f"{f.code}: {f.message.removeprefix('Not checked: ')}"
                     for f in findings if f.status == "skipped"],
    )


def _approval_text(validated: ValidateResult, matched: MatchResult, notes: int) -> tuple[str, str]:
    po = matched.po
    pretax = validated.pretax_amount
    if po is None or pretax is None:  # cannot happen for an approval; kept for type safety
        return "Approved.", "Schedule the invoice for payment."
    if notes:
        headline = (f"Approved with {notes} note{'s' if notes > 1 else ''}: the invoice matches "
                    f"{po.po_id}; nothing found needs a person.")
    else:
        headline = f"Approved: the invoice matches {po.po_id} and every check passed."
    payable = (f" of {format_inr(validated.gross_amount)} including tax"
               if validated.gross_amount else "")
    position = po_position(po.po_id, po.value, po.billed_to_date + pretax, now=True)
    next_action = f"Schedule payment{payable}. {position}."
    return headline, next_action
