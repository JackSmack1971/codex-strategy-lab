"""Synthetic workbench for Phase 4/5 tests. Every number is a fixture; none is evidence about markets."""
import random
import tempfile
from pathlib import Path

from research.experiments import dispatch
from research.ledger import Ledger
from tests.research import builders as b
from tests.research import flow as f

COST = 0.001
STRESS = [1, 2]
LEGACY = b.rng("2025-11-17T00:00:00Z", "2026-11-17T00:00:00Z")
FIXTURE_NOTE = "TEST FIXTURE value, not a research standard"
EXP_MODULE = "tests.research.fixture_experiments"


class Bench:
    def __init__(self, repo, led, pre):
        self.repo, self.led, self.pre = repo, led, pre


def make_repo():
    repo = Path(tempfile.mkdtemp(prefix="research-bench-"))
    for name in ("REPORT.md", "PREREGISTRATION.md", "STAGE_01_HANDOFF.json"):
        (repo / name).write_text(f"historical {name}")
    (repo / "results").mkdir()
    (repo / "results" / "assessment.json").write_text("{}")
    (repo / "work").mkdir()
    return repo


def prereg(holdout="UNTOUCHED", method="COUNT_ONLY", extra_gates=(), eval_split=None, only_gates=None, **over):
    pre = f.prereg(max_trials=4)
    pre["multiplicity"]["method"] = method
    if holdout == "CONSUMED_LEGACY":
        pre["splits"] = {"train": b.rng("2021-11-17T00:00:00Z", "2024-11-17T00:00:00Z"),
                         "validation": b.rng("2024-11-18T00:00:00Z", "2025-11-16T00:00:00Z"),
                         "test": LEGACY, "holdout_class": "CONSUMED_LEGACY"}
    else:
        pre["splits"]["holdout_class"] = holdout
    pre["embargo_purge"] = "one-day gap between splits (longer than the 1h label horizon and embargo)"
    pre["gate_rules"]["gates"] = [
        {"gate_id": "g-n", "mandatory": True, "metric": "n_trades", "comparator": ">=", "threshold": 30,
         "threshold_source": FIXTURE_NOTE},
        {"gate_id": "g-net-stress", "mandatory": True, "metric": "mean_net_return_stress_x2", "comparator": ">",
         "threshold": 0, "threshold_source": FIXTURE_NOTE},
        {"gate_id": "g-gross-info", "mandatory": False, "metric": "mean_gross_return", "comparator": ">",
         "threshold": 0, "threshold_source": FIXTURE_NOTE},
        *extra_gates]
    if only_gates is not None:
        pre["gate_rules"]["gates"] = list(only_gates)
    if eval_split:
        pre["economics"]["evaluation_split"] = eval_split
    pre.update(over)
    return pre


def setup_unstarted(holdout="UNTOUCHED", **kw):
    """Repo + empty ledger + preregistration; nothing registered yet."""
    repo = make_repo()
    return Bench(repo, Ledger(repo / "work" / "research", clock=f.seq_clock()), prereg(holdout, **kw))


def setup(holdout="UNTOUCHED", **kw):
    repo = make_repo()
    led = Ledger(repo / "work" / "research", clock=f.seq_clock())
    pre = prereg(holdout, **kw)
    f.to_state(led, "EXPERIMENT_PENDING", pre=pre)
    return Bench(repo, led, pre)


def returns(edge, n, seed):
    rnd = random.Random(seed)
    return [edge + rnd.uniform(-0.01, 0.01) for _ in range(n)]


def datasets(edge, n_test=60, seed=11):
    return {"train": lambda: returns(edge, 40, seed), "validation": lambda: returns(edge, 40, seed + 1),
            "test": lambda: returns(edge, n_test, seed + 2)}


def run_trial(bench, n=1, edge=0.01, *, experiment="edge_experiment", mode="brokered", report_override=None,
              n_test=60, trial_over=None, **kw):
    """Run one candidate. mode: 'brokered' (child process, in-memory data) | 'inproc' (advisory accounting)."""
    pre = bench.pre
    eval_split = pre["economics"]["evaluation_split"]
    cfg = {"edge": edge, "eval_split": eval_split, "range_start_utc": pre["splits"][eval_split]["start_utc"],
           "cost": pre["economics"]["cost_per_trade"], "stress": pre["economics"]["stress_multipliers"],
           "report_override": report_override or {}, "mutate": kw.pop("mutate", "none")}
    trial = f.trial_for(pre, n, **(trial_over or {}))
    in_memory = kw.pop("in_memory_datasets", True)
    if callable(experiment):
        exp, extra = experiment, {}
    elif mode == "brokered":
        exp, extra = f"{EXP_MODULE}:{experiment}", {"in_memory_datasets": in_memory}
    else:
        from tests.research import fixture_experiments as fe
        exp, extra = getattr(fe, experiment), {}
    return dispatch.run_candidate(bench.led, bench.repo, trial, exp, datasets(edge, n_test), f.ACTOR, config=cfg,
                                  dataset_digests=[b.fixture_manifest()["manifest_sha256"]], **extra, **kw)
