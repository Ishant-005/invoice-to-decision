"""Extraction evaluation (`make eval`): how accurately does the live AI model read the PDFs?

Sends all 15 PDFs (13 test invoices + 2 seeded-history invoices) to the model, compares
every field with the ground truth they were printed from, and writes:

    docs/EXTRACTION_EVAL.md             the report (overwritten each run)
    data/eval/latest_extractions.json   exactly what the model returned, per file
    data/eval/history.json              a summary of every eval run, so runs can be compared

This calls the real API (15 calls, a few US cents) and needs ANTHROPIC_API_KEY in .env.
It does not use or change the app's database, saved results or daily cap.

    make eval
    make eval NOTE="what changed since the last run"
"""

import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import config
from app.pipeline import extract
from app.pipeline.record import InvoiceRecord

REPORT = config.REPO_ROOT / "docs" / "EXTRACTION_EVAL.md"
EVAL_DIR = config.REPO_ROOT / "data" / "eval"
LATEST = EVAL_DIR / "latest_extractions.json"
HISTORY = EVAL_DIR / "history.json"

# US dollars per million tokens (input, output), from Anthropic's pricing page on 2026-11-18.
PRICES = {"claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00"))}

HEADER_FIELDS = ["document_type", "vendor_name", "vendor_tax_id", "invoice_number",
                 "invoice_date", "date_is_ambiguous", "po_reference", "currency", "subtotal",
                 "tax_amount", "tax_rate_percent", "amounts_tax_inclusive", "total"]
LINE_FIELDS = ["description", "quantity", "unit_price", "amount"]
ALL_FIELDS = [*HEADER_FIELDS, "line_items (count)", *[f"line: {name}" for name in LINE_FIELDS]]


def load_documents() -> list[dict]:
    """The 15 PDFs with their ground truth."""
    answer_key = json.loads((config.INVOICE_DIR / "expected.json").read_text(encoding="utf-8"))
    seeded = json.loads((config.SEED_DIR / "seed_invoices.json").read_text(encoding="utf-8"))
    documents = [{"file": case["file"], "path": config.INVOICE_DIR / case["file"],
                  "scanned": case["scanned"], "truth": case["truth"]}
                 for case in answer_key["invoices"]]
    documents += [{"file": entry["file"], "path": config.SEED_DIR / entry["file"],
                   "scanned": False, "truth": entry["extraction"]}
                  for entry in seeded["invoices"]]
    return documents


def same(expected, got) -> bool:
    """Amounts are equal when they are the same number (100000 and 100000.00). Text is equal
    when it matches exactly after trimming and collapsing spaces; upper and lower case count
    as different. Null only equals null."""
    if isinstance(expected, Decimal) and isinstance(got, Decimal):
        return expected == got
    if isinstance(expected, str) and isinstance(got, str):
        return " ".join(expected.split()) == " ".join(got.split())
    return expected == got


def compare(truth: InvoiceRecord, got: InvoiceRecord | None) -> list[dict]:
    """One entry per compared value: {field, expected, got, correct}.

    If the model failed to return a record at all, every value counts as wrong."""
    def entry(field, expected, actual):
        correct = got is not None and same(expected, actual)
        return {"field": field, "expected": show(expected),
                "got": "(no record returned)" if got is None else show(actual),
                "correct": correct}

    checks = [entry(name, getattr(truth, name), getattr(got, name, None))
              for name in HEADER_FIELDS]
    got_lines = got.line_items if got else []
    checks.append(entry("line_items (count)", len(truth.line_items), len(got_lines)))
    for index, line in enumerate(truth.line_items):
        got_line = got_lines[index] if index < len(got_lines) else None
        for name in LINE_FIELDS:
            actual = getattr(got_line, name) if got_line else "(line missing)"
            checks.append({**entry(f"line: {name}", getattr(line, name), actual),
                           "line": index + 1})
    return checks


def show(value) -> str:
    return "null" if value is None else str(value)


def evaluate(documents: list[dict]) -> list[dict]:
    results = []
    for document in documents:
        truth = InvoiceRecord.model_validate(document["truth"])
        started = time.perf_counter()
        record, error, tokens_in, tokens_out = None, None, 0, 0
        try:
            reading = extract.read_with_model(document["path"].read_bytes())
            record, tokens_in, tokens_out = reading.record, reading.input_tokens, reading.output_tokens
        except extract.ExtractionError as failure:
            error = f"{failure} ({failure.__cause__!r})"
        seconds = round(time.perf_counter() - started, 1)

        checks = compare(truth, record)
        wrong = sum(not check["correct"] for check in checks)
        print(f"{document['file']:<36} {seconds:>5}s  {len(checks) - wrong}/{len(checks)} correct"
              + (f"  ERROR: {error}" if error else ""), flush=True)
        results.append({
            "file": document["file"], "scanned": document["scanned"], "seconds": seconds,
            "input_tokens": tokens_in, "output_tokens": tokens_out, "error": error,
            "record": record.model_dump(mode="json") if record else None, "checks": checks})
    return results


def summarise(results: list[dict], note: str) -> dict:
    per_field = {}
    for name in ALL_FIELDS:
        checks = [c for r in results for c in r["checks"] if c["field"] == name]
        per_field[name] = {"correct": sum(c["correct"] for c in checks), "total": len(checks)}
    mismatches = [{"file": r["file"], **{k: c[k] for k in ("field", "expected", "got")},
                   **({"line": c["line"]} if "line" in c else {})}
                  for r in results for c in r["checks"] if not c["correct"]]
    tokens_in = sum(r["input_tokens"] for r in results)
    tokens_out = sum(r["output_tokens"] for r in results)
    model = config.extraction_model()
    cost = None
    if model in PRICES:
        price_in, price_out = PRICES[model]
        cost = str(((tokens_in * price_in + tokens_out * price_out) / 1_000_000).quantize(
            Decimal("0.0001")))
    return {
        "run_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "model": model, "effort": extract.EXTRACTION_EFFORT,
        "prompt_version": extract.PROMPT_VERSION, "note": note,
        "documents": len(results), "failed_documents": sum(r["error"] is not None for r in results),
        "correct": sum(f["correct"] for f in per_field.values()),
        "total": sum(f["total"] for f in per_field.values()),
        "per_field": per_field, "mismatches": mismatches,
        "input_tokens": tokens_in, "output_tokens": tokens_out, "cost_usd": cost,
        "seconds_total": round(sum(r["seconds"] for r in results), 1),
        "seconds_slowest": max(r["seconds"] for r in results),
    }


def percent(correct: int, total: int) -> str:
    return f"{100 * correct / total:.1f}%" if total else "n/a"


def describe_mismatch(m: dict) -> str:
    line = f" (line {m['line']})" if "line" in m else ""
    return f"`{m['file']}` — **{m['field']}**{line}: expected `{m['expected']}`, got `{m['got']}`"


def write_report(summary: dict, results: list[dict], history: list[dict]) -> None:
    s = summary
    out = [
        "# Extraction evaluation",
        "",
        "Written by `scripts/eval_extraction.py` (`make eval`). Every number below comes from a",
        "real run against the live model; nothing is typed in by hand.",
        "",
        "## Latest run",
        "",
        f"- Run at: {s['run_at']}",
        f"- Model: `{s['model']}`, effort `{s['effort']}`, prompt {s['prompt_version']}",
        *([f"- Note: {s['note']}"] if s["note"] else []),
        (f"- Documents: {s['documents']} PDFs (13 test invoices + 2 seeded-history invoices), "
        f"one live call each. Documents the model failed to return a record for: "
        f"{s['failed_documents']}"),
        (f"- **Overall: {s['correct']} of {s['total']} values correct "
        f"({percent(s['correct'], s['total'])})**"),
        "",
        "How values are compared: against the ground truth each PDF was printed from",
        "(`data/invoices/expected.json`, `data/seed/seed_invoices.json`). Amounts must be the same",
        "number. Text must match exactly after trimming spaces (upper and lower case count as",
        "different). Null must be null. Line items are compared in order, row by row. The",
        "`evidence` and `notes` fields are not scored, because their exact wording cannot be",
        "fixed in advance.",
        "",
        "### Accuracy per field",
        "",
        "| Field | Correct | Out of | Accuracy |",
        "|---|---|---|---|",
    ]
    for name, f in s["per_field"].items():
        out.append(f"| {name} | {f['correct']} | {f['total']} | {percent(f['correct'], f['total'])} |")

    out += ["", "### Every mismatch", ""]
    out += [f"- {describe_mismatch(m)}" for m in s["mismatches"]] or ["None."]

    case10 = next((r for r in results if r["file"].startswith("10_")), None)
    if case10 and case10["record"]:
        rec = case10["record"]
        out += [
            "", "### Case 10 (damaged scan): the two values that must be null", "",
            f"- invoice_number: `{show(rec['invoice_number'])}` (expected `null`)",
            (f"- total: `{show(rec['total'])}` (expected `null`; the hidden figure is 259600.00, "
            "which is subtotal + tax, so a model that \"helps\" would produce it)"),
            f"- The model's own note: \"{rec['notes']}\"",
        ]

    out += ["", "### Per document", "",
            "| File | Scan | Values correct | Seconds | Input tokens | Output tokens |",
            "|---|---|---|---|---|---|"]
    for r in results:
        right = sum(c["correct"] for c in r["checks"])
        out.append(f"| {r['file']} | {'yes' if r['scanned'] else 'no'} | {right}/{len(r['checks'])} "
                   f"| {r['seconds']} | {r['input_tokens']} | {r['output_tokens']} |")

    cost = f"about US ${s['cost_usd']}" if s["cost_usd"] else "not priced (unknown model)"
    out += [
        "", "### Time and cost", "",
        (f"- Tokens: {s['input_tokens']:,} input + {s['output_tokens']:,} output across "
        f"{s['documents']} calls."),
        f"- Cost of this run: {cost}"
        + (f" (at ${PRICES[s['model']][0]} per million input tokens and "
           f"${PRICES[s['model']][1]} per million output tokens)." if s["cost_usd"] else "."),
        (f"- Time: {s['seconds_total']} s in total, slowest single document "
        f"{s['seconds_slowest']} s."),
        "",
        "## All eval runs",
        "",
        "Oldest first. When the prompt or schema is changed because of a miss, the run before",
        "and the run after both stay in this table.",
        "",
        "| Run at | Prompt | Effort | Correct | Accuracy | Mismatches | Cost (US $) | Note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for h in history:
        out.append(f"| {h['run_at']} | {h['prompt_version']} | {h['effort']} "
                   f"| {h['correct']}/{h['total']} | {percent(h['correct'], h['total'])} "
                   f"| {len(h['mismatches'])} | {h['cost_usd'] or 'n/a'} | {h['note']} |")
    for h in history[:-1]:
        if h["mismatches"]:
            out += ["", (f"Mismatches in the run of {h['run_at']} (prompt {h['prompt_version']}, "
                        f"effort {h['effort']}):"), ""]
            out += [f"- {describe_mismatch(m)}" for m in h["mismatches"]]

    out += [
        "", "## What this does and does not show", "",
        "- These are 15 synthetic invoices in four layouts, three of them simulated scans. Real",
        "  invoices are messier; accuracy on real documents would be lower and has to be",
        "  measured on a real sample.",
        "- The model does not accept a temperature setting, so two runs can differ. Each row in",
        "  the table above is one pass over the 15 documents; `docs/E2E_CHECK.md` is a further,",
        "  independent pass over the 13 test invoices.",
        "- A wrong value here is not automatically a wrong decision: the deterministic checks",
        "  after extraction catch many misreads (totals that do not add up, unknown vendors).",
        "  `docs/E2E_CHECK.md` shows the decisions reached from live extraction.",
        "",
    ]
    REPORT.write_text("\n".join(out), encoding="utf-8")


def main() -> None:
    note = " ".join(sys.argv[1:]).strip()
    results = evaluate(load_documents())
    summary = summarise(results, note)

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    history.append(summary)
    HISTORY.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    LATEST.write_text(json.dumps(
        {"_about": "What the live model returned in the latest `make eval` run, per file.",
         "run_at": summary["run_at"], "model": summary["model"],
         "prompt_version": summary["prompt_version"],
         "extractions": {r["file"]: r["record"] for r in results}},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(summary, results, history)

    print(f"\n{summary['correct']}/{summary['total']} values correct "
          f"({percent(summary['correct'], summary['total'])}), "
          f"{len(summary['mismatches'])} mismatches")
    for m in summary["mismatches"]:
        print(f"  {m['file']}  {m['field']}: expected {m['expected']!r}, got {m['got']!r}")
    print(f"Tokens: {summary['input_tokens']:,} in + {summary['output_tokens']:,} out. "
          f"Cost: US ${summary['cost_usd']}")
    print(f"Report: {REPORT.relative_to(config.REPO_ROOT)}")


if __name__ == "__main__":
    main()
