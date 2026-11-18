"""End-to-end synthetic slice driver (fixtures only; no market data, no performance claim).

Flow: register -> as-of verification -> data qualification -> adversarial objections (executed tests)
-> review outcome -> preregistration freeze -> isolated run -> deterministic adjudication -> report.
"""
from research import asof
from research.data import qualification as q
from research.experiments import dispatch, isolation, pipeline
from research.identifiers import digest
from research.reporting import render
from research.validation import adversarial, multiple_testing
from tests.research import builders as b
from tests.research import flow as f
from tests.research import slice as s

DECISION = "2026-01-01T00:00:10Z"
EXP = asof.Expectation(venue="SYNTHETIC", instrument_id="SYN-USD", instrument_type="SPOT", unit="USD")
SCENARIOS = {  # name -> (edge, leaks_future_feature, metric_override)
    "valid": (0.01, False, None),
    "true_negative": (-0.002, False, None),
    "future_leak": (0.01, True, None),
    "missing_eligibility": (0.01, False, "drop_eligibility"),
}


def observations(n=3):
    out = []
    for i in range(n):
        out.append(b.observation(observation_id=f"obs-{i:04d}", event_at_utc=f"2026-01-01T00:00:0{i}Z",
                                 published_at_utc=f"2026-01-01T00:00:0{i}Z", available_at_utc=f"2026-01-01T00:00:0{i + 1}Z",
                                 ingested_at_utc=f"2026-01-01T00:00:0{i + 2}Z", revision_id=f"rev-{i:04d}"))
    out.append(b.observation(observation_id="obs-late", event_at_utc="2026-01-01T00:00:05Z", available_at_utc="2026-01-01T00:01:00Z",
                             published_at_utc="2026-01-01T00:00:06Z", ingested_at_utc="2026-01-01T00:01:01Z", revision_id="rev-late"))
    return out


def objection(oid, review_type, spec, material=True):
    return {"schema_version": "1.0.0", "objection_id": oid, "hypothesis_id": f.HID, "hypothesis_version": f.VER,
            "review_type": review_type, "claim": "synthetic claim", "assumptions": ["fixture"], "test_specification": spec,
            "artifact_dependencies": ["fixture"], "severity": "HIGH", "materiality": "MATERIAL" if material else "NON_MATERIAL",
            "adjudication_status": "PENDING", "reviewer_agent_id": "fixture-reviewer", "reviewer_context_digest": "c" * 64,
            "submitted_at_utc": "2026-01-01T00:00:00Z"}


def run_slice(scenario, bench=None):
    edge, leak, mode = SCENARIOS[scenario]
    bench = bench or s.setup_unstarted()
    led, repo, pre = bench.led, bench.repo, bench.pre
    out = {"scenario": scenario}
    led.register_hypothesis(b.hypothesis(), f.ACTOR, "register")
    led.transition(f.HID, f.VER, "DATA_PENDING", f.ACTOR, "begin data qualification")
    chosen, excluded = asof.select_as_of(observations(), DECISION, EXP, latency_budget_ms=0)
    out["asof"] = {"chosen": [o["observation_id"] for o in chosen], "excluded": excluded}
    refs = [f"asof:{digest({'chosen': out['asof']['chosen'], 'excluded': [[o, list(c)] for o, c in excluded]})[:16]}"]
    led.transition(f.HID, f.VER, "DATA_QUALIFIED", f.ACTOR, "as-of verified", refs + f.evidence_refs(led, "DATA_QUALIFIED"))
    led.transition(f.HID, f.VER, "REVIEW_PENDING", f.ACTOR, "critics", ["tasks:causal,statistical"])
    features = {"momentum": "2026-01-01T00:00:00Z"}
    if leak:
        features["next_bar_return"] = "2026-01-01T00:00:01Z"      # fabricated future-data feature
    samples = [{"decision_at": "2026-01-01T00:00:00Z", "features": features}]
    val = s.returns(edge, 40, 12)
    objs = [adversarial.execute(objection("obj-causal-leak", "causal", {"type": "LEAKAGE_AUDIT", "params": {}}), {"samples": samples}, "2026-01-01T00:00:05Z"),
            adversarial.execute(objection("obj-stat-overlap", "statistical", {"type": "LABEL_OVERLAP", "params": {"label_horizon_s": 3600, "embargo_s": 3600}}),
                                {"train_end_utc": pre["splits"]["train"]["end_utc"], "validation_start_utc": pre["splits"]["validation"]["start_utc"]}, "2026-01-01T00:00:05Z"),
            adversarial.execute(objection("obj-exec-cost", "execution", {"type": "COST_STRESS", "params": {"multiplier": 2}}, material=False),
                                {"returns": val, "cost_per_trade": s.COST}, "2026-01-01T00:00:05Z")]
    out["objections"] = objs
    outcome = adversarial.review_outcome(objs)
    out["review"] = outcome
    if outcome["state"] == "BLOCKED":
        led.transition(f.HID, f.VER, "BLOCKED", f.ACTOR, "review outcome", outcome["evidence_refs"])
        return out
    bundle = {"objections": objs, "evidence": {"obj-causal-leak": {"samples": samples},
                                                "obj-stat-overlap": {"train_end_utc": pre["splits"]["train"]["end_utc"],
                                                                     "validation_start_utc": pre["splits"]["validation"]["start_utc"]},
                                                "obj-exec-cost": {"returns": val, "cost_per_trade": s.COST}}}
    led.transition(f.HID, f.VER, "REVIEW_RECORDED", f.ACTOR, "review outcome",
                   [f"review:{led.evidence.store.put(bundle)}"] + outcome["evidence_refs"])
    from research.prereg import freeze
    freeze(led, pre, f.ACTOR, "freeze before any confirmation exposure")
    led.transition(f.HID, f.VER, "EXPERIMENT_PENDING", f.ACTOR, "start", ["prereg:frozen"])
    out["run"] = s.run_trial(bench, 1, edge, mode="brokered")
    res = pipeline.adjudicate_trial(led, repo, "trial-0001", f.ACTOR)
    out["adjudication"] = res
    view = led.view()
    t = view.trials["trial-0001"]
    rep = render.build_report(record=res["record"], trial=t, family=multiple_testing.family_summary(view, t["family_id"]),
                              artifact_hashes=view.runs[t["run_id"]]["artifact_hashes"], preregistration_sha256=view.hyp[(f.HID, f.VER)]["prereg_sha"],
                              data_kind="SYNTHETIC_FIXTURE", objections=objs)
    md = render.render_markdown(rep)
    rd = isolation.RunDir(repo, t["run_id"], "research-reports").create()
    rd.write("report.json", rep); rd.write_text("report.md", md)
    out.update(report=rep, markdown=md, report_dir=rd.path)
    return out
