# End-to-end check: live extraction into the decision logic

Written by `scripts/e2e_check.py` (`make e2e`) from a real run; nothing is typed in by
hand. Each PDF goes through Receive and Extract (live model), and the record the model
returned goes through Validate, Match, Rules and Decide. The outcome is compared with
`data/invoices/expected.json`: decision, owner, vendor, PO, match type, pre-tax amount
and finding codes.

- Run at: 2026-11-18 15:27 UTC
- Model: `claude-sonnet-5-5`, prompt v1
- **Cases matching the answer key: 13 of 13**
- **Sequences matching the answer key: 3 of 3**
- Live calls: 18; tokens: 96,472 input + 7,101 output; cost about US $0.2640

## The 13 cases (each from a fresh reset)

| # | File | Expected | Got | Owner | PO | PO match | Warnings and failures | Result |
|---|---|---|---|---|---|---|---|---|
| 1 | 01_acme_clean.pdf | APPROVE | APPROVE | none | PO-2231 | explicit_verified | - | PASS |
| 2 | 02_brightline_tax_inclusive.pdf | APPROVE | APPROVE | none | PO-2240 | explicit_verified | - | PASS |
| 3 | 03_sharma_scan.pdf | APPROVE | APPROVE | none | PO-2252 | explicit_verified | - | PASS |
| 4 | 04_zenith_october.pdf | APPROVE | APPROVE | none | PO-2260 | explicit_verified | - | PASS |
| 5 | 05_zenith_over_balance.pdf | REVIEW | REVIEW | procurement | PO-2260 | explicit_verified | LINE_NOT_ON_PO, PO_BALANCE | PASS |
| 6 | 06_corelight_freight.pdf | APPROVE | APPROVE | none | PO-2275 | explicit_verified | LINE_NOT_ON_PO, PO_BALANCE | PASS |
| 7 | 07_corelight_price_hike.pdf | REVIEW | REVIEW | procurement | PO-2281 | explicit_verified | PO_BALANCE, PRICE_VARIANCE | PASS |
| 8 | 08_acme_near_duplicate.pdf | REVIEW | REVIEW | ap | PO-2219 | explicit_verified | DUPLICATE_PROBABLE | PASS |
| 9 | 09_sharma_no_po.pdf | REVIEW | REVIEW | ap | PO-2290 | implied_single | PO_IMPLIED | PASS |
| 10 | 10_corelight_damaged_scan.pdf | REVIEW | REVIEW | vendor | PO-2296 | explicit_verified | DUPLICATE_CHECK_PARTIAL, REQUIRED_FIELDS | PASS |
| 11 | 11_acme_name_variant.pdf | APPROVE | APPROVE | none | PO-2219 | explicit_verified | - | PASS |
| 12 | 12_brightline_bad_sum.pdf | REVIEW | REVIEW | vendor | PO-2301 | explicit_verified | TOTALS | PASS |
| 13 | 13_unknown_vendor.pdf | REJECT | REJECT | procurement | - | not_found | PO_NOT_FOUND, VENDOR_NOT_FOUND | PASS |

## The 3 sequences (no reset between steps; the last step is checked)

| Sequence | Steps | Expected last | Got | Warnings and failures (last step) | Result |
|---|---|---|---|---|---|
| same_file_twice | 01_acme_clean.pdf → APPROVE (read live by the AI model)<br>01_acme_clean.pdf → REJECT (reused: identical file) | REJECT | REJECT | DUPLICATE_EXACT, PO_BALANCE | PASS |
| october_then_over_balance | 04_zenith_october.pdf → APPROVE (read live by the AI model)<br>05_zenith_over_balance.pdf → REVIEW (read live by the AI model) | REVIEW | REVIEW | LINE_NOT_ON_PO, PO_BALANCE | PASS |
| name_variant_then_near_duplicate | 11_acme_name_variant.pdf → APPROVE (read live by the AI model)<br>08_acme_near_duplicate.pdf → REVIEW (read live by the AI model) | REVIEW | REVIEW | DUPLICATE_PROBABLE, PO_BALANCE | PASS |

Not covered here: this check calls the stage functions directly. Running the same
thing over HTTP and in the browser belongs to Milestones 4 and 5.
