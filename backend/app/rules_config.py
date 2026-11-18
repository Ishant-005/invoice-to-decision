"""Loads config/rules.yaml: the thresholds the deterministic stages use."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from app import config

RULES_FILE = config.REPO_ROOT / "config" / "rules.yaml"


class ValidateConfig(BaseModel):
    rounding_tolerance_rupees: Decimal
    max_invoice_age_days: int
    currency: str


class MatchConfig(BaseModel):
    vendor_name_suffixes: list[str]
    vendor_fuzzy_min_score: int
    line_match_min_score: int
    implied_po_points_amount_fits: int
    implied_po_points_description: int
    implied_po_points_date: int
    implied_po_strong_score: int


class RulesThresholds(BaseModel):
    po_overage_max_percent: Decimal
    po_overage_max_rupees: Decimal
    price_variance_max_percent: Decimal
    duplicate_max_extra_characters: int


class RulesConfig(BaseModel):
    validate_: ValidateConfig
    match: MatchConfig
    rules: RulesThresholds


def load_rules(path: Path = RULES_FILE) -> RulesConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    # "validate" is a reserved name on pydantic models, so the section is stored as validate_.
    return RulesConfig(validate_=raw["validate"], match=raw["match"], rules=raw["rules"])


@lru_cache
def default_rules() -> RulesConfig:
    """The rules in config/rules.yaml, read once."""
    return load_rules()
