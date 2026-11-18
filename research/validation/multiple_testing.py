"""Family trial accounting and the multiplicity adjustments the preregistration may name.

Every attempted trial counts - failed, aborted, interrupted and superseded included. Supported
methods are the plain, standard ones below; anything else is reported as unsupported so the
adjudicator can block instead of guessing. Deflated Sharpe / PBO are NOT implemented here.
"""
from __future__ import annotations

SUPPORTED_METHODS = ("COUNT_ONLY", "BONFERRONI", "SIDAK")


def family_summary(view, family_id: str) -> dict:
    ids = sorted(view.family_trials.get(family_id, {}))
    by_status = {}
    for tid in ids:
        st = view.trials[tid]["status"]
        by_status[st] = by_status.get(st, 0) + 1
    return {"family_id": family_id, "trials_total": len(ids), "by_status": dict(sorted(by_status.items())),
            "unfinished": [t for t in ids if view.trials[t]["status"] == "STARTED"], "trial_ids": ids}


def adjust_p(method: str, p: float, m: int):
    """Adjusted p-value for m family trials; None when the method is unsupported or inputs are invalid."""
    if method not in SUPPORTED_METHODS or not (0.0 <= p <= 1.0) or m < 1:
        return None
    if method == "BONFERRONI":
        return min(1.0, p * m)
    if method == "SIDAK":
        return 1.0 - (1.0 - p) ** m
    return p
