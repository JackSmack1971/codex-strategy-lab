"""Stage 06: write one hypothesis record per (strategy x change family) for ledger registration BEFORE any real-data run."""
import json, pathlib
from . import variants as V
out = pathlib.Path(__file__).resolve().parents[1] / "work" / "s6"; out.mkdir(parents=True, exist_ok=True)
RAT = {
 "PARAM": ("Indicator parameters near the Stage 01 values sit on a smooth performance surface; a one-step move may reduce lag or noise without changing the mechanism.", "any one-step change in lookback/threshold (MOM) or Donchian/range-expansion multiple (VEX)"),
 "ENTRY_CONFIRM": ("Requiring the trigger to persist (MOM: K consecutive bars; VEX: stronger close location) filters one-bar noise and false breakouts at the cost of later entry.", "stricter trigger persistence"),
 "VOL_FILTER": ("Entering right after a volatility spike (MOM) mimics late entry into V-reversals; requiring prior compression (VEX) isolates quiet-to-active transitions as the Stage 01 hypothesis states.", "a causal volatility-ratio / compression entry filter"),
 "TREND_FILTER": ("Limiting extension above the 300-bar mean (MOM) or demanding a stronger 4H trend context (VEX) avoids exhausted moves / counter-trend breakouts.", "a stricter trend or extension filter"),
 "LIQ_FILTER": ("Higher liquidity floors (MOM) or stronger volume confirmation and no weekend entries (VEX) reduce the chance that assumed flat costs understate real impact.", "a stricter liquidity/volume/session filter"),
 "STOP": ("The ATR multiples of the initial and trailing stop trade whipsaw risk against give-back; narrow multiples around the Stage 01 values test local sensitivity.", "a different initial/trailing ATR stop multiple"),
 "EXIT_CONFIRM": ("Requiring more than one completed bar of an exit condition (MOM) or a longer failed-breakout window (VEX) reduces exits on single-bar noise at the cost of larger give-back.", "a confirmed signal exit / longer failure window"),
 "FACTOR_OVERLAY": ("Stage 05 cross-sectional factor composite used only as an entry filter (score >= tau). Stage 05 found NO demonstrated predictive skill, so this is a low-prior hypothesis.", "a Stage 05 composite-score entry filter (weights EQ3 / PRIOR5 / VOLONLY)"),
 "REGIME_ACTIVATION": ("Activating the strategy only in BTC regimes where its mechanism is hypothesised to work (Stage 04 tags); Stage 04 thresholds are uncalibrated, so the prior is weak.", "a BTC-regime activation gate (direction / ADX structure / volatility)"),
}
common = dict(schema_version="1.0.0", hypothesis_version=1, family_id="fam-crypto-stage06-v1", status="PROPOSED",
  venue="Binance spot public archive (data profile P1, USDT quote); execution venue UNSPECIFIED", instrument_type="SPOT", expected_direction="LONG",
  baseline="the unmodified Stage 02 rule (rules_version 0.1.0) on identical windows, costs and cohort; paired comparison",
  created_at_utc="2026-11-18T00:00:00Z", created_by="claude-code-stage06",
  source_refs=[{"ref": "docs/strategy-specs/STAGE_06_ANALYSIS_PLAN.md", "kind": "FILE"}, {"ref": "docs/strategy-specs/STAGE_05_HANDOFF.json", "kind": "FILE"}, {"ref": "docs/strategy-specs/STAGE_01_HANDOFF.v2.json", "kind": "FILE"}],
  instrument_id="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,DOGEUSDT,LTCUSDT",
  primary_estimand="pooled walk-forward out-of-sample daily-return Sharpe difference (candidate procedure minus baseline), 5 anchored 6-month folds 2023-05-17..2025-11-17, baseline costs f=0.001 s=0.0005 per side (assumed, not observed)")
names = {V.MOM: ("hyp-cry-mom-101", "4H signals, holds up to 30 days", "persistent directional markets"), V.VEX: ("hyp-cry-vex-103", "1H signals, holds up to 48 hours", "quiet-to-active volatility transition in liquid sessions")}
n_cfg = {}
for (sid, fam) in V.families(): n_cfg[(sid, fam)] = len(V.points(sid, fam)) - 1
for (sid, fam) in V.families():
    base_id, hor, reg = names[sid]; mech, change = RAT[fam]
    hid = f"hyp-{sid.lower()}-s6-{fam.lower().replace('_','-')}"
    rec = dict(common, hypothesis_id=hid, dependencies=[base_id], horizon=hor,
      mechanism=f"{sid}: {mech}", economic_actor="the same flow the baseline targets", market_friction="costs, noise and regime dependence of the baseline rule",
      null_hypothesis=f"The walk-forward-selected change ({change}; {n_cfg[(sid, fam)]} non-baseline configurations) does not improve pooled out-of-sample Sharpe over the unmodified baseline.",
      necessary_regimes=[reg], failure_regimes=["regimes where the baseline already fails", "cohort-specific history"], preregistration_id=f"prereg-{hid[4:]}",
      falsifiers=[dict(question=q, discriminating_test=t, threshold_source="STAGE_06_ANALYSIS_PLAN.md (predeclared, uncalibrated)", outcome="PENDING") for q, t in [
        ("Is pooled OOS dSharpe >= +0.15 with trades >= 0.75x, turnover <= 1.25x, worst-fold maxDD within 1pp (G1-G4)?", "anchored walk-forward, 5 folds"),
        ("Is the selection stable and cost-robust, and are grid neighbours positive (G5-G7)?", "modal selected config; stress A/B; full-dev neighbours"),
        ("Does the Holm-adjusted paired block-bootstrap p stay < 0.05 and the adjacent-asset holdout stay consistent?", "paired circular block bootstrap 14d, 10000 reps, seed 20261118; BNB/DOT/ATOM/BCH holdout")]])
    (out / f"{hid}.json").write_text(json.dumps(rec, indent=1))
print(len(list(out.glob('hyp-*.json'))), "hypothesis files;", sum(n_cfg.values()), "non-baseline configs across families")
