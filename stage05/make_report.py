"""Generates STAGE_05_FACTOR_MODEL_REPORT.md and STAGE_05_HANDOFF.json from stage05_results.json (no new analysis)."""
import json, hashlib, subprocess, math
from pathlib import Path
from .spec import FACTOR_SPEC
ROOT = Path(__file__).resolve().parents[1]; D = ROOT / "docs" / "strategy-specs"; OUT = D / "stage05"
r = json.loads((OUT / "stage05_results.json").read_text()); fz = json.loads((OUT / "frozen_model.json").read_text())
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
bp = lambda x: "n/a" if x is None else f"{x*1e4:+.1f}"
f3 = lambda x: "n/a" if x is None else f"{x:+.3f}"
PR = ["MOM", "TREND", "VOL", "LIQ", "VALUE"]; AK = PR + ["VALUE_MVRV"]
fi = r["factor_ic"]; st = fi["status"]; cand = r["candidates_ic"]; sel = r["selection"]; rob = r["robustness"]; port = r["portfolio_top3_weekly"]; dep = r["dependence"]; leg = r["consumed_legacy_descriptive"]
def tbl(h, rows): return "| " + " | ".join(h) + " |\n|" + "|".join("---" for _ in h) + "|\n" + "\n".join("| " + " | ".join(map(str, x)) + " |" for x in rows)
def ci(d): return f"{d['mean']:+.3f} [{d['lo95']:+.3f}, {d['hi95']:+.3f}]"
fv = r["frozen_val_ic_POST_SELECTION_optimistic"]; fw = fz["weights"]
se_val = fv["sd"] / math.sqrt(fv["eff_weeks"]); mde = 2.49 * se_val; se26 = fv["sd"] / math.sqrt(26)
cur = r["current"]; frz = port["FROZEN"]; stat = port["STATIC_LOWVOL_ARM"]
L = []; A = L.append
A(f"""# Stage 05 — Regime-aware multi-factor signal model (CRY-MFS-201, v0.1.0-draft)

**Status:** `RESEARCH_SPEC_NOT_VALIDATED` · research only (no orders, credentials or execution) · prepared 2026-11-18 · code `{r['git']['head'][:10]}` (dirty at run: {r['git']['dirty']}) · frozen-model sha256 `{fz['sha256'][:16]}…`
**Inputs:** Stage 01–04 handoffs (`STAGE_01_HANDOFF.v2.json` … `STAGE_04_HANDOFF.json`). **Ledger:** `hyp-cry-mfs-201@1` REGISTERED before any factor statistic was computed; preregistration NOT frozen; `adjudicate.py` NOT run.

## Headline

- **The model is fully specified, reproducible and frozen, but it has NOT demonstrated predictive skill.** Everything below is a development-stage assessment on train and validation windows that were already known to the project (Stage 02: "not untouched"). The consumed 2025-11-17 → 2026-11-17 window is `CONSUMED_LEGACY`; it was read only after the model was frozen and only descriptively.
- **Frozen composite** = equal weights on **MOM, VOL, VALUE(price-based proxy)**; TREND, LIQ and the on-chain MVRV value factor have weight 0 (excluded or experimental). Weights are hypotheses to be tested forward, not estimates of anything real.
- **Only VOL clears the pre-declared validation rule** (validation IC {ci(fi['h7_val']['VOL'])}). But a *static* ranking by train-period volatility (BTC, ETH, XRP, LTC … ADA, LINK, DOGE, AVAX, SOL) scores a *higher* validation IC ({rob['VOL_static_vs_dynamic']['static_val_ic']:+.3f}) than the dynamic factor ({rob['VOL_static_vs_dynamic']['dynamic_val_ic']:+.3f}). The "volatility factor" is therefore a persistent **large-cap-versus-alt tilt in a survivor-selected 9-asset cohort**, not evidence of dynamic volatility timing.
- **The validation result of the frozen composite ({f3(fv['mean'])}) is optimistic**: the composition was edited after seeing validation (TREND and LIQ dropped). Treat it as a development number. In the consumed window (descriptive only) the frozen composite's IC was {f3(leg['results']['FROZEN']['ic']['mean'])} and net top-3 excess {bp(leg['results']['FROZEN']['portfolio']['mean_excess_net_per_week'])} bp/week; VOL stayed positive ({f3(leg['per_factor_ic_DIAGNOSTIC_ONLY']['VOL'])}) while MOM ({f3(leg['per_factor_ic_DIAGNOSTIC_ONLY']['MOM'])}) and VALUE ({f3(leg['per_factor_ic_DIAGNOSTIC_ONLY']['VALUE'])}) were negative. **No change was made to the frozen model after seeing this.**
- **Complexity is not justified yet.** Among the six multi-factor candidates, EQ, NNLS, COND and EQ_TRAINPOS were statistically indistinguishable in validation, so the pre-declared parsimony rule chose fixed equal weights. Separately, the single factor VOL (validation IC +0.110) and a static low-vol tilt (+0.165) score at least as high as any composite, so there is no evidence that combining factors adds anything.
- **Current state (as of {cur['date']} close):** Stage 04 tag BTC = **{cur['btc_direction_tag']}**, {cur['btc_structure']}; all Stage 02/03 strategy gates are closed, so this model supplies at most a *ranking* and creates no exposure. Evidence for the frozen model in Bearish tags is thin and mixed (see regime stability).

Labels: **[M]** measured here · **[H]** historical/descriptive · **[D]** derived/heuristic · **[U]** unavailable. Every IC below is a cross-sectional Spearman rank IC across **9 assets** (sd of the daily IC ≈ 0.35), so statistical power is low: one validation year has ≈{fv['eff_weeks']:.0f} effective weeks, SE of a mean IC ≈ {se_val:.3f}, and the minimum detectable mean IC (one-sided 5 %, 80 % power) ≈ {mde:.2f}.

## 1. Data, splits and protocol

{tbl(['Window','Signal dates','Role'],[['Train', f"{r['dates']['train'][0]} → {r['dates']['train'][1]} ({r['dates']['train'][2]} days)", 'fit weights/signs check; full-factor start 2022-05-01 because VALUE needs 365 days of history'],['Validation', f"{r['dates']['val'][0]} → {r['dates']['val'][1]} ({r['dates']['val'][2]} days)", 'compare/select candidates (not untouched)'],['Consumed legacy', f"{leg['window'][0]} → {leg['window'][1]} ({leg['window'][2]} days)", '`CONSUMED_LEGACY` — frozen model only, after freeze, descriptive']])}

- **Target** y = ln(C[t+7] / O[t+1]): signal at the close of day *t*, entry at the next open, 7-day horizon. Targets never cross a split boundary (last train signal 2024-11-09, last validation signal 2025-11-09). Horizons 1 and 30 days are reported as descriptive context only.
- **Data:** Binance spot USDT daily bars built from the Stage 02 hourly archive plus fresh klines (snapshot `{r['panel']['snapshot']}`; archive/fresh overlap matched exactly in Stage 04). A day is valid only with all 24 hourly bars; {r['panel']['missing_days']} days are missing for all nine assets. Coinmetrics community MVRV (8/9 assets) fetched per asset, hashes in the handoff. Survivor-selected cohort, single venue family, assumed (not observed) costs.
- **Pre-declared rules** (in `stage05/evaluate.py` docstring, written before any statistic): sign of each factor fixed a priori and never flipped by data; factor status SUPPORTED / EXPERIMENTAL_WEAK / EXCLUDED by the train+validation rule; weights fitted on train only; candidate chosen on validation as the lowest-complexity candidate not distinguishable from the best by a paired block bootstrap.
- **Inference:** circular block bootstrap, 14-day blocks, 10 000 reps, seed 20261118 (block-length sensitivity in §8). **Multiplicity:** {r['n_statistical_evaluations']} statistical evaluations were executed in `run_stage05.py` (including diagnostics); no correction is applied and none of the confidence intervals should be read as multiplicity-adjusted.

## A. Factor definitions and formulas
""")
for k in AK:
    s = FACTOR_SPEC[k]; ts, vs = fi["h7_train"][k], fi["h7_val"][k]
    A(f"""### {k} — {s['name']}  ·  status **{st[k]}**{'  (experimental, never in the composite)' if k=='VALUE_MVRV' else ''}
- **Formula:** `{s['formula']}`  ·  **Inputs:** {s['inputs']}  ·  **Lookback:** {s['lookback']}
- **Direction / normalisation:** hypothesised sign {s['sign']:+d}; {s['normalisation']}
- **Availability timing:** {s['timing']}
- **Missing values:** {s['missing']}
- **Economic rationale:** {s['rationale']}
- **Expected relationship to future returns:** {s['expected']}
- **Potential overlap:** {s['overlap']}
- **[M] Evidence (h=7):** train IC {ci(ts)}, hit-rate {ts['hit_rate']:.2f}; validation IC {ci(vs)}, hit-rate {vs['hit_rate']:.2f}; mean IC at h=1 / h=30 (train, val): {f3(fi['other_horizons_mean_ic']['1']['train'][k])}/{f3(fi['other_horizons_mean_ic']['30']['train'][k])}, {f3(fi['other_horizons_mean_ic']['1']['val'][k])}/{f3(fi['other_horizons_mean_ic']['30']['val'][k])}
""")
A(f"""**Why VALUE is a proxy.** No fundamental, cash-flow, token-supply or revenue data exist in this project for the nine assets, so relative valuation is **[U] not measured**. VALUE is a *price-only* long-horizon reversal statistic. The only value-like measured input is on-chain MVRV (community tier, 8/9 assets, no point-in-time vintages, realised-cap definitions differ across UTXO, account-based and token chains); its IC had the **opposite** sign to the hypothesis in train ({f3(fi['h7_train']['VALUE_MVRV']['mean'])}) and validation ({f3(fi['h7_val']['VALUE_MVRV']['mean'])}). The sign was not flipped; the factor is excluded.

Status rule outcome: SUPPORTED = {', '.join(k for k in AK if st[k]=='SUPPORTED') or 'none'}; EXPERIMENTAL_WEAK = {', '.join(k for k in AK if st[k]=='EXPERIMENTAL_WEAK') or 'none'}; EXCLUDED = {', '.join(k for k in AK if st[k]=='EXCLUDED') or 'none'}. *Qualification:* SUPPORTED means only "passed the pre-declared validation rule"; VOL's support is a static cohort tilt (§8).

![factor IC](stage05/factor_ic.png)

## B. Normalisation methodology

1. **Raw value** per asset from data ≤ t (formulas in A). **Orientation** by the a-priori sign, so higher z always means "hypothesised higher future return".
2. **Cross-sectional rank-normal transform** at each date t over the assets valid on that date: z = Φ⁻¹((rank − 0.5)/N_t), ties by average rank, clipped to ±2.0. Requires N_t ≥ 5 assets, else the row is NaN. Rank-normal is used because with N ≤ 9 means/variances are unstable and returns are heavy-tailed; it bounds the influence of any one asset and removes market-wide level shifts, so a factor is a *relative* statement.
3. **No time-series normalisation, no look-ahead:** the transform at date t uses only same-date values. [M] **Point-in-time truncation test** — factors recomputed from data truncated at five dates match the full-sample values exactly (max |diff| = {max(c['max_abs_diff'] for c in rob['point_in_time_truncation_test']['cases']):.0e}; passed = {rob['point_in_time_truncation_test']['passed']}). A deliberately leaked factor is detected by the harness (unit test), and a random-walk panel yields no spurious IC.
4. **Missing values:** never imputed. A factor missing for an asset-day is excluded from that asset's score and the remaining weights are re-normalised, provided at least min(3, #factors in the model) factors are present; otherwise the score is NaN. The frozen model has 3 factors, so all three are required.
5. **Execution latency:** delaying every score by an extra day leaves the frozen validation IC at {f3(rob['extra_1day_lag_val_ic_frozen'])} (vs {f3(fv['mean'])}).

## C. Factor dependence table
""")
M = dep["by_split"]["train"]["cs_rank_corr"]; Mv = dep["by_split"]["val"]["cs_rank_corr"]
A("**Average cross-sectional rank correlation of z-scores** (upper triangle = train, lower triangle = validation):\n")
A(tbl([""] + PR, [[a] + [("1" if a == b else (f"{M[b][a]:+.2f}" if PR.index(a) < PR.index(b) else f"{Mv[b][a]:+.2f}")) for b in PR] for a in PR]))
ic_c = dep["by_split"]["train"]["ic_series_corr"]
A("\n**Correlation of daily IC series** (train): " + "; ".join(f"{a}-{b} {ic_c[b][a]:+.2f}" for i, a in enumerate(PR) for b in PR[i + 1:] if abs(ic_c[b][a]) >= 0.2) + " (pairs with |ρ| ≥ 0.2 shown).\n")
A(tbl(["Factor", "VIF (train)", "rank autocorr lag 7", "top-3 retention lag 7", "residual IC train", "residual IC val", "IC train", "IC val"],
      [[k, f"{dep['by_split']['train']['vif'][k]:.2f}", f"{dep['persistence'][k]['rank_autocorr_lag7']:.2f}", f"{dep['persistence'][k]['top3_retention_lag7']:.2f}", f3(dep['residual_ic'][k]['train']), f3(dep['residual_ic'][k]['val']), f3(fi['h7_train'][k]['mean']), f3(fi['h7_val'][k]['mean'])] for k in PR]))
A(f"""
- **Redundancy [M]:** effective number of independent factors (participation ratio of the correlation eigenvalues) = {dep['by_split']['train']['effective_n_factors']:.2f} (train) / {dep['by_split']['val']['effective_n_factors']:.2f} (validation) out of 5; condition number {dep['by_split']['train']['condition_number']:.1f}. Largest overlaps: MOM–LIQ (0.48 train, 0.57 validation — the only near-redundant pair), TREND–VALUE (−0.39 train) and VOL–LIQ (−0.33 validation). The *incremental* information in MOM is nil after removing the others (residual IC ≈ 0).
- **Slowness [M]:** TREND, VALUE and VOL are almost static rankings (lag-7 rank autocorrelation 0.87–0.97), so a year of data holds far fewer independent observations than the {r['dates']['val'][2]} daily ICs suggest; MOM and LIQ turn over faster (0.63–0.68) and cost more to trade (§D).
- **Incremental information (residual IC):** only VOL keeps a clearly positive residual IC in both train and validation; VALUE's residual is small and positive in both (≈0.01 / 0.04); TREND's residual flips sign (+0.06 train, −0.02 validation); MOM and LIQ have ≈0 residual. [D] The practical dimension of the model is closer to 1–2 factors than 5.
""")
A("## D. Candidate weight allocations\n")
Wc = r["weights"]["candidates"]
rows = []
for n in ["EQ", "PRIOR", "EQ_TRAINPOS", "ICP", "NNLS"]:
    c = cand[n]; d = c["val_vs_best_diff"]
    rows.append([n, c["complexity"]] + [f"{Wc[n][k]:.2f}" for k in PR] + [ci(c["train"]), ci(c["val"]), "best" if d is None else f"{d['mean']:+.3f} [{d['lo95']:+.3f}, {d['hi95']:+.3f}]"])
c = cand["COND"]; d = c["val_vs_best_diff"]; rows.append(["COND", c["complexity"], "by regime", "", "", "", "", ci(c["train"]), ci(c["val"]), f"{d['mean']:+.3f} [{d['lo95']:+.3f}, {d['hi95']:+.3f}]" if d else "best"])
A(tbl(["Candidate", "Fitted params", "MOM", "TREND", "VOL", "LIQ", "VALUE", "Train IC", "Validation IC", "best − candidate (val, paired)"], rows))
A(f"""
- **EQ** = 0.2 each. **PRIOR** = initial hypothesis weights (MOM .30, TREND .25, VOL .15, LIQ .10, VALUE .20) — a hypothesis, *not* estimated. **EQ_TRAINPOS** = equal weight on factors with positive train IC (all five here, so identical to EQ). **ICP** = weights ∝ max(0, train mean IC). **NNLS** = non-negative ridge regression of the cross-sectionally rank-normal 7-day target on the five z-scores, λ = {r['weights']['nnls_cv']['chosen_lambda']:g} chosen by 5-fold purged blocked CV inside train (CV IC differences across λ are ≤ 0.002 — the choice is immaterial). **COND** = per-regime IC weights (BTC direction tag: Bullish / Bearish / Other) shrunk toward global with k = 250 days; regimes with < 60 train days fall back to global.
- **Train ICs of ICP, NNLS and COND are in-sample** (their weights were fitted on those days) and are shown only for completeness; only the validation column is a comparison.
- **Fitted on train only** ({r['weights']['estimation_sample'][0]} → {r['weights']['estimation_sample'][1]}, {r['weights']['estimation_sample'][2]} days ≈ {r['weights']['estimation_sample'][2]//7} effective weeks). With IC SE ≈ 0.03 per factor in train, differences between the weights ICP/NNLS give each factor are mostly within noise.
- **Regime-conditional weights (train):**

{tbl(['BTC regime','train days','MOM','TREND','VOL','LIQ','VALUE'],[[g, r['weights']['COND'][g]['_n']]+[f"{r['weights']['COND'][g][k]:.2f}" for k in PR] for g in ['Bullish','Bearish','Other']])}

### Selection and the frozen model
- Best validation mean IC: **{sel['best_by_val_mean_ic']}**. Candidates not distinguishable from it (paired block-bootstrap 95 % CI of the difference contains 0): **{', '.join(sel['comparable_to_best'])}**. By the parsimony rule the chosen candidate is **{sel['chosen']}** (fewest fitted parameters).
- **Conditional vs fixed weighting [M]:** COND validation IC {ci(cand['COND']['val'])} vs fixed EQ {ci(cand['EQ']['val'])}; the regime-conditional scheme is not distinguishable from fixed weights and adds ~10 fitted numbers. In validation the Bearish tag covers only {r['regime_day_counts']['val'].get('Bearish',0)} days, so conditional weights for the *current* regime cannot be validated from this window.
- **Freeze edit (disclosed):** after selection, factors with status EXCLUDED were set to weight 0 and the rest renormalised: **MOM {fw['MOM']:.3f}, VOL {fw['VOL']:.3f}, VALUE {fw['VALUE']:.3f}; TREND 0, LIQ 0, VALUE_MVRV 0**. This edit used validation information, so the frozen validation IC {ci(fv)} is **post-selection and optimistic**. MOM and VALUE (EXPERIMENTAL_WEAK) remain in the composite only so the forward test can decide on them (ablation plan, F). Sha256 of the frozen spec: `{fz['sha256']}`.

### Costs and turnover (top-3 long-only, weekly rebalance, 7 phase offsets, 15 bp per side — Stage 01 assumed fee 10 bp + adverse 5 bp, not observed)
""")
def prow(n, lab): 
    t, v = port[n]["train"], port[n]["val"]
    return [lab, bp(t["mean_excess_net_per_week"]), f"{t['one_way_turnover_per_rebalance']:.2f}", bp(v["mean_excess_net_per_week"]), f"[{bp(v['excess_net_lo95'])}, {bp(v['excess_net_hi95'])}]", f"{v['one_way_turnover_per_rebalance']:.2f}", ("n/a" if v["breakeven_cost_per_side_bp"] is None else f"{v['breakeven_cost_per_side_bp']:.0f}")]
A(tbl(["Score", "Train net excess vs EW9 (bp/wk)", "Train 1-way turnover", "Val net excess (bp/wk)", "Val 95 % CI", "Val 1-way turnover", "Val break-even cost (bp/side)"],
      [prow("FROZEN", "FROZEN (MOM+VOL+VALUE)")] + [prow(n, n) for n in ["EQ", "ICP", "NNLS", "COND"]] + [prow(k, k) for k in AK] + [["STATIC_LOWVOL_ARM"] + [bp(stat["train"]["mean_excess_net_per_week"]), f"{stat['train']['one_way_turnover_per_rebalance']:.2f}", bp(stat["val"]["mean_excess_net_per_week"]), f"[{bp(stat['val']['excess_net_lo95'])}, {bp(stat['val']['excess_net_hi95'])}]", f"{stat['val']['one_way_turnover_per_rebalance']:.2f}", "n/a"]]))
cs = r["cost_sensitivity_frozen_val_mean_excess_net_per_week"]
A(f"""
- Cost sensitivity of the frozen composite (validation net excess bp/wk): {', '.join(f"{k.replace('_per_side','')}: {v*1e4:+.1f}" for k, v in cs.items())}. Turnover is modest (≈0.1–0.4 one-way per weekly rebalance) so costs are not the binding problem; **estimation noise is** — every net-excess confidence interval in the table includes 0 except the static low-vol arm in validation, and that arm's *train* excess is {bp(stat['train']['mean_excess_net_per_week'])} bp/wk.
- **IC and the long-only top-3 portfolio disagree [M]:** Among the five primary factors VOL has the best IC in train and validation yet the *lowest* top-3 excess ({bp(port['VOL']['train']['mean_excess_net_per_week'])} / {bp(port['VOL']['val']['mean_excess_net_per_week'])} bp/wk). A positive IC can come from ordering the lower and middle ranks (avoiding the worst assets), which a long-only top-3 cannot monetise. Short-selling is disabled in Stage 01. Rank IC is therefore not a proxy for long-only profitability.

### Stability across historical regimes (BTC tags from the Stage 04 rule; point-in-time)
""")
def sb(nm, sp): 
    d = r["regime_stability"][nm]["direction"][sp]; return " · ".join(f"{g}: {('n/a' if v['mean_ic'] is None else f3(v['mean_ic']))} (n={v['n_days']})" for g, v in d.items())
lf = leg["frozen_by_btc_direction"]
A(tbl(["Score", "Train by BTC direction", "Validation by BTC direction", "Train 1st half / 2nd half"],
      [[nm, sb(nm, "train"), sb(nm, "val"), f"{f3(r['regime_stability'][nm]['train_halves']['first'])} / {f3(r['regime_stability'][nm]['train_halves']['second'])}"] for nm in ["FROZEN", "EQ", "VOL", "MOM", "TREND", "LIQ", "VALUE"]]))
A(f"""
- Consumed window (diagnostic, frozen model): {' · '.join(f"{g}: {f3(v['mean_ic'])} (n={v['n_days']})" for g, v in lf.items())}.
- **Interpretation [D]:** no factor is stable across regimes or halves; VOL's train IC fell from {f3(r['regime_stability']['VOL']['train_halves']['first'])} (first half) to {f3(r['regime_stability']['VOL']['train_halves']['second'])} (second half). Frozen-model IC is positive in train Bearish tags ({f3(r['regime_stability']['FROZEN']['direction']['train']['Bearish']['mean_ic'])}, n=265) but negative in validation Bearish (n=36) and in the consumed window (n={lf.get('Bearish',{}).get('n_days','?')}), and Bearish is the regime the market is in now; the evidence for this regime is therefore thin and mixed. The BTC tags themselves use the *uncalibrated* Stage 04 thresholds.

## E. Signal aggregation formula

For asset *i* on UTC day *t* (all inputs ≤ close of *t*):

```
z_{{k,i,t}} = clip( Φ⁻¹( (rank_i( s_k · x_{{k,i,t}} ) − 0.5) / N_t ), −2, +2 ),   N_t = #assets with x_{{k,·,t}} valid, require N_t ≥ 5
S_{{i,t}}    = Σ_k w_k · z_{{k,i,t}} / Σ_{{k available}} w_k          (NaN unless ≥ min(3, #model factors) factors available)
frozen v0.1.0-draft:  w_MOM = w_VOL = w_VALUE = 1/3 ;  w_TREND = w_LIQ = w_VALUE_MVRV = 0
s_MOM=+1, s_TREND=+1, s_VOL=−1, s_LIQ=+1, s_VALUE=−1, s_VALUE_MVRV=−1   (a-priori hypotheses; never flipped by data)
```

- **Use:** S ranks the nine assets. Research-evaluation mapping: hold the top 3 equally weighted, rebalance every 7 days, signal at close *t*, trade at O[t+1]. This mapping is for evaluation only.
- **Regime awareness:** (i) **Gate:** the model never creates exposure; absolute exposure remains governed by the Stage 02 entry rules, Stage 03 risk limits and the Stage 04 regime assessment (currently all gates closed). (ii) **Weights:** the frozen model uses *fixed* weights; the regime-conditional alternative (COND) is retained as a challenger because it was not distinguishable from fixed weights. (iii) **Reporting:** IC and returns are always stratified by BTC direction tag.
- **Current cross-section [M], {cur['date']} close (research record, not a signal):** BTC tag {cur['btc_direction_tag']} / {cur['btc_structure']} / {cur['btc_vol']}. Scores: {', '.join(f"{a} {('n/a' if v is None else f'{v:+.2f}')}" for a, v in sorted(cur['scores'].items(), key=lambda kv: -(kv[1] if kv[1] is not None else -9)))}. These are relative ranks; they say nothing about absolute direction. Per-factor z-scores are in `stage05_results.json`.

## F. Factor ablation plan (pre-specified for out-of-sample evaluation)

**Arms (defined now, before any forward data exist; A2 and A3 were added *after* the validation and robustness findings, so they are comparators, not prior hypotheses; family size 12 → Holm adjustment of one-sided p-values):**

{tbl(['Arm','Definition','Question'],[['A0','FROZEN: MOM+VOL+VALUE, 1/3 each','primary'],['A1','EQ5: all five primary factors, 0.2 each','does dropping TREND/LIQ matter?'],['A2','VOL only','is the composite better than its one supported factor?'],['A3','STATIC_LOWVOL: constant ranking by train-period vol','does VOL add anything beyond a fixed cohort tilt?'],['A4','EW9 buy-and-hold, weekly rebalanced (benchmark)','baseline'],['A5','COND: regime-conditional weights (train-fitted, frozen)','conditional vs fixed'],['A6–A8','A0 minus MOM / minus VOL / minus VALUE','marginal contribution'],['A9–A10','A0 plus TREND / plus LIQ (0.2 each, rest renormalised)','were exclusions right?'],['A11','A0 plus VALUE_MVRV 0.2 (experimental; 8 assets)','on-chain value']])}

- **Metrics:** mean daily rank IC (h=7) with 14-day-block and 60-day-block bootstrap CIs; net top-3 excess over EW9 at 15 bp and 30 bp per side (Stage 01 stress levels); turnover; IC and excess by BTC direction tag; leave-one-asset-out.
- **Decision rules:** retain a factor only if removing it lowers the OOS IC with a paired-bootstrap lower bound > 0 *and* the sign agrees in ≥ 2 of 3 sub-periods; A0 beats A3 only if the paired IC difference lower bound > 0; otherwise report "no incremental information beyond a static tilt". An arm with OOS IC ≤ 0 is closed, not re-tuned.
- **Required sample:** with the observed daily-IC sd ≈ {fv['sd']:.2f}, 26 forward weeks give SE ≈ {se26:.3f} and a minimum detectable IC ≈ {2.49*se26:.2f}; the realised validation IC (≈0.1) is *below* that, so a half-year forward test can only confirm large effects. Stage 01 requires ≥ 6 months and ≥ 100 trades else INCONCLUSIVE; an adjacent-asset cross-section (BNB, DOT, ATOM, BCH, …) would also enlarge N.
- **Data prerequisites:** independent second price source; delisted/failed assets (survivorship); execution venue, fee tier and depth; Binance/Bybit derivatives for any positioning factor (blocked in this container in Stage 04).

**Exploratory ablation on train/validation (hypothesis-generating only; each row after the first is an additional comparison):**

{tbl(['Variant','Weights','Train IC','Validation IC','Val net excess (bp/wk)'],[[k, ', '.join(f"{a} {b:.2f}" for a, b in v['weights'].items()), f3(v['train_ic']), f3(v['val_ic']), bp(v['val_net_excess_per_week'])] for k, v in r['ablation_exploratory'].items()])}

Reading: removing VOL collapses the validation IC (0.114 → {f3(r['ablation_exploratory']['drop_VOL']['val_ic'])}); removing MOM or VALUE does not hurt (VOL+VALUE {f3(r['ablation_exploratory']['drop_MOM']['val_ic'])}, MOM+VOL {f3(r['ablation_exploratory']['drop_VALUE']['val_ic'])}) — consistent with a one-factor model; adding MVRV lowers it ({f3(r['ablation_exploratory']['add_VALUE_MVRV_0.2']['val_ic'])}).

## 8. Robustness and diagnostics [M]

{tbl(['Test','Result'],[
['Block-length sensitivity, validation IC lower 95 % bound (14/30/60/90-day blocks)', 'VOL ' + '/'.join(f"{x['lo95']:+.3f}" for x in rob['block_length_sensitivity_val']['VOL']) + ' · FROZEN ' + '/'.join(f"{x['lo95']:+.3f}" for x in rob['block_length_sensitivity_val']['FROZEN']) + ' · EQ ' + '/'.join(f"{x['lo95']:+.3f}" for x in rob['block_length_sensitivity_val']['EQ'])],
['IC autocorrelation (validation, lag 1 / 7 / 14 / 30)', 'VOL ' + ' / '.join(f"{v:+.2f}" for v in rob['ic_autocorr']['VOL'].values()) + ' · FROZEN ' + ' / '.join(f"{v:+.2f}" for v in rob['ic_autocorr']['FROZEN'].values()) + ' (overlap of 7-day targets explains lag 1; blocks ≥ 14 days cover it)'],
['Static vs dynamic VOL (IC train / val)', f"static {f3(rob['VOL_static_vs_dynamic']['static_train_ic'])} / {f3(rob['VOL_static_vs_dynamic']['static_val_ic'])} · dynamic {f3(rob['VOL_static_vs_dynamic']['dynamic_train_ic'])} / {f3(rob['VOL_static_vs_dynamic']['dynamic_val_ic'])} · static ordering (low→high vol): {', '.join(rob['VOL_static_vs_dynamic']['static_asset_order_low_to_high_vol'])}; static consumed-window IC {f3(rob['STATIC_LOWVOL_ic']['legacy_DESCRIPTIVE'])} (descriptive)"],
['Leave-one-asset-out, validation IC range', f"VOL {min(v['VOL_val'] for v in rob['leave_one_asset_out'].values()):+.3f} … {max(v['VOL_val'] for v in rob['leave_one_asset_out'].values()):+.3f} · FROZEN {min(v['FROZEN_val'] for v in rob['leave_one_asset_out'].values()):+.3f} … {max(v['FROZEN_val'] for v in rob['leave_one_asset_out'].values()):+.3f} (no single asset drives the result; the effect is a cohort-wide ordering)"],
['Point-in-time truncation / lag', f"passed = {rob['point_in_time_truncation_test']['passed']}; extra 1-day lag IC {f3(rob['extra_1day_lag_val_ic_frozen'])}"]])}

**Consumed-window descriptive [H] (CONSUMED_LEGACY; frozen before access; no inference; no change afterwards):** IC — FROZEN {f3(leg['results']['FROZEN']['ic']['mean'])}, EQ {f3(leg['results']['EQ']['ic']['mean'])}, MOM-only {f3(leg['results']['MOM_only']['ic']['mean'])}; net top-3 excess bp/wk — FROZEN {bp(leg['results']['FROZEN']['portfolio']['mean_excess_net_per_week'])}, EQ {bp(leg['results']['EQ']['portfolio']['mean_excess_net_per_week'])}, MOM-only {bp(leg['results']['MOM_only']['portfolio']['mean_excess_net_per_week'])}. Per-factor IC (diagnostic): {', '.join(f"{k} {f3(v)}" for k, v in leg['per_factor_ic_DIAGNOSTIC_ONLY'].items())}.

## Limitations and unresolved items

- **Power:** nine assets, ≈51 effective weeks per year, slow factors → only large effects are detectable; multiple factors and candidates were examined ({r['n_statistical_evaluations']} evaluations), so isolated "significant" intervals may be chance.
- **Cohort:** survivor-selected nine assets; the dominant measured effect (large-cap over small-cap) is exactly what survivorship and a 2022–2025 alt-underperformance period would produce. No delisted assets, no second data source.
- **Development windows are not untouched** (Stage 02); the model's design was informed by Stage 01–04 knowledge and by the validation window (freeze edit). Only forward data can test it.
- **Thresholds:** BTC regime tags use uncalibrated Stage 04 thresholds; factor parameters (30/50/200/90/365-day windows, ±2 clip, top-3, 7-day horizon) are conventional single choices, not optimised and not sensitivity-tested.
- **[U] Unavailable:** token fundamentals, supply/unlock schedules, on-chain data for SOL, vintages of on-chain data, ETF/options/stablecoin flows, Binance/Bybit derivatives, realised execution costs.
- **Costs** are assumed (Stage 01); impact and spread vary with account size and venue (unspecified).
- Ledger: registered; **preregistration not frozen** (needs independent recorded review); `adjudicate.py` not run; no disposition is issued here.

## G. STAGE_05_HANDOFF

`docs/strategy-specs/STAGE_05_HANDOFF.json` (machine-readable: factor spec, normalisation, dependence, weights, frozen model + sha256, evidence hashes, ablation plan, requirements for out-of-sample evaluation, uncertainty). Reproduce: `PYTHONPATH=. scripts/lab python -m stage05.run_stage05` (≈1 min, deterministic; needs `data/s2grid.pkl`, a Stage 04 snapshot and `data/s5raw/`), then `-m stage05.make_chart` and `-m stage05.make_report`. Unit tests: `scripts/lab python -m unittest discover -s tests/stage05 -t .`

**Files:** `stage05_results.json`, `frozen_model.json`, `frozen_scores_daily.csv`, `factor_ic_daily_h7.csv`, `factor_ic.png` in `docs/strategy-specs/stage05/`.
""")
(D / "STAGE_05_FACTOR_MODEL_REPORT.md").write_text("\n".join(L))

# ---------------- handoff JSON
man = json.loads((ROOT / "data" / "s5raw" / "S5_MANIFEST.json").read_text())
ho = dict(handoff_type="STAGE_05_HANDOFF", schema_version="1.0.0", status="RESEARCH_SPEC_NOT_VALIDATED", created="2026-11-18",
  summary="Frozen candidate regime-aware multi-factor ranking model; predictive skill NOT demonstrated; ready for pre-registered forward / out-of-sample evaluation, not for deployment.",
  inputs={f: dict(sha256=sha(D / f)) for f in ["STAGE_01_HANDOFF.v2.json", "STAGE_02_HANDOFF.json", "STAGE_03_HANDOFF.json", "STAGE_04_HANDOFF.json"]},
  constraints=["research only; no orders, credentials or execution", "consumed window 2025-11-17..2026-11-17 is CONSUMED_LEGACY, never a holdout", "dispositions only from research/validation/adjudicate.py (not run)", "the model never creates exposure; Stage 02/03/04 gates govern"],
  ledger=dict(registered="hyp-cry-mfs-201@1", family="fam-crypto-stage05-v1", preregistration_frozen=False, adjudicate_py_run=False, reason="freeze needs independent recorded review"),
  provenance=dict(code_commit_at_run=r["git"]["head"], dirty_at_run=r["git"]["dirty"], panel_snapshot=r["panel"]["snapshot"], coinmetrics_files_sha256=man, results_sha256=sha(OUT / "stage05_results.json"), frozen_model_sha256=fz["sha256"], seed=20261118),
  data=dict(assets=r["panel"]["assets"], daily_panel_first=r["panel"]["first"], last_complete_day=r["panel"]["last_complete"], splits=r["dates"], consumed_legacy=leg["window"], target="ln(C[t+7]/O[t+1])", ic="daily cross-sectional Spearman, 9 assets"),
  factor_definitions=FACTOR_SPEC, factor_status=st, composite_members=[k for k, v in fw.items() if v > 0], experimental_factors_in_composite=[k for k in AK if st[k] == "EXPERIMENTAL_WEAK" and fw.get(k, 0) > 0], excluded_factors=[k for k in AK if st[k] == "EXCLUDED"], supported_by_rule=[k for k in AK if st[k] == "SUPPORTED"],
  normalisation=dict(method="cross-sectional rank-normal, clip +-2, N>=5, same-date only", missing="renormalise weights over available factors; require >=min(3,#factors); never impute", parameters=fz["params"]),
  dependence=dict(cs_rank_corr_train=dep["by_split"]["train"]["cs_rank_corr"], effective_n_factors=dep["by_split"]["train"]["effective_n_factors"], persistence=dep["persistence"], residual_ic=dep["residual_ic"]),
  candidate_weights=r["weights"], selection=sel, frozen_model=fz,
  results=dict(factor_ic_h7_train=fi["h7_train"], factor_ic_h7_val=fi["h7_val"], candidates=cand, portfolio_top3_weekly=port, cost_sensitivity=cs, regime_stability=r["regime_stability"], robustness=rob, ablation_exploratory=r["ablation_exploratory"],
               consumed_legacy_descriptive=leg, frozen_val_ic_post_selection_optimistic=fv),
  current_cross_section=cur,
  ablation_plan=dict(arms=["A0 FROZEN", "A1 EQ5", "A2 VOL-only", "A3 STATIC_LOWVOL", "A4 EW9 benchmark", "A5 COND", "A6-A8 A0 minus MOM/VOL/VALUE", "A9-A10 A0 plus TREND/LIQ", "A11 A0 plus VALUE_MVRV"], family_size=12, correction="Holm", block_days=[14, 60],
                     decision_rules=["retain a factor only if removal lowers OOS IC with paired-bootstrap lower bound > 0 and sign agrees in >=2 of 3 subperiods", "A0 must beat A3 with paired lower bound > 0 else no incremental information beyond a static tilt", "arms with OOS IC <= 0 are closed, not re-tuned"]),
  oos_requirements=dict(min_forward_weeks=26, min_trades="Stage 01: >=100 or INCONCLUSIVE", daily_ic_sd=fv["sd"], se_at_26_weeks=se26, min_detectable_ic_5pct_one_sided_80pct_power=2.49 * se26,
                        prerequisites=["independent second price source", "delisted/failed assets (survivorship)", "execution venue, fee tier, depth", "preregistration freeze after independent review", "adjacent-asset cross-section (BNB, DOT, ATOM, BCH)", "calibration of BTC regime tags"]),
  uncertainty=["no factor demonstrated stable across regimes or halves", "VOL support is a static cohort tilt, not dynamic", "frozen-model validation IC is post-selection optimistic", "consumed-window diagnostic adverse for frozen composite (MOM, VALUE negative)", "IC does not translate to long-only top-3 excess", "multiplicity uncorrected"],
  limitations=["9-asset survivor cohort; single data family", "assumed costs", "uncalibrated regime thresholds", "on-chain data community tier without vintages", "token fundamentals unavailable"],
  unresolved=["pre-register forward evaluation arms and freeze after independent review", "obtain survivorship-free and second-source data", "specify execution venue and costs", "decide whether to simplify to VOL-only/static tilt before forward test (this stage keeps the frozen A0 plus comparators)", "calibrate Stage 04 regime thresholds before using conditional weights"],
  n_statistical_evaluations=r["n_statistical_evaluations"])
(D / "STAGE_05_HANDOFF.json").write_text(json.dumps(ho, indent=1, default=str))
print("ok", len(L))
