"""Runs the four deterministic stages in order: Validate -> Match -> Rules -> Decide."""

from datetime import date

from pydantic import BaseModel

from app.pipeline.decide import Decision, decide
from app.pipeline.findings import Finding
from app.pipeline.match import MatchResult, match
from app.pipeline.record import Books, InvoiceRecord
from app.pipeline.rules import RulesResult, apply_rules
from app.pipeline.validate import ValidateResult, validate
from app.rules_config import RulesConfig, default_rules


class Assessment(BaseModel):
    validated: ValidateResult
    matched: MatchResult
    ruled: RulesResult
    decision: Decision

    @property
    def findings(self) -> list[Finding]:
        return self.validated.findings + self.matched.findings + self.ruled.findings


def assess(record: InvoiceRecord, books: Books, file_hash: str, today: date,
           rules: RulesConfig | None = None) -> Assessment:
    """Every stage runs even when an earlier one found problems, so the reviewer gets one
    complete list. `today` is passed in (not read from the clock) so results are repeatable."""
    rules = rules or default_rules()
    validated = validate(record, today, rules.validate_)
    matched = match(record, validated, books, rules.match)
    ruled = apply_rules(record, validated, matched, books, file_hash, rules.rules)
    decision = decide(validated, matched, ruled)
    return Assessment(validated=validated, matched=matched, ruled=ruled, decision=decision)
