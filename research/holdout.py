"""Global holdout-access registry (derived from the ledger; independent of hypothesis id, version or family).

A confirmation holdout is a (market instrument, time range) pair. Whether it is still untouched is a
property of the DATA, not of the hypothesis that claims it, so every check here ignores
hypothesis_id, hypothesis_version, family_id, run_id and snapshot names. Only the instruments named in
the frozen preregistration `datasets` and the preregistered test range matter.

Exposure policy (explicit, conservative):
* A trial's declared test range is CONFIRMATION-EXPOSED (it can never again back an UNTOUCHED claim) when
    - the preregistration claimed UNTOUCHED: from the moment the trial is recorded STARTED, because a crash
      leaves the number of reads unknowable; or
    - the trial reports test_access_count >= 1 (observed read); or
    - the trial ended without a COMPLETED status (FAILED / ABORTED / INTERRUPTED / STARTED: access unknowable).
* An EXPLORATORY_OR_REUSED / CONSUMED_LEGACY trial that COMPLETED with test_access_count == 0 did not touch
  its test range and exposes nothing. Exploratory reads of train/validation ranges are recorded in the
  per-trial audit trail (ranges stay in the trial and preregistration) but do NOT consume a confirmation
  holdout by themselves; they are surfaced as a limitation instead of being treated as consumption.
* The Stage 02 test window (contracts.LEGACY_CONSUMED_WINDOW) is consumed for every instrument.
* Correlated-instrument contamination (e.g. BTC vs ETH) is NOT modelled; it is a stated limitation.
"""
from __future__ import annotations
from .contracts import LEGACY_CONSUMED_WINDOW, parse_utc

ENFORCED = "IN_MEMORY_BROKERED"


def instruments_of(prereg: dict) -> frozenset:
    return frozenset(d["instrument_id"] for d in prereg["datasets"])


def overlaps(a: dict, b: dict) -> bool:
    return parse_utc(a["start_utc"]) < parse_utc(b["end_utc"]) and parse_utc(b["start_utc"]) < parse_utc(a["end_utc"])


def legacy_overlap(rng: dict) -> bool:
    return overlaps(rng, {"start_utc": LEGACY_CONSUMED_WINDOW[0], "end_utc": LEGACY_CONSUMED_WINDOW[1]})


def _consumes(trial: dict, meta: dict) -> bool:
    if "test_range" not in trial:
        return False
    if meta["claimed_untouched"] or trial["test_access_count"] >= 1:
        return True
    return trial["status"] != "COMPLETED"


def exposures(view) -> list:
    """Every consuming test-range exposure, oldest first: [{trial_id, seq, instruments, range, ...}]."""
    rows = []
    for tid, meta in sorted(view.trial_meta.items(), key=lambda kv: kv[1]["seq"]):
        t = view.trials[tid]
        if _consumes(t, meta):
            rows.append({"trial_id": tid, "seq": meta["seq"], "instruments": meta["instruments"], "range": t["test_range"],
                         "hypothesis": [t["hypothesis_id"], t["hypothesis_version"]], "family_id": t["family_id"],
                         "purpose": "CONFIRMATION" if meta["claimed_untouched"] else "EXPLORATORY_TEST_ACCESS"})
    return rows


def conflicts(view, instruments, test_range: dict, *, before_seq=None) -> list:
    """Reasons an UNTOUCHED claim over (instruments, test_range) is invalid. Empty list = still untouched."""
    out = []
    if legacy_overlap(test_range):
        out.append("LEGACY_CONSUMED_WINDOW")
    for row in exposures(view):
        if before_seq is not None and row["seq"] >= before_seq:
            continue
        if set(instruments) & set(row["instruments"]) and overlaps(test_range, row["range"]):
            out.append(f"EXPOSED_BY:{row['trial_id']}")
    return out


def registry_digest(view) -> str:
    from .identifiers import digest
    return digest([{k: r[k] for k in ("trial_id", "seq", "instruments", "range", "purpose")} for r in exposures(view)])


def integrity(view, trial: dict, prereg: dict, enforcement: str) -> str:
    """holdout_integrity the adjudicator may claim for this trial (never stronger than the registry allows)."""
    if trial["holdout_class"] == "CONSUMED_LEGACY" or prereg["splits"]["holdout_class"] == "CONSUMED_LEGACY":
        return "CONSUMED_LEGACY"
    meta = view.trial_meta.get(trial["trial_id"])
    if (prereg["splits"]["holdout_class"] == "UNTOUCHED" and trial["holdout_class"] == "UNTOUCHED" and meta is not None
            and "test_range" in trial and trial["test_access_count"] >= 1 and enforcement == ENFORCED
            and not conflicts(view, instruments_of(prereg), trial["test_range"], before_seq=meta["seq"])):
        return "UNTOUCHED"
    return "EXPLORATORY_OR_REUSED"
