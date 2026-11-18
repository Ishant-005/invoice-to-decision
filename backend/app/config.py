"""Where things live on disk. Paths are worked out from this file, so the app runs from anywhere."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SEED_DIR = REPO_ROOT / "data" / "seed"  # the "spreadsheet": vendors, POs, PO lines, history
INVOICE_DIR = REPO_ROOT / "data" / "invoices"  # the 13 sample invoices and the answer key
VAR_DIR = REPO_ROOT / "var"  # runtime files (database, uploads); git-ignored

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{VAR_DIR / 'app.db'}")
