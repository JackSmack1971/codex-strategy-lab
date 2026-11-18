"""Leakage, purging and embargo checks (structural; no statistical thresholds are chosen here)."""
from __future__ import annotations
from datetime import timedelta

from ..contracts import parse_utc


def label_overlap_issues(train_end_utc: str, validation_start_utc: str, *, label_horizon_s: int, embargo_s: int) -> list:
    """Training labels reaching into validation (or an embargo shorter than the horizon) are leakage.

    The horizon and embargo come from the frozen preregistration; they are required arguments.
    """
    for name, v in (("label_horizon_s", label_horizon_s), ("embargo_s", embargo_s)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError(f"{name} must be a non-negative integer from the preregistration")
    gap = parse_utc(validation_start_utc) - parse_utc(train_end_utc)
    issues = []
    if gap < timedelta(seconds=label_horizon_s):
        issues.append("LABEL_OVERLAP")          # last training label is still unresolved at validation start
    if gap < timedelta(seconds=embargo_s):
        issues.append("EMBARGO_TOO_SHORT")
    if gap < timedelta(0):
        issues.append("SPLIT_OVERLAP")
    return sorted(issues)


def leakage_audit(samples) -> dict:
    """samples: [{"decision_at": utc, "features": {name: available_at_utc | "UNKNOWN"}}].

    A feature whose availability is after the decision (or unknown) is inadmissible. Returns
    violations per feature so a seeded future-label feature is caught structurally.
    """
    violations, checked = {}, 0
    for i, s in enumerate(samples):
        d = parse_utc(s["decision_at"])
        for name, avail in sorted(s["features"].items()):
            checked += 1
            if avail == "UNKNOWN":
                violations.setdefault(name, []).append((i, "AVAILABLE_UNKNOWN"))
            elif parse_utc(avail) > d:
                violations.setdefault(name, []).append((i, "AVAILABLE_AFTER_DECISION"))
    return {"ok": not violations, "checked": checked, "violations": violations}
