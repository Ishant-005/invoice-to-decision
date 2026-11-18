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
