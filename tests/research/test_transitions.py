import unittest

from research import lifecycle as lc
from research.contracts import ContractError, load_schema

LEGAL = {
    ("DRAFT", "REGISTERED"), ("REGISTERED", "DATA_PENDING"), ("REGISTERED", "BLOCKED"),
    ("DATA_PENDING", "DATA_QUALIFIED"), ("DATA_PENDING", "BLOCKED"),
    ("DATA_QUALIFIED", "REVIEW_PENDING"), ("REVIEW_PENDING", "REVIEW_RECORDED"),
    ("REVIEW_PENDING", "BLOCKED"), ("REVIEW_RECORDED", "PREREG_FROZEN"),
    ("PREREG_FROZEN", "EXPERIMENT_PENDING"), ("EXPERIMENT_PENDING", "EXPERIMENT_COMPLETE"),
    ("EXPERIMENT_PENDING", "FAILED"), ("EXPERIMENT_COMPLETE", "ADJUDICATED"), ("ADJUDICATED", "REPORTED"),
}
KW = dict(hypothesis_id="hyp-synthetic-001", hypothesis_version=1, actor="tester", reason="because",
          evidence_refs=["ev1"], timestamp_utc="2026-01-01T00:00:00Z", prior_state_digest="0" * 64)


class Transitions(unittest.TestCase):
    def test_states_come_from_schema_and_table_covers_all(self):
        self.assertEqual(set(lc.STATES), set(load_schema("common")["$defs"]["workflow_state"]["enum"]))
        self.assertEqual(set(lc.TRANSITIONS), set(lc.STATES))
        for targets in lc.TRANSITIONS.values():
            self.assertLessEqual(targets, set(lc.STATES))

    def test_every_legal_transition_accepted_and_every_other_rejected(self):
        for a in lc.STATES:
            for b in lc.STATES:
                with self.subTest(a=a, b=b):
                    if (a, b) in LEGAL:
                        lc.check_transition(a, b)
                        self.assertTrue(lc.is_legal(a, b))
                    else:
                        with self.assertRaises(ContractError):
                            lc.check_transition(a, b)
                        self.assertFalse(lc.is_legal(a, b))

    def test_terminal_states_and_unknown_state_codes(self):
        for s in ("REPORTED", "BLOCKED", "FAILED"):
            with self.assertRaises(ContractError) as ctx:
                lc.check_transition(s, "REGISTERED")
            self.assertIn("TERMINAL_STATE", ctx.exception.codes)
        with self.assertRaises(ContractError) as ctx:
            lc.check_transition("DRAFT", "NOPE")
        self.assertIn("UNKNOWN_STATE", ctx.exception.codes)

    def test_failed_run_is_workflow_not_disposition(self):
        self.assertNotIn("FAILED", lc.DISPOSITIONS)
        self.assertNotIn("REJECT", lc.STATES)
        self.assertTrue(set(lc.DISPOSITIONS).isdisjoint(set(lc.STATES) - {"BLOCKED"}))

    def test_no_state_skips_prereg_freeze_before_experiment(self):
        # experiment can only be reached through PREREG_FROZEN
        preds = [a for a, t in lc.TRANSITIONS.items() if "EXPERIMENT_PENDING" in t]
        self.assertEqual(preds, ["PREREG_FROZEN"])

    def test_transition_record_is_deterministic_and_validated(self):
        a = lc.make_transition(current="DRAFT", target="REGISTERED", **KW)
        b = lc.make_transition(current="DRAFT", target="REGISTERED", **KW)
        self.assertEqual(a, b)
        self.assertEqual(len(a["transition_digest"]), 64)
        for bad in ({"reason": " "}, {"actor": ""}, {"timestamp_utc": "2026-01-01"}):
            with self.assertRaises((ContractError, ValueError)):
                lc.make_transition(current="DRAFT", target="REGISTERED", **{**KW, **bad})
        with self.assertRaises(ContractError):
            lc.make_transition(current="DRAFT", target="ADJUDICATED", **KW)

    def test_state_digest_changes_with_state(self):
        self.assertNotEqual(lc.state_digest("h", 1, "DRAFT"), lc.state_digest("h", 1, "REGISTERED"))


if __name__ == "__main__":
    unittest.main()
