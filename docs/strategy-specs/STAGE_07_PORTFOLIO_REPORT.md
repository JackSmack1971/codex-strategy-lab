# STAGE 07: Research portfolio construction and allocation

**Determination: NO ALLOCATION.** No capital is allocated: 100 % cash ($10,000 in cash, $0 at risk). The two eligible sleeves fail the predeclared validation gates (V1-V6, plan section 6). Four allocation schemes were still built and tested so that their consequences are on record; they are **conditional research specifications for paper/forward evaluation only**, not recommendations to trade. Research only: no orders, credentials or execution. Historical numbers are conditional on assumed costs (15 bp per side) and an unspecified venue; nothing here is a forecast.

Plan: `STAGE_07_ANALYSIS_PLAN.md` (committed before any run; amendment 1 disclosed below). Code: `stage07/`, tests `tests/stage07`. Results: `stage07/stage07_results.json`. Commit at report time: `6bb456c2`.

## 0. Evidence base, deviations and what this stage cannot show
* **Eligible sleeves only.** CRY-MOM-101 (Stage 03: eligible, paper-forward only) and CRY-VEX-103 (conditional, shadow/paper only, micro budget). CRY-REV-102 is excluded (Stage 02 REJECT). Frozen Stage 06 specification = unmodified Stage 02 baselines (Stage 06: KEEP BASELINE for both). Nine liquidity-gated cohort assets, spot, long-only, no leverage.
* **Aligned history is short.** Both sleeves overlap on 1,461 days (2021-11-17..2025-11-17); standalone trades in that window: MOM 141, VEX 984. The walk-forward out-of-sample span is 915 days (2023-05-17..2025-11-17, 5 anchored 6-month folds), **which excludes the 2022 bear market** (that year appears only in training and in the in-sample/stress tables). The 2025-11-17..2026-11-17 year is `CONSUMED_LEGACY`: reported descriptively, never a criterion.
* **"Out-of-sample" is relative to the weights only.** The whole 2021-2025 history informed Stages 01-06, so the sleeve rules themselves are not out-of-sample; only the weight estimates are.
* **Amendment 1 (disclosed).** Run 1 modelled schemes as segregated sub-books (plan section 2). It exposed cross-sleeve limit violations (1,149 hours of same-symbol overlap between sleeves; single-asset notional up to 33% of equity against a 15 % cap; run 1 also showed 7 simultaneous positions, which a later fix of the exposure-timing rule showed to be a one-hour measurement artifact), so run 2 uses one shared book with portfolio admission control (`stage07/shared.py`, asserted identical to `engine.simulate` under uniform parameters: 877 trades, max equity difference 0). The amendment was driven by the limit violations, but run-1 performance numbers were visible when it was written. Run 1 is preserved (`stage07_run1_segregated_results.json`). Later runs only added or corrected reporting (exposure tolerances, a segregated-book comparison, an exposure-timing fix, 2022 invested-time fields); no design parameter, weight formula or gate changed.
* **Counts.** 4 schemes (registered `fam-crypto-stage07-v1`), 2 sleeve-only and 3 passive benchmarks, 188 engine simulations, 5 folds, 10,000 bootstrap reps (14-day blocks, seed 20261118). No parameter was searched; weights come from three predeclared formulas. Holm correction over the 4 schemes.
* **Not independent of Stage 06.** Stage 06 found that both baselines lose on adjacent assets (MOM Sharpe -0.20, VEX -1.71); that result is carried into gate V1.

## Validation gates for any non-zero allocation (predeclared)
| gate | requirement | result |
|---|---|---|
| V1 | each funded sleeve validated: positive baseline Sharpe on adjacent-asset holdout | **FAIL** (MOM -0.20, VEX -1.71) |
| V2 | >= 6 months and >= 100 forward trades per sleeve | **FAIL** (0 forward trades; forward window starts 2026-11-18) |
| V3 | venue specified, observed fees/spreads/stop fills | **FAIL** (venue UNSPECIFIED; costs assumed) |
| V4 | preregistration frozen after independent review; `adjudicate.py` run | **FAIL** (not frozen, not run) |
| V5 | pooled OOS Sharpe 95 % lower bound > 0 and max DD within 15 % | **FAIL** for all four: Sharpe CI lower bounds EW -0.55, IV -0.43, RB -0.31, CONS -0.63; max DD EW -14.8%, IV -15.1%, RB -15.1%, CONS -12.6% (CONS inside 15 %, but its Sharpe bound is below 0) |
| V6 | Stage 04 gates currently permit entries | **FAIL** (2026-11-18 snapshot: MOM and VEX gates closed, 0 assets passing) |

## A. Proposed allocation matrix
**A1. Capital to deploy now: 100 % cash, 0 % risk assets.** Reason: V1-V6 not met (above); in addition both sleeves are dormant under the current Stage 04 snapshot.

**A2. Conditional research specification** (shares of the $10,000 as risk budgets; used only for paper/forward evaluation if the Stage 06/07 open items are resolved). Weights are capital/risk shares; risk per trade = weight x 1 % of equity.

| scheme | MOM | VEX | cash | risk/trade MOM / VEX | open-risk cap | max positions | single-asset / gross notional cap | weight source |
|---|---|---|---|---|---|---|---|---|
| EW | 50% | 50% | 0% | 0.50% / 0.50% | 3.0% | 6 | 15% / 60% | fixed 1/2, 1/2 |
| IV | 63.9% | 36.1% | 0% | 0.64% / 0.36% | 3.0% | 6 | 15% / 60% | 1 / daily vol of each sleeve (train) |
| RB | 73.3% | 26.7% | 0% | 0.73% / 0.27% | 3.0% | 6 | 15% / 60% | risk contributions 2/3, 1/3 (train covariance) |
| CONS | 50% | 25% | 25% | 0.50% / 0.25% | 1.5% | 3 | 15% / 40% | Stage 03 budgets, fixed |

Walk-forward weight ranges (MOM share, 5 folds): IV 62.4%-70.0%, RB 71.7%-77.9%. Full-DEV in-sample weights shown above (sigma_MOM 0.63%/day, sigma_VEX 1.11%/day, rho 0.26).

**A3. Paper-forward specification if forward testing is authorised: CONS.** The choice among schemes is **not evidence-driven**: no scheme differs from MOM alone (Holm-adjusted p = EW 1.00, IV 1.00, RB 1.00, CONS 1.00). CONS is selected on risk-limit grounds, not return: lowest 99 % ES (1.42%), shallowest OOS max drawdown (-12.6%), explicit Stage 03 caps, 25 % standing cash. Its OOS Sharpe (0.79) is below MOM alone (1.07). Whether VEX deserves even a paper budget is open (Stage 06: cost-fragile, loses on all adjacent assets); an MOM-only paper sleeve is an *unregistered* alternative and would need its own registration.

## B. Position-sizing rules (research specification; shared book)
1. Account: $10,000 USDT-quoted spot; no leverage, no shorts; cash is unallocated capital. Sleeve signals are the frozen Stage 02 baseline rules (rules_version 0.1.0); signals use completed bars only and fill at the next bar's open plus assumed adverse selection.
2. **Per-trade planned risk** = scheme weight x 1 % of frozen equity (EW 0.50 %, IV 0.64 %/0.36 %, RB 0.73 %/0.27 %, CONS 0.50 %/0.25 %; MOM/VEX). Never above 1 %.
3. **Budget** B = min(per-trade risk x E, open-risk cap x E - sum of reserved risk of open positions); skip if B <= 0. Open-risk cap 3 % (EW/IV/RB), 1.5 % (CONS). Reserved risk = quantity x initial stop distance.
4. **Quantity** q = lot-floor of min(B / stop distance, per-position notional cap x E / fill, available cash, 1 % of the asset's median 168-hour quote volume / fill, gross-notional room). Per-position cap 33 % (EW/IV/RB) or 13.3 % MOM / 10 % VEX (CONS); single-asset cap 15 %; gross cap 60 % (EW/IV/RB) or 40 % (CONS). Skip if notional < $10.
5. **Position limits:** one position per symbol across both sleeves; <= 6 positions (<= 3 for CONS); a one-bar re-entry cooldown per sleeve and symbol after any exit (Stage 02 engine rule); no entries in an asset failing the L1-L3 liquidity gates (simulated). The Stage 03 T8 condition (24-hour volume < 50 % of its 90-day median) is a proposed live rule that was **not** simulated.
6. **Gates:** no entries unless the Stage 04 sleeve gate is open; no new entries under any T1-T10 trigger.
7. Scaling to larger accounts changes participation and impact; sizes above the C5 account-size estimate need a new liquidity study.

## Portfolio results (shared book, baseline costs, walk-forward weights)
Pooled OOS, 915 days, folds chained (each a fresh book). Trades OOS (EW): MOM 157, VEX 604.

| series | total return | ann. vol | Sharpe [95 % block-bootstrap CI] | max DD | ES95 | ES99 [95 % CI] | worst day | dSharpe vs MOM-only (Holm p) |
|---|---|---|---|---|---|---|---|---|
| EW | 29.6% | 14.2% | 0.80 [-0.55, 2.00] | -14.8% | 1.46% | 2.28% [1.8%, 2.7%] | -3.1% | -0.27 (1.00) |
| IV | 39.8% | 14.9% | 0.97 [-0.43, 2.19] | -15.1% | 1.52% | 2.38% [2.0%, 2.8%] | -3.4% | -0.10 (1.00) |
| RB | 46.4% | 14.6% | 1.11 [-0.31, 2.35] | -15.1% | 1.49% | 2.36% [1.9%, 2.8%] | -3.5% | +0.04 (1.00) |
| CONS | 18.1% | 9.0% | 0.79 [-0.63, 2.03] | -12.6% | 0.90% | 1.42% [1.2%, 1.7%] | -1.9% | -0.29 (1.00) |
| MOM-ONLY | 41.4% | 13.7% | 1.07 [-0.42, 2.29] | -17.6% | 1.54% | 2.54% [2.0%, 2.9%] | -3.4% | - |
| VEX-ONLY | 35.0% | 22.6% | 0.64 [-0.67, 1.84] | -19.7% | 2.02% | 3.35% [2.7%, 3.8%] | -4.5% | - |
| EW-BH-9 | 188.5% | 67.0% | 0.97 | -52.6% | 7.98% | 12.11% [9.6%, 14.6%] | -18.4% | - |
| BTC-BH | 248.7% | 46.2% | 1.31 | -28.1% | 5.15% | 7.15% [6.2%, 7.9%] | -8.5% | - |
| CASH | 0.0% | 0.0% | - | 0.0% | 0.00% | 0.00% | 0.0% | - |

EW-BH-9 is a daily-rebalanced equal-weight of the nine assets; BTC-BH is buy-and-hold. They are passive references, not strategies. ES99 rests on only 10 tail days per series, so the interval is wide; the Gaussian ES99 (1.95% for EW) is close to the historical one here, but tails of the underlying assets are fat (worst cohort day -42.2%).

In-sample (weights estimated on all of DEV, 2021-11-17..2025-11-17, includes the 2022 bear market):

| scheme | total return | Sharpe | max DD | ES99 | MOM / VEX trades |
|---|---|---|---|---|---|
| EW | 17.4% | 0.37 | -16.1% | 2.23% | 190 / 928 |
| IV | 25.2% | 0.48 | -15.8% | 2.31% | 190 / 946 |
| RB | 30.7% | 0.58 | -15.8% | 2.31% | 190 / 969 |
| CONS | 12.1% | 0.39 | -12.1% | 1.37% | 139 / 738 |
| CRY-MOM-101 alone (own 1 % / 3 % book) | 33.6% | 0.66 | -17.6% | 2.55% | 141 |
| CRY-VEX-103 alone (own 1 % / 3 % book) | 14.8% | 0.27 | -26.8% | 3.18% | 984 |
| EW-BH-9 (passive) | -10.5% | 0.32 | -79.5% | 13.60% | - |

Consumed legacy year 2025-11-17..2026-11-17 (**descriptive only; weights from DEV; not a holdout**): EW -1.2% (Sharpe -0.06, max DD -8.1%); IV -1.0% (Sharpe -0.03, max DD -8.4%); RB -1.6% (Sharpe -0.09, max DD -8.7%); CONS 1.8% (Sharpe 0.28, max DD -4.4%); MOM alone -5.4%, VEX alone 6.7%; passive EW-BH-9 -49.4%.

## C. Correlation and concentration analysis
**C1. Cohort assets are one factor, not nine bets.** Daily returns 2021-11-17..2025-11-17:

| state | days | mean pairwise corr | first principal component share | effective independent bets |
|---|---|---|---|---|
| all days | 1461 | 0.67 | 71% | 1.9 of 9 |
| calm (excl. BTC worst decile) | 1314 | 0.58 | 63% | 2.4 of 9 |
| BTC worst-decile days | 147 | 0.63 | 67% | 2.1 of 9 |
| BTC > 20 % below its 90-day high | 349 | 0.78 | 80% | 1.5 of 9 |

Adding the four adjacent assets (BNB, DOT, ATOM, BCH) leaves it at 2.1 effective bets of 13 (mean pairwise 0.66). Rolling 30-day mean pairwise correlation: min 0.30, median 0.72, max 0.91; above the Stage 03 T9 threshold of 0.90 in 1.5% of weekly samples. On BTC's worst 5 % days 98% of asset-days are down. Lower-tail co-exceedance (both assets below their own 5th percentile, given one is) averages 0.62 versus 0.05 under independence. Picking different tokens does **not** diversify: in sustained BTC drawdowns the mean correlation is 0.78 and the effective number of bets 1.5; on single worst days the pairwise correlation is not higher (0.63; conditioning on BTC's own return compresses it) but nearly every asset still falls together.

**C2. Strategy return correlation.** MOM vs VEX standalone daily returns: 0.26 (all days), 0.44 (weekly), 0.46 when both are active (243 days), 0.19 on BTC worst-decile days. Low *daily* correlation is partly an artifact of inactivity: MOM is flat 71% of days, VEX 56%, both 43%. Each sleeve correlates with BTC at 0.36 (MOM) and 0.28 (VEX). The sleeves hold the **same asset at the same time** on 112 days (1,149 hours) when run as independent books; the shared book forbids this (one position per symbol), which changes the trade set (see sensitivity).

**C3. Regime diversification is weak.** Almost all profit of both sleeves comes from one state, BTC above its 200-day mean with low volatility:

| BTC regime (Stage 02 labels) | days | MOM sum of daily returns | VEX sum | EW scheme sum | BTC buy-hold sum |
|---|---|---|---|---|---|
| DOWN_HIGHVOL | 251 | -0.4% | -22.1% | -9.8% | 8.2% |
| DOWN_LOWVOL | 319 | -10.6% | 9.6% | -1.9% | -14.0% |
| UP_HIGHVOL | 108 | -1.1% | -0.6% | -0.2% | -10.2% |
| UP_LOWVOL | 783 | 43.9% | 35.6% | 31.3% | 115.9% |

Both sleeves are long-only trend/volatility-expansion rules on the same crypto beta; VEX loses in down/high-volatility regimes (the regime that matters for tail risk). Strategy-type diversification is therefore limited to *timing* (MOM 4H holds, VEX 1H holds), not to different return drivers.

**C4. Tail concentration** (worst 5 % of days, pooled OOS, share of the loss by sleeve; both sleeves negative on the same day in the last column):

| scheme | MOM share | VEX share | both negative |
|---|---|---|---|
| EW | 59% | 41% | 35% |
| IV | 67% | 33% | 33% |
| RB | 77% | 23% | 30% |
| CONS | 70% | 30% | 28% |

Equal capital is not equal risk: under EW, VEX supplies 71% of the volatility (in-sample estimate) while having the weakest evidence. Diversification ratio (sum w sigma / sigma_p): EW 1.27, IV 1.14, RB 1.11, CONS 1.39 (1.0 = no diversification benefit).

**C5. Liquidity and costs.** At $10,000 the 1 %-of-median-volume participation cap never binds. Estimated account size at which it would bind for 5 % of trades: EW $64,627, IV $64,299, RB $72,425, CONS $93,091 (linear scaling; market impact beyond the cap is not modelled; fills not observed).

| cost level (per side fee + adverse) | EW | IV | RB | CONS | MOM-only | VEX-only |
|---|---|---|---|---|---|---|
| 0x (0+0.0 bp) | 1.69 | 1.76 | 1.82 | 1.52 | 1.24 | 1.78 |
| 1x (10+5.0 bp) | 0.80 | 0.97 | 1.11 | 0.79 | 1.07 | 0.64 |
| 2x (20+10.0 bp) | 0.29 | 0.56 | 0.75 | 0.43 | 0.91 | -0.20 |
| 3x (30+15.0 bp) | -0.01 | 0.37 | 0.55 | 0.21 | 0.75 | -0.60 |
| stressA (20+10.0 bp) | 0.29 | 0.56 | 0.75 | 0.43 | 0.91 | -0.20 |
| stressB (10+20.0 bp) | 0.21 | 0.48 | 0.68 | 0.29 | 0.91 | -0.37 |

(Pooled OOS Sharpe, weights fixed at their base-cost estimates.) At 3x costs: EW -0.01, IV 0.37, RB 0.55, CONS 0.21, MOM-ONLY 0.75, VEX-ONLY -0.60. From 2x costs every scheme that holds VEX is below MOM alone, and VEX alone is non-positive. Costs are assumed, not observed.

## D. Stress scenarios
**Historical (in-sample series; weights from DEV; HISTORICAL, not forecasts).**

| scheme | worst day | worst 7 days (start) | worst 30 days (start) | LUNA 2022-05-01..06-30 | FTX 2022-11-01..12-15 | calendar 2022 |
|---|---|---|---|---|---|---|
| EW | -3.1% (2025-07-23) | -5.7% (2025-07-28) | -7.8% (2024-09-22) | -0.6% | -1.6% | -12.4% (max DD -15.7%) |
| IV | -3.4% (2024-03-05) | -5.9% (2025-07-28) | -7.9% (2024-09-22) | -0.6% | -2.4% | -13.8% (max DD -15.7%) |
| RB | -3.5% (2024-03-05) | -6.0% (2025-07-28) | -7.3% (2022-03-19) | -0.6% | -3.0% | -14.2% (max DD -15.6%) |
| CONS | -1.9% (2025-07-23) | -3.5% (2024-09-25) | -5.2% (2024-09-22) | -0.1% | -1.2% | -9.1% (max DD -11.1%) |
| EW-BH-9 (passive) | - | - | - | -49.8% | -19.7% | -73.0% |
| BTC-BH | - | - | - | -46.5% | -13.1% | -64.1% |

Calendar 2022 cost the schemes 12% (EW), 14% (RB) and 9% (CONS) with maximum drawdowns of 11%-16%, against 64% for BTC and 73% for the passive nine-asset basket. The sleeves were invested in only 27% of 2022 hours (mean gross notional 6%), so the smaller loss reflects closed trend gates, not diversification across assets. Losses inside the LUNA and FTX windows were small, but two events cannot separate luck from a systematic gate effect.

**Hypothetical shocks on the realised exposure timeline (arithmetic, HYPOTHETICAL, not measurements).**

| scheme | peak planned open risk (all stops hit as planned) | all open stops fill at -1.5R | at -2R | 20 % gap through every open position (peak) | each sleeve at expectancy -0.2R/trade (per year, uncompounded, MOM / VEX) |
|---|---|---|---|---|---|
| EW | 3.04% | 4.56% | 6.08% | 12.1% | -4.7% / -16.0% |
| IV | 3.08% | 4.61% | 6.15% | 12.1% | -5.5% / -14.1% |
| RB | 3.08% | 4.61% | 6.15% | 12.1% | -5.9% / -11.7% |
| CONS | 1.52% | 2.28% | 3.04% | 6.7% | -3.4% / -7.9% |

Because the cohort is one factor (C1), the correlated-gap case is the relevant one: a 20 % simultaneous gap through all open positions would cost 12.1% (EW) or 6.7% (CONS), about 4.0x the planned open risk. Stage 03 found stop-through behaviour cannot be observed from OHLC bars; it remains unquantified. Stress-cost rows are in section C5.

**Path dependence (estimation fragility).** The same weights give materially different OOS results depending on whether the sleeves run as independent sub-books or in one shared book: EW Sharpe 0.96 segregated vs 0.80 shared, IV Sharpe 1.09 segregated vs 0.97 shared, RB Sharpe 1.12 segregated vs 1.11 shared, CONS Sharpe 1.00 segregated vs 0.79 shared. In the last fold the shared book is negative for every scheme (EW -0.48, IV -0.29, RB -0.05, CONS -0.06) while the segregated approximation is positive (EW 0.69, IV 0.62, RB 0.56, CONS 0.48), because the shared book's admission order, the one-position-per-symbol rule and the larger combined position allowance change which signals are taken (in that fold MOM took 45 trades in the shared EW book versus 31 standalone, and the extra trades lost). A portfolio Sharpe difference of this size is within the noise of that choice.

## E. Risk budget utilization (shared book, in-sample timeline, hourly)

| scheme | open-risk cap | mean open risk (% of cap) | peak open risk | peak positions (limit) | peak single-asset notional (limit) | peak gross (limit) | share of hours invested | hours over limit by >5 % (risk / asset / gross) |
|---|---|---|---|---|---|---|---|---|
| EW | 3.0% | 0.45% (15%) | 3.04% | 6 (6) | 15.3% (15%) | 60.7% (60%) | 40% | 0 / 0 / 0 |
| IV | 3.0% | 0.50% (17%) | 3.08% | 6 (6) | 15.4% (15%) | 60.7% (60%) | 40% | 0 / 0 / 0 |
| RB | 3.0% | 0.52% (17%) | 3.08% | 6 (6) | 15.4% (15%) | 60.7% (60%) | 40% | 0 / 0 / 0 |
| CONS | 1.5% | 0.32% (21%) | 1.52% | 3 (3) | 13.4% (15%) | 33.4% (40%) | 40% | 0 / 0 / 0 |

Limits are enforced **at entry** on frozen equity; afterwards equity moves, so the measured ratios drift (e.g. open risk 3.0-3.1 % against a 3 % cap after a drawdown). Position counts never exceed the limit (peak 6 of 6; CONS 3 of 3). Average utilisation of the open-risk budget is low (15%-21%), because the sleeves are invested 40% of hours. Maximum planned risk per trade stays <= 0.73% (limit 1 %). **Segregated books cannot enforce the cross-sleeve rules** (run-1 design, corrected normalisation): EW 1,149 h of same-symbol overlap and peak single-asset notional 33% (cap 15 %); IV 1,149 h of same-symbol overlap and peak single-asset notional 33% (cap 15 %).

## F. Rebalancing and suspension rules (proposed, not validated)
**F1. Rebalancing.** Sleeve weights are inputs to *risk per trade*, not capital transfers between accounts; they are re-estimated at most **every 6 months** (the walk-forward cadence) from an expanding window of standalone sleeve returns. Between re-estimations they are frozen. Return-level model of capital rebalancing (in-sample, RB weights): Sharpe 0.63 daily, 0.64 monthly, 0.61 semi-annual, 0.60 never; capital transferred per year 82% (daily) vs 7% (semi-annual) of equity. The frequency changes Sharpe by < 0.04, so the low-turnover choice (semi-annual) is used. Rebalancing capital moves cash between sleeve budgets and is not market turnover. **Market turnover** is driven by the sleeves: MOM 35 trades/yr (13x capital traded per year), VEX 246 trades/yr (144x); scheme-level traded notional per year: EW 78x, IV 60x, RB 48x, CONS 42x of equity.

**F2. Suspension rules** (Stage 03 T1-T10 inherited unchanged; no new thresholds). Portfolio-level application of the drawdown/loss rules to the pooled OOS series (APPROXIMATE return-level overlay, thresholds not tuned):

| scheme | T1 >= 8 % DD episodes | T1 >= 12 % | T2 day loss >= 3 % days | T3 7-day loss >= 5 % | Sharpe plain -> overlay | max DD plain -> overlay |
|---|---|---|---|---|---|---|
| EW | 7 | 1 | 2 | 0 | 0.80 -> 0.71 | -14.8% -> -12.1% |
| IV | 6 | 0 | 2 | 2 | 0.97 -> 0.90 | -15.1% -> -11.9% |
| RB | 9 | 1 | 2 | 2 | 1.11 -> 1.01 | -15.1% -> -12.1% |
| CONS | 1 | 0 | 0 | 0 | 0.79 -> 0.74 | -12.6% -> -10.3% |

Rules in force for any paper/forward run: (1) **dormant while Stage 04 gates are closed** (V6) - capital stays cash; (2) T1: DD >= 8 % halve risk, >= 12 % no new entries, >= 15 % halt and independent review; (3) T2 day loss >= 3 %: no new entries until next UTC day; (4) T3 7-day loss >= 5 %: half risk until above -2 %; (5) T5 execution quality: pause if mean realised cost per side > 0.30 % over 20 fills; (6) T9: >= 2 sleeves long the same asset is impossible in the shared book (one position per symbol), and new entries pause while 30-day mean pairwise correlation > 0.90; (7) T10 forward-evidence stop at >= 100 trades per sleeve; (8) **sleeve suspension**: VEX is suspended if its realised cost per side exceeds 2x assumed or its forward expectancy <= -0.2R after 100 trades (its Sharpe is already <= 0 at 2x costs); MOM likewise at <= -0.2R. (9) Any change to weights outside the 6-month cadence, to caps, or to the sleeve rules requires a new version and registration.

## Sensitivity to estimation error
* **Weights.** Block-bootstrap of the DEV window: MOM share under IV 63.9% (5-95 %: 59.9%-68.1%); under RB 73.3% (69.8%-76.8%). Weights are stable to *sampling* error of sigma and rho because both sleeves have long histories of daily returns; they are not robust to *regime* error: the sleeve volatility ratio is dominated by VEX's down-regime losses.
* **Assumed correlation and volatility error.** Annualised volatility of the weights if the true sleeve correlation is 0 or 0.9 and VEX volatility is 30 % lower/higher than estimated: EW 10%-19%, RB 9%-14%, CONS 7%-13% (range by assumption). Risk-budgeted and conservative weights are less exposed to correlation error than EW.
* **Expected-return error.** Halving each sleeve's mean return halves every Sharpe (RB 1.12 -> 0.56); with a 100 % haircut the Sharpe is 0 by construction. With Sharpe 95 % intervals of width ~2.7, the data cannot distinguish a positive edge from none, and cannot rank the schemes.
* **Multiple testing.** Four schemes against MOM-only: Holm-adjusted p = EW 1.00, IV 1.00, RB 1.00, CONS 1.00; paired dSharpe 95 % intervals EW [-1.1, +0.6], IV [-0.8, +0.7], RB [-0.6, +0.7], CONS [-0.9, +0.4]. The best-looking scheme (RB) is also the one most dependent on in-sample weight tilt towards the better-evidenced sleeve.

## Limitations and unresolved concerns
* No untouched temporal holdout exists; the sleeve rules were designed on the same history used here. Stage 06's adjacent-asset holdout found both baselines negative; this stage does not repair that.
* The walk-forward span (2023-05..2025-11) is a mostly rising market and excludes 2022; in-sample Sharpe values (0.37-0.58) are far below the OOS ones (0.79-1.11) for that reason, not because of skill.
* Costs, spreads, stop fills, lot sizes and venue are assumed; stop-through slippage is not modelled beyond open-gap fills. The 20 % gap and -2R fill results are arithmetic on exposure, not observations.
* Few independent events: 141 MOM and 984 VEX trades in four years; ES99 rests on ~10 OOS tail days.
* Cohort is survivor-selected and nine assets behave as ~2 bets; a survivorship-free data source and exchange-failure scenarios (withdrawal freeze, depeg) are unquantified.
* Shared-book vs segregated results differ by more than the differences between schemes: portfolio-level admission order materially changes outcomes.
* Gate thresholds (V1-V6) and the weight formulas are judgement-based and uncalibrated; the CONS stop-trading overlay is an approximation of rules that act on intraday exposure.
* Preregistration is not frozen and `adjudicate.py` was not run; dispositions here are research assessments, not adjudicated decisions.

## G. Handoff
`STAGE_07_HANDOFF.json` (frozen allocation specification, constraints, evidence index, unresolved items). Figure: `stage07/stage07_portfolio.png`. Evidence: `stage07/stage07_results.json`, `oos_daily_returns.csv`, `stage07_suspension_overlay.json`, `stage07_run1_segregated_results.json`.
