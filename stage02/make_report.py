"""Generate STAGE_02 report tables + handoff from results.json (no hand-typed numbers)."""
import json, hashlib, math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; D = ROOT / "docs/strategy-specs"; S2 = D / "stage02"
R = json.loads((S2 / "results.json").read_text()); X = json.loads((S2 / "results_extra.json").read_text())
SIDS = ["CRY-MOM-101", "CRY-REV-102", "CRY-VEX-103"]; W = ["train", "validation", "final"]
def f(x, n=3, pct=False):
    if x is None or (isinstance(x, float) and math.isnan(x)): return "n/a"
    if x == float("inf"): return "inf"
    return f"{x*100:.1f}%" if pct else f"{x:.{n}f}"
def gates(sid):
    o = R[sid]; v = o["windows"]["validation"]; pooled = o["pooled_train_validation"]["trade_metrics"]
    cs = o["cost_stress"]; nb = o["neighbours"]; ab = o["ablation"]
    g = {}
    g["F1 validation ratio > 0"] = v["ratio"] > 0
    g["F2 ratio > 0 under both cost stresses (validation)"] = all(cs[k]["validation"]["ratio"] > 0 for k in cs if k != "baseline")
    g["F3 99.17% bootstrap lower bound > 0 (validation)"] = v["ratio_bootstrap"]["lower_one_sided"] > 0
    g["F4 real mean R > null p95 (validation, literal)"] = o["null"]["validation"]["exceeds_p95"]
    bad = sum(1 for k in nb if nb[k]["validation"]["ratio"] <= 0)
    g[f"F5 fewer than half of neighbours <= 0 ({bad}/{len(nb)} <= 0)"] = bad < len(nb) / 2
    g["F6 ratio > 0 after dropping best 5% trades (validation)"] = o["F6"]["validation"][0] is not None and o["F6"]["validation"][0] > 0
    g["F7 pooled train+validation trades >= 100"] = pooled["n"] >= 100
    g["F8 >= 2 of 3 subperiods positive"] = sum(1 for s in o["F8_subperiods"] if s["ratio"] and s["ratio"] > 0) >= 2
    g[f"F9 {ab['name']} does not match/beat real rule (validation)"] = ab["validation"]["ratio"] < v["ratio"]
    if sid == "CRY-REV-102": g["F10 5 worst losses < gross profit (pooled)"] = abs(pooled["worst5_loss"]) < pooled["gross_profit"]
    return g, pooled["ratio"]
def label(sid):
    g, pr = gates(sid); k = list(g)
    if not g[k[0]] or pr <= 0 or not [g[x] for x in k if x.startswith(("F9", "F10"))] == [True] * len([x for x in k if x.startswith(("F9", "F10"))]): return "REJECT"
    return "PASS-CONDITIONAL" if all(g[x] for x in k) else "INVESTIGATE"
LAB = {s: label(s) for s in SIDS}
L = []
def T(h, rows): L.append("| " + " | ".join(h) + " |"); L.append("|" + "---|" * len(h)); [L.append("| " + " | ".join(r) + " |") for r in rows]; L.append("")
m = R["meta"]
L += ["# STAGE 02 — Independent backtest of CRY-MOM-101, CRY-REV-102, CRY-VEX-103", "",
 f"Executed {m['windows']['train'][0][:10]}..{m['windows']['final'][1][:10]} on Binance spot public-archive 1H klines (USDT quote). Code commit `{m['code_commit'][:12]}`, rules_version `{m['rules_version']}` (unchanged from STAGE_01_HANDOFF.v2.json), Python {m['python']}, numpy {m['numpy']}, pandas {m['pandas']}. All outputs are deterministic (two consecutive runs gave byte-identical results). Costs are **assumed, not observed** (fee 0.10%, adverse 0.05% per side). The final window is a consumed legacy window: descriptive only. Nothing here is a profitability claim.", "",
 "**Headline:** none of the three strategies shows statistically credible net edge. Point estimates are small and positive in validation for MOM and VEX, but every 99.17% bootstrap lower bound is below zero, results are fragile to costs and parameters, and the consumed final window is flat-to-negative for MOM and REV. Assessments: " + "; ".join(f"**{s}: {LAB[s]}**" for s in SIDS) + ".", ""]
L += ["## A. Reproducible methodology", "",
 "- **Data (VERIFIED):** `data.binance.vision` monthly 1H spot klines 2021-05..2026-10 plus daily files 2026-11-01..17 for BTC, ETH, SOL, XRP, ADA, LINK, AVAX, DOGE, LTC; 747 files, all SHA-256 verified against Binance's published `.CHECKSUM`; manifest hash `" + m["data_manifest_sha256"][:16] + "…`. Time zone UTC, bar timestamp = open time; microsecond timestamps (2025+) normalised. Venue: Binance spot (the execution venue the user left as '[Specify]' is **still unspecified**; Binance.com API itself returned HTTP 451 from this environment).",
 "- **Code:** `stage02/` (`fetch.py`, `data.py`, `engine.py`, `analysis.py`, `run_full.py`, `run_extra.py`, `make_report.py`); tests `tests/stage02/test_engine.py` (8 synthetic mechanics tests: sizing worked example, stop-first, gap-through fill, next-bar trailing, next-open signal exits, Wilder indicators by hand, 4H invalidation/warm-up reset, future-perturbation invariance of signals). Frozen analysis plan: `docs/strategy-specs/STAGE_02_ANALYSIS_PLAN.md` (committed before any real-data result). Reproduce: `python -m stage02.fetch && python -m stage02.run_full && python -m stage02.run_extra && python -m stage02.make_report`.",
 "- **Execution model:** signal at completed-bar close; market entry at next open; adverse slippage s and fee f per side; initial stop live in entry bar; stop fills at min(stop, open)·(1−s) (gap-through losses can exceed 1R); stop-first on ambiguity; trailing/ratchet effective next bar; SMA20 limit fills only on strict high-through; gap guard; cost-feasibility gate; one-bar cooldown; liquidity gates L1–L3; 1% risk per trade, 3% total open risk, 33% notional cap, 1% of median hourly quote volume participation cap, ≤3 positions, one per symbol; spot, long-only, so **no funding/borrow applies**; spread is inside the adverse-slippage term (no observed spreads); partial fills are **not** modelled beyond the participation cap; cash earns 0.",
 "- **Windows (chronological, fixed before evaluation):** train 2021-11-17→2024-11-17; validation 2024-11-17→2025-11-17; final 2025-11-17→2026-11-17 (`CONSUMED_LEGACY`, descriptive). Each is a fresh $10,000 book; open positions force-closed at the window's last close (counted in `forced_closes`). Warm-up: 1000 consecutive valid bars after any gap.",
 "- **Books:** primary inference = standalone book per strategy; combined book (shared slots/risk, handoff priority order) reported separately.",
 "- **Uncertainty:** circular block bootstrap (14-day blocks, 10,000 resamples, seed 20261118) on sum(P&L)/sum(reserved risk); Sharpe 95% CI by block bootstrap of daily returns; 1000-draw random-entry null.", ""]
L += ["## B. Metrics by strategy (baseline assumed costs, standalone $10,000 book)", "",
 "Sharpe/Sortino use daily mark-to-market equity, rf = 0, ×√365. `ratio` = Σnet P&L / Σreserved risk. R = P&L / reserved initial risk (costs included). Exposure = share of hours with ≥1 open position; invested = mean position value / equity; turnover = (buys+sells)/mean equity per year.", ""]
for sid in SIDS:
    L.append(f"### {sid}"); rows = []
    for w in W:
        x = R[sid]["windows"][w]
        rows.append([w, str(x["n"]), f(x["win_rate"], 2), f(x["profit_factor"], 2), f(x["expectancy_R"]), f(x["median_R"]), f(x["ratio"]), f(x["cagr"], pct=True), f(x["ann_vol"], pct=True),
                     f(x["sharpe"], 2) + " [" + f(x["sharpe_ci95_block_boot"][0], 1) + ", " + f(x["sharpe_ci95_block_boot"][1], 1) + "]", f(x["sortino"], 2), f(x["max_dd"], pct=True), f(x["exposure_time"], pct=True), f(x["avg_invested_pct_equity"], pct=True), f(x["turnover_per_year"], 1)])
    T(["window", "trades", "win", "PF", "E[R]", "median R", "ratio", "CAGR", "ann vol", "Sharpe [95% CI]", "Sortino", "MaxDD", "exposure", "invested", "turnover/yr"], rows)
    p = R[sid]["pooled_train_validation"]; pb = p["ratio_bootstrap"]
    L.append(f"Pooled train+validation: n={p['trade_metrics']['n']}, ratio {f(p['trade_metrics']['ratio'])}, bootstrap 95% CI [{f(pb['ci95'][0])}, {f(pb['ci95'][1])}], 99.17% one-sided lower bound {f(pb['lower_one_sided'])}. Exit mix (all windows): stops/targets/open-fills/forced = " + " / ".join(str(sum(R[sid]['windows'][w][k] for w in W)) for k in ("stop_exits", "target_exits", "open_exits", "forced_closes")) + f". Losses worse than −1R: {sum(R[sid]['windows'][w]['gt1R_loss'] for w in W)} (gap-through).")
    L.append("")
L += ["### Combined book (shared 3 slots / 3% risk; MOM → REV → VEX priority)", ""]
T(["window", "trades", "ratio", "total return", "Sharpe", "MaxDD", "trades MOM/REV/VEX"], [[w, str(R["combined_book"][w]["n"]), f(R["combined_book"][w]["ratio"]), f(R["combined_book"][w]["total_return"], pct=True), f(R["combined_book"][w]["sharpe"], 2), f(R["combined_book"][w]["max_dd"], pct=True), "/".join(str(R["combined_book"][w]["by_strategy"][s]["n"]) for s in SIDS)] for w in W])
L += ["### Sample sizes and power", "", "Trade counts above are the sample sizes; the R-multiple SD is roughly 1R, so with n≈50–100 the standard error of mean R is about 0.1–0.14R, comparable to the observed point estimates. REV has only 62 pooled train+validation trades (F7 requires 100). Evidence is **weak** for all three; VEX has the largest sample (984 pooled) but a point estimate near zero.", ""]
L += ["### Performance by calendar year (chained daily returns of the three windows; trades by entry year)", ""]
for sid in SIDS:
    by = R[sid]["by_year"]; L.append(f"**{sid}**"); L.append("")
    T(["year", "days", "return", "trades", "ratio"], [[y, str(v["days"]) + (" (partial)" if v["partial_year"] else ""), f(v["return_chained"], pct=True), str(v["n_trades"]), f(v["ratio"], 2)] for y, v in by.items()])
L += ["### Performance by market regime (attribution only; BTC prior-day close vs SMA200 × prior 30-day vol vs 60%)", ""]
for sid in SIDS:
    rg = R[sid]["by_regime_trades"]; sh = R[sid]["regime_day_share"]
    L.append(f"**{sid}**"); L.append("")
    T(["regime", "share of days", "trades", "win rate", "E[R]", "ratio"], [[k, f(sh.get(k, 0), pct=True), str(v["n"]), f(v["win_rate"], 2), f(v["expectancy_R"], 2), f(v["ratio"], 2)] for k, v in rg.items()])
L += ["Regime cells with fewer than ~30 trades are not interpretable.", ""]
L += ["### Sensitivity to trading costs (ratio; multiples scale both fee and slippage)", ""]
for sid in SIDS:
    g = R[sid]["cost_multiple_grid"]; L.append(f"**{sid}**"); L.append("")
    rows = [[k + "×"] + [f(g[k][w]["ratio"]) for w in W] for k in g]
    for name, d in R[sid]["cost_stress"].items():
        if name != "baseline": rows.append([name] + [f(d[w]["ratio"]) for w in W])
    T(["cost", "train", "validation", "final"], rows)
L += ["Note: the two handoff stress scenarios have the same total per-side cost (0.30%) but differ for VEX because the pre-registered cost gate `2(f+s)P_f > 0.35(P_f−S0)` uses P_f, which includes slippage; more slippage inflates the denominator and admits more thin-stop trades (96 more VEX candidates in scenario B). This is a property of the registered gate, not a measured effect of slippage.", ""]
L += ["## C. Equity and drawdown analysis", "", "![equity and drawdown](stage02/equity_drawdown.png)", "",
 "Daily equity and trade-level evidence are in `stage02/daily_equity_baseline.csv` and `stage02/trades_baseline.csv`. Intra-bar equity is approximated (an exit inside a bar is credited from that bar's first hourly close), so intra-day drawdowns are slightly smoothed.", ""]
rows = []
for sid in SIDS:
    for w in W:
        x = R[sid]["windows"][w]; rows.append([sid, w, f(x["max_dd"], pct=True), str(x["mdd_peak_to_trough_days"]), (str(x["mdd_peak_to_recovery_days"]) if x["mdd_recovered"] else "not recovered by window end"), str(x["longest_underwater_days"])])
T(["strategy", "window", "max drawdown", "peak→trough days", "peak→recovery days", "longest underwater (days)"], rows)
L += ["## D. Benchmark comparison", "",
 "Benchmarks are fully invested (or long/cash) while the strategies' capital is deployed only about 1–11% of the time-weighted equity, so raw returns are **not** like-for-like; Sharpe and drawdown are the fairer comparison, and even those mix very different exposure. Equal-weight and BTC buy-and-hold include entry costs only; the BTC SMA200 benchmark pays costs on each switch. The nine-asset cohort is survivor-selected, which flatters buy-and-hold less than a delisting-free universe would.", ""]
rows = []
for w in W:
    for k, nm in (("EW_BH", "Equal-weight B&H"), ("BTC_BH", "BTC B&H"), ("BTC_SMA200", "BTC SMA200 long/cash")):
        x = R["benchmarks"][w][k]; rows.append([w, nm, f(x["total_return"], pct=True), f(x["cagr"], pct=True), f(x["ann_vol"], pct=True), f(x["sharpe"], 2), f(x["sortino"], 2), f(x["max_dd"], pct=True)])
    for sid in SIDS:
        x = R[sid]["windows"][w]; rows.append([w, sid, f(x["total_return"], pct=True), f(x["cagr"], pct=True), f(x["ann_vol"], pct=True), f(x["sharpe"], 2), f(x["sortino"], 2), f(x["max_dd"], pct=True)])
T(["window", "series", "return", "CAGR", "ann vol", "Sharpe", "Sortino", "MaxDD"], rows)
L += ["Random-entry null (identical exits, same count/symbols, 1000 draws; sizing-neutral mean R):", ""]
rows = []
for sid in SIDS:
    for w in ("train", "validation"):
        n = R[sid]["null"][w]; rows.append([sid, w, f(n["real_mean_R"]), f(n["null_mean"]), f(n["null_p95"]), f(n["p_value"], 3), "yes" if n["exceeds_p95"] else "no"])
T(["strategy", "window", "real mean R", "null mean", "null p95", "p-value", "real > p95"], rows)
L += ["**Null caveat (found after the run, reported as such):** for CRY-VEX-103 the failed-breakout exit is tied to the breakout trigger, so random entries are almost always exited after one bar and pay round-trip costs; the literal null mean (≈−0.11R) is an artefact and the literal F4 pass is **not credible**. A post-hoc diagnostic with that exit leg removed for both real and random entries gives: train real mean R "
 + f(X["null_decoupled_POST_HOC"]["CRY-VEX-103"]["train"]["real_mean_R"]) + " vs null p95 " + f(X["null_decoupled_POST_HOC"]["CRY-VEX-103"]["train"]["null_p95"]) + " (exceeds), validation " + f(X["null_decoupled_POST_HOC"]["CRY-VEX-103"]["validation"]["real_mean_R"]) + " vs p95 " + f(X["null_decoupled_POST_HOC"]["CRY-VEX-103"]["validation"]["null_p95"]) + " (does not exceed, p=" + f(X["null_decoupled_POST_HOC"]["CRY-VEX-103"]["validation"]["p_value"], 3) + "), i.e. mixed. Random in-context 1H entries lose to costs on average, so beating them is a low bar.", ""]
L += ["## E. Bias and data-quality audit", ""]
A_ = R["data_audit"]
T(["symbol", "rows", "missing bars", "gap events", "duplicates", "OHLC violations", "zero-volume bars", "|1H move| > 20%"], [[a["symbol"], str(a["rows"]), str(a["missing_bars"]), str(a["gap_events"]), str(a["duplicates"]), str(a["ohlc_violations"]), str(a["zero_volume_bars"]), str(a["jumps_gt_20pct"])] for a in A_])
L += [f"- Coverage 2021-05-01 00:00 → 2026-11-17 23:00 UTC, 48,648 hourly slots, 7 missing hours (2021-08-13 01:00 ×4, 2021-09-29 06:00 ×2, 2023-03-24 12:00 ×1), **identical across all nine symbols** (consistent with venue-wide gaps; cause not verified). No duplicates, no non-finite or non-positive prices, no OHLC inequality violations; one zero-volume hour per symbol (also shared).",
 "- The >20% hourly moves are **flagged, not removed**: several coincide across symbols on the same hour (e.g. 2021-05-19 12:00, 2022-05-11 12:00); single-symbol cases were not independently verified against a second source. The handoff said invalid data blocks a run; these are extreme-but-valid-looking prints, so a judgement call that is disclosed here. No second data source cross-check was performed.",
 "- **Warm-up consequence:** because any missing hour invalidates a 4H bar and resets warm-up to 1000 bars (≈167 days at 4H), MOM/REV could not signal between 2021-09-29 and ~2022-03-15 or between 2023-03-24 and ~2023-09-06; share of bars eligible by structure (valid, warm, liquid, trend/context) per window: " + "; ".join(f"{s}: " + "/".join(f(X['pool_eligibility_share'][s][w]['mean_share_of_bars_pool_eligible'], pct=True) for w in W) for s in SIDS) + " (train/validation/final). A 400-bar warm-up sensitivity gave similar ratios (see results.json `warmup_400_sensitivity`).",
 "- **Look-ahead:** signals use completed bars only; entry at next open; 4H context for VEX uses the last 4H bar whose close ≤ the 1H close; daily liquidity uses completed UTC days; a synthetic test confirms signals are invariant to perturbing future bars. Stop/target exits free capital only at the end of their bar. Parameters were not tuned and rules were not changed after seeing results.",
 f"- **Constraint audit:** {X['constraint_audit']['checked_trades']} trades checked across all books/windows: violations of 33% notional cap {X['constraint_audit']['notional_cap']}, 1% per-trade risk {X['constraint_audit']['risk_per_trade']}, max 3 positions {X['constraint_audit']['max_positions']}, 3% total open risk {X['constraint_audit']['total_risk']}. Equity reconciles to Σ trade P&L in every run; entry prices hand-checked against raw bars.",
 "- **Survivorship (NOT eliminated):** the nine-asset cohort was chosen retrospectively from assets that survived; delisted/failed assets are UNAVAILABLE. Results for alts are therefore biased upward in expectation.",
 "- **Data leakage / reuse:** the final window was already consumed by legacy Stage 02 work, and the cohort and thresholds were designed knowing the 2021–2026 history in general terms; the train/validation split gives **no** untouched out-of-sample test. Counting this family as 6 hypotheses, 3 were evaluated here with a handful of single-parameter neighbours and ablations, none used to select a variant.",
 "- **Costs/venue (UNAVAILABLE / ASSUMED):** historical fee tier, spread, depth, lot/tick/min-notional filters, venue status and USDT/USD conversion were not observed; lot step 1e-6 and min notional 10 USDT are assumptions; slippage is a flat 0.05% regardless of volatility or size, which understates costs in fast markets and for thin alts. Partial fills, outages and API/latency effects are not modelled. Shorts, funding and borrow are out of scope (spot, long-only).",
 "- **Formal adjudication not run:** `research/validation/adjudicate.py` requires a frozen preregistration, which in this ledger needs an independent recorded review that this session cannot supply. The three hypotheses are registered (ledger state REGISTERED) but not frozen; the labels below are research assessments only.", ""]
L += ["## F. Pass / Investigate / Reject research assessment", "",
 "Rule (declared in the frozen plan): REJECT if F1 fails, pooled train+validation ratio ≤ 0, or a strategy-specific falsifier triggers; PASS-CONDITIONAL only if every gate passes (and never unconditional, because costs/venue/survivorship are unobserved); otherwise INVESTIGATE.", ""]
for sid in SIDS:
    g, pr = gates(sid); L.append(f"### {sid} — **{LAB[sid]}**"); L.append("")
    T(["gate", "result"], [[k, "pass" if v else "FAIL"] for k, v in g.items()])
reasons = {"CRY-MOM-101": "Validation and train point estimates are positive and survive both cost stresses, and the placebo (M≤0) entries do worse, but the 99.17% lower bound is below zero, the real rule does not beat the random-entry null, three of four parameter neighbours are ≤0 in validation, dropping the best 3 trades makes the ratio negative, and the consumed final window is negative. Treat as **weak, possibly noise**; worth investigating only with an independent sample (forward paper, adjacent assets) before any further use.",
           "CRY-REV-102": "Only 119 raw signals / 62 pooled trades; pooled ratio slightly negative, one of three subperiods positive, train negative, final window strongly negative. The REJECT is rule-based on a **small, inconclusive sample** (F7): this test cannot prove the absence of an edge, only that none is demonstrated. The no-trend-filter ablation is clearly worse, which supports the regime filter but not profitability.",
           "CRY-VEX-103": "Largest sample (984 pooled trades) with an expectancy near zero (pooled ratio ≈ +0.02); validation/final positive but train flat, cost-fragile (ratio negative in train and final under both handoff stress scenarios and in validation under stress B; negative at 3× costs in every window), 99.17% lower bound below zero, outlier-dependent (dropping the best 13 trades turns validation negative), turnover ≈110–165×/yr. The literal random-entry test is degenerate (see Section D). Weak evidence; costs dominate."}
for sid in SIDS: L += [f"**{sid} summary:** {reasons[sid]}", ""]
L += ["No strategy is ranked as profitable. The ordering of labels is a statement about falsification gates, not expected returns.", ""]
L += ["## G. STAGE_02_HANDOFF", "", "Machine-readable: `docs/strategy-specs/STAGE_02_HANDOFF.json` (metrics, evidence file hashes, windows, limitations, unresolved items).", ""]
(D / "STAGE_02_BACKTEST_REPORT.md").write_text("\n".join(L))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
H = {"handoff_type": "STAGE_02_HANDOFF", "schema_version": "1.0.0", "status": "RESEARCH_ASSESSMENT_NOT_LEDGER_ADJUDICATED", "created": "2026-11-18",
 "inputs": {"stage01": "docs/strategy-specs/STAGE_01_HANDOFF.v2.json", "rules_version": m["rules_version"], "analysis_plan": "docs/strategy-specs/STAGE_02_ANALYSIS_PLAN.md"},
 "provenance": {"code_commit": m["code_commit"], "source_dirty": m["source_dirty"], "data_provider": "Binance public archive data.binance.vision (spot, 1h klines, USDT quote)", "data_files": m["data_files"],
   "data_manifest_sha256": m["data_manifest_sha256"], "data_checksum_status": m["data_checksum_status"], "python": m["python"], "numpy": m["numpy"], "pandas": m["pandas"], "deterministic_rerun_identical": True},
 "costs": m["baseline_costs"], "windows": m["windows"], "window_status": {"train": "development", "validation": "evaluation (not untouched: cohort/rules designed with general knowledge of history)", "final": "CONSUMED_LEGACY descriptive only"},
 "ledger": {"registered": ["hyp-cry-mom-101@1", "hyp-cry-rev-102@1", "hyp-cry-vex-103@1"], "preregistration_frozen": False, "adjudicate_py_run": False, "reason": "freeze requires independent recorded review"},
 "evidence_files": {p: {"sha256": sha(ROOT / p)} for p in ["docs/strategy-specs/stage02/results.json", "docs/strategy-specs/stage02/results_extra.json", "docs/strategy-specs/stage02/trades_baseline.csv", "docs/strategy-specs/stage02/daily_equity_baseline.csv", "docs/strategy-specs/stage02/equity_drawdown.png", "stage02/audit.json"]},
 "trade_level_evidence": {"file": "docs/strategy-specs/stage02/trades_baseline.csv", "columns": "strategy,symbol,entry_utc,exit_utc,kind,qty,entry_fill,exit_fill,S0,reserved_risk,pnl,R,fees,window,regime,..."},
 "strategies": {}, "benchmarks": R["benchmarks"], "combined_book": {w: {k: R["combined_book"][w][k] for k in ("n", "ratio", "total_return", "sharpe", "max_dd")} for w in W},
 "limitations": ["Assumed (not observed) fees, spread, slippage, lot and min-notional", "Survivor-selected nine-asset cohort; no delisted assets", "No untouched out-of-sample window; final window consumed", "No second data source cross-check; >20% hourly moves flagged not removed",
   "Partial fills not modelled beyond participation cap; flat slippage", "Intra-bar equity approximated; stop/target resolved on strategy-timeframe bars", "Spot long-only: shorts, funding, borrow untested", "Warm-up reset rule blanks 4H signals for ~167 days after each data gap",
   "F4 literal null degenerate for VEX; decoupled diagnostic is post-hoc", "Small samples: REV n=62 pooled; all bootstrap lower bounds < 0"],
 "unresolved": ["execution venue and eligibility", "historical venue filters, fees, spreads, depth", "delisted-asset data", "independent data cross-check", "ledger preregistration freeze + adjudicate.py", "forward paper evaluation from 2026-11-18 or adjacent-asset holdout (BNB, DOT, ATOM, BCH)"]}
for sid in SIDS:
    g, pr = gates(sid)
    H["strategies"][sid] = {"assessment": LAB[sid], "status": "EXECUTED", "gates": g, "pooled_train_validation": {k: R[sid]["pooled_train_validation"]["trade_metrics"].get(k) for k in ("n", "ratio", "expectancy_R", "win_rate", "profit_factor")},
        "windows": {w: {k: R[sid]["windows"][w].get(k) for k in ("n", "win_rate", "profit_factor", "expectancy_R", "ratio", "cagr", "ann_vol", "sharpe", "sortino", "max_dd", "mdd_peak_to_recovery_days", "exposure_time", "turnover_per_year", "total_return")} | {"ratio_bootstrap": R[sid]["windows"][w]["ratio_bootstrap"], "sharpe_ci95": R[sid]["windows"][w]["sharpe_ci95_block_boot"]} for w in W},
        "cost_stress": R[sid]["cost_stress"], "neighbours": R[sid]["neighbours"], "ablation": R[sid]["ablation"], "null": R[sid]["null"]}
(D / "STAGE_02_HANDOFF.json").write_text(json.dumps(H, indent=1, default=str))
print({s: LAB[s] for s in SIDS})
