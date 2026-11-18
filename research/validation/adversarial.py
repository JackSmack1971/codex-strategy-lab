"""Machine-checkable objections. Status comes only from an executed test, never from debate.

Supported executable specs: LEAKAGE_AUDIT (claim: a feature is unavailable at decision time),
COST_STRESS (claim: mean net return at multiplier m is <= 0 - the definition of 'no net edge',
not a tuned threshold) and LABEL_OVERLAP (claim: split violates the preregistered horizon/embargo).
MANUAL_POLICY objections can only be UNRESOLVED_POLICY; they are never auto-resolved.
Reviewer text is data: only the typed spec and supplied evidence are read.
"""
from __future__ import annotations
from ..contracts import require_valid
from ..identifiers import digest
from . import economics, timing


def _run(spec, evidence):
    t, p = spec["type"], spec["params"]
    if t == "LEAKAGE_AUDIT":
        rep = timing.leakage_audit(evidence["samples"])
        return (not rep["ok"]), {"violations": {k: len(v) for k, v in sorted(rep["violations"].items())}, "checked": rep["checked"]}
    if t == "COST_STRESS":
        m = p["multiplier"]
        met = economics.recompute_metrics(evidence["returns"], cost_per_trade=evidence["cost_per_trade"], stress_multipliers=[m])
        v = met[f"mean_net_return_stress_x{m}"]
        return (v is None or v <= 0), {"mean_net_return_stress": v, "multiplier": m, "n": met["n_trades"]}
    if t == "LABEL_OVERLAP":
        issues = timing.label_overlap_issues(evidence["train_end_utc"], evidence["validation_start_utc"],
                                             label_horizon_s=p["label_horizon_s"], embargo_s=p["embargo_s"])
        return bool(issues), {"issues": issues}
    raise ValueError(f"unsupported test type {t!r}")


def execute(objection: dict, evidence: dict, executed_at_utc: str) -> dict:
    """Return a copy of the objection with status/test_result set from the executed test."""
    require_valid("objection", objection)
    spec = objection["test_specification"]
    out = dict(objection)
    if spec["type"] == "MANUAL_POLICY":
        out["adjudication_status"] = "UNRESOLVED_POLICY"
        out.pop("test_result", None)
    else:
        claim_holds, result = _run(spec, evidence)
        out["adjudication_status"] = "UPHELD" if claim_holds else "REFUTED"
        out["test_result"] = {"executed_at_utc": executed_at_utc, "result_sha256": digest(result),
                              "outcome": "CLAIM_HOLDS" if claim_holds else "CLAIM_FAILS"}
    require_valid("objection", out)
    return out


def review_outcome(objections) -> dict:
    """REVIEW_RECORDED only when every MATERIAL objection is REFUTED; otherwise BLOCKED (blueprint section 6)."""
    blocking = sorted(o["objection_id"] for o in objections
                      if o["materiality"] == "MATERIAL" and o["adjudication_status"] != "REFUTED")
    return {"state": "BLOCKED" if blocking else "REVIEW_RECORDED", "blocking": blocking,
            "evidence_refs": sorted(f"objection:{o['objection_id']}:{digest(o)[:16]}" for o in objections)}
