# Assumptions

Choices made where the spec is silent, one line each. Decisions the spec marks FIXED are not
repeated here.

## Milestone 0

- uv was not installed, so it was installed with Homebrew (`brew install uv`).
- In development the frontend runs on port 5173 and the backend on port 8000; Vite forwards `/api` requests to the backend, so the browser only ever talks to one address.
- All backend routes live under `/api`, leaving `/` free for the built frontend later.
- Frontend uses whatever `npm create vite@latest` and `shadcn@latest init` currently produce: Tailwind v4 (no `tailwind.config.js`), shadcn "nova" preset on Radix, oxlint as the linter.
- `make test` runs the backend tests and a frontend type-check + build; the frontend has no unit tests of its own yet.
- Makefile targets `seed`, `invoices` and `eval` are added in the milestone that builds them, rather than existing as empty stubs now.
- CI uses Python 3.12 and Node 24 (the versions used locally).
- Runtime files (database, uploads, page images) will live in a git-ignored `var/` folder.

## Milestone 1

- Money is stored in SQLite as text (`"100000.00"`) and read back as `Decimal`, because SQLite's own numeric type goes through floating point.
- Vendor GSTINs are made up but well-formed, including a correct check character; the PAN part uses obvious placeholders such as `AAACA0001A`.
- `vendors.csv` holds only what a real vendor sheet would (ID, name, GSTIN, status, city, state). Which PDF layout a vendor uses is test-data detail and lives in `scripts/invoice_definitions.json`.
- PO dates run in PO-number order from 2026-08-05 to 2026-10-15, each before its first invoice.
- The generator's one data file is `scripts/invoice_definitions.json`. `data/invoices/expected.json` and `data/seed/seed_invoices.json` are written from it, so the PDFs and the answer key cannot drift apart.
- The two seeded-history PDFs live in `data/seed/`, not `data/invoices/`, so the samples folder holds exactly the 13 test invoices.
- The seeded invoices' stored "extraction" is the ground truth they were printed from, labelled `seed_file` (it is not a model reading).
- Regenerating the PDFs gives byte-identical files (fixed random seed, fixed PDF timestamps), so their SHA-256 hashes are stable. Fonts come from macOS, so this holds on the owner's Mac; the committed PDFs are the canonical set.
- Layouts print dates in four different styles, none of them day/month ambiguous, so `date_is_ambiguous` is false for every case.
- PO references are printed in different styles to exercise normalisation: `PO-2231` (layouts A, D), `PO 2240` (B), `P.O. #2252` (C).
- Layout A prints CGST and SGST and a "Total GST (18%)" row, so the single GST figure in the spec appears on the page.
- Layout B (Brightline) prints description and amount only, no quantity or unit price, as service invoices often do; those fields are null in the answer key.
- Case 2 prints its one bundled line as a description with no amount beside it; the only amount on the page is the tax-inclusive total.
- Case 10's "opaque stain" is an ink blot. The tax row above it stays readable; the generator asserts on every run that no pixel of the total is left uncovered. Layout D prints no amount in words, which would give the total away.
- Case 13's content is two hardware lines totalling 48,380; its PO match type is recorded as `not_found` (the spec names the finding `PO_NOT_FOUND` but not a match type).
- In `expected.json`, `finding_codes` are codes that must appear as a warning or failure and `absent_codes` must not; it is not an exhaustive list of findings. Case 9 has no code because the spec does not name one for an implied PO; it is tested on `po_match_type`.
- The answer key has no `evidence` snippets: the exact wording a reader quotes cannot be fixed in advance, so it is not scored.
- Database tables for runs and stage events exist now (reset has to wipe them) but are minimal; Milestone 4 may add columns. The database is disposable: delete `var/app.db` and it is re-seeded on startup.
- `POST /api/demo/reset` was added now rather than in Milestone 4, since "reset works" is part of this milestone.

## Milestone 2

- The deterministic stages take a `Books` snapshot (vendors, POs, PO lines, earlier invoices) rather than a database session, so they are pure functions; `load_books` is the one place that reads the database.
- "Today" is passed into Validate as a parameter instead of read from the clock, so the same inputs always give the same decision and the tests do not depend on the day they run.
- A finding's `status` and `severity` are independent: a small PO overage is `warn` + `info` (still approves); a suggested PO or suggested vendor is `warn` + `review`; skipped and passed checks are always `info`.
- Each check emits exactly one finding. A check with several parts (TOTALS: lines to subtotal, and subtotal + tax to total) passes when every part that could run passed, and says which part could not be checked.
- Finding codes the spec does not name: `PRETAX_AMOUNT` (tax normalisation succeeded), `VENDOR_MATCH`, `VENDOR_BLOCKED`, `PO_MATCH`, `PO_VENDOR_CONFLICT` (explicit_conflict), `PO_IMPLIED` (implied_single and implied_multiple), `PO_NOT_IDENTIFIED` (no strong candidate).
- Pre-tax amount: a printed subtotal is used even when the total is missing (case 10: pre-tax 2,20,000, gross unknown). The spec's wording is "if subtotal and total are printed"; the missing total is already reported by REQUIRED_FIELDS. The code never fills in a missing total by adding subtotal and tax.
- Pre-tax amount, third route: no subtotal but total and tax amount printed gives `total - tax`. Only when no route works is `TAX_UNRESOLVED` raised.
- A derived pre-tax amount is rounded to the paisa, half up.
- No printed currency is a note (INR assumed), not a failure; a currency other than INR is a review.
- Owners where the spec gives none: DOC_TYPE, AMOUNT_SANITY, TAX_UNRESOLVED and an ambiguous date go to AP; a blocked vendor and a closed PO go to procurement.
- Fuzzy vendor matching uses rapidfuzz `ratio` on the cleaned names. A suggested vendor is still used to look up POs and duplicates so the reviewer sees the full picture; the decision is REVIEW regardless.
- PO reference normalisation keeps letters and digits, then drops a leading "PURCHASE ORDER", "PO" and "NO", so "P.O. #2231" and "2231" both become "2231".
- A quoted PO that exists but whose invoice vendor is unknown is reported as `explicit_conflict`.
- Implied-PO description points are scaled: 40 x (best line similarity / 100). An implied_single PO is still run through the balance, status and price checks so the reviewer sees them; explicit_conflict and implied_multiple are not (there is no single PO to check against).
- Line matching runs when the invoice has at least one line with a description; a line is compared on unit price only if it prints one. Several invoice lines may pair with the same PO line.
- Invoice numbers are compared after upper-casing and removing everything except letters and digits ("INV-1017-A" becomes "INV1017A").
- The same-file (hash) duplicate check also ignores rejected invoices, like the other duplicate checks, so a rejected file can be resubmitted once the cause is fixed.
- When the invoice number or the total is unreadable, the duplicate comparisons that need it are skipped and say so; nothing is guessed.
- A unit price more than 2% below the PO price is flagged as well as one above ("within plus or minus 2%").
- The primary owner is the owner of the first, most serious problem: reject before review, then pipeline order (Validate, Match, Rules; duplicates before balance). The headline names that problem and counts the others.
- The Decide output also carries a "not checked" list (skipped checks and why), besides the reasons and "what passed".
- Recording an outcome (adding to billed-to-date, adding the invoice to history) belongs to Milestone 4. The answer-key test does it in memory in `tests/answer_key.py` so the three sequences can be tested now.
- `make decisions` was added so the decision wording can be read without the web app.
- Wording: every rupee amount is labelled "before tax" or "including tax" where both kinds could appear. Line amounts are labelled "before tax" unless the invoice says its amounts include tax.
- PO_BALANCE states one limit per PO: the lower of 2% of the PO value and ₹5,000 (PO-2275: ₹3,000; PO-2260: ₹5,000). This is the same test as "within 2% AND within ₹5,000", worded as a single figure.
- When an invoice goes over the PO and has lines that are not on the PO, PO_BALANCE works out whether the invoice would fit without those lines and says so only when it would. This is done for small (within-limit) overages as well as large ones, and is skipped if an unlisted line has no amount or the amounts include tax.
- A check describes the PO position as "would have / would be" (nothing is decided yet); the approval's next action says "now has / is now".
- The PO_IMPLIED message states the three pieces of evidence in words (amount against remaining balance, which lines matched, invoice date against PO date), including any that count against the PO. The score appears only in the finding's data, as a whole number.
- Headlines for PO_BALANCE and PO_IMPLIED quote the PO number (and the overage) from the finding's data; all other headlines are fixed phrases per finding code.

## Milestone 3

- **Temperature is not set, although the spec says "Temperature 0".** The API rejects the setting for `claude-sonnet-5-5` (tested on 2026-11-18: HTTP 400 "temperature: Extra inputs are not permitted"; the current SDK no longer has the parameter). Repeatability is instead measured: the eval and the end-to-end check are separate live passes over the same PDFs.
- The model's "effort" is set to `low` (a constant in `extract.py`). Reading a one-page invoice is transcription; at `low` the eval scored 294 of 294 and a reading takes 3 to 5 seconds. Raise it only if an eval shows misses.
- PDF input: the file is sent as a base64 `document` block before the instruction, as the PDF-support documentation recommends. The API gives the model a picture of each page plus any text layer, so scans and digital PDFs use one path.
- Structured output: `client.messages.parse()` with a Pydantic model (`ReadInvoice`), the method the structured-outputs documentation recommends. Every field is required but may be null, so the model must state "null" rather than omit a field, and the schema stays inside the documented limits (at most 16 nullable fields; it has 15). A test guards this.
- The model returns amounts as text made only of digits and a decimal point, which is converted straight to `Decimal`. A reply with a comma or currency sign in an amount is rejected as a failed reading rather than cleaned up.
- Evidence comes back as five fixed fields; an empty string means "no evidence" and is stored as null.
- Retries are the SDK's own: 60-second timeout and 2 retries with exponential backoff on timeouts, connection errors, rate limits and server errors. A wrong API key or a bad request is not retried, because retrying cannot fix it.
- A model refusal or a reply cut off by the token limit counts as a failed reading, never as a record. Anthropic's optional "fall back to another model on refusal" beta is not used: the eval measures one named model, and a failed reading already has a defined path (saved result or a clear error).
- "Seen before" (Receive) means an earlier run, or an invoice in the history including the seeded ones, has the same file hash. When that is true and a saved reading exists, Extract reuses it without a live call ("reused: identical file"). Any other file is always read live in `fallback` mode, even if a saved reading survives from before a reset.
- `EXTRACTION_CACHE_MODE=off` means a saved reading is never used: not for an identical file, not after a failed call, not when the daily cap is reached.
- The daily cap counts live calls attempted (a failed call can still cost money), per UTC day, in a small database table that a reset does not clear. On a host that wipes its disk on restart the count starts again from zero.
- Any failure of the live call (including a rejected API key) falls back to a saved reading if one exists, and the stage result carries the reason in plain English.
- Page images are written to `var/pages/<file hash>/<page number>.png` at 144 dpi. Receive checks the file's first bytes (`%PDF-`), not its name.
- `.env` is loaded with `python-dotenv` in `app/config.py`; variables already set in the environment win, so a hosting service's settings take priority.
- `pillow` moved from a development dependency to a runtime one, because rendering pages to PNG needs it.
- Eval scoring: amounts equal as numbers; text equal after trimming spaces, case-sensitive; lines compared in order. `evidence` and `notes` are not scored.
- The answer key now records vendor names as printed. Layout C prints the name in capitals, so cases 3, 9 and 13 have `SHARMA OFFICE SUPPLIES` and `QUICKFIX HARDWARE CO.` as ground truth. The first eval run showed this as 3 mismatches where the model was right and the key was wrong; the prompt was not changed. Regenerating left all 15 PDFs byte-identical.
- `make eval` writes what the model returned to `data/eval/latest_extractions.json` and a summary of every run to `data/eval/history.json`; both are committed as evidence. Neither the eval nor `make e2e` touches the app database or the daily cap.
- `make e2e` was added for the end-to-end check (SPEC 8, item 4). It uses the real Receive and Extract code with an in-memory database, and the same comparison function as the answer-key test.

## Milestone 4

- One `stage_event` row per stage per run: it is inserted with status `running` when the stage starts and the same row is filled in (status, duration, result, findings) when it finishes. The API always returns six stages in order, showing `waiting` for ones not reached yet and `not_run` for ones a failure prevented.
- Stage durations are measured with a monotonic clock and stored to a tenth of a millisecond, because the deterministic stages take well under 1 ms and "0 ms" would look made up. The Match stage's time includes reading the vendors, POs and invoice history from the database; the Decide stage's time includes recording the outcome.
- The pipeline runs as a FastAPI background task in the same process (no queue, no worker). If the server stops mid-run, that run is marked failed on the next startup with "the server restarted" rather than left spinning.
- One process-wide lock covers everything that reads or changes the books: stages 3 to 6 of a run, a review resolution and a reset. Two invoices can therefore never be checked against the same PO balance at the same moment. The AI call is outside the lock. This relies on the app running as a single process.
- A reset while a run is in progress abandons that run: before every write the run checks its own row still exists, and stops if it does not. Nothing from it reaches the restored books.
- "Today" for the date checks is the date in India (UTC+5:30), read once per run, whatever time zone the server is in.
- `POST /api/runs` takes a multipart form with either `file` (a PDF) or `sample` (a file name from `GET /api/samples`) and answers `202` with the run ID. The 10 MB limit is checked here (`413`, nothing stored). Every other file problem (not a PDF, damaged, too many pages) is found by the Receive stage and shows as a failed run with the reason, so it is visible in the run view like everything else.
- The PDF of each run is stored as `var/uploads/<run id>.pdf`, never under a user-supplied name, and no route serves it. A reset deletes these files. `python-multipart` was added because FastAPI needs it for uploads.
- A failed run's message is the stage's own plain-English error when there is one (bad file, AI service down). For any other exception the user sees the stage and the error type only; the full detail goes to the server log.
- A failed run records no invoice, so it never counts as an "earlier invoice" in duplicate checks.
- Every completed run adds one row to the invoice history with the vendor and PO the Match stage arrived at, in state approved / awaiting_review / rejected. An invoice awaiting review shows against its PO but has not been added to billed-to-date.
- The run keeps what the pipeline decided (`decision` stays REVIEW after a person resolves it); the person's answer is stored separately. The API's `state` field combines the two: processing, approved, awaiting_review, approved_by_reviewer, rejected_by_reviewer, rejected, failed.
- Human review: the comment is required and must not be blank; a run can be resolved once. Approving books the pre-tax amount against the PO the pipeline matched or suggested, or against `po_id` if the reviewer names one, which must exist and belong to the invoice's vendor. If the pre-tax amount is unknown the invoice cannot be approved, only rejected.
- A reviewer may approve an invoice that takes a PO over its value (that judgement is what the review is for); the PO's remaining balance then shows as negative.
- An invoice rejected by a reviewer becomes `rejected`, so a corrected resubmission is not flagged as a duplicate of it.
- Money in API responses is text (`"180000.00"`), never a JSON number. All responses go through Pydantic models to guarantee this. Times are UTC with a trailing `Z`.
- `GET /api/runs` returns the runs (newest first) and, separately, `seeded_history`: the seeded invoices have no run, so they are not mixed into the runs. Filters: `decision`, `status`, `state`, `vendor` (a vendor ID).
- `GET /api/stats` counts only runs made in the app. "Processed" means runs that reached a decision. Approved value is given before tax and including tax, and covers approvals by the pipeline and by a reviewer; an approved invoice with no readable total is left out of the including-tax figure.
- `GET /api/purchase-orders` returns each PO with its lines and invoices, the same shape as the single-PO endpoint, since there are only ten.
- Page images are served by run ID and page number; the file-system paths of the images are not included in any response.
- Logs are one line per event in `key=value` form; every line about a run starts with `run=<id>`.
- Adding columns changed the database layout. There are no migrations: an older `var/app.db` must be deleted (it is re-created and seeded on startup).
