"""Regression tests for the P0 acceptance-audit findings (docs/control-plane/p0-acceptance-audit.md).

Each test names the finding it pins. Every number is a synthetic fixture.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research import contracts as c
from research import holdout
from research.contracts import ContractError
from research.evidence_store import EvidenceError, EvidenceStore, verify_dataset_bundle, verify_review_bundle
from research.experiments import isolation, pipeline
from research.identifiers import canonical_bytes
from research.ledger import Ledger, LedgerError, RuleViolation
from research.prereg import freeze
from research.provenance import hash_tree
from research.validation import economics
from tests.research import builders as b
from tests.research import fixture_experiments as fe
from tests.research import flow as f
from tests.research import slice as s

ROOT = Path(__file__).resolve().parents[2]


def code_of(call):
    try:
        call()
    except (LedgerError, EvidenceError) as exc:
        return exc.code
    except ContractError as exc:
        return exc.codes[0]
    return None


def second_hypothesis(led, hid, ver=1, family="fam-synthetic", test=None, holdout_class="UNTOUCHED", upto="PREREG_FROZEN"):
    """Register another hypothesis in the SAME ledger and try to freeze an UNTOUCHED claim."""
    pre = s.prereg(holdout_class)
    pre.update(hypothesis_id=hid, hypothesis_version=ver, family_id=family, preregistration_id=f"prereg-{hid}-{ver}")
    pre["multiplicity"]["family_id"] = family
    if test:
        pre["splits"]["test"] = test
    f.to_state(led, upto, hid=hid, ver=ver, pre=pre, family_id=family)
    return pre


# ----------------------------------------------------------------------------- R0
class Packaging(unittest.TestCase):
    def test_source_package_is_not_ignored_but_the_market_data_dir_is(self):  # H1
        def ignored(path):
            r = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True)
            return r.returncode == 0
        try:
            subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT, capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git work tree (for example a copied checkout); ignore rules cannot be queried")
        for p in ("research/data/types.py", "research/data/__init__.py", "research/data/qualification.py", "research/data/legacy_ohlcv.py"):
            self.assertFalse(ignored(p), p)
        for p in ("data/raw/BTCUSDT/1h/x.zip", "data/anything"):
            self.assertTrue(ignored(p), p)


# ----------------------------------------------------------------------------- C1
class GlobalHoldout(unittest.TestCase):
    def consumed_ledger(self):
        bench = s.setup()
        s.run_trial(bench, 1, 0.0015)                                  # v1 reads the test split and is REJECTED
        return bench.led

    def test_new_version_cannot_reuse_a_consumed_test_window_as_untouched(self):  # C1
        led = self.consumed_ledger()
        self.assertEqual(code_of(lambda: second_hypothesis(led, f.HID, ver=2)), "HOLDOUT_CONFLICT")

    def test_renamed_hypothesis_and_family_cannot_either(self):  # C1
        led = self.consumed_ledger()
        self.assertEqual(code_of(lambda: second_hypothesis(led, "hyp-renamed-002", family="fam-renamed")), "HOLDOUT_CONFLICT")

    def test_partial_overlap_conflicts_and_a_later_disjoint_range_does_not(self):  # C1
        led = self.consumed_ledger()
        self.assertEqual(code_of(lambda: second_hypothesis(led, "hyp-partial-002", family="fam-p",
                                                           test=b.rng("2020-12-01T00:00:00Z", "2021-06-01T00:00:00Z"))), "HOLDOUT_CONFLICT")
        second_hypothesis(led, "hyp-later-0003", family="fam-l", test=b.rng("2021-02-01T00:00:00Z", "2021-06-01T00:00:00Z"))
        self.assertEqual(led.view().hyp[("hyp-later-0003", 1)]["state"], "PREREG_FROZEN")

    def test_interrupted_run_still_consumes_the_window(self):  # C1 resumed runs
        bench = s.setup()
        f.record_trial(bench.led, f.trial_for(bench.pre))                # STARTED, then the process dies
        bench.led.reconcile_interrupted_trials(f.ACTOR, "found interrupted")
        self.assertEqual(bench.led.view().trials["trial-0001"]["test_access_count"], 0)
        self.assertEqual(code_of(lambda: second_hypothesis(bench.led, "hyp-resume-002", family="fam-r")), "HOLDOUT_CONFLICT")

    def test_a_second_untouched_trial_under_one_prereg_is_refused(self):  # C1/H2
        bench = s.setup()
        s.run_trial(bench, 1, 0.01)
        self.assertEqual(code_of(lambda: f.record_trial(bench.led, f.trial_for(bench.pre, 2))), "HOLDOUT_CONSUMED")

    def test_exploratory_trial_that_never_read_test_does_not_consume_it(self):  # exposure policy
        bench = s.setup("EXPLORATORY_OR_REUSED", eval_split="validation")
        s.run_trial(bench, 1, 0.01)
        self.assertEqual(bench.led.view().trials["trial-0001"]["test_access_count"], 0)
        self.assertEqual(holdout.exposures(bench.led.view()), [])
        second_hypothesis(bench.led, "hyp-fresh-0002", family="fam-f")      # still untouched for others

    def test_exploratory_test_read_does_consume_it(self):  # exposure policy
        bench = s.setup("EXPLORATORY_OR_REUSED")
        s.run_trial(bench, 1, 0.01)                                      # reads the test split
        self.assertEqual(holdout.exposures(bench.led.view())[0]["purpose"], "EXPLORATORY_TEST_ACCESS")
        self.assertEqual(code_of(lambda: second_hypothesis(bench.led, "hyp-peeked-002", family="fam-q")), "HOLDOUT_CONFLICT")

    def test_replay_rejects_a_conflicting_claim_a_buggy_writer_let_through(self):  # C1 replay
        led = self.consumed_ledger()
        with mock.patch("research.ledger.holdout.conflicts", return_value=[]):
            second_hypothesis(led, "hyp-forged-0002", family="fam-x")
        rep = Ledger(led.root).verify()
        self.assertEqual(rep["status"], "CORRUPT")
        self.assertIn("HOLDOUT_CONFLICT", " ".join(rep["issues"]))

    def test_adjudication_integrity_is_derived_from_the_registry(self):  # C1 adjudication
        bench = s.setup()
        s.run_trial(bench, 1, 0.01)
        rec = pipeline.adjudicate_trial(bench.led, bench.repo, "trial-0001", f.ACTOR)["record"]
        self.assertEqual((rec["holdout_integrity"], rec["decision"]), ("UNTOUCHED", "QUALIFIED"))
        view = bench.led.view()
        view.trials["trial-earlier"] = dict(view.trials["trial-0001"], trial_id="trial-earlier", status="STARTED")
        view.trial_meta["trial-earlier"] = {"seq": 0, "instruments": ["SYN-USD"], "claimed_untouched": True}   # an earlier exposure
        self.assertEqual(holdout.integrity(view, view.trials["trial-0001"], view.hyp[(f.HID, f.VER)]["prereg"], holdout.ENFORCED),
                         "EXPLORATORY_OR_REUSED")


# ----------------------------------------------------------------------------- C2
class IndependentEconomics(unittest.TestCase):
    def adjudicated(self, **kw):
        bench = s.setup()
        s.run_trial(bench, 1, kw.pop("edge", 0.0015), **kw)
        return pipeline.adjudicate_trial(bench.led, bench.repo, "trial-0001", f.ACTOR, record_it=False)["record"]

    def gates(self, rec):
        return {g["gate_id"]: g["value"] for g in rec["gate_results"]}

    def test_forged_cost_free_metrics_are_blocked_and_negative_stress_is_rejected(self):
        rec = self.adjudicated(report_override={"mean_net_return_stress_x2": 0.05, "mean_net_return": 0.0015})
        self.assertEqual(rec["decision"], "BLOCKED")
        self.assertEqual(self.gates(rec)["sys-independent-recompute"], "FAIL")
        honest = self.adjudicated()
        self.assertEqual((honest["decision"], self.gates(honest)["core-net-edge-stress-x2"]), ("REJECT", "FAIL"))

    def test_inconsistent_trades_and_fills_block_qualification(self):
        for mutate in ("gross", "orphan", "side", "outside"):
            rec = self.adjudicated(edge=0.01, mutate=mutate)
            self.assertEqual((rec["decision"], self.gates(rec)["sys-execution-verified"]), ("BLOCKED", "FAIL"), mutate)

    def test_economics_cannot_be_chosen_by_the_experiment(self):
        bench = s.setup()
        bad = f.trial_for(bench.pre, 1, cost_model_hash="e" * 64)
        self.assertEqual(code_of(lambda: f.record_trial(bench.led, bad)), "COST_MODEL_MISMATCH")

    def test_missing_or_toothless_stress_definitions_are_rejected_at_freeze(self):
        for mut, want in ((lambda p: p.pop("economics"), "REQUIRED"),
                          (lambda p: p["economics"].update(stress_multipliers=[1]), "STRESS_NOT_STRESSING"),
                          (lambda p: p["economics"].update(stress_multipliers=[]), "LENGTH"),
                          (lambda p: p["multiplicity"].update(alpha=1.0), "ALPHA_RANGE")):
            pre = s.prereg(); mut(pre)
            self.assertIn(want, {i.code for i in c.validate("preregistration", pre)}, want)

    def test_unit_checks_on_the_execution_verifier(self):
        pre = s.prereg()
        ex = fe.execution_from_returns([0.01, 0.02], "2020-01-02T00:00:00Z")
        self.assertEqual(len(economics.trades_from_execution(ex, pre)), 2)
        import copy
        for edit, tag in ((lambda e: e["trades"][0].update(split="validation"), "TRADE_SPLIT"),
                          (lambda e: e["fills"].pop(), "TRADE_FILL_MISSING"),
                          (lambda e: e["trades"].append(dict(e["trades"][0])), "TRADE_DUPLICATE"),
                          (lambda e: e["fills"][0].update(price=-1), "FILL_PRICE"),
                          (lambda e: e["fills"][1].update(at_utc="2020-01-02T00:30:00Z"), "TRADE_CHRONOLOGY"),
                          (lambda e: e["trades"][0].update(gross_return=float("nan")), "TRADE_RETURN_INCONSISTENT")):
            bad = copy.deepcopy(ex); edit(bad)
            with self.assertRaises(economics.ExecutionError, msg=tag) as cm:
                economics.trades_from_execution(bad, pre)
            self.assertIn(tag, str(cm.exception))

    def test_labels_may_not_cross_the_split_boundary_or_enter_the_embargo(self):  # F9
        pre = s.prereg()
        late = fe.execution_from_returns([0.01], "2020-12-31T23:30:00Z")           # exits after the test range ends
        with self.assertRaises(economics.ExecutionError) as cm:
            economics.trades_from_execution(late, pre)
        self.assertIn("TRADE_OUTSIDE_SPLIT", str(cm.exception))
        early = fe.execution_from_returns([0.01], "2020-01-01T23:30:00Z")          # entry inside the 3600 s embargo
        early["fills"][0]["at_utc"] = "2020-01-02T00:10:00Z"
        early["fills"][1]["at_utc"] = "2020-01-02T00:40:00Z"
        with self.assertRaises(economics.ExecutionError) as cm:
            economics.trades_from_execution(early, pre)
        self.assertIn("TRADE_INSIDE_EMBARGO", str(cm.exception))

    def test_zero_gap_splits_are_rejected(self):  # F9
        pre = s.prereg(); pre["splits"]["validation"] = b.rng("2019-01-01T00:00:00Z", "2020-01-01T00:00:00Z")
        self.assertIn("PURGE_GAP_TOO_SHORT", {i.code for i in c.validate("preregistration", pre)})


# ----------------------------------------------------------------------------- C3
class LedgerRefusesSelfAttestedAdjudication(unittest.TestCase):
    def setUp(self):
        self.bench = s.setup()
        s.run_trial(self.bench, 1, 0.01)
        self.led = self.bench.led
        self.real = pipeline.adjudicate_trial(self.led, self.bench.repo, "trial-0001", f.ACTOR, record_it=False)["record"]
        self.led.transition(f.HID, f.VER, "EXPERIMENT_COMPLETE", f.ACTOR, "resolved", ["run:run-0001"])
        self.subj = {"hypothesis_id": f.HID, "hypothesis_version": f.VER}

    def submit(self, rec, key="adj-x"):
        return self.led.append("ADJUDICATION_RECORDED", subject=self.subj, payload=rec, actor=f.ACTOR, reason="x", idempotency_key=key)

    def test_hand_written_qualified_is_refused(self):
        self.assertEqual(code_of(lambda: self.submit(b.adjudication(run_id="run-0001"))), "ADJUDICATION_MISMATCH")
        self.assertEqual(self.led.view().hyp[(f.HID, f.VER)]["state"], "EXPERIMENT_COMPLETE")

    def test_altered_rule_digest_and_forged_unknown_gate_are_refused(self):
        forged = dict(self.real, decision_rule_digest="f" * 64)
        self.assertEqual(code_of(lambda: self.submit(forged)), "ADJUDICATION_MISMATCH")
        gates = [dict(g) for g in self.real["gate_results"]]
        gates[-1] = {"gate_id": "g-extra", "mandatory": True, "value": "PASS", "proof_refs": ["trust me"]}
        self.assertEqual(code_of(lambda: self.submit(dict(self.real, gate_results=gates))), "ADJUDICATION_MISMATCH")

    def test_altered_bindings_are_refused(self):
        forged = dict(self.real, evidence_bindings=dict(self.real["evidence_bindings"], run_artifacts_digest="0" * 64))
        self.assertEqual(code_of(lambda: self.submit(forged)), "ADJUDICATION_MISMATCH")

    def test_missing_evidence_cannot_be_recorded(self):
        import shutil
        shutil.rmtree(self.bench.repo / "work" / "research-runs" / "run-0001")
        self.assertEqual(code_of(lambda: self.submit(self.real)), "EVIDENCE_UNAVAILABLE")

    def test_the_genuine_record_is_accepted_and_replays(self):
        self.submit(self.real)
        self.assertEqual(Ledger(self.led.root).verify()["evidence"]["status"], "VERIFIED")

    def test_artifact_modified_after_adjudication_fails_replay(self):
        self.submit(self.real)
        (self.bench.repo / "work" / "research-runs" / "run-0001" / "execution.json").write_bytes(canonical_bytes({"fills": [], "trades": []}))
        rep = Ledger(self.led.root).verify()
        self.assertEqual(rep["status"], "CORRUPT")
        self.assertIn("ADJUDICATION_MISMATCH", " ".join(rep["issues"]))

    def test_deleted_evidence_after_the_fact_is_reported_unverifiable_not_ok(self):
        self.submit(self.real)
        import shutil
        shutil.rmtree(self.bench.repo / "work" / "research-runs")
        rep = Ledger(self.led.root).verify()
        self.assertEqual((rep["status"], rep["evidence"]["status"]), ("OK", "UNVERIFIABLE"))

    def test_consumed_legacy_cannot_be_forged_into_qualified(self):
        b2 = s.setup("CONSUMED_LEGACY")
        s.run_trial(b2, 1, 0.01)
        real = pipeline.adjudicate_trial(b2.led, b2.repo, "trial-0001", f.ACTOR, record_it=False)["record"]
        b2.led.transition(f.HID, f.VER, "EXPERIMENT_COMPLETE", f.ACTOR, "resolved", ["run:run-0001"])
        forged = dict(real, holdout_integrity="UNTOUCHED", decision="QUALIFIED")
        self.assertIn(code_of(lambda: b2.led.append("ADJUDICATION_RECORDED", subject=self.subj, payload=forged, actor=f.ACTOR,
                                                    reason="x", idempotency_key="adj-legacy")), ("ADJUDICATION_MISMATCH", "PROOF_REQUIRED"))


# ----------------------------------------------------------------------------- H3
class AccessBoundary(unittest.TestCase):
    def test_no_dataset_attribute_is_reachable_on_the_context(self):
        from research.experiments import dispatch
        ctx = dispatch.RunContext("run-x", dispatch.Broker({"test": 1}, {"test": lambda: []}), {})
        for name in ("_datasets", "_splits", "datasets"):
            self.assertFalse(hasattr(ctx, name), name)

    def test_in_process_and_file_backed_runs_can_never_be_untouched_confirmations(self):
        for kw in ({"mode": "inproc"}, {"mode": "brokered", "in_memory_datasets": False}):
            bench = s.setup()
            s.run_trial(bench, 1, 0.01, **kw)
            rec = pipeline.adjudicate_trial(bench.led, bench.repo, "trial-0001", f.ACTOR, record_it=False)["record"]
            self.assertEqual((rec["decision"], rec["holdout_integrity"]), ("PROMISING_UNVALIDATED", "EXPLORATORY_OR_REUSED"), kw)
            self.assertTrue(any("data access enforcement" in x for x in rec["execution_limitations"]))

    def test_brokered_reads_are_counted_even_when_the_output_hides_them(self):  # finding F5
        bench = s.setup("EXPLORATORY_OR_REUSED", eval_split="validation")
        s.run_trial(bench, 1, 0.01, experiment="peeking_experiment")
        self.assertEqual(bench.led.view().trials["trial-0001"]["test_access_count"], 1)
        self.assertEqual(holdout.exposures(bench.led.view())[0]["trial_id"], "trial-0001")


# ----------------------------------------------------------------------------- H4
class VerifiableEvidence(unittest.TestCase):
    def ledger(self):
        led = f.new_ledger()
        led.register_hypothesis(b.hypothesis(), f.ACTOR, "register")
        led.transition(f.HID, f.VER, "DATA_PENDING", f.ACTOR, "go", ["e"])
        return led

    def test_free_text_cannot_qualify_data_or_record_a_review(self):
        led = self.ledger()
        self.assertEqual(code_of(lambda: led.transition(f.HID, f.VER, "DATA_QUALIFIED", f.ACTOR, "x", ["i-say-so"])), "EVIDENCE_REQUIRED")
        led.transition(f.HID, f.VER, "DATA_QUALIFIED", f.ACTOR, "ok", f.evidence_refs(led, "DATA_QUALIFIED"))
        led.transition(f.HID, f.VER, "REVIEW_PENDING", f.ACTOR, "go", ["e"])
        self.assertEqual(code_of(lambda: led.transition(f.HID, f.VER, "REVIEW_RECORDED", f.ACTOR, "x", ["i-say-so"])), "EVIDENCE_REQUIRED")

    def test_dataset_bundles_are_rederived_not_trusted(self):
        led = self.ledger(); st = led.evidence.store
        good = b.dataset_bundle()
        forged = json.loads(json.dumps(good)); forged["certificate"]["status"] = "QUALIFIED"
        forged["manifest"]["missing_bars"] = 9                   # manifest hash no longer matches its body
        self.assertEqual(code_of(lambda: verify_dataset_bundle(st, st.put(forged))), "MANIFEST_DIGEST")
        gappy = b.dataset_bundle(); man = dict(gappy["manifest"], missing_bars=5); man.pop("manifest_sha256")
        from research.identifiers import digest
        man["manifest_sha256"] = digest(man)
        gappy = {"manifest": man, "criteria": good["criteria"], "certificate": dict(good["certificate"])}
        self.assertEqual(code_of(lambda: verify_dataset_bundle(st, st.put(gappy))), "CERTIFICATE_MISMATCH")

    def test_future_coverage_claim_is_not_qualified(self):  # F15
        man = b.fixture_manifest(last_open="2027-01-01T00:00:00Z")
        crit = dict(b.dataset_bundle()["criteria"], require_end_utc="2026-11-17T00:00:00Z")
        from research.data import qualification as q
        cert = q.qualify_ohlcv(man, **crit)
        self.assertEqual(cert["status"], "BLOCKED")
        self.assertIn("COVERAGE_CLAIM_IN_FUTURE", cert["issues"])

    def test_review_bundles_are_reexecuted(self):
        led = self.ledger(); st = led.evidence.store
        ok = f.review_bundle()
        self.assertEqual(verify_review_bundle(st, st.put(ok), f.HID, f.VER)["objection_ids"], ["obj-fixture-leak"])
        edited = json.loads(json.dumps(ok)); edited["objections"][0]["test_result"]["outcome"] = "CLAIM_HOLDS"
        self.assertIn(code_of(lambda: verify_review_bundle(st, st.put(edited), f.HID, f.VER)), ("REVIEW_MISMATCH", "EVIDENCE_INVALID"))
        leaky = json.loads(json.dumps(ok)); leaky["evidence"]["obj-fixture-leak"]["samples"][0]["features"]["next_bar"] = "2026-01-02T00:00:00Z"
        self.assertIn(code_of(lambda: verify_review_bundle(st, st.put(leaky), f.HID, f.VER)), ("REVIEW_MISMATCH", "REVIEW_BLOCKED"))
        self.assertEqual(code_of(lambda: verify_review_bundle(st, st.put(ok), "hyp-other-0009", 1)), "REVIEW_SUBJECT")

    def test_adjudication_records_that_reviewer_independence_is_unverified(self):
        bench = s.setup(); s.run_trial(bench, 1, 0.01)
        rec = pipeline.adjudicate_trial(bench.led, bench.repo, "trial-0001", f.ACTOR, record_it=False)["record"]
        self.assertTrue(any("UNVERIFIED until Phase 6" in x for x in rec["execution_limitations"]))

    def test_evidence_store_detects_tampering_and_malformed_references(self):
        st = EvidenceStore(tempfile.mkdtemp(prefix="research-ev-"))
        sha = st.put({"a": 1})
        (st.dir / f"{sha}.json").write_bytes(b'{"a":2}')
        self.assertEqual(code_of(lambda: st.get(sha)), "EVIDENCE_TAMPERED")
        self.assertEqual(code_of(lambda: st.get("../../etc/passwd")), "EVIDENCE_REF_MALFORMED")
        self.assertEqual(code_of(lambda: st.get("a" * 64)), "EVIDENCE_UNAVAILABLE")


# ----------------------------------------------------------------------------- H5 / F13-F15
class IdentityAndParsing(unittest.TestCase):
    def test_trailing_newline_identifiers_are_rejected(self):  # F13
        for kind, rec in (("hypothesis", b.hypothesis(hypothesis_id="hyp-newline-001\n")),
                          ("trial", b.trial(trial_id="trial-newline-1\n")),
                          ("preregistration", b.preregistration(family_id="fam-synthetic\n"))):
            self.assertIn("PATTERN", {i.code for i in c.validate(kind, rec)}, kind)

    def test_family_cannot_be_reassigned_by_a_new_version(self):  # H5
        led = f.new_ledger(); led.register_hypothesis(b.hypothesis(), f.ACTOR, "v1")
        self.assertEqual(code_of(lambda: led.register_hypothesis(b.hypothesis(hypothesis_version=2, family_id="fam-escape"), f.ACTOR, "v2")),
                         "FAMILY_REASSIGNMENT")
        led.register_hypothesis(b.hypothesis(hypothesis_version=2), f.ACTOR, "v2 same family")

    def test_duplicate_json_keys_are_rejected_everywhere(self):  # F14
        with self.assertRaises(ValueError):
            c.strict_loads('{"a": 1, "a": 2}')
        with self.assertRaises(ValueError):
            c.strict_loads('{"a": NaN}')
        led = f.new_ledger(); led.register_hypothesis(b.hypothesis(), f.ACTOR, "v1")
        raw = led.path.read_bytes()
        bad = raw.replace(b'{"actor"', b'{"seq":1,"actor"', 1)
        self.assertNotEqual(bad, raw)
        led.path.write_bytes(bad)
        self.assertEqual(led.verify()["status"], "CORRUPT")

    def test_observation_chronology_must_be_possible(self):  # F15
        self.assertIn("TIME_ORDER", {i.code for i in c.validate("observation", b.observation(available_at_utc="2025-12-31T23:59:59Z"))})
        self.assertIn("TIME_ORDER", {i.code for i in c.validate("observation", b.observation(published_at_utc="2025-12-31T23:59:59Z"))})


# ----------------------------------------------------------------------------- F10 / F12
class IsolationAndRecovery(unittest.TestCase):
    def test_interpreter_caches_never_enter_digests(self):  # F10
        d = Path(tempfile.mkdtemp(prefix="research-hash-"))
        (d / "pkg" / "__pycache__").mkdir(parents=True)
        (d / "pkg" / "a.py").write_text("x = 1")
        (d / "pkg" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\x00\x01")
        self.assertEqual(list(hash_tree(d, ["pkg"])), ["pkg/a.py"])

    def test_reconcile_completes_only_from_artifacts_actually_on_disk(self):  # G07/F11
        bench = s.setup(); trial = f.trial_for(bench.pre)
        from research.experiments import dispatch
        with mock.patch.object(dispatch, "_run_brokered", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                s.run_trial(bench, 1, 0.01)
        view = bench.led.view()
        self.assertEqual((view.unfinished_trials(), view.runs["run-0001"]["status"]), (["trial-0001"], "STARTED"))
        run_dir = bench.repo / "work" / "research-runs" / "run-0001"
        ex = fe.execution_from_returns(s.returns(0.01, 60, 13), bench.pre["splits"]["test"]["start_utc"])
        (run_dir / "metrics.json").write_bytes(canonical_bytes({}))
        (run_dir / "execution.json").write_bytes(canonical_bytes(ex))
        from research.identifiers import digest, sha256_hex
        actual = {n: sha256_hex((run_dir / n).read_bytes()) for n in ("execution.json", "metrics.json")}
        with self.assertRaises(RuleViolation):
            bench.led.reconcile_interrupted_trials(f.ACTOR, "r", {"trial-0001": {"status": "COMPLETED", "artifact_manifest_hash": "a" * 64}})
        bench.led.reconcile_interrupted_trials(f.ACTOR, "r", {"trial-0001": {"status": "COMPLETED",
                                                                              "artifact_manifest_hash": digest(dict(sorted(actual.items())))}})
        view = bench.led.view()
        self.assertEqual((view.trials["trial-0001"]["status"], view.runs["run-0001"]["status"]), ("COMPLETED", "COMPLETED"))
        self.assertEqual(view.runs["run-0001"]["artifact_hashes"], dict(sorted(actual.items())))

    def test_symlink_or_junction_in_the_path_is_refused_before_creating_anything(self):  # F12
        repo = s.make_repo(); outside = Path(tempfile.mkdtemp(prefix="research-outside-"))
        link = repo / "work" / "research-runs"
        if os.name == "nt":
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True)
            if r.returncode:
                self.skipTest("cannot create a junction: " + r.stderr.strip()[:80])
        else:
            try:
                os.symlink(outside, link, target_is_directory=True)
            except OSError:
                self.skipTest("cannot create a symlink")
        with self.assertRaises(isolation.IsolationError) as cm:
            isolation.RunDir(repo, "run-0001")
        self.assertEqual(cm.exception.code, "SYMLINK")
        self.assertEqual(list(outside.iterdir()), [])

    def test_two_processes_cannot_both_hold_the_ledger_lock(self):  # process-level concurrency
        led = f.new_ledger()
        code = ("import sys; sys.path.insert(0, sys.argv[1]);"
                "from research.ledger import Ledger, LockHeld;"
                "l = Ledger(sys.argv[2], lock_wait=0.2);"
                "\ntry:\n l._acquire(); print('ACQUIRED')\nexcept LockHeld: print('HELD')")
        led._acquire()
        try:
            r = subprocess.run([os.sys.executable, "-B", "-c", code, str(ROOT), str(led.root)], capture_output=True, text=True, timeout=60)
        finally:
            led._release()
        self.assertEqual(r.stdout.strip(), "HELD", r.stderr)
        r = subprocess.run([os.sys.executable, "-B", "-c", code, str(ROOT), str(led.root)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "ACQUIRED", r.stderr)


class CliDispatch(unittest.TestCase):
    def test_the_real_cli_process_dispatches_and_exits_with_documented_codes(self):  # CLI integration, not direct calls
        repo = Path(tempfile.mkdtemp(prefix="research-cli-proc-")); (repo / "work").mkdir()
        py = [os.sys.executable, "-B", str(ROOT / "scripts" / "research.py")]
        r = subprocess.run(py + ["--root", str(repo), "status"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)                                  # root outside the lab's own work dir
        r = subprocess.run(py + ["status"], capture_output=True, text=True, cwd=repo)
        self.assertIn(r.returncode, (0, 4))
        r = subprocess.run(py, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)                                  # usage


if __name__ == "__main__":
    unittest.main()
