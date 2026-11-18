import json, pathlib
out = pathlib.Path(__file__).resolve().parents[1] / "work" / "s2"
common = dict(schema_version="1.0.0", hypothesis_version=1, family_id="fam-crypto-stage02-v2", status="PROPOSED",
  venue="Binance spot public archive (data profile P1, USDT quote); execution venue UNSPECIFIED", instrument_type="SPOT",
  expected_direction="LONG", baseline="equal-weight buy-and-hold of the 9-asset cohort; BTC SMA200 daily long/cash; random-entry null with identical exits",
  dependencies=[], created_at_utc="2026-11-18T00:00:00Z", created_by="claude-code-stage02",
  source_refs=[{"ref": "docs/strategy-specs/STAGE_01_HANDOFF.v2.json", "kind": "FILE"}, {"ref": "docs/strategy-specs/STAGE_01_STRATEGY_SPECS.md", "kind": "FILE"}],
  instrument_id="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,DOGEUSDT,LTCUSDT",
  primary_estimand="sum(net P&L)/sum(reserved initial risk), baseline costs f=0.001 s=0.0005 per side (assumed, not observed)")
H = {
 "CRY-MOM-101": dict(hypothesis_id="hyp-cry-mom-101", horizon="4H signals, holds up to 30 days",
   mechanism="Risk-adjusted multi-week returns in large crypto assets are positively autocorrelated (slow information diffusion, herding).",
   economic_actor="trend-following and slow-moving discretionary capital", market_friction="gradual information diffusion; limits to arbitrage",
   null_hypothesis="Entries at M>=1.25 have no higher net R than entries at random eligible bars with identical exits.",
   necessary_regimes=["persistent directional markets"], failure_regimes=["range-bound chop", "V-shaped reversals"], preregistration_id="prereg-cry-mom-101"),
 "CRY-REV-102": dict(hypothesis_id="hyp-cry-rev-102", horizon="4H signals, holds up to 2 days",
   mechanism="Forced selling inside a long-term uptrend overshoots and partially reverses within days.",
   economic_actor="liquidity providers absorbing forced sellers", market_friction="liquidation and panic-driven overshoot",
   null_hypothesis="Entries after RSI3<=8 capitulation have no higher net R than random eligible entries with identical exits.",
   necessary_regimes=["uptrend dips", "wide range with ample liquidity"], failure_regimes=["cascade/contagion crashes", "structural breaks"], preregistration_id="prereg-cry-rev-102"),
 "CRY-VEX-103": dict(hypothesis_id="hyp-cry-vex-103", horizon="1H signals, holds up to 48 hours",
   mechanism="Volume-confirmed range-expansion breakouts mark informed or forced flow that continues for hours.",
   economic_actor="informed or forced flow", market_friction="gradual absorption of large order flow",
   null_hypothesis="Volume-confirmed breakouts have no higher net R than random eligible entries with identical exits, nor than the same rule without the volume condition.",
   necessary_regimes=["quiet-to-active volatility transition in liquid sessions"], failure_regimes=["thin or weekend liquidity", "fully retraced news spikes"], preregistration_id="prereg-cry-vex-103"),
}
src = "STAGE_01_HANDOFF.v2.json falsification_common (proposed, unvalidated)"
for sid, h in H.items():
    rec = dict(common, **h)
    rec["falsifiers"] = [dict(question=q, discriminating_test=t, threshold_source=src, outcome="PENDING") for q, t in [
        ("Is baseline net P&L/risk > 0 in validation (F1)?", "ratio on validation window"),
        ("Does the 99.17% one-sided block-bootstrap lower bound exceed 0 (F3)?", "circular block bootstrap, 14-day blocks, 10000 reps, seed 20261118"),
        ("Does the ratio exceed the 95th percentile of random-entry nulls (F4)?", "1000 random-entry draws with identical exits")]]
    (out / f"hyp_{sid}.json").write_text(json.dumps(rec, indent=1))
