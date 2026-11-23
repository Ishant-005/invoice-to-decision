# Assumptions

Choices made where the spec is silent, one line each. Decisions the spec marks FIXED are not
repeated here.

## Known limits

- Two-way match only: the invoice is compared with the purchase order. There is no goods receipt, so the process cannot confirm that what was billed was delivered.
- Quantities are not tracked cumulatively per purchase order line; over-billing is caught on value, through the PO balance.
- One currency (INR), one tax rate (GST 18%), and invoices of a single page are the focus.
- The 13 sample invoices are synthetic and cleaner than real ones. Reading accuracy on real documents would be lower and needs a real sample to measure.
- There is no sign-in. Anyone with the link can run invoices, resolve reviews and reset the data: this is a demo, not a deployment.
- The app must run as a single process, and its data lives in one SQLite file that a host may wipe on restart (it is re-seeded on startup).

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

## Milestone 5

- Visual direction: a quiet "paper and ink" look. Geist for text, tabular figures for every amount so columns line up, and a mono font only for machine identifiers (check codes, file names, fingerprints). One slate-blue accent; green, amber and red are used only for decisions and check results, always with an icon and a word.
- The base font size is 14 px and the layout is built for 1280 px and wider (the spec's laptop width). It is not designed for phones.
- No data-fetching library: one small hook (`useApi`) fetches a path, and can repeat the call while a condition holds. The run view polls every 700 ms while the run is queued or running; the dashboard polls every 1.5 s only while a run is in progress.
- Live pacing in the run view: when the page has watched a run in progress, each finished stage is revealed 450 ms after the one before, because stages 3 to 6 finish within milliseconds of each other. A stage not yet revealed is shown as "Waiting"; nothing is shown as running unless the server says it is. Durations are always the server's measurements, and the page says so in a note under the timeline. A run opened later as a record is shown at once, with no pacing.
- While a stage is running, the clock beside it counts from the moment the browser first saw it running. It is replaced by the server's measured duration when the stage finishes.
- Amounts stay text in the browser. They are formatted in the Indian style by string handling, and the few sums needed for the balance bar are done in whole paise (BigInt), never floating point. Floating point is used only for the width of a bar.
- The PO balance bar in the Match stage uses the balance as it was when the run was processed (stored with the run), so a record opened later still shows what the decision was based on. The Purchase orders screen shows today's balances.
- Which stages start open: any stage with a problem or a note, Match whenever a PO was found (for the balance bar), Extract when a key field is missing or the reading was not live, Receive when the file was seen before. Everything can be opened or closed by hand.
- The AI reader's free-text note is shown in the Extract stage labelled as the reader's own note; no check or decision uses it.
- Reviewer controls sit in the decision banner beside "Next step". Approve and Reject are the same size and weight, and both stay disabled until a comment is entered. The purchase order selector appears only when the process did not confirm a PO from the invoice; it lists the vendor's purchase orders with the suggested one preselected.
- The sentence under the buttons says what approving would do in this invoice's own figures: the amount booked, the purchase order, and where that leaves it (over its value by how much, fully billed, or how much unbilled), worked out in the browser from the PO's balance today. It adds the double-payment amount for a suspected duplicate and a warning when the total could not be read.
- Three small API additions were needed for the screens: `GET /api/invoices/{id}` (an earlier invoice with its stored reading and page images, for the side-by-side view), `GET /api/invoices/{id}/pages/{n}.png`, and `GET /api/samples/{file}/preview.png` (the first page of a sample, for the gallery). Pages of documents that never went through a run (seeded history, samples) are rendered the first time they are asked for.
- The side-by-side comparison marks a field "Same" or "Different" by comparing the two stored readings in the browser; this is display only. The duplicate decision itself is made by the Rules stage.
- The dashboard has one filter system, by where a run stands now: All, Approved (by the process or a reviewer), Awaiting review, Rejected (by the process or a reviewer). It is applied in the browser to the list already loaded, so the count on every filter is always visible. Failed runs and runs in progress have no outcome, so they appear only under All.
- The summary tiles are display only (no click or hover behaviour). The filter buttons on the runs table are the only way to change the view, and the active button is the only indicator of what is shown.
- So that the tile and the filter show the same number, "Invoices processed" counts every run, including a failed one (its subline then says how many were decided and how many failed). "Auto-approved" is a share, so it cannot equal a count: its subline gives the count approved by the process, and "Value approved" gives the number of invoices it covers, which equals the Approved filter.
- `GET /api/stats` gained `total_runs`, `approved` (both kinds) and `rejected_by_process`; `rejected` now means rejected by the process or a reviewer.
- The Decision column keeps the process's original verdict; the State column says who settled it ("Approved by the process", "Approved by reviewer", "Rejected by the process", "Rejected by reviewer", "Awaiting review"). In the "Headline reason" column the leading "Needs review:" / "Approved:" is dropped because the Decision column already says it.
- The dashboard's Amount column is always the total including tax. When the total could not be read it says "not found" and gives the amount before tax on a labelled second line.
- Finding codes (such as `PO_BALANCE`) are not shown in the decision banner, which is written for the person deciding. They stay, small, beside each check in the stage detail as an audit reference.
- In the line comparison the score is headed "Wording match" and shown only for a line that was paired with a purchase order line.
- "How it works" shows this document itself: `docs/ASSUMPTIONS.md` is bundled into the frontend when it is built, so the screen and the document cannot drift apart. The rules table is read from the API on every visit. The process map's wording is written in the frontend; its thresholds are filled in from the API.
- After a reset the app returns to the dashboard and reloads its data. There is no sign-in, so the reviewer is not named.
- `react-router` was added for the five addresses (`/`, `/new`, `/runs/<id>`, `/purchase-orders`, `/how-it-works`). In development Vite serves them; serving the built app from FastAPI (one service, one URL) is left to the deployment milestone.
- `make ui-check` (scripts/ui_check.py) drives the real app in a headless browser with the Playwright library already used for generating PDFs. It is a manual check that calls the live model, not part of `make test` or CI.
- Sample file names are neutral: `<vendor>_<invoice date>.pdf` (for example `zenith_2026-11-14.pdf`), so a name never hints at what the process should decide. The case number lives only in `expected.json`. Gallery descriptions say what was bought and whether the bill is a scan, nothing about what is unusual.
- The rename did not change any PDF: the files were moved, and regenerating them with `make invoices` gave the same SHA-256 for all 13. A scan's paper noise used to be seeded from its file name, so the three scans carry a `scan_seed` in `scripts/invoice_definitions.json` holding the original name to keep them byte-for-byte the same. Saved readings are keyed by file hash and are therefore still found.
- The earlier evaluation reports (`docs/EXTRACTION_EVAL.md`, `docs/E2E_CHECK.md`, `data/eval/*.json`) had the old names replaced with the new ones by search-and-replace; their figures are from the original runs and were not re-measured.
- Light and dark theme: a button in the header switches between them. Light is the default on a first visit whatever the operating system prefers; the choice is kept in the browser's local storage. A three-line script in `index.html` applies a remembered dark theme before the page is drawn, so the light theme never flashes first.
- Every colour comes from the tokens at the top of `frontend/src/index.css` (one set for light, one for dark); components name a token, never a colour. Three tokens exist for special cases: `paper` (the white sheet behind an invoice image, the same in both themes), `hatch` (the stripes on the over-value part of the balance bar) and `overlay` (the dimmed page behind a dialog).
- Text contrast was calculated from the token values, not judged by eye: every text and background pair used for body text and for the approve, review and reject colours is at least 5.9 to 1 in light and 6.4 to 1 in dark (the usual minimum for normal text is 4.5 to 1). Text deliberately dimmed with opacity (disabled buttons, secondary counts) is lower.
- The frontend now has tests of its own (Vitest with a simulated browser page): `npm test`, run by `make test` and CI. They render the real dashboard with the two API calls answered from test data.
