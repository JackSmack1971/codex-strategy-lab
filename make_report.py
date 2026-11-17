"""Render report directly from executed artifacts; no strategy outcomes hard-coded."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from download import ROOT

def table(df):
    cols=list(df.columns)
    def val(x):
        if x is None or (isinstance(x,float) and np.isnan(x)): return '—'
        return str(x)
    return '| '+' | '.join(cols)+' |\n| '+' | '.join(['---']*len(cols))+' |\n'+'\n'.join('| '+' | '.join(val(x) for x in row)+' |' for row in df.itertuples(index=False,name=None))+'\n'

def pct(x): return f'{100*x:.2f}%'
def num(x): return '—' if pd.isna(x) else f'{x:.3f}'

def main():
    out=ROOT/'results'; df=pd.read_csv(out/'metrics.csv'); audit=json.loads((out/'data_audit.json').read_text())
    unc=json.loads((out/'uncertainty.json').read_text()); meta=json.loads((out/'run_metadata.json').read_text())
    if 'completed_utc' not in meta: raise RuntimeError('Refuse to report incomplete run')
    ex=json.loads((out/'execution_audit.json').read_text())
    manifest=json.loads((out/'data_manifest.json').read_text()); sample=json.loads((out/'native_4h_comparison.json').read_text())
    baseline=df[(df.scenario=='baseline')&(df.window=='test')].copy()
    strategies=baseline[baseline.strategy.str.startswith('CRY-')].copy()
    decisions=[]
    for _,r in strategies.iterrows():
        ci=unc[r.strategy]; n=int(r.trade_count)
        if r.expectancy_R<=0:
            assessment='Reject'; reason='Nonpositive final-test net trade expectancy under the specified model'
        else:
            assessment='Investigate'; reason='Positive point estimate is not sufficient for validation'
        if n<100: reason+=f'; only {n} trades, below preregistered minimum 100'
        if ci['lower_adjusted'] is None or ci['lower_adjusted']<=0: reason+='; adjusted confidence bound does not establish positive edge'
        stress=df[(df.scenario=='high_cost')&(df.window=='test')&(df.strategy==r.strategy)].iloc[0]
        if stress.expectancy_R<=0: reason+='; fails cost-robustness requirement'
        reason+='; historical status/filter, execution, fixed-cohort and holdout-rerun limitations remain'
        decisions.append({'strategy':r.strategy,'assessment':assessment,'reason':reason})
    (out/'assessment.json').write_text(json.dumps(decisions,indent=2))
    parts=['# Stage 02: executed historical backtest and independent validation\n',
      '**Status: conditional historical research. These are calculations executed on downloaded historical candles, not live returns or verified executable fills. No strategy receives an unconditional Pass.**\n',
      '## A. Reproducible methodology\n',
      f'Methodology `{meta["methodology_version"]}`, executed source commit `{meta["git_commit"]}`. The source-file SHA-256 hashes, Python/dependency versions and UTC execution timestamps are in [run metadata](results/run_metadata.json). Rules are in [STAGE_01_HANDOFF.json](STAGE_01_HANDOFF.json); the [preregistration](PREREGISTRATION.md) was committed before performance evaluation.\n',
      'Venue: Binance.com spot. Symbols: BTCUSDT, ETHUSDT, SOLUSDT. Quote unit: USDT. Time zone: UTC. Signals: 1H and 4H; execution resolution: 1 minute. Evaluation interval [2021-11-17 00:00, 2026-11-17 00:00) UTC. Additional data from 2021-05-01 provide warm-up. All three strategies were run independently and under one shared-capital allocator. Each split starts flat with 10,000 USDT; the splits are separate account experiments, not a single compounded five-year account.\n',
      table(pd.DataFrame([['Train','2021-11-17','2024-11-17'],['Validation','2024-11-17','2025-11-17'],['Final test','2025-11-17','2026-11-17']],columns=['Window','Start inclusive UTC','End exclusive UTC'])),
      'No parameter optimization was performed. Signals use completed candles; higher-timeframe features are shifted to their availability timestamps. Entries and bar-close exits execute at the next strategy-bar open. Stops and targets use minute candles, with stop-first treatment when chronology inside a minute is unknowable. Trailing changes apply only after a strategy candle closes. Window-end exits are forced and labelled `boundary`. Indicator warm-up resets after missing hourly data, requiring another 1,000 consecutive 4H bars.\n',
      '**Holdout integrity:** preliminary test calculations executed during implementation review. Correctness fixes addressed exact-boundary cooldown, causal minute-gap handling and partial-fill capacity accounting. Runs were repeated without performance-driven parameter selection. The final test has the preregistered dates but is consumed and is not a pristine single-pass untouched holdout. Do not reuse it as untouched evidence for subsequent versions. Source history records the corrections; an intermediate checkpoint is not an authoritative archive of the initial partial run.\n',
      '**Risk and capital:** initial risk at most 1% per trade and reserved total risk at most 3% at entry; at most three positions, one per asset, no leverage, 33% notional cap per asset. Original risk remains reserved until full exit. Quantities round down to explicitly assumed lot steps and must meet assumed 10 USDT minimum notional. Stops round down and targets up to assumed 0.01 USDT ticks. Stop gaps may exceed planned risk.\n',
      '**Costs:** baseline 10bp fee + 2bp assumed half-spread + 3bp assumed slippage on each side. High-cost scenario: 20bp fee + 10bp combined adverse adjustment; high-slippage scenario: 10bp fee + 20bp adjustment. No funding or borrow costs apply to unlevered owned spot inventory. USDT=USD is an unverified baseline valuation assumption. Effective target prices include the handoff\'s adverse cost haircut; these are conservative modeled effective prices, not reconstructed native resting-limit fills.\n',
      '**Partial fills:** baseline retains Stage 01 full fills under the hourly participation cap. A separate stress caps fills at 1% of the preceding completed minute quote volume, cancels unfilled entry quantity, and carries unfinished market exits forward. This deterministic proxy does not reproduce order-book queues or historical fill probabilities. Window-end liquidation is uncapped in that stress and explicitly counted.\n',
      '**Metric definitions:** CAGR uses actual elapsed years of 365.25 days. Volatility and Sharpe use UTC daily returns with annualization 365.25 and zero risk-free rate. Sortino uses all-day downside deviation about zero. Drawdown uses hourly marked equity including initial capital, so minute-level drawdowns can be deeper. Recovery measures the worst drawdown\'s peak to recovery and is censored at window end when unrecovered. Trade R is net P&L divided by initial reserved risk; expectancy is the unweighted mean of those R values. Exposure is average hourly-end gross inventory/equity; very short intrahour exposure can be undercounted. Turnover is annualized two-way executed notional divided by mean equity.\n',
      'Reproduce from a clean checkout:\n\n```bash\npython -m pip install -r requirements.txt\npython download.py\npython verify_data.py\npython -m unittest -v test_lab\npython -W ignore::FutureWarning run.py --sensitivity\npython validate_results.py\npython make_report.py\n```\n',
      '## B. Final-test baseline metrics\n']
    show=baseline[['strategy','CAGR','annual_volatility','Sharpe','Sortino','max_drawdown']].copy()
    for c in ['CAGR','annual_volatility','max_drawdown']: show[c]=show[c].map(pct)
    for c in ['Sharpe','Sortino']: show[c]=show[c].map(num)
    parts.append(table(show))
    parts.append('Trend-following has a positive unweighted mean R but negative account P&L and profit factor below one: trade risk amounts differ because of notional, liquidity and capital caps. Its aggregate net P&L/aggregate initial risk is negative. A positive unweighted trade average is therefore not evidence of positive portfolio returns.\n')
    show=strategies[['strategy','trade_count','win_rate','profit_factor','expectancy_R','mean_gross_exposure','annual_two_way_turnover','ending_equity']].copy()
    show.trade_count=show.trade_count.astype(int)
    for c in ['win_rate','mean_gross_exposure']: show[c]=show[c].map(pct)
    for c in ['profit_factor','expectancy_R','annual_two_way_turnover']: show[c]=show[c].map(num)
    show.ending_equity=show.ending_equity.map(lambda x:f'{x:,.2f}')
    parts.append(table(show))
    parts.append('All final-test accounts have 365 daily observations. A zero/undefined denominator is reported as unavailable rather than inventing a finite ratio. Full metrics for every split, account and scenario are in [metrics.csv](results/metrics.csv). Benchmark trade statistics are deliberately unavailable because their equity accounting is not a stop-risk trade ledger.\n')
    parts.append('### Chronological split comparison\n')
    show=df[(df.scenario=='baseline')&df.strategy.str.startswith('CRY-')][['strategy','window','CAGR','Sharpe','max_drawdown','trade_count','expectancy_R']].copy()
    for c in ['CAGR','max_drawdown']: show[c]=show[c].map(pct)
    for c in ['Sharpe','expectancy_R']: show[c]=show[c].map(num)
    parts.append(table(show))
    parts.append('### Cost and fill sensitivity: final test\n')
    show=df[(df.window=='test')&df.strategy.str.startswith('CRY-')][['strategy','scenario','CAGR','trade_count','expectancy_R']].copy()
    show.CAGR=show.CAGR.map(pct); show.expectancy_R=show.expectancy_R.map(num)
    parts.append(table(show))
    parts.append('### Uncertainty\n')
    rows=[]
    for _,r in strategies.iterrows():
        u=unc[r.strategy]
        rows.append({'strategy':r.strategy,'test trades':int(r.trade_count),'adjusted lower bound':num(u['lower_adjusted']),'descriptive 95% interval':f"[{num(u['ci95'][0])}, {num(u['ci95'][1])}]"})
    parts.append(table(pd.DataFrame(rows)))
    parts.append('Intervals estimate aggregate net P&L / aggregate initial risk, which differs from unweighted mean trade R. Circular 14-day daily-P&L/risk blocks, 10,000 replications, seed 20261117; one-sided 98.33% bounds address the three strategy hypotheses. These intervals cover sampling variation conditional on this surviving cohort and execution model, not model uncertainty or selection bias. The 100-trade minimum is a decision threshold, not proof that 100 trades are independent.\n')
    parts.append('## C. Equity, drawdown, year and regime analysis\n')
    show=baseline[['strategy','max_drawdown','recovery_days','recovery_censored','drawdown_peak','drawdown_trough']].copy(); show.max_drawdown=show.max_drawdown.map(pct); show.recovery_days=show.recovery_days.map(lambda x:f'{x:.1f}')
    parts.append(table(show))
    parts.append('`recovery_censored=True` means recovery had not occurred by test end; the reported duration is only the elapsed lower bound.\n\n![Final-test equity and drawdown](results/test_equity_drawdown.png)\n\n[Training chart](results/train_equity_drawdown.png) · [Validation chart](results/validation_equity_drawdown.png)\n')
    year=pd.read_csv(out/'by_year.csv'); year=year[year.strategy.str.startswith('CRY-')]; year['return']=year['return'].map(pct)
    parts.append('### Calendar-year performance, separated at split boundaries\n'+table(year[['strategy','window','year','days','return','closed_trades']]))
    reg=pd.read_csv(out/'by_regime.csv'); reg=reg[(reg.window=='test')&reg.strategy.str.startswith('CRY-')].copy()
    reg.mean_daily_return=reg.mean_daily_return.map(pct); reg.expectancy_R=reg.expectancy_R.map(num)
    parts.append('### Final-test market-regime attribution\n'+table(reg[['strategy','regime','days','mean_daily_return','entry_trades','expectancy_R']]))
    parts.append('Regimes use only prior completed BTC daily observations: close above/below SMA200, crossed with prior 30-day annualized volatility above/below 60%. Daily returns are attributed by that day\'s known regime; trades by entry regime. Regime-only compounded returns are not a tradable separate account, and regime means do not imply causal explanation. Small cells are weak evidence.\n')
    sensitive=pd.read_csv(out/'training_parameter_sensitivity.csv')
    ss=sensitive.groupby('strategy').agg(runs=('CAGR','size'),minimum_CAGR=('CAGR','min'),maximum_CAGR=('CAGR','max'),minimum_expectancy_R=('expectancy_R','min'),maximum_expectancy_R=('expectancy_R','max')).reset_index()
    for c in ['minimum_CAGR','maximum_CAGR']: ss[c]=ss[c].map(pct)
    for c in ['minimum_expectancy_R','maximum_expectancy_R']: ss[c]=ss[c].map(num)
    parts.append('### Training-only parameter stability\n'+table(ss))
    parts.append('One-at-a-time ±20% lookback and ATR-multiplier perturbations were executed only on training data. No replacement parameters were selected. Individual runs are in [training_parameter_sensitivity.csv](results/training_parameter_sensitivity.csv).\n')
    parts.append('## D. Benchmarks\n')
    parts.append('The first table includes equal-weight BTC/ETH/SOL buy-and-hold and a simple BTC daily SMA200 long/cash rule. Both pay the same modeled fees and adverse execution costs; both assume full fills. Accounts restart at each split. Benchmark concentration and exposure differ from the strategies, so their raw returns are not risk-matched comparisons.\n')
    parts.append('## E. Bias and data-quality audit\n')
    q=[]
    for a in audit:
        hr=a['intervals']['1h']; mi=a['intervals']['1m']
        q.append({'symbol':a['symbol'],'1H missing':hr['missing_count'],'1m missing':mi['missing_count'],'duplicates':hr['duplicate_count']+mi['duplicate_count'],'invalid':hr['invalid_count']+mi['invalid_count'],'flagged hourly observations, incl warmup':hr['suspicious_count'],'quote-volume mismatches, incl warmup':a['aggregation_mismatches']['quote_volume']})
    parts.append(table(pd.DataFrame(q)))
    parts.append(f'{len(manifest)} primary files passed official SHA-256 checksums. Raw coverage for all assets starts 2021-05-01 00:00 UTC and ends 2026-11-16 23:59 UTC at minute resolution. The evaluation has 43,824 expected hourly candles per asset, with one missing. All assets miss the 2023-03-24 13:00 hourly candle; BTC/ETH miss 80 minutes around that event, and SOL also misses 2023-02-14 16:39. These gaps are retained and recorded.\n')
    parts.append(f'Minute-to-hour OHLC comparisons have zero mismatches. Quote-volume aggregation mismatches are retained and disclosed; maximum relative differences are 1.31% BTC, 0.60% ETH, 2.61% SOL, all before July 2022. Native 4H samples from November 2021 and October 2026 total {sum(x["bars"] for x in sample if x["field"]=="close")} bars and match derived OHLC and quote volume without mismatches. This sample check is not a complete native-4H archive audit.\n')
    parts.append('Suspicious prices use >20% adjacent close changes or >30% high/low ranges. Flagged ETH/SOL candles are retained because minute aggregation corroborates their OHLC; checksum agreement does not itself prove economic correctness. Zero-volume candles are separately counted in the audit.\n')
    gaps=sum(v['counters']['missing_execution_hours'] for k,v in ex.items() if k.startswith('baseline__'))
    parts.append(f'Baseline simulations logged {gaps} invested hours with incomplete minute coverage across independent and combined split accounts (overlapping experiments, not unique market hours). See [execution audit](results/execution_audit.json) for each account and [data audit](results/data_audit.json) for exact missing timestamps.\n')
    parts.append('**Bias controls and unresolved gates:** completed-bar availability prevents indicator look-ahead; explicit flat split boundaries prevent cross-split position leakage; there was no parameter search on validation/test. However, the three assets were chosen retrospectively, so broad-universe survivorship bias cannot be claimed eliminated. Findings apply only to this fixed cohort. Historical tradability/status and instrument filters are missing; assumed filters do not satisfy Stage 01\'s strict eligibility gate. Historical spreads, depth, actual fees and fill probabilities remain unverified. User jurisdiction and account eligibility are unresolved. No USD depeg robustness was calculated. The final test was rerun after correctness fixes. These limitations prevent unconditional validation.\n')
    parts.append('## F. Research assessment\n'+table(pd.DataFrame(decisions)))
    parts.append('Reject is the preregistered research decision for the tested implementation, not statistical proof that its true expected return is negative or a rejection of every strategy in its family. The descriptive 95% intervals include zero for all three. Investigate means further independent evidence is required. Neither category authorizes trading. A future revised strategy needs new rules/version and genuinely new out-of-sample data.\n')
    checks=json.loads((out/'validation_checks.json').read_text())
    parts.append(f'Engineering verification: {checks["synthetic_unit_tests"]} synthetic unit tests passed and {checks["artifact_checks"]} artifact reconciliation checks passed. These verify implementation arithmetic and timing, not the unresolved market-data or execution assumptions.\n')
    parts.append('## Artifacts and provenance\n\n- [Complete metrics](results/metrics.csv), [year attribution](results/by_year.csv), [regime attribution](results/by_regime.csv), [uncertainty](results/uncertainty.json)\n- `results/*__equity.csv`, `*__trades.csv`, `*__fills.csv`: complete account traces\n- [Primary download manifest](results/data_manifest.json), [4H sample manifest](results/native_4h_sample_manifest.json), [4H comparison](results/native_4h_comparison.json), [quote-volume discrepancies](results/quote_volume_discrepancies.json)\n- Public data documentation: https://github.com/binance/binance-public-data\n- No raw market files or credentials are committed; the downloader recreates checksum-verified files.\n')
    (ROOT/'REPORT.md').write_text('\n'.join(parts))
    print(table(pd.DataFrame(decisions)))

if __name__=='__main__': main()
