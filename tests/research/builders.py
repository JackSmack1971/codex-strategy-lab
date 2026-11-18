"""Valid synthetic records for tests. Values are fixtures, never research results."""
import copy

from research.data import qualification as _q
from research.identifiers import digest as _digest

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
COMMIT = "0123456789abcdef0123456789abcdef01234567"
T0 = "2026-01-01T00:00:00Z"


def rng(a, b):
    return {"start_utc": a, "end_utc": b}


def fixture_manifest(instrument="SYN-USD", last_open="2026-11-17T00:00:00Z"):
    body = {"kind": "OHLCV", "venue": "SYNTHETIC", "instrument_id": instrument, "instrument_type": "SPOT", "interval": "1h",
            "provider": "fixture", "bars": 1, "first_open_utc": "2017-12-31T00:00:00Z", "last_open_utc": last_open,
            "missing_bars": 0, "off_grid_bars": 0, "retrieved_utc": "2026-11-18T00:00:00Z",
            "archives": [{"name": "x.zip", "sha256": SHA_A}]}
    return dict(body, manifest_sha256=_digest(body))


def dataset_bundle(instrument="SYN-USD"):
    man = fixture_manifest(instrument)
    crit = {"require_start_utc": "2018-01-01T00:00:00Z", "require_end_utc": "2026-11-17T00:00:00Z", "max_missing_bars": 0,
            "max_off_grid_bars": 0}
    return {"manifest": man, "certificate": _q.qualify_ohlcv(man, **crit), "criteria": crit}


def hypothesis(**over):
    rec = {
        "schema_version": "1.0.0", "hypothesis_id": "hyp-synthetic-001", "hypothesis_version": 1,
        "family_id": "fam-synthetic", "status": "PROPOSED",
        "mechanism": "Synthetic mechanism used only to exercise contracts.",
        "economic_actor": "synthetic actor", "market_friction": "synthetic friction",
        "venue": "SYNTHETIC", "instrument_id": "SYN-USD", "instrument_type": "SPOT",
        "horizon": "1h", "expected_direction": "LONG",
        "null_hypothesis": "No incremental net return over baseline.",
        "primary_estimand": "net return per trade", "baseline": "no-signal",
        "falsifiers": [{"question": "Does edge survive costs?", "discriminating_test": "cost stress",
                        "threshold_source": "preregistration gate g-net", "outcome": "PENDING"}],
        "necessary_regimes": ["any"], "failure_regimes": ["none-declared"], "dependencies": [],
        "preregistration_id": "prereg-synthetic-001", "created_at_utc": T0,
        "created_by": "test-fixture", "source_refs": [],
    }
    rec.update(over)
    return rec


def preregistration(**over):
    rec = {
        "schema_version": "1.0.0", "preregistration_id": "prereg-synthetic-001", "amendment": 0,
        "family_id": "fam-synthetic", "hypothesis_id": "hyp-synthetic-001", "hypothesis_version": 1,
        "mechanism": "synthetic", "universe_construction": "synthetic universe",
        "venue_eligibility": "synthetic venue", "data_asof_rule": "available_at <= decision_at",
        "information_schedule": "synthetic schedule",
        "splits": {"train": rng("2018-01-01T00:00:00Z", "2019-01-01T00:00:00Z"),
                   "validation": rng("2019-01-02T00:00:00Z", "2020-01-01T00:00:00Z"),
                   "test": rng("2020-01-02T00:00:00Z", "2021-01-01T00:00:00Z"),
                   "holdout_class": "UNTOUCHED"},
        "datasets": [{"dataset_id": "ds-synthetic", "snapshot_id": "snap-0001", "manifest_sha256": fixture_manifest()["manifest_sha256"],
                      "instrument_id": "SYN-USD"}],
        "economics": {"cost_per_trade": 0.001, "stress_multipliers": [1, 2], "evaluation_split": "test"},
        "purge": {"label_horizon_s": 3600, "embargo_s": 3600},
        "embargo_purge": "none required for synthetic data", "baselines": ["no-signal"],
        "cost_capacity_assumptions": "synthetic costs", "estimand": "net return",
        "uncertainty_method": "synthetic block bootstrap",
        "multiplicity": {"family_id": "fam-synthetic", "method": "COUNT_ONLY", "planned_trials": 4, "alpha": 0.05},
        "min_sample_size": 30, "robustness_criteria": ["cost stress"], "planned_ablations": [],
        "stopping_rule": "max_trials", "research_budget": {"max_trials": 8},
        "disclosure_rules": "report all trials",
        "gate_rules": {"rule_version": "rules-test-1", "gates": [
            {"gate_id": "g-net", "mandatory": True, "metric": "net_return", "comparator": ">",
             "threshold": 0, "threshold_source": "TEST FIXTURE value, not a research standard"},
            {"gate_id": "g-n", "mandatory": True, "metric": "n_trades", "comparator": ">=",
             "threshold": 30, "threshold_source": "TEST FIXTURE value, not a research standard"}]},
        "frozen_at_utc": T0,
    }
    rec.update(over)
    return rec


def observation(**over):
    rec = {
        "schema_version": "1.0.0", "observation_id": "obs-0001", "source_id": "src-synthetic",
        "provider_version": "synthetic-1", "retrieval_id": "ret-0001", "venue": "SYNTHETIC",
        "instrument_id": "SYN-USD", "instrument_type": "SPOT", "unit": "USD", "clock": "EXCHANGE",
        "event_at_utc": "2026-01-01T00:00:00Z", "published_at_utc": "2026-01-01T00:00:01Z",
        "available_at_utc": "2026-01-01T00:00:02Z", "ingested_at_utc": "2026-01-01T00:00:03Z",
        "revision_id": "rev-0001", "value": 100.5, "raw_sha256": SHA_A, "precision": 2,
        "quality_flags": [],
    }
    rec.update(over)
    return rec


def trial(**over):
    rec = {
        "schema_version": "1.0.0", "trial_id": "trial-0001", "hypothesis_id": "hyp-synthetic-001",
        "hypothesis_version": 1, "family_id": "fam-synthetic", "preregistration_sha256": SHA_A,
        "trial_sequence": 1, "run_id": "run-0001", "data_snapshot_ids": ["snap-0001"],
        "train_range": rng("2018-01-01T00:00:00Z", "2019-01-01T00:00:00Z"),
        "validation_range": rng("2019-01-02T00:00:00Z", "2020-01-01T00:00:00Z"),
        "holdout_class": "EXPLORATORY_OR_REUSED", "test_access_count": 0,
        "feature_set_hash": SHA_A, "parameter_hash": SHA_B, "code_commit": COMMIT,
        "cost_model_hash": SHA_A, "execution_model_hash": SHA_B, "random_seed": 7,
        "requested_by": "test-fixture", "start_time": T0, "status": "STARTED",
    }
    rec.update(over)
    return rec


def adjudication(**over):
    rec = {
        "schema_version": "1.0.0", "hypothesis_id": "hyp-synthetic-001", "hypothesis_version": 1,
        "run_id": "run-0001",
        "gate_results": [
            {"gate_id": "g-net", "mandatory": True, "value": "PASS", "proof_refs": ["metrics.json"]},
            {"gate_id": "g-n", "mandatory": True, "value": "PASS", "proof_refs": ["metrics.json"]}],
        "family_multiplicity_ref": "fam-synthetic@ledger", "economic_estimate": 0.01,
        "uncertainty_method": "synthetic", "data_limitations": ["synthetic data"],
        "execution_limitations": ["synthetic fills"], "holdout_integrity": "UNTOUCHED",
        "decision": "QUALIFIED", "decision_rule_digest": SHA_A, "adjudication_code_digest": SHA_B,
        "created_at_utc": T0, "evidence_bindings": {},
    }
    rec.update(over)
    return rec


def run_manifest(**over):
    rec = {
        "schema_version": "1.0.0", "run_id": "run-0001", "recorded_at": T0, "git_head_oid": COMMIT,
        "source_dirty_state": "CLEAN", "source_digests": {"lab.py": SHA_A}, "prereg_sha256": SHA_A,
        "dataset_manifest_digests": [SHA_B], "experiment_configuration_digest": SHA_C,
        "python_version": "3.12.13", "dependency_lock_sha256": "UNKNOWN",
        "runner_command_redacted": "research run <redacted>", "execution_surface": "LOCAL_SCRIPT",
        "codex_version_if_observed": "UNKNOWN", "effective_permissions_if_observed": "UNKNOWN",
        "network_policy_if_observed": "UNKNOWN", "start_utc": T0, "artifact_hashes": {},
        "tests_executed": 0, "tests_failed": 0, "status": "STARTED",
        "data_access_enforcement": "IN_PROCESS_UNENFORCED",
    }
    rec.update(over)
    return rec


BUILDERS = {"hypothesis": hypothesis, "preregistration": preregistration, "observation": observation,
            "trial": trial, "adjudication": adjudication, "run_manifest": run_manifest}


def clone(rec):
    return copy.deepcopy(rec)
