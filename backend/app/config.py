"""Where things live on disk, and the settings read from the environment.

Paths are worked out from this file, so the app runs from anywhere. Settings come from
environment variables; in development they are read from the `.env` file at the repo root
(which is never committed). `.env.example` lists them all.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

# Reads .env into the environment. Variables that are already set (for example on the
# hosting service) win over the file. A missing file is fine.
load_dotenv(REPO_ROOT / ".env")

SEED_DIR = REPO_ROOT / "data" / "seed"  # the "spreadsheet": vendors, POs, PO lines, history
INVOICE_DIR = REPO_ROOT / "data" / "invoices"  # the 13 sample invoices and the answer key
VAR_DIR = REPO_ROOT / "var"  # runtime files (database, uploads); git-ignored
PAGES_DIR = VAR_DIR / "pages"  # page images, one folder per file hash

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{VAR_DIR / 'app.db'}")

# Receive stage limits (SPEC 3.2).
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PAGES = 5

# Extract stage reliability (SPEC 3.3).
EXTRACTION_TIMEOUT_SECONDS = 60.0
EXTRACTION_MAX_RETRIES = 2


# The settings below are functions, not constants, so they are read when used. That lets the
# tests change them, and means a changed .env only needs a server restart.


def extraction_model() -> str:
    return os.environ.get("EXTRACTION_MODEL", "claude-sonnet-5-5")


def extraction_cache_mode() -> str:
    """`fallback`: always call the live API, use a saved result only if that fails.
    `off`: never use a saved result."""
    mode = os.environ.get("EXTRACTION_CACHE_MODE", "fallback").strip().lower()
    if mode not in ("fallback", "off"):
        raise ValueError(f"EXTRACTION_CACHE_MODE must be 'fallback' or 'off', not '{mode}'")
    return mode


def max_live_extractions_per_day() -> int:
    return int(os.environ.get("MAX_LIVE_EXTRACTIONS_PER_DAY", "150"))
