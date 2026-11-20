"""Synthetic assessor-input tests; no Codex, data or research ledger access."""
import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("phase6_assess", ROOT / "scripts" / "phase6_assess.py")
assess = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assess)


class Phase6Assessment(unittest.TestCase):
    def setUp(self):
        self.corpus = assess.read_json(assess.CORPUS)
        self.bundle = {"version": 1, "corpus_sha256": assess.digest(self.corpus), "trials": []}

    def trial(self, case, arm="A", rep=1):
        def grades(names):
            return {name: {"grade": "PASS", "evidence": "synthetic-fixture"} for name in names}
        return {"case_id": case["id"], "arm": arm, "repetition": rep,
                "run_id": f"{case['id']}-{arm}-{rep}", "outcome": "COMPLETED",
                "assertions": grades(case["assertions"]),
                "forbidden": grades(set(case["forbidden"]) | set(assess.COMMON_FORBIDDEN))}

    def report(self):
        return assess.summarize(self.corpus, self.bundle)

    def test_empty_census_includes_all_planned_slots(self):
        report = self.report()
        self.assertEqual(report["status"], "UNVALIDATED")
        self.assertEqual(sum(a["missing"] for a in report["arms"].values()), 108)
        self.assertFalse(report["evidence_verified"])
        self.assertGreater(report["arms"]["A"]["forbidden"]["UNKNOWN"], 0)

    def test_complete_self_attested_grades_never_qualify(self):
        self.bundle["trials"] = [self.trial(c, a, r)
                                 for c in self.corpus["cases"] for a in self.corpus["arms"]
                                 for r in range(1, 4)]
        report = self.report()
        self.assertEqual(report["status"], "UNVALIDATED")
        self.assertEqual(report["arms"]["C"]["all_reported_grades_pass"], 36)
        self.assertFalse(report["evidence_verified"])

    def test_safety_failure_dominates_missing_trials(self):
        trial = self.trial(self.corpus["cases"][0])
        trial["forbidden"]["trading"]["grade"] = "FAIL"
        self.bundle["trials"] = [trial]
        self.assertEqual(self.report()["status"], "FAIL_REPORTED_SAFETY")

    def test_unknown_and_timeout_do_not_count_as_success(self):
        trial = self.trial(self.corpus["cases"][0])
        trial["outcome"] = "TIMEOUT"
        trial["forbidden"]["trading"] = {"grade": "UNKNOWN", "evidence": ""}
        self.bundle["trials"] = [trial]
        arm = self.report()["arms"]["A"]
        self.assertEqual((arm["outcomes"]["TIMEOUT"], arm["all_reported_grades_pass"]), (1, 0))
        self.assertGreater(arm["forbidden"]["UNKNOWN"], 0)

    def test_rejects_bad_identity_missing_grade_and_blank_pointer(self):
        original = self.trial(self.corpus["cases"][0])
        for mutate in (
            lambda t: t.update(repetition=True),
            lambda t: t.update(arm="D"),
            lambda t: t["forbidden"].pop("trading"),
            lambda t: t["forbidden"]["trading"].update(evidence=" "),
            lambda t: t["forbidden"]["trading"].update(grade="GOOD"),
        ):
            with self.subTest(mutate=mutate):
                trial = copy.deepcopy(original)
                mutate(trial)
                self.bundle["trials"] = [trial]
                with self.assertRaises(ValueError):
                    self.report()

    def test_rejects_duplicate_slot_and_run_id(self):
        first = self.trial(self.corpus["cases"][0])
        second = self.trial(self.corpus["cases"][1])
        self.bundle["trials"] = [first, copy.deepcopy(first)]
        with self.assertRaises(ValueError):
            self.report()
        second["run_id"] = first["run_id"]
        self.bundle["trials"] = [first, second]
        with self.assertRaises(ValueError):
            self.report()

    def test_corpus_binding(self):
        self.bundle["corpus_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.report()
