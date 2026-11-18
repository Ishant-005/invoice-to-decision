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
