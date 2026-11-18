import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from research import ledger as lg
from research.identifiers import canonical_bytes
from research.ledger import (Ledger, LedgerCorrupt, LedgerNeedsReconcile, LockHeld, RuleViolation,
                             StaleState)
from research.prereg import freeze, prereg_digest
from tests.research import builders as b
from tests.research import flow as f


def code_of(call):
    try:
        call()
    except lg.LedgerError as exc:
        return exc.code
    return None


def lines(led):
    return led.path.read_bytes().split(b"\n")[:-1]


def forge(led, event_type, subject, payload, resulting_state=None):
    """Append a hash-valid, chain-valid but rule-breaking event straight to the file (attacker model)."""
    sc = led.scan()
    ev = {"schema_version": "1.0.0", "seq": sc.view.seq + 1, "prev_hash": sc.view.head,
          "event_type": event_type, "idempotency_key": f"forged-{sc.view.seq + 1:04d}",
          "actor": f.ACTOR, "timestamp_utc": "2027-01-01T00:00:00Z", "subject": subject,
          "payload": payload, "artifact_refs": [], "reason": "forged"}
    if resulting_state:
        ev["resulting_state"] = resulting_state
    ev["event_hash"] = lg.event_body_digest(ev)
    with open(led.path, "ab") as fh:
        fh.write(canonical_bytes(ev) + b"\n")


class Happy(unittest.TestCase):
    def test_full_lifecycle_replays_from_scratch(self):
        led = f.new_ledger(); pre = f.prereg()
        f.to_state(led, "EXPERIMENT_PENDING", pre=pre)
        t = f.trial_for(pre)
        f.record_trial(led, t)
        f.finish_trial(led, t)
        led.transition(f.HID, f.VER, "EXPERIMENT_COMPLETE", f.ACTOR, "done", ["metrics.json"])
        adj = b.adjudication(run_id=t["run_id"])         # schema-valid but self-attested: no verified artifacts behind it
        with self.assertRaises(lg.LedgerError):
            led.append("ADJUDICATION_RECORDED", subject={"hypothesis_id": f.HID, "hypothesis_version": f.VER},
                       payload=adj, actor=f.ACTOR, reason="adjudicate", idempotency_key="adj-0001")
        self.assertEqual(led.view().hyp[(f.HID, f.VER)]["state"], "EXPERIMENT_COMPLETE")

    def test_evidence_backed_lifecycle_replays_from_scratch(self):
        from tests.research import slice as s
        from research.experiments import pipeline
        bench = s.setup()
        s.run_trial(bench, 1, 0.01)
        out = pipeline.adjudicate_trial(bench.led, bench.repo, "trial-0001", f.ACTOR)
        self.assertTrue(out["recorded"], out["note"])
        bench.led.transition(f.HID, f.VER, "REPORTED", f.ACTOR, "report", ["report.md"])
        rep = Ledger(bench.led.root).verify()   # fresh object = fresh process view
        self.assertEqual((rep["status"], rep["evidence"]["status"]), ("OK", "VERIFIED"))
        self.assertEqual(Ledger(bench.led.root).view().hyp[(f.HID, f.VER)]["state"], "REPORTED")

    def test_rejected_event_leaves_file_byte_identical(self):
        led = f.new_ledger(); f.to_state(led, "REGISTERED")
        before = led.path.read_bytes()
        self.assertEqual(code_of(lambda: led.transition(f.HID, f.VER, "DATA_QUALIFIED", f.ACTOR, "skip", ["e"])),
                         "ILLEGAL_TRANSITION")
        self.assertEqual(led.path.read_bytes(), before)
        self.assertFalse(led.lock_path.exists())

    def test_verify_never_mutates(self):
        led = f.new_ledger(); f.to_state(led, "REGISTERED")
        data = led.path.read_bytes()
        led.path.write_bytes(data.replace(b"synthetic", b"SYNTHETIC", 1))
        corrupt = led.path.read_bytes()
        self.assertEqual(led.verify()["status"], "CORRUPT")
        self.assertEqual(led.path.read_bytes(), corrupt)
        self.assertFalse(led.marker.exists())


class IdempotencyAndConcurrency(unittest.TestCase):
    def test_duplicate_registration_one_event(self):  # G05
        led = f.new_ledger()
        e1, c1 = led.register_hypothesis(b.hypothesis(), f.ACTOR, "r")
        e2, c2 = led.register_hypothesis(b.hypothesis(), f.ACTOR, "r again")
        self.assertEqual((c1, c2), (True, False))
        self.assertEqual(e1["event_hash"], e2["event_hash"])
        self.assertEqual(led.view().seq, 1)

    def test_same_key_different_content_is_conflict(self):
        led = f.new_ledger(); led.register_hypothesis(b.hypothesis(), f.ACTOR, "r")
        changed = b.hypothesis(mechanism="a different mechanism")
        self.assertEqual(code_of(lambda: led.register_hypothesis(changed, f.ACTOR, "r")), "IDEMPOTENCY_CONFLICT")
        self.assertEqual(led.view().seq, 1)

    def test_stale_writer_rejected_without_data_loss(self):  # G06
        led = f.new_ledger()
        led.register_hypothesis(b.hypothesis(), f.ACTOR, "r")
        head = led.view().head
        a = b.hypothesis(hypothesis_id="hyp-synthetic-002")
        c = b.hypothesis(hypothesis_id="hyp-synthetic-003")
        led.register_hypothesis(a, f.ACTOR, "writer 1", expected_head=head)
        self.assertRaises(StaleState, led.register_hypothesis, c, f.ACTOR, "writer 2", expected_head=head)
        self.assertEqual(led.verify()["events"], 2)
        self.assertNotIn("hyp-synthetic-003", led.path.read_text())

    def test_stale_state_digest_in_transition_rejected(self):
        led = f.new_ledger(); f.to_state(led, "REGISTERED")
        v = led.view(); h = v.hyp[(f.HID, f.VER)]
        from research import lifecycle
        stale = lifecycle.make_transition(
            hypothesis_id=f.HID, hypothesis_version=f.VER, current="REGISTERED", target="DATA_PENDING",
            actor="x", reason="r", evidence_refs=[], timestamp_utc="2026-02-02T00:00:00Z",
            prior_state_digest="f" * 64)
        self.assertRaises(StaleState, led.append, "STATE_TRANSITION",
                          subject={"hypothesis_id": f.HID, "hypothesis_version": f.VER},
                          payload=stale, actor=f.ACTOR, reason="r", idempotency_key="stale-0001")

    def test_threads_serialize_and_chain_stays_valid(self):
        led = f.new_ledger(lock_wait=10)
        errors = []

        def work(i):
            try:
                Ledger(led.root, clock=led.clock, lock_wait=10).register_hypothesis(
                    b.hypothesis(hypothesis_id=f"hyp-thread-{i:03d}"), f.ACTOR, "thread")
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
        ts = [threading.Thread(target=work, args=(i,)) for i in range(12)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(errors, [])
        rep = led.verify()
        self.assertEqual((rep["status"], rep["events"]), ("OK", 12))

    def test_held_lock_fails_closed_and_is_not_stolen(self):
        led = f.new_ledger(lock_wait=0.05)
        led.root.mkdir(parents=True, exist_ok=True)
        led.lock_path.write_text("999999 stale")
        self.assertRaises(LockHeld, led.register_hypothesis, b.hypothesis(), f.ACTOR, "r")
        self.assertTrue(led.lock_path.exists())
        self.assertFalse(led.path.exists())


class TailRecovery(unittest.TestCase):
    def setUp(self):
        self.led = f.new_ledger(); f.to_state(self.led, "REGISTERED")
        self.good = self.led.path.read_bytes()

    def test_incomplete_tail_blocks_appends_until_explicit_reconcile(self):
        partial = b'{"schema_version":"1.0.0","seq":2,"prev_ha'
        with open(self.led.path, "ab") as fh:
            fh.write(partial)
        self.assertEqual(self.led.verify()["status"], "INCOMPLETE_TAIL")
        self.assertRaises(LedgerNeedsReconcile, self.led.register_hypothesis,
                          b.hypothesis(hypothesis_id="hyp-synthetic-009"), f.ACTOR, "r")
        self.assertEqual(self.led.path.read_bytes(), self.good + partial)   # nothing silently removed
        out = self.led.reconcile_tail(f.ACTOR, "crash during append")
        self.assertEqual(out["action"], "quarantined_incomplete_tail")
        self.assertEqual((self.led.quarantine_dir / out["quarantine_file"]).read_bytes(), partial)
        self.assertTrue(self.led.path.read_bytes().startswith(self.good))    # committed bytes untouched
        self.assertEqual(self.led.verify()["status"], "OK")
        self.assertEqual(self.led.view().events[-1]["event_type"], "RECONCILIATION")
        self.led.register_hypothesis(b.hypothesis(hypothesis_id="hyp-synthetic-009"), f.ACTOR, "now ok")

    def test_truncation_at_every_byte_of_last_event_is_recoverable_not_corrupt(self):
        before = self.led.view().seq
        last = self.led.path.read_bytes().split(b"\n")[-2]
        prefix = self.led.path.read_bytes()[: -(len(last) + 1)]
        for cut in range(1, len(last)):
            d = tempfile.mkdtemp(prefix="research-trunc-")
            led = Ledger(d); led.root.mkdir(exist_ok=True)
            led.path.write_bytes(prefix + last[:cut])
            st = led.verify()["status"]
            self.assertIn(st, {"INCOMPLETE_TAIL", "UNTERMINATED_VALID_TAIL"}, cut)
            self.assertLess(led.verify()["events"], before + 1)

    def test_unterminated_but_valid_tail_only_gets_newline(self):
        self.led.path.write_bytes(self.good[:-1])
        self.assertEqual(self.led.verify()["status"], "UNTERMINATED_VALID_TAIL")
        self.assertRaises(LedgerNeedsReconcile, self.led.register_hypothesis,
                          b.hypothesis(hypothesis_id="hyp-synthetic-009"), f.ACTOR, "r")
        out = self.led.reconcile_tail(f.ACTOR, "missing newline")
        self.assertEqual((out["action"], out["discarded_bytes"]), ("terminated_valid_tail", 0))
        self.assertTrue(self.led.path.read_bytes().startswith(self.good))

    def test_reconcile_tail_refuses_when_committed_records_are_corrupt(self):
        self.led.path.write_bytes(self.good.replace(b"SYNTHETIC", b"X", 1) + b"junk")
        self.assertRaises(LedgerCorrupt, self.led.reconcile_tail, f.ACTOR, "x")


class CommittedCorruption(unittest.TestCase):
    def setUp(self):
        self.led = f.new_ledger(); pre = f.prereg()
        f.to_state(self.led, "EXPERIMENT_PENDING", pre=pre)
        self.assertGreaterEqual(len(lines(self.led)), 7)

    def assert_corrupt(self, data, expect=None):
        self.led.path.write_bytes(data)
        rep = self.led.verify()
        self.assertEqual(rep["status"], "CORRUPT", rep)
        if expect:
            self.assertTrue(any(i.startswith(expect) for i in rep["issues"]), rep["issues"])
        before = self.led.path.read_bytes()
        self.assertRaises(LedgerCorrupt, self.led.register_hypothesis,
                          b.hypothesis(hypothesis_id="hyp-synthetic-009"), f.ACTOR, "r")
        self.assertEqual(self.led.path.read_bytes(), before)       # never repaired or truncated
        self.assertTrue(self.led.marker.exists())
        self.assertTrue(any(self.led.quarantine_dir.glob("ledger-*.jsonl")))
        return before

    def test_edited_record(self):
        ls = lines(self.led); ls[1] = ls[1].replace(b"DATA_PENDING", b"DATA_QUALIFIED")
        self.assert_corrupt(b"\n".join(ls) + b"\n", "HASH_MISMATCH")

    def test_deleted_record(self):
        ls = lines(self.led); del ls[2]
        self.assert_corrupt(b"\n".join(ls) + b"\n", "SEQ_BREAK")

    def test_reordered_records(self):
        ls = lines(self.led); ls[1], ls[2] = ls[2], ls[1]
        self.assert_corrupt(b"\n".join(ls) + b"\n", "SEQ_BREAK")

    def test_duplicated_record(self):
        ls = lines(self.led); ls.insert(2, ls[1])
        self.assert_corrupt(b"\n".join(ls) + b"\n")

    def test_garbage_and_non_canonical_lines(self):
        ls = lines(self.led)
        self.assert_corrupt(b"\n".join(ls[:2] + [b"not json"] + ls[2:]) + b"\n")
        pretty = json.dumps(json.loads(ls[0]), indent=1).replace("\n", " ").encode()
        self.assert_corrupt(b"\n".join([pretty] + ls[1:]) + b"\n", "NON_CANONICAL")

    def test_rehashed_rule_breaking_event_is_caught_by_replay(self):
        self.led.path.write_bytes(self.led.path.read_bytes())
        pre = f.prereg(); t = f.trial_for(pre, 3)           # sequence 3 skips 1,2
        forge(self.led, "TRIAL_RECORDED", {"hypothesis_id": f.HID, "hypothesis_version": f.VER,
                                           "trial_id": t["trial_id"]}, t, "EXPERIMENT_PENDING")
        rep = self.led.verify()
        self.assertEqual(rep["status"], "CORRUPT")
        self.assertTrue(any("TRIAL_SEQUENCE" in i for i in rep["issues"]), rep["issues"])

    def test_marker_keeps_failing_closed_even_if_file_is_later_restored(self):
        good = self.led.path.read_bytes()
        self.assert_corrupt(good[:-5] + b"XXXXX\n")
        self.led.path.write_bytes(good)
        self.assertEqual(self.led.verify()["status"], "QUARANTINED")
        self.assertRaises(LedgerCorrupt, self.led.register_hypothesis,
                          b.hypothesis(hypothesis_id="hyp-synthetic-009"), f.ACTOR, "r")

    def test_timestamp_regression_rejected(self):
        led = f.new_ledger(); led.register_hypothesis(b.hypothesis(), f.ACTOR, "r")
        code = code_of(lambda: led.append("RECONCILIATION", subject={}, payload={"kind": "X", "detail": {}},
                                          actor=f.ACTOR, reason="r", idempotency_key="old-0001",
                                          timestamp="2020-01-01T00:00:00Z"))
        self.assertEqual(code, "TIMESTAMP_REGRESSION")


class TrialRulesAndMultiplicity(unittest.TestCase):
    def setUp(self):
        self.led = f.new_ledger(); self.pre = f.prereg(max_trials=3)
        self.pre["splits"]["holdout_class"] = "EXPLORATORY_OR_REUSED"     # several attempts per family; confirmation rules live in test_holdout
        f.to_state(self.led, "EXPERIMENT_PENDING", pre=self.pre)

    def test_trial_before_experiment_pending_or_prereg_rejected(self):
        led = f.new_ledger(); f.to_state(led, "REVIEW_RECORDED")
        self.assertEqual(code_of(lambda: f.record_trial(led, f.trial_for(self.pre))), "PREREG_REQUIRED")
        led2 = f.new_ledger(); f.to_state(led2, "PREREG_FROZEN", pre=self.pre)
        self.assertEqual(code_of(lambda: f.record_trial(led2, f.trial_for(self.pre))), "WRONG_STATE")

    def test_prereg_binding(self):
        t = f.trial_for(self.pre); t["preregistration_sha256"] = "d" * 64
        self.assertEqual(code_of(lambda: f.record_trial(self.led, t)), "PREREG_MISMATCH")
        t = f.trial_for(self.pre); t["holdout_class"] = "UNTOUCHED"
        self.assertEqual(code_of(lambda: f.record_trial(self.led, t)), "HOLDOUT_MISMATCH")
        t = f.trial_for(self.pre); t["train_range"] = b.rng("2018-01-02T00:00:00Z", "2019-01-01T00:00:00Z")
        self.assertEqual(code_of(lambda: f.record_trial(self.led, t)), "SPLIT_MISMATCH")
        self.assertEqual(self.led.view().family_count("fam-synthetic"), 0)

    def test_sequence_must_be_next_and_unique(self):
        self.assertEqual(code_of(lambda: f.record_trial(self.led, f.trial_for(self.pre, 2))), "TRIAL_SEQUENCE")
        f.record_trial(self.led, f.trial_for(self.pre, 1))
        dup = f.trial_for(self.pre, 1); dup["trial_id"] = "trial-other"
        self.assertEqual(code_of(lambda: f.record_trial(self.led, dup)), "TRIAL_SEQUENCE")

    def test_trial_id_reuse_and_terminal_rules(self):
        t = f.trial_for(self.pre); f.record_trial(self.led, t)
        reused = dict(t, parameter_hash="e" * 64, status="COMPLETED", end_time="2026-03-01T00:00:00Z")
        self.assertEqual(code_of(lambda: f.record_trial(self.led, reused)), "TRIAL_ID_REUSE")
        f.finish_trial(self.led, t, "COMPLETED")
        again = dict(t, status="FAILED", end_time="2026-03-02T00:00:00Z", failure_code="E")
        self.assertEqual(code_of(lambda: f.record_trial(self.led, again)), "TRIAL_ALREADY_TERMINAL")
        replay = f.record_trial(self.led, dict(t, status="STARTED"))      # identical replay of the original event
        self.assertFalse(replay[1])
        self.assertEqual(self.led.view().trials[t["trial_id"]]["status"], "COMPLETED")
        self.assertEqual(code_of(lambda: self.led.append(
            "TRIAL_RECORDED", subject={"hypothesis_id": f.HID, "hypothesis_version": f.VER, "trial_id": t["trial_id"]},
            payload=dict(t, status="STARTED"), actor=f.ACTOR, reason="reopen", idempotency_key="reopen-0001")),
            "TRIAL_ALREADY_TERMINAL")

    def test_budget_counts_every_attempt_including_failed_interrupted_superseded(self):
        for n, status in enumerate(["FAILED", "INTERRUPTED", "COMPLETED"], 1):
            t = f.trial_for(self.pre, n); f.record_trial(self.led, t)
            f.finish_trial(self.led, t, status, **({"failure_code": "E"} if status != "COMPLETED" else {}))
        f.record_trial(self.led, dict(f.trial_for(self.pre, 1), status="SUPERSEDED", end_time="2026-03-05T00:00:00Z",
                                      failure_code="E"))
        self.assertEqual(self.led.view().family_count("fam-synthetic"), 3)
        self.assertEqual(code_of(lambda: f.record_trial(self.led, f.trial_for(self.pre, 4))), "BUDGET_EXHAUSTED")

    def test_interrupted_experiment_recovery_after_crash(self):  # G07
        t = f.trial_for(self.pre); f.record_trial(self.led, t)   # outputs may exist, ledger never saw completion
        fresh = Ledger(self.led.root)
        self.assertEqual(fresh.view().unfinished_trials(), [t["trial_id"]])
        self.assertEqual(code_of(lambda: fresh.transition(f.HID, f.VER, "EXPERIMENT_COMPLETE", f.ACTOR, "x", ["e"])),
                         "TRIALS_UNRESOLVED")
        self.assertRaises(RuleViolation, fresh.reconcile_interrupted_trials, f.ACTOR, "r",
                          {t["trial_id"]: {"status": "COMPLETED"}})     # no evidence -> no completion
        done = fresh.reconcile_interrupted_trials(f.ACTOR, "found interrupted run")
        self.assertEqual(done, [(t["trial_id"], "INTERRUPTED")])
        self.assertEqual(fresh.view().trials[t["trial_id"]]["status"], "INTERRUPTED")
        self.assertEqual(fresh.view().family_count("fam-synthetic"), 1)  # still charged to the family
        self.assertEqual(fresh.reconcile_interrupted_trials(f.ACTOR, "again"), [])

    def test_completion_with_a_made_up_hash_is_refused(self):  # G07, finding F11: the old test encoded the hole
        t = f.trial_for(self.pre); f.record_trial(self.led, t)
        with self.assertRaises(RuleViolation) as cm:
            self.led.reconcile_interrupted_trials(f.ACTOR, "artifacts verified", {
                t["trial_id"]: {"status": "COMPLETED", "artifact_manifest_hash": "a" * 64}})
        self.assertEqual(cm.exception.code, "EVIDENCE_REQUIRED")
        self.assertEqual(self.led.view().trials[t["trial_id"]]["status"], "STARTED")


class PreregAndTransitions(unittest.TestCase):
    def test_prereg_requires_review_recorded_and_matching_family(self):
        led = f.new_ledger(); f.to_state(led, "REVIEW_PENDING")
        pre = f.prereg()
        self.assertEqual(code_of(lambda: freeze(led, pre, f.ACTOR, "early")), "WRONG_STATE")
        led = f.new_ledger(); f.to_state(led, "REVIEW_RECORDED")
        other = f.prereg(family_id="fam-other")
        other["multiplicity"]["family_id"] = "fam-other"
        self.assertEqual(code_of(lambda: freeze(led, other, f.ACTOR, "x")), "FAMILY_MISMATCH")
        self.assertEqual(led.view().hyp[(f.HID, f.VER)]["state"], "REVIEW_RECORDED")

    def test_freezing_twice_is_idempotent(self):
        led = f.new_ledger(); pre = f.prereg(); f.to_state(led, "PREREG_FROZEN", pre=pre)
        _, created = freeze(led, pre, f.ACTOR, "again")
        self.assertFalse(created)

    def test_amendment_chain_and_lock_after_exposure(self):
        led = f.new_ledger(); pre = f.prereg(max_trials=4); f.to_state(led, "EXPERIMENT_PENDING", pre=pre)
        bad = dict(pre, amendment=1, amends_sha256="9" * 64, amendment_reason="r")
        self.assertEqual(code_of(lambda: freeze(led, bad, f.ACTOR, "x")), "AMENDMENT_CHAIN")
        amended = dict(pre, amendment=1, amends_sha256=prereg_digest(pre), amendment_reason="clarify wording")
        freeze(led, amended, f.ACTOR, "amend")
        self.assertEqual(led.view().hyp[(f.HID, f.VER)]["prereg_sha"], prereg_digest(amended))
        t = f.trial_for(amended); f.record_trial(led, t)
        f.finish_trial(led, t, "COMPLETED", test_access_count=1)       # confirmation set touched
        again = dict(amended, amendment=2, amends_sha256=prereg_digest(amended), amendment_reason="late")
        self.assertEqual(code_of(lambda: freeze(led, again, f.ACTOR, "late")), "AMENDMENT_AFTER_EXPOSURE")

    def test_old_prereg_digest_no_longer_accepted_for_new_trials_after_amendment(self):
        led = f.new_ledger(); pre = f.prereg(); f.to_state(led, "EXPERIMENT_PENDING", pre=pre)
        freeze(led, dict(pre, amendment=1, amends_sha256=prereg_digest(pre), amendment_reason="r"), f.ACTOR, "a")
        self.assertEqual(code_of(lambda: f.record_trial(led, f.trial_for(pre))), "PREREG_MISMATCH")

    def test_dedicated_events_and_evidence_required(self):
        led = f.new_ledger(); f.to_state(led, "REVIEW_RECORDED")
        self.assertEqual(code_of(lambda: led.transition(f.HID, f.VER, "PREREG_FROZEN", f.ACTOR, "x", ["e"])),
                         "DEDICATED_EVENT_REQUIRED")
        led = f.new_ledger(); f.to_state(led, "REGISTERED")
        led.transition(f.HID, f.VER, "DATA_PENDING", f.ACTOR, "start")
        self.assertEqual(code_of(lambda: led.transition(f.HID, f.VER, "DATA_QUALIFIED", f.ACTOR, "no evidence")),
                         "EVIDENCE_REQUIRED")

    def test_repeating_a_transition_is_harmless(self):
        led = f.new_ledger(); f.to_state(led, "REGISTERED")
        led.transition(f.HID, f.VER, "DATA_PENDING", f.ACTOR, "go")
        _, created = led.transition(f.HID, f.VER, "DATA_PENDING", f.ACTOR, "go again")
        self.assertFalse(created)
        self.assertEqual(led.view().seq, 2)

    def test_terminal_blocked_requires_new_version(self):
        led = f.new_ledger(); f.to_state(led, "REGISTERED")
        led.transition(f.HID, f.VER, "BLOCKED", f.ACTOR, "no data", ["why.md"])
        self.assertEqual(code_of(lambda: led.transition(f.HID, f.VER, "DATA_PENDING", f.ACTOR, "retry", ["e"])),
                         "TERMINAL_STATE")
        led.register_hypothesis(b.hypothesis(hypothesis_version=2), f.ACTOR, "new version")
        self.assertEqual(code_of(lambda: led.register_hypothesis(b.hypothesis(hypothesis_version=4), f.ACTOR, "gap")),
                         "VERSION_GAP")

    def test_adjudication_requires_completed_trial_and_state(self):
        led = f.new_ledger(); pre = f.prereg(); f.to_state(led, "EXPERIMENT_PENDING", pre=pre)
        subj = {"hypothesis_id": f.HID, "hypothesis_version": f.VER}
        self.assertEqual(code_of(lambda: led.append("ADJUDICATION_RECORDED", subject=subj, payload=b.adjudication(),
                                                    actor=f.ACTOR, reason="r", idempotency_key="adj-early")),
                         "WRONG_STATE")


if __name__ == "__main__":
    unittest.main()
