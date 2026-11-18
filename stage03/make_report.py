"""Generate STAGE_03_RISK_REPORT.md and STAGE_03_HANDOFF.json from risk_results.json. Research only; no invented numbers."""
import json, hashlib, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; D = ROOT / "docs/strategy-specs"; OUT = D / "stage03"
r = json.load(open(OUT / "risk_results.json")); S = r["scenarios"]; DB = r["dashboard"]; CO = r["cohort"]; X = r["cross_book"]; EF = r["efficiency"]
aud = json.load(open(ROOT / "stage02/audit.json")); h2 = json.load(open(D / "STAGE_02_HANDOFF.json"))
MOM, REV, VEX, CMB = "CRY-MOM-101", "CRY-REV-102", "CRY-VEX-103", "COMBINED"; B3 = [MOM, REV, VEX]; B4 = B3 + [CMB]; W = ["train", "validation", "final"]
p = lambda x, d=1: "n/a" if x is None else f"{x * 100:.{d}f}%"
u = lambda x: "n/a" if x is None else (f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}")
n2 = lambda x, d=2: "n/a" if x is None else f"{x:.{d}f}"
def tbl(head, rows): return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows])
L = []; A = L.append

commit = r["meta"]["head_commit"]; src_dirty = r["meta"]["stage03_source_dirty"]
A(f"""# STAGE 03 — Quantitative risk assessment of CRY-MOM-101, CRY-REV-102, CRY-VEX-103

Created 2026-11-18 from `STAGE_01_HANDOFF.v2.json` and `STAGE_02_HANDOFF.json` (rules_version 0.1.0-draft, unchanged). Code commit `{commit[:12]}` (stage02/stage03 source dirty at run: {src_dirty}). Research only: no orders, credentials or execution. All numbers come from `docs/strategy-specs/stage03/risk_results.json`, produced by `stage03/run_stage03.py` on the Stage 02 trade engine; the engine trades reconcile exactly to `stage02/trades_baseline.csv` (reconciliation_ok = {r['meta']['reconciliation_ok']}).

**Labels used throughout.** **[H] Historical** = measured in the 2021-11-17..2026-11-17 backtest trades/hourly books (costs ASSUMED, not observed; the final year is `CONSUMED_LEGACY`). **[S] Simulated** = an explicitly stated hypothetical rule applied to historical exposures or an engine re-run; not a forecast. **[U] Unquantified** = cannot be estimated from this data; no probability is given. Assessments are research labels, not `adjudicate.py` dispositions (the ledger is not frozen; see Stage 02).

## Headline

1. **Planned risk and real tail exposure differ by a large factor.** The book is built to risk 1% per trade and 3% open, but CRY-VEX-103 is notional-cap-bound: {p(DB[VEX]['windows']['train']['share_trades_below_budget_pct'],0)} of its train trades risk less than 1% because the 33% position cap binds, so three positions mean ~100% gross exposure (max {p(DB[VEX]['windows']['train']['max_gross_pct_equity'],0)}). A [S] instant −20% gap with stops failing would cost VEX/combined up to **{p(S['S1_sudden_20pct_decline']['hypothetical'][VEX]['gap_-20pct']['max'])} of equity** (MOM {p(S['S1_sudden_20pct_decline']['hypothetical'][MOM]['gap_-20pct']['max'])}, REV {p(S['S1_sudden_20pct_decline']['hypothetical'][REV]['gap_-20pct']['max'])}) against a 3% planned open-risk cap.
2. **VEX has almost no stop-fill slack.** Its pooled net P&L vanishes if stops fill only **{n2(S['S2b_stop_fill_tolerance'][VEX]['pooled_all']['breakeven_extra_bps_per_stop_exit'],0)} bp** worse (mean) than modelled (train: {n2(S['S2b_stop_fill_tolerance'][VEX]['train']['breakeven_extra_bps_per_stop_exit'],1)} bp), while the exit bar's wick below the stop averages ~{n2(S['S2b_stop_fill_tolerance'][VEX]['pooled_all']['mean_wick_bps'],0)} bp. MOM tolerates ~{n2(S['S2b_stop_fill_tolerance'][MOM]['pooled_all']['breakeven_extra_bps_per_stop_exit'],0)} bp; REV has none. Real stop slippage is **[U]**: OHLC bars cannot show it.
3. **Ten consecutive losses is routine, not a tail event, for MOM and VEX.** Loss share is {p(DB[MOM]['loss_streaks']['loss_share'],0)} / {p(DB[VEX]['loss_streaks']['loss_share'],0)}; observed runs of ≥10 losses: MOM {DB[MOM]['loss_streaks']['runs_ge10']}, VEX {DB[VEX]['loss_streaks']['runs_ge10']}; longest runs {DB[MOM]['loss_streaks']['max_run']} and {DB[VEX]['loss_streaks']['max_run']}. Runs cluster more than an independent-trials model predicts, so "10 losses" cannot serve as a halt rule by itself.
4. **Historical max drawdown at baseline sizing:** MOM {p(DB[MOM]['windows']['train']['max_dd_daily'])} (train), VEX {p(DB[VEX]['windows']['train']['max_dd_daily'])}, shared three-strategy book {p(DB[CMB]['windows']['train']['max_dd_daily'])}. These all came with ≤3% planned open risk.
5. **Risk modifications cut drawdown by cutting exposure; none is shown to improve return per unit risk.** Where tested (development windows only) P&L falls roughly in proportion. Efficiency ideas are hypotheses, not findings.
6. **Eligibility:** MOM — continue (reduced budget, paper/forward only); VEX — conditional (shadow/paper until observed fill evidence exists); REV — shadow only, 0% budget. None is cleared for capital.

## Methodology (risk layer)

- **Inputs:** the Stage 02 standalone $10,000 books (one per strategy, train/validation/final) re-run through the unchanged engine, plus the Stage 02 shared three-strategy book (`COMBINED`). Sizing, signals, costs and rules are untouched; every scenario below is a post-processing or a labelled re-run.
- **Risk per trade** = reserved risk q·d (stop distance plus fees/slippage), in $ and % of entry-time equity. **R** = net P&L / reserved risk. **Planned R:R** is defined only where a target exists (REV: SMA20 target, gross (target − O1)/(O1 − S0)); MOM/VEX use trailing exits, so planned R:R is **not defined** — only realised R:R (avg win R / |avg loss R|) is reported.
- **VaR/ES:** historical simulation on daily mark-to-market book returns pooled across the three windows ({DB[MOM]['pooled_days']} days; windows are separate books so returns are %-based). 95% and 99%, 1-day, rf = 0, stated as positive loss fractions. Gaussian VaR/ES shown as a comparator only. 95% CIs by circular block bootstrap (14-day blocks, 2,000 resamples, seed 20261118). 99% has only {DB[MOM]['var_es_pooled']['0.99']['tail_obs']} tail days and is flagged limited; 99.9% is **not** reported. A 7-day overlapping-window 95% figure is given with its dependence caveat. A second version conditional on days with an open position is given because 44–95% of days are flat.
- **Extreme-condition exposure:** conditions from the cohort (equal-weight of the nine assets): worst 5% of days ({CO['n_stress_days']} days, daily return ≤ {p(CO['ew_daily_ret_p5'])}) and BTC high-volatility regime days (30-day annualised vol > 60%).
- **Gap shock [S]:** at the close of every historical hour with an open position, mark every position down by x%, fill at the gapped price × (1 − slippage) less fee; report loss as % of that hour's equity. This is exposure arithmetic: it ignores stop levels because the premise is that stops fail.
- **Stop-fill bound [S on H bars]:** for each stop exit, the loss if the stop fills at a fraction α of the way from the modelled fill to the exit bar's low (α = 0.5, 1.0; excursion ×2 for the volatility-doubles case). α = 1 is a worst-case bound, not an expectation.
- **Venue-unavailable freeze [S]:** positions cannot be exited for T hours (24/72/168); loss = worst adverse excursion (exit at the trough of the next T hours, less fee/slippage) versus the mark.
- **Engine re-runs [S]:** volatility ×2 (every bar's log-return deviation from its linear trend doubled, intrabar ranges doubled; quote volume unchanged), costs ×3, volume ×0.1 (alone, and with 4× slippage). Whole-book re-runs, including the cost gate and liquidity gates.
- **Variants M1–M3 and policy replay are exploratory sensitivities on the development/evaluation/consumed windows with one pre-declared configuration each (not selected on performance, not registered as new hypotheses, not preregistered). They cannot support a performance claim.** The throttle (M3) is a linear-scaling replay of closed-trade equity, not a re-simulation.
- **Adequacy rules applied:** no tail probability is inferred from the trade samples (MOM n = {DB[MOM]['loss_streaks']['n_trades']}, REV n = {DB[REV]['loss_streaks']['n_trades']}, VEX n = {DB[VEX]['loss_streaks']['n_trades']}); independent-trials expectations for loss runs are printed as ILLUSTRATIVE only.

## A. Risk dashboard
""")
# A1
for b in B4:
    A(f"### {b}" + (" (shared book: all three rule sets, shared slots/risk)" if b == CMB else ""))
    rows = []
    for w in W:
        x = DB[b]["windows"][w]
        rr = x.get("risk_usd"); prr = x.get("planned_rr_REV_gross")
        rows.append([w, x["n"], f"${rr['median']:.0f} / {p(x['risk_pct_equity']['median'],2)} (max {p(x['risk_pct_equity']['max'],2)})", f"{p(x['notional_pct_equity']['median'],0)} / {p(x['notional_pct_equity']['max'],0)}",
                     p(x["stop_distance_pct"]["median"]), (f"{n2(prr['median'])} (n={prr['n']})" if prr else "undefined (trailing exit)" if b in (MOM, VEX) else "mixed"), n2(x["realized_rr"]),
                     f"{u(x['avg_win_usd'])} / {u(x['avg_loss_usd'])}", f"{u(x['expectancy_usd'])} ({n2(x['expectancy_R'],3)}R)", p(x["win_rate"], 0)])
    A(tbl(["window", "trades", "risk/trade median $ / %E (max %E)", "notional %E median / max", "stop distance median", "planned R:R", "realised R:R", "avg win / avg loss", "expectancy $ (R)", "win rate"], rows))
    rows = []
    for w in W:
        x = DB[b]["windows"][w]
        rows.append([w, p(x["max_dd_daily"]), p(x["max_dd_hourly"]), ("yes, " + str(x["mdd_peak_to_recovery_days"]) + "d peak→recovery") if x["mdd_recovered"] else "not within window", f"{x['longest_underwater_days']}d",
                     f"{p(x['exposure_time'],0)} / {p(x['avg_invested_pct'],1)}", f"{p(x['max_gross_pct_equity'],0)} / {p(x['p99_gross_pct_equity'],0)}", f"{p(x['max_open_risk_pct'],1)}", x["max_open"]])
    A("\n" + tbl(["window", "MaxDD daily MTM", "MaxDD hourly", "recovered", "longest underwater", "time in market / avg invested", "gross exposure max / p99 (% equity)", "max open reserved risk", "max open positions"], rows) + "\n")
A("**Reading:** risk per trade is at the 1% budget except where the 33% notional cap binds (VEX, REV in tight-stop regimes); reserved open risk never exceeded 3.1% of hourly equity (3% of entry equity). Gross exposure is the quantity that carries gap risk, and for VEX/combined it reaches ~100% of equity.\n")
# A2 VaR/ES
rows = []
for b in B4:
    v = DB[b]["var_es_pooled"]; c = DB[b].get("var_es_95_conditional_on_invested_days"); s7 = DB[b]["var_es_7d_95_overlapping"]
    rows.append([b, f"{p(v['0.95']['hist_var'],2)} / {p(v['0.95']['hist_es'],2)}", f"[{p(v['0.95']['var_ci95'][0],2)}, {p(v['0.95']['var_ci95'][1],2)}] / [{p(v['0.95']['es_ci95'][0],2)}, {p(v['0.95']['es_ci95'][1],2)}]",
                 f"{p(v['0.99']['hist_var'],2)} / {p(v['0.99']['hist_es'],2)}", f"{p(v['0.95']['gauss_var'],2)} / {p(v['0.95']['gauss_es'],2)}", (f"{p(c['var'],2)} / {p(c['es'],2)} (n={c['n_days']}d)" if c else "n/a"),
                 f"{p(s7['var'],1)} / {p(s7['es'],1)}", f"{p(DB[b]['worst_1d_return'],1)} / {p(DB[b]['worst_7d_return'],1)}", p(DB[b]["share_zero_return_days"], 0)])
A("**Table A2 — 1-day VaR/ES (positive = loss), pooled three windows, historical simulation [H]**\n")
A(tbl(["book", "95% VaR / ES", "95% bootstrap CI (VaR / ES)", "99% VaR / ES (limited: 19 tail days)", "Gaussian 95% VaR / ES (comparator)", "95% VaR / ES on invested days only", "7-day 95% VaR / ES (overlapping)", "worst 1d / 7d", "flat days"], rows))
A("\nREV's unconditional 95% VaR is 0 because it is flat on ~95% of days; use the invested-day column. The Gaussian comparator understates the 99% historical tail for MOM and REV (fat tails). VaR/ES on daily returns do not capture gap, stop-failure or venue risk — see section B.\n")
# A3 loss runs
rows = []
for b in B4:
    ls = DB[b]["loss_streaks"]
    rows.append([b, ls["n_trades"], p(ls["loss_share"], 0), ls["runs"], ls["max_run"], f"{ls['runs_ge5']} / {ls['runs_ge8']} / {ls['runs_ge10']}", n2(ls["iid_expected_runs_ge10_ILLUSTRATIVE"], 1), f"{n2(ls['worst_run_R'],1)}R / {u(ls['worst_run_pnl_usd'])}",
                 ", ".join(f"{k}:{v}" for k, v in ls["histogram"].items())])
A("**Table A3 — consecutive-loss distribution [H]** (loss = net P&L ≤ 0, trades ordered by exit; each window is its own sequence, pooled)\n")
A(tbl(["book", "trades", "loss share", "loss runs", "longest", "runs ≥5 / ≥8 / ≥10", "independent-trials expectation of ≥10 runs (ILLUSTRATIVE only)", "costliest run", "histogram length:count"], rows))
A("\nObserved ≥10-loss runs exceed the independent-trials expectation for both MOM and VEX (losses cluster in downtrends and chop). With 18–23 loss runs in a five-year sample, the sample is too small to estimate the probability of a longer run.\n")
# A4 gap/slip/liq
mx1h = max(a["max_abs_1h_logret"] for a in aud)
rows = []
for b in B4:
    g = DB[b]["gap_trade_level"]; lq = DB[b]["liquidity_trade_level"]; ov = S["S2b_stops_fail_inside_bar"][b]
    rows.append([b, g["n_stop_exits"], n2(g["worst_R"], 3) + "R", f"{p(ov['stop_fills_at_50pct_of_wick_below_modelled_fill']['wick_pct_p50'],2)} / {p(ov['stop_fills_at_50pct_of_wick_below_modelled_fill']['wick_pct_p95'],1)} / {p(ov['stop_fills_at_50pct_of_wick_below_modelled_fill']['wick_pct_max'],1)}",
                 f"{p(ov['stop_fills_at_exit_bar_low']['share_R_adjusted_below_minus1_5'],0)} / {p(ov['stop_fills_at_exit_bar_low']['share_R_adjusted_below_minus2'],0)}", n2(ov["stop_fills_at_exit_bar_low"]["worst_R_adjusted"], 1) + "R",
                 f"{p(lq['entry_notional_over_entry_bar_quote_volume']['p99'],2)} / {p(lq['entry_notional_over_entry_bar_quote_volume']['max'],2)}", f"{p(lq['exit_notional_over_exit_bar_quote_volume']['p99'],2)} / {p(lq['exit_notional_over_exit_bar_quote_volume']['max'],2)}", p(lq["entry_notional_over_median168_hourly_volume"]["max"], 2)])
A("**Table A4 — gap, slippage and liquidity [H measured; wick columns are bounds [S]]**\n")
A(tbl(["book", "stop exits", "worst modelled trade", "wick below stop fill, exit bar: median / p95 / max (% of price)", "stop-at-bar-low: share worse than −1.5R / −2R", "worst R at bar-low fill", "entry notional ÷ entry-bar volume p99 / max", "exit notional ÷ exit-bar volume p99 / max", "max entry notional ÷ 168h median hourly volume (cap 1%)"], rows))
A(f"""
- **No material gap-through in the model.** Every modelled trade lost ≤1.000R (float noise only) because the largest 1H log move in the data is {p(mx1h,1)} (all assets) and stops fill at min(stop, open)·(1−s): spot crypto trades continuously, so "gaps" appear as in-bar wicks, which the model fills at the stop plus a fixed 5 bp. That is an assumption, not an observation.
- **Wick evidence (bounds, not expectations):** exit bars wick a median {p(S['S2b_stops_fail_inside_bar'][VEX]['stop_fills_at_exit_bar_low']['wick_pct_p50'],2)} (VEX) – {p(S['S2b_stops_fail_inside_bar'][MOM]['stop_fills_at_exit_bar_low']['wick_pct_p50'],2)} (MOM) of price below the modelled stop fill and up to {p(S['S2b_stops_fail_inside_bar'][CMB]['stop_fills_at_exit_bar_low']['wick_pct_max'],0)}; VEX's median stop distance is only {p(DB[VEX]['windows']['validation']['stop_distance_pct']['median'],1)}.
- **Liquidity (measured against the assumed 1%-of-median-volume cap):** the cap bound on 0% of trades; the largest position was {p(max(DB[b]['liquidity_trade_level']['entry_notional_over_entry_bar_quote_volume']['max'] for b in B4),2)} of its entry bar's quote volume. At $10,000 these sizes are small; they do not describe a larger account, a thin hour, or a stress when volume collapses (scenario S4).
""")
# A5 concentration
A("**Table A5 — correlated-signal concentration and extreme-condition exposure [H]**\n")
rows = []
for b in B4:
    c = DB[b]["concentration"]; e = DB[b]["extreme_condition_exposure"]
    rows.append([b, p(c["share_trades_entered_same_hour_as_another"], 0), p(c["candidate_share_with_simultaneous_candidate"], 0), ", ".join(f"{k}:{v}" for k, v in c["skips_total"].items()), f"{c['max_losing_exits_within_24h']} / {u(c['worst_realised_24h_exit_cluster_usd'])}",
                 f"{p(e['worst5pct_cohort_days']['mean_gross_exposure'],0)} (max day {p(e['worst5pct_cohort_days']['max_day_gross_exposure'],0)})", f"{p(e['high_vol_regime_days']['mean_gross_exposure'],0)} (max {p(e['high_vol_regime_days']['max_day_gross_exposure'],0)})", f"{p(e['normal_days']['mean_gross_exposure'],0)}", p(e["worst5pct_cohort_days"]["worst_daily_return"], 1)])
A(tbl(["book", "trades entered the same hour as another", "candidates with a simultaneous candidate", "entries blocked (symbol occupied / slots / cooldown)", "max losing exits in 24h / worst 24h exit cluster", "mean gross exposure on worst-5% cohort days", "on high-vol days", "on other days", "worst day return on worst-5% cohort days"], rows))
rc = CO["rolling30d_mean_pairwise_corr"]
A(f"""
- **Cohort correlation:** mean pairwise daily-return correlation of the nine assets {n2(CO['mean_pairwise_corr_all'])} over the full window (rolling 30-day: median {n2(rc['p50'])}, 95th pct {n2(rc['p95'])}, max {n2(rc['max'])}); first principal component {p(CO['pc1_share_all'],0)} of variance. Restricted to the worst-5% cohort days the average is {n2(CO['mean_pairwise_corr_worst5pct_days'])}; conditioning on extreme days restricts the range and biases correlation estimates, so this is not evidence that correlations do not rise in a crash.
- **Effective diversification is low:** up to three positions in nine highly co-moving assets, one position per symbol. {X['share_days_ge2_books_invested']*100:.0f}% of days have ≥2 of the three strategies invested; standalone-book daily-return correlations: MOM~VEX {n2(X['daily_return_corr']['CRY-MOM-101~CRY-VEX-103'])}, MOM~REV {n2(X['daily_return_corr']['CRY-MOM-101~CRY-REV-102'])}, REV~VEX {n2(X['daily_return_corr']['CRY-REV-102~CRY-VEX-103'])}; MOM and VEX held the same symbol at overlapping times in {X['same_symbol_overlapping_position_pairs_standalone_books']['CRY-MOM-101~CRY-VEX-103']} trade pairs.
- **Trend strategies sat out the worst days:** on the worst-5% cohort days mean gross exposure is {p(DB[MOM]['extreme_condition_exposure']['worst5pct_cohort_days']['mean_gross_exposure'],0)} (MOM) / {p(DB[VEX]['extreme_condition_exposure']['worst5pct_cohort_days']['mean_gross_exposure'],0)} (VEX) versus {p(DB[MOM]['extreme_condition_exposure']['normal_days']['mean_gross_exposure'],0)} / {p(DB[VEX]['extreme_condition_exposure']['normal_days']['mean_gross_exposure'],0)} on other days. That is flat-market luck as much as design: the worst single-day exposure on such a day was still {p(DB[VEX]['extreme_condition_exposure']['worst5pct_cohort_days']['max_day_gross_exposure'],0)}.
- **Skipped entries:** because only one position per symbol and three slots are allowed, most simultaneous signals are discarded (MOM: {DB[MOM]['concentration']['skips_total'].get('symbol_occupied',0)} symbol-occupied and {DB[MOM]['concentration']['skips_total'].get('max_positions',0)} slot-blocked entries), so realised concentration understates signal concentration.

![Drawdown and gap-shock exposure](stage03/risk_drawdown_shock.png)
""")

# ------------------------------------------------------------------ B
H1 = S["S1_sudden_20pct_decline"]["historical"]["books"]; H1x = S["S1_sudden_20pct_decline"]["hypothetical"]
A("## B. Scenario stress-test matrix\n")
A("Type: **[H]** historical replay, **[S]** simulated/hypothetical, **[U]** unquantified. 'Pooled' = train+validation+final (final is consumed; descriptive). Baseline pooled results for reference are in the first row.\n")
bs = S["baseline"]
def cell_runs(k, b):
    x = S[k][b]; return f"{u(x['net_pnl_usd_3books_windows'])}; ratio {n2(x['ratio'],3)}; worst-window MaxDD {p(x['max_dd_daily_worst_window'])}; n={x['n_trades']}"
rows = [["Baseline (assumed costs) [H]"] + [cell_runs("baseline", b) for b in B4]]
rows.append(["S1a Worst cohort day 2022-11-09 (cohort −19.2%) [H]"] + [("flat (no position)" if H1[b]["worst_1d_cohort_day"]["in_warmup_or_flat"] else f"{p(H1[b]['worst_1d_cohort_day']['book_return'],1)}; gross {p(H1[b]['worst_1d_cohort_day']['max_gross_exposure'],0)}") for b in B4])
rows.append(["S1b Worst cohort 7 days 2022-05-05..11 (cohort −39.1%) [H]"] + [("flat (no position)" if H1[b]["worst_7d_cohort_window"]["in_warmup_or_flat"] else f"{p(H1[b]['worst_7d_cohort_window']['book_return'],1)}; max gross {p(H1[b]['worst_7d_cohort_window']['max_gross_exposure'],0)}") for b in B4])
rows.append(["S1c Instant −20% gap, stops fail: loss % equity, in-position hours max / p99 [S]"] + [f"{p(H1x[b]['gap_-20pct']['max'])} / {p(H1x[b]['gap_-20pct']['p99'])}; >3% in {p(H1x[b]['gap_-20pct']['share_exposed_hours_loss_gt_3pct'],0)} of hours" for b in B4])
rows.append(["S1d same, plus 2% extra exit slippage [S]"] + [f"{p(H1x[b]['gap_-20pct_plus_2pct_illiquid_exit']['max'])} / {p(H1x[b]['gap_-20pct_plus_2pct_illiquid_exit']['p99'])}" for b in B4])
k = "S2_volatility_x2_HYPOTHETICAL"; rows.append(["S2a Volatility ×2, whole-book re-run (sizing adapts) [S]; return not interpretable"] + [cell_runs(k, b) for b in B4])
ov = S["S2b_stops_fail_inside_bar"]
rows.append(["S2b Stops fill at 50% of in-bar wick [S on H bars]: pooled net P&L; share of stops worse than −1.5R"] + [f"{u(sum(w['net_pnl_adjusted'] for w in ov[b]['stop_fills_at_50pct_of_wick_below_modelled_fill']['by_window'].values()))}; {p(ov[b]['stop_fills_at_50pct_of_wick_below_modelled_fill']['share_R_adjusted_below_minus1_5'],1)}" for b in B4])
rows.append(["S2c Stops fill at exit-bar low (worst-case bound) [S]"] + [f"{u(sum(w['net_pnl_adjusted'] for w in ov[b]['stop_fills_at_exit_bar_low']['by_window'].values()))}; {p(ov[b]['stop_fills_at_exit_bar_low']['share_R_adjusted_below_minus1_5'],0)}; worst {n2(ov[b]['stop_fills_at_exit_bar_low']['worst_R_adjusted'],1)}R" for b in B4])
rows.append(["S2d Wick depth ×2 and fill at bar low (post-entry vol shock, stops sized before) [S]"] + [f"{u(sum(w['net_pnl_adjusted'] for w in ov[b]['wick_depth_x2_vol_doubles_fill_at_exit_bar_low']['by_window'].values()))}; worst {n2(ov[b]['wick_depth_x2_vol_doubles_fill_at_exit_bar_low']['worst_R_adjusted'],1)}R" for b in B4])
rows.append(["S3 Execution costs ×3 (fee 0.30%, slippage 0.15% per side) [S]"] + [cell_runs("S3_costs_x3_HYPOTHETICAL", b) for b in B4])
rows.append(["S4a Quote volume ×0.1 (liquidity gates + 1% participation cap) [S]"] + [cell_runs("S4a_volume_x0.1_HYPOTHETICAL", b) for b in B4])
rows.append(["S4b Volume ×0.1 and slippage ×4 [S]"] + [cell_runs("S4b_volume_x0.1_and_slippage_x4_HYPOTHETICAL", b) for b in B4])
S5 = S["S5_ten_consecutive_losses"]
rows.append(["S5a Ten losses in a row at −1R each, compounding [S]"] + [f"−{p(S5[b]['cases']['planned_-1R']['equity_loss_pct_10_in_row'])} equity" for b in B4])
rows.append(["S5b Ten losses at the mean stop-loss size if stops fill at bar low [S]"] + [f"−{p(S5[b]['cases']['mean_loss_R_if_stops_fill_at_exit_bar_low_HYPOTHETICAL']['equity_loss_pct_10_in_row'])} ({n2(S5[b]['cases']['mean_loss_R_if_stops_fill_at_exit_bar_low_HYPOTHETICAL']['R_per_loss'],2)}R each)" for b in B4])
rows.append(["S5c Observed: longest losing run, its cost, runs ≥10 [H]"] + [f"{DB[b]['loss_streaks']['max_run']} losses; {n2(DB[b]['loss_streaks']['worst_run_R'],1)}R / {u(DB[b]['loss_streaks']['worst_run_pnl_usd'])}; {DB[b]['loss_streaks']['runs_ge10']} runs ≥10" for b in B4])
F = S["S6_venue_unavailable"]["hypothetical_freeze"]
for T in ("24", "72", "168"):
    rows.append([f"S6 Venue unreachable {T}h, no exits possible: worst loss % equity max / p99 [S]"] + [f"{p(F[T][b]['max'])} / {p(F[T][b]['p99'])}" for b in B4])
rows.append(["S6x Exchange insolvency, withdrawal freeze, delisting, USDT depeg [U]"] + ["exposure up to the venue balance; no probability estimable"] * 4)
A(tbl(["scenario", "CRY-MOM-101", "CRY-REV-102", "CRY-VEX-103", "COMBINED"], rows))
tol = S["S2b_stop_fill_tolerance"]
A(f"""
**Notes on the matrix**

- **S1 (−20% decline).** No day in the sample reached −20% for the equal-weight cohort (worst −19.2% on 2022-11-09; {CO['days_le_minus10pct']} days ≤ −10%, {CO['days_le_minus15pct']} ≤ −15%); the worst 7-day cohort decline was −39.1% and the worst 14-day −42.4%. In both replays MOM and REV were flat; VEX/combined were flat on 2022-11-09 and lost 2.1% over the 7-day window (a historical outcome, not a guarantee). The hypothetical instant gap is the informative row: planned open risk is ≤3%, but loss under a gap scales with **gross exposure**, so VEX/combined can lose ~20% and MOM up to ~{p(H1x[MOM]['gap_-20pct']['max'],0)}. With continuously working stops the loss would be near the planned risk; the gap is the stop-failure case.
- **S2 (volatility doubles).** The transformation doubles every deviation from trend, which also amplifies multi-week trends (BTC min/max price ratio {n2(S['S2_volatility_x2_HYPOTHETICAL']['_check']['btc_min_max_price_ratio_before'],1)}→{n2(S['S2_volatility_x2_HYPOTHETICAL']['_check']['btc_min_max_price_ratio_after'],0)}), so the large P&L increases for trend rules are an artefact and must not be read as "volatility helps". What is informative: ATR sizing halves position size, so MOM's MaxDD *fell* ({p(S['S2_volatility_x2_HYPOTHETICAL'][MOM]['max_dd_daily_worst_window'])} vs {p(bs[MOM]['max_dd_daily_worst_window'])}) while VEX stayed capped by notional ({p(S['S2_volatility_x2_HYPOTHETICAL'][VEX]['max_dd_daily_worst_window'])}). The unanticipated-shock version (S2b–S2d), where stops are sized before the volatility rises, is the harsher and more relevant test.
- **S2b–S2d (stops failing inside bars).** If stops filled at the exit-bar low the pooled net P&L would be {u(sum(w['net_pnl_adjusted'] for w in ov[VEX]['stop_fills_at_exit_bar_low']['by_window'].values()))} (VEX) and {u(sum(w['net_pnl_adjusted'] for w in ov[MOM]['stop_fills_at_exit_bar_low']['by_window'].values()))} (MOM); the bar-low case is a bound. The **fill tolerance** is the useful number: net P&L reaches zero when stops fill an average of {n2(tol[MOM]['pooled_all']['breakeven_extra_bps_per_stop_exit'],0)} bp (MOM; validation {n2(tol[MOM]['validation']['breakeven_extra_bps_per_stop_exit'],0)}), {n2(tol[VEX]['pooled_all']['breakeven_extra_bps_per_stop_exit'],0)} bp (VEX; validation {n2(tol[VEX]['validation']['breakeven_extra_bps_per_stop_exit'],0)}, train {n2(tol[VEX]['train']['breakeven_extra_bps_per_stop_exit'],1)}) worse than modelled; REV is already negative pooled, and the combined book has ≈{n2(tol[CMB]['pooled_all']['breakeven_extra_bps_per_stop_exit'],0)} bp pooled and none in train. Drawdowns under S2c exceed −100% of the additive $10,000 base for VEX/combined ("wipe-out" in the bound).
- **S3 (costs ×3).** The VEX cost gate removes {bs[VEX]['n_trades'] - S['S3_costs_x3_HYPOTHETICAL'][VEX]['n_trades']} of {bs[VEX]['n_trades']:,} trades, yet net P&L is {u(S['S3_costs_x3_HYPOTHETICAL'][VEX]['net_pnl_usd_3books_windows'])} and train MaxDD {p(S['S3_costs_x3_HYPOTHETICAL'][VEX]['max_dd_by_window']['train'])}. VEX cost is {p(EF['cost_share_of_gross_all_books'][VEX]['train']['cost_over_abs_gross'],0)} / {p(EF['cost_share_of_gross_all_books'][VEX]['validation']['cost_over_abs_gross'],0)} / {p(EF['cost_share_of_gross_all_books'][VEX]['final']['cost_over_abs_gross'],0)} of gross P&L in train / validation / final even at baseline costs. MOM is the least cost-sensitive (ratio {n2(S['S3_costs_x3_HYPOTHETICAL'][MOM]['ratio'],3)} at ×3).
- **S4 (liquidity).** Scaling volume to 10% removes {S['S4a_volume_x0.1_HYPOTHETICAL']['_candidates_vs_baseline'][MOM][1] - S['S4a_volume_x0.1_HYPOTHETICAL']['_candidates_vs_baseline'][MOM][0]} MOM and {S['S4a_volume_x0.1_HYPOTHETICAL']['_candidates_vs_baseline'][VEX][1] - S['S4a_volume_x0.1_HYPOTHETICAL']['_candidates_vs_baseline'][VEX][0]} VEX candidates through the liquidity gates; trades survive in the most liquid assets, so MaxDD can fall simply because there is less trading. Adding 4× slippage drives VEX to ratio {n2(S['S4b_volume_x0.1_and_slippage_x4_HYPOTHETICAL'][VEX]['ratio'],3)} and train MaxDD {p(S['S4b_volume_x0.1_and_slippage_x4_HYPOTHETICAL'][VEX]['max_dd_by_window']['train'])}. The engine has no market-impact function; impact on exit under a real liquidity shock is [U].
- **S5 (ten losses).** Ten −1R losses cost ≈ 7–10% of equity at baseline sizing, but this is not a tail case: MOM lost {DB[MOM]['loss_streaks']['max_run']} in a row ({n2(DB[MOM]['loss_streaks']['worst_run_R'],1)}R, {u(DB[MOM]['loss_streaks']['worst_run_pnl_usd'])}) and VEX {DB[VEX]['loss_streaks']['max_run']} in a row. The 3% open-risk cap bounds *simultaneous* losses, not sequential ones.
- **S6 (venue unavailable).** The three gaps in the data (2021-08-13 02:00–05:00, 2021-09-29 07:00–08:00, 2023-03-24 13:00 UTC; same hours missing for all nine assets) moved the cohort at most {p(max(g['max_abs_logmove_across_gap'] for g in S['S6_venue_unavailable']['historical_data_gaps']),1)} across the gap and cannot be attributed to a venue outage; they are uninformative about severe outages. The freeze simulation is exposure-weighted: for VEX the worst 24h adverse excursion on a held position set was {p(F['24'][VEX]['max'])} (2025-10-10) and the worst 168h {p(F['168'][VEX]['max'])}. Windows overlap, so these are a handful of episodes, not a distribution.
""")

# ------------------------------------------------------------------ C
A("## C. Identified vulnerabilities (ranked)\n")
V = [
 ("V1", "Gross exposure far exceeds planned risk (VEX, combined)", f"VEX is notional-cap-bound: the 33% cap binds on {p(DB[VEX]['windows']['train']['share_trades_below_budget_pct'],0)} of train trades, three positions ≈ 100% gross. Any non-stop-protected move scales with gross: −20% gap → ≈ −{p(H1x[VEX]['gap_-20pct']['max'],0)}; 72h freeze max {p(F['72'][CMB]['max'],0)}, 168h {p(F['168'][CMB]['max'],0)}.", "[S] on [H] exposure"),
 ("V2", "Thin stop-fill slack in VEX; none in REV", f"Edge margin ≈ {n2(tol[VEX]['pooled_all']['breakeven_extra_bps_per_stop_exit'],0)} bp per stop exit (train {n2(tol[VEX]['train']['breakeven_extra_bps_per_stop_exit'],1)}); stops 1–4% from price while exit bars wick ~{n2(tol[VEX]['pooled_all']['mean_wick_bps'],0)} bp below the stop fill. Slippage and spreads are assumed (5 bp) and unobservable here.", "[S] bound; real slippage [U]"),
 ("V3", "Failure of stops in a fast move", "Stops are modelled as always executable at min(stop, open). In a venue disruption, a sharp single-day drop (e.g. 2025-10-10 in the replay) or a stop-limit that does not fill, losses exceed 1R with no cap; worst bound R at bar-low fill: " + f"{n2(ov[CMB]['stop_fills_at_exit_bar_low']['worst_R_adjusted'],1)}R (combined).", "[S] bound; [U] probability"),
 ("V4", "Long loss clusters / drawdowns are normal for these rules", f"Loss share {p(DB[MOM]['loss_streaks']['loss_share'],0)} (MOM) / {p(DB[VEX]['loss_streaks']['loss_share'],0)} (VEX); 18- and 22-loss runs; MaxDD {p(DB[MOM]['windows']['train']['max_dd_daily'],0)} / {p(DB[VEX]['windows']['train']['max_dd_daily'],0)} / {p(DB[CMB]['windows']['train']['max_dd_daily'],0)} (MOM/VEX/combined, train) at only ≤3% planned open risk; drawdown lasted {DB[VEX]['windows']['train']['longest_underwater_days']} days (VEX train).", "[H]"),
 ("V5", "Single-factor concentration", f"Mean pairwise correlation {n2(CO['mean_pairwise_corr_all'])}, rolling-30d 95th pct {n2(rc['p95'])}; one factor explains {p(CO['pc1_share_all'],0)} of cohort variance. Nine nominal assets, one effective bet. {DB[CMB]['concentration']['max_losing_exits_within_24h']} losing exits inside 24h occurred.", "[H]"),
 ("V6", "Cost sensitivity", f"Costs consume {p(EF['cost_share_of_gross_all_books'][VEX]['train']['cost_over_abs_gross'],0)} (train) of VEX gross P&L at baseline; ×3 costs → VEX ratio {n2(S['S3_costs_x3_HYPOTHETICAL'][VEX]['ratio'],3)}, REV {n2(S['S3_costs_x3_HYPOTHETICAL'][REV]['ratio'],3)}. Fee tier and spread were never observed.", "[S]; costs [U]"),
 ("V7", "Liquidity deterioration", "Sizes are small at $10,000 (≤0.6% of entry-bar volume) so the cap never bound; the vulnerability is gate attrition and impact in stress (S4) and scaling to a larger account. Exit impact is not modelled.", "[S]; impact [U]"),
 ("V8", "Venue / counterparty / asset-status events", "Binance.com was HTTP 451 from the research container; venue eligibility is unresolved. Insolvency, withdrawal freeze, delisting, USDT depeg: exposure up to the full venue balance, no probability estimable.", "[U]"),
 ("V9", "Data and warm-up blind spots", "One missing hour resets the 1000-bar warm-up (about 167 days at 4H) so MOM/REV were blind in two multi-month periods; survivorship-selected nine-asset cohort; final year consumed; assumed lot/min-notional. Risk numbers inherit all of these.", "[H] / [U]"),
 ("V10", "Sample inadequacy for tail estimates", f"REV n = {DB[REV]['loss_streaks']['n_trades']}, MOM n = {DB[MOM]['loss_streaks']['n_trades']}; 99% VaR/ES rest on {DB[MOM]['var_es_pooled']['0.99']['tail_obs']} tail days. No tail probabilities are asserted.", "limitation"),
]
A(tbl(["id", "vulnerability", "mechanism and evidence", "basis"], V))
A("\n")

# ------------------------------------------------------------------ D
VR = S["variants"]; TH = VR["M3_drawdown_throttle_replay_APPROX"]; PR = S["policy_replay"]
A("## D. Risk policy with thresholds\n")
A("All thresholds are **proposed policy choices for a research/paper setting**, derived from the measurements above and not optimised or validated out of sample. No capital is allocated by this document.\n")
A("### D1. Three risk-reduction modifications (development-window sensitivity only; none changes signals)\n")
def v(k, b): x = VR[k][b]; return f"MaxDD {p(x['max_dd_daily_worst_window'])}, pooled net {u(x['net_pnl_usd_3books_windows'])}, ES95 {p(x['es95_1d'],2)}"
rows = [
 ["**M1** Lower risk budget: 0.5% per trade, 1.5% total open", *[f"baseline {p(bs[b]['max_dd_daily_worst_window'])} / {u(bs[b]['net_pnl_usd_3books_windows'])} → {p(VR['M1_risk_0.5pct_open_1.5pct'][b]['max_dd_daily_worst_window'])} / {u(VR['M1_risk_0.5pct_open_1.5pct'][b]['net_pnl_usd_3books_windows'])}" for b in B4],
  f"−20% gap loss max: MOM {p(VR['M1_gap20_shock'][MOM]['max'])}, VEX {p(VR['M1_gap20_shock'][VEX]['max'])} (VEX unchanged: notional cap, not risk budget, binds)"],
 ["**M2** Gross-exposure cap: ≤13.3% notional per position (≤40% gross)", *[f"{p(bs[b]['max_dd_daily_worst_window'])} / {u(bs[b]['net_pnl_usd_3books_windows'])} → {p(VR['M2_notional_cap_13.3pct_per_position'][b]['max_dd_daily_worst_window'])} / {u(VR['M2_notional_cap_13.3pct_per_position'][b]['net_pnl_usd_3books_windows'])}" for b in B4],
  f"−20% gap loss max: MOM {p(VR['M2_gap20_shock'][MOM]['max'])}, VEX {p(VR['M2_gap20_shock'][VEX]['max'])}, combined {p(VR['M2_gap20_shock'][CMB]['max'])}"],
 ["**M3** Drawdown throttle: ×0.5 risk at −10%, halt at −20% (closed-trade replay, approximation)", *[f"train closed-trade DD {p(TH[b]['train']['closed_dd_base'])} → {p(TH[b]['train']['throttle_max_dd_closed'])}; train net {u(TH[b]['train']['net_pnl_base'])} → {u(TH[b]['train']['throttle_net_pnl'])}" for b in B4],
  "Reacts after losses: no protection against a single gap; costs recoveries (see P&L change)"],
]
A(tbl(["modification", "MOM: MaxDD(worst window) / pooled net P&L", "REV", "VEX", "COMBINED", "what it does not fix"], rows))
A(f"""
Format: baseline → modified. **Findings:** M1 roughly halves MaxDD and ES but also roughly halves P&L (ratio is not improved by construction); it does nothing for VEX gap exposure. M2 is the only one that bounds gap loss (VEX −20% gap {p(S['S1_sudden_20pct_decline']['hypothetical'][VEX]['gap_-20pct']['max'])} → {p(VR['M2_gap20_shock'][VEX]['max'])}) and cut VEX MaxDD from {p(bs[VEX]['max_dd_daily_worst_window'])} to {p(VR['M2_notional_cap_13.3pct_per_position'][VEX]['max_dd_daily_worst_window'])}, at a P&L cost ({u(bs[VEX]['net_pnl_usd_3books_windows'])} → {u(VR['M2_notional_cap_13.3pct_per_position'][VEX]['net_pnl_usd_3books_windows'])}). M3 cut train drawdown for MOM and VEX but lowered or reversed P&L there (the recoveries were part of the return) and tripped the halt in the combined train book. **No modification is claimed to raise return without raising risk; each lowers risk at a measured or implied cost in return.**
""")
A("### D2. Two potential efficiency improvements (hypotheses — not claimed to raise returns without raising risk)\n")
e2 = EF["E2_inverse_vol_sleeves_EXPLORATORY_one_configuration"]
A(f"""- **E1. Lower execution cost per trade (maker/limit entries or a lower fee tier), principally for VEX.** Costs are {p(EF['cost_share_of_gross_all_books'][VEX]['train']['cost_over_abs_gross'],0)} / {p(EF['cost_share_of_gross_all_books'][VEX]['validation']['cost_over_abs_gross'],0)} / {p(EF['cost_share_of_gross_all_books'][VEX]['final']['cost_over_abs_gross'],0)} of VEX gross P&L (train/validation/final) and {p(EF['cost_share_of_gross_all_books'][MOM]['train']['cost_over_abs_gross'],0)} / {p(EF['cost_share_of_gross_all_books'][MOM]['validation']['cost_over_abs_gross'],0)} of MOM's. **Untested:** it needs observed fee/fill data; passive entries add non-fill and adverse-selection risk, and stop exits remain marketable. A simpler filter I examined, tightening the cost gate, is **not supported**: in all three windows the highest cost-to-risk tercile of VEX trades had the *best* mean R (train {n2(EF['E1_VEX_cost_to_risk_terciles_DESCRIPTIVE_POST_HOC']['train']['high']['mean_R'],2)}, validation {n2(EF['E1_VEX_cost_to_risk_terciles_DESCRIPTIVE_POST_HOC']['validation']['high']['mean_R'],2)}, final {n2(EF['E1_VEX_cost_to_risk_terciles_DESCRIPTIVE_POST_HOC']['final']['high']['mean_R'],2)}; post-hoc, descriptive).
- **E2. Allocate capital across sleeves by inverse volatility instead of one shared three-slot book (MOM and VEX only; REV excluded).** Weights from train daily volatility ({p(e2['weights_from_train_daily_sd'][MOM],0)} MOM / {p(e2['weights_from_train_daily_sd'][VEX],0)} VEX) applied to validation and final: annualised volatility {p(e2['evaluation']['validation']['inverse_vol_MOM_VEX']['ann_vol'],1)} vs {p(e2['evaluation']['validation']['equal_weight_MOM_VEX']['ann_vol'],1)} for 50/50 (validation) and {p(e2['evaluation']['final']['inverse_vol_MOM_VEX']['ann_vol'],1)} vs {p(e2['evaluation']['final']['equal_weight_MOM_VEX']['ann_vol'],1)} (final), but total return was lower than 50/50 in both ({p(e2['evaluation']['validation']['inverse_vol_MOM_VEX']['total_return'],1)} vs {p(e2['evaluation']['validation']['equal_weight_MOM_VEX']['total_return'],1)}; {p(e2['evaluation']['final']['inverse_vol_MOM_VEX']['total_return'],1)} vs {p(e2['evaluation']['final']['equal_weight_MOM_VEX']['total_return'],1)}) and the final-window Sharpe is ≈ 0. **Lower risk, no demonstrated gain in return per unit risk.** For reference the shared combined book had {p(DB[CMB]['windows']['train']['max_dd_daily'],0)} train MaxDD versus {p(e2['evaluation']['train']['equal_weight_MOM_VEX']['max_dd'],0)} for equal-capital MOM+VEX sleeves (a sizing difference: the shared book gives VEX the whole account).

Both require a new rules version, ledger registration and preregistration before any held-out evaluation.
""")
A("### D3. Revised sizing and portfolio-level risk caps (proposed)\n")
pol = [
 ["CRY-MOM-101", "0.50%", "1.50% (≤3 positions)", "13.3% equity (≤40% gross)", "3, one per symbol", "continue; paper/forward"],
 ["CRY-VEX-103", "0.25%", "0.75%", "10% equity (≤30% gross)", "3, one per symbol", "conditional; shadow until execution evidence"],
 ["CRY-REV-102", "0%", "0%", "0%", "0", "shadow only (signals logged, no sizing)"],
]
A(tbl(["sleeve", "risk per trade (of sleeve equity)", "open risk cap", "notional cap per position", "max positions", "mode"], pol))
A(f"""
**Portfolio-level caps (all sleeves combined, % of portfolio equity):** total open reserved risk ≤ 1.5%; gross notional ≤ 40%; any single asset ≤ 15% (summed across sleeves); at most 3 concurrent positions portfolio-wide, one per symbol; no new entries while the rolling 30-day mean pairwise correlation of the cohort exceeds 0.90 (≈ its historical 95th percentile; rule untested); no leverage, no shorting, no derivatives. **Arithmetic rationale:** loss under an instant −20% gap ≈ 0.20 × gross exposure, so a 40% gross cap bounds that scenario near 8–9% of equity (plus costs); the observed replay of the proposed limits is below.

**Replay of the proposed limits on the Stage 02 windows [S, descriptive, single configuration, not optimised or out-of-sample]:**
""")
rows = []
for k, x in {**PR["sleeves"], **PR["portfolio"]}.items():
    rows.append([k, x["n_trades"], u(x["net_pnl_usd"]), n2(x["ratio"], 3), " / ".join(p(x["max_dd_by_window"][w]) for w in W), p(x["es95_1d"], 2), p(x["worst_7d"], 1), p(x["gap20_shock_max"], 1), p(x["freeze72h_max"], 1), p(x["max_gross_pct_equity"], 0), p(x["max_open_risk_pct"], 1)])
A(tbl(["book", "trades", "pooled net P&L", "ratio", "MaxDD train / val / final", "ES95 1d", "worst 7d", "−20% gap max loss", "72h freeze max loss", "max gross (mark-to-market)", "max open risk"], rows))
A("""
The portfolio row (MOM+VEX in one shared book at 0.5%/1.5%/13.3%) still drew down about 15% in the train window and its 72h-freeze worst case exceeds the −20% gap bound because a 72-hour adverse excursion on held assets can exceed 20%; limits bound *entry* sizing, not the size of the move or the length of an outage. These limits therefore do not remove the need for the stop-trading rules below.

### D4. Explicit stop-trading and pause conditions (proposed)
""")
t1 = S["trigger_replay_counts_at_M1_sizing"]
trig = [
 ["T1 Drawdown, sleeve or portfolio (daily mark-to-market, from high-water mark)", "≥ 8%: halve risk; ≥ 12%: no new entries pending review; ≥ 15%: halt and independent review before restart", f"At 0.5% risk (VEX's proposed budget is 0.25%) the replay crossed 8% {sum(t1[MOM][w]['dd_cross_8pct'] for w in W)}× (MOM) and {sum(t1[VEX][w]['dd_cross_8pct'] for w in W)}× (VEX) and 12% {sum(t1[VEX][w]['dd_cross_12pct'] for w in W)}× (VEX) in 5 years; baseline MaxDD {p(DB[MOM]['windows']['train']['max_dd_daily'],0)}/{p(DB[VEX]['windows']['train']['max_dd_daily'],0)}"],
 ["T2 Single-day loss", "≥ 3% of equity: no new entries until the next UTC day", f"Largest 1d loss at baseline: MOM {p(DB[MOM]['worst_1d_return'],1)}, VEX {p(DB[VEX]['worst_1d_return'],1)}, combined {p(DB[CMB]['worst_1d_return'],1)}; under the proposed limits: MOM {p(PR['sleeves'][MOM]['worst_1d'],1)}, VEX {p(PR['sleeves'][VEX]['worst_1d'],1)}, portfolio {p(PR['portfolio']['PORTFOLIO_MOM_VEX']['worst_1d'],1)} (so T2 sits above every historical day at policy size)"],
 ["T3 Rolling 7-day loss", "≥ 5%: halve risk until recovered above −2%", f"Worst 7d at baseline: MOM {p(DB[MOM]['worst_7d_return'],1)}, VEX {p(DB[VEX]['worst_7d_return'],1)}, combined {p(DB[CMB]['worst_7d_return'],1)}; under the proposed limits: MOM {p(PR['sleeves'][MOM]['worst_7d'],1)}, VEX {p(PR['sleeves'][VEX]['worst_7d'],1)}, portfolio {p(PR['portfolio']['PORTFOLIO_MOM_VEX']['worst_7d'],1)} (T3 is a tripwire above all history at policy size)"],
 ["T4 Loss clusters", "alert at 8 consecutive losses; pause and review at cumulative −10R since the last equity high (R at the sleeve's own risk unit); a loss streak alone is **not** a halt", f"≥8-loss runs occurred {DB[MOM]['loss_streaks']['runs_ge8']}× (MOM) and {DB[VEX]['loss_streaks']['runs_ge8']}× (VEX) in the sample; costliest runs {n2(DB[MOM]['loss_streaks']['worst_run_R'],1)}R / {n2(DB[VEX]['loss_streaks']['worst_run_R'],1)}R"],
 ["T5 Execution quality", "pause new entries if the mean realised cost per side over the last 20 fills exceeds 2× assumed (0.30%), if any stop fills worse than −2R, or if 3 stops fill worse than −1.5R in 30 days", f"Bar-low bound: {p(ov[VEX]['stop_fills_at_exit_bar_low']['share_R_adjusted_below_minus1_5'],0)} of VEX stops and {p(ov[MOM]['stop_fills_at_exit_bar_low']['share_R_adjusted_below_minus1_5'],0)} of MOM stops would be worse than −1.5R if fills were at the bar low; VEX stop-fill slack ≈ {n2(tol[VEX]['pooled_all']['breakeven_extra_bps_per_stop_exit'],0)} bp"],
 ["T6 Data and feed", "any missing 1H bar: existing warm-up reset applies; stale feed > 2 bars or a failed checksum: no new entries; feed outage with open positions: manage manually, halt if > 24h", "Stage 02 audit: 7 missing hours in 3 events; warm-up blackout ≈ 167 days at 4H (V9)"],
 ["T7 Venue and asset status", "venue/API unavailable with open positions, withdrawal suspension, delisting notice, or USDT/USD deviation > 1%: halt entries and escalate", "Unquantified (V8); freeze scenario: 24h worst loss at baseline exposure up to " + p(F['24'][CMB]['max'], 0)],
 ["T8 Liquidity", "an asset fails L1–L3 or its 24h quote volume < 50% of its 90-day median: no entries in that asset; participation never above 1% of median hourly volume", "Assumed thresholds; S4: gate attrition 37–58% of candidates at 10% volume"],
 ["T9 Concentration", "30-day mean pairwise correlation > 0.90, or ≥ 2 sleeves long the same asset: cap at 2 concurrent positions", f"Rolling 30d correlation 95th pct {n2(rc['p95'])}, max {n2(rc['max'])}; MOM and VEX overlapped on the same symbol in {X['same_symbol_overlapping_position_pairs_standalone_books']['CRY-MOM-101~CRY-VEX-103']} trade pairs (untested rule)"],
 ["T10 Forward-evidence stop", "after ≥ 100 forward/paper trades per sleeve, if the point estimate of expectancy is ≤ −0.2R or the 99.17% bootstrap bound is still ≤ 0 and drawdown has tripped T1 twice: archive the sleeve", "Stage 02 plan: all 99.17% lower bounds currently < 0; this is a research-governance rule"],
]
rows = [[t[0], t[1], t[2]] for t in trig]
A(tbl(["condition", "pause / stop action", "evidence and calibration"], rows))
A("\nThresholds T1–T3 are set relative to the proposed 0.5%/0.25% sizing (T2 and T3 above every historical value at that size, so they are tripwires for out-of-sample behaviour, not tuned fits); if sizing changes, rescale in proportion to risk per trade. A tripped condition requires a recorded review before restart; none of these rules has been tested out of sample.\n")

# ------------------------------------------------------------------ E
A("## E. Revised strategy eligibility for continued research\n")
tolm = lambda b: n2(tol[b]['pooled_all']['breakeven_extra_bps_per_stop_exit'], 0)
elig = [
 [MOM, "INVESTIGATE (weak)", "ELIGIBLE — continue research (paper/forward only)", "0.50% per trade, 1.50% open, 13.3% notional/position, ≤40% gross",
  f"Whipsaw/late entries in chop and V-reversals; long loss runs (max {DB[MOM]['loss_streaks']['max_run']}); MaxDD {p(DB[MOM]['windows']['train']['max_dd_daily'],0)} at 1%; 4H warm-up blackouts; moderate gap exposure (−20% gap → {p(H1x[MOM]['gap_-20pct']['max'],0)} at baseline, {p(VR['M1_gap20_shock'][MOM]['max'],0)} at 0.5%); stop-fill slack ≈ {tolm(MOM)} bp",
  "Observed fills/fees; new-version preregistration; forward ≥100 trades or adjacent-asset holdout; independent data source"],
 [VEX, "INVESTIGATE (weak, cost-fragile)", "CONDITIONAL — shadow/paper only; no risk budget above 0.25% until stop-fill and fee evidence exists", "0.25% per trade, 0.75% open, 10% notional/position, ≤30% gross",
  f"Notional-cap-bound ≈100% gross; stop-fill slack ≈ {tolm(VEX)} bp pooled ({n2(tol[VEX]['train']['breakeven_extra_bps_per_stop_exit'],1)} bp train); costs {p(EF['cost_share_of_gross_all_books'][VEX]['train']['cost_over_abs_gross'],0)} of gross P&L; fails ×3 cost; turnover 110–165×/yr; 22-loss runs; the Stage 02 random-entry null is degenerate",
  "Venue fee tier and spread data; measured stop slippage (paper fills); a reduced-turnover rules version registered first; gating on execution-cost evidence"],
 [REV, "REJECT (inconclusive sample)", "NOT ELIGIBLE for risk — shadow signal logging only", "0% (no sizing)",
  f"n = {DB[REV]['loss_streaks']['n_trades']} trades; no pooled edge; realised R:R {n2(DB[REV]['windows']['train']['realized_rr'])}/{n2(DB[REV]['windows']['validation']['realized_rr'])}/{n2(DB[REV]['windows']['final']['realized_rr'])} against a planned ≥1.0; wicks of ~1.1% below stops; −20% gap loss up to {p(H1x[REV]['gap_-20pct']['max'],0)} on a 33%-notional position; no stop-fill slack",
  "None planned; reopen only with a new rules version and a materially larger sample (≥100 trades)"],
]
A(tbl(["strategy", "Stage 02 label", "Stage 03 eligibility", "defined risk budget (proposed)", "failure mechanisms (measured)", "needed before any upgrade"], elig))
A("""
These are research assessments. Formal dispositions still come only from `research/validation/adjudicate.py`; the ledger holds the three hypotheses as REGISTERED and not frozen, so adjudication has **not** been run.

## F. STAGE_03_HANDOFF

Written to `docs/strategy-specs/STAGE_03_HANDOFF.json` (status `RESEARCH_ASSESSMENT_NOT_LEDGER_ADJUDICATED`): inputs, provenance, per-strategy risk budgets and eligibility, portfolio caps, trigger table, scenario summary, evidence hashes, limitations and unresolved items.

## Limitations and what was not done

- Costs, lot size, min-notional, spread and depth are **assumed**; the execution venue is UNSPECIFIED; OHLC bars cannot reveal stop slippage or market impact. Every gap and stop-failure number is a bound or a hypothetical, not a measurement.
- The data are Binance spot archive bars (single source, survivor-selected cohort, five years, one bull-bear cycle); the final year was already consumed. No funding, borrow, margin, tax or withdrawal risk exists in these spot, long-only books.
- Daily-return VaR/ES use 1,826 pooled days from three separate books; 99% is limited and 99.9% is not reported. Loss-run expectations assume independence and are illustrative only.
- Variants M1–M3, the policy replay and E2 are exploratory single-configuration runs on windows already seen by the Stage 02 analysis; they are not registered hypotheses, are not preregistered, and cannot be cited as evidence of improvement. E1 and all trigger thresholds are untested.
- Not done: ledger freeze/adjudication; observed fills; a second data source; delisted assets; account sizes other than $10,000; live or paper execution.
""")
(D / "STAGE_03_RISK_REPORT.md").write_text("\n".join(L))

# ------------------------------------------------------------------ handoff JSON
def sha(pth): return hashlib.sha256(Path(pth).read_bytes()).hexdigest()
ev = {}
for f_ in ["docs/strategy-specs/stage03/risk_results.json", "docs/strategy-specs/stage03/risk_drawdown_shock.png", "docs/strategy-specs/STAGE_03_RISK_REPORT.md", "docs/strategy-specs/STAGE_02_HANDOFF.json", "docs/strategy-specs/stage02/trades_baseline.csv"]:
    ev[f_] = dict(sha256=sha(ROOT / f_))
H = dict(handoff_type="STAGE_03_HANDOFF", schema_version="1.0.0", status="RESEARCH_ASSESSMENT_NOT_LEDGER_ADJUDICATED", created="2026-11-18",
  inputs=dict(stage01="docs/strategy-specs/STAGE_01_HANDOFF.v2.json", stage02="docs/strategy-specs/STAGE_02_HANDOFF.json", rules_version="0.1.0-draft (unchanged)"),
  provenance=dict(head_commit_at_run=commit, stage02_stage03_source_dirty=src_dirty, reconciliation_to_stage02_trades=r["meta"]["reconciliation_ok"], costs=dict(fee=0.001, adverse=0.0005, status="ASSUMED_NOT_OBSERVED"),
                  windows=r["meta"]["windows"], window_status=r["meta"]["window_status"], bootstrap=r["meta"]["bootstrap"]),
  labels=dict(H="historical backtest measurement (assumed costs)", S="simulated/hypothetical rule", U="unquantified"),
  ledger=dict(registered=h2["ledger"]["registered"], preregistration_frozen=False, adjudicate_py_run=False),
  risk_budgets={MOM: dict(risk_per_trade=0.005, open_risk_cap=0.015, notional_cap_per_position=0.133, max_positions=3, mode="paper_forward_only"),
                VEX: dict(risk_per_trade=0.0025, open_risk_cap=0.0075, notional_cap_per_position=0.10, max_positions=3, mode="shadow_or_paper_micro_budget_pending_execution_evidence"),
                REV: dict(risk_per_trade=0.0, open_risk_cap=0.0, notional_cap_per_position=0.0, max_positions=0, mode="shadow_signal_logging_only")},
  portfolio_caps=dict(total_open_risk=0.015, gross_notional=0.40, single_asset=0.15, max_positions=3, one_position_per_symbol=True, leverage=False, shorting=False,
                      correlation_rule="no new entries while rolling-30d mean pairwise cohort correlation > 0.90 (untested)", status="PROPOSED_NOT_VALIDATED"),
  stop_trading_conditions=[dict(id=t[0].split()[0], condition=t[0], action=t[1]) for t in trig],
  eligibility={MOM: dict(stage02="INVESTIGATE", stage03="ELIGIBLE_CONTINUED_RESEARCH_PAPER_FORWARD_ONLY"), VEX: dict(stage02="INVESTIGATE", stage03="CONDITIONAL_SHADOW_PAPER_ONLY_PENDING_EXECUTION_EVIDENCE"),
               REV: dict(stage02="REJECT", stage03="NOT_ELIGIBLE_SHADOW_ONLY")},
  key_measurements={
    "baseline_max_dd_daily_by_window": {b: {w: DB[b]["windows"][w]["max_dd_daily"] for w in W} for b in B4},
    "var_es_pooled_1d_historical": {b: {k: dict(var=DB[b]["var_es_pooled"][k]["hist_var"], es=DB[b]["var_es_pooled"][k]["hist_es"], tail_obs=DB[b]["var_es_pooled"][k]["tail_obs"], adequacy=DB[b]["var_es_pooled"][k]["adequacy"]) for k in ("0.95", "0.99")} for b in B4},
    "loss_streaks": {b: {k: DB[b]["loss_streaks"][k] for k in ("n_trades", "loss_share", "max_run", "runs_ge10", "worst_run_R")} for b in B4},
    "gap20_shock_max_loss_fraction_equity": {b: H1x[b]["gap_-20pct"]["max"] for b in B4},
    "stop_fill_tolerance_bps_per_stop_exit_pooled": {b: tol[b]["pooled_all"]["breakeven_extra_bps_per_stop_exit"] for b in B4},
    "freeze_max_loss_fraction_equity": {T: {b: F[T][b]["max"] for b in B4} for T in ("24", "72", "168")},
    "scenario_reruns_pooled_ratio": {k: {b: S[k][b]["ratio"] for b in B4} for k in ("baseline", "S2_volatility_x2_HYPOTHETICAL", "S3_costs_x3_HYPOTHETICAL", "S4a_volume_x0.1_HYPOTHETICAL", "S4b_volume_x0.1_and_slippage_x4_HYPOTHETICAL")},
    "policy_replay": PR},
  modifications=dict(risk_reduction=["M1 risk 0.5%/1.5%", "M2 notional cap 13.3% per position (<=40% gross)", "M3 drawdown throttle x0.5 at -10%, halt -20% (replay approximation)"], efficiency=["E1 lower execution cost (untested; needs venue data)", "E2 inverse-volatility sleeve weights, MOM+VEX (exploratory; no demonstrated gain per unit risk)"],
                     status="EXPLORATORY_NOT_REGISTERED_NOT_PREREGISTERED_NO_PERFORMANCE_CLAIM"),
  evidence_files=ev,
  limitations=["Assumed costs, lots, spreads; execution venue UNSPECIFIED", "OHLC bars cannot reveal stop slippage or impact: all gap/stop-failure figures are bounds or hypotheticals", "Survivor-selected nine-asset cohort; single data source; final year CONSUMED_LEGACY",
               "Tail estimates inadequate (99% VaR/ES 19 tail days; trade samples small); no tail probabilities asserted", "Variants and thresholds are single-configuration, unvalidated policy choices"],
  unresolved=["execution venue and eligibility", "observed fee tier, spread, depth, stop-order behaviour and slippage", "independent second data source and delisted assets", "ledger preregistration freeze and adjudicate.py run (needs independent review)",
              "forward paper evaluation (>=6 months, >=100 trades) or adjacent-asset holdout", "calibration of proposed thresholds on forward data", "account-size scaling of liquidity and impact"])
(D / "STAGE_03_HANDOFF.json").write_text(json.dumps(H, indent=1))
print("wrote report + handoff", (D / "STAGE_03_RISK_REPORT.md").stat().st_size)
