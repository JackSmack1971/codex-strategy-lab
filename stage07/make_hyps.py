"""Stage 07: one hypothesis record per allocation scheme, for ledger registration BEFORE any run."""
import json, pathlib
out = pathlib.Path(__file__).resolve().parents[1] / "work" / "s7"; out.mkdir(parents=True, exist_ok=True)
S = {"ew": ("Equal capital weight across the two eligible sleeves is a robust default when estimates of volatility and correlation are noisy.", "EW"),
     "iv": ("Weighting sleeves by inverse standalone volatility equalises their stand-alone risk and needs only volatility estimates.", "IV"),
     "rb": ("Risk contributions set to the Stage 03 evidence ratio (2/3 MOM, 1/3 VEX) give the better-evidenced sleeve more risk.", "RB"),
     "cons": ("Stage 03 conservative budgets (0.50/0.25 of capital, 25% cash) with stop-trading rules limit loss while evidence is unverified.", "CONS")}
common = dict(schema_version="1.0.0", hypothesis_version=1, family_id="fam-crypto-stage07-v1", status="PROPOSED",
  venue="Binance spot public archive (data profile P1, USDT quote); execution venue UNSPECIFIED", instrument_type="SPOT", expected_direction="LONG",
  baseline="100% cash and each eligible sleeve alone (Stage 06 frozen baselines) on identical windows and costs",
  created_at_utc="2026-11-18T00:00:00Z", created_by="claude-code-stage07",
  source_refs=[{"ref": "docs/strategy-specs/STAGE_07_ANALYSIS_PLAN.md", "kind": "FILE"}, {"ref": "docs/strategy-specs/STAGE_06_HANDOFF.json", "kind": "FILE"}, {"ref": "docs/strategy-specs/STAGE_03_HANDOFF.json", "kind": "FILE"}],
  instrument_id="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,DOGEUSDT,LTCUSDT",
  primary_estimand="pooled walk-forward out-of-sample portfolio daily-return Sharpe and 99% one-day expected shortfall, 5 anchored 6-month folds 2023-05-17..2025-11-17, baseline costs assumed")
for k, (mech, tag) in S.items():
    hid = f"hyp-cry-portfolio-s7-{k}"
    rec = dict(common, hypothesis_id=hid, dependencies=["hyp-cry-mom-101", "hyp-cry-vex-103"], horizon="portfolio, daily marks, sleeve weights re-estimated at most every 6 months",
      mechanism=f"{tag}: {mech}", economic_actor="a single account allocating risk capital between two long-only spot sleeves", market_friction="crypto assets share one dominant factor; sleeve return and tail estimates come from few events",
      null_hypothesis=f"Scheme {tag} does not improve out-of-sample risk-adjusted return or expected shortfall over the better single sleeve, and the allocation is not supported by independent validation.",
      necessary_regimes=["regimes in which at least one sleeve has positive expectancy"], failure_regimes=["correlated crypto drawdowns", "cost-stress regimes"],
      preregistration_id=f"prereg-cry-portfolio-s7-{k}",
      falsifiers=[dict(question=q, discriminating_test=t, threshold_source="STAGE_07_ANALYSIS_PLAN.md (predeclared, uncalibrated)", outcome="PENDING") for q, t in [
        ("Is the pooled walk-forward portfolio Sharpe > 0 with a 95% block-bootstrap lower bound > 0 (V5)?", "5 anchored folds; circular block bootstrap 14d, 10000 reps, seed 20261118"),
        ("Do validation gates V1-V4 and V6 (holdout, forward evidence, venue, preregistration, open regime gate) pass?", "Stage 03/04/06 handoffs")]])
    (out / f"{hid}.json").write_text(json.dumps(rec, indent=1))
print(len(list(out.glob("hyp-*.json"))))
