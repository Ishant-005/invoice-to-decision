# Invoice-to-Decision: Build Specification

This is the single source of truth for the build. It was written by the technical lead; the
implementer (Claude Code) builds from it milestone by milestone. Decisions marked FIXED are
settled and must not be redesigned. Everything else is yours to engineer sensibly.

## 1. Context

This is a take-home case study for an "AI Solutions Analyst" role. The brief (PS-1, Finance / AP):

> A mid-size company receives hundreds of vendor invoices a month as PDFs. Someone on the AP team
> opens each one, finds the matching purchase order in a spreadsheet, checks whether the numbers
> line up, and decides what to do. Build a process that takes an invoice as input and produces a
> clear, reasoned decision as output, with everything that happened in between visible.

How it is graded, in the evaluators' words: whether the process actually works, the judgment behind
the design choices, and how it is explained to a non-technical buyer. They also require:

- A live, runnable process at a public link. Not a mockup, not a simulation.
- An intuitive, well-designed UI with a **live run view** (each stage shown as it executes) and a
  **dashboard** (history, status and outputs across runs).
- 2 to 4 non-trivial edge cases, designed by the candidate, handled deliberately.
- A live demo in an interview. A demo that breaks live is hard to recover from, so reliability and
  repeatability outrank feature count.

The owner of this repo is new to building software and must be able to explain every decision in
an interview. Favour simple, readable code and plain-English messages over cleverness.

## 2. The one architectural rule (FIXED)

**The AI model reads; code decides.**

- The language model is used in exactly one place: turning a PDF into a structured record
  (the Extract stage).
- Validation, matching, rules and the final decision are deterministic Python. Same inputs, same
  decision, every time.
- Every sentence of reasoning shown to the user is assembled from real check results. No model
  writes or embellishes the explanation after the fact.

## 3. Pipeline

Six stages, always in this order. Each stage is a plain function that takes the outputs of the
earlier stages and returns a typed result plus a list of findings.

| # | Stage | Uses AI | Purpose |
|---|---|---|---|
| 1 | Receive | No | Accept the file, check type and size, hash it, render page images |
| 2 | Extract | Yes | PDF to structured invoice record |
| 3 | Validate | No | Is the record complete and internally consistent? |
| 4 | Match | No | Which vendor and which purchase order does it belong to? |
| 5 | Rules | No | Does it comply with company policy (balance, tolerance, duplicates)? |
| 6 | Decide | No | Combine all findings into one decision with reasons, owner and next action |

**Collect everything, do not stop at the first failure (FIXED).** Run every check that can still
run. When an earlier failure makes a check impossible, record it as `skipped` with the reason.
The reviewer must get one complete list of problems, not one problem per resubmission.

### 3.1 Findings

Every check emits a finding:

```
code        machine-readable, e.g. TOTALS_MISMATCH
stage       validate | match | rules
status      pass | warn | fail | skipped
severity    info | review | reject        (what this finding implies for the decision)
message     one plain-English sentence with the actual numbers in it
owner       ap | procurement | vendor | none
data        the values used, for display
```

Messages must contain the real figures, formatted in Indian style, for example:
"Subtotal ₹90,000 + tax ₹16,200 = ₹1,06,200, but the invoice states ₹1,07,200."

### 3.2 Stage 1: Receive

- Accept PDF only, max 10 MB, max 5 pages. Reject anything else with a clear error.
- Compute SHA-256 of the file.
- Render each page to PNG (use `pypdfium2`) for the UI preview.
- If an earlier run has the same hash, note it: the stored extraction is reused (labelled
  "reused: identical file") and the Rules stage will raise an exact-duplicate finding.

### 3.3 Stage 2: Extract

- Send the PDF to the Anthropic API and get back the record below as structured output.
- Model ID comes from the `EXTRACTION_MODEL` env var, default `claude-sonnet-5-5`. Temperature 0.
- **Before writing the client, read the current Anthropic documentation** for PDF input and for
  structured / schema-constrained output, and use what it currently recommends. Do not rely on
  memory for SDK details.
- One path for both digital and scanned PDFs. No separate OCR library.

Record (every field nullable unless stated):

```
document_type          invoice | credit_note | quotation | statement | other   (required)
vendor_name
vendor_tax_id          GSTIN as printed
invoice_number
invoice_date           ISO YYYY-MM-DD
date_is_ambiguous      bool, true if day/month order could not be determined
po_reference           exactly as printed; null if none is printed
currency               ISO code
line_items[]           description, quantity, unit_price, amount   (may be empty)
subtotal               pre-tax amount if printed
tax_amount             total tax if printed (sum CGST + SGST, or IGST)
tax_rate_percent       if stated
amounts_tax_inclusive  bool, true if the document says prices/total include tax
total                  final payable amount as printed
evidence               for vendor_name, invoice_number, invoice_date, po_reference, total:
                       the exact text snippet read from the page
notes                  anything unusual the reader noticed (smudges, handwriting)
```

Prompt requirements (FIXED):

- Report only what is printed. If a field is absent or unreadable, return null. Never infer,
  compute or guess a value. Do not calculate a total from other numbers.
- Do not decide which PO was "probably meant". That is the Match stage's job.
- Convert Indian-format numbers (1,06,200.00) to plain decimals.

Reliability:

- Timeout 60 s, up to 2 retries with backoff.
- Persist every successful extraction keyed by file hash.
- `EXTRACTION_CACHE_MODE` = `fallback` (default) | `off`. In `fallback`, always call the live API;
  if it fails after retries and a stored extraction exists for that hash, use it and label the
  stage clearly as "served from saved result (live call failed)". Never hide this.
- `MAX_LIVE_EXTRACTIONS_PER_DAY` (default 150) protects the API budget on a public link. When the
  cap is hit, use the saved result if one exists, otherwise fail the run with a clear message.
- Do not ask the model for a confidence score and do not build logic on one.

### 3.4 Stage 3: Validate

Checks the invoice against itself only.

| Code | Check | On failure |
|---|---|---|
| DOC_TYPE | document_type is invoice | reject |
| REQUIRED_FIELDS | invoice_number, vendor_name, invoice_date, total present | review, owner vendor |
| LINE_ARITHMETIC | quantity × unit_price = amount per line (± ₹1) | review, owner vendor |
| TOTALS | lines sum to subtotal; subtotal + tax = total (± ₹1) | review, owner vendor |
| DATE_SANITY | date parses, not in the future; warn if older than 180 days; review if ambiguous | see left |
| AMOUNT_SANITY | amounts positive, currency is INR | review |
| TAX_ID_FORMAT | GSTIN is 15 characters matching the standard pattern, if present | warn |

A missing PO reference is NOT a validation failure. Bundled invoices (no line items) are fine:
line checks are `skipped`.

**Tax normalisation.** Compute `pretax_amount` and `gross_amount` for every invoice:

- If subtotal and total are printed, use them.
- If only a tax-inclusive total is printed and a rate is stated, `pretax = total / (1 + rate)`.
- If neither is possible, emit a review finding (`TAX_UNRESOLVED`).

All PO comparisons downstream use `pretax_amount`, because PO values are pre-tax.

### 3.5 Stage 4: Match

**Vendor**, in order of strength:

1. Tax ID exact match → confirmed.
2. Cleaned-name exact match (lowercase, strip punctuation and suffixes such as Pvt, Ltd, Private,
   Limited, LLP, Co) → confirmed.
3. Fuzzy name match (rapidfuzz, score ≥ 88) → `suggested` only: review, owner AP. A similar name
   must never confirm a vendor on its own, because look-alike names are a fraud pattern.
4. Nothing → `VENDOR_NOT_FOUND`: reject, owner procurement ("vendor must be onboarded first").

Also: name matches but printed tax ID differs from the master → review (`VENDOR_TAX_ID_CONFLICT`).
Vendor status `blocked` → reject.

**Purchase order:**

- If `po_reference` is printed: normalise it ("PO-2231", "P.O. #2231", "PO 2231", "2231" are the
  same) and look it up. Then verify the PO belongs to the matched vendor.
  - Found and belongs to vendor → `explicit_verified`.
  - Found but belongs to another vendor → `explicit_conflict`: review, owner AP.
  - Not found → `PO_NOT_FOUND`: review, owner procurement.
- If no reference is printed: score the vendor's open POs. Starting formula (tune if needed):
  amount fits remaining balance 40, best line-description similarity 40, invoice date on or
  after PO date 20. A candidate is strong at ≥ 70.
  - Exactly one strong candidate → `implied_single`: review, owner AP, with the suggested PO.
  - Several → `implied_multiple`: review with the shortlist.
  - None → `none`: review, owner procurement.
- **An implied match never auto-approves (FIXED).** The process does the search; a human confirms.

Output includes the PO's value, billed-to-date, remaining balance and the earlier invoices
against it.

**Line matching** (only when the invoice and the PO are both itemised): pair each invoice line to
a PO line by description similarity (rapidfuzz token_set_ratio ≥ 70). Unpaired invoice lines are
reported as `LINE_NOT_ON_PO` (warn).

### 3.6 Stage 5: Rules

All thresholds live in `config/rules.yaml` and are displayed in the UI.

| Code | Rule | Result |
|---|---|---|
| DUPLICATE_EXACT | Same file hash as an earlier run, OR same vendor + same normalised invoice number | reject, owner AP |
| DUPLICATE_PROBABLE | Same vendor AND same gross total AND (same invoice date OR one normalised invoice number is the other plus at most 2 trailing characters) | review, owner AP, link to the earlier invoice |
| PO_BALANCE | billed_to_date + this pretax_amount ≤ PO value | pass |
| PO_BALANCE (over, within tolerance) | overage ≤ 2% of PO value AND ≤ ₹5,000 | warn: approve with a note |
| PO_BALANCE (over, beyond tolerance) | otherwise | review, owner procurement |
| PRICE_VARIANCE | per paired line, unit price within ± 2% of PO unit price | beyond: review, owner procurement |
| PO_STATUS | PO is open | closed: review |

Duplicate checks compare against earlier invoices whose state is approved or awaiting review.
Invoices that were rejected are excluded, because a corrected resubmission is legitimate.

Deliberate design point to preserve: two invoices from the same vendor with the same amount but
different dates and unrelated numbers (a monthly service) are NOT duplicates.

If the invoice number is null, emit `DUPLICATE_CHECK_PARTIAL` (info).

### 3.7 Stage 6: Decide

- Decision = the worst severity across all findings: any `reject` → REJECT; else any `review` →
  REVIEW; else APPROVE.
- Output: decision, headline sentence, ordered list of reasons (fail first, then warn), primary
  owner, recommended next action, and a "what passed" list.
- All text is produced from templates keyed on finding codes.
- APPROVE updates the PO's billed-to-date in the same transaction. REVIEW and REJECT do not.

### 3.8 Human review

A REVIEW run can be resolved by a person: approve (optionally confirming the suggested PO) or
reject, with a required comment. Human approval updates the PO balance. The resolution, comment
and timestamp are stored and shown. This closes the loop and is what the dashboard's
"needs review" queue is for.

## 4. Data

Fictional buyer: **Meridian Home Retail Pvt Ltd**, Gurugram. Currency INR, GST 18% on everything.
Generate syntactically valid but obviously fictional GSTINs.

"The spreadsheet" is three CSV files in `data/seed/`, loaded into the database at seed time:
`vendors.csv`, `purchase_orders.csv`, `po_lines.csv`. Plus `seed_invoices.json` for history.

### 4.1 Vendors

| ID | Name | Layout | Status |
|---|---|---|---|
| V-001 | Acme Packaging Pvt Ltd | A | active |
| V-002 | Brightline Logistics LLP | B | active |
| V-003 | Sharma Office Supplies | C | active |
| V-004 | Corelight Electricals Pvt Ltd | D | active |
| V-005 | Zenith Facility Services Pvt Ltd | A | active |

### 4.2 Purchase orders (values are pre-tax)

| PO | Vendor | Lines | Value | Billed at seed |
|---|---|---|---|---|
| PO-2219 | V-001 | 2000 × Shipping carton 18x12x10 @ 100 | 2,00,000 | 1,00,000 |
| PO-2231 | V-001 | 500 × Corrugated box 12x10x8 @ 180; 200 × Bubble wrap roll @ 450 | 1,80,000 | 0 |
| PO-2240 | V-002 | 1 × Freight services, October, Delhi NCR @ 1,00,000 | 1,00,000 | 0 |
| PO-2252 | V-003 | 40 × A4 paper ream @ 320; 25 × Printer toner @ 2,400 | 72,800 | 0 |
| PO-2260 | V-005 | 3 × Housekeeping contract, monthly (Sep to Nov) @ 1,00,000 | 3,00,000 | 1,00,000 |
| PO-2275 | V-004 | 100 × LED panel light 40W @ 1,500 | 1,50,000 | 0 |
| PO-2281 | V-004 | 60 × MCB distribution board @ 2,500 | 1,50,000 | 0 |
| PO-2290 | V-003 | 30 × Ergonomic office chair @ 6,500 | 1,95,000 | 0 |
| PO-2296 | V-004 | 200 × Copper cable 2.5 sq mm, 90 m coil @ 1,100 | 2,20,000 | 0 |
| PO-2301 | V-002 | 1 × Warehouse-to-store transfers, November @ 80,000 | 80,000 | 0 |

All POs are dated between 2026-08-01 and 2026-10-15, before their invoices.

### 4.3 Seeded history (already approved; shown on the dashboard, labelled "seeded history")

| Invoice | Vendor | PO | Date | Pre-tax | Gross |
|---|---|---|---|---|---|
| INV-1017 | V-001 | PO-2219 | 2026-10-03 | 1,00,000 | 1,18,000 |
| ZFS-0911 | V-005 | PO-2260 | 2026-09-30 | 1,00,000 | 1,18,000 |

Generate PDFs for these too, and store their extraction results in the repo so seeding never
calls the API.

### 4.4 Test invoices (the answer key)

Thirteen PDFs in `data/invoices/`, committed to the repo so the set never changes. Expected
decisions assume a fresh reset before each case unless stated.

| # | File | Vendor / PO | Invoice no., date | Content | What is messy | Expected |
|---|---|---|---|---|---|---|
| 1 | 01_acme_clean.pdf | V-001 / PO-2231 | INV-1042, 2026-11-05 | Both PO lines in full. Subtotal 1,80,000; CGST 16,200 + SGST 16,200; total 2,12,400 | Nothing. Happy path | APPROVE |
| 2 | 02_brightline_tax_inclusive.pdf | V-002 / PO-2240 | BL/26-27/0193, 2026-11-02 | One bundled line. Only "Total ₹1,18,000 inclusive of GST @ 18%" | Bundled, tax embedded | APPROVE (pre-tax derived as 1,00,000) |
| 3 | 03_sharma_scan.pdf | V-003 / PO-2252 | SOS-778, 2026-10-28 | Both lines. Subtotal 72,800; GST 13,104; total 85,904 | Scanned image, slightly skewed | APPROVE |
| 4 | 04_zenith_october.pdf | V-005 / PO-2260 | ZFS-0934, 2026-10-31 | Housekeeping October 1,00,000; GST 18,000; total 1,18,000 | Part-invoice on a split PO; same amount as last month | APPROVE; PO billed becomes 2,00,000. Must NOT be flagged as a duplicate of ZFS-0911 |
| 5 | 05_zenith_over_balance.pdf | V-005 / PO-2260 | ZFS-0958, 2026-11-14 | Housekeeping November 1,00,000 + "Additional deep cleaning" 1,40,000. Subtotal 2,40,000; GST 43,200; total 2,83,200 | Pushes the PO over its value; extra line not on PO | REVIEW, owner procurement (in either order relative to case 4) |
| 6 | 06_corelight_freight.pdf | V-004 / PO-2275 | CE-5521, 2026-11-06 | 100 × 1,500 = 1,50,000 + Freight 1,200. Subtotal 1,51,200; IGST 27,216; total 1,78,416 | Over PO by 1,200 (0.8%) | APPROVE with tolerance note |
| 7 | 07_corelight_price_hike.pdf | V-004 / PO-2281 | CE-5547, 2026-11-10 | 60 × 2,700 = 1,62,000; IGST 29,160; total 1,91,160 | Unit price 8% above PO | REVIEW, owner procurement |
| 8 | 08_acme_near_duplicate.pdf | V-001 / PO-2219 | INV-1017-A, 2026-10-03 | Same as seeded INV-1017: 1000 cartons, 1,00,000; GST 18,000; total 1,18,000. Rendered as a scan | Altered number, different file, same bill. The PO still has room, so only duplicate detection can catch it | REVIEW, DUPLICATE_PROBABLE, linked to INV-1017 |
| 9 | 09_sharma_no_po.pdf | V-003 / (PO-2290 implied) | SOS-801, 2026-11-08 | "Ergonomic office chairs (mesh back), 30 nos" @ 6,500. Subtotal 1,95,000; GST 35,100; total 2,30,100. No PO printed | PO implied | REVIEW, implied_single, suggests PO-2290 |
| 10 | 10_corelight_damaged_scan.pdf | V-004 / PO-2296 | number blank, 2026-11-11 | 200 × 1,100 = 2,20,000; IGST 39,600; total 2,59,600 | Scan; invoice number field empty; total covered by an opaque stain | REVIEW, owner vendor. invoice_number and total must be null, not guessed |
| 11 | 11_acme_name_variant.pdf | V-001 / PO-2219 | INV-1058, 2026-11-12 | 500 cartons @ 100 = 50,000; GST 9,000; total 59,000. Vendor printed as "ACME PACKAGING PRIVATE LIMITED", no GSTIN | Name variant | APPROVE via cleaned-name match |
| 12 | 12_brightline_bad_sum.pdf | V-002 / PO-2301 | BL/26-27/0214, 2026-11-14 | Lines 50,000 + 30,000; subtotal 80,000; GST 14,400; total printed 95,400 (correct is 94,400) | Totals do not add up | REVIEW, TOTALS, owner vendor |
| 13 | 13_unknown_vendor.pdf | Quickfix Hardware Co. / "PO-9999" | QH-0091, 2026-11-09 | Any plausible content | Vendor not in master | REJECT |

Sequence cases to test as well:

- Case 1 submitted twice without a reset → second run is REJECT, DUPLICATE_EXACT.
- Case 4 then case 5 → case 5 is REVIEW with an overage of ₹1,40,000.
- Case 11 then case 8 → case 8 is still REVIEW.

`data/invoices/expected.json` holds, per file: the ground-truth field values and the expected
decision, match type and finding codes. It is the acceptance test.

### 4.5 Generating the PDFs

- Four visually distinct HTML/CSS layouts (A classic table with CGST/SGST split, B modern
  minimal, C plain small-business, D dense with IGST). Field labels and positions should differ
  between layouts ("Invoice No.", "Bill #", "Ref", and so on).
- Render with Playwright (Chromium) print-to-PDF. If Playwright cannot be installed, fall back
  to ReportLab and say so.
- "Scans": render the PDF page to an image, rotate 1 to 2 degrees, add slight blur, noise and
  JPEG compression, then wrap the image in an image-only PDF. Verify the result has no
  extractable text layer.
- The generator is `scripts/generate_invoices.py`, driven by one data file, deterministic
  (fixed random seed).

## 5. Technology (FIXED unless noted)

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2 | Readable, typed, quick to build |
| Database | SQLite via SQLModel | Zero setup; enough for a demo |
| Money | `Decimal` everywhere; never float | Finance arithmetic must be exact |
| AI | Anthropic Python SDK | One model call per invoice |
| Fuzzy matching | rapidfuzz | Fast, well known |
| Frontend | React + Vite + TypeScript + Tailwind + shadcn/ui | Polished UI quickly |
| Live updates | The client polls `GET /api/runs/{id}` every ~700 ms while a run is active | Simplest thing that cannot break behind a proxy during a live demo |
| Serving | FastAPI serves the built frontend; one service, one URL | One thing to deploy |
| Packaging | One Dockerfile | Portable across hosts |
| Tests | pytest; Playwright for one end-to-end smoke test | |
| CI | GitHub Actions: backend tests + frontend build on every push | |

Use `uv` for Python dependencies and `npm` for the frontend unless you have a strong reason.
Provide a `Makefile` (or equivalent scripts) with: `make dev`, `make test`, `make seed`,
`make invoices`, `make eval`, `make build`.

### 5.1 Execution model

- `POST /api/runs` stores the file, creates a run in `queued`, starts the pipeline as a background
  task and returns the run ID immediately.
- Each stage writes a `stage_event` row when it starts and when it finishes (status, real
  duration in ms, result JSON, findings). The run view is rendered from these rows.
- **No fake delays in the backend (FIXED).** Deterministic stages finish in milliseconds. The UI
  may reveal completed stages one after another at a readable pace, but it must show the real
  measured duration of each stage.
- An unexpected exception marks the run `failed` with a readable message and the stage where it
  happened. A failed run never produces a decision.

### 5.2 API (shape is yours to refine)

```
POST /api/runs                      upload a PDF or reference a sample by name
GET  /api/runs                      list, with filters (decision, status, vendor)
GET  /api/runs/{id}                 run + stage events + findings + decision
GET  /api/runs/{id}/pages/{n}.png   page image
POST /api/runs/{id}/resolve         human approve / reject with comment
GET  /api/samples                   the 13 sample invoices
GET  /api/purchase-orders           with billed and remaining
GET  /api/purchase-orders/{id}      with linked invoices
GET  /api/vendors
GET  /api/stats                     dashboard numbers
GET  /api/config/rules              thresholds, for display
POST /api/demo/reset                restore seed state
GET  /api/health
```

### 5.3 Demo state (FIXED)

The process is stateful: PO balances and invoice history change with every run, so the same
invoice can get a different decision the second time. That is correct behaviour, and it makes
demos unrepeatable without a reset.

- `POST /api/demo/reset` wipes runs and restores vendors, POs, balances and seeded history.
  Saved extractions (keyed by file hash) survive a reset.
- On startup, if the database is empty, seed it automatically. The app must be usable on a host
  whose disk is wiped on every restart.
- A "Reset demo data" button sits in the app header behind a confirmation dialog.

## 6. Frontend

Audience: an AP clerk and a finance manager. The interviewers will look at this UI with the
candidate, so it is graded. Aim for a calm, credible finance-operations tool: dense where data
is tabular, generous where a decision is being explained. Indian number formatting (₹1,06,200)
everywhere. No decorative gradients. Decision colours: green approve, amber review, red reject,
always paired with a text label.

Screens:

1. **Dashboard** (home). Summary tiles: invoices processed, auto-approved share, awaiting
   review, rejected, value approved. A runs table: time, vendor, invoice number, amount, PO,
   decision, headline reason, state. Filter by decision. Clicking a row opens the run.
2. **New run.** Drag-and-drop upload, plus a gallery of the 13 sample invoices, each with a
   one-line description of what it contains (not its expected outcome).
3. **Run view** (the centrepiece).
   - Left: the invoice page image(s).
   - Right: a vertical timeline of the six stages. Each shows waiting / running / done, its real
     duration, and expands to show what it found: Extract shows fields beside the quoted
     evidence, with nulls marked "not found on the document"; Validate and Rules show the
     findings as a checklist; Match shows the vendor and PO with how each was matched, and the
     PO balance as a bar (value, billed, this invoice, remaining).
   - Top, once finished: the decision banner with headline, reasons in plain English, who owns
     the next step, and what passed.
   - For REVIEW: approve / reject controls with a comment box. For a probable duplicate: the
     earlier invoice side by side. For an implied PO: the suggested PO with a confirm action.
   - The run view must work both live (while running) and as a record (opened later from the
     dashboard).
4. **Purchase orders.** Each PO with value, billed, remaining, and its invoices.
5. **How it works.** The process map, the rules and thresholds currently in force (read from the
   API), and the list of assumptions.

Every screen needs loading, empty and error states. The app must be usable at laptop width
(1280 px) since it will be screen-shared.

## 7. Repository layout (suggested)

```
backend/app/        api/, pipeline/ (receive, extract, validate, match, rules, decide), models, db, config
backend/tests/      unit/, integration/, fixtures/
frontend/           React app
data/seed/          CSVs and seeded history
data/invoices/      13 PDFs + expected.json
config/rules.yaml   thresholds
scripts/            generate_invoices.py, eval_extraction.py, seed.py
docs/               SPEC.md, PROCESS_MAP.md, ASSUMPTIONS.md, PROGRESS.md, DEMO_SCRIPT.md
Dockerfile, Makefile, README.md, CLAUDE.md, .env.example, .github/workflows/ci.yml
```

## 8. Testing and evaluation

1. **Unit tests** for each deterministic stage, including boundaries: overage exactly at 2%,
   rounding at ₹1, tax-inclusive derivation, PO number normalisation, vendor name cleaning,
   duplicate rules (including the monthly-invoice non-duplicate).
2. **Answer-key test.** For all 13 cases and the 3 sequences, feed the ground-truth extraction
   from `expected.json` through Validate → Decide and assert the decision, match type and
   finding codes. Needs no API key. This proves the logic independently of the model.
3. **Extraction evaluation** (`make eval`). Run the live model over all PDFs and compare field by
   field with ground truth. Write `docs/EXTRACTION_EVAL.md` with per-field accuracy and every
   miss listed. Report the real numbers, whatever they are.
4. **End-to-end check.** With real extraction, all 13 cases reach their expected decision.
5. **API integration tests** with extraction mocked.
6. **One Playwright smoke test:** open the app, run sample 1, see APPROVE; reset.

**Honesty rules (FIXED).** Never invent a metric or claim a test passed without running it.
`docs/PROGRESS.md` tracks every feature as one of: implemented, tested (automated test passes),
verified (seen working end to end). If something does not work, say so plainly.

## 9. Non-functional requirements

- The API key lives only in server-side env vars. Never in the repo, never sent to the browser.
- Upload limits enforced server-side. Uploaded files are stored outside the web root.
- Structured logs with the run ID on every line.
- A typical run finishes in under 30 seconds; the UI shows progress throughout.
- `README.md` lets a stranger run the project locally in under 10 minutes.

## 10. Milestones

Each milestone ends with: tests green, `docs/PROGRESS.md` updated, committed and pushed. Commit
in small logical steps within a milestone using conventional commit messages.

| # | Milestone | Done when |
|---|---|---|
| 0 | Repo and scaffold | Backend health endpoint and a placeholder frontend run with one command; CI passes; pushed to GitHub |
| 1 | Data and test invoices | Seed CSVs load; 13 + 2 PDFs generated and committed; expected.json complete; reset works |
| 2 | Decision logic | Validate, Match, Rules, Decide implemented; unit tests and the answer-key test pass with no API key |
| 3 | Extraction | Live extraction works on all PDFs; eval report written with real numbers; cache and fallback work |
| 4 | Pipeline and API | A run can be started over HTTP and polled to completion; state updates and review resolution work |
| 5 | Web app | All five screens work against the real API; end-to-end check passes in the browser |
| 6 | Hardening | Error states, limits, Playwright smoke test, README, assumptions, process map |
| 7 | Deploy and demo prep | Live public URL passes the smoke test; demo script written and rehearsable |

## 11. If time runs short, cut in this order

1. Line-level price check (keep the header-level balance check).
2. Purchase orders screen.
3. Playwright test and CI.
4. Cases 11 to 13.

Never cut: the live run view, the dashboard, the reset button, cases 1, 5, 8, 9, 10.

## 12. Known limits to state openly

- Two-way match only (invoice vs PO). No goods receipt, so it cannot confirm delivery.
- Quantities are not tracked cumulatively per PO line; over-billing is caught on value.
- Single currency, single tax rate, single page focus.
- Synthetic invoices are cleaner than real ones; extraction accuracy on real documents would be
  lower and needs a real sample to measure.
- No authentication; this is a demo, not a deployment.
