"""Run audited historical evaluation; outputs are generated, never hard-coded."""
import argparse, hashlib, json, platform, subprocess, sys
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from lab import *

def clean(x):
    if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,list): return [clean(v) for v in x]
    if isinstance(x,(float,np.floating)) and not np.isfinite(x): return None
    if isinstance(x,np.integer): return int(x)
    if isinstance(x,np.bool_): return bool(x)
    return x

def save_json(path,obj): path.write_text(json.dumps(clean(obj),indent=2,default=str,allow_nan=False))

def attribution(eq,tr,market,start):
    d=daily_frame(eq,start); d['regime']=market.regime.reindex(d.index).fillna('unknown')
    years=[]
    for y,g in d.groupby(d.index.year):
        tt=tr[pd.to_datetime(tr.exit_time,utc=True).dt.year==y] if len(tr) else tr
        years.append({'year':int(y),'days':len(g),'return':float((1+g['return']).prod()-1),'closed_trades':len(tt),'closed_trade_pnl':float(tt.pnl.sum()) if len(tt) else 0})
    regs=[]
    for name,g in d.groupby('regime'):
        entryreg=market.regime.reindex(pd.to_datetime(tr.entry_time,utc=True).dt.floor('1D')).to_numpy() if len(tr) else np.array([])
        tt=tr[entryreg==name] if len(tr) else tr
        regs.append({'regime':name,'days':len(g),'mean_daily_return':float(g['return'].mean()),'compounded_regime_return':float((1+g['return']).prod()-1),'entry_trades':len(tt),'expectancy_R':float(tt.R.mean()) if len(tt) else None})
    return years,regs

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--sensitivity',action='store_true'); args=parser.parse_args()
    out=ROOT/'results'; out.mkdir(exist_ok=True)
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')}
    prereg=hashlib.sha256((ROOT/'PREREGISTRATION.md').read_bytes()).hexdigest()
    runmeta={'started_utc':datetime.now(timezone.utc).isoformat(),'methodology_version':VERSION,
      'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
      'source_sha256':hashes,'preregistration_sha256':prereg,'python':sys.version,'numpy':np.__version__,'pandas':pd.__version__,
      'test_status':'CONSUMED; rerun after correctness fixes; no performance-driven parameter selection',
      'implementation_corrections':['exact-boundary cooldown','causal handling of missing minute observations'],
      'untouched_test_caveat':'Original dates frozen before execution. Preliminary test calculations occurred before correctness fixes; numerical outcomes were not used to select rules. Final test is not a pristine single-pass holdout.'}
    save_json(out/'run_metadata.json',runmeta)
    market=Market()
    scenarios={'baseline':(.001,.0005,False),'high_cost':(.002,.001,False),'high_slippage':(.001,.002,False),'partial_fill':(.001,.0005,True)}
    summary=[]; yearrows=[]; regrows=[]; curves={}; uncertainty={}; execaudit={}
    for scenario,(fee,slip,partial) in scenarios.items():
        for name,sids in [(s,[s]) for s in IDS]+[('COMBINED',IDS)]:
            for window,(start,end) in WINDOWS.items():
                print('Running',scenario,name,window,flush=True)
                eq,tr,fi,audit=simulate(market,sids,start,end,fee,slip,partial)
                key=f'{scenario}__{name}__{window}'
                met=metrics(eq,tr,start,end); met.update(scenario=scenario,strategy=name,window=window)
                summary.append(met); execaudit[key]=audit
                eq.to_csv(out/f'{key}__equity.csv',float_format='%.10f')
                tr.to_csv(out/f'{key}__trades.csv',index=False,float_format='%.10f')
                fi.to_csv(out/f'{key}__fills.csv',index=False,float_format='%.10f')
                if scenario=='baseline':
                    years,regs=attribution(eq,tr,market,start)
                    yearrows.extend([dict(strategy=name,window=window,**r) for r in years]); regrows.extend([dict(strategy=name,window=window,**r) for r in regs])
                    curves[name,window]=eq
                    if window=='test': uncertainty[name]=bootstrap(eq,start)
    for scenario,(fee,slip,partial) in scenarios.items():
        if partial: continue
        for kind in ['equal_weight','btc_sma200']:
            for window,(start,end) in WINDOWS.items():
                eq=benchmark(market,start,end,kind,fee,slip)
                met=metrics(eq,pd.DataFrame(),start,end)
                for k in ['win_rate','profit_factor','expectancy_R','aggregate_pnl_per_risk','trade_count','fees','forced_boundary_trades']: met[k]=None
                met.update(scenario=scenario,strategy=kind,window=window); summary.append(met)
                eq.to_csv(out/f'{scenario}__{kind}__{window}__equity.csv',float_format='%.10f')
                if scenario=='baseline': curves[kind,window]=eq
    df=pd.DataFrame(summary); df.to_csv(out/'metrics.csv',index=False,float_format='%.10f')
    pd.DataFrame(yearrows).to_csv(out/'by_year.csv',index=False)
    pd.DataFrame(regrows).to_csv(out/'by_regime.csv',index=False)
    save_json(out/'uncertainty.json',uncertainty); save_json(out/'execution_audit.json',execaudit)
    save_json(out/'metrics.json',summary)
    for window in WINDOWS:
        fig,(ax,dx)=plt.subplots(2,1,figsize=(12,8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
        for (name,w),eq in curves.items():
            if w!=window: continue
            series=pd.concat([pd.Series([10000.],index=[WINDOWS[w][0]]),eq.equity])
            ax.plot(series.index,series,label=name,linewidth=1.1)
            dx.plot(series.index,100*(series/series.cummax()-1),label=name,linewidth=.9)
        ax.set_ylabel('Equity (USDT)'); ax.set_title(f'{window}: executed historical calculations; conditional execution assumptions')
        ax.legend(ncol=2,fontsize=8); ax.grid(alpha=.2); dx.grid(alpha=.2); dx.set_ylabel('Drawdown (%)')
        fig.tight_layout(); fig.savefig(out/f'{window}_equity_drawdown.png',dpi=160); plt.close(fig)
    if args.sensitivity:
        sensitive=[]
        defaults={'ema20':20,'ema50':50,'ema200':200,'slope':6,'atr':14,'er':20,'mean':20,'breakout':20,'compression':120,'volume':20}
        affected={'ema20':[IDS[0]],'ema50':[IDS[0],IDS[2]],'ema200':[IDS[0]],'slope':[IDS[0]],'atr':IDS,'er':[IDS[1]],'mean':[IDS[1],IDS[2]],'breakout':[IDS[2]],'compression':[IDS[2]],'volume':[IDS[2]]}
        original=market.plans
        for param,default in defaults.items():
            for factor in [.8,1.2]:
                val=math.floor(default*factor+.5)
                market.plans={s:features(load(s,'1h'),{param:val})[1] for s in SYMBOLS}
                for sid in affected[param]:
                    print('Sensitivity TRAIN ONLY',param,val,sid,flush=True)
                    a,b=WINDOWS['train']; eq,tr,_,_=simulate(market,[sid],a,b)
                    sensitive.append(dict(parameter=param,value=val,strategy=sid,**metrics(eq,tr,a,b)))
        market.plans=original
        for sid,base in [(IDS[0],(2.5,3.)),(IDS[1],(1.5,0.)),(IDS[2],(2.,2.))]:
            for k,label in [(0,'initial_stop_ATR'),(1,'trailing_ATR')]:
                if base[k]==0: continue
                for factor in [.8,1.2]:
                    changed=list(base); changed[k]*=factor; a,b=WINDOWS['train']
                    eq,tr,_,_=simulate(market,[sid],a,b,atr_multipliers={sid:tuple(changed)})
                    sensitive.append(dict(parameter=label,value=changed[k],strategy=sid,**metrics(eq,tr,a,b)))
        pd.DataFrame(sensitive).to_csv(out/'training_parameter_sensitivity.csv',index=False)
    runmeta['completed_utc']=datetime.now(timezone.utc).isoformat(); save_json(out/'run_metadata.json',runmeta)
    print(df[(df.window=='test')&(df.scenario=='baseline')][['strategy','CAGR','Sharpe','max_drawdown','trade_count','expectancy_R']].to_string(index=False),flush=True)

if __name__=='__main__': main()
