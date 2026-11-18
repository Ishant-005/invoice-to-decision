# Progress

Status of every feature, kept honest (SPEC section 8).

- **implemented**: the code exists.
- **tested**: an automated test passes.
- **verified**: seen working end to end by actually running it.

A feature not listed here has not been started.

## Milestone 0: Repo and scaffold

| Feature | Status | Evidence |
|---|---|---|
| Backend health endpoint `GET /api/health` | tested + verified | `backend/tests/test_health.py` passes; `curl localhost:8000/api/health` returned `{"status":"ok"}` |
| Frontend placeholder home page | verified | `npm run build` succeeds; page served on port 5173 |
| Frontend reaches backend through the dev proxy | verified | `curl localhost:5173/api/health` returned `{"status":"ok"}` while `make dev` was running |
| `make dev` runs both servers | verified | Both ports answered from one `make dev` |
| `make test` | verified | 1 backend test passed, frontend build succeeded |
| CI workflow (backend tests + frontend build) | verified | GitHub Actions run 44320105493 passed on `main` (first run failed on a wrong action version tag; fixed) |
| Process map | implemented | `docs/PROCESS_MAP.md`. The Mermaid diagram has not been rendered by the implementer; check it displays on GitHub |

The placeholder page's appearance in a real browser has not been checked by the implementer;
only that it builds and is served.

## Milestone 1: Data and test invoices

| Feature | Status | Evidence |
|---|---|---|
| Database models (vendor, PO, PO line, invoice, run, stage event, saved extraction) | tested | `backend/tests/test_seed.py` |
| Money stored exactly (Decimal as text) | tested + verified | Test reads `72800.00` back as `Decimal`; `sqlite3` shows the column type is text |
| Seed CSVs and seeded history load as SPEC section 4 | tested + verified | `test_seed.py`; `make seed` printed 5 vendors, 10 POs, 2 seeded invoices with the spec's balances |
| Reset (wipes runs, restores balances, keeps saved extractions) | tested + verified | `test_seed.py`, `test_demo_api.py`; on a live server a tampered PO balance went back to 0 after `POST /api/demo/reset` |
| Auto-seed on startup when the database is empty | verified | Deleted `var/app.db`, started the server, found 5 vendors. `seed_if_empty` itself is tested |
| `scripts/generate_invoices.py`: 13 test PDFs + 2 seeded PDFs, four layouts | verified | Every PDF rendered to an image and looked at by the implementer |
| Generator is deterministic | verified | Two runs produced byte-identical files (same SHA-256 for all 15) |
| Every figure recomputed; spec section 4 arithmetic is consistent | tested + verified | `make check-invoices` prints "ALL CHECKS PASSED"; `test_invoice_files.py` |
| Scans (cases 3, 8, 10) have no text layer | tested + verified | `make check-invoices`: 0 text characters, 0 text objects, 1 image each; no `/Font` in the files |
| Case 10: invoice number blank, total unreadable | verified | Looked at the image; the generator asserts the blot covers every pixel of the total |
| `data/invoices/expected.json` answer key (13 cases + 3 sequences) | tested | `test_invoice_files.py`. The expected decisions are proven by the decision logic in Milestone 2 |

Not checked: the PDFs have only been rendered with pdfium (the same engine Chrome uses), not
opened in Preview or Acrobat by the implementer. The digital PDFs' fonts come from macOS, so
`make invoices` on another operating system would produce different-looking files.

## Milestone 2: Decision logic

No AI model, no API and no web code is involved in anything below. "Verified" here means the
implementer ran `make decisions` and read the printed decisions; nothing has been seen in the
web app yet, because the stages are not wired into it until Milestone 4.

| Feature | Status | Evidence |
|---|---|---|
| Findings structure (code, stage, status, severity, message, owner, data) | tested | `app/pipeline/findings.py`; used by every test below |
| Thresholds read from `config/rules.yaml` | tested | Boundary tests in `tests/unit/test_rules.py` and `test_validate.py` run against the file's values |
| Validate: 7 checks + tax normalisation | tested | `tests/unit/test_validate.py` (rounding at ₹1, tax-inclusive derivation, dates, currency) |
| Match: vendor (tax ID, cleaned name, suggested, not found, blocked, tax ID conflict) | tested | `tests/unit/test_match.py` |
| Match: PO (explicit verified / conflict / not found; implied single / multiple / none) | tested | `tests/unit/test_match.py` |
| Match: line pairing, `LINE_NOT_ON_PO` | tested | `tests/unit/test_match.py` |
| Rules: exact and probable duplicates, monthly non-duplicate, rejected invoices ignored | tested | `tests/unit/test_rules.py` |
| Rules: PO balance with tolerance (exactly 2%, exactly ₹5,000), PO status, price variance | tested | `tests/unit/test_rules.py` |
| Decide: worst severity wins, reasons ordered, owner, next action, what passed | tested | `tests/unit/test_decide.py` |
| Answer key: all 13 cases reach the expected decision, owner, vendor, PO, match type, pre-tax amount and finding codes | tested + verified | `tests/test_answer_key.py` (13 passed); `make decisions` output read |
| Answer key: the 3 sequences | tested | `tests/test_answer_key.py` (3 passed) |
| Decision wording: "what passed" list, before/including tax labels, PO position, single overage limit, "would fit without" sentence, duplicate sentences, implied-PO evidence | tested | Exact-sentence assertions in `tests/unit/` (including the case where removing the unlisted line does not make the invoice fit) |
| Decision wording for the 13 cases | verified | `make decisions CASES="..."` read by the implementer. Wording for situations outside the 13 cases (blocked vendor, closed PO, several candidate POs and so on) is covered by tests for its codes but has not been read through |

Not done in this milestone, by design: nothing writes a decision to the database or updates a
PO balance yet (Milestone 4). The answer-key test applies outcomes in memory to test sequences.

## Milestone 3: Extraction

Results below are from real runs against `claude-sonnet-5-5` on 2026-11-18. The reports are
written by the scripts, not by hand: `docs/EXTRACTION_EVAL.md` and `docs/E2E_CHECK.md`.

| Feature | Status | Evidence |
|---|---|---|
| Receive: PDF only, 10 MB, 5 pages, clear errors | tested | `tests/unit/test_receive.py` (not a PDF, empty, damaged, too large, too many pages) |
| Receive: SHA-256 hash, page images with pypdfium2 | tested + verified | Test checks the hash and that a PNG is written; a real run wrote `1.png` for case 10 |
| Receive: notes a file seen before (earlier run or seeded history) | tested + verified | Tests; in `make e2e` the second submission of case 1 was recognised |
| Extract: live call, PDF in, schema-constrained record out | verified | `make eval`: all 15 PDFs returned a valid record, 3 to 5 seconds each |
| Extract: prompt keeps the FIXED requirements | tested | `test_the_prompt_keeps_the_fixed_requirements` |
| Extract: amounts are exact `Decimal`, never float | tested | `tests/unit/test_extract.py` |
| Extraction accuracy | verified | `make eval`: 294 of 294 values correct. The first run scored 291 of 294; the 3 misses were an answer-key error (vendor name printed in capitals), corrected in the key, not the prompt. Both runs are in the report |
| Case 10: invoice_number and total come back null | verified | Null in all 5 live readings made today (2 eval runs, the e2e check, 2 manual runs). The model's note names the ink blot and the blank field |
| Saved extractions keyed by file hash | tested + verified | Tests; real run saved then served the reading |
| Identical file reuses the saved reading ("reused: identical file") | tested + verified | Tests; `make e2e` sequence `same_file_twice` |
| Fallback: saved result when the live call fails, clearly labelled | tested + verified | Tests; real runs with an invalid API key and with an unreachable address both returned "served from saved result (live call failed)" plus the reason |
| No saved result and live call fails: the run fails with a readable message | tested + verified | Same real runs, on a file with nothing saved |
| `EXTRACTION_CACHE_MODE=off` never uses a saved result | tested + verified | Tests; real run failed as it should |
| Daily cap `MAX_LIVE_EXTRACTIONS_PER_DAY` | tested + verified | Tests; real run with the cap reached returned the saved result, and a clear error for a file with nothing saved |
| Retry: 60 s timeout, 2 retries with backoff | implemented | Configured on the SDK client. Not observed: no real timeout or server error was provoked. The unreachable-address run did go through the retries before falling back |
| `make eval` and `docs/EXTRACTION_EVAL.md` | verified | Run twice; report read |
| End-to-end: live extraction into the decision logic | verified | `make e2e`: 13 of 13 cases and 3 of 3 sequences match the answer key (`docs/E2E_CHECK.md`) |

API usage for this milestone, from the token counts the API returned: two eval runs
(US $0.22 each), one end-to-end run (US $0.26) and a handful of single test calls: about
US $0.75 in total.

Not done in this milestone, by design: nothing calls Receive or Extract over HTTP yet, and no
run or stage event is written to the database (Milestone 4). Structured logs with the run ID
also belong there.

Limits to be honest about: 15 synthetic invoices is a small, clean sample, so "294 of 294"
says the reading works on these layouts, not that it is 100% accurate in general. The model
has no temperature setting, so a future run could differ; today's separate passes agreed.

## Known issues

- pytest prints one deprecation warning from Starlette's test client (it suggests the `httpx2`
  package instead of `httpx`). Harmless; tests pass.

## Milestones 4 to 7

Not started.
