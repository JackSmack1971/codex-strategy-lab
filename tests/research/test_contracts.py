import json
import unittest
from pathlib import Path

from research import contracts as c
from research.identifiers import CanonicalizationError, canonical_bytes, derived_id, digest
from tests.research import builders as b


def codes(kind, rec):
    return {i.code for i in c.validate(kind, rec)}


class ValidRecords(unittest.TestCase):
    def test_every_builder_is_valid(self):
        for kind, build in b.BUILDERS.items():
            with self.subTest(kind=kind):
                self.assertEqual(c.validate(kind, build()), [])

    def test_schema_files_cover_all_kinds_and_share_one_version_authority(self):
        for kind in c.KINDS:
            self.assertEqual(c.supported_versions(kind), frozenset({"1.0.0"}))
            self.assertEqual(c.load_schema(kind)["properties"]["schema_version"]["const"], "1.0.0")


class StructuralRejections(unittest.TestCase):
    def test_missing_required_extra_field_and_wrong_types(self):
        for kind, build in b.BUILDERS.items():
            rec = build(); first = [k for k in c.load_schema(kind)["required"] if k != "schema_version"][0]
            del rec[first]
            self.assertIn("REQUIRED", codes(kind, rec), kind)
            self.assertIn("ADDITIONAL_PROPERTY", codes(kind, build(surprise=1)), kind)
        self.assertIn("TYPE", codes("trial", b.trial(trial_sequence="1")))
        self.assertIn("TYPE", codes("trial", b.trial(trial_sequence=1.0)))   # float is not an integer
        self.assertIn("TYPE", codes("trial", b.trial(random_seed=True)))     # bool is not an integer

    def test_unsupported_and_missing_schema_version(self):
        self.assertEqual(codes("trial", b.trial(schema_version="2.0.0")), {"SCHEMA_VERSION_UNSUPPORTED"})
        rec = b.trial(); del rec["schema_version"]
        self.assertEqual(codes("trial", rec), {"SCHEMA_VERSION_UNSUPPORTED"})
        self.assertEqual({i.code for i in c.validate("nonsense", {})}, {"UNKNOWN_KIND"})
        self.assertEqual({i.code for i in c.validate("trial", [])}, {"TYPE"})

    def test_timestamps_must_be_utc_z_and_real(self):
        for bad in ["2026-01-01T00:00:00", "2026-01-01T00:00:00+00:00", "2026-01-01 00:00:00Z",
                    "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z", "2026-01-01T00:00:00.1234567Z", 5]:
            with self.subTest(bad=bad):
                self.assertTrue(codes("trial", b.trial(start_time=bad)) & {"FORMAT", "TYPE"})
        self.assertEqual(c.validate("trial", b.trial(start_time="2026-01-01T00:00:00.123456Z")), [])

    def test_identifiers_hashes_and_enums(self):
        self.assertIn("PATTERN", codes("trial", b.trial(trial_id="x")))
        self.assertIn("PATTERN", codes("trial", b.trial(trial_id="bad id with spaces")))
        self.assertIn("PATTERN", codes("trial", b.trial(feature_set_hash="A" * 64)))
        self.assertIn("PATTERN", codes("trial", b.trial(code_commit="abc")))
        self.assertIn("ENUM", codes("trial", b.trial(status="DONE")))
        self.assertIn("ENUM", codes("adjudication", b.adjudication(decision="WINNER")))

    def test_null_is_never_accepted_and_unknown_only_where_declared(self):
        self.assertIn("TYPE", codes("trial", b.trial(random_seed=None)))
        self.assertEqual(c.validate("run_manifest", b.run_manifest(codex_version_if_observed="UNKNOWN")), [])
        self.assertIn("ANYOF", codes("run_manifest", b.run_manifest(codex_version_if_observed=None)))
        self.assertEqual(codes("trial", b.trial(requested_by="UNKNOWN")), set())  # plain text field
        self.assertIn("ENUM", codes("trial", b.trial(holdout_class="UNKNOWN")))     # not declared UNKNOWN-able

    def test_observation_absent_publication_needs_reason_and_availability_may_be_unknown(self):
        self.assertEqual(c.validate("observation", b.observation(
            published_at_utc={"absent_reason": "provider gives no publication time"})), [])
        self.assertIn("ANYOF", codes("observation", b.observation(published_at_utc={})))
        self.assertIn("ANYOF", codes("observation", b.observation(published_at_utc="UNKNOWN")))
        self.assertEqual(c.validate("observation", b.observation(available_at_utc="UNKNOWN")), [])

    def test_numeric_ranges(self):
        self.assertIn("RANGE", codes("trial", b.trial(trial_sequence=0)))
        self.assertIn("RANGE", codes("observation", b.observation(precision=19)))
        self.assertIn("TYPE", codes("observation", b.observation(value=float("nan"))))
        self.assertEqual(codes("observation", b.observation(value=2**70)), {"NOT_CANONICALIZABLE"})

    def test_issue_order_is_deterministic(self):
        rec = b.trial(trial_id="x", status="DONE", random_seed=-1)
        first = c.validate("trial", rec)
        self.assertEqual(first, c.validate("trial", dict(reversed(list(rec.items())))))
        self.assertEqual(first, sorted(first))


class SemanticRejections(unittest.TestCase):
    def test_observation_time_ordering(self):
        self.assertIn("TIME_ORDER", codes("observation", b.observation(available_at_utc="2026-01-01T00:00:00Z")))
        self.assertIn("TIME_ORDER", codes("observation", b.observation(ingested_at_utc="2026-01-01T00:00:01Z")))

    def test_trial_rules(self):
        self.assertIn("SPLIT_OVERLAP", codes("trial", b.trial(
            validation_range=b.rng("2018-06-01T00:00:00Z", "2020-01-01T00:00:00Z"))))
        self.assertIn("RANGE_ORDER", codes("trial", b.trial(train_range=b.rng("2021-01-01T00:00:00Z", "2020-01-01T00:00:00Z"))))
        self.assertIn("END_TIME_REQUIRED", codes("trial", b.trial(status="COMPLETED")))
        self.assertIn("END_TIME_FORBIDDEN", codes("trial", b.trial(end_time="2026-01-02T00:00:00Z")))
        self.assertIn("FAILURE_CODE_REQUIRED", codes("trial", b.trial(status="FAILED", end_time="2026-01-02T00:00:00Z")))
        self.assertIn("TEST_ACCESS_WITHOUT_RANGE", codes("trial", b.trial(test_access_count=1)))
        self.assertEqual(c.validate("trial", b.trial(status="FAILED", end_time="2026-01-02T00:00:00Z", failure_code="E_TIMEOUT")), [])

    def test_consumed_legacy_window_cannot_be_untouched(self):  # blueprint G11
        legacy = b.rng("2025-11-17T00:00:00Z", "2026-11-17T00:00:00Z")
        pre = b.preregistration()
        pre["splits"]["test"] = legacy
        self.assertIn("HOLDOUT_CONSUMED", codes("preregistration", pre))
        pre["splits"]["holdout_class"] = "CONSUMED_LEGACY"
        self.assertEqual(c.validate("preregistration", pre), [])
        self.assertIn("HOLDOUT_CONSUMED", codes("trial", b.trial(
            holdout_class="UNTOUCHED", test_range=legacy, test_access_count=1,
            validation_range=b.rng("2021-01-01T00:00:00Z", "2025-11-17T00:00:00Z"))))

    def test_preregistration_rules(self):
        self.assertIn("AMENDMENT_INCOMPLETE", codes("preregistration", b.preregistration(amendment=1)))
        self.assertIn("AMENDMENT_INCOMPLETE", codes("preregistration", b.preregistration(amends_sha256=b.SHA_A)))
        self.assertEqual(c.validate("preregistration", b.preregistration(
            amendment=1, amends_sha256=b.SHA_A, amendment_reason="clarify")), [])
        pre = b.preregistration(); pre["multiplicity"]["planned_trials"] = 99
        self.assertIn("BUDGET_EXCEEDED", codes("preregistration", pre))
        pre = b.preregistration(); pre["multiplicity"]["family_id"] = "fam-other"
        self.assertIn("FAMILY_MISMATCH", codes("preregistration", pre))
        pre = b.preregistration(); pre["gate_rules"]["gates"][1]["gate_id"] = "g-net"
        self.assertIn("DUPLICATE_ID", codes("preregistration", pre))
        pre = b.preregistration()
        for g in pre["gate_rules"]["gates"]:
            g["mandatory"] = False
        self.assertIn("NO_MANDATORY_GATE", codes("preregistration", pre))
        pre = b.preregistration(); pre["splits"]["validation"] = b.rng("2018-06-01T00:00:00Z", "2020-01-01T00:00:00Z")
        self.assertIn("SPLIT_OVERLAP", codes("preregistration", pre))

    def test_adjudication_cannot_qualify_with_unknown_or_failed_mandatory_gate(self):  # G13
        for bad in ("UNKNOWN", "FAIL", "NOT_APPLICABLE"):
            adj = b.adjudication(); adj["gate_results"][0]["value"] = bad
            self.assertIn("QUALIFIED_WITH_NONPASS_GATE", codes("adjudication", adj), bad)
        adj = b.adjudication(holdout_integrity="CONSUMED_LEGACY")
        self.assertIn("QUALIFIED_WITHOUT_CLEAN_HOLDOUT", codes("adjudication", adj))
        self.assertIn("QUALIFIED_WITH_UNKNOWN_ESTIMATE", codes("adjudication", b.adjudication(economic_estimate="UNKNOWN")))
        adj = b.adjudication(); adj["gate_results"][0]["proof_refs"] = []
        self.assertIn("PROOF_REQUIRED", codes("adjudication", adj))
        adj = b.adjudication(decision="INVESTIGATE"); adj["gate_results"][0]["value"] = "UNKNOWN"; adj["gate_results"][0]["proof_refs"] = []
        self.assertEqual(c.validate("adjudication", adj), [])

    def test_run_manifest_rules(self):
        self.assertIn("END_TIME_REQUIRED", codes("run_manifest", b.run_manifest(status="COMPLETED")))
        self.assertIn("COUNT_ORDER", codes("run_manifest", b.run_manifest(tests_executed=1, tests_failed=2)))


class SchemaSubsetIsExplicit(unittest.TestCase):
    def test_unsupported_keywords_fail_closed(self):
        for node in ({"oneOf": []}, {"allOf": []}, {"not": {}}, {"format": "date-time"},
                     {"x-format": "other"}, {"patternProperties": {}}):
            with self.assertRaises(c.SchemaError, msg=str(node)):
                c._check_schema_node(node, "t")

    def test_all_shipped_schemas_use_only_supported_keywords(self):
        for p in sorted(c.SCHEMA_DIR.glob("*.schema.json")):
            c.load_schema(p.name[: -len(".schema.json")])

    def test_subset_keyword_behaviour(self):
        def run(node, inst):
            out = []; c._validate(inst, node, "", "common", out); return {i.code for i in out}
        self.assertEqual(run({"type": ["string", "integer"]}, 3), set())
        self.assertEqual(run({"type": "number"}, True), {"TYPE"})
        self.assertEqual(run({"const": 1}, True), {"CONST"})
        self.assertEqual(run({"enum": [1]}, True), {"ENUM"})
        self.assertEqual(run({"minItems": 2}, [1]), {"LENGTH"})
        self.assertEqual(run({"maxItems": 1}, [1, 2]), {"LENGTH"})
        self.assertEqual(run({"minLength": 3}, "ab"), {"LENGTH"})
        self.assertEqual(run({"type": "object", "additionalProperties": {"type": "integer"}}, {"a": "x"}), {"TYPE"})
        self.assertEqual(run({"anyOf": [{"type": "integer"}, {"const": "UNKNOWN"}]}, "no"), {"ANYOF"})
        self.assertEqual(run({"minimum": 0, "maximum": 1}, 2), {"RANGE"})

    def test_every_schema_file_is_valid_json_with_dialect(self):
        for p in c.SCHEMA_DIR.glob("*.schema.json"):
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["$schema"], c.SCHEMA_DIALECT)


class CanonicalHashing(unittest.TestCase):
    def test_hash_is_stable_across_key_order_and_numeric_spelling(self):
        a = {"b": 1, "a": [1.0, {"y": 2, "x": 3}]}
        z = {"a": [1, {"x": 3, "y": 2}], "b": 1.0}
        self.assertEqual(digest(a), digest(z))
        self.assertEqual(canonical_bytes({"v": -0.0}), canonical_bytes({"v": 0}))
        self.assertNotEqual(digest({"v": 1.5}), digest({"v": 1.50000001}))

    def test_record_digest_is_order_independent_and_changes_with_content(self):
        rec = b.trial()
        shuffled = dict(reversed(list(rec.items())))
        self.assertEqual(c.require_valid("trial", rec), c.require_valid("trial", shuffled))
        self.assertNotEqual(c.require_valid("trial", rec), c.require_valid("trial", b.trial(random_seed=8)))
        self.assertEqual(c.require_valid("trial", json.loads(json.dumps(rec))), c.require_valid("trial", rec))

    def test_non_canonical_inputs_rejected(self):
        for bad in (float("nan"), float("inf"), {1: "x"}, (1, 2), {"a"}, 2**63, object(), "\ud800"):
            with self.assertRaises(CanonicalizationError, msg=repr(bad)):
                canonical_bytes({"v": bad})

    def test_derived_id_is_idempotent_and_namespaced(self):
        self.assertEqual(derived_id("hyp", "k1"), derived_id("hyp", "k1"))
        self.assertNotEqual(derived_id("hyp", "k1"), derived_id("trial", "k1"))
        self.assertNotEqual(derived_id("hyp", "k1"), derived_id("hyp", "k2"))
        self.assertEqual(c.validate("trial", b.trial(trial_id=derived_id("trial", "k1"))), [])
        with self.assertRaises(ValueError):
            derived_id("hyp", "")

    def test_require_valid_raises_with_codes(self):
        with self.assertRaises(c.ContractError) as ctx:
            c.require_valid("trial", b.trial(status="DONE"))
        self.assertIn("ENUM", ctx.exception.codes)


if __name__ == "__main__":
    unittest.main()
