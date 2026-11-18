"""Extract stage with the AI call replaced by a stand-in. No API key or network needed.

The live model's accuracy is measured separately by `make eval`."""

from decimal import Decimal
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from anthropic import transform_schema
from pydantic import ValidationError
from sqlmodel import select

from app.models import LiveCallCount, SavedExtraction
from app.pipeline.extract import (
    ExtractionError,
    ModelReading,
    ReadInvoice,
    extract,
    read_with_model,
    to_invoice_record,
)
from app.pipeline.receive import ReceiveResult
from app.pipeline.record import InvoiceRecord

FILE_HASH = "a" * 64


def received(seen_before: bool = False) -> ReceiveResult:
    return ReceiveResult(file_name="x.pdf", file_hash=FILE_HASH, size_bytes=10, page_count=1,
                         page_images=[], seen_before=seen_before)


def record(total: str = "118000.00") -> InvoiceRecord:
    return InvoiceRecord(document_type="invoice", invoice_number="INV-1", total=Decimal(total))


class FakeReader:
    """Stands in for the live call: returns a fixed record, or fails, and counts its calls."""

    def __init__(self, result: InvoiceRecord | None = None, error: str | None = None):
        self.result, self.error, self.calls = result, error, 0

    def __call__(self, pdf_bytes: bytes) -> ModelReading:
        self.calls += 1
        if self.error:
            raise ExtractionError(self.error)
        return ModelReading(record=self.result, model="fake", input_tokens=1, output_tokens=1)


def save(session, total: str = "999.00") -> None:
    session.add(SavedExtraction(file_hash=FILE_HASH, file_name="x.pdf", source="live",
                                record=record(total).model_dump(mode="json")))
    session.commit()


@pytest.fixture(autouse=True)
def default_settings(monkeypatch):
    monkeypatch.setenv("EXTRACTION_CACHE_MODE", "fallback")
    monkeypatch.setenv("MAX_LIVE_EXTRACTIONS_PER_DAY", "150")


# --- live call succeeds ---


def test_live_reading_is_returned_saved_and_counted(session):
    reader = FakeReader(record())
    result = extract(b"pdf", received(), session, reader)

    assert result.source == "live" and result.label == "read live by the AI model"
    assert result.record.total == Decimal("118000.00")
    saved = session.get(SavedExtraction, FILE_HASH)
    assert saved.record["total"] == "118000.00"  # stored as exact text, not a float
    assert [row.calls for row in session.exec(select(LiveCallCount))] == [1]


def test_fallback_mode_still_calls_live_when_a_saved_result_exists(session):
    save(session, total="999.00")
    reader = FakeReader(record("118000.00"))
    result = extract(b"pdf", received(), session, reader)

    assert reader.calls == 1 and result.source == "live"
    assert session.get(SavedExtraction, FILE_HASH).record["total"] == "118000.00"  # replaced


# --- live call fails ---


def test_live_failure_with_a_saved_result_uses_it_and_says_so(session):
    save(session)
    result = extract(b"pdf", received(), session, FakeReader(error="could not be reached"))

    assert result.source == "saved_live_failed"
    assert result.label == "served from saved result (live call failed)"
    assert result.live_error == "could not be reached"
    assert result.record.total == Decimal("999.00")
    assert result.saved_at is not None


def test_live_failure_without_a_saved_result_fails(session):
    with pytest.raises(ExtractionError, match="could not be reached"):
        extract(b"pdf", received(), session, FakeReader(error="could not be reached"))


def test_cache_mode_off_never_uses_a_saved_result(session, monkeypatch):
    monkeypatch.setenv("EXTRACTION_CACHE_MODE", "off")
    save(session)
    with pytest.raises(ExtractionError):
        extract(b"pdf", received(seen_before=True), session, FakeReader(error="down"))


# --- identical file ---


def test_identical_file_reuses_the_saved_result_without_a_live_call(session):
    save(session)
    reader = FakeReader(record())
    result = extract(b"pdf", received(seen_before=True), session, reader)

    assert reader.calls == 0
    assert result.source == "reused_identical_file"
    assert result.label == "reused: identical file"
    assert result.record.total == Decimal("999.00")


def test_identical_file_with_nothing_saved_is_read_live(session):
    reader = FakeReader(record())
    assert extract(b"pdf", received(seen_before=True), session, reader).source == "live"


# --- daily cap ---


def test_daily_cap_blocks_live_calls_and_uses_saved_result(session, monkeypatch):
    monkeypatch.setenv("MAX_LIVE_EXTRACTIONS_PER_DAY", "1")
    reader = FakeReader(record())
    assert extract(b"pdf", received(), session, reader).source == "live"  # call 1 of 1

    result = extract(b"pdf", received(), session, reader)  # over the cap; saved by call 1
    assert reader.calls == 1
    assert result.source == "saved_daily_cap" and "daily limit" in result.label


def test_daily_cap_without_a_saved_result_fails_clearly(session, monkeypatch):
    monkeypatch.setenv("MAX_LIVE_EXTRACTIONS_PER_DAY", "0")
    reader = FakeReader(record())
    with pytest.raises(ExtractionError, match="limit of 0 live AI readings"):
        extract(b"pdf", received(), session, reader)
    assert reader.calls == 0


def test_a_failed_live_call_still_counts_towards_the_cap(session):
    with pytest.raises(ExtractionError):
        extract(b"pdf", received(), session, FakeReader(error="down"))
    assert [row.calls for row in session.exec(select(LiveCallCount))] == [1]


# --- the reply format ---

READ = {
    "document_type": "invoice", "vendor_name": "Acme", "vendor_tax_id": None,
    "invoice_number": None, "invoice_date": "2026-11-05", "date_is_ambiguous": False,
    "po_reference": "PO-2231", "currency": "INR",
    "line_items": [{"description": "Box", "quantity": "500", "unit_price": "180.00",
                    "amount": "90000.00"}],
    "subtotal": "90000.00", "tax_amount": "16200.00", "tax_rate_percent": "18",
    "amounts_tax_inclusive": False, "total": None,
    "evidence": {"vendor_name": "Acme", "invoice_number": "", "invoice_date": "5 Nov 2026",
                 "po_reference": "PO-2231", "total": " "},
    "notes": None,
}


def test_reply_becomes_a_record_with_exact_decimals_and_null_evidence():
    result = to_invoice_record(ReadInvoice.model_validate(READ))
    assert result.subtotal == Decimal("90000.00") and str(result.subtotal) == "90000.00"
    assert result.line_items[0].unit_price == Decimal("180.00")
    assert result.invoice_number is None and result.total is None
    assert result.evidence["invoice_number"] is None and result.evidence["total"] is None
    assert result.evidence["po_reference"] == "PO-2231"


@pytest.mark.parametrize("bad", ["1,06,200.00", "₹106200", "106200.", "about 100"])
def test_an_amount_that_is_not_a_plain_decimal_is_rejected(bad):
    with pytest.raises(ValidationError):
        ReadInvoice.model_validate({**READ, "subtotal": bad})


def test_every_field_must_be_stated_even_if_null():
    reply = {key: value for key, value in READ.items() if key != "total"}
    with pytest.raises(ValidationError):
        ReadInvoice.model_validate(reply)


def test_schema_stays_inside_the_documented_structured_output_limits():
    """Anthropic's limits: at most 16 fields that can be 'this or null', at most 24 optional."""
    schema = transform_schema(ReadInvoice)
    objects = [schema, *schema["$defs"].values()]
    nullable = sum("anyOf" in prop for obj in objects for prop in obj["properties"].values())
    optional = sum(len(obj["properties"]) - len(obj["required"]) for obj in objects)
    assert nullable <= 16
    assert optional == 0


# --- one live call, with the SDK client replaced ---


class FakeClient:
    def __init__(self, response=None, error: Exception | None = None):
        self.messages = SimpleNamespace(parse=self.parse)
        self.response, self.error, self.request = response, error, None

    def parse(self, **request):
        self.request = request
        if self.error:
            raise self.error
        return self.response


def response(stop_reason: str = "end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, model="claude-test",
                           parsed_output=ReadInvoice.model_validate(READ),
                           usage=SimpleNamespace(input_tokens=5000, output_tokens=400))


def test_live_call_sends_the_pdf_before_the_instruction_and_returns_the_record():
    client = FakeClient(response())
    reading = read_with_model(b"%PDF-fake", client)

    content = client.request["messages"][0]["content"]
    assert [block["type"] for block in content] == ["document", "text"]
    assert content[0]["source"]["media_type"] == "application/pdf"
    assert client.request["output_format"] is ReadInvoice
    assert "temperature" not in client.request  # this model rejects it; see ASSUMPTIONS.md
    assert reading.record.subtotal == Decimal("90000.00")
    assert (reading.input_tokens, reading.output_tokens) == (5000, 400)


@pytest.mark.parametrize("stop_reason, message", [
    ("refusal", "declined"), ("max_tokens", "cut off")])
def test_an_unfinished_reply_is_an_error_not_a_record(stop_reason, message):
    with pytest.raises(ExtractionError, match=message):
        read_with_model(b"%PDF-fake", FakeClient(response(stop_reason)))


def test_a_network_failure_becomes_a_readable_error():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APIConnectionError(request=request)
    with pytest.raises(ExtractionError, match="could not be reached"):
        read_with_model(b"%PDF-fake", FakeClient(error=error))


def test_the_prompt_keeps_the_fixed_requirements():
    from app.pipeline.extract import SYSTEM_PROMPT
    for phrase in ("Report only what is printed", "return null", "Never infer, compute",
                   "do not work out a total", "probably meant", "1,06,200.00"):
        assert phrase in SYSTEM_PROMPT
