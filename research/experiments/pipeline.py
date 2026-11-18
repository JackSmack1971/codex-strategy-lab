"""Record the deterministic adjudication of one trial in the ledger.

The decision is NOT assembled here from caller-supplied evidence. validation.derive re-reads the
verified artifacts, the evidence store and the ledger state, and the ledger itself re-derives the same
record on append and on every replay; a record that differs is rejected. Nothing reads agent prose.
"""
from __future__ import annotations

from ..identifiers import derived_id, digest
from ..ledger import LedgerError
from ..validation.derive import derive


def adjudicate_trial(ledger, repo, trial_id: str, actor: dict, *, not_applicable=(), record_it=True):
    """Returns {"record": adjudication, "recorded": bool, "note": str|None, "evidence_unavailable": bool}."""
    view = ledger.view()
    trial = view.trials[trial_id]
    hk = (trial["hypothesis_id"], trial["hypothesis_version"])
    record, unavailable = derive(view, trial_id, ledger.evidence, created_at_utc=ledger.clock(), not_applicable=not_applicable)
    if not record_it:
        return {"record": record, "recorded": False, "note": None, "evidence_unavailable": unavailable}
    subject = {"hypothesis_id": hk[0], "hypothesis_version": hk[1]}
    try:
        if view.hyp[hk]["state"] == "EXPERIMENT_PENDING":
            ledger.transition(hk[0], hk[1], "EXPERIMENT_COMPLETE", actor, "trials resolved", [f"run:{trial['run_id']}"])
        ledger.append("ADJUDICATION_RECORDED", subject=subject, payload=record, actor=actor, reason="deterministic adjudication",
                      idempotency_key=derived_id("adjudication", digest(record)))
    except (LedgerError, ValueError) as exc:
        return {"record": record, "recorded": False, "note": f"{getattr(exc, 'code', type(exc).__name__)}: {exc}",
                "evidence_unavailable": unavailable}
    return {"record": record, "recorded": True, "note": None, "evidence_unavailable": unavailable}
