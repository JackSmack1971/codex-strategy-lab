"""Test helper: drive a synthetic hypothesis through the ledger. Fixture data only."""
import itertools
import tempfile
from pathlib import Path

from research.identifiers import digest
from research.ledger import Ledger
from research.prereg import freeze, prereg_digest
from research.validation import adversarial
from tests.research import builders as b

ACTOR = {"category": "SCRIPT", "id": "test-runner"}
HID, VER = "hyp-synthetic-001", 1


def review_bundle(hid=None, ver=None):
    """A deterministic, executed review: one material LEAKAGE_AUDIT objection that is REFUTED on clean samples."""
    obj = {"schema_version": "1.0.0", "objection_id": "obj-fixture-leak", "hypothesis_id": hid or HID, "hypothesis_version": ver or VER,
           "review_type": "causal", "claim": "a feature is unavailable at decision time", "assumptions": ["fixture"],
           "test_specification": {"type": "LEAKAGE_AUDIT", "params": {}}, "artifact_dependencies": ["fixture"],
           "severity": "HIGH", "materiality": "MATERIAL", "adjudication_status": "PENDING", "reviewer_agent_id": "fixture-reviewer",
           "reviewer_context_digest": "c" * 64, "submitted_at_utc": "2026-01-01T00:00:00Z"}
    ev = {"samples": [{"decision_at": "2026-01-01T00:00:00Z", "features": {"momentum": "2026-01-01T00:00:00Z"}}]}
    return {"objections": [adversarial.execute(obj, ev, "2026-01-01T00:00:05Z")], "evidence": {"obj-fixture-leak": ev}}


def evidence_refs(led, target, hid=HID, ver=VER, instrument="SYN-USD"):
    """Real, verifiable evidence references for a transition target (stored in the ledger's evidence store)."""
    if target == "DATA_QUALIFIED":
        return [f"dataset-qualification:{led.evidence.store.put(b.dataset_bundle(instrument))}"]
    if target == "REVIEW_RECORDED":
        return [f"review:{led.evidence.store.put(review_bundle(hid, ver))}"]
    return ["evidence:fixture"]


def make_clock(start_minute=0):
    counter = itertools.count(start_minute)
    return lambda: f"2026-01-01T{(next(counter) // 60) % 24:02d}:{next(counter) % 60:02d}:00Z"


def seq_clock():
    n = itertools.count(1)
    return lambda: "2026-02-01T00:00:00.%06dZ" % next(n)


def new_ledger(root=None, **kw):
    root = root or tempfile.mkdtemp(prefix="research-ledger-")
    kw.setdefault("clock", seq_clock())
    return Ledger(root, **kw)


def prereg(max_trials=4, **over):
    rec = b.preregistration(**over)
    rec["research_budget"]["max_trials"] = max_trials
    rec["multiplicity"]["planned_trials"] = min(rec["multiplicity"]["planned_trials"], max_trials)
    return rec


def trial_for(pre, n=1, status="STARTED", **over):
    sp = pre["splits"]
    over.setdefault("cost_model_hash", digest(pre["economics"]))
    rec = b.trial(trial_id=f"trial-{n:04d}", trial_sequence=n, run_id=f"run-{n:04d}",
                  preregistration_sha256=prereg_digest(pre), train_range=sp["train"],
                  validation_range=sp["validation"], test_range=sp["test"],
                  holdout_class=sp["holdout_class"], status=status, **over)
    return rec


def to_state(led, target, hid=HID, ver=VER, pre=None, **hyp_over):
    """Register the hypothesis and walk it to `target` using real ledger operations."""
    led.register_hypothesis(b.hypothesis(hypothesis_id=hid, hypothesis_version=ver, **hyp_over), ACTOR, "register")
    if target == "REGISTERED":
        return
    for st in ["DATA_PENDING", "DATA_QUALIFIED", "REVIEW_PENDING", "REVIEW_RECORDED"]:
        led.transition(hid, ver, st, ACTOR, f"to {st}", evidence_refs(led, st, hid, ver))
        if st == target:
            return
    freeze(led, pre or prereg(), ACTOR, "freeze")
    if target == "PREREG_FROZEN":
        return
    led.transition(hid, ver, "EXPERIMENT_PENDING", ACTOR, "start", ["evidence:fixture"])


def record_trial(led, rec, subject_extra=None):
    subject = {"hypothesis_id": rec["hypothesis_id"], "hypothesis_version": rec["hypothesis_version"],
               "trial_id": rec["trial_id"]}
    return led.append("TRIAL_RECORDED", subject=subject, payload=rec, actor=ACTOR, reason="trial",
                      idempotency_key=f"trial-{rec['trial_id']}-{rec['status']}")


def finish_trial(led, rec, status="COMPLETED", **over):
    new = dict(rec, status=status, end_time="2026-03-01T00:00:00Z", **over)
    if status == "FAILED":
        new.setdefault("failure_code", "E_FIXTURE")
    return record_trial(led, new)
