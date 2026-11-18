# STAGE 07 analysis plan (frozen by git commit BEFORE any Stage 07 run)

Research only: no orders, credentials or execution. The Stage 02 engine is unchanged; the Stage 02 baselines (`engine.DEFAULTS`) are the
frozen Stage 06 specifications (Stage 06: KEEP BASELINE for both). Mechanics are tested on synthetic data first (`tests/stage07`).

## 0. Question and default answer
Can a capital allocation across the eligible sleeves be justified by the available evidence? **Default = NO ALLOCATION** (100 % cash,
paper/shadow only) unless every validation gate V1-V6 below passes. The allocation matrix is still computed and reported as a
*conditional research specification* so that the consequences of each scheme are visible; it is never a recommendation to deploy capital.

## 1. Eligible sleeves and universe
| sleeve | Stage 02 | Stage 03 | Stage 06 | in Stage 07 |
|---|---|---|---|---|
| CRY-MOM-101 | INVESTIGATE | ELIGIBLE paper-forward only | KEEP BASELINE (baseline fails adjacent-asset holdout) | eligible sleeve |
| CRY-VEX-103 | INVESTIGATE | CONDITIONAL shadow/paper only | KEEP BASELINE; cost-fragile; fails holdout | eligible sleeve (micro budget) |
| CRY-REV-102 | REJECT | NOT ELIGIBLE | not evaluated | **excluded**, weight 0 |
Permitted assets: the nine liquidity-gated cohort assets BTC ETH SOL XRP ADA LINK AVAX DOGE LTC (spot, USDT quote, long-only, no leverage).
BNB DOT ATOM BCH are used for the correlation study only (descriptive; never traded here).

## 2. Constraints (user defaults, tightened by validated Stage 03 caps where stricter)
$10,000; risk/trade <= 1 %; simultaneous open risk <= 3 %; spot; no leverage; no shorts; cash allowed. A scheme is a vector of
**capital weights** w = (w_MOM, w_VEX, cash = 1 - sum). Each sleeve runs its frozen Stage 02 rule in a segregated sub-book of w_i x $10,000
(risk/trade = 1 % of the sub-book = w_i % of total, open-risk cap 3 % x w_i, 3 positions per sleeve, notional cap per position 33 % of the sub-book).
Portfolio risk/trade <= max_i w_i % <= 1 % and portfolio open risk <= sum_i 3 w_i % <= 3 %: both default limits hold by construction when sum(w) <= 1.
Cross-sleeve rules that segregated books cannot enforce (one position per symbol across sleeves, 15 % single-asset notional, 40 % gross
notional, <= 3 positions in a stressed correlation state) are **measured** on the realised combined timeline and reported as breach frequencies;
the Stage 03 T9 rule is the proposed enforcement.
The segregated-book simulation is a linear-in-capital approximation of a shared book (lots, minimum notional and the shared slot count are second order).

## 3. Schemes (predeclared; no others are tried)
* **EW**: w = (1/2, 1/2, 0).
* **IV**: w_i proportional to 1 / sigma_i, sum = 1; sigma_i = standard deviation of the sleeve's w = 1 daily returns on the estimation window.
* **RB**: risk-budgeted: weights such that the contribution to portfolio volatility is 2/3 MOM, 1/3 VEX (Stage 03 evidence ratio 0.5 : 0.25), sum = 1; sigma and correlation estimated on the estimation window.
* **CONS**: conservative cash-inclusive = Stage 03 risk budgets: w = (0.50, 0.25, cash 0.25), per-position notional caps 13.3 % (MOM) and 10 % (VEX) of total equity, plus the Stage 03 stop-trading rules T1-T10 (descriptive overlay).
* Benchmarks: 100 % cash; MOM alone (w=1); VEX alone (w=1); passive equal-weight buy-and-hold of the nine assets; BTC buy-and-hold.
A scheme with a weight computed from data is estimated on training data only.

## 4. Windows
Aligned history = 2021-11-17 .. 2025-11-17 (DEV, 1,461 days, both sleeves, baseline costs f=0.001 + s=0.0005 per side, assumed).
* Walk-forward (out-of-sample for the weights): anchored; weights for test fold k estimated on [2021-11-17, T_k); folds = 6-month blocks from 2023-05-17 to 2025-11-17 (5 folds); every fold a fresh $10,000 book force-closed at its end (Stage 06 convention).
* In-sample table: weights estimated on all of DEV and evaluated on DEV (labelled IN-SAMPLE).
* 2025-11-17 .. 2026-11-17 is `CONSUMED_LEGACY`: reported descriptively after the freeze; never a criterion and never an untouched holdout.
* Insufficient-overlap disclosure: both sleeves together have only 4 years, ~170 MOM and ~1,100 VEX trades; the sleeve return correlation and the tail are estimated from few events.

## 5. Evaluation (all executed, none asserted)
1. Asset correlations: full-sample, stressed (BTC lowest-decile days; BTC drawdown > 20 % from rolling 90d high), rolling 30d mean pairwise, tail co-exceedance (both below own 5th percentile), PCA first-component share, effective number of independent bets = (sum eigenvalues)^2 / sum eigenvalues^2.
2. Sleeve return correlations: daily and weekly, full / BTC-stress days / days both sleeves in the market; same-symbol overlapping position days.
3. Portfolio volatility, CAGR, Sharpe, Sortino, max drawdown, time under water for every scheme (walk-forward pooled and in-sample).
4. Tail concentration: share of the worst 5 % days attributable to each sleeve and to each asset; co-loss frequency.
5. Expected shortfall: historical 95 % / 99 % one-day ES with 14-day circular block-bootstrap CI (10,000 reps, seed 20261118); 7-day ES; Gaussian vs historical.
6. Position and exposure limits: peak and mean open risk, gross notional, single-asset notional, positions, same-symbol overlap, from the realised timeline.
7. Costs and liquidity: costs x0, x1, x2, x3, stress A (0.002, 0.001), stress B (0.001, 0.002); participation vs median 168h quote volume; account-size capacity (the engine caps participation at 1 %).
8. Rebalancing and turnover: annual traded notional / equity per scheme; weights are re-estimated at most every 6 months; the cost of a monthly vs semi-annual vs never rebalance of sleeve capital is compared.
9. Diversification across strategy types and regimes: sleeve P&L by Stage 04 BTC regime tag (direction, ADX structure, volatility), share of days in cash, diversification ratio, risk contribution.
10. Sensitivity to estimation error: block-bootstrap of the estimation window -> distribution of IV / RB weights; grid over assumed sleeve correlation (0, 0.25, 0.5, 0.75, 0.9) and volatility error (+/-30 %); haircut of sleeve expected return; paired block bootstrap (14d, 10,000 reps) of scheme-minus-MOM-only Sharpe.
Stress scenarios (D): historical worst 7/30-day windows; 2022-05 (LUNA) and 2022-11 (FTX) windows; costs x3; HYPOTHETICAL 20 % gap through all open stops simultaneously; HYPOTHETICAL stop fills at -2R; correlation-to-1 (all open positions lose together); sleeve-failure (each sleeve expectancy forced to -0.2R per trade).

## 6. Validation gates for any non-zero capital allocation (predeclared)
All must pass, otherwise the determination is **NO ALLOCATION** (capital = 0, 100 % cash; paper-forward specification only):
* V1 each sleeve with weight > 0 is independently validated: its Stage 06 baseline shows positive Sharpe on the adjacent-asset holdout and a Stage 06 ACCEPT or a positive forward paper record.
* V2 forward evidence: >= 6 months and >= 100 forward trades per sleeve after 2026-11-18.
* V3 execution venue specified and observed fees / spreads / stop-fill behaviour available.
* V4 preregistration frozen after independent review and `adjudicate.py` run.
* V5 the pooled walk-forward portfolio Sharpe for the chosen scheme is > 0 with a block-bootstrap 95 % lower bound > 0, and max drawdown within the Stage 03 stop thresholds (15 %).
* V6 the Stage 04 gates currently permit entries (otherwise the allocation is dormant: capital stays in cash until they open).
Thresholds are judgement-based and uncalibrated.

## 7. Multiple testing
Four schemes + 2 sleeve-only benchmarks are compared; scheme-vs-benchmark p-values are Holm-adjusted over the 4 schemes. Weight estimates are never tuned on test folds.
Dispositions are research assessments; `adjudicate.py` is NOT run (needs an independent recorded review).
