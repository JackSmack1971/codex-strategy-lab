"""Append-only, hash-chained JSONL evidence ledger (PROPOSED project tool).

Integrity model - read this before trusting it:
* A hash chain gives TAMPER EVIDENCE for the recorded events. It is not tamper
  prevention, not independent attestation, and says nothing about whether the
  recorded observations are true. Anyone who can rewrite the whole file can rebuild it.
* One writer at a time (exclusive lock file; contention fails closed after a short
  bounded wait; stale locks are never stolen automatically).
* Each event is one canonical-JSON line written with a single O_APPEND write plus fsync.
  A line is COMMITTED only if it is newline-terminated, schema-valid, hash-valid, chained
  to its predecessor and consistent with the lifecycle/ledger rules.
* Scan classes: OK | INCOMPLETE_TAIL (uncommitted partial last line - recoverable, only by
  explicit reconcile_tail which first preserves the bytes in quarantine/) |
  UNTERMINATED_VALID_TAIL (complete valid last event missing its newline - reconcile adds
  the newline, discards nothing) | CORRUPT (any committed record bad: never repaired,
  never truncated; a QUARANTINED marker is written and all appends fail closed).
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path

from . import holdout, lifecycle
from .contracts import ContractError, Issue, parse_utc, strict_loads, validate
from .evidence_store import (DATASET_PREFIX, REVIEW_PREFIX, EvidenceError, Unavailable, refs_with,
                             verify_dataset_bundle, verify_review_bundle)
from .identifiers import canonical_bytes, derived_id, digest, sha256_hex

GENESIS = "0" * 64
EVENT_PAYLOAD_KIND = {
    "HYPOTHESIS_REGISTERED": "hypothesis", "PREREG_FROZEN": "preregistration",
    "TRIAL_RECORDED": "trial", "RUN_RECORDED": "run_manifest",
    "ADJUDICATION_RECORDED": "adjudication",
}
TRIAL_TERMINAL = {"COMPLETED", "FAILED", "ABORTED", "INTERRUPTED"}
TRIAL_MUTABLE = {"status", "end_time", "metrics_ref", "failure_code", "artifact_manifest_hash",
                 "test_access_count"}
RUN_MUTABLE = {"status", "end_utc", "artifact_hashes", "tests_executed", "tests_failed", "recorded_at"}
GENERIC_TRANSITION_FORBIDDEN = {"REGISTERED", "PREREG_FROZEN", "ADJUDICATED"}


class LedgerError(Exception):
    code = "LEDGER_ERROR"

    def __init__(self, message, code=None):
        super().__init__(message)
        if code:
            self.code = code


class RuleViolation(LedgerError):
    """An event breaks lifecycle/ledger rules (code says which)."""


class StaleState(LedgerError):
    code = "STALE_STATE"


class LockHeld(LedgerError):
    code = "LOCK_HELD"


class LedgerCorrupt(LedgerError):
    code = "LEDGER_CORRUPT"


class LedgerNeedsReconcile(LedgerError):
    code = "NEEDS_RECONCILE"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _viol(code, msg):
    raise RuleViolation(msg, code)


# ------------------------------------------------------------------ state view
class View:
    """State derived by replaying committed events through the same rules used on append."""

    def __init__(self):
        self.head = GENESIS
        self.seq = 0
        self.last_ts = None
        self.idem = {}          # idempotency_key -> event
        self.hyp = {}           # (hid, ver) -> dict(state, digest, family, record, prereg, prereg_sha, prereg_amend)
        self.trials = {}        # trial_id -> latest trial record
        self.family_trials = {}  # family -> {trial_id: trial_sequence}
        self.runs = {}          # run_id -> latest manifest
        self.adjudications = []
        self.events = []
        self.trial_meta = {}     # trial_id -> {seq, instruments, claimed_untouched} (holdout registry source)
        self.evidence = None     # validation.derive.Evidence, or None for a chain-only scan
        self.strict_from_seq = None   # events at/after this seq must have their evidence present (append path)
        self.evidence_gaps = []  # evidence referenced by replayed events that this machine cannot verify
        self._cur_seq = 0

    @property
    def strict(self):
        return self.strict_from_seq is not None and self._cur_seq >= self.strict_from_seq

    def hkey(self, subject):
        return (subject.get("hypothesis_id"), subject.get("hypothesis_version"))

    def test_access(self, hid, ver):
        return sum(t["test_access_count"] for t in self.trials.values()
                   if (t["hypothesis_id"], t["hypothesis_version"]) == (hid, ver))

    def current_digest(self, hkey):
        h = self.hyp.get(hkey)
        return None if h is None else h["digest"]

    def unfinished_trials(self):
        return sorted(t["trial_id"] for t in self.trials.values() if t["status"] == "STARTED")

    def family_count(self, family_id):
        return len(self.family_trials.get(family_id, {}))


def _need_state(view, subject, allowed, what):
    h = view.hyp.get(view.hkey(subject))
    if h is None:
        _viol("UNKNOWN_HYPOTHESIS", f"{what}: hypothesis {view.hkey(subject)} is not registered")
    if h["state"] not in allowed:
        _viol("WRONG_STATE", f"{what}: state is {h['state']}, need one of {sorted(allowed)}")
    return h


def _versioned_update(existing, new, mutable_keys, id_name):
    for k in set(existing) | set(new):
        if k in mutable_keys:
            continue
        if existing.get(k) != new.get(k):
            _viol(f"{id_name.upper()}_ID_REUSE", f"{id_name} reused with different immutable field {k!r}")


def apply_event(view: View, ev: dict) -> None:
    """Apply one already-hashed event to the view; raises RuleViolation on any breach."""
    et, subj, pay = ev["event_type"], ev["subject"], ev["payload"]
    view._cur_seq = ev["seq"]          # first, so strict-evidence checks apply to THIS event
    new_state = None
    hk = view.hkey(subj)
    if et in EVENT_PAYLOAD_KIND:
        issues = validate(EVENT_PAYLOAD_KIND[et], pay)
        if issues:
            _viol("PAYLOAD_INVALID", f"{et} payload: {issues[0]}")

    if et == "HYPOTHESIS_REGISTERED":
        if (pay["hypothesis_id"], pay["hypothesis_version"]) != hk:
            _viol("SUBJECT_MISMATCH", "subject does not match hypothesis payload")
        if hk in view.hyp:
            _viol("HYPOTHESIS_VERSION_EXISTS", f"{hk} already registered; versions are immutable")
        ver = pay["hypothesis_version"]
        if ver > 1 and (pay["hypothesis_id"], ver - 1) not in view.hyp:
            _viol("VERSION_GAP", "version must follow an existing version")
        if ver > 1 and view.hyp[(pay["hypothesis_id"], ver - 1)]["family"] != pay["family_id"]:
            _viol("FAMILY_REASSIGNMENT", "a hypothesis keeps its research family across versions; a family "
                  "change needs a separately audited migration that carries the old multiplicity obligations (not implemented)")
        if ver == 1 and any(k[0] == pay["hypothesis_id"] for k in view.hyp):
            _viol("HYPOTHESIS_VERSION_EXISTS", "version 1 already exists for this id")
        new_state = "REGISTERED"
        view.hyp[hk] = {"state": None, "digest": None, "family": pay["family_id"], "record": pay,
                        "prereg": None, "prereg_sha": None, "amend": -1, "certs": [], "review_ref": None}
    elif et == "STATE_TRANSITION":
        h = view.hyp.get(hk)
        if h is None:
            _viol("UNKNOWN_HYPOTHESIS", f"{hk} is not registered")
        req = {"hypothesis_id", "hypothesis_version", "from_state", "to_state", "actor", "reason",
               "evidence_refs", "timestamp_utc", "prior_state_digest", "transition_digest"}
        if set(pay) != req:
            _viol("TRANSITION_MALFORMED", "transition record fields do not match the contract")
        body = {k: v for k, v in pay.items() if k != "transition_digest"}
        if digest(body) != pay["transition_digest"]:
            _viol("TRANSITION_DIGEST", "transition_digest does not match record")
        if (pay["hypothesis_id"], pay["hypothesis_version"]) != hk:
            _viol("SUBJECT_MISMATCH", "transition subject mismatch")
        if pay["from_state"] != h["state"]:
            _viol("WRONG_STATE", f"transition from {pay['from_state']} but state is {h['state']}")
        if pay["prior_state_digest"] != h["digest"]:
            raise StaleState("transition prior_state_digest is not the current state digest")
        try:
            lifecycle.check_transition(pay["from_state"], pay["to_state"])
        except ContractError as exc:
            _viol(exc.codes[0], str(exc))
        if pay["to_state"] in GENERIC_TRANSITION_FORBIDDEN:
            _viol("DEDICATED_EVENT_REQUIRED", f"{pay['to_state']} is reached only by its dedicated event")
        if pay["to_state"] != "DATA_PENDING" and not pay["evidence_refs"]:
            _viol("EVIDENCE_REQUIRED", "this transition needs evidence_refs")
        if pay["to_state"] == "EXPERIMENT_COMPLETE":
            mine = [t for t in view.trials.values() if (t["hypothesis_id"], t["hypothesis_version"]) == hk]
            if any(t["status"] == "STARTED" for t in mine) or not any(t["status"] == "COMPLETED" for t in mine):
                _viol("TRIALS_UNRESOLVED", "need >=1 COMPLETED trial and none STARTED")
        if pay["to_state"] == "DATA_QUALIFIED":
            _bind_dataset_evidence(view, h, pay["evidence_refs"])
        if pay["to_state"] == "REVIEW_RECORDED":
            _bind_review_evidence(view, h, hk, pay["evidence_refs"])
        new_state = pay["to_state"]
    elif et == "PREREG_FROZEN":
        h = _need_state(view, subj, {"REVIEW_RECORDED", "PREREG_FROZEN", "EXPERIMENT_PENDING"}, "prereg")
        if (pay["hypothesis_id"], pay["hypothesis_version"]) != hk:
            _viol("SUBJECT_MISMATCH", "prereg hypothesis mismatch")
        if pay["family_id"] != h["family"]:
            _viol("FAMILY_MISMATCH", "prereg family differs from the hypothesis family")
        sha = digest(pay)
        if h["prereg"] is None:
            _check_prereg_datasets_and_holdout(view, h, pay)
            if h["state"] != "REVIEW_RECORDED" or pay["amendment"] != 0:
                _viol("PREREG_ORDER", "first prereg needs state REVIEW_RECORDED and amendment 0")
            new_state = "PREREG_FROZEN"
        else:
            if h["state"] == "REVIEW_RECORDED":
                _viol("PREREG_ORDER", "unexpected state")
            if pay["amendment"] != h["amend"] + 1 or pay.get("amends_sha256") != h["prereg_sha"]:
                _viol("AMENDMENT_CHAIN", "amendment must follow current prereg digest")
            if any((t["hypothesis_id"], t["hypothesis_version"]) == hk for t in view.trials.values()):
                _viol("AMENDMENT_AFTER_EXPOSURE", "a trial already exists; the preregistration is locked")
            _check_prereg_datasets_and_holdout(view, h, pay)
            new_state = h["state"]
        h["prereg"], h["prereg_sha"], h["amend"] = pay, sha, pay["amendment"]
    elif et == "TRIAL_RECORDED":
        h = view.hyp.get(hk)
        if h is None or h["prereg"] is None:
            _viol("PREREG_REQUIRED", "trials need a frozen preregistration")
        tid = pay["trial_id"]
        if (pay["hypothesis_id"], pay["hypothesis_version"]) != hk or subj.get("trial_id") != tid:
            _viol("SUBJECT_MISMATCH", "trial subject mismatch")
        if pay["family_id"] != h["family"]:
            _viol("FAMILY_MISMATCH", "trial family differs from hypothesis family")
        pre = h["prereg"]
        prev = view.trials.get(tid)
        if prev is None:
            if h["state"] != "EXPERIMENT_PENDING":
                _viol("WRONG_STATE", f"new trials need EXPERIMENT_PENDING, state is {h['state']}")
            if pay["status"] != "STARTED":
                _viol("TRIAL_MUST_START", "a trial is first recorded as STARTED")
            if pay["preregistration_sha256"] != h["prereg_sha"]:
                _viol("PREREG_MISMATCH", "trial does not cite the current frozen preregistration")
            fam = view.family_trials.setdefault(pay["family_id"], {})
            if pay["trial_sequence"] != len(fam) + 1 or pay["trial_sequence"] in fam.values():
                _viol("TRIAL_SEQUENCE", f"next trial_sequence must be {len(fam) + 1}")
            if len(fam) >= pre["research_budget"]["max_trials"]:
                _viol("BUDGET_EXHAUSTED", "family trial budget exhausted")
            sp = pre["splits"]
            if (pay["train_range"], pay["validation_range"], pay.get("test_range")) != (
                    sp["train"], sp["validation"], sp.get("test")):
                _viol("SPLIT_MISMATCH", "trial ranges differ from the frozen preregistration")
            if pay["holdout_class"] != sp["holdout_class"]:
                _viol("HOLDOUT_MISMATCH", "trial holdout_class differs from the frozen preregistration")
            if pay["cost_model_hash"] != digest(pre["economics"]):
                _viol("COST_MODEL_MISMATCH", "trial cost_model_hash must be the digest of the frozen preregistered economics")
            snaps = {d["snapshot_id"] for d in pre["datasets"]}
            if not set(pay["data_snapshot_ids"]) <= snaps:
                _viol("SNAPSHOT_NOT_PREREGISTERED", "trial uses data snapshots absent from the frozen preregistration")
            claimed = pre["splits"]["holdout_class"] == "UNTOUCHED"
            if claimed:
                bad = holdout.conflicts(view, holdout.instruments_of(pre), sp["test"])
                if bad:
                    _viol("HOLDOUT_CONSUMED", f"UNTOUCHED claim conflicts with the global holdout registry: {bad}")
            view.trial_meta[tid] = {"seq": ev["seq"], "instruments": sorted(holdout.instruments_of(pre)),
                                    "claimed_untouched": claimed}
            fam[tid] = pay["trial_sequence"]
        else:
            if prev["status"] == "SUPERSEDED":
                _viol("TRIAL_ALREADY_TERMINAL", "superseded trial cannot change")
            _versioned_update(prev, pay, TRIAL_MUTABLE, "trial")
            ok = (prev["status"] == "STARTED" and pay["status"] in TRIAL_TERMINAL | {"SUPERSEDED"}) or \
                 (prev["status"] in TRIAL_TERMINAL and pay["status"] == "SUPERSEDED")
            if not ok:
                _viol("TRIAL_ALREADY_TERMINAL", f"{prev['status']} -> {pay['status']} is not allowed")
            if pay["test_access_count"] < prev["test_access_count"]:
                _viol("TEST_ACCESS_DECREASED", "test_access_count cannot decrease")
        view.trials[tid] = pay
        new_state = h["state"]
    elif et == "RUN_RECORDED":
        _need_state(view, subj, set(lifecycle.STATES), "run")
        rid = pay["run_id"]
        if subj.get("run_id") != rid:
            _viol("SUBJECT_MISMATCH", "run subject mismatch")
        prev = view.runs.get(rid)
        if prev is not None:
            _versioned_update(prev, pay, RUN_MUTABLE, "run")
            if prev["status"] != "STARTED":
                _viol("RUN_ALREADY_TERMINAL", "run already finished")
        view.runs[rid] = pay
        new_state = view.hyp[hk]["state"]
    elif et == "ADJUDICATION_RECORDED":
        h = _need_state(view, subj, {"EXPERIMENT_COMPLETE"}, "adjudication")
        if (pay["hypothesis_id"], pay["hypothesis_version"]) != hk:
            _viol("SUBJECT_MISMATCH", "adjudication subject mismatch")
        ok = [t for t in view.trials.values() if t["run_id"] == pay["run_id"] and t["status"] == "COMPLETED"
              and (t["hypothesis_id"], t["hypothesis_version"]) == hk]
        if not ok:
            _viol("NO_COMPLETED_TRIAL", "adjudication run_id has no COMPLETED trial for this hypothesis")
        _check_adjudication(view, h, hk, pay, ok[0]["trial_id"], ev["seq"])
        view.adjudications.append(pay)
        new_state = "ADJUDICATED"
    elif et == "RECONCILIATION":
        if set(pay) != {"kind", "detail"}:
            _viol("PAYLOAD_INVALID", "reconciliation payload must be {kind, detail}")
    # ---- common bookkeeping
    if et != "RECONCILIATION" and new_state is not None:
        h = view.hyp[hk]
        h["state"], h["digest"] = new_state, lifecycle.state_digest(hk[0], hk[1], new_state, ev["event_hash"])
        if ev.get("resulting_state") != new_state:
            _viol("RESULTING_STATE", "resulting_state does not match rules")
    view.head, view.seq, view.last_ts = ev["event_hash"], ev["seq"], ev["timestamp_utc"]
    view.idem[ev["idempotency_key"]] = ev
    view.events.append(ev)


def _evidence_or_gap(view, what, fn, *args):
    """Run a verifier. Missing evidence is a gap on replay but a rejection when appending."""
    try:
        return fn(*args)
    except Unavailable as exc:
        if view.strict:
            _viol("EVIDENCE_UNAVAILABLE", f"{what}: {exc}")
        view.evidence_gaps.append(f"seq{view._cur_seq}:{what}")
    except EvidenceError as exc:
        _viol(exc.code, f"{what}: {exc}")
    return None


def _bind_dataset_evidence(view, h, refs):
    shas = refs_with(DATASET_PREFIX, refs)
    if not shas or len(set(shas)) != len(shas):
        _viol("EVIDENCE_REQUIRED", "DATA_QUALIFIED needs unique dataset-qualification:<sha256> evidence references")
    if view.evidence is None:
        _viol("EVIDENCE_STORE_REQUIRED", "this scan has no evidence store")
    for sha in shas:
        _evidence_or_gap(view, f"dataset-qualification:{sha[:12]}", verify_dataset_bundle, view.evidence.store, sha)
    h["certs"] = sorted(shas)


def _bind_review_evidence(view, h, hk, refs):
    shas = refs_with(REVIEW_PREFIX, refs)
    if len(shas) != 1:
        _viol("EVIDENCE_REQUIRED", "REVIEW_RECORDED needs exactly one review:<sha256> evidence reference")
    if view.evidence is None:
        _viol("EVIDENCE_STORE_REQUIRED", "this scan has no evidence store")
    _evidence_or_gap(view, f"review:{shas[0][:12]}", verify_review_bundle, view.evidence.store, shas[0], hk[0], hk[1])
    h["review_ref"] = shas[0]


def _check_prereg_datasets_and_holdout(view, h, pay):
    """Freeze-time checks: datasets must be the qualified ones; an UNTOUCHED claim must not conflict with the registry."""
    certified, gap = set(), False
    for sha in h["certs"]:
        before = len(view.evidence_gaps)
        info = _evidence_or_gap(view, f"dataset-qualification:{sha[:12]}", verify_dataset_bundle, view.evidence.store, sha)             if view.evidence is not None else None
        gap = gap or len(view.evidence_gaps) > before
        if info:
            certified.add(info["manifest_sha256"])
    missing = [d["snapshot_id"] for d in pay["datasets"] if d["manifest_sha256"] not in certified]
    if missing and not gap:
        _viol("DATASET_NOT_QUALIFIED", f"preregistered datasets lack a verified qualification: {missing}")
    if pay["splits"]["holdout_class"] == "UNTOUCHED":
        bad = holdout.conflicts(view, holdout.instruments_of(pay), pay["splits"]["test"])
        if bad:
            _viol("HOLDOUT_CONFLICT", f"UNTOUCHED claim conflicts with the global holdout registry: {bad}")


_IGNORED_DERIVED = {"adjudication_code_digest"}


def _check_adjudication(view, h, hk, pay, trial_id, seq):
    """The recorded adjudication must equal the one the deterministic rules derive from authoritative state."""
    if view.evidence is None:
        _viol("EVIDENCE_STORE_REQUIRED", "adjudications can only be recorded or replayed with an evidence store")
    from .validation.derive import derive
    na = [g["gate_id"] for g in pay["gate_results"] if g["value"] == "NOT_APPLICABLE"]
    rec, unavailable = derive(view, trial_id, view.evidence, created_at_utc=pay["created_at_utc"], not_applicable=na)
    if unavailable:
        if view.strict:
            _viol("EVIDENCE_UNAVAILABLE", "artifacts or evidence needed to verify this adjudication are not present")
        view.evidence_gaps.append(f"seq{seq}:adjudication")
        return
    diff = sorted(k for k in set(rec) | set(pay) if k not in _IGNORED_DERIVED and rec.get(k) != pay.get(k))
    if diff:
        _viol("ADJUDICATION_MISMATCH", f"recorded adjudication differs from the derived one in {diff} "
              f"(derived decision {rec['decision']}, recorded {pay['decision']})")


def event_body_digest(ev: dict) -> str:
    return digest({k: v for k, v in ev.items() if k != "event_hash"})


# ----------------------------------------------------------------- file scanning
class Scan:
    def __init__(self):
        self.status = "OK"            # OK | INCOMPLETE_TAIL | UNTERMINATED_VALID_TAIL | CORRUPT
        self.view = View()
        self.committed_bytes = 0
        self.tail = b""
        self.issues = []

    def as_dict(self):
        return {"status": self.status, "events": self.view.seq, "head": self.view.head,
                "committed_bytes": self.committed_bytes, "tail_bytes": len(self.tail),
                "issues": [str(i) for i in self.issues],
                "evidence": {"status": "UNVERIFIABLE" if self.view.evidence_gaps else "VERIFIED",
                             "gaps": list(self.view.evidence_gaps)}}


def _check_event(view: View, ev: dict, line_no: int):
    issues = validate("ledger_event", ev)
    if issues:
        raise RuleViolation(f"line {line_no}: {issues[0]}", "EVENT_INVALID")
    if ev["seq"] != view.seq + 1:
        raise RuleViolation(f"line {line_no}: seq {ev['seq']} after {view.seq}", "SEQ_BREAK")
    if ev["prev_hash"] != view.head:
        raise RuleViolation(f"line {line_no}: prev_hash does not match chain", "CHAIN_BREAK")
    if event_body_digest(ev) != ev["event_hash"]:
        raise RuleViolation(f"line {line_no}: event_hash mismatch", "HASH_MISMATCH")
    if ev["idempotency_key"] in view.idem:
        raise RuleViolation(f"line {line_no}: duplicate idempotency_key", "DUPLICATE_KEY")
    if view.last_ts and parse_utc(ev["timestamp_utc"]) < parse_utc(view.last_ts):
        raise RuleViolation(f"line {line_no}: timestamp regressed", "TIMESTAMP_REGRESSION")


def scan_bytes(data: bytes, evidence=None, strict_from_seq=None) -> Scan:
    sc = Scan()
    sc.view.evidence, sc.view.strict_from_seq = evidence, strict_from_seq
    pos, line_no = 0, 0
    while pos < len(data):
        nl = data.find(b"\n", pos)
        if nl == -1:
            raw, terminated = data[pos:], False
        else:
            raw, terminated = data[pos:nl], True
        line_no += 1
        try:
            ev = strict_loads(raw.decode("utf-8"))
            if not isinstance(ev, dict):
                raise RuleViolation(f"line {line_no}: not an object", "EVENT_INVALID")
            _check_event(sc.view, ev, line_no)
            apply_event(sc.view, ev)
            if raw != canonical_bytes(ev):
                raise RuleViolation(f"line {line_no}: not canonical serialization", "NON_CANONICAL")
        except (ValueError, LedgerError, ContractError) as exc:
            if not terminated:
                sc.status, sc.tail = "INCOMPLETE_TAIL", data[pos:]
                sc.issues.append(Issue("", "INCOMPLETE_TAIL", f"{len(sc.tail)} uncommitted bytes after last committed event"))
            else:
                sc.status = "CORRUPT"
                sc.issues.append(Issue("", getattr(exc, "code", "BAD_RECORD"), str(exc)))
            return sc
        if not terminated:
            sc.status, sc.tail = "UNTERMINATED_VALID_TAIL", data[pos:]
            sc.issues.append(Issue("", "UNTERMINATED_VALID_TAIL", "last event valid but newline missing"))
            sc.committed_bytes = pos
            return sc
        pos = nl + 1
        sc.committed_bytes = pos
    return sc


# ---------------------------------------------------------------------- Ledger
class Ledger:
    def __init__(self, root, clock=utc_now, lock_wait=2.0, runs_root=None):
        from .validation.derive import Evidence
        self.root = Path(root)
        self.evidence = Evidence(self.root, runs_root)
        self.path = self.root / "ledger.jsonl"
        self.lock_path = self.root / "ledger.lock"
        self.quarantine_dir = self.root / "quarantine"
        self.marker = self.root / "QUARANTINED.json"
        self.clock, self.lock_wait = clock, lock_wait

    # -- read side (never mutates)
    def scan(self) -> Scan:
        data = self.path.read_bytes() if self.path.exists() else b""
        sc = scan_bytes(data, evidence=self.evidence)
        if self.marker.exists() and sc.status != "CORRUPT":
            sc.status = "QUARANTINED"
            sc.issues.append(Issue("", "QUARANTINE_MARKER", "QUARANTINED.json present; manual reconciliation required"))
        return sc

    def verify(self) -> dict:
        return self.scan().as_dict()

    def view(self) -> View:
        sc = self.scan()
        self._require_ok(sc)
        return sc.view

    def _require_ok(self, sc: Scan):
        if self.marker.exists() or sc.status == "CORRUPT":
            raise LedgerCorrupt("; ".join(str(i) for i in sc.issues) or "quarantined")
        if sc.status != "OK":
            raise LedgerNeedsReconcile(f"{sc.status}: run reconcile_tail explicitly")

    # -- write side
    def _acquire(self):
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_wait
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {self.clock()}\n".encode())
                os.close(fd)
                return
            except (FileExistsError, PermissionError):      # Windows reports a delete-pending lock as PermissionError
                if time.monotonic() >= deadline:
                    raise LockHeld(f"{self.lock_path} held; stale locks are never stolen automatically") from None
                time.sleep(0.01)

    def _release(self):
        for _ in range(50):
            try:
                os.unlink(self.lock_path)
                return
            except FileNotFoundError:
                return
            except PermissionError:                          # transient sharing violation on Windows
                time.sleep(0.01)
        raise LockHeld(f"could not release {self.lock_path}")

    def _write_line(self, line: bytes):
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        try:
            view = memoryview(line)
            while view:
                n = os.write(fd, view)
                view = view[n:]
            os.fsync(fd)
        finally:
            os.close(fd)

    def _quarantine(self, sc: Scan, why: str):
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        data = self.path.read_bytes() if self.path.exists() else b""
        copy = self.quarantine_dir / f"ledger-{sha256_hex(data)[:16]}.jsonl"
        if not copy.exists():
            copy.write_bytes(data)
        self.marker.write_text(json.dumps({"reason": why, "issues": [str(i) for i in sc.issues],
                                           "copy": copy.name, "sha256": sha256_hex(data)}, indent=2))

    def append(self, event_type, *, subject, payload, actor, reason, idempotency_key,
               expected_head=None, artifact_refs=(), timestamp=None):
        """Admit one event. Returns (event, created). Idempotent on idempotency_key."""
        if event_type in EVENT_PAYLOAD_KIND:   # precise contract codes before anything touches the file
            issues = validate(EVENT_PAYLOAD_KIND[event_type], payload)
            if issues:
                raise ContractError(issues)
        self._acquire()
        try:
            sc = self.scan()
            if sc.status == "CORRUPT" and not self.marker.exists():
                self._quarantine(sc, "corruption detected during append")
            self._require_ok(sc)
            view = sc.view
            body = {"event_type": event_type, "subject": subject, "payload": payload,
                    "actor": actor, "reason": reason, "artifact_refs": list(artifact_refs)}
            prior = view.idem.get(idempotency_key)
            if prior is not None:
                same = all(prior[k] == body[k] for k in ("event_type", "subject", "payload", "artifact_refs"))
                if not same:
                    raise RuleViolation("idempotency_key already used with different content", "IDEMPOTENCY_CONFLICT")
                return prior, False
            if expected_head is not None and expected_head != view.head:
                raise StaleState(f"expected head {expected_head[:12]} but ledger head is {view.head[:12]}")
            ev = {"schema_version": "1.0.0", "seq": view.seq + 1, "prev_hash": view.head,
                  "event_type": event_type, "idempotency_key": idempotency_key, "actor": actor,
                  "timestamp_utc": timestamp or self.clock(), "subject": subject, "payload": payload,
                  "artifact_refs": list(artifact_refs), "reason": reason}
            ev["resulting_state"] = self._predict_state(view, ev)
            if ev["resulting_state"] is None:
                del ev["resulting_state"]
            ev["event_hash"] = event_body_digest(ev)
            _check_event(view, ev, ev["seq"])
            # dry-run on a throwaway replay so a rejected event never mutates anything
            dry = scan_bytes((self.path.read_bytes() if self.path.exists() else b"") + canonical_bytes(ev) + b"\n",
                             evidence=self.evidence, strict_from_seq=ev["seq"])
            if dry.status != "OK":
                if dry.issues and dry.issues[0].code == "STALE_STATE":
                    raise StaleState(dry.issues[0].message)
                raise RuleViolation("; ".join(str(i) for i in dry.issues), dry.issues[0].code if dry.issues else "REJECTED")
            self._write_line(canonical_bytes(ev) + b"\n")
            return ev, True
        finally:
            self._release()

    @staticmethod
    def _predict_state(view: View, ev: dict):
        """resulting_state the rules will compute; replay in a dry run verifies it."""
        et, hk = ev["event_type"], view.hkey(ev["subject"])
        if et == "HYPOTHESIS_REGISTERED":
            return "REGISTERED"
        if et == "STATE_TRANSITION":
            return ev["payload"].get("to_state")
        if et == "PREREG_FROZEN":
            h = view.hyp.get(hk)
            return None if h is None else ("PREREG_FROZEN" if h["prereg"] is None else h["state"])
        if et == "ADJUDICATION_RECORDED":
            return "ADJUDICATED"
        if et in ("TRIAL_RECORDED", "RUN_RECORDED"):
            h = view.hyp.get(hk)
            return None if h is None else h["state"]
        return None

    # -- explicit reconciliation (never implicit)
    def reconcile_tail(self, actor, reason):
        """Resolve a recoverable tail. Partial bytes are preserved in quarantine/ first."""
        self._acquire()
        try:
            sc = self.scan()
            if sc.status in ("CORRUPT",) or self.marker.exists():
                raise LedgerCorrupt("committed records are corrupt; reconcile_tail refuses to act")
            if sc.status == "OK":
                return {"action": "none", "status": "OK"}
            self.quarantine_dir.mkdir(parents=True, exist_ok=True)
            data = self.path.read_bytes()
            prefix = data[: sc.committed_bytes]
            tail_copy = self.quarantine_dir / f"tail-{sha256_hex(sc.tail)[:16]}.bin"
            tail_copy.write_bytes(sc.tail)
            if sc.status == "UNTERMINATED_VALID_TAIL":
                self._write_line(b"\n")
                action, discarded = "terminated_valid_tail", 0
            else:
                with open(self.path, "r+b") as fh:
                    fh.truncate(sc.committed_bytes)
                    fh.flush(); os.fsync(fh.fileno())
                action, discarded = "quarantined_incomplete_tail", len(sc.tail)
            detail = {"action": action, "quarantine_file": tail_copy.name, "tail_sha256": sha256_hex(sc.tail),
                      "discarded_bytes": discarded, "ledger_prefix_sha256": sha256_hex(prefix)}
        finally:
            self._release()
        key = derived_id("reconcile", detail["tail_sha256"] + str(sc.committed_bytes))
        ev, _ = self.append("RECONCILIATION", subject={}, payload={"kind": "TAIL", "detail": detail},
                            actor=actor, reason=reason, idempotency_key=key)
        return detail | {"event_seq": ev["seq"]}

    def reconcile_interrupted_trials(self, actor, reason, observed=None):
        """Mark every STARTED trial as INTERRUPTED (or an observed terminal status). Nothing is dropped.

        observed: {trial_id: {"status": ..., "artifact_manifest_hash": ..., "failure_code": ...}}.
        COMPLETED is accepted only when the run directory on disk holds metrics.json and execution.json and
        the digest of the files ACTUALLY THERE equals the supplied artifact_manifest_hash; a made-up hash
        is rejected. The run manifest is reconciled together with the trial, from the files on disk.
        """
        from .experiments import isolation
        observed, done = observed or {}, []
        for tid in self.view().unfinished_trials():
            cur = self.view().trials[tid]
            obs = observed.get(tid, {})
            status = obs.get("status", "INTERRUPTED")
            actual = {}
            if status == "COMPLETED" or "artifact_manifest_hash" in obs:
                run_dir = self.evidence.run_dir(cur["run_id"])
                actual = isolation.observed_hashes(run_dir) if run_dir else {}
                if status == "COMPLETED" and not (actual and {"metrics.json", "execution.json"} <= set(actual)
                                                  and obs.get("artifact_manifest_hash") == digest(dict(sorted(actual.items())))):
                    raise RuleViolation("COMPLETED needs run artifacts on disk whose manifest digest equals the observed "
                                        "artifact_manifest_hash", "EVIDENCE_REQUIRED")
            new = dict(cur, status=status, end_time=self.clock())
            if status in ("FAILED", "INTERRUPTED"):
                new["failure_code"] = obs.get("failure_code", "E_INTERRUPTED_RECONCILED")
            if status == "COMPLETED":
                new["artifact_manifest_hash"] = digest(dict(sorted(actual.items())))
            subject = {"hypothesis_id": cur["hypothesis_id"], "hypothesis_version": cur["hypothesis_version"]}
            self.append("TRIAL_RECORDED", subject=dict(subject, trial_id=tid), payload=new, actor=actor, reason=reason,
                        idempotency_key=derived_id("reconcile-trial", f"{tid}:{status}"))
            run = self.view().runs.get(cur["run_id"])
            if run is not None and run["status"] == "STARTED":
                fin = dict(run, status=status, end_utc=self.clock(), artifact_hashes=actual if status == "COMPLETED" else run["artifact_hashes"])
                self.append("RUN_RECORDED", subject=dict(subject, run_id=cur["run_id"]), payload=fin, actor=actor, reason=reason,
                            idempotency_key=derived_id("reconcile-run", f"{cur['run_id']}:{status}"))
            done.append((tid, status))
        return done

    # -- convenience wrappers (all go through append, so every rule still applies)
    def register_hypothesis(self, record, actor, reason, expected_head=None):
        issues = validate("hypothesis", record)
        if issues:
            raise ContractError(issues)
        key = derived_id("hyp", f"{record.get('hypothesis_id')}:{record.get('hypothesis_version')}")
        subject = {"hypothesis_id": record.get("hypothesis_id"),
                   "hypothesis_version": record.get("hypothesis_version")}
        return self.append("HYPOTHESIS_REGISTERED", subject=subject, payload=record, actor=actor,
                           reason=reason, idempotency_key=key, expected_head=expected_head)

    def transition(self, hypothesis_id, hypothesis_version, target, actor, reason, evidence_refs=()):
        view = self.view()
        h = view.hyp.get((hypothesis_id, hypothesis_version))
        if h is None:
            raise RuleViolation("hypothesis is not registered", "UNKNOWN_HYPOTHESIS")
        # a state is entered at most once (the machine has no cycles), so (hypothesis, target) is the edge key
        key = derived_id("transition", f"{hypothesis_id}:{hypothesis_version}:{target}")
        if key in view.idem:  # same edge already taken: harmless repeat
            return view.idem[key], False
        try:
            rec = lifecycle.make_transition(
                hypothesis_id=hypothesis_id, hypothesis_version=hypothesis_version, current=h["state"],
                target=target, actor=actor["id"], reason=reason, evidence_refs=list(evidence_refs),
                timestamp_utc=self.clock(), prior_state_digest=h["digest"])
        except ContractError as exc:
            raise RuleViolation(str(exc), exc.codes[0]) from exc
        subject = {"hypothesis_id": hypothesis_id, "hypothesis_version": hypothesis_version}
        return self.append("STATE_TRANSITION", subject=subject, payload=rec, actor=actor, reason=reason,
                           idempotency_key=key, expected_head=view.head)
