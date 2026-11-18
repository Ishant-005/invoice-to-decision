"""The 13 sample invoices offered in the app. Read from the answer key file, but only the
neutral facts (what the document is), never the expected outcome."""

import json
from pathlib import Path

from pydantic import BaseModel

from app import config


class Sample(BaseModel):
    case: int
    file: str
    description: str  # what the document contains, not what should happen to it
    scanned: bool


def load_samples() -> list[Sample]:
    answer_key = json.loads((config.INVOICE_DIR / "expected.json").read_text(encoding="utf-8"))
    return [Sample(case=entry["case"], file=entry["file"], description=entry["description"],
                   scanned=entry["scanned"]) for entry in answer_key["invoices"]]


def sample_path(file_name: str) -> Path | None:
    """The path of a sample, or None if there is no sample with exactly that name. Looking
    the name up in the list (rather than joining it to a folder) means a request can never
    reach any other file on the server."""
    if any(sample.file == file_name for sample in load_samples()):
        return config.INVOICE_DIR / file_name
    return None
