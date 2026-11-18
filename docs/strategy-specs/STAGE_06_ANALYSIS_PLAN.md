# STAGE 06 analysis plan (frozen by git commit BEFORE any real-data candidate run)

Status: committed before `stage06/run_dev.py` or `stage06/run_holdout.py` was executed. Mechanics were tested on synthetic data only
(`tests/stage06/test_stage06.py`, 14 tests). The Stage 02 engine is unchanged; the unmodified baseline is reproduced inside the runner
and asserted against the Stage 02 handoff before any candidate is evaluated. Research only: no orders, credentials or execution.

## 0. What this stage can and cannot establish
* **No untouched temporal holdout exists.** 2025-11-17..2026-11-17 is `CONSUMED_LEGACY`; 2021-11-17..2025-11-17 was seen in Stage 02-05.
  The development walk-forward therefore measures *selection-procedure overfitting within seen history*, not true out-of-sample skill.
* The only never-run data are the **adjacent assets BNB, DOT, ATOM, BCH** (Stage 01 `confirmation_options`). They test asset-selection
  overfitting only; they share calendar time and BTC beta with the cohort, so they are **not independent of regime**. Their data were
  fetched and audited for gaps only; no strategy has been run on them. They are touched once, for finalists and the baseline, after the freeze.
* Costs are assumed (fee 0.001 + adverse 0.0005 per side), the venue is UNSPECIFIED, the cohort is survivor-selected.

## 1. Eligibility
| strategy | Stage 02 | Stage 03 | Stage 06 |
|---|---|---|---|
| CRY-MOM-101 | INVESTIGATE | ELIGIBLE_CONTINUED_RESEARCH_PAPER_FORWARD_ONLY | tuned |
| CRY-VEX-103 | INVESTIGATE | CONDITIONAL_SHADOW_PAPER_ONLY | tuned |
| CRY-REV-102 | REJECT | NOT_ELIGIBLE_SHADOW_ONLY | **excluded** (tuning a rejected rule only adds trials) |

Baseline = `engine.DEFAULTS` (rules_version 0.1.0) with baseline costs. Stage 03 risk budgets (half size) rescale P&L but do not change entry
signals; Stage 06 evaluates at the Stage 01 sizing so that results are comparable to the preserved Stage 02 numbers.

## 2. Candidate changes: one family at a time around the baseline (71 configurations incl. 2 baselines)
Ranges are one grid step either side of the Stage 01 value (Stage 01 `neighbours` where given). Each family is varied with all others at baseline.
| family | CRY-MOM-101 (4H) | CRY-VEX-103 (1H) |
|---|---|---|
| PARAM | lookback {150,**180**,210} x thr {1.0,**1.25**,1.5} (8 new) | donch {36,**48**,72} x tr_k {1.5,**1.8**,2.2} (8) |
| ENTRY_CONFIRM | trigger on K consecutive bars, K {**1**,2,3} (2) | ibs_min {0.65,**0.75**,0.85} (2) |
| VOL_FILTER | 7d/30d 4H-return vol ratio <= {off,1.5,1.25} (2) | ATR24[1]/median_30d(ATR24) <= {off,1.0,0.8} (2) |
| TREND_FILTER | ext = C/SMA300 <= {1.20,**1.30**,1.45} (2) | extra 4H trend: C4 > SMA{off,100,200} (2) |
| LIQ_FILTER | 30d median daily quote vol >= {**20M**,50M,100M} (2) | vol_k {1.5,**2.0**,2.5} x weekend entries excluded {**no**,yes} (5) |
| STOP | stop_k {2.5,**3.0**,3.5} x trail_k {3.0,**3.5**,4.0} (8) | stop_k {1.5,**2.0**,2.5} x trail_k {2.0,**2.5**,3.0} (8) |
| EXIT_CONFIRM | signal exit needs N consecutive bars, N {**1**,2,3} (2) | fail_bars {3,**6**,12} (2) |
| FACTOR_OVERLAY | Stage 05 composite z at last completed day >= tau: {off, EQ3@0, PRIOR5@0, VOLONLY@0, EQ3@0.5} (4) | same (4) |
| REGIME_ACTIVATION | BTC (Stage 04/05 tags, last completed day): {off, direction != Bearish, ADX structure Trending, vol != HighVol} (3) | same (3) |
Totals: MOM 33 non-baseline + baseline = 34; VEX 36 + baseline = 37; 69 candidates + 2 baselines = **71 configurations**.
Bold = baseline value. Where an external daily value is unavailable (NA tag, composite not yet defined before 2022-05-01) the baseline rule
applies (no imputation, no blocking). EQ3 = Stage 05 frozen weights (MOM, VOL, VALUE = 1/3); PRIOR5 = Stage 05 hypothesis weights; VOLONLY = VOL.
Weights are **not re-estimated** here: Stage 05 already fixed them. Factor overlays cannot be run on the holdout (cross-section of 4 assets < min 5).

## 3. Windows
* DEV = 2021-11-17..2025-11-17. Folds (anchored): train = [2021-11-17, T_k); test = 6-month block, T_k = 2023-05-17, 2023-11-17, 2024-05-17,
  2024-11-17, 2025-05-17 (test ends 2023-11-17 ... 2025-11-17). Every window is a fresh $10,000 book with positions force-closed at the window
  end (Stage 02 convention). The full DEV window is simulated once per configuration for neighbour stability, PBO and the reality check.
* HOLDOUT (adjacent assets) = DEV and CONSUMED windows on BNB, DOT, ATOM, BCH with the same gates (L1-L3), BTC from the cohort data for the MOM filter.
* CONSUMED_LEGACY 2025-11-17..2026-11-17: descriptive only, reported after the freeze, never a criterion.

## 4. Selection (TRAIN ONLY, per fold, per family)
dS(c) = Sharpe_train(c) - Sharpe_train(baseline), same window, daily-equity Sharpe, baseline costs in every trial.
Constraints on c itself: trades >= 0.75 x baseline; maxDD >= baseline maxDD - 2pp; turnover/yr <= 1.25 x baseline.
Score = mean dS over c and its grid neighbours (|step| <= 1 on ordered dims, same categorical values); categorical-only families use dS itself.
Choose the best-scoring constrained c. **Switch from baseline only if score >= 0.10 (ordered) / 0.20 (categorical)**; else keep baseline for that fold.
The highest-in-sample-Sharpe configuration is never chosen on that basis alone.

## 5. Gates on pooled out-of-sample folds (finalist = all pass)
G1 pooled OOS dSharpe >= +0.15. G2 worst-fold maxDD not worse than baseline by > 1pp. G3 OOS trades >= 0.75 x baseline. G4 OOS turnover <= 1.25 x baseline.
G5 stability: the modal chosen config is chosen (non-baseline) in >= 3 of 5 folds. G6 cost robustness: modal config minus baseline pooled OOS Sharpe > 0 under
stress A (fee .002, adverse .001) and stress B (fee .001, adverse .002). G7 neighbour stability: modal config dSharpe > 0 on full DEV and >= 2/3 of its grid neighbours' full-DEV dSharpe > 0.
Thresholds are judgement-based and uncalibrated.

## 6. Multiple testing and selection bias (reported for every family and strategy)
* Configurations tested: 71 configs x (5 train + 5 test + 1 DEV + 1 CONSUMED) windows; 90 walk-forward selection decisions (2 strategies x 9 families x 5 folds).
* Paired circular block bootstrap (14-day blocks, 10,000 reps, seed 20261118) of pooled OOS daily-return difference, one-sided p per family, **Holm correction over the 18 families**.
* White reality check (same bootstrap) over all candidate-minus-baseline DEV daily differences per strategy; probability of backtest overfitting (CSCV, S=8, 70 splits) per strategy.
* Train -> unseen degradation: mean in-sample dS of the chosen config vs its OOS dS.

## 7. Determination rule (per family, then per strategy)
* **REJECT**: any of G1-G7 fails (no holdout access for it), or holdout inconsistent.
* **ACCEPT_CANDIDATE**: finalist AND Holm-adjusted p < 0.05 AND holdout consistent (dSharpe >= 0, trades >= 0.75 x, maxDD within 1pp of baseline) AND testable on the holdout.
* **UNVERIFIED_HYPOTHESIS**: finalist that is not ACCEPT (significance, holdout or testability missing). Requires forward paper evaluation.
* Strategy determination: **KEEP BASELINE** unless at least one family is ACCEPT_CANDIDATE. If >= 2 families of one strategy are finalists, one COMBO (union of modal
  configs, no re-selection) is evaluated on the same folds as one extra counted trial.
* Dispositions are research assessments; `research/validation/adjudicate.py` is NOT run (needs an independent recorded review that this session cannot supply).

## 8. Holdout protocol (single shot)
After `stage06_dev_results.json` and `frozen_candidates.json` are committed, `run_holdout.py` (a) refuses to run on a dirty tree, (b) runs the baseline and the finalists once
on BNB/DOT/ATOM/BCH, (c) records the frozen-file sha256. Nothing is changed afterwards; if the holdout result is unwelcome the determination stands.
