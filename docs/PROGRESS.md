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

## Milestone 4: Pipeline and API

"Tested" means the API integration tests in `backend/tests/integration/` (the real app and
pipeline on a temporary database; only the AI call is replaced by a stand-in that returns the
answer key's ground truth). "Verified" means done with `curl` against a running server with
the live model on 2026-11-18.

| Feature | Status | Evidence |
|---|---|---|
| `POST /api/runs` (sample or upload) answers at once with a run ID; the pipeline runs in the background | tested + verified | `test_a_run_is_accepted_at_once_and_can_be_polled_to_completion`; live: `202` then 7 polls at 0.7 s until `completed` |
| A stage row is written when a stage starts and filled in when it finishes | tested + verified | `test_stage_rows_are_written_while_the_run_is_in_progress`; live polls showed Receive `done` and Extract `running` while the model was reading |
| Real measured durations, no delays | tested + verified | Live sample 1: receive 27.9 ms, extract 4,236.2 ms, validate 0.2, match 2.1, rules 2.0, decide 0.8. Sample 5: 24.8 / 3,906.2 / 0.3 / 2.2 / 2.3 / 0.4 |
| `GET /api/runs/{id}`: run, six stages, findings per stage, decision | tested + verified | Tests; JSON of both live runs read |
| All 13 samples reach the expected decision over HTTP | tested | `test_every_sample_reaches_its_expected_decision_over_http` (extraction stood in). Live over HTTP: samples 1 and 5 only |
| APPROVE adds the pre-tax amount to the PO in the same commit; REVIEW and REJECT do not | tested + verified | Tests; live: PO-2231 billed 0 to 1,80,000 after sample 1; PO-2260 unchanged after sample 5 |
| The three sequences | tested | `test_sequence_from_the_answer_key` and two more detailed tests. Live: only "same file twice" (second run REJECT, "reused: identical file", no AI call) |
| Human review: approve / reject with a required comment, once only; chosen PO must be the vendor's | tested + verified | 7 tests; live: sample 5 approved with a comment, PO-2260 billed 1,00,000 to 3,40,000; blank comment refused with 422 |
| A run fails cleanly when extraction raises an error | tested | `test_a_run_fails_cleanly_when_extraction_raises_an_error`, `test_an_unexpected_error_fails_the_run_without_leaking_details`. Not provoked on the live server in this milestone (the Extract stage's own failure paths were verified live in Milestone 3) |
| A file that is not a PDF fails in Receive with a clear message; oversize upload refused | tested + verified | Tests; live: a text file gave a failed run, "Only PDF files are accepted". The 413 path is tested only |
| Reset restores the seed state, also during a run | tested + verified | `test_reset_restores_the_seed_state`, `test_a_reset_during_a_run_abandons_it_without_touching_the_books`; live: after reset no runs, balances back. The mid-run reset is tested only |
| Auto-seed on startup with an empty database | verified | Server started with no `var/app.db`; POs and seeded history were there |
| Runs interrupted by a restart are marked failed on startup | tested | `test_runs_left_unfinished_by_a_stopped_server_are_marked_failed_on_startup` |
| `GET /api/runs` with filters, `/samples`, `/purchase-orders`, `/purchase-orders/{id}`, `/vendors`, `/stats`, `/config/rules`, page images | tested + verified | `test_reference_api.py`; live: runs list, PO detail, stats and a page image (PNG, 200) fetched. `/samples`, `/vendors` and `/config/rules` are tested only |
| Money is text in every response | tested | `test_money_is_sent_as_text_never_as_a_floating_point_number` |
| Logs carry the run ID on every line | verified | Server log read: `run=<id> stage=extract status=done duration_ms=3906.2` |

Live API usage for this milestone: 2 extraction calls (5,509 + 476 and 5,535 + 402 tokens).

Limits to be honest about:

- Two runs at exactly the same time have not been tested. The lock that keeps them from
  both using one PO balance is simple, but there is no automated test that races two runs.
- The app must run as a single process (one lock, background tasks in-process).
- There are no database migrations; a database from before this milestone must be deleted.
- Nothing has been seen in a browser yet. That is Milestone 5.

## Known issues

- None open. (The Starlette test-client deprecation warning noted earlier no longer appears: 290 tests pass with no warnings.)

## Milestones 5 to 7

Not started.
