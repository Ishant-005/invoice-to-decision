# Extraction evaluation

Written by `scripts/eval_extraction.py` (`make eval`). Every number below comes from a
real run against the live model; nothing is typed in by hand.

## Latest run

- Run at: 2026-11-18 15:25 UTC
- Model: `claude-sonnet-5-5`, effort `low`, prompt v1
- Note: Same prompt and settings. Answer key corrected: layout C prints the vendor name in capitals, so the key now says so (3 values)
- Documents: 15 PDFs (13 test invoices + 2 seeded-history invoices), one live call each. Documents the model failed to return a record for: 0
- **Overall: 294 of 294 values correct (100.0%)**

How values are compared: against the ground truth each PDF was printed from
(`data/invoices/expected.json`, `data/seed/seed_invoices.json`). Amounts must be the same
number. Text must match exactly after trimming spaces (upper and lower case count as
different). Null must be null. Line items are compared in order, row by row. The
`evidence` and `notes` fields are not scored, because their exact wording cannot be
fixed in advance.

### Accuracy per field

| Field | Correct | Out of | Accuracy |
|---|---|---|---|
| document_type | 15 | 15 | 100.0% |
| vendor_name | 15 | 15 | 100.0% |
| vendor_tax_id | 15 | 15 | 100.0% |
| invoice_number | 15 | 15 | 100.0% |
| invoice_date | 15 | 15 | 100.0% |
| date_is_ambiguous | 15 | 15 | 100.0% |
| po_reference | 15 | 15 | 100.0% |
| currency | 15 | 15 | 100.0% |
| subtotal | 15 | 15 | 100.0% |
| tax_amount | 15 | 15 | 100.0% |
| tax_rate_percent | 15 | 15 | 100.0% |
| amounts_tax_inclusive | 15 | 15 | 100.0% |
| total | 15 | 15 | 100.0% |
| line_items (count) | 15 | 15 | 100.0% |
| line: description | 21 | 21 | 100.0% |
| line: quantity | 21 | 21 | 100.0% |
| line: unit_price | 21 | 21 | 100.0% |
| line: amount | 21 | 21 | 100.0% |

### Every mismatch

None.

### Case 10 (damaged scan): the two values that must be null

- invoice_number: `null` (expected `null`)
- total: `null` (expected `null`; the hidden figure is 259600.00, which is subtotal + tax, so a model that "helps" would produce it)
- The model's own note: "The Grand Total amount is covered by a black ink blot and is unreadable. The Doc. No. field is blank, so there is no invoice number."

### Per document

| File | Scan | Values correct | Seconds | Input tokens | Output tokens |
|---|---|---|---|---|---|
| 01_acme_clean.pdf | no | 22/22 | 3.5 | 5509 | 458 |
| 02_brightline_tax_inclusive.pdf | no | 18/18 | 3.9 | 5280 | 386 |
| 03_sharma_scan.pdf | yes | 22/22 | 3.2 | 4937 | 363 |
| 04_zenith_october.pdf | no | 18/18 | 3.4 | 5496 | 393 |
| 05_zenith_over_balance.pdf | no | 22/22 | 4.0 | 5535 | 442 |
| 06_corelight_freight.pdf | no | 22/22 | 4.2 | 5713 | 383 |
| 07_corelight_price_hike.pdf | no | 18/18 | 3.2 | 5670 | 345 |
| 08_acme_near_duplicate.pdf | yes | 18/18 | 3.4 | 4937 | 348 |
| 09_sharma_no_po.pdf | no | 18/18 | 4.0 | 5357 | 383 |
| 10_corelight_damaged_scan.pdf | yes | 18/18 | 3.6 | 4937 | 369 |
| 11_acme_name_variant.pdf | no | 18/18 | 4.2 | 5463 | 397 |
| 12_brightline_bad_sum.pdf | no | 22/22 | 3.2 | 5326 | 379 |
| 13_unknown_vendor.pdf | no | 22/22 | 5.0 | 5372 | 403 |
| seed_acme_inv1017.pdf | no | 18/18 | 3.5 | 5482 | 376 |
| seed_zenith_zfs0911.pdf | no | 18/18 | 4.1 | 5497 | 391 |

### Time and cost

- Tokens: 80,511 input + 5,816 output across 15 calls.
- Cost of this run: about US $0.2192 (at $2.00 per million input tokens and $10.00 per million output tokens).
- Time: 56.4 s in total, slowest single document 5.0 s.

## All eval runs

Oldest first. When the prompt or schema is changed because of a miss, the run before
and the run after both stay in this table.

| Run at | Prompt | Effort | Correct | Accuracy | Mismatches | Cost (US $) | Note |
|---|---|---|---|---|---|---|---|
| 2026-11-18 15:23 UTC | v1 | low | 291/294 | 99.0% | 3 | 0.2193 | First run: prompt v1, effort low |
| 2026-11-18 15:25 UTC | v1 | low | 294/294 | 100.0% | 0 | 0.2192 | Same prompt and settings. Answer key corrected: layout C prints the vendor name in capitals, so the key now says so (3 values) |

Mismatches in the run of 2026-11-18 15:23 UTC (prompt v1, effort low):

- `03_sharma_scan.pdf` — **vendor_name**: expected `Sharma Office Supplies`, got `SHARMA OFFICE SUPPLIES`
- `09_sharma_no_po.pdf` — **vendor_name**: expected `Sharma Office Supplies`, got `SHARMA OFFICE SUPPLIES`
- `13_unknown_vendor.pdf` — **vendor_name**: expected `Quickfix Hardware Co.`, got `QUICKFIX HARDWARE CO.`

## What this does and does not show

- These are 15 synthetic invoices in four layouts, three of them simulated scans. Real
  invoices are messier; accuracy on real documents would be lower and has to be
  measured on a real sample.
- The model does not accept a temperature setting, so two runs can differ. Each row in
  the table above is one pass over the 15 documents; `docs/E2E_CHECK.md` is a further,
  independent pass over the 13 test invoices.
- A wrong value here is not automatically a wrong decision: the deterministic checks
  after extraction catch many misreads (totals that do not add up, unknown vendors).
  `docs/E2E_CHECK.md` shows the decisions reached from live extraction.
