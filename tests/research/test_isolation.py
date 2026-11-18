import os
import unittest

from research.experiments import dispatch, isolation
from research.provenance import hash_tree
from tests.research import flow as f
from tests.research import slice as s

PROTECTED = ["REPORT.md", "PREREGISTRATION.md", "STAGE_01_HANDOFF.json", "results"]


def run(bench, n=1, experiment=None, edge=0.01, **kw):
    return s.run_trial(bench, n, edge, experiment=experiment or "edge_experiment", mode="inproc" if callable(experiment) else "brokered", **kw)


class RunDirectory(unittest.TestCase):
    def test_creation_names_and_no_reuse(self):
        repo = s.make_repo()
        rd = isolation.RunDir(repo, "run-0001").create()
        self.assertEqual(rd.path.parent, repo.resolve() / "work" / "research-runs")
        with self.assertRaises(isolation.IsolationError) as ctx:
            isolation.RunDir(repo, "run-0001").create()
        self.assertEqual(ctx.exception.code, "RUN_EXISTS")
        for bad in ("../x", "a/b", "a\\b", "", ".", "..", "x" * 200, "-lead"):
            with self.assertRaises(isolation.IsolationError, msg=bad):
                isolation.RunDir(repo, bad)

    def test_artifact_names_and_single_write(self):
        rd = isolation.RunDir(s.make_repo(), "run-0002").create()
        rd.write("metrics.json", {"a": 1})
        for bad in ("../m.json", "m.txt", "a/b.json", "x"):
            with self.assertRaises(isolation.IsolationError, msg=bad):
                rd.write(bad, {})
        with self.assertRaises(isolation.IsolationError) as ctx:
            rd.write("metrics.json", {"a": 2})
        self.assertEqual(ctx.exception.code, "ARTIFACT_EXISTS")

    def test_verify_detects_changed_missing_and_unrecorded(self):
        rd = isolation.RunDir(s.make_repo(), "run-0003").create()
        rd.write("a.json", {"x": 1}); rd.write("b.json", {"y": 2})
        good = isolation.verify_artifacts(rd.path, rd.artifacts, rd.manifest_hash())
        self.assertEqual(good, {"ok": True, "problems": []})
        (rd.path / "a.json").write_bytes(b'{"x":9}')
        (rd.path / "b.json").unlink()
        (rd.path / "c.json").write_text("{}")
        bad = isolation.verify_artifacts(rd.path, rd.artifacts, rd.manifest_hash())
        self.assertEqual(bad["problems"], ["HASH_MISMATCH:a.json", "MISSING:b.json", "UNRECORDED:c.json"])
        self.assertIn("MANIFEST_HASH_MISMATCH", isolation.verify_artifacts(rd.path, rd.artifacts, "0" * 64)["problems"])

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_symlinked_work_directory_is_refused(self):
        repo = s.make_repo(); other = s.make_repo()
        (repo / "work").rmdir()
        try:
            os.symlink(other / "work", repo / "work", target_is_directory=True)
        except OSError:
            self.skipTest("symlink privilege not held on this host")
        with self.assertRaises(isolation.IsolationError) as ctx:
            isolation.RunDir(repo, "run-0004")
        self.assertEqual(ctx.exception.code, "SYMLINK")

    def test_protected_baseline_detects_any_change(self):
        repo = s.make_repo()
        base = isolation.protected_baseline(repo)
        self.assertEqual(isolation.protected_changes(repo, base), {"added": [], "removed": [], "changed": []})
        (repo / "results" / "new.json").write_text("{}")
        (repo / "REPORT.md").write_text("tampered")
        ch = isolation.protected_changes(repo, base)
        self.assertEqual((ch["added"], ch["changed"]), (["results/new.json"], ["REPORT.md"]))


class Dispatch(unittest.TestCase):
    def test_successful_run_is_recorded_isolated_and_leaves_protected_files_alone(self):
        b = s.setup(); before = hash_tree(b.repo, PROTECTED)
        out = run(b)
        self.assertEqual(out["status"], "COMPLETED")
        self.assertEqual(out["run_dir"].parent.name, "research-runs")
        self.assertEqual(sorted(p.name for p in out["run_dir"].iterdir()), ["execution.json", "metrics.json"])
        v = b.led.view()
        self.assertEqual(v.trials["trial-0001"]["status"], "COMPLETED")
        self.assertEqual(v.trials["trial-0001"]["test_access_count"], 1)          # test split read once, counted
        self.assertEqual(v.runs["run-0001"]["status"], "COMPLETED")
        self.assertEqual(v.runs["run-0001"]["artifact_hashes"].keys(), {"metrics.json", "execution.json"})
        self.assertEqual(v.runs["run-0001"]["data_access_enforcement"], "IN_MEMORY_BROKERED")
        self.assertEqual(hash_tree(b.repo, PROTECTED), before)
        self.assertEqual(b.led.verify()["status"], "OK")

    def test_out_of_scope_requests_are_refused_before_any_side_effect(self):  # G12
        b = s.setup(); seq = b.led.view().seq
        for request in ({"goal": "please place an order for 1 BTC"}, {"note": "use my API key"},
                        {"api_key": "x"}, {"exchange_account": "main"}, {"steps": ["connect my exchange"]},
                        {"mode": "live trading"}):
            with self.assertRaises(dispatch.UnsupportedScope, msg=str(request)):
                run(b, request=request)
        with self.assertRaises(dispatch.UnsupportedScope):
            dispatch.run_candidate(b.led, b.repo, f.trial_for(b.pre), s.EXP_MODULE + ":edge_experiment", s.datasets(0.01), f.ACTOR,
                                   config={"order_type": "market"})
        self.assertEqual(b.led.view().seq, seq)
        self.assertFalse((b.repo / "work" / "research-runs").exists())

    def test_ordinary_research_text_is_not_flagged(self):
        dispatch.check_scope({"goal": "estimate net return after costs", "family": "fam-synthetic"})

    def test_failed_experiment_is_recorded_and_counted(self):
        b = s.setup()
        def boom(ctx): raise ValueError("synthetic failure")
        out = run(b, experiment=boom)
        self.assertEqual(out["status"], "FAILED")
        t = b.led.view().trials["trial-0001"]
        self.assertEqual((t["status"], t["failure_code"]), ("FAILED", "E_EXPERIMENT_EXCEPTION"))
        self.assertEqual(b.led.view().family_count("fam-synthetic"), 1)
        self.assertEqual(b.led.view().hyp[(f.HID, f.VER)]["state"], "EXPERIMENT_PENDING")   # failed run != rejected hypothesis

    def test_crash_leaves_trial_started_then_reconciles(self):  # G07 end to end
        b = s.setup()
        class Crash(BaseException): pass
        def die(ctx): raise Crash()
        with self.assertRaises(Crash):
            run(b, experiment=die)
        v = b.led.view()
        self.assertEqual(v.unfinished_trials(), ["trial-0001"])
        self.assertEqual(v.runs["run-0001"]["status"], "STARTED")
        self.assertEqual(code(lambda: b.led.transition(f.HID, f.VER, "EXPERIMENT_COMPLETE", f.ACTOR, "x", ["e"])), "TRIALS_UNRESOLVED")
        with self.assertRaises(isolation.IsolationError):
            run(b)                                                     # same trial id: no silent re-run
        b.led.reconcile_interrupted_trials(f.ACTOR, "found interrupted")
        self.assertEqual(b.led.view().trials["trial-0001"]["status"], "INTERRUPTED")

    def test_unregistered_split_and_experiment_modifying_protected_files(self):
        b = s.setup()
        out = run(b, experiment=lambda ctx: ctx.data("holdout2"))
        self.assertEqual(out["status"], "FAILED")
        b2 = s.setup()
        def tamper(ctx):
            (b2.repo / "results" / "assessment.json").write_text('{"tampered": true}')
            return {"metrics": {}}
        with self.assertRaises(dispatch.ProtectedArtifactError):
            run(b2, experiment=tamper)
        t = b2.led.view().trials["trial-0001"]
        self.assertEqual((t["status"], t["failure_code"]), ("FAILED", "PROTECTED_MODIFIED"))

    def test_hypothesis_without_frozen_prereg_cannot_run(self):
        repo = s.make_repo()
        from research.ledger import Ledger
        led = Ledger(repo / "work" / "research", clock=f.seq_clock()); f.to_state(led, "REVIEW_RECORDED")
        with self.assertRaises(isolation.IsolationError) as ctx:
            dispatch.run_candidate(led, repo, f.trial_for(s.prereg()), s.EXP_MODULE + ":edge_experiment", s.datasets(0.01), f.ACTOR, config={})
        self.assertEqual(ctx.exception.code, "PREREG_REQUIRED")


def code(call):
    from research.ledger import LedgerError
    try:
        call()
    except LedgerError as exc:
        return exc.code


if __name__ == "__main__":
    unittest.main()
