"""Re-derive an adjudication from authoritative state: ledger view + verified artifacts + evidence store.

This single function is used BOTH to create an adjudication (pipeline) and to check one on append and
on every replay (ledger), so a recorded decision can never differ from what the rules derive.
It reads nothing the experiment could have pre-baked except the artifacts, which are verified against
hashes recorded by the harness and then re-computed, never trusted.
"""
from __future__ import annotations
from pathlib import Path

from .. import holdout
from ..contracts import ContractError, parse_utc
from ..evidence_store import EvidenceError, EvidenceStore, Unavailable, verify_dataset_bundle, verify_review_bundle
from ..identifiers import digest
from ..experiments import isolation
from . import adjudicate as adj
from . import economics, multiple_testing


class Evidence:
    """Where verified evidence lives: the ledger's evidence store and the isolated run directories."""

    def __init__(self, ledger_root, runs_root=None):
        self.store = EvidenceStore(ledger_root)
        self.runs_root = Path(runs_root) if runs_root else Path(ledger_root).parent / "research-runs"

    def run_dir(self, run_id):
        p = self.runs_root / run_id
        return p if p.is_dir() else None


def _data_check(h, prereg, store):
    """Re-derive every dataset qualification the ledger recorded and bind it to the preregistered datasets."""
    problems, bundles, manifests, unavailable, limits = [], [], {}, False, []
    for sha in h["certs"]:
        try:
            info = verify_dataset_bundle(store, sha)
        except Unavailable:
            unavailable = True
            problems.append(f"UNAVAILABLE:{sha[:12]}")
            continue
        except EvidenceError as exc:
            problems.append(f"{exc.code}:{sha[:12]}")
            continue
        bundles.append(sha)
        manifests[info["manifest_sha256"]] = info
        limits = sorted(set(limits) | set(info["limitations"]))
    sp = prereg["splits"]
    first = min(parse_utc(sp[k]["start_utc"]) for k in sp if k != "holdout_class")
    last = parse_utc(sp[prereg["economics"]["evaluation_split"]]["end_utc"])
    for d in prereg["datasets"]:
        info = manifests.get(d["manifest_sha256"])
        if info is None:
            problems.append(f"DATASET_NOT_QUALIFIED:{d['snapshot_id']}")
            continue
        if info["instrument_id"] != d["instrument_id"]:
            problems.append(f"INSTRUMENT_MISMATCH:{d['snapshot_id']}")
        c = info["criteria"]
        if parse_utc(c["require_start_utc"]) > first or parse_utc(c["require_end_utc"]) < last:
            problems.append(f"COVERAGE_DOES_NOT_CONTAIN_SPLITS:{d['snapshot_id']}")
    return {"ok": not problems and bool(bundles), "problems": problems, "bundles": sorted(bundles), "limitations": limits,
            "manifests": sorted(manifests)}, unavailable


def _review_check(h, hk, store):
    if not h.get("review_ref"):
        return {"ok": False, "problems": ["NO_REVIEW"]}, False
    try:
        info = verify_review_bundle(store, h["review_ref"], hk[0], hk[1])
    except Unavailable:
        return {"ok": False, "problems": ["UNAVAILABLE"], "review_sha256": h["review_ref"]}, True
    except (EvidenceError, ContractError) as exc:
        return {"ok": False, "problems": [str(getattr(exc, "code", "REVIEW_INVALID"))], "review_sha256": h["review_ref"]}, False
    return {"ok": True, "review_sha256": info["review_sha256"]}, False


def derive(view, trial_id: str, evidence: Evidence, *, created_at_utc: str, not_applicable=()):
    """Return (record, unavailable). `unavailable` is True when evidence is absent (not when it disagrees)."""
    trial = view.trials[trial_id]
    hk = (trial["hypothesis_id"], trial["hypothesis_version"])
    h = view.hyp[hk]
    prereg = h["prereg"]
    run = view.runs.get(trial["run_id"], {})
    hashes = run.get("artifact_hashes", {})
    enforcement = run.get("data_access_enforcement", "IN_PROCESS_UNENFORCED")
    run_dir = evidence.run_dir(trial["run_id"])
    unavailable = run_dir is None
    if run_dir is None:
        check = {"ok": False, "problems": ["RUN_DIR_UNAVAILABLE"]}
    elif not hashes:
        check = {"ok": False, "problems": ["NO_ARTIFACTS_RECORDED"]}
    else:
        check = isolation.verify_artifacts(run_dir, hashes, trial.get("artifact_manifest_hash", ""))
    reported, recomputed, problem = {}, {}, "ARTIFACTS_UNVERIFIED"
    if check["ok"]:
        try:
            reported = isolation.load_artifact(run_dir, "metrics.json") if "metrics.json" in hashes else {}
            recomputed = economics.evaluate(isolation.load_artifact(run_dir, "execution.json"), prereg)
            problem = None
        except economics.ExecutionError as exc:
            problem = str(exc)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problem = f"UNREADABLE:{type(exc).__name__}"
    data_check, data_unavail = _data_check(h, prereg, evidence.store)
    review_check, review_unavail = _review_check(h, hk, evidence.store)
    family = multiple_testing.family_summary(view, trial["family_id"])
    integrity = holdout.integrity(view, trial, prereg, enforcement)
    bindings = {
        "derivation_version": adj.DERIVATION_VERSION, "trial_digest": digest(trial), "prereg_sha256": h["prereg_sha"],
        "artifact_manifest_hash": trial.get("artifact_manifest_hash", "NONE"), "run_artifacts_digest": digest(hashes),
        "dataset_bundles": data_check["bundles"], "review_sha256": h.get("review_ref") or "NONE",
        "holdout_registry_digest": holdout.registry_digest(view), "data_access_enforcement": enforcement,
        "family_digest": digest(family), "recomputed_digest": digest(recomputed), "execution_problem": problem or "NONE"}
    record = adj.adjudicate(prereg=prereg, trial=trial, reported=reported, recomputed=recomputed, execution_problem=problem,
                            artifact_check=check, data_check=data_check, review_check=review_check, family=family,
                            holdout_integrity=integrity, enforcement=enforcement, bindings=bindings,
                            created_at_utc=created_at_utc, not_applicable=not_applicable)
    return record, (unavailable or data_unavail or review_unavail)
