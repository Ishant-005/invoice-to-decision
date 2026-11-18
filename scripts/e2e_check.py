"""End-to-end check (`make e2e`): live AI extraction feeding the real decision logic.

For each of the 13 test invoices, starting from a fresh reset every time:

    PDF -> Receive -> Extract (live model) -> Validate -> Match -> Rules -> Decide

and the outcome is compared with the answer key (data/invoices/expected.json): decision,
owner, vendor, PO, match type, pre-tax amount and finding codes. Then the 3 sequences
(several invoices in a row with no reset) are run the same way.

Uses the real Receive and Extract stage code with a throwaway in-memory database, so it
does not touch the app's database, saved results or daily cap. Calls the real API (about
18 calls, a few US cents). Writes docs/E2E_CHECK.md and exits with an error if any case
differs from the answer key.
"""

import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_extraction import PRICES

from app import config, models  # noqa: F401  (importing models registers the tables)
from app.pipeline.extract import PROMPT_VERSION, ExtractResult, extract
from app.pipeline.receive import receive
from tests.answer_key import CASES, SEQUENCES, differences, flagged_codes, fresh_books, run_case

REPORT = config.REPO_ROOT / "docs" / "E2E_CHECK.md"


class Usage:
    """Running totals of live calls and tokens."""

    def __init__(self):
        self.calls, self.tokens_in, self.tokens_out = 0, 0, 0

    def add(self, extracted: ExtractResult) -> None:
        if extracted.source == "live":
            self.calls += 1
            self.tokens_in += extracted.input_tokens
            self.tokens_out += extracted.output_tokens

    def cost(self) -> Decimal | None:
        if config.extraction_model() not in PRICES:
            return None
        price_in, price_out = PRICES[config.extraction_model()]
        dollars = (self.tokens_in * price_in + self.tokens_out * price_out) / 1_000_000
        return dollars.quantize(Decimal("0.0001"))


def new_session() -> Session:
    """A brand-new, empty in-memory database: the state straight after a reset."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def run_live(session: Session, books, file_name: str, pages_dir: Path, usage: Usage):
    """One invoice through all six stages, then record the outcome in the database so a
    later invoice in the same sequence sees it."""
    pdf = (config.INVOICE_DIR / file_name).read_bytes()
    received = receive(pdf, file_name, session, pages_dir=pages_dir)
    extracted = extract(pdf, received, session)
    usage.add(extracted)
    result = run_case(books, file_name, extracted.record)
    session.add(books.invoices[-1])
    session.commit()
    return extracted, result


def main() -> None:
    usage = Usage()
    case_rows, sequence_rows, failures = [], [], 0

    with tempfile.TemporaryDirectory() as folder:
        pages_dir = Path(folder)

        for file_name, case in CASES.items():
            with new_session() as session:
                books = fresh_books(session)
                extracted, result = run_live(session, books, file_name, pages_dir, usage)
                problems = differences(result, case["expected"], books)
            failures += bool(problems)
            row = {
                "case": case["case"], "file": file_name,
                "expected": case["expected"]["decision"], "got": result.decision.decision,
                "owner": result.decision.owner, "po": result.matched.po_id or "-",
                "match": result.matched.po_match_type,
                "codes": ", ".join(sorted(flagged_codes(result))) or "-",
                "problems": problems,
            }
            case_rows.append(row)
            print(f"{row['case']:>2}  {'PASS' if not problems else 'FAIL'}  "
                  f"expected {row['expected']:<8} got {row['got']:<8} {row['match']:<18} "
                  f"owner={row['owner']:<12} {row['codes']}", flush=True)
            for problem in problems:
                print(f"      {problem}")

        for sequence in SEQUENCES:
            with new_session() as session:
                books = fresh_books(session)
                steps = []
                for file_name in sequence["steps"]:
                    extracted, result = run_live(session, books, file_name, pages_dir, usage)
                    steps.append(f"{file_name} → {result.decision.decision} ({extracted.label})")
                problems = differences(result, sequence["expected_last"], books)
            failures += bool(problems)
            sequence_rows.append({
                "name": sequence["name"], "steps": steps,
                "expected": sequence["expected_last"]["decision"],
                "got": result.decision.decision,
                "codes": ", ".join(sorted(flagged_codes(result))) or "-", "problems": problems})
            print(f"sequence {sequence['name']}: {'PASS' if not problems else 'FAIL'}  "
                  f"{' ; '.join(steps)}", flush=True)
            for problem in problems:
                print(f"      {problem}")

    write_report(case_rows, sequence_rows, usage)
    passed = len(case_rows) + len(sequence_rows) - failures
    print(f"\n{passed} of {len(case_rows) + len(sequence_rows)} match the answer key. "
          f"{usage.calls} live calls, {usage.tokens_in:,} in + {usage.tokens_out:,} out tokens, "
          f"about US ${usage.cost()}. Report: {REPORT.relative_to(config.REPO_ROOT)}")
    sys.exit(1 if failures else 0)


def write_report(case_rows: list[dict], sequence_rows: list[dict], usage: Usage) -> None:
    cases_passed = sum(not row["problems"] for row in case_rows)
    sequences_passed = sum(not row["problems"] for row in sequence_rows)
    out = [
        "# End-to-end check: live extraction into the decision logic",
        "",
        "Written by `scripts/e2e_check.py` (`make e2e`) from a real run; nothing is typed in by",
        "hand. Each PDF goes through Receive and Extract (live model), and the record the model",
        "returned goes through Validate, Match, Rules and Decide. The outcome is compared with",
        "`data/invoices/expected.json`: decision, owner, vendor, PO, match type, pre-tax amount",
        "and finding codes.",
        "",
        f"- Run at: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- Model: `{config.extraction_model()}`, prompt {PROMPT_VERSION}",
        f"- **Cases matching the answer key: {cases_passed} of {len(case_rows)}**",
        f"- **Sequences matching the answer key: {sequences_passed} of {len(sequence_rows)}**",
        (f"- Live calls: {usage.calls}; tokens: {usage.tokens_in:,} input + "
        f"{usage.tokens_out:,} output; cost about US ${usage.cost()}"),
        "",
        "## The 13 cases (each from a fresh reset)",
        "",
        "| # | File | Expected | Got | Owner | PO | PO match | Warnings and failures | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in case_rows:
        result = "PASS" if not row["problems"] else "FAIL: " + "; ".join(row["problems"])
        out.append(f"| {row['case']} | {row['file']} | {row['expected']} | {row['got']} "
                   f"| {row['owner']} | {row['po']} | {row['match']} | {row['codes']} | {result} |")
    out += [
        "",
        "## The 3 sequences (no reset between steps; the last step is checked)",
        "",
        "| Sequence | Steps | Expected last | Got | Warnings and failures (last step) | Result |",
        "|---|---|---|---|---|---|",
    ]
    for row in sequence_rows:
        result = "PASS" if not row["problems"] else "FAIL: " + "; ".join(row["problems"])
        out.append(f"| {row['name']} | {'<br>'.join(row['steps'])} | {row['expected']} "
                   f"| {row['got']} | {row['codes']} | {result} |")
    out += [
        "",
        "Not covered here: this check calls the stage functions directly. Running the same",
        "thing over HTTP and in the browser belongs to Milestones 4 and 5.",
        "",
    ]
    REPORT.write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()
