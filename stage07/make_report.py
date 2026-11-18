"""Generate STAGE_07_PORTFOLIO_REPORT.md and STAGE_07_HANDOFF.json from stage07_results.json (every number comes from the executed run)."""
from __future__ import annotations
import json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "docs" / "strategy-specs"; S7 = OUT / "stage07"
R = json.loads((S7 / "stage07_results.json").read_text()); X = json.loads((S7 / "stage07_suspension_overlay.json").read_text())["results"]
M, V = "CRY-MOM-101", "CRY-VEX-103"; SC = ["EW", "IV", "RB", "CONS"]
pc = lambda x, d=1: "n/a" if x is None else f"{100 * x:.{d}f}%"
f2 = lambda x: "n/a" if x is None else f"{x:.2f}"
o = R["oos"]["results"]; ci = R["oos"]["sharpe_ci"]; WD = R["in_sample"]["weights"]; E = R["exposure_and_budget"]; cor = R["asset_correlation"]; sc_ = R["sleeve_correlation"]
L = []; P = L.append
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()

P("# STAGE 07: Research portfolio construction and allocation")
P("")
P("**Determination: NO ALLOCATION.** No capital is allocated: 100 % cash ($10,000 in cash, $0 at risk). The two eligible sleeves fail the predeclared validation gates "
  "(V1-V6, plan section 6). Four allocation schemes were still built and tested so that their consequences are on record; they are **conditional research specifications for paper/forward evaluation only**, not recommendations to trade. "
  "Research only: no orders, credentials or execution. Historical numbers are conditional on assumed costs (15 bp per side) and an unspecified venue; nothing here is a forecast.")
P("")
P("Plan: `STAGE_07_ANALYSIS_PLAN.md` (committed before any run; amendment 1 disclosed below). Code: `stage07/`, tests `tests/stage07`. Results: `stage07/stage07_results.json`. Commit at report time: `" + head[:8] + "`.")
P("")
P("## 0. Evidence base, deviations and what this stage cannot show")
P("* **Eligible sleeves only.** CRY-MOM-101 (Stage 03: eligible, paper-forward only) and CRY-VEX-103 (conditional, shadow/paper only, micro budget). CRY-REV-102 is excluded (Stage 02 REJECT). Frozen Stage 06 specification = unmodified Stage 02 baselines (Stage 06: KEEP BASELINE for both). Nine liquidity-gated cohort assets, spot, long-only, no leverage.")
P(f"* **Aligned history is short.** Both sleeves overlap on {R['counts']['dev_days']:,} days (2021-11-17..2025-11-17); standalone trades in that window: MOM {sc_['trades'][M]}, VEX {sc_['trades'][V]}. "
  f"The walk-forward out-of-sample span is {R['counts']['oos_days']} days (2023-05-17..2025-11-17, 5 anchored 6-month folds), **which excludes the 2022 bear market** (that year appears only in training and in the in-sample/stress tables). "
  "The 2025-11-17..2026-11-17 year is `CONSUMED_LEGACY`: reported descriptively, never a criterion.")
P("* **\"Out-of-sample\" is relative to the weights only.** The whole 2021-2025 history informed Stages 01-06, so the sleeve rules themselves are not out-of-sample; only the weight estimates are.")
P(f"* **Amendment 1 (disclosed).** Run 1 modelled schemes as segregated sub-books (plan section 2). It exposed cross-sleeve limit violations ({R['sleeve_correlation']['same_symbol_overlap_hours']:,} hours of same-symbol overlap between sleeves; single-asset notional up to {pc(R['segregated_exhibit_run1_corrected_normalisation']['EW']['peak_single_asset'],0)} of equity against a 15 % cap; run 1 also showed 7 simultaneous positions, which a later fix of the exposure-timing rule showed to be a one-hour measurement artifact), so run 2 uses one shared book with portfolio admission control "
  "(`stage07/shared.py`, asserted identical to `engine.simulate` under uniform parameters: "
  f"{R['shared_simulator_equivalence']['trades']} trades, max equity difference {R['shared_simulator_equivalence']['max_abs_equity_diff']:.0f}). The amendment was driven by the limit violations, but run-1 performance numbers were visible when it was written. Run 1 is preserved (`stage07_run1_segregated_results.json`). "
  "Later runs only added or corrected reporting (exposure tolerances, a segregated-book comparison, an exposure-timing fix, 2022 invested-time fields); no design parameter, weight formula or gate changed.")
P(f"* **Counts.** 4 schemes (registered `fam-crypto-stage07-v1`), 2 sleeve-only and 3 passive benchmarks, {R['counts']['simulations']} engine simulations, 5 folds, {R['counts']['bootstrap_reps']:,} bootstrap reps (14-day blocks, seed 20261118). "
  "No parameter was searched; weights come from three predeclared formulas. Holm correction over the 4 schemes.")
P("* **Not independent of Stage 06.** Stage 06 found that both baselines lose on adjacent assets (MOM Sharpe -0.20, VEX -1.71); that result is carried into gate V1.")
P("")
P("## Validation gates for any non-zero allocation (predeclared)")
P("| gate | requirement | result |"); P("|---|---|---|")
g = R["validation_gates"]["RB"]
P(f"| V1 | each funded sleeve validated: positive baseline Sharpe on adjacent-asset holdout | **FAIL** (MOM {f2(g['V1_detail'][M])}, VEX {f2(g['V1_detail'][V])}) |")
P("| V2 | >= 6 months and >= 100 forward trades per sleeve | **FAIL** (0 forward trades; forward window starts 2026-11-18) |")
P("| V3 | venue specified, observed fees/spreads/stop fills | **FAIL** (venue UNSPECIFIED; costs assumed) |")
P("| V4 | preregistration frozen after independent review; `adjudicate.py` run | **FAIL** (not frozen, not run) |")
P("| V5 | pooled OOS Sharpe 95 % lower bound > 0 and max DD within 15 % | **FAIL** for all four: Sharpe CI lower bounds " + ", ".join(f"{k} {f2(ci[k]['ci95'][0])}" for k in SC) + "; max DD " + ", ".join(f"{k} {pc(o[k]['max_dd'])}" for k in SC) + " (CONS inside 15 %, but its Sharpe bound is below 0) |")
P("| V6 | Stage 04 gates currently permit entries | **FAIL** (2026-11-18 snapshot: MOM and VEX gates closed, 0 assets passing) |")
P("")
P("## A. Proposed allocation matrix")
P("**A1. Capital to deploy now: 100 % cash, 0 % risk assets.** Reason: V1-V6 not met (above); in addition both sleeves are dormant under the current Stage 04 snapshot.")
P("")
P("**A2. Conditional research specification** (shares of the $10,000 as risk budgets; used only for paper/forward evaluation if the Stage 06/07 open items are resolved). Weights are capital/risk shares; risk per trade = weight x 1 % of equity.")
P("")
P("| scheme | MOM | VEX | cash | risk/trade MOM / VEX | open-risk cap | max positions | single-asset / gross notional cap | weight source |"); P("|---|---|---|---|---|---|---|---|---|")
src = {"EW": "fixed 1/2, 1/2", "IV": "1 / daily vol of each sleeve (train)", "RB": "risk contributions 2/3, 1/3 (train covariance)", "CONS": "Stage 03 budgets, fixed"}
for s in SC:
    w = WD[s]; lim = E[s]["limits"]; rp = lim["risk_per_trade"]
    P(f"| {s} | {pc(w[M],0) if s in ('EW','CONS') else pc(w[M])} | {pc(w[V],0) if s in ('EW','CONS') else pc(w[V])} | {pc(E[s]['cash_weight'],0)} | {pc(rp[M],2)} / {pc(rp[V],2)} | {pc(lim['open_risk'],1)} | {lim['positions']} | {pc(lim['single_asset'],0)} / {pc(lim['gross'],0)} | {src[s]} |")
P("")
P(f"Walk-forward weight ranges (MOM share, 5 folds): IV {pc(R['estimation_sensitivity']['fold_weight_range']['IV'][0])}-{pc(R['estimation_sensitivity']['fold_weight_range']['IV'][1])}, RB {pc(R['estimation_sensitivity']['fold_weight_range']['RB'][0])}-{pc(R['estimation_sensitivity']['fold_weight_range']['RB'][1])}. "
  f"Full-DEV in-sample weights shown above (sigma_MOM {R['in_sample']['sigma'][M]*100:.2f}%/day, sigma_VEX {R['in_sample']['sigma'][V]*100:.2f}%/day, rho {R['in_sample']['rho']:.2f}).")
P("")
P("**A3. Paper-forward specification if forward testing is authorised: CONS.** The choice among schemes is **not evidence-driven**: no scheme differs from MOM alone (Holm-adjusted p = " + ", ".join(f"{k} {R['oos']['vs_mom_only'][k]['holm_p']:.2f}" for k in SC) + "). "
  f"CONS is selected on risk-limit grounds, not return: lowest 99 % ES ({pc(o['CONS']['es99'],2)}), shallowest OOS max drawdown ({pc(o['CONS']['max_dd'])}), explicit Stage 03 caps, 25 % standing cash. Its OOS Sharpe ({f2(ci['CONS']['sharpe'])}) is below MOM alone ({f2(ci['MOM_ONLY']['sharpe'])}). "
  "Whether VEX deserves even a paper budget is open (Stage 06: cost-fragile, loses on all adjacent assets); an MOM-only paper sleeve is an *unregistered* alternative and would need its own registration.")
P("")
P("## B. Position-sizing rules (research specification; shared book)")
P("1. Account: $10,000 USDT-quoted spot; no leverage, no shorts; cash is unallocated capital. Sleeve signals are the frozen Stage 02 baseline rules (rules_version 0.1.0); signals use completed bars only and fill at the next bar's open plus assumed adverse selection.")
P("2. **Per-trade planned risk** = scheme weight x 1 % of frozen equity (EW 0.50 %, IV 0.64 %/0.36 %, RB 0.73 %/0.27 %, CONS 0.50 %/0.25 %; MOM/VEX). Never above 1 %.")
P("3. **Budget** B = min(per-trade risk x E, open-risk cap x E - sum of reserved risk of open positions); skip if B <= 0. Open-risk cap 3 % (EW/IV/RB), 1.5 % (CONS). Reserved risk = quantity x initial stop distance.")
P("4. **Quantity** q = lot-floor of min(B / stop distance, per-position notional cap x E / fill, available cash, 1 % of the asset's median 168-hour quote volume / fill, gross-notional room). Per-position cap 33 % (EW/IV/RB) or 13.3 % MOM / 10 % VEX (CONS); single-asset cap 15 %; gross cap 60 % (EW/IV/RB) or 40 % (CONS). Skip if notional < $10.")
P("5. **Position limits:** one position per symbol across both sleeves; <= 6 positions (<= 3 for CONS); a one-bar re-entry cooldown per sleeve and symbol after any exit (Stage 02 engine rule); no entries in an asset failing the L1-L3 liquidity gates (simulated). The Stage 03 T8 condition (24-hour volume < 50 % of its 90-day median) is a proposed live rule that was **not** simulated.")
P("6. **Gates:** no entries unless the Stage 04 sleeve gate is open; no new entries under any T1-T10 trigger.")
P("7. Scaling to larger accounts changes participation and impact; sizes above the C5 account-size estimate need a new liquidity study.")
P("")
P("## Portfolio results (shared book, baseline costs, walk-forward weights)")
P(f"Pooled OOS, {R['counts']['oos_days']} days, folds chained (each a fresh book). Trades OOS (EW): MOM {R['oos']['per_scheme_oos_trades']['EW'][M]}, VEX {R['oos']['per_scheme_oos_trades']['EW'][V]}.")
P("")
P("| series | total return | ann. vol | Sharpe [95 % block-bootstrap CI] | max DD | ES95 | ES99 [95 % CI] | worst day | dSharpe vs MOM-only (Holm p) |"); P("|---|---|---|---|---|---|---|---|---|")
for k in SC + ["MOM_ONLY", "VEX_ONLY", "EW_BH_9", "BTC_BH"]:
    r = o[k]; cc = ci.get(k); cs = f"{f2(cc['sharpe'])} [{f2(cc['ci95'][0])}, {f2(cc['ci95'][1])}]" if cc else f2(r["sharpe"])
    vm = R["oos"]["vs_mom_only"].get(k); vs = f"{vm['dSharpe']:+.2f} ({vm['holm_p']:.2f})" if vm else "-"
    P(f"| {k.replace('_', '-')} | {pc(r['total_return'])} | {pc(r['ann_vol'])} | {cs} | {pc(r['max_dd'])} | {pc(r['es95'],2)} | {pc(r['es99'],2)} [{pc(r['es99_ci'][0],1)}, {pc(r['es99_ci'][1],1)}] | {pc(r['worst_day'])} | {vs} |")
P("| CASH | 0.0% | 0.0% | - | 0.0% | 0.00% | 0.00% | 0.0% | - |")
P("")
P("EW-BH-9 is a daily-rebalanced equal-weight of the nine assets; BTC-BH is buy-and-hold. They are passive references, not strategies. "
  f"ES99 rests on only {o['EW']['tail_obs99']} tail days per series, so the interval is wide; the Gaussian ES99 ({pc(o['EW']['gauss_es99'],2)} for EW) is close to the historical one here, but tails of the underlying assets are fat (worst cohort day {pc(min(cor['worst_day'].values()))}).")
P("")
P("In-sample (weights estimated on all of DEV, 2021-11-17..2025-11-17, includes the 2022 bear market):")
P("")
P("| scheme | total return | Sharpe | max DD | ES99 | MOM / VEX trades |"); P("|---|---|---|---|---|---|")
for s in SC:
    r = R["in_sample"]["results"][s]; t = R["in_sample"]["trades"][s]; P(f"| {s} | {pc(r['total_return'])} | {f2(r['sharpe'])} | {pc(r['max_dd'])} | {pc(r['es99'],2)} | {t[M]} / {t[V]} |")
for sid in (M, V):
    r = R["in_sample"]["sleeves"][sid]; P(f"| {sid} alone (own 1 % / 3 % book) | {pc(r['total_return'])} | {f2(r['sharpe'])} | {pc(r['max_dd'])} | {pc(r['es99'],2)} | {sc_['trades'][sid]} |")
r = R["in_sample"]["ew_bh_9"]; P(f"| EW-BH-9 (passive) | {pc(r['total_return'])} | {f2(r['sharpe'])} | {pc(r['max_dd'])} | {pc(r['es99'],2)} | - |")
P("")
P("Consumed legacy year 2025-11-17..2026-11-17 (**descriptive only; weights from DEV; not a holdout**): " + "; ".join(f"{s} {pc(R['consumed_descriptive']['results'][s]['total_return'])} (Sharpe {f2(R['consumed_descriptive']['results'][s]['sharpe'])}, max DD {pc(R['consumed_descriptive']['results'][s]['max_dd'])})" for s in SC)
  + f"; MOM alone {pc(R['consumed_descriptive']['sleeves'][M]['total_return'])}, VEX alone {pc(R['consumed_descriptive']['sleeves'][V]['total_return'])}; passive EW-BH-9 {pc(R['consumed_descriptive']['ew_bh_9']['total_return'])}.")
P("")
P("## C. Correlation and concentration analysis")
P("**C1. Cohort assets are one factor, not nine bets.** Daily returns 2021-11-17..2025-11-17:")
P("")
P("| state | days | mean pairwise corr | first principal component share | effective independent bets |"); P("|---|---|---|---|---|")
for lab_, k, n in (("all days", "full9", R["counts"]["dev_days"]), ("calm (excl. BTC worst decile)", "calm", R["counts"]["dev_days"] - cor["n_stress_days"]), ("BTC worst-decile days", "btc_worst_decile", cor["n_stress_days"]), ("BTC > 20 % below its 90-day high", "btc_dd_gt20", cor["n_dd20_days"])):
    c = cor[k]; P(f"| {lab_} | {n} | {c['mean_pairwise']:.2f} | {pc(c['pc1_share'],0)} | {c['eff_bets']:.1f} of {c['n_assets']} |")
P("")
P(f"Adding the four adjacent assets (BNB, DOT, ATOM, BCH) leaves it at {cor['full13']['eff_bets']:.1f} effective bets of 13 (mean pairwise {cor['full13']['mean_pairwise']:.2f}). Rolling 30-day mean pairwise correlation: min {cor['rolling30_mean_pairwise']['min']:.2f}, median {cor['rolling30_mean_pairwise']['median']:.2f}, max {cor['rolling30_mean_pairwise']['max']:.2f}; "
  f"above the Stage 03 T9 threshold of 0.90 in {pc(cor['rolling30_mean_pairwise']['frac_gt_0p9'])} of weekly samples. On BTC's worst 5 % days {pc(cor['share_assets_down_on_btc_worst5'],0)} of asset-days are down. "
  f"Lower-tail co-exceedance (both assets below their own 5th percentile, given one is) averages {cor['tail_coexceed_5pct']:.2f} versus 0.05 under independence. Picking different tokens does **not** diversify: in sustained BTC drawdowns the mean correlation is {cor['btc_dd_gt20']['mean_pairwise']:.2f} and the effective number of bets {cor['btc_dd_gt20']['eff_bets']:.1f}; on single worst days the pairwise correlation is not higher ({cor['btc_worst_decile']['mean_pairwise']:.2f}; conditioning on BTC's own return compresses it) but nearly every asset still falls together.")
P("")
P("**C2. Strategy return correlation.** MOM vs VEX standalone daily returns: "
  f"{sc_['daily']:.2f} (all days), {sc_['weekly']:.2f} (weekly), {sc_['corr_both_active']:.2f} when both are active ({sc_['days_both_active']} days), {sc_['btc_worst_decile_days']:.2f} on BTC worst-decile days. "
  f"Low *daily* correlation is partly an artifact of inactivity: MOM is flat {pc(R['diversification']['frac_days_flat_mom'],0)} of days, VEX {pc(R['diversification']['frac_days_flat_vex'],0)}, both {pc(R['diversification']['frac_days_flat_both_sleeves'],0)}. "
  f"Each sleeve correlates with BTC at {sc_['corr_each_vs_btc']['MOM']:.2f} (MOM) and {sc_['corr_each_vs_btc']['VEX']:.2f} (VEX). The sleeves hold the **same asset at the same time** on {sc_['same_symbol_overlap_days']} days ({sc_['same_symbol_overlap_hours']:,} hours) when run as independent books; the shared book forbids this (one position per symbol), which changes the trade set (see sensitivity).")
P("")
P("**C3. Regime diversification is weak.** Almost all profit of both sleeves comes from one state, BTC above its 200-day mean with low volatility:")
P("")
P("| BTC regime (Stage 02 labels) | days | MOM sum of daily returns | VEX sum | EW scheme sum | BTC buy-hold sum |"); P("|---|---|---|---|---|---|")
for k, v in R["diversification"]["regime_attribution"].items():
    P(f"| {k} | {v['days']} | {pc(v[M]['sum_ret'])} | {pc(v[V]['sum_ret'])} | {pc(v['EW']['sum_ret'])} | {pc(v['btc']['sum_ret'])} |")
P("")
P("Both sleeves are long-only trend/volatility-expansion rules on the same crypto beta; VEX loses in down/high-volatility regimes (the regime that matters for tail risk). Strategy-type diversification is therefore limited to *timing* (MOM 4H holds, VEX 1H holds), not to different return drivers.")
P("")
P("**C4. Tail concentration** (worst 5 % of days, pooled OOS, share of the loss by sleeve; both sleeves negative on the same day in the last column):")
P("")
P("| scheme | MOM share | VEX share | both negative |"); P("|---|---|---|---|")
for s in SC:
    t = R["tail_concentration"]["oos"][s]; P(f"| {s} | {pc(t['sleeve_share'][M],0)} | {pc(t['sleeve_share'][V],0)} | {pc(t['both_negative_share'],0)} |")
P("")
P(f"Equal capital is not equal risk: under EW, VEX supplies {pc(R['diversification']['ratios']['EW']['risk_contrib'][V],0)} of the volatility (in-sample estimate) while having the weakest evidence. Diversification ratio (sum w sigma / sigma_p): " + ", ".join(f"{s} {R['diversification']['ratios'][s]['DR']:.2f}" for s in SC) + " (1.0 = no diversification benefit).")
P("")
P("**C5. Liquidity and costs.** At $10,000 the 1 %-of-median-volume participation cap never binds. Estimated account size at which it would bind for 5 % of trades: " + ", ".join(f"{s} ${R['liquidity_capacity']['schemes'][s]['account_size_p05']:,.0f}" for s in SC) + " (linear scaling; market impact beyond the cap is not modelled; fills not observed).")
P("")
P("| cost level (per side fee + adverse) | " + " | ".join(SC + ["MOM-only", "VEX-only"]) + " |"); P("|---|" + "---|" * 6)
for c, v in R["cost_sensitivity"].items():
    P(f"| {c} ({v['cost'][0]*1e4:.0f}+{v['cost'][1]*1e4:.1f} bp) | " + " | ".join(f2(v[k]["sharpe"]) for k in SC + ["MOM_ONLY", "VEX_ONLY"]) + " |")
P("")
P("(Pooled OOS Sharpe, weights fixed at their base-cost estimates.) At 3x costs: " + ", ".join(f"{k.replace('_','-')} {f2(R['cost_sensitivity']['3x'][k]['sharpe'])}" for k in SC + ["MOM_ONLY", "VEX_ONLY"]) + ". From 2x costs every scheme that holds VEX is below MOM alone, and VEX alone is non-positive. Costs are assumed, not observed.")
P("")
P("## D. Stress scenarios")
P("**Historical (in-sample series; weights from DEV; HISTORICAL, not forecasts).**")
P("")
P("| scheme | worst day | worst 7 days (start) | worst 30 days (start) | LUNA 2022-05-01..06-30 | FTX 2022-11-01..12-15 | calendar 2022 |"); P("|---|---|---|---|---|---|---|")
H = R["stress"]["historical"]
for s in SC:
    h = H[s]; P(f"| {s} | {pc(h['worst_day'])} ({h['worst_day_date']}) | {pc(h['worst_7d'])} ({h['worst_7d_start']}) | {pc(h['worst_30d'])} ({h['worst_30d_start']}) | {pc(h['luna_2022_05_01_to_06_30']['total'])} | {pc(h['ftx_2022_11_01_to_12_15']['total'])} | {pc(h['bear_2022_full']['total'])} (max DD {pc(h['bear_2022_full']['max_dd'])}) |")
P(f"| EW-BH-9 (passive) | - | - | - | {pc(H['EW_BH_9']['luna']['total'])} | {pc(H['EW_BH_9']['ftx']['total'])} | {pc(H['EW_BH_9']['bear_2022']['total'])} |")
P(f"| BTC-BH | - | - | - | {pc(H['BTC_BH']['luna']['total'])} | {pc(H['BTC_BH']['ftx']['total'])} | {pc(H['BTC_BH']['bear_2022']['total'])} |")
P("")
P(f"Calendar 2022 cost the schemes {pc(-H['EW']['bear_2022_full']['total'],0)} (EW), {pc(-H['RB']['bear_2022_full']['total'],0)} (RB) and {pc(-H['CONS']['bear_2022_full']['total'],0)} (CONS) with maximum drawdowns of {pc(-H['CONS']['bear_2022_full']['max_dd'],0)}-{pc(-H['EW']['bear_2022_full']['max_dd'],0)}, against {pc(-H['BTC_BH']['bear_2022']['total'],0)} for BTC and {pc(-H['EW_BH_9']['bear_2022']['total'],0)} for the passive nine-asset basket. "
  f"The sleeves were invested in only {pc(E['EW']['frac_hours_invested_2022'],0)} of 2022 hours (mean gross notional {pc(E['EW']['mean_gross_2022'],0)}), so the smaller loss reflects closed trend gates, not diversification across assets. Losses inside the LUNA and FTX windows were small, but two events cannot separate luck from a systematic gate effect.")
P("")
P("**Hypothetical shocks on the realised exposure timeline (arithmetic, HYPOTHETICAL, not measurements).**")
P("")
P("| scheme | peak planned open risk (all stops hit as planned) | all open stops fill at -1.5R | at -2R | 20 % gap through every open position (peak) | each sleeve at expectancy -0.2R/trade (per year, uncompounded, MOM / VEX) |"); P("|---|---|---|---|---|---|")
fl = R["stress"]["sleeve_expectancy_minus_0p2R_per_year_frac_equity_uncompounded_HYPOTHETICAL"]
for s in SC:
    h = R["hypothetical_shocks"]["results"][s]; P(f"| {s} | {pc(h['all_open_hit_planned_stop'],2)} | {pc(h['stop_fill_minus_1p5R_all_open'],2)} | {pc(h['stop_fill_minus_2R_all_open'],2)} | {pc(h['gap20_all_open_loss_max'],1)} | {pc(fl[s][M],1)} / {pc(fl[s][V],1)} |")
P("")
P(f"Because the cohort is one factor (C1), the correlated-gap case is the relevant one: a 20 % simultaneous gap through all open positions would cost {pc(R['hypothetical_shocks']['results']['EW']['gap20_all_open_loss_max'],1)} (EW) or {pc(R['hypothetical_shocks']['results']['CONS']['gap20_all_open_loss_max'],1)} (CONS), "
  f"about {R['hypothetical_shocks']['results']['EW']['gap20_vs_planned_open_risk_max']:.1f}x the planned open risk. Stage 03 found stop-through behaviour cannot be observed from OHLC bars; it remains unquantified. Stress-cost rows are in section C5.")
P("")
P("**Path dependence (estimation fragility).** The same weights give materially different OOS results depending on whether the sleeves run as independent sub-books or in one shared book: "
  + ", ".join(f"{k} Sharpe {f2(R['oos']['segregated_subbook_approx'][k]['sharpe'])} segregated vs {f2(ci[k]['sharpe'])} shared" for k in SC)
  + ". In the last fold the shared book is negative for every scheme (" + ", ".join(f"{k} {f2(R['folds'][-1]['oos_sharpe'][k])}" for k in SC) + ") while the segregated approximation is positive (" + ", ".join(f"{k} {f2(R['folds'][-1]['segregated_oos_sharpe'][k])}" for k in SC)
  + "), because the shared book's admission order, the one-position-per-symbol rule and the larger combined position allowance change which signals are taken (in that fold MOM took 45 trades in the shared EW book versus 31 standalone, and the extra trades lost). A portfolio Sharpe difference of this size is within the noise of that choice.")
P("")
P("## E. Risk budget utilization (shared book, in-sample timeline, hourly)")
P("")
P("| scheme | open-risk cap | mean open risk (% of cap) | peak open risk | peak positions (limit) | peak single-asset notional (limit) | peak gross (limit) | share of hours invested | hours over limit by >5 % (risk / asset / gross) |"); P("|---|---|---|---|---|---|---|---|---|")
for s in SC:
    e = E[s]; l = e["limits"]
    P(f"| {s} | {pc(l['open_risk'])} | {pc(e['mean_open_risk'],2)} ({pc(e['mean_util'],0)}) | {pc(e['peak_open_risk'],2)} | {e['peak_positions']} ({l['positions']}) | {pc(e['peak_single_asset'])} ({pc(l['single_asset'],0)}) | {pc(e['peak_gross'])} ({pc(l['gross'],0)}) | {pc(e['frac_hours_any_position'],0)} | {e['hours_open_risk_gt_1p05x']} / {e['hours_single_asset_gt_1p05x']} / {e['hours_gross_gt_1p05x']} |")
P("")
P("Limits are enforced **at entry** on frozen equity; afterwards equity moves, so the measured ratios drift (e.g. open risk 3.0-3.1 % against a 3 % cap after a drawdown). " + f"Position counts never exceed the limit (peak {E['EW']['peak_positions']} of {E['EW']['limits']['positions']}; CONS {E['CONS']['peak_positions']} of {E['CONS']['limits']['positions']}). "
  f"Average utilisation of the open-risk budget is low ({pc(E['EW']['mean_util'],0)}-{pc(E['CONS']['mean_util'],0)}), because the sleeves are invested {pc(E['EW']['frac_hours_any_position'],0)} of hours. Maximum planned risk per trade stays <= {pc(max(E[s]['max_trade_risk_frac_reserved'] for s in SC),2)} (limit 1 %). "
  "**Segregated books cannot enforce the cross-sleeve rules** (run-1 design, corrected normalisation): " + "; ".join(f"{s} {R['segregated_exhibit_run1_corrected_normalisation'][s]['hours_same_symbol_overlap']:,} h of same-symbol overlap and peak single-asset notional {pc(R['segregated_exhibit_run1_corrected_normalisation'][s]['peak_single_asset'],0)} (cap 15 %)" for s in SC[:2]) + ".")
P("")
P("## F. Rebalancing and suspension rules (proposed, not validated)")
P("**F1. Rebalancing.** Sleeve weights are inputs to *risk per trade*, not capital transfers between accounts; they are re-estimated at most **every 6 months** (the walk-forward cadence) from an expanding window of standalone sleeve returns. Between re-estimations they are frozen. "
  f"Return-level model of capital rebalancing (in-sample, RB weights): Sharpe {f2(R['turnover_rebalancing']['schemes']['RB']['daily']['sharpe'])} daily, {f2(R['turnover_rebalancing']['schemes']['RB']['monthly30d']['sharpe'])} monthly, {f2(R['turnover_rebalancing']['schemes']['RB']['semiannual182d']['sharpe'])} semi-annual, {f2(R['turnover_rebalancing']['schemes']['RB']['never']['sharpe'])} never; "
  f"capital transferred per year {pc(R['turnover_rebalancing']['schemes']['RB']['daily']['capital_transfer_per_year'],0)} (daily) vs {pc(R['turnover_rebalancing']['schemes']['RB']['semiannual182d']['capital_transfer_per_year'],0)} (semi-annual) of equity. The frequency changes Sharpe by < 0.04, so the low-turnover choice (semi-annual) is used. "
  f"Rebalancing capital moves cash between sleeve budgets and is not market turnover. **Market turnover** is driven by the sleeves: MOM {R['turnover_rebalancing']['sleeves'][M]['trades_per_year']:.0f} trades/yr ({R['turnover_rebalancing']['sleeves'][M]['traded_notional_per_year_over_capital']:.0f}x capital traded per year), VEX {R['turnover_rebalancing']['sleeves'][V]['trades_per_year']:.0f} trades/yr ({R['turnover_rebalancing']['sleeves'][V]['traded_notional_per_year_over_capital']:.0f}x); "
  f"scheme-level traded notional per year: " + ", ".join(f"{s} {R['turnover_rebalancing']['schemes'][s]['market_turnover_per_year_over_equity']:.0f}x" for s in SC) + " of equity.")
P("")
P("**F2. Suspension rules** (Stage 03 T1-T10 inherited unchanged; no new thresholds). Portfolio-level application of the drawdown/loss rules to the pooled OOS series (APPROXIMATE return-level overlay, thresholds not tuned):")
P("")
P("| scheme | T1 >= 8 % DD episodes | T1 >= 12 % | T2 day loss >= 3 % days | T3 7-day loss >= 5 % | Sharpe plain -> overlay | max DD plain -> overlay |"); P("|---|---|---|---|---|---|---|")
for s in SC:
    x = X[s]; e = x["events"]; P(f"| {s} | {e['T1_8pct_dd_episodes']} | {e['T1_12pct_dd_episodes']} | {e['T2_day_loss_3pct_days']} | {e['T3_7d_loss_5pct_episodes']} | {f2(x['plain']['sharpe'])} -> {f2(x['with_overlay']['sharpe'])} | {pc(x['plain']['max_dd'])} -> {pc(x['with_overlay']['max_dd'])} |")
P("")
P("Rules in force for any paper/forward run: (1) **dormant while Stage 04 gates are closed** (V6) - capital stays cash; (2) T1: DD >= 8 % halve risk, >= 12 % no new entries, >= 15 % halt and independent review; (3) T2 day loss >= 3 %: no new entries until next UTC day; (4) T3 7-day loss >= 5 %: half risk until above -2 %; "
  "(5) T5 execution quality: pause if mean realised cost per side > 0.30 % over 20 fills; (6) T9: >= 2 sleeves long the same asset is impossible in the shared book (one position per symbol), and new entries pause while 30-day mean pairwise correlation > 0.90; (7) T10 forward-evidence stop at >= 100 trades per sleeve; "
  "(8) **sleeve suspension**: VEX is suspended if its realised cost per side exceeds 2x assumed or its forward expectancy <= -0.2R after 100 trades (its Sharpe is already <= 0 at 2x costs); MOM likewise at <= -0.2R. (9) Any change to weights outside the 6-month cadence, to caps, or to the sleeve rules requires a new version and registration.")
P("")
P("## Sensitivity to estimation error")
b = R["estimation_sensitivity"]["bootstrap_weights_wMOM"]
P(f"* **Weights.** Block-bootstrap of the DEV window: MOM share under IV {pc(b['IV']['mean'])} (5-95 %: {pc(b['IV']['p05'])}-{pc(b['IV']['p95'])}); under RB {pc(b['RB']['mean'])} ({pc(b['RB']['p05'])}-{pc(b['RB']['p95'])}). Weights are stable to *sampling* error of sigma and rho because both sleeves have long histories of daily returns; "
  "they are not robust to *regime* error: the sleeve volatility ratio is dominated by VEX's down-regime losses.")
gg = [x for x in R["estimation_sensitivity"]["grid"] if x["vex_vol_mult"] in (0.7, 1.3) and x["rho"] in (0.0, 0.9)]
P("* **Assumed correlation and volatility error.** Annualised volatility of the weights if the true sleeve correlation is 0 or 0.9 and VEX volatility is 30 % lower/higher than estimated: EW " + f"{pc(min(x['ann_vol_EW'] for x in gg),0)}-{pc(max(x['ann_vol_EW'] for x in gg),0)}, RB {pc(min(x['ann_vol_RB'] for x in gg),0)}-{pc(max(x['ann_vol_RB'] for x in gg),0)}, CONS {pc(min(x['ann_vol_CONS'] for x in gg),0)}-{pc(max(x['ann_vol_CONS'] for x in gg),0)} (range by assumption). Risk-budgeted and conservative weights are less exposed to correlation error than EW.")
hh = R["estimation_sensitivity"]["sleeve_mean_haircut_oos_sharpe_approx_daily_rebalanced"]
P(f"* **Expected-return error.** Halving each sleeve's mean return halves every Sharpe (RB {f2(hh['0.0']['RB'])} -> {f2(hh['0.5']['RB'])}); with a 100 % haircut the Sharpe is 0 by construction. With Sharpe 95 % intervals of width ~{ci['RB']['ci95'][1]-ci['RB']['ci95'][0]:.1f}, the data cannot distinguish a positive edge from none, and cannot rank the schemes.")
P("* **Multiple testing.** Four schemes against MOM-only: Holm-adjusted p = " + ", ".join(f"{k} {R['oos']['vs_mom_only'][k]['holm_p']:.2f}" for k in SC) + "; paired dSharpe 95 % intervals " + ", ".join(f"{k} [{R['oos']['vs_mom_only'][k]['dSharpe_ci95'][0]:+.1f}, {R['oos']['vs_mom_only'][k]['dSharpe_ci95'][1]:+.1f}]" for k in SC) + ". The best-looking scheme (RB) is also the one most dependent on in-sample weight tilt towards the better-evidenced sleeve.")
P("")
P("## Limitations and unresolved concerns")
for x in ["No untouched temporal holdout exists; the sleeve rules were designed on the same history used here. Stage 06's adjacent-asset holdout found both baselines negative; this stage does not repair that.",
          "The walk-forward span (2023-05..2025-11) is a mostly rising market and excludes 2022; in-sample Sharpe values (0.37-0.58) are far below the OOS ones (0.79-1.11) for that reason, not because of skill.",
          "Costs, spreads, stop fills, lot sizes and venue are assumed; stop-through slippage is not modelled beyond open-gap fills. The 20 % gap and -2R fill results are arithmetic on exposure, not observations.",
          f"Few independent events: {sc_['trades'][M]} MOM and {sc_['trades'][V]} VEX trades in four years; ES99 rests on ~{o['EW']['tail_obs99']} OOS tail days.",
          "Cohort is survivor-selected and nine assets behave as ~2 bets; a survivorship-free data source and exchange-failure scenarios (withdrawal freeze, depeg) are unquantified.",
          "Shared-book vs segregated results differ by more than the differences between schemes: portfolio-level admission order materially changes outcomes.",
          "Gate thresholds (V1-V6) and the weight formulas are judgement-based and uncalibrated; the CONS stop-trading overlay is an approximation of rules that act on intraday exposure.",
          "Preregistration is not frozen and `adjudicate.py` was not run; dispositions here are research assessments, not adjudicated decisions."]: P("* " + x)
P("")
P("## G. Handoff")
P("`STAGE_07_HANDOFF.json` (frozen allocation specification, constraints, evidence index, unresolved items). Figure: `stage07/stage07_portfolio.png`. Evidence: `stage07/stage07_results.json`, `oos_daily_returns.csv`, `stage07_suspension_overlay.json`, `stage07_run1_segregated_results.json`.")
(OUT / "STAGE_07_PORTFOLIO_REPORT.md").write_text("\n".join(L) + "\n")

ho = dict(handoff_type="STAGE_07_HANDOFF", schema_version="1.0.0", status="COMPLETE_NO_ALLOCATION", created="2026-11-18", code_commit=head,
  inputs=["STAGE_01..STAGE_06 handoffs", "STAGE_07_ANALYSIS_PLAN.md"],
  decision=dict(allocation="NO_ALLOCATION", capital_deployed_usd=0.0, cash_usd=10000.0, reason="gates V1-V6 not met (see validation_gates)", research_only=True),
  eligible_sleeves={M: "Stage 03 ELIGIBLE_CONTINUED_RESEARCH_PAPER_FORWARD_ONLY; Stage 06 KEEP BASELINE", V: "Stage 03 CONDITIONAL_SHADOW_PAPER_ONLY; Stage 06 KEEP BASELINE; cost-fragile", "CRY-REV-102": "excluded (REJECT)"},
  constraints=dict(capital_usd=10000, max_risk_per_trade=0.01, max_open_risk=0.03, spot_only=True, leverage=False, shorting=False, cash_allowed=True, assets=["BTC", "ETH", "SOL", "XRP", "ADA", "LINK", "AVAX", "DOGE", "LTC"], orders_or_credentials=False),
  conditional_allocation_spec=dict(status="CONDITIONAL_PAPER_FORWARD_ONLY", recommended_for_paper="CONS", reason_for_choice="risk-limit grounds only; no scheme is distinguishable from MOM alone (Holm p = 1.0)",
      schemes={s: dict(weights=WD[s], cash_weight=E[s]["cash_weight"], limits=E[s]["limits"], weight_rule=src[s]) for s in SC},
      sizing_rules="STAGE_07_PORTFOLIO_REPORT.md section B", rebalancing="re-estimate at most every 6 months; capital transfers are not market trades", suspension="Stage 03 T1-T10 inherited; dormant while Stage 04 gates closed"),
  validation_gates=R["validation_gates"], determination_rule="NO ALLOCATION unless V1-V6 all pass (plan section 6)",
  key_measurements=dict(oos_days=R["counts"]["oos_days"], oos_sharpe={k: ci[k]["sharpe"] for k in SC + ["MOM_ONLY", "VEX_ONLY"]}, oos_sharpe_ci95={k: ci[k]["ci95"] for k in SC + ["MOM_ONLY", "VEX_ONLY"]},
      oos_max_dd={k: o[k]["max_dd"] for k in SC + ["MOM_ONLY", "VEX_ONLY"]}, oos_es99={k: o[k]["es99"] for k in SC + ["MOM_ONLY", "VEX_ONLY"]}, vs_mom_only_holm_p={k: R["oos"]["vs_mom_only"][k]["holm_p"] for k in SC},
      cohort_effective_bets=dict(all=cor["full9"]["eff_bets"], btc_worst_decile=cor["btc_worst_decile"]["eff_bets"], btc_dd_gt20=cor["btc_dd_gt20"]["eff_bets"]), cohort_mean_pairwise=dict(all=cor["full9"]["mean_pairwise"], stress=cor["btc_worst_decile"]["mean_pairwise"]),
      sleeve_corr=dict(daily=sc_["daily"], weekly=sc_["weekly"], both_active=sc_["corr_both_active"]), cost_sharpe_3x={k: R["cost_sensitivity"]["3x"][k]["sharpe"] for k in SC + ["MOM_ONLY", "VEX_ONLY"]}),
  ledger=dict(registered="4 hypotheses hyp-cry-portfolio-s7-{ew,iv,rb,cons} (fam-crypto-stage07-v1, REGISTERED)", preregistration_frozen=False, adjudicate_py_run=False),
  deviations=["Amendment 1: segregated sub-books replaced by a shared book after run 1 (limit violations); run-1 performance was visible", "Run 3 added reporting fields only"],
  unresolved=["forward paper evaluation from 2026-11-18 (>= 6 months, >= 100 trades per sleeve) is the only clean test; it must precede any capital", "whether VEX should have even a paper budget (Stage 06: loses on all adjacent assets; Sharpe <= 0 at 2x costs); an MOM-only paper alternative needs registration",
              "execution venue, observed fees/spreads/depth/stop fills", "survivorship-free second data source; exchange-failure scenarios", "preregistration freeze after independent review, then adjudicate.py",
              "calibration of Stage 04 gates and V1-V6 thresholds", "portfolio admission-order sensitivity: shared-book results differ from segregated results by more than scheme differences", "account-size scaling of liquidity and impact"],
  limitations=["no untouched temporal holdout; walk-forward span excludes 2022", "assumed costs/fills; venue unspecified", "few independent events; wide intervals", "nine assets ~ two bets", "gate and overlay thresholds uncalibrated"],
  evidence_files=["docs/strategy-specs/STAGE_07_PORTFOLIO_REPORT.md", "docs/strategy-specs/STAGE_07_ANALYSIS_PLAN.md", "docs/strategy-specs/stage07/stage07_results.json", "docs/strategy-specs/stage07/stage07_run1_segregated_results.json",
                  "docs/strategy-specs/stage07/oos_daily_returns.csv", "docs/strategy-specs/stage07/stage07_suspension_overlay.json", "docs/strategy-specs/stage07/stage07_portfolio.png"])
(OUT / "STAGE_07_HANDOFF.json").write_text(json.dumps(ho, indent=1)); print("report", len(L), "lines")
