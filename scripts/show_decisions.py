"""Print the decision the logic reaches for sample invoices, using the answer key's
ground-truth extractions (no AI model, no saved database: a throwaway in-memory one).

    make decisions                 all 13 cases, one line each
    make decisions CASES="1 5 8"   those cases in full, each from a fresh reset
"""

import sys
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import models  # noqa: F401  (registers the tables)
from tests.answer_key import CASES, flagged_codes, fresh_books, run_case


def assess_from_fresh_reset(file_name: str):
    engine = create_engine("sqlite://")  # in memory
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        return run_case(fresh_books(session), file_name)


def print_full(file_name: str) -> None:
    result = assess_from_fresh_reset(file_name)
    decision = result.decision
    print("=" * 100)
    print(f"Case {CASES[file_name]['case']}: {file_name}")
    print(f"  DECISION     {decision.decision}")
    print(f"  HEADLINE     {decision.headline}")
    print("  REASONS" + ("" if decision.reasons else "      (none)"))
    for reason in decision.reasons:
        print(f"    - [{reason.status}/{reason.severity}] {reason.code}: {reason.text}")
    print(f"  OWNER        {decision.owner_label} ({decision.owner})")
    print(f"  NEXT ACTION  {decision.next_action}")
    print("  WHAT PASSED")
    for line in decision.passed:
        print(f"    - {line}")
    if decision.not_checked:
        print("  NOT CHECKED")
        for line in decision.not_checked:
            print(f"    - {line}")


def print_summary() -> None:
    for file_name, case in CASES.items():
        result = assess_from_fresh_reset(file_name)
        codes = ", ".join(sorted(flagged_codes(result))) or "-"
        print(f"{case['case']:>2}  {result.decision.decision:<8} "
              f"{result.matched.po_match_type:<18} owner={result.decision.owner:<12} {codes}")


if __name__ == "__main__":
    wanted = [int(arg) for arg in sys.argv[1:]]
    if not wanted:
        print_summary()
    for file_name, case in CASES.items():
        if case["case"] in wanted:
            print_full(file_name)
