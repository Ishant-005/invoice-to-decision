"""Receive stage: file checks, hashing, page images, and "seen this file before"."""

import hashlib
from pathlib import Path

import pytest

from app import config
from app.models import Run
from app.pipeline.receive import ReceiveError, receive
from app.seed import seed_database

SAMPLE = config.INVOICE_DIR / "acme_2026-11-05.pdf"


def test_accepts_a_sample_invoice_and_renders_its_page(session, tmp_path):
    pdf = SAMPLE.read_bytes()
    result = receive(pdf, SAMPLE.name, session, pages_dir=tmp_path)

    assert result.file_hash == hashlib.sha256(pdf).hexdigest()
    assert result.size_bytes == len(pdf)
    assert result.page_count == 1
    assert result.seen_before is False
    assert result.page_images == [str(tmp_path / result.file_hash / "1.png")]
    assert Path(result.page_images[0]).read_bytes().startswith(b"\x89PNG")


def test_rejects_a_file_that_is_not_a_pdf(session, tmp_path):
    with pytest.raises(ReceiveError, match="Only PDF files"):
        receive(b"PK\x03\x04 this is a spreadsheet", "invoice.pdf", session, pages_dir=tmp_path)


def test_rejects_an_empty_file(session, tmp_path):
    with pytest.raises(ReceiveError, match="empty"):
        receive(b"", "invoice.pdf", session, pages_dir=tmp_path)


def test_rejects_a_damaged_pdf(session, tmp_path):
    with pytest.raises(ReceiveError, match="could not be opened"):
        receive(b"%PDF-1.7 not really a pdf", "invoice.pdf", session, pages_dir=tmp_path)


def test_rejects_a_file_over_the_size_limit(session, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1024)
    with pytest.raises(ReceiveError, match="limit is"):
        receive(SAMPLE.read_bytes(), SAMPLE.name, session, pages_dir=tmp_path)


def test_size_limit_is_ten_megabytes_and_page_limit_is_five():
    assert config.MAX_UPLOAD_BYTES == 10 * 1024 * 1024
    assert config.MAX_PAGES == 5


def test_rejects_a_pdf_with_too_many_pages(session, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_PAGES", 0)  # the sample has one page
    with pytest.raises(ReceiveError, match="1 pages. The limit is 0"):
        receive(SAMPLE.read_bytes(), SAMPLE.name, session, pages_dir=tmp_path)


def test_notes_a_file_that_an_earlier_run_already_submitted(session, tmp_path):
    pdf = SAMPLE.read_bytes()
    earlier = Run(file_name=SAMPLE.name, file_hash=hashlib.sha256(pdf).hexdigest())
    session.add(earlier)
    session.commit()

    assert receive(pdf, SAMPLE.name, session, pages_dir=tmp_path).seen_before is True
    # The run being processed right now does not count as an earlier one.
    current = receive(pdf, SAMPLE.name, session, current_run_id=earlier.id, pages_dir=tmp_path)
    assert current.seen_before is False


def test_a_seeded_history_file_counts_as_seen_before(session, tmp_path):
    seed_database(session)
    seeded = config.SEED_DIR / "seed_acme_inv1017.pdf"
    assert receive(seeded.read_bytes(), seeded.name, session, pages_dir=tmp_path).seen_before
