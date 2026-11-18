"""Claim -> evidence index. Every statement in a report must cite recorded fields or artifact hashes."""
from __future__ import annotations


def build_index(record: dict, trial: dict, artifact_hashes: dict, family: dict) -> dict:
    """Claims keyed by id; each has the statement text and the sources it was derived from."""
    idx = {
        "C-decision": {"statement": f"Deterministic decision: {record['decision']}",
                       "sources": [f"adjudication.decision_rule_digest={record['decision_rule_digest']}",
                                   f"adjudication.adjudication_code_digest={record['adjudication_code_digest']}"]},
        "C-holdout": {"statement": f"Holdout integrity: {record['holdout_integrity']} (test accesses: {trial['test_access_count']})",
                      "sources": [f"trial.holdout_class={trial['holdout_class']}",
                                  f"trial.test_access_count={trial['test_access_count']}"]},
        "C-family": {"statement": f"{family['trials_total']} trial(s) charged to family {family['family_id']}: {family['by_status']}",
                     "sources": [f"adjudication.family_multiplicity_ref={record['family_multiplicity_ref']}"]},
    }
    for g in record["gate_results"]:
        refs = list(g["proof_refs"]) or ["no proof recorded (value is not PASS)"]
        if g["gate_id"].startswith("sys-"):
            src = refs
        else:
            src = refs + [f"artifact:{n}={h}" for n, h in sorted(artifact_hashes.items()) if n == "metrics.json"]
        idx[f"C-gate-{g['gate_id']}"] = {
            "statement": f"Gate {g['gate_id']} ({'mandatory' if g['mandatory'] else 'informational'}): {g['value']}",
            "sources": src}
    return idx
