# Stage 02 preregistration, methodology 1.1.0

Frozen before any strategy performance calculation. Input: the STAGE_01_HANDOFF
1.0.0 in this conversation. Strategy signal parameters are unchanged.

Requested evaluation: [2021-11-17 00:00, 2026-11-17 00:00) UTC.
Training [2021-11-17,2024-11-17), validation [2024-11-17,2025-11-17),
untouched test [2025-11-17,2026-11-17). Start flat each window, use earlier
data for 1000 consecutive 4h warmup. Never move split dates in response to P&L.
If data do not reach the requested end, truncate and disclose; do not recenter splits.
No optimization. The test becomes consumed by the first execution of run.py.

Venue Binance.com spot. Fixed cohort BTCUSDT, ETHUSDT, SOLUSDT; this is a
retrospectively selected surviving cohort, NOT a survivorship-free crypto universe.
No shorting, leverage, borrowing, funding, staking or cash yield.
Baseline uses USDT=USD. Dollar results are conditional on that assumption.

Archive provider https://data.binance.vision. Download monthly 1h and 1m files
from 2021-05 through 2026-10 and daily files through 2026-11-16; verify official
SHA256 checksums and log retrieval times, byte counts, headers and local hashes.
Audit duplicate timestamps, nonfinite prices, OHLC inequalities, nonpositive prices,
negative volume, zero-volume candles, discontinuities, >20% hourly close changes,
>30% hourly high-low ranges and minute/hour aggregation differences. Suspicious
observations are flagged, not silently winsorized. Invalid observations block runs.
Missing hours reset indicator warmup, never forward fill signal inputs.
Minute gaps while invested make execution unobservable; close at first observable
price and report the event. Data-quality issues gate research approval.

Baseline assumptions: 10bp fee each side, 5bp adverse execution each side,
decomposed into 2bp half-spread + 3bp slippage (assumed, not observed).
Cost stresses: 20bp fee + 10bp adverse adjustment, plus 10bp fee + 20bp adverse
adjustment per side. All sizes, risk budgets and cash re-evaluated in each scenario.
Baseline preserves original full-fill model. Additional partial-fill stress uses
maximum 1% of preceding completed minute quote volume per fill. Entry remainder
is cancelled, exit remainder remains pending and is processed at following minute
opens. Initial stops protect the filled inventory. This is an explicit execution
extension, not a claim to historical queue reconstruction. Limit target fills need
minute high STRICTLY above target, are priced at target less adverse adjustment,
and are conservatively stop-first if both levels appear in a minute.

Historical filters/status are unavailable: diagnostic runs use explicit assumed
steps BTC=0.000001, ETH=0.00001, SOL=0.001 and minimum notional 10 USDT.
They do NOT satisfy the original strict historical-tradability gate. No strategy
can receive an unconditional Pass until this gate is resolved. Availability of
valid prints establishes observable trading activity, not complete venue status.
Stops round down and targets up to assumed 0.01 USDT tick. This discretization
extension is recorded; quantity reserves use the rounded stop.

At a timestamp, process queued exits and stops before entries. Freeze equity
for all allocations then decrement cash and reserved risk sequentially; sort by
strategy ID then symbol. Exits induced by the bar close happen next bar open.
1000-bar warmup applies to each uninterrupted 4h data segment. One full strategy
bar cooldown; trailing updates only affect later bars; no same-bar trail activation.
At window end force close with costs, labelled separately. In the partial stress,
end-of-window liquidation is uncapped, with a separate flag (no assumption of
future data). Equity sampled hourly, daily UTC returns include all cash days.

Metrics: ACT/365.25 CAGR, daily sample volatility*sqrt(365.25), daily arithmetic
Sharpe with zero risk-free rate, Sortino with sqrt(mean(min(r,0)^2))*sqrt(365.25).
Drawdown from hourly equity including initial capital; recovery is peak-to-next
recovered peak, right-censored if unrecovered. Report exposure as average hourly
gross inventory/equity and time invested. Turnover = two-way executed notional /
mean hourly equity, annualized by elapsed years. Trade R = net P&L / original
reserved risk of actual filled quantity. Expectancy R is arithmetic mean trade R;
also report aggregate P&L/aggregate risk, the Stage 01 bootstrap estimand.

Report train, validation, test separately; full-period chained flat-boundary runs
are descriptive. Independent strategy accounts and a combined shared $10000
account. Benchmarks: equal-weight buy-and-hold fixed three-asset cohort and
BTC-only SMA200 daily long/cash benchmark, signals after daily close, next UTC
open; identical cost scenarios. Benchmark full fills are explicitly assumed.

Regimes for attribution, not entry: prior completed BTC daily close above/below
SMA200, crossed with prior completed 30-day daily-return sample volatility above/
below annualized 60%. Assign daily returns by regime; assign trades by entry regime.
No future regime labels. Calendar-year returns compound daily marked equity returns.

Test uncertainty: circular 14-day blocks, 10000 samples, seed 20261117, one-sided
98.33% lower bound for each of three strategies; bootstrap daily P&L and entry risk
jointly; ratio sum(P&L)/sum(risk). Also 95% descriptive interval. Minimum 100 closed
test trades and 300 usable days. Nonpositive test expectancy rejects this implementation;
positive with inadequate samples or bound<=0 investigates. Stress nonpositive
expectancy fails cost robustness. Data/eligibility/execution gaps override Pass.
Parameter sensitivities +/-20% of lookbacks and ATR multipliers, one at a time,
nearest integer halves up. They are diagnostic training-only runs; never tune on test.
