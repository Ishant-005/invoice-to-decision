"""Stage 1, Receive: accept the file, check it, fingerprint it, and make page images.

No AI model here. The stage answers three questions:
  1. Is this a PDF we are willing to process (type, size, page count)?
  2. What is its fingerprint (SHA-256)? Two files with the same fingerprint are the same file.
  3. Have we seen this exact file before?
"""

import hashlib
from pathlib import Path

import pypdfium2 as pdfium
from pydantic import BaseModel
from sqlmodel import Session, select

from app import config
from app.models import Invoice, Run

RENDER_SCALE = 2  # 2 = 144 dots per inch: sharp enough to read in the page preview


class ReceiveError(Exception):
    """The file cannot be processed. The message is written for the person who uploaded it."""


class ReceiveResult(BaseModel):
    file_name: str
    file_hash: str  # SHA-256 of the file's bytes
    size_bytes: int
    page_count: int
    page_images: list[str]  # paths of the PNG files, in page order
    seen_before: bool  # an earlier run, or the seeded history, has this exact file
    note: str | None = None


def receive(pdf_bytes: bytes, file_name: str, session: Session,
            current_run_id: str | None = None,
            pages_dir: Path | None = None) -> ReceiveResult:
    """Check the file and prepare it for the next stages. Raises ReceiveError if it is not
    a PDF, is too large, has too many pages, or cannot be opened."""
    pages_dir = pages_dir or config.PAGES_DIR

    if len(pdf_bytes) == 0:
        raise ReceiveError("The file is empty.")
    if len(pdf_bytes) > config.MAX_UPLOAD_BYTES:
        raise ReceiveError(
            f"The file is {len(pdf_bytes) / (1024 * 1024):.1f} MB. "
            f"The limit is {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    # Every PDF starts with the characters "%PDF-". Checking the content, not the file
    # name, means a renamed image or spreadsheet is still turned away.
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ReceiveError("Only PDF files are accepted. This file is not a PDF.")

    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except pdfium.PdfiumError as error:
        raise ReceiveError(
            "The PDF could not be opened. It may be damaged or password-protected.") from error

    try:
        page_count = len(pdf)
        if page_count == 0:
            raise ReceiveError("The PDF has no pages.")
        if page_count > config.MAX_PAGES:
            raise ReceiveError(
                f"The PDF has {page_count} pages. The limit is {config.MAX_PAGES}.")

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        page_images = render_pages(pdf, pages_dir / file_hash)
    finally:
        pdf.close()

    seen_before = file_seen_before(session, file_hash, current_run_id)
    return ReceiveResult(
        file_name=file_name, file_hash=file_hash, size_bytes=len(pdf_bytes),
        page_count=page_count, page_images=page_images, seen_before=seen_before,
        note="This exact file has been submitted before." if seen_before else None)


def render_pages(pdf: pdfium.PdfDocument, folder: Path) -> list[str]:
    """Save each page as folder/1.png, folder/2.png, ... and return the paths.

    The folder is named after the file's hash, so the same file always lands in the same
    place and its pages are simply written again."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(len(pdf)):
        image = pdf[index].render(scale=RENDER_SCALE).to_pil()
        path = folder / f"{index + 1}.png"
        image.save(path, format="PNG")
        paths.append(str(path))
    return paths


def file_seen_before(session: Session, file_hash: str, current_run_id: str | None) -> bool:
    """True if an earlier run, or an invoice in the history, has the same file hash.

    `current_run_id` is the run being processed now; it must not count as "earlier"."""
    earlier_run = session.exec(
        select(Run).where(Run.file_hash == file_hash, Run.id != (current_run_id or ""))
    ).first()
    in_history = session.exec(select(Invoice).where(Invoice.file_hash == file_hash)).first()
    return earlier_run is not None or in_history is not None
