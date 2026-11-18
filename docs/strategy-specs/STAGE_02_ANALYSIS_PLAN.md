# STAGE 02 analysis plan (frozen by git commit BEFORE any real-data performance run)

Status: committed before `stage02/run.py` was executed on real data. Mechanics were tested on synthetic data only
(`tests/stage02/test_engine.py`). Rules under test are STAGE_01_HANDOFF.v2.json rules_version 0.1.0-draft, unchanged.
Any change after seeing results requires a new rules_version and is reported as post-hoc.

## Interpretation choices made up front (the handoff was ambiguous)
1. **Books.** Primary inference = each strategy in its **own standalone $10,000 book** (all C4 caps apply within the book).
   Secondary = the **combined book** in handoff order (strategy ID, then symbol; max 3 positions and 3% risk shared).
2. **Windows.** Train 2021-11-17..2024-11-17, validation 2024-11-17..2025-11-17, final 2025-11-17..2026-11-17.
   Each window is a fresh $10,000 book; positions open at window end are force-closed at the last completed 1H close
   (costs applied, flagged). Final window is `CONSUMED_LEGACY`: descriptive only, never a pass criterion.
3. **Bars.** 4H strategies evaluate stops/targets on their own 4H bars; VEX on 1H bars. Missing 1H bar => 4H bar invalid;
   any invalid bar resets warm-up to 1000 consecutive valid bars (primary). Sensitivity: warm-up 400.
4. **Capital release.** A stop/target exit inside bar k frees cash, slot and symbol only at the END of bar k
   (conservative, avoids intrabar look-ahead on capital). Open-fill exits free at the open.
5. **Venue assumptions (ASSUMED, not observed):** lot step 1e-6 units, minimum notional 10 USDT, fee 0.001, adverse 0.0005
   per side (spread is inside the adverse term), no funding/borrow (spot long-only). Partial fills are NOT modelled beyond
   the 1%-of-median-hourly-quote-volume participation cap; the SMA20 limit target fills only on a strict high-through.
6. **Ratio estimand** = sum(net P&L)/sum(reserved initial risk) over closed trades.
7. **F1** validation window, baseline costs. **F2** same ratio under both stresses. **F3** one-sided 99.17% circular block
   bootstrap lower bound (14-day blocks by entry day, 10,000 reps, seed 20261118) on the validation window; the pooled
   train+validation bound is also reported. **F4** 1000 random-entry draws: for each real trade a random eligible bar of the
   same symbol in the same window (gates, gap guard, cost gate and, for REV, target structure applied; strategy trigger and trend
   context NOT applied), identical exit logic, sizing-neutral unit-R; real mean unit-R must exceed the 95th percentile.
   **F5** single-parameter neighbours listed in the handoff, validation ratio <=0 in half or more => fragile.
   **F6** drop best ceil(5%) trades by R. **F7** pooled train+validation closed trades < 100 => INCONCLUSIVE.
   **F8** positive ratio in at least 2 of 3 equal-length subperiods of train+validation.
   **MOM-F9** placebo: conditions 2-5 kept, trigger replaced by M<=0, M<0 signal-exit leg disabled (it would fire immediately).
   **REV-F9** same rule without C>SMA300. **REV-F10** sum of 5 worst losses > total gross profit (pooled train+validation).
   **VEX-F9** same rule without the volume condition. F9 comparisons use validation ratio.
8. **Labels.** REJECT: F1 fails, or pooled train+validation ratio <=0, or a strategy-specific falsifier (F9/F10) is triggered.
   PASS-CONDITIONAL: F1-F8, F9/F10 all satisfied with F7 not inconclusive. It is never unconditional because costs, venue
   filters and survivorship are unobserved. INVESTIGATE: everything else. `research/validation/adjudicate.py` was NOT run:
   the ledger freeze requires an independent recorded review that this session cannot supply; these labels are research
   assessments, not ledger dispositions.
9. **Benchmarks.** (a) equal-weight buy-and-hold of the 9-asset cohort (entry costs only), (b) BTC buy-and-hold,
   (c) BTC SMA200 daily long/cash (signal at UTC daily close, trade at next daily open, costs both sides).
10. **Regimes (attribution only).** BTC prior completed daily close vs its SMA200 x prior 30-day annualised vol vs 60%.
11. **Cost sensitivity.** baseline, handoff stress A (0.002/0.001), stress B (0.001/0.002), plus a grid of total round-trip
    cost multiples (0x, 0.5x, 1x, 2x, 3x of baseline).
12. **Not done / not possible:** historical venue filters, observed fees/spreads/depth, delisted assets (survivorship),
    funding/borrow (no shorts), USDT/USD conversion, independent data source cross-check.
