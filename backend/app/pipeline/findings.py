"""A finding is the result of one check (SPEC section 3.1).

status    what happened to the check:        pass | warn | fail | skipped
severity  what it means for the decision:    info | review | reject

The two are separate on purpose. A small PO overage is a `warn` that still lets the invoice be
approved (severity info); a suggested PO is a `warn` that needs a person (severity review).
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

Stage = Literal["validate", "match", "rules"]
Status = Literal["pass", "warn", "fail", "skipped"]
Severity = Literal["info", "review", "reject"]
Owner = Literal["ap", "procurement", "vendor", "none"]


class Finding(BaseModel):
    code: str  # machine-readable, e.g. "PO_BALANCE"
    stage: Stage
    status: Status
    severity: Severity
    message: str  # one plain-English sentence with the real numbers in it
    owner: Owner
    data: dict[str, Any] = Field(default_factory=dict)  # the values used, for display


def passed(code: str, stage: Stage, message: str, **data: Any) -> Finding:
    return Finding(code=code, stage=stage, status="pass", severity="info", message=message,
                   owner="none", data=data)


def warned(code: str, stage: Stage, message: str, severity: Severity = "info",
           owner: Owner = "none", **data: Any) -> Finding:
    return Finding(code=code, stage=stage, status="warn", severity=severity, message=message,
                   owner=owner, data=data)


def failed(code: str, stage: Stage, message: str, severity: Severity, owner: Owner,
           **data: Any) -> Finding:
    return Finding(code=code, stage=stage, status="fail", severity=severity, message=message,
                   owner=owner, data=data)


def plural(count: int, noun: str) -> str:
    """'1 line', '2 lines'."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def skipped(code: str, stage: Stage, reason: str) -> Finding:
    """A check that could not run. The message says why."""
    return Finding(code=code, stage=stage, status="skipped", severity="info",
                   message=f"Not checked: {reason}", owner="none")
