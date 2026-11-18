import unittest

from research import ledger as lg
from research.experiments import dispatch, isolation, pipeline
from research.identifiers import canonical_bytes
from research.provenance import hash_tree
from research.reporting import render
from tests.research import flow as f
from tests.research import slice as s
from tests.research import vertical as v

PROTECTED = ["REPORT.md", "PREREGISTRATION.md", "STAGE_01_HANDOFF.json", "results"]


class Scenarios(unittest.TestCase):
    def test_valid_synthetic_slice_exercises_the_whole_trace(self):
        bench = s.setup_unstarted(); before = hash_tree(bench.repo, PROTECTED)
        out = v.run_slice("valid", bench)
        self.assertEqual(out["asof"]["chosen"], ["obs-0000", "obs-0001", "obs-0002"])
        self.assertEqual(out["asof"]["excluded"], [("obs-late", ("AVAILABLE_AFTER_DECISION",))])      # fabricated-future observation never used
        self.assertEqual(out["review"]["state"], "REVIEW_RECORDED")
        self.assertEqual(out["adjudication"]["record"]["decision"], "QUALIFIED")        # machinery check only
        self.assertEqual(out["report"]["data_kind"], "SYNTHETIC_FIXTURE")
        self.assertIn("not a performance claim", out["markdown"])
        self.assertEqual(bench.led.view().hyp[(f.HID, f.VER)]["state"], "ADJUDICATED")
        self.assertEqual(sorted(p.name for p in out["report_dir"].iterdir()), ["report.json", "report.md"])
        self.assertEqual(hash_tree(bench.repo, PROTECTED), before)                       # no Stage 02 change
        self.assertEqual(bench.led.verify()["status"], "OK")

    def test_true_negative_is_rejected_not_qualified(self):
        out = v.run_slice("true_negative")
        rec = out["adjudication"]["record"]
        self.assertEqual(rec["decision"], "REJECT")
        self.assertEqual({g["gate_id"]: g["value"] for g in rec["gate_results"]}["g-net-stress"], "FAIL")
        self.assertTrue(out["adjudication"]["recorded"])

    def test_fabricated_future_data_is_caught_before_any_experiment(self):  # G10
        bench = s.setup_unstarted()
        out = v.run_slice("future_leak", bench)
        self.assertEqual(out["review"], {"state": "BLOCKED", "blocking": ["obj-causal-leak"], "evidence_refs": out["review"]["evidence_refs"]})
        self.assertNotIn("run", out)
        view = bench.led.view()
        self.assertEqual(view.hyp[(f.HID, f.VER)]["state"], "BLOCKED")
        self.assertEqual(len(view.trials), 0)
        self.assertFalse((bench.repo / "work" / "research-runs").exists())
        with self.assertRaises(lg.LedgerError):                    # blocked is terminal: no trial can start
            f.record_trial(bench.led, f.trial_for(bench.pre))

    def test_missing_eligibility_metric_never_qualifies(self):
        extra = [{"gate_id": "g-eligibility", "mandatory": True, "metric": "eligibility_checked_fraction", "comparator": ">=",
                  "threshold": 1, "threshold_source": s.FIXTURE_NOTE}]
        bench = s.setup_unstarted(extra_gates=extra)
        out = v.run_slice("missing_eligibility", bench)
        gates = {g["gate_id"]: g["value"] for g in out["adjudication"]["record"]["gate_results"]}
        self.assertEqual(gates["g-eligibility"], "UNKNOWN")
        self.assertEqual(out["adjudication"]["record"]["decision"], "BLOCKED")     # blueprint 8: missing required evidence
        self.assertNotEqual(out["adjudication"]["record"]["decision"], "QUALIFIED")


class ReplayAndGrounding(unittest.TestCase):
    def test_two_independent_runs_produce_byte_identical_reports(self):
        a = v.run_slice("valid"); b = v.run_slice("valid")
        self.assertEqual(canonical_bytes(a["report"]), canonical_bytes(b["report"]))
        self.assertEqual(a["markdown"], b["markdown"])

    def test_trace_replays_from_hashed_artifacts_and_ledger(self):
        bench = s.setup_unstarted()
        out = v.run_slice("valid", bench)
        fresh = lg.Ledger(bench.led.root, clock=f.seq_clock())
        self.assertEqual(fresh.verify()["status"], "OK")
        stored = [e for e in fresh.view().events if e["event_type"] == "ADJUDICATION_RECORDED"][0]["payload"]
        again = pipeline.adjudicate_trial(fresh, bench.repo, "trial-0001", f.ACTOR, record_it=False)["record"]
        self.assertEqual({k: x for k, x in again.items() if k != "created_at_utc"}, {k: x for k, x in stored.items() if k != "created_at_utc"})
        on_disk = isolation.load_artifact(out["report_dir"], "report.json")
        self.assertEqual(on_disk, out["report"])
        run_dir = bench.repo / "work" / "research-runs" / "run-0001"
        view = fresh.view()
        self.assertEqual(isolation.verify_artifacts(run_dir, view.runs["run-0001"]["artifact_hashes"],
                                                    view.trials["trial-0001"]["artifact_manifest_hash"]), {"ok": True, "problems": []})

    def test_narrative_cannot_change_the_decision(self):
        out = v.run_slice("true_negative")
        tampered = dict(out["report"], decision="QUALIFIED")
        rebuilt = render.build_report(record=out["adjudication"]["record"], trial=tampered and {"holdout_class": "UNTOUCHED", "test_access_count": 1,
                                      "artifact_manifest_hash": None}, family=out["report"]["family"], artifact_hashes=out["report"]["hashes"]["artifacts"],
                                      preregistration_sha256="a" * 64, data_kind="SYNTHETIC_FIXTURE")
        self.assertEqual(rebuilt["decision"], "REJECT")                  # derived from the recorded adjudication only

    def test_every_claim_has_sources_and_every_gate_has_a_claim(self):
        out = v.run_slice("valid")
        idx = out["report"]["evidence_index"]
        self.assertTrue(all(c["sources"] for c in idx.values()))
        for g in out["report"]["gates"]:
            self.assertIn(f"C-gate-{g['gate_id']}", idx)
        for needed in ("C-decision", "C-holdout", "C-family"):
            self.assertIn(needed, idx)
        self.assertIn("C-family", out["markdown"])

    def test_report_files_cannot_be_overwritten_or_escape(self):
        out = v.run_slice("valid")
        rd = isolation.RunDir(out["report_dir"].parents[2], "run-0001", "research-reports")
        with self.assertRaises(isolation.IsolationError) as ctx:
            rd.create()
        self.assertEqual(ctx.exception.code, "RUN_EXISTS")
        with self.assertRaises(isolation.IsolationError):
            isolation.RunDir(out["report_dir"].parents[2], "run-0001", "elsewhere")


class NoTradingPath(unittest.TestCase):
    def test_order_or_credential_requests_stop_the_pipeline(self):  # G12
        bench = s.setup()
        seq = bench.led.view().seq
        for req in ({"task": "place an order on the exchange"}, {"api_key": "REDACTED"}, {"note": "use live trading"}):
            with self.assertRaises(dispatch.UnsupportedScope):
                dispatch.run_candidate(bench.led, bench.repo, f.trial_for(bench.pre), s.EXP_MODULE + ":edge_experiment", s.datasets(0.01), f.ACTOR,
                                       config={}, request=req)
        self.assertEqual(bench.led.view().seq, seq)

    def test_no_trading_or_credential_code_in_the_workbench(self):
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "research"
        banned = re.compile(r"(import\s+(ccxt|binance|requests|urllib\.request|socket|http\.client)|api_secret|place_order|create_order|os\.environ\[)")
        hits = [str(p.relative_to(root)) for p in root.rglob("*.py") if banned.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
