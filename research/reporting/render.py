"""Deterministic Markdown + JSON report from recorded evidence (no timestamps of its own, no prose generation)."""
from __future__ import annotations

from ..identifiers import canonical_bytes, digest
from . import evidence

DISCLAIMER = ("This report states what recorded evidence shows under the preregistered rules. QUALIFIED means "
              "research-qualified only: it is not a performance claim, trading recommendation or deployment approval.")


def build_report(*, record: dict, trial: dict, family: dict, artifact_hashes: dict, preregistration_sha256: str,
                 data_kind: str, objections=()) -> dict:
    idx = evidence.build_index(record, trial, artifact_hashes, family)
    body = {
        "report_version": 1, "data_kind": data_kind, "disclaimer": DISCLAIMER,
        "hypothesis": {"id": record["hypothesis_id"], "version": record["hypothesis_version"]},
        "run_id": record["run_id"], "decision": record["decision"], "holdout_integrity": record["holdout_integrity"],
        "economic_estimate": record["economic_estimate"],
        "gates": [{"gate_id": g["gate_id"], "mandatory": g["mandatory"], "value": g["value"], "proof_refs": g["proof_refs"]}
                  for g in record["gate_results"]],
        "family": family,
        "objections": [{"objection_id": o["objection_id"], "review_type": o["review_type"],
                        "materiality": o["materiality"], "status": o["adjudication_status"]}
                       for o in sorted(objections, key=lambda o: o["objection_id"])],
        "data_limitations": record["data_limitations"], "execution_limitations": record["execution_limitations"],
        "hashes": {"preregistration_sha256": preregistration_sha256, "decision_rule_digest": record["decision_rule_digest"],
                   "adjudication_code_digest": record["adjudication_code_digest"],
                   "artifact_manifest_hash": trial.get("artifact_manifest_hash"),
                   "artifacts": dict(sorted(artifact_hashes.items()))},
        "evidence_index": idx,
    }
    body["report_sha256"] = digest(body)
    return body


def render_markdown(rep: dict) -> str:
    L = [f"# Research report: {rep['hypothesis']['id']} v{rep['hypothesis']['version']}", "",
         f"> **Data kind:** {rep['data_kind']}  ", f"> {rep['disclaimer']}", "",
         f"## Decision: {rep['decision']}", "",
         f"- Holdout integrity: {rep['holdout_integrity']}  _[C-holdout]_",
         f"- Economic estimate: {rep['economic_estimate']}",
         f"- Family: {rep['family']['trials_total']} attempted trial(s) {rep['family']['by_status']}  _[C-family]_", "",
         "## Gates", "", "| Gate | Mandatory | Value | Proof |", "|---|---|---|---|"]
    for g in rep["gates"]:
        L.append(f"| {g['gate_id']} | {'yes' if g['mandatory'] else 'no'} | {g['value']} | {'; '.join(g['proof_refs']) or '-'} |")
    L += ["", "## Objections", ""]
    L += [f"- {o['objection_id']} ({o['review_type']}, {o['materiality']}): {o['status']}" for o in rep["objections"]] or ["- none recorded"]
    L += ["", "## Limitations", ""] + [f"- {x}" for x in rep["data_limitations"] + rep["execution_limitations"]]
    h = rep["hashes"]
    L += ["", "## Hashes", "", f"- preregistration: `{h['preregistration_sha256']}`", f"- decision rule: `{h['decision_rule_digest']}`",
          f"- adjudication code: `{h['adjudication_code_digest']}`", f"- artifact manifest: `{h['artifact_manifest_hash']}`",
          f"- report: `{rep['report_sha256']}`", "", "## Evidence index", ""]
    for cid, c in sorted(rep["evidence_index"].items()):
        L.append(f"- **{cid}** {c['statement']} - sources: " + "; ".join(f"`{s}`" for s in c["sources"]))
    return "\n".join(L) + "\n"


def report_bytes(rep: dict) -> bytes:
    return canonical_bytes(rep)
