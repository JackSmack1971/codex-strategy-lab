import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.research import builders as b
from tests.research import flow as f

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("research_cli", ROOT / "scripts" / "research.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

WHO = ["--actor-category", "SCRIPT", "--actor-id", "cli-test", "--reason", "test"]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="research-cli-repo-"))
        (self.repo / "work").mkdir()
        self.tmp = Path(tempfile.mkdtemp(prefix="research-cli-in-"))

    def call(self, *argv):
        buf = io.StringIO()
        code = cli.run(list(argv), repo=self.repo, out=buf)
        text = buf.getvalue()
        return code, (json.loads(text) if text.strip() else {})

    def write(self, name, obj):
        p = self.tmp / name
        p.write_text(json.dumps(obj), encoding="utf-8")
        return str(p)

    def evidence_args(self, to):
        """Real, verifiable evidence for the transitions that now demand it (stored via the CLI)."""
        if to == "DATA_QUALIFIED":
            code, out = self.call("evidence-put", "--file", self.write("bundle.json", b.dataset_bundle()))
            return ["--evidence", f"dataset-qualification:{out['sha256']}"]
        if to == "REVIEW_RECORDED":
            code, out = self.call("evidence-put", "--file", self.write("review.json", f.review_bundle()))
            return ["--evidence", f"review:{out['sha256']}"]
        return ["--evidence", "ev1"]

    def test_capability_list_is_read_only_and_distinguishes_interfaces(self):
        import argparse
        from unittest.mock import patch

        root = self.repo / "work" / "research"
        with patch.object(cli.lg, "Ledger", side_effect=AssertionError("ledger accessed")):
            code, out = self.call("capability-list")
            self.assertEqual(self.call("capability-list"), (code, out))
        self.assertEqual(code, 0)
        self.assertFalse(root.exists())
        self.assertEqual(out["schema_version"], 1)
        self.assertEqual(out["status"], "navigation_only")
        self.assertEqual(out["authorization"], "not_evaluated")
        self.assertEqual(out["runtime_availability"], "not_evaluated")
        entries = out["capabilities"]
        commands = {e["name"]: e for e in entries if e["interface"] == "cli"}
        # Compare against the actual parser; a new CLI command must be classified.
        sub = next(a for a in cli.parser()._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual(set(commands), set(sub.choices))
        self.assertEqual(len(commands), 10)
        self.assertEqual(commands["capability-list"]["effect"], "read_only")
        self.assertEqual(commands["register"]["owner"], "supervisor_only")
        self.assertNotIn("run_candidate", commands)
        modules = {e["name"]: e for e in entries if e["interface"] == "python"}
        self.assertEqual(modules["run_candidate"]["owner"], "supervisor_only")
        self.assertEqual(modules["adjudicate_trial"]["owner"], "supervisor_only")
        self.assertEqual(modules["qualify_ohlcv"]["effect"], "derived_only")
        for e in modules.values():
            import ast
            tree = ast.parse((ROOT / e["source"]).read_text(encoding="utf-8"))
            self.assertIn(e["name"], {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))})
        code, out = self.call("--root", str(self.tmp), "capability-list")
        self.assertEqual((code, out["error"]), (2, "ROOT_REFUSED"))

    def test_register_advance_freeze_status_flow(self):
        code, out = self.call("register", "--file", self.write("h.json", b.hypothesis()), *WHO)
        self.assertEqual((code, out["created"], out["resulting_state"]), (0, True, "REGISTERED"))
        code, out = self.call("register", "--file", self.write("h.json", b.hypothesis()), *WHO)
        self.assertEqual((code, out["created"]), (0, False))                     # G05 via CLI
        for to in ("DATA_PENDING", "DATA_QUALIFIED", "REVIEW_PENDING", "REVIEW_RECORDED"):
            code, out = self.call("advance", "--hypothesis-id", f.HID, "--version", "1", "--to", to,
                                  *self.evidence_args(to), *WHO)
            self.assertEqual((code, out["resulting_state"]), (0, to))
        code, out = self.call("prereg-freeze", "--file", self.write("p.json", f.prereg()), *WHO)
        self.assertEqual((code, out["resulting_state"]), (0, "PREREG_FROZEN"))
        code, st = self.call("status")
        self.assertEqual(code, 0)
        self.assertEqual(st["hypotheses"][f"{f.HID}@1"]["state"], "PREREG_FROZEN")
        code, ver = self.call("ledger-verify")
        self.assertEqual((code, ver["status"], ver["events"]), (0, "OK", 6))

    def test_illegal_transition_and_bad_input_are_rejected_with_codes(self):
        self.call("register", "--file", self.write("h.json", b.hypothesis()), *WHO)
        code, out = self.call("advance", "--hypothesis-id", f.HID, "--version", "1", "--to", "REPORTED", *WHO)
        self.assertEqual((code, out["codes"]), (3, ["ILLEGAL_TRANSITION"]))
        code, out = self.call("register", "--file", self.write("bad.json", {"schema_version": "9"}), *WHO)
        self.assertEqual((code, out["codes"]), (3, ["SCHEMA_VERSION_UNSUPPORTED"]))
        code, out = self.call("register", "--file", str(self.tmp / "missing.json"), *WHO)
        self.assertEqual((code, out["codes"]), (3, ["NOT_A_FILE"]))

    def test_actor_is_mandatory(self):
        with self.assertRaises(SystemExit):
            self.call("register", "--file", "x.json")

    def test_free_text_evidence_cannot_advance_data_or_review_states(self):  # finding H4
        self.call("register", "--file", self.write("h.json", b.hypothesis()), *WHO)
        self.call("advance", "--hypothesis-id", f.HID, "--version", "1", "--to", "DATA_PENDING", "--evidence", "x", *WHO)
        code, out = self.call("advance", "--hypothesis-id", f.HID, "--version", "1", "--to", "DATA_QUALIFIED",
                              "--evidence", "i-say-so", *WHO)
        self.assertEqual((code, out["codes"]), (3, ["EVIDENCE_REQUIRED"]))

    def test_root_must_stay_inside_work(self):
        for root in (str(self.tmp), "work/../escape"):
            code, out = self.call("--root", root, "status")
            self.assertEqual((code, out["error"]), (2, "ROOT_REFUSED"))
        code, _ = self.call("--root", "work/other", "ledger-verify")
        self.assertEqual(code, 0)

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_symlink_escape_is_refused(self):
        link = self.repo / "work" / "link"
        try:
            os.symlink(self.tmp, link, target_is_directory=True)
        except OSError:
            self.skipTest("symlink privilege not held on this host")
        code, out = self.call("--root", "work/link/ledger", "status")
        self.assertEqual((code, out["error"]), (2, "ROOT_REFUSED"))
        self.assertFalse((self.tmp / "ledger").exists())

    @unittest.skipUnless(os.name == "nt", "NTFS junctions exist only on Windows")
    def test_windows_junction_escape_is_refused_before_anything_is_created(self):  # finding F12
        import subprocess
        link = self.repo / "work" / "junction"
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.tmp)], capture_output=True, text=True)
        if r.returncode:
            self.skipTest("cannot create a junction here: " + r.stderr.strip()[:80])
        code, out = self.call("--root", "work/junction/ledger", "status")
        self.assertEqual((code, out["error"]), (2, "ROOT_REFUSED"))
        code, out = self.call("--root", "work/junction/ledger", "register", "--file", self.write("h.json", b.hypothesis()), *WHO)
        self.assertEqual(code, 2)
        self.assertEqual(list(self.tmp.glob("ledger*")), [])                      # nothing created through the junction

    def test_abort_and_reconcile_tail_and_corrupt_exit_codes(self):
        self.call("register", "--file", self.write("h.json", b.hypothesis()), *WHO)
        pre = f.prereg()
        for to in ("DATA_PENDING", "DATA_QUALIFIED", "REVIEW_PENDING", "REVIEW_RECORDED"):
            self.call("advance", "--hypothesis-id", f.HID, "--version", "1", "--to", to, *self.evidence_args(to), *WHO)
        self.call("prereg-freeze", "--file", self.write("p.json", pre), *WHO)
        self.call("advance", "--hypothesis-id", f.HID, "--version", "1", "--to", "EXPERIMENT_PENDING", "--evidence", "e", *WHO)
        root = self.repo / "work" / "research"
        led = cli.lg.Ledger(root)
        t = f.trial_for(pre)
        f.record_trial(led, t)
        code, out = self.call("status")
        self.assertEqual(out["unfinished_trials"], [t["trial_id"]])
        code, out = self.call("abort", "--trial-id", t["trial_id"], *WHO)
        self.assertEqual((code, out["created"]), (0, True))
        self.assertEqual(self.call("status")[1]["trials"][t["trial_id"]], "ABORTED")
        self.assertEqual(self.call("status")[1]["family_trial_counts"], {"fam-synthetic": 1})   # aborted still counted
        self.call("abort", "--trial-id", "trial-nope", *WHO)
        with open(root / "ledger.jsonl", "ab") as fh:
            fh.write(b'{"partial"')
        code, out = self.call("ledger-verify")
        self.assertEqual((code, out["status"]), (4, "INCOMPLETE_TAIL"))
        code, out = self.call("register", "--file", self.write("h3.json", b.hypothesis(hypothesis_id="hyp-three-0001")), *WHO)
        self.assertEqual((code, out["error"]), (4, "NEEDS_RECONCILE"))
        code, out = self.call("reconcile-tail", *WHO)
        self.assertEqual((code, out["action"]), (0, "quarantined_incomplete_tail"))
        self.assertEqual(self.call("ledger-verify")[0], 0)


if __name__ == "__main__":
    unittest.main()
