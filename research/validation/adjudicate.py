"""Deterministic adjudication from VERIFIED evidence (no agent prose, no manual override, no self-reported metric).

Thresholds come only from the frozen preregistration. Gate VALUES come only from metrics this package
recomputed from verified execution artifacts (economics.evaluate); an experiment's own metrics.json is
descriptive input that must agree with the recomputation or the evaluation is BLOCKED.

Gate values: PASS | FAIL | UNKNOWN | NOT_APPLICABLE. Missing / None / non-finite metric => UNKNOWN.
Gate families (all mandatory unless the preregistration marks a gate informational):
  sys-*   evidence integrity (binding, artifacts, census, dataset, review, execution, recompute, cost model)
  core-*  gates no preregistration can omit: minimum sample, positive net return at EVERY frozen cost
          stress, and the multiplicity-adjusted p-value against the frozen alpha
  other   the preregistered gate_rules

Precedence (PRECEDENCE_VERSION):
  1. any sys-* gate not PASS                          -> BLOCKED  (missing/unverifiable evidence)
  2. any mandatory gate FAIL                          -> REJECT   (established preregistered failure)
  3. any mandatory gate UNKNOWN                       -> BLOCKED  (required evidence is missing, blueprint 8)
  4. any mandatory gate NOT_APPLICABLE                -> INVESTIGATE
  5. all mandatory PASS and holdout UNTOUCHED         -> QUALIFIED   (research-qualified only)
  6. all mandatory PASS otherwise                     -> PROMISING_UNVALIDATED
A strong aggregate metric never substitutes for a failing mandatory gate; agent agreement is not an input.
"""
from __future__ import annotations
import math
from pathlib import Path

from ..contracts import require_valid
from ..identifiers import digest, sha256_hex
from . import economics
from . import multiple_testing as mt

PRECEDENCE_VERSION = "adjudication-precedence-2"
DERIVATION_VERSION = "derive-1"
_COMPARE = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
_ENGINE_FILES = ("validation/adjudicate.py", "validation/economics.py", "validation/multiple_testing.py",
                 "validation/derive.py", "holdout.py")


def code_digest() -> str:
    """Digest of the decision engine; CRLF/LF-normalised so a Windows checkout hashes like a Linux one."""
    root = Path(__file__).resolve().parent.parent
    h = []
    for rel in _ENGINE_FILES:
        p = root / rel
        h.append(sha256_hex(p.read_bytes().replace(b"\r\n", b"\n")) if p.is_file() else "MISSING")
    return digest({"files": dict(zip(_ENGINE_FILES, h))})


def rule_digest(prereg: dict) -> str:
    return digest({"precedence": PRECEDENCE_VERSION, "gate_rules": prereg["gate_rules"],
                   "multiplicity": prereg["multiplicity"], "economics": prereg["economics"],
                   "purge": prereg["purge"], "min_sample_size": prereg["min_sample_size"],
                   "holdout_class": prereg["splits"]["holdout_class"]})


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _sys(gate_id, ok, proof):
    return {"gate_id": gate_id, "mandatory": True, "value": "PASS" if ok else "FAIL",
            "proof_refs": [proof] if ok else []}


def _metric_gate(gate_id, mandatory, metric, comparator, threshold, values, source):
    x = values.get(metric)
    if not _finite(x):
        return {"gate_id": gate_id, "mandatory": mandatory, "value": "UNKNOWN", "proof_refs": []}
    ok = _COMPARE[comparator](x, threshold)
    return {"gate_id": gate_id, "mandatory": mandatory, "value": "PASS" if ok else "FAIL",
            "proof_refs": [f"{source}:{metric}={x!r} {comparator} {threshold!r}"]}


def adjudicate(*, prereg: dict, trial: dict, reported: dict, recomputed: dict, execution_problem, artifact_check: dict,
               data_check: dict, review_check: dict, family: dict, holdout_integrity: str, enforcement: str,
               bindings: dict, created_at_utc: str, not_applicable=()) -> dict:
    """Build and validate the adjudication record. Every argument is verified evidence, not a claim."""
    prereg_sha = require_valid("preregistration", prereg)
    m = family["trials_total"]
    method = prereg["multiplicity"]["method"]
    values = dict(recomputed)
    if _finite(values.get("p_value")) and method in mt.SUPPORTED_METHODS:
        values["p_value_adjusted"] = mt.adjust_p(method, values["p_value"], m)
    mismatch = economics.compare_metrics(reported, recomputed) if recomputed else []
    eco = prereg["economics"]
    sys_gates = [
        _sys("sys-prereg-binding", trial["preregistration_sha256"] == prereg_sha and trial["hypothesis_id"] == prereg["hypothesis_id"]
             and trial["family_id"] == prereg["family_id"], f"trial:{trial['trial_id']}"),
        _sys("sys-cost-model-bound", trial["cost_model_hash"] == digest(eco), f"economics:{digest(eco)[:16]}"),
        _sys("sys-artifact-integrity", bool(artifact_check.get("ok")), f"manifest:{trial.get('artifact_manifest_hash', 'NONE')}"),
        _sys("sys-execution-verified", execution_problem is None and bool(recomputed), "execution.json re-derived from fills"),
        _sys("sys-independent-recompute", not mismatch and bool(recomputed), "recomputed-from-fills"),
        _sys("sys-trial-census", not family["unfinished"] and m <= prereg["research_budget"]["max_trials"]
             and trial["status"] == "COMPLETED", f"family:{family['family_id']}:{m}"),
        _sys("sys-data-qualified", bool(data_check.get("ok")), f"dataset:{','.join(data_check.get('bundles', []))}"),
        _sys("sys-review-recorded", bool(review_check.get("ok")), f"review:{review_check.get('review_sha256')}"),
        _sys("sys-multiplicity-method", method in mt.SUPPORTED_METHODS, f"method:{method}"),
        _sys("sys-test-access-declared", not (trial["test_access_count"] > 0 and "test" not in prereg["splits"]), "prereg-splits"),
    ]
    core = [_metric_gate("core-min-sample", True, "n_trades", ">=", prereg["min_sample_size"], values, "recomputed")]
    for mult in eco["stress_multipliers"]:
        met = economics.stress_metric(mult)
        core.append(_metric_gate(f"core-net-edge-stress-x{economics._mk(mult)}", True, met, ">", 0, values, "recomputed"))
    core.append(_metric_gate("core-multiplicity", True, "p_value_adjusted", "<=", prereg["multiplicity"]["alpha"], values, "recomputed"))
    gates = []
    for g in prereg["gate_rules"]["gates"]:
        if g["gate_id"] in set(not_applicable):
            gates.append({"gate_id": g["gate_id"], "mandatory": g["mandatory"], "value": "NOT_APPLICABLE", "proof_refs": []})
        else:
            gates.append(_metric_gate(g["gate_id"], g["mandatory"], g["metric"], g["comparator"], g["threshold"], values, "recomputed"))
    mandatory = core + [g for g in gates if g["mandatory"]]
    if any(g["value"] != "PASS" for g in sys_gates):
        decision = "BLOCKED"
    elif any(g["value"] == "FAIL" for g in mandatory):
        decision = "REJECT"
    elif any(g["value"] == "UNKNOWN" for g in mandatory):
        decision = "BLOCKED"
    elif any(g["value"] != "PASS" for g in mandatory):
        decision = "INVESTIGATE"
    elif holdout_integrity == "UNTOUCHED":
        decision = "QUALIFIED"
    else:
        decision = "PROMISING_UNVALIDATED"
    estimate = values.get("economic_estimate")
    record = {
        "schema_version": "1.0.0", "hypothesis_id": trial["hypothesis_id"], "hypothesis_version": trial["hypothesis_version"],
        "run_id": trial["run_id"], "gate_results": sys_gates + core + gates,
        "family_multiplicity_ref": f"{family['family_id']}:{m}:{digest(family)[:16]}",
        "economic_estimate": estimate if _finite(estimate) else "UNKNOWN",
        "uncertainty_method": prereg["uncertainty_method"],
        "data_limitations": list(data_check.get("limitations", [])) + [f"dataset_manifest:{s}" for s in data_check.get("manifests", [])],
        "execution_limitations": [
            "cost model is the preregistered assumption; fills are recorded fills of the experiment, not verified exchange fills",
            f"data access enforcement: {enforcement}",
            "reviewer independence (separate agent context) is UNVERIFIED until Phase 6",
            "correlated-instrument contamination of the holdout is not modelled"],
        "holdout_integrity": holdout_integrity,
        "decision": decision, "decision_rule_digest": rule_digest(prereg), "adjudication_code_digest": code_digest(),
        "created_at_utc": created_at_utc, "evidence_bindings": bindings,
    }
    require_valid("adjudication", record)
    return record
