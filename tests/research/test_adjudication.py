import inspect
import unittest

from research.contracts import validate
from research.evidence_store import EvidenceStore
from research.validation import adjudicate as adj
from research.validation import economics, multiple_testing as mt, timing
from research.experiments import pipeline
from tests.research import flow as f
from tests.research import slice as s


def full_run(edge=0.01, holdout="UNTOUCHED", experiment="edge_experiment", mode="brokered", n_test=60,
             report_override=None, **setup_kw):
    b = s.setup(holdout, **setup_kw)
    s.run_trial(b, 1, edge, experiment=experiment, mode=mode, report_override=report_override, n_test=n_test)
    return b


def adjudicate(b, trial="trial-0001", **kw):
    return pipeline.adjudicate_trial(b.led, b.repo, trial, f.ACTOR, **kw)


def gates(rec):
    return {g["gate_id"]: g["value"] for g in rec["gate_results"]}


class Dispositions(unittest.TestCase):
    def test_synthetic_positive_fixture_exercises_the_qualified_path_only(self):
        b = full_run(edge=0.01)
        out = adjudicate(b); rec = out["record"]
        self.assertEqual(rec["decision"], "QUALIFIED")                    # machinery check, not an empirical claim
        self.assertEqual(rec["holdout_integrity"], "UNTOUCHED")
        self.assertTrue(all(v == "PASS" for k, v in gates(rec).items() if k.startswith(("sys-", "core-"))))
        self.assertTrue(out["recorded"], out["note"])
        self.assertEqual(b.led.view().hyp[(f.HID, f.VER)]["state"], "ADJUDICATED")
        self.assertEqual(validate("adjudication", rec), [])
        self.assertTrue(any("dataset_manifest" in x for x in rec["data_limitations"]))
        self.assertEqual(rec["adjudication_code_digest"], adj.code_digest())
        self.assertEqual(b.led.verify()["evidence"]["status"], "VERIFIED")

    def test_positive_gross_but_negative_cost_stress_cannot_qualify(self):  # G09
        b = full_run(edge=0.0015)           # gross > 0; net at 2x cost = 0.0015 - 0.002 < 0
        rec = adjudicate(b)["record"]
        self.assertEqual(gates(rec)["g-gross-info"], "PASS")
        self.assertEqual(gates(rec)["g-net-stress"], "FAIL")
        self.assertEqual(rec["decision"], "REJECT")

    def test_cost_stress_is_enforced_even_when_the_preregistration_has_no_stress_gate(self):  # G09, original defect
        only = [{"gate_id": "g-n", "mandatory": True, "metric": "n_trades", "comparator": ">=", "threshold": 30,
                 "threshold_source": s.FIXTURE_NOTE}]
        b = full_run(edge=0.0015, only_gates=only)
        rec = adjudicate(b)["record"]
        self.assertEqual(gates(rec)["core-net-edge-stress-x2"], "FAIL")
        self.assertEqual(rec["decision"], "REJECT")

    def test_unconfirmed_evaluation_is_only_promising(self):
        b = full_run(edge=0.01, holdout="EXPLORATORY_OR_REUSED", eval_split="validation")
        rec = adjudicate(b)["record"]
        self.assertEqual(b.led.view().trials["trial-0001"]["test_access_count"], 0)
        self.assertEqual((rec["decision"], rec["holdout_integrity"]), ("PROMISING_UNVALIDATED", "EXPLORATORY_OR_REUSED"))

    def test_consumed_legacy_window_never_qualifies(self):  # G11
        b = full_run(edge=0.01, holdout="CONSUMED_LEGACY")
        rec = adjudicate(b)["record"]
        self.assertEqual(rec["holdout_integrity"], "CONSUMED_LEGACY")
        self.assertEqual(rec["decision"], "PROMISING_UNVALIDATED")
        self.assertNotEqual(rec["decision"], "QUALIFIED")

    def test_unknown_mandatory_gate_means_never_qualified(self):  # G13
        b = full_run(edge=0.01, report_override={"mean_net_return_stress_x2": None})
        rec = adjudicate(b)["record"]
        self.assertNotEqual(rec["decision"], "QUALIFIED")                  # reported None vs recomputed number: mismatch
        self.assertEqual(rec["decision"], "BLOCKED")
        self.assertNotIn("agent_consensus", inspect.signature(adj.adjudicate).parameters)
        self.assertNotIn("decision", inspect.signature(adj.adjudicate).parameters)    # no manual override input

    def test_missing_mandatory_evidence_is_blocked_not_investigate(self):  # blueprint 8, finding M6
        extra = [{"gate_id": "g-extra", "mandatory": True, "metric": "not_measured", "comparator": ">", "threshold": 0,
                  "threshold_source": s.FIXTURE_NOTE}]
        b = full_run(extra_gates=extra)
        rec = adjudicate(b)["record"]
        self.assertEqual(gates(rec)["g-extra"], "UNKNOWN")
        self.assertEqual(rec["decision"], "BLOCKED")

    def test_not_applicable_mandatory_gate_cannot_qualify(self):
        b = full_run()
        rec = adjudicate(b, not_applicable=["g-net-stress"])["record"]
        self.assertEqual(gates(rec)["g-net-stress"], "NOT_APPLICABLE")
        self.assertEqual(rec["decision"], "INVESTIGATE")

    def test_corrupted_or_missing_artifact_blocks(self):  # G08
        forged = b'{"fills":[],"trades":[]}'
        for mutate in (lambda p: (p / "execution.json").write_bytes(forged),
                       lambda p: (p / "execution.json").unlink(),
                       lambda p: (p / "extra.json").write_text("{}")):
            b = full_run()
            mutate(b.repo / "work" / "research-runs" / "run-0001")
            rec = adjudicate(b, record_it=False)["record"]
            self.assertEqual(rec["decision"], "BLOCKED")
            self.assertEqual(gates(rec)["sys-artifact-integrity"], "FAIL")

    def test_misreported_metric_is_caught_by_independent_recomputation(self):
        b = full_run(edge=0.0015, report_override={"mean_net_return_stress_x2": 0.5})
        rec = adjudicate(b)["record"]
        self.assertEqual(gates(rec)["sys-independent-recompute"], "FAIL")
        self.assertEqual(rec["decision"], "BLOCKED")

    def test_fabricated_p_value_is_caught(self):
        b = full_run(edge=0.0015, report_override={"p_value": 1e-9})
        rec = adjudicate(b)["record"]
        self.assertEqual((gates(rec)["sys-independent-recompute"], rec["decision"]), ("FAIL", "BLOCKED"))

    def test_unresolved_family_trial_and_unsupported_method_block(self):
        b = full_run(holdout="EXPLORATORY_OR_REUSED")
        class Crash(BaseException): pass
        def die(ctx): raise Crash()
        with self.assertRaises(Crash):
            s.run_trial(b, 2, experiment=die, mode="inproc")
        out = adjudicate(b)
        self.assertEqual(out["record"]["decision"], "BLOCKED")
        self.assertEqual(gates(out["record"])["sys-trial-census"], "FAIL")
        self.assertFalse(out["recorded"])                       # ledger refuses: trials unresolved
        self.assertIn("TRIALS_UNRESOLVED", out["note"])
        b2 = full_run(method="FANCY_DEFLATION")
        self.assertEqual(gates(adjudicate(b2)["record"])["sys-multiplicity-method"], "FAIL")

    def test_failed_and_superseded_trials_count_in_the_family(self):
        b = s.setup("EXPLORATORY_OR_REUSED")
        def boom(ctx): raise ValueError("x")
        s.run_trial(b, 1, experiment=boom, mode="inproc")
        s.run_trial(b, 2)
        summary = mt.family_summary(b.led.view(), "fam-synthetic")
        self.assertEqual((summary["trials_total"], summary["by_status"]), (2, {"COMPLETED": 1, "FAILED": 1}))
        rec = adjudicate(b, "trial-0002")["record"]
        self.assertTrue(rec["family_multiplicity_ref"].startswith("fam-synthetic:2:"))

    def test_tampered_dataset_evidence_fails_replay_closed(self):
        b = full_run()
        for p in (b.led.root / "evidence").glob("*.json"):
            p.write_bytes(b'{"manifest":{},"certificate":{},"criteria":{}}')
        rep = b.led.verify()
        self.assertEqual(rep["status"], "CORRUPT")
        self.assertIn("EVIDENCE_TAMPERED", " ".join(rep["issues"]))
        with self.assertRaises(Exception) as cm:
            b.led.view()
        self.assertEqual(getattr(cm.exception, "code", None), "LEDGER_CORRUPT")

    def test_decision_rule_digest_tracks_the_frozen_thresholds_and_economics(self):
        a = s.prereg(); c = s.prereg(); d = s.prereg()
        c["gate_rules"]["gates"][1]["threshold"] = 0.5
        d["economics"]["cost_per_trade"] = 0.0
        self.assertNotEqual(adj.rule_digest(a), adj.rule_digest(c))
        self.assertNotEqual(adj.rule_digest(a), adj.rule_digest(d))
        self.assertEqual(adj.rule_digest(a), adj.rule_digest(s.prereg()))

    def test_adjudication_is_deterministic(self):
        b = full_run()
        r1 = adjudicate(b, record_it=False)["record"]; r2 = adjudicate(b, record_it=False)["record"]
        r1.pop("created_at_utc"); r2.pop("created_at_utc")
        self.assertEqual(r1, r2)


class Multiplicity(unittest.TestCase):
    def test_adjustments(self):
        self.assertAlmostEqual(mt.adjust_p("BONFERRONI", 0.01, 3), 0.03)
        self.assertEqual(mt.adjust_p("BONFERRONI", 0.5, 3), 1.0)
        self.assertAlmostEqual(mt.adjust_p("SIDAK", 0.01, 3), 1 - 0.99 ** 3)
        self.assertEqual(mt.adjust_p("COUNT_ONLY", 0.2, 5), 0.2)
        for bad in (("NOPE", 0.1, 2), ("SIDAK", 1.5, 2), ("SIDAK", 0.1, 0)):
            self.assertIsNone(mt.adjust_p(*bad))

    def test_bonferroni_uses_every_attempt_in_the_family(self):
        rs = s.returns(0.01, 60, 13)                                  # the test split the experiment reads
        p = economics.one_sided_t_p_value([r - s.COST for r in rs])
        extra = [{"gate_id": "g-p", "mandatory": True, "metric": "p_value_adjusted", "comparator": "<=", "threshold": 2 * p,
                  "threshold_source": s.FIXTURE_NOTE}]
        b = full_run(method="BONFERRONI", extra_gates=extra)
        rec = adjudicate(b, record_it=False)["record"]
        self.assertEqual(gates(rec)["g-p"], "PASS")                 # p * 1 trial <= 2p
        b = s.setup("EXPLORATORY_OR_REUSED", method="BONFERRONI", extra_gates=extra)
        def boom(ctx): raise ValueError("x")
        for n in (1, 2):
            s.run_trial(b, n, experiment=boom, mode="inproc")
        s.run_trial(b, 3)
        rec = adjudicate(b, "trial-0003", record_it=False)["record"]
        self.assertEqual(gates(rec)["g-p"], "FAIL")                 # p * 3 attempts > 2p

    def test_qualification_cannot_bypass_multiplicity_by_omitting_a_p_gate(self):  # finding H2
        only = [{"gate_id": "g-n", "mandatory": True, "metric": "n_trades", "comparator": ">=", "threshold": 30,
                 "threshold_source": s.FIXTURE_NOTE}]
        b = full_run(edge=0.0003, only_gates=only)                    # noise-level edge: p is large
        rec = adjudicate(b, record_it=False)["record"]
        self.assertEqual(gates(rec)["core-multiplicity"], "FAIL")
        self.assertNotEqual(rec["decision"], "QUALIFIED")


class TimingAndEconomics(unittest.TestCase):
    def test_label_overlap_and_embargo(self):
        self.assertEqual(timing.label_overlap_issues("2021-01-01T00:00:00Z", "2021-01-01T00:00:00Z", label_horizon_s=3600, embargo_s=0),
                         ["LABEL_OVERLAP"])
        self.assertEqual(timing.label_overlap_issues("2021-01-01T00:00:00Z", "2021-01-01T02:00:00Z", label_horizon_s=3600, embargo_s=7200 * 2),
                         ["EMBARGO_TOO_SHORT"])
        self.assertEqual(timing.label_overlap_issues("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z", label_horizon_s=3600, embargo_s=3600), [])
        self.assertIn("SPLIT_OVERLAP", timing.label_overlap_issues("2021-01-02T00:00:00Z", "2021-01-01T00:00:00Z", label_horizon_s=0, embargo_s=0))
        with self.assertRaises(ValueError):
            timing.label_overlap_issues("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z", label_horizon_s=-1, embargo_s=0)
        with self.assertRaises(TypeError):
            timing.label_overlap_issues("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    def test_seeded_future_feature_is_caught(self):  # G10
        samples = [{"decision_at": f"2026-01-01T00:0{i}:00Z",
                    "features": {"momentum": f"2026-01-01T00:0{i}:00Z", "next_bar_return": f"2026-01-01T00:0{i + 1}:00Z",
                                 "mystery": "UNKNOWN"}} for i in range(5)]
        rep = timing.leakage_audit(samples)
        self.assertFalse(rep["ok"])
        self.assertEqual(sorted(rep["violations"]), ["mystery", "next_bar_return"])
        self.assertEqual(rep["violations"]["next_bar_return"][0], (0, "AVAILABLE_AFTER_DECISION"))
        clean = [{"decision_at": "2026-01-01T00:00:00Z", "features": {"momentum": "2026-01-01T00:00:00Z"}}]
        self.assertTrue(timing.leakage_audit(clean)["ok"])

    def test_recompute_metrics(self):
        m = economics.recompute_metrics([0.01, 0.03], cost_per_trade=0.005, stress_multipliers=[2])
        self.assertAlmostEqual(m["mean_gross_return"], 0.02)
        self.assertAlmostEqual(m["mean_net_return"], 0.015)
        self.assertAlmostEqual(m["mean_net_return_stress_x2"], 0.01)
        self.assertEqual(economics.recompute_metrics([], cost_per_trade=0.0, stress_multipliers=[1])["mean_net_return"], None)
        with self.assertRaises(ValueError):
            economics.recompute_metrics([float("nan")], cost_per_trade=0.0, stress_multipliers=[1])
        self.assertEqual(economics.compare_metrics({"a": 1.0, "b": None}, {"a": 1.0 + 1e-9, "b": 2.0}), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
