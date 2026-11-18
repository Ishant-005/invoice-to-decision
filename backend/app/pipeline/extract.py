"""Stage 2, Extract: turn the PDF into a structured record. The only stage that uses AI.

The model's job is to READ: copy what is printed into named fields, and say null when
something is not there. It does not check, match or decide anything; that is ordinary code
in the later stages.

Two layers in this file:

  read_with_model()  one live call to the Anthropic API for one PDF
  extract()          the stage: decides between a live call and a saved result, enforces
                     the daily cap, saves every successful reading, and always says
                     where the record came from

API details follow the Anthropic documentation as read on 2026-11-18 ("PDF support" and
"Structured outputs"):
  - The PDF goes in as a base64 `document` block, before the instruction text. The API
    gives the model an image of every page plus any text layer, so digital PDFs and scans
    take the same path and no OCR library is needed.
  - `client.messages.parse(output_format=<Pydantic model>)` constrains the reply to the
    model's JSON schema and validates it.
"""

import base64
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session

from app import config
from app.models import LiveCallCount, SavedExtraction
from app.pipeline.receive import ReceiveResult
from app.pipeline.record import InvoiceRecord

# How hard the model works on each invoice (low | medium | high). Reading a one-page
# invoice is a transcription task, so "low" is the starting point; docs/EXTRACTION_EVAL.md
# records the measured accuracy at this setting.
EXTRACTION_EFFORT = "low"
MAX_OUTPUT_TOKENS = 16000

# Bump this when SYSTEM_PROMPT or the schema below changes, so eval runs can be compared.
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """\
You are the reading step of an accounts-payable process. You are given one vendor document, \
usually an invoice, as a PDF. It may be a clean digital file or a scan that is skewed, \
blurred or stained. Your only job is to transcribe what is printed on it into the fields of \
the output record.

Separate, deterministic code runs after you. It checks the arithmetic, finds the vendor \
and the purchase order, and makes the decision. That code relies on receiving exactly what \
the page says, including when the page is wrong or incomplete. So:

1. Report only what is printed. If a field is absent, left blank, covered, smudged or \
otherwise unreadable, return null for it. Null is a correct and useful answer: it sends \
the invoice to a person. A guessed value is the worst possible answer, because the later \
steps would trust it.

2. Never infer, compute or reconstruct a value. In particular, do not work out a total, \
subtotal or tax amount from other numbers on the page, even when the arithmetic makes the \
missing figure obvious. If a figure is hidden by a stain or blot, it is null. Do not \
correct mistakes either: if the printed total disagrees with the lines, report the printed \
total as it is.

3. invoice_number: only a value actually printed beside its label ("Invoice No.", \
"Bill #", "Ref" and similar). If the label is there but the space beside it is empty, \
return null. Do not substitute another reference such as a PO number, order number or \
tax ID.

4. po_reference: the purchase order reference exactly as printed, for example \
"P.O. #2252" stays "P.O. #2252". Null if none is printed. Do not decide which purchase \
order was probably meant.

5. Amounts are plain decimal strings: digits and an optional decimal point, with no \
currency symbol and no thousands separators. Indian-format numbers are converted, so \
1,06,200.00 becomes "106200.00". Keep the decimal places that are printed.

6. tax_amount is the total tax as printed. If CGST and SGST are printed separately and no \
combined tax figure is printed, tax_amount is their sum; this is the one addition you may \
do. IGST is reported as printed. tax_rate_percent is the overall tax rate if one is stated.

7. amounts_tax_inclusive is true only when the document itself says that its prices or \
total include tax.

8. invoice_date is written as YYYY-MM-DD. Set date_is_ambiguous to true only when the \
date is all digits and you cannot tell which part is the day and which is the month.

9. line_items: one entry per printed item or charge row, in order, including rows such as \
freight. Do not include subtotal, tax or total rows. Within a row, anything not printed \
is null: a service line may have no quantity or unit price, and a description with no \
amount beside it has a null amount.

10. currency is the ISO code when the document shows a currency (for example the rupee \
sign, "Rs" or "INR" all mean "INR"), otherwise null.

11. evidence: for each of the five listed fields, the exact text from the page that you \
read the value from, label included when it helps. Use an empty string when the field \
is null.

12. notes: one or two short sentences on anything unusual that a person reviewing this \
document should know, such as a stain covering a figure, handwriting, or a field left \
blank. Null if there is nothing unusual.
"""

USER_INSTRUCTION = "Read the attached document and fill in the record."


# --- What the model is asked to return -------------------------------------------------
#
# This mirrors InvoiceRecord (record.py) with three deliberate differences:
#   - Amounts are strings of digits and are converted straight to Decimal, so money never
#     passes through a float. A reply with anything else in an amount (a comma, a currency
#     sign) fails the pattern check and the reading is rejected rather than half-trusted.
#   - Every field is required but may be null. The model has to state "null" explicitly;
#     it cannot simply leave a field out.
#   - Evidence is a fixed set of five named fields rather than a free-form dictionary,
#     because the schema must list every key.

DecimalText = Annotated[str, Field(pattern=r"^-?[0-9]+(\.[0-9]+)?$")]


class ReadLineItem(BaseModel):
    description: str | None
    quantity: DecimalText | None
    unit_price: DecimalText | None
    amount: DecimalText | None


class ReadEvidence(BaseModel):
    vendor_name: str
    invoice_number: str
    invoice_date: str
    po_reference: str
    total: str


class ReadInvoice(BaseModel):
    document_type: Literal["invoice", "credit_note", "quotation", "statement", "other"]
    vendor_name: str | None
    vendor_tax_id: str | None = Field(description="Tax ID (GSTIN) of the vendor, as printed")
    invoice_number: str | None
    invoice_date: str | None = Field(description="YYYY-MM-DD")
    date_is_ambiguous: bool
    po_reference: str | None
    currency: str | None
    line_items: list[ReadLineItem]
    subtotal: DecimalText | None = Field(description="Pre-tax amount, if printed")
    tax_amount: DecimalText | None
    tax_rate_percent: DecimalText | None
    amounts_tax_inclusive: bool
    total: DecimalText | None = Field(description="Final payable amount, as printed")
    evidence: ReadEvidence
    notes: str | None


def to_invoice_record(read: ReadInvoice) -> InvoiceRecord:
    """Convert the model's reply into the record the later stages use (amounts as Decimal)."""
    data = read.model_dump()
    data["evidence"] = {field: (text.strip() or None) for field, text in data["evidence"].items()}
    return InvoiceRecord.model_validate(data)


# --- One live call ---------------------------------------------------------------------


class ExtractionError(Exception):
    """The document could not be read. The message is plain English, safe to show."""


class ModelReading(BaseModel):
    record: InvoiceRecord
    model: str
    input_tokens: int
    output_tokens: int


def make_client() -> anthropic.Anthropic:
    """The API key is read from the ANTHROPIC_API_KEY environment variable (server-side
    only). The SDK itself retries timeouts, connection errors, rate limits and server
    errors with exponential backoff, which is exactly the retry rule in the spec."""
    return anthropic.Anthropic(timeout=config.EXTRACTION_TIMEOUT_SECONDS,
                               max_retries=config.EXTRACTION_MAX_RETRIES)


def read_with_model(pdf_bytes: bytes, client: anthropic.Anthropic | None = None) -> ModelReading:
    """Send one PDF to the model and return what it read. Raises ExtractionError on any
    failure, after the SDK's retries are used up."""
    model = config.extraction_model()
    pdf_base64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
    try:
        client = client or make_client()
        response = client.messages.parse(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "document",
                     "source": {"type": "base64", "media_type": "application/pdf",
                                "data": pdf_base64}},
                    {"type": "text", "text": USER_INSTRUCTION},
                ],
            }],
            output_config={"effort": EXTRACTION_EFFORT},
            output_format=ReadInvoice,
        )
    except anthropic.AuthenticationError as error:
        raise ExtractionError("The AI service rejected the API key.") from error
    except anthropic.RateLimitError as error:
        raise ExtractionError("The AI service is rate-limiting requests.") from error
    except anthropic.APITimeoutError as error:
        raise ExtractionError(
            f"The AI service did not answer within {config.EXTRACTION_TIMEOUT_SECONDS:.0f} "
            "seconds.") from error
    except anthropic.APIConnectionError as error:
        raise ExtractionError("The AI service could not be reached.") from error
    except anthropic.APIStatusError as error:
        raise ExtractionError(
            f"The AI service returned an error (HTTP {error.status_code}).") from error
    except anthropic.AnthropicError as error:  # for example: no API key configured
        raise ExtractionError(f"The AI client could not be used: {error}") from error
    except ValidationError as error:
        raise ExtractionError("The AI reply did not fit the expected record.") from error

    # The schema is only guaranteed when the model finished normally.
    if response.stop_reason == "refusal":
        raise ExtractionError("The AI model declined to read this document.")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("The AI reply was cut off before the record was complete.")
    if response.parsed_output is None:
        raise ExtractionError("The AI reply did not contain a record.")

    try:
        record = to_invoice_record(response.parsed_output)
    except ValidationError as error:
        raise ExtractionError("The AI reply did not fit the expected record.") from error
    return ModelReading(record=record, model=response.model,
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens)


# --- The stage -------------------------------------------------------------------------

LABELS = {
    "live": "read live by the AI model",
    "reused_identical_file": "reused: identical file",
    "saved_live_failed": "served from saved result (live call failed)",
    "saved_daily_cap": "served from saved result (daily limit on live AI calls reached)",
}


class ExtractResult(BaseModel):
    record: InvoiceRecord
    source: Literal["live", "reused_identical_file", "saved_live_failed", "saved_daily_cap"]
    label: str  # the plain-English version of `source`, always shown to the user
    model: str | None = None  # set only for a live reading
    input_tokens: int | None = None
    output_tokens: int | None = None
    live_error: str | None = None  # why the live call failed, when a saved result was used
    saved_at: datetime | None = None  # when the saved result was first stored


def extract(pdf_bytes: bytes, received: ReceiveResult, session: Session,
            reader: Callable[[bytes], ModelReading] | None = None) -> ExtractResult:
    """Produce the invoice record for a received file.

    In order:
      1. The exact same file was processed before -> reuse its saved record, no AI call.
      2. Today's limit on live calls is reached   -> saved record if there is one, else fail.
      3. Otherwise call the model live. If that fails after retries -> saved record if
         there is one (clearly labelled), else fail.

    A saved record is only ever used when EXTRACTION_CACHE_MODE is "fallback".
    `reader` exists so tests can stand in for the live call."""
    reader = reader or read_with_model
    saved = None
    if config.extraction_cache_mode() == "fallback":
        saved = session.get(SavedExtraction, received.file_hash)

    if saved is not None and received.seen_before:
        return from_saved(saved, "reused_identical_file")

    if not count_live_call(session):
        limit = config.max_live_extractions_per_day()
        if saved is not None:
            return from_saved(saved, "saved_daily_cap")
        raise ExtractionError(
            f"Today's limit of {limit} live AI readings has been reached, and there is no "
            "saved reading of this file. Please try again tomorrow.")

    try:
        reading = reader(pdf_bytes)
    except ExtractionError as error:
        if saved is not None:
            return from_saved(saved, "saved_live_failed", live_error=str(error))
        raise

    save_extraction(session, received, reading.record)
    return ExtractResult(record=reading.record, source="live", label=LABELS["live"],
                         model=reading.model, input_tokens=reading.input_tokens,
                         output_tokens=reading.output_tokens)


def from_saved(saved: SavedExtraction, source: str, live_error: str | None = None) -> ExtractResult:
    return ExtractResult(record=InvoiceRecord.model_validate(saved.record), source=source,
                         label=LABELS[source], live_error=live_error, saved_at=saved.created_at)


def save_extraction(session: Session, received: ReceiveResult, record: InvoiceRecord) -> None:
    """Store (or replace) the reading for this file hash. mode="json" writes Decimals as
    text such as "106200.00", so they are read back exactly."""
    session.merge(SavedExtraction(file_hash=received.file_hash, file_name=received.file_name,
                                  record=record.model_dump(mode="json"), source="live"))
    session.commit()


def count_live_call(session: Session) -> bool:
    """Add one to today's count of live calls and return True, or return False (without
    counting) if today's limit is already used up. A call is counted when it is attempted,
    whether or not it succeeds, because a failed call can still cost money."""
    today = datetime.now(UTC).date()
    counter = session.get(LiveCallCount, today) or LiveCallCount(day=today, calls=0)
    if counter.calls >= config.max_live_extractions_per_day():
        return False
    counter.calls += 1
    session.add(counter)
    session.commit()
    return True
