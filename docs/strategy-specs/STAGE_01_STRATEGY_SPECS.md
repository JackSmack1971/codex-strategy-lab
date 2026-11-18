# Stage 01 v2 — three new crypto strategy specifications (DRAFT, not frozen)

Date: 2026-11-18. Status: **specification only. No backtest has been run. No performance, win rate,
Sharpe or profitability is claimed or implied.** Spec version `0.1.0` of each strategy becomes
binding only when preregistered (frozen) through the research workbench.

New IDs, deliberately different in mechanism from the legacy `CRY-TF-001`, `CRY-MR-002`, `CRY-BO-003`
(EMA stack / 1H z-score with ER filter / BB-width squeeze + 20-bar high), which stay untouched.

| ID | Family | Signal TF | One-line mechanism |
|---|---|---|---|
| `CRY-MOM-101` | Trend / momentum | 4H | Volatility-normalised 30-day return t-stat >= 1.25, above rising 50-day SMA |
| `CRY-REV-102` | Mean reversion | 4H | RSI(3) capitulation (>=2 ATR 3-bar drop) inside a long-term uptrend, target = SMA20 |
| `CRY-VEX-103` | Breakout / vol expansion | 1H (+4H context) | 48-bar high break on a >=1.8x-ATR true-range thrust with >=2x volume |

---

## 0. Evidence ledger

### VERIFIED (probed 2026-11-18 from this container; point-in-time observations)
- Binance.com public API returned **HTTP 451** ("restricted location") here. Binance.com instrument status and filters could **not** be checked from this environment.
- `data.binance.vision` answered HTTP 200 (HEAD) for the monthly **1H spot kline** zip of BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, ADAUSDT, LINKUSDT, AVAXUSDT, DOGEUSDT, LTCUSDT, BNBUSDT for each of 2021-05, 2021-11, 2026-10. This shows file existence at those three months only. Checksums and continuity are not verified.
- Binance.US `exchangeInfo` answered HTTP 200 (contents not reviewed).
- Coinbase Exchange `/products` returned 847 products. BTC, ETH, SOL, XRP, ADA, LINK, AVAX, DOGE, LTC, DOT, BCH, ATOM `-USD` all showed `status=online`, `trading_disabled=false`. `BTC-USD` base increment 1e-8, quote increment 0.01.
- Coinbase 24h stats snapshot, volume x last price, USD millions (single moment, not a distribution): BTC ~617, ETH ~207, SOL ~82, XRP ~85, ADA ~9.3, LINK ~7.1, AVAX ~4.4, DOGE ~5.6, LTC ~5.5. Against gate L2 below (10M/24h) the last five would fail on Coinbase at that moment.
- Coinbase daily candles returned for [2021-01-01, 2021-10-01): ETH 274, LINK 274, LTC 274, ADA 198 (from 2021-03-18), DOGE 121 (from 2021-06-03), SOL 107 (from 2021-06-17), XRP **19** (sparse), AVAX **2** (from 2021-09-30). So Coinbase history does **not** span 5 years for every alternative. `BTC-USD` daily candles exist from at least 2016-04.
- Kraken public 1H OHLC began at ~2026-10-19 in the response I saw (recent window only). It is not a 5-year source via that endpoint.
- Repo: legacy handoff `STAGE_01_HANDOFF.json` (Binance.com spot, BTC/ETH/SOL) exists. The 2025-11-17 to 2026-11-17 window is `CONSUMED_LEGACY`. I did **not** read `REPORT.md` or `results/`, so no parameter below was chosen from those results.

### RESEARCH HYPOTHESES (unverified; each strategy section states its own)
All behavioural claims, regime suitability and failure mechanisms are hypotheses. Parameter values are conventional round numbers, not fitted. I cannot prove they are independent of my general knowledge of crypto history, so no window is treated as untouched (section D).

### UNAVAILABLE (must be resolved or disclosed; never imputed)
- **Trading venue is unspecified** (`[Specify]`), and user eligibility is unresolved. Binance.com is not reachable from here.
- Historical symbol trading status, lot/tick/min-notional filters, fee tiers, spreads and depth.
- Historical USDT/USD conversion. Funding, borrow and margin data (needed for any short variant).
- Data on delisted or failed assets, so any alt cohort is survivorship-biased.
- Expected trade counts, ATR levels, regime frequencies and every performance statistic.

---

## C. Shared conventions (apply to all three strategies)

**C1 Bars and time.** Base series: 1H spot OHLCV with quote volume, UTC, bar timestamp = open time. A 4H bar aggregates four 1H bars at 00/04/08/12/16/20 UTC (O = first open, H = max, L = min, C = last close, Q = sum of quote volume). A 4H bar missing any 1H bar is invalid. Any invalid or missing bar resets indicator warm-up. No forward fill. Warm-up: 1000 bars per uninterrupted segment. Signals use completed bars only. `x[k]` = value k completed bars before the current completed bar (`x[0]` = current). `O1` = open of the bar after the signal bar.

**C2 Indicator definitions.**
- `SMA_n(x)` = arithmetic mean of the last n values including the current bar.
- `TR` = max(H-L, |H-C[1]|, |L-C[1]|). `ATR_n` is Wilder: the first value is the mean of the first n TRs, then `ATR = ((n-1)*ATR[1] + TR)/n`.
- `RSI_n` is Wilder: the first average gain and loss are simple means of the first n changes, then `avg = ((n-1)*avg[1] + x)/n`. `RSI = 100 - 100/(1+avg_gain/avg_loss)`. If avg_loss = 0 then RSI = 100. If both are 0 then RSI = 50.
- `std` = sample standard deviation (ddof = 1). `median` = mean of the two middle values for even n.
- `IBS` = (C-L)/(H-L). If H = L, any IBS condition is false.
- `HC` = highest close since entry, including the entry bar's close once that bar completes.

**C3 Execution model (baseline).** Signal at completed bar close, market entry at next bar open. Baseline costs: fee f = 0.0010 and adverse slippage s = 0.0005 per side. These are **assumed, not observed**, and are the inherited values from the legacy preregistration. Stress scenarios: (f 0.0020, s 0.0010) and (f 0.0010, s 0.0020).
- Buy fill = O1*(1+s). Sell fill = price*(1-s). Fee = f * fill notional.
- Stop: a sell-stop at S triggers if bar L <= S. Fill = min(S, bar open)*(1-s). The initial stop is live from the entry bar itself. Trailing and ratchet updates take effect from the **next** bar only.
- Limit target T triggers only if bar H > T strictly. Fill = T*(1-s). If stop and target are both reachable in one bar, **stop first**.
- Signal exits (evaluated at bar close) fill at the next bar open.
- **Gap guard:** skip the entry if |O1 - C[0]| > 0.5*ATR_ref (ATR_ref defined per strategy).
- **Cooldown:** after an exit fill in bar k, a new entry signal for the same symbol and strategy may only be evaluated from the close of bar k+1.
- **Cost-feasibility gate:** skip if 2*(f+s)*P_f > 0.35*(P_f - S0) (round-trip cost more than 35% of the initial stop distance).

**C4 Position sizing (spot, long-only, no leverage).**
Definitions: E = marked equity (cash + sum of qty * last completed 1H close). P_f = O1*(1+s). S0 = initial stop price. S_x = S0*(1-s). G = sum of reserved initial risk of open positions across all strategies.
- Per-unit risk: `d = (P_f - S_x) + f*(P_f + S_x)`. Require d > 0.
- Risk budget: `B = max(0, min(0.01*E, 0.03*E - G))`.
- `q = floor_to_lot_step( min( B/d , 0.33*E/P_f , cash/(P_f*(1+f)) , 0.01*Qmed168/P_f ) )`. Qmed168 = median quote volume of the last 168 completed 1H bars.
- Skip if q = 0 or q*P_f < venue minimum notional. Reserved risk = q*d, held until exit and not reduced by trailing.
- Max 3 concurrent positions across all strategies, 1 position per symbol. Processing order each timestamp: exits and stops first, then entries sorted by strategy ID, then symbol; E is frozen before sequential allocation.
- Worked arithmetic only (synthetic, not data): E = 10,000, P = 100, S0 = 95, f = .001, s = .0005 gives P_f = 100.05, S_x = 94.9525, d = 5.2925, B = 100, q = 18.894 units (notional ~1,890, below the 3,300 cap).

**C5 Liquidity gates (on the data venue, at signal time).** L1: median of the last 30 completed UTC daily quote volumes >= 20,000,000. L2: sum of the last 24 completed 1H quote volumes >= 10,000,000. L3: no zero-volume 1H bar in the last 24. These thresholds are assumptions, not validated. The 1%-of-Qmed168 size cap sits in C4.

**C6 Universe.** Fixed pre-registered cohort: BTC, ETH (core) plus SOL, XRP, ADA, LINK, AVAX, DOGE, LTC (liquid alternatives). Symbols that fail L1-L3 on a bar are ineligible on that bar. The cohort is chosen retrospectively from survivors, so it is **not** survivorship-free. BNB is excluded for venue portability. Quote asset: USDT (data profile P1) or USD (profile P2); **execution venue is unspecified**.

**C7 Short eligibility.** Spot has no shorting. Each strategy lists a mirrored short rule, `enabled=false`. Enabling it needs a margin or perpetual venue, funding/borrow data and a new rules version. It is not part of this spec's baseline.

---

## A1. CRY-MOM-101 — volatility-normalised momentum persistence (4H)

**Hypothesis (unverified).** Slow information diffusion and herding make risk-adjusted multi-week returns in large crypto assets positively autocorrelated. Normalising by realised volatility separates persistent drift from noise.

**Indicators (4H).** `r = ln(C/C[1])`. `sig180 = std(r[0..179])`. `M = ln(C[0]/C[180]) / (sig180*sqrt(180))`. `SMA300`. `ATR20`. ATR_ref = ATR20[0].

**Long eligibility** (all true at bar close, symbol flat, cooldown elapsed, C5 gates and cost gate pass):
1. `M >= 1.25`
2. `C[0] > SMA300[0]`
3. `SMA300[0] > SMA300[30]` (rising 50-day mean)
4. `C[0]/SMA300[0] <= 1.30` (no extreme-extension chase)
5. Market filter: BTC 4H `C[0] > SMA300[0]` (trivially BTC's own for BTC)

**Entry:** market buy at O1 (gap guard applies). Confirmation = conditions 2-5.
**Initial stop:** `S0 = O1 - 3.0*ATR20[0]`, live from the entry bar.
**Profit-taking:** none, by design. Profit is realised through the trail and signal exit.
**Trailing stop:** after each completed bar t, `stop[t+1] = max(stop[t], HC[t] - 3.5*ATR20[t])`.
**Signal exit:** `M[0] < 0` OR `C[0] < SMA300[0]` leads to a sell at the next open.
**Time exit:** held >= 180 completed 4H bars (30 days) leads to a sell at the next open.
**Sizing / liquidity:** C4 and C5.
**Short (disabled):** M <= -1.25, C < SMA300, SMA300 falling, BTC < SMA300, stop above entry.
**Regime suitability (hypothesis):** persistent directional markets. Unsuitable: range-bound chop and V-shaped reversals.
**Expected failure mechanisms:** whipsaw around the threshold in chop. Late entry after a move is largely done. Gap-through stops (stop fills at open, so loss > 1R). Cohort correlation, because up to 3 positions behave as one BTC-beta bet and the 3% open-risk cap understates joint risk. Turnover cost drag. Lookback decay. Survivorship in the alt cohort.
**Required data:** 1H OHLCV and quote volume for all cohort symbols, plus 1000 4H bars of warm-up (about 167 days) before each window start.
**Falsification (proposed numerics, frozen at preregistration):** common set F1-F8 below, plus **MOM-F9 placebo:** the same exits applied to entries triggered at `M <= 0` must not have an aggregate net-P&L/risk ratio below the real rule's. If it does, the persistence hypothesis is falsified. Neighbours for F5: lookback 90/270, threshold 1.0/1.5.

## A2. CRY-REV-102 — capitulation reversion inside an uptrend (4H)

**Hypothesis (unverified).** Forced selling (liquidations, panic) in a larger uptrend overshoots, and liquidity providers earn a partial reversal over hours to days. Without the uptrend context the same signal is a falling knife.

**Indicators (4H).** `RSI3` (Wilder, 3). `ATR14`. `SMA20`. `SMA300`. `IBS`. ATR_ref = ATR14[0].

**Long eligibility** (all true at bar close, symbol flat, cooldown elapsed, gates pass):
1. `RSI3[0] <= 8`
2. `C[0] > SMA300[0]`
3. `C[3] - C[0] >= 2.0*ATR14[0]` (down-impulse)
4. `IBS[0] >= 0.20` (confirmation: not closing on the extreme low)
5. Target `T = SMA20[0]` frozen at signal. Require `T > O1` and `(T - O1)/(O1 - S0) >= 1.0`.

**Entry:** market buy at O1 (gap guard applies).
**Initial stop:** `S0 = O1 - 2.0*ATR14[0]`, live from the entry bar.
**Profit-taking:** limit sell at T (fill rule C3).
**Trailing / ratchet:** once a completed bar closes >= `O1 + 1.0*ATR14[entry]`, set `armed=1`. From the next bar, `stop[t+1] = max(stop[t], O1, HC[t] - 1.5*ATR14[t])`.
**Signal exit:** `RSI3[0] >= 65` leads to a sell at the next open.
**Time exit:** held >= 12 completed 4H bars (2 days) leads to a sell at the next open.
**Short (disabled):** RSI3 >= 92, C < SMA300, (C - C[3]) >= 2 ATR, IBS <= 0.80, target SMA20, stop above entry.
**Regime suitability (hypothesis):** uptrend or wide range with ample liquidity. Unsuitable: cascade or contagion crashes, exchange or stablecoin failures, structural breaks.
**Expected failure mechanisms:** repeated losing entries inside one cascade (cooldown is only one bar). Negative skew: many small wins, rare large stop-through losses. A weak SMA300 filter during trend transitions. The target needs H strictly above T, so some touches go unfilled. Cost drag on small SMA20 gaps. Venue outages.
**Required data:** same as MOM plus 4H warm-up of 1000 bars.
**Falsification:** F1-F8 plus **REV-F9 ablation:** the same rule without condition 2 must not match or beat the filtered rule. If it does, the regime-dependence hypothesis is falsified. **REV-F10 tail:** if the sum of the 5 worst trades' losses exceeds total gross profit, it is tail-dominated and rejected. Neighbours: RSI3 threshold 5/12, drop 1.5/2.5 ATR.

## A3. CRY-VEX-103 — volume-confirmed volatility-expansion breakout (1H, 4H context)

**Hypothesis (unverified).** A range-expansion bar that closes near its high, breaks a 2-day high and carries abnormal volume marks arrival of informed or forced flow, and the order flow continues for several hours. Without volume confirmation, such bars are more often stop-runs.

**Indicators (1H).** `ATR24`. `DH48 = max(H[1..48])`. `Qmed168 = median(Q[1..168])`. `TR[0]`. `IBS[0]`. 4H context: the most recent 4H bar whose close time <= the 1H bar's close time, with `C4 > SMA50_4H`. ATR_ref = ATR24[1].

**Long eligibility** (all true at 1H bar close, symbol flat, cooldown elapsed, gates pass):
1. `C[0] > DH48`
2. `TR[0] >= 1.8*ATR24[1]`
3. `Q[0] >= 2.0*Qmed168`
4. `IBS[0] >= 0.75`
5. 4H context true

**Entry:** market buy at the next 1H open (gap guard applies).
**Initial stop:** `S0 = O1 - 2.0*ATR24[1]`, live from the entry bar.
**Profit-taking:** none fixed. Trail only.
**Trailing stop:** `stop[t+1] = max(stop[t], HC[t] - 2.5*ATR24[t])`.
**Failed-breakout exit:** for completed bars 1..6 after entry (bar 1 = entry bar), if `C[0] < DH48_signal` (frozen) then sell at the next open.
**Time exit:** held >= 48 completed 1H bars leads to a sell at the next open.
**Short (disabled):** mirrored (C < 48-bar low, TR/ volume/ IBS <= 0.25, 4H C < SMA50).
**Regime suitability (hypothesis):** transitions from quiet to active volatility during liquid sessions. Unsuitable: thin or weekend liquidity, news spikes that fully retrace, low-volume drift.
**Expected failure mechanisms:** false breakouts and stop-runs. Thrust-bar entries are near the high of the move, so risk is large relative to the typical continuation. The cost-feasibility gate may skip many signals (**unknown until measured**). Gap-through stops. High turnover at 1H. Volume spikes caused by venue-specific wash trading or promotions.
**Required data:** 1H OHLCV and quote volume, 4H aggregate, warm-up 1000 1H bars.
**Falsification:** F1-F8 plus **VEX-F9 ablation:** the same rule without condition 3 must not match or beat the volume-confirmed rule. If it does, the information-flow hypothesis is falsified. Neighbours: TR 1.5/2.2, volume 1.5/2.5, window 36/72.

### Common falsification set F1-F8 (proposed; applies to each strategy; dispositions come only from `research/validation/adjudicate.py`)
- **F1** Baseline-cost aggregate net P&L / aggregate reserved risk <= 0 in the validation window: reject.
- **F2** Same ratio <= 0 in either cost stress: label cost-fragile.
- **F3** One-sided 99.17% block-bootstrap lower bound of that ratio <= 0 on the evaluation window: cannot pass.
- **F4** Random-entry null (same exits, same trade count, same symbols, 1000 draws): strategy ratio below the 95th percentile: no entry edge.
- **F5** At least half of single-parameter neighbours (listed per strategy) have ratio <= 0: fragile.
- **F6** Removing the best ceil(5%) of trades by R makes the ratio <= 0: outlier-dependent.
- **F7** Fewer than 100 closed trades pooled: INCONCLUSIVE (not pass, not fail).
- **F8** Positive ratio in fewer than 2 of 3 equal-length subperiods of train+validation: unstable.
UNKNOWN mandatory gates (historical filters, venue status, cost observation) block any unconditional pass.

---

## B. Comparison matrix (design attributes only; no performance ranking)

| Attribute | CRY-MOM-101 | CRY-REV-102 | CRY-VEX-103 |
|---|---|---|---|
| Family | Trend / momentum | Mean reversion | Breakout / vol expansion |
| Signal TF / warm-up | 4H / 1000 bars | 4H / 1000 bars | 1H (+4H) / 1000 bars |
| Direction (spot baseline) | Long only | Long only | Long only |
| Core signal | M >= 1.25 (30d t-stat) | RSI3 <= 8 + 2 ATR drop | 48-bar high + 1.8 ATR TR + 2x volume |
| Trend context | SMA300 rising, BTC filter | SMA300 up | 4H C > SMA50 |
| Initial stop | 3.0 ATR20 | 2.0 ATR14 | 2.0 ATR24 |
| Profit-taking | None (trail) | Limit SMA20 | None (trail) |
| Trail | 3.5 ATR chandelier | Ratchet then 1.5 ATR | 2.5 ATR chandelier |
| Time stop | 180 bars (30d) | 12 bars (2d) | 48 bars (2d) |
| Hypothesised payoff shape | Few large winners, many small losers | Many small winners, rare large losers | Few large winners, many small losers |
| Hypothesised favourable regime | Persistent trend | Uptrend dip / range | Quiet to active volatility |
| Main cost sensitivity | Low turnover (hypothesis) | Moderate | High (1H, cost gate) |
| Overlap risk | Highest BTC-beta overlap | Overlaps MOM in strong trends only | Overlaps MOM at trend starts |
| Mechanism distinct from legacy | vs EMA-stack TF-001 | vs z-score/ER MR-002 | vs BB-width squeeze BO-003 |

Payoff shapes and cost sensitivities are design hypotheses, not measurements.

## C-data. Data requirements

| Need | Spec | Status |
|---|---|---|
| 1H OHLCV + quote volume, UTC | 9 symbols, 2021-11-17 to 2026-11-17 plus 1000 bars warm-up before each window (about 2021-05) | P1 files exist at 3 probed months. Continuity, checksums and gap audit **not yet run** |
| 4H aggregation | Built from 1H (C1) | Derived |
| Audit | Reuse legacy audit rules: duplicates, nonfinite or nonpositive prices, OHLC inequalities, zero volume, gaps, >20% hourly close jumps. Invalid data blocks the run | Required |
| Venue filters / status / fees / spreads | Historical lot, tick, min notional, status, fee tier | **UNAVAILABLE** (Binance.com blocked here; venue unspecified) |
| Quote-asset conversion | USDT/USD history if P1 is used and USD results are wanted | **UNAVAILABLE** |
| Short economics | Funding, borrow, margin | **UNAVAILABLE** (shorts disabled) |
| Delisted or failed assets | Survivor-free universe | **UNAVAILABLE** |
| Live data | Not needed for specification | Not required |

Profile P1 (Binance spot archive, USDT, continuity with the legacy pipeline) is the proposed backtest data source. Profile P2 (Coinbase Exchange USD) is an alternative or cross-check and does not cover all alternatives for five years.

## D. Pre-registered testing assumptions (proposed; frozen only via the workbench)

1. **No optimisation.** Parameters above are final for version 0.1.0. Changes need a new version and a new registered trial.
2. **Register all three** as trials in the hash-chained ledger and preregister before any test-split access: `scripts/lab research ...`. Not done yet.
3. **Splits:** train [2021-11-17, 2024-11-17), validation [2024-11-17, 2025-11-17), final [2025-11-17, 2026-11-17). Never move the dates after seeing P&L.
4. **The final window is `CONSUMED_LEGACY`** for this lab and general market history. It is reported as **descriptive, contaminated** evidence, not an untouched holdout. No honest untouched historical holdout exists on the same assets.
5. **Confirmation options:** (a) forward, no-trade-execution paper evaluation from 2026-11-18, with at least 6 months and at least 100 trades or else INCONCLUSIVE. (b) An adjacent-asset holdout of symbols outside the cohort (e.g. BNB, DOT, ATOM, BCH), disclosed as a cross-sectional rather than temporal holdout.
6. **Multiplicity:** treat the lab family as 6 hypotheses (3 legacy + 3 new), so one-sided confidence 1 - 0.05/6 = 99.17%. Block bootstrap: circular, 14-day blocks, 10,000 resamples, seed 20261118, estimand sum(P&L)/sum(reserved risk).
7. **Costs:** baseline f = 10 bp, s = 5 bp per side (assumed). Two stress scenarios in C3. Optional partial-fill stress at 1% of the preceding minute's quote volume (legacy convention).
8. **Benchmarks (report-only):** equal-weight buy-and-hold of the cohort, and BTC SMA200 daily long/cash, under identical costs.
9. **Regime attribution (not entry filters):** BTC prior-daily-close vs SMA200, crossed with prior 30-day annualised volatility above or below 60%.
10. **Reporting:** per strategy and combined shared $10,000 account, each window separately; trade R = net P&L / reserved risk of the filled quantity; report cost-to-risk skip counts, gap-guard skips, gap-through stop losses and failed-breakout exits.
11. **Research only.** No orders, no credentials, no execution code. Do not construct `lab.Market` on the real tree.
12. **Disclosure.** Trade counts, ATR scale and gate hit-rates are unknown until the first run; nothing here predicts them.
