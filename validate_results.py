"""Artifact reconciliation independent of the simulation control loop."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from download import ROOT,load
from lab import IDS,WINDOWS

def main():
    out=ROOT/'results'; met=pd.read_csv(out/'metrics.csv'); checks=0
    meta=json.loads((out/'run_metadata.json').read_text())
    assert 'completed_utc' in meta
    for name in ['lab.py','download.py','run.py','test_lab.py']:
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==meta['source_sha256'][name],name
        checks+=1
    fee_map={'baseline':.001,'high_cost':.002,'high_slippage':.001,'partial_fill':.001}
    minute={}
    for _,r in met.iterrows():
        key=f'{r.scenario}__{r.strategy}__{r.window}'; eq=pd.read_csv(out/f'{key}__equity.csv',index_col=0,parse_dates=True)
        a,b=WINDOWS[r.window]
        assert len(eq)==int((b-a).total_seconds()/3600)
        assert eq.index.min()==a+pd.Timedelta(hours=1) and eq.index.max()==b
        assert np.isfinite(eq[['equity','cash','gross']]).all().all()
        np.testing.assert_allclose(eq.equity,eq.cash+eq.gross,atol=1e-6)
        assert abs(eq.equity.iloc[-1]-r.ending_equity)<1e-6
        assert eq.cash.min()>=-1e-6
        checks+=5
        if not (r.strategy.startswith('CRY-') or r.strategy=='COMBINED'): continue
        tp=out/f'{key}__trades.csv'; fp=out/f'{key}__fills.csv'
        if tp.stat().st_size<=1:
            assert int(r.trade_count)==0; continue
        tr=pd.read_csv(tp); fi=pd.read_csv(fp)
        fi['time']=pd.to_datetime(fi.time,utc=True,format='mixed')
        assert len(tr)==int(r.trade_count)
        np.testing.assert_allclose(tr.R,tr.pnl/tr.initial_risk,atol=1e-8)
        np.testing.assert_allclose(eq.equity.iloc[-1]-10000,tr.pnl.sum(),atol=1e-6)
        np.testing.assert_allclose(fi.fee,fi.quantity*fi.price*fee_map[r.scenario],atol=1e-7)
        buys=fi[fi.side=='buy']; sells=fi[fi.side=='sell']
        net=(sells.quantity*sells.price-sells.fee).sum()-(buys.quantity*buys.price+buys.fee).sum()
        assert abs(net-tr.pnl.sum())<1e-5
        for s,g in fi.groupby('symbol'):
            signed=np.where(g.side=='buy',g.quantity,-g.quantity)
            assert np.cumsum(signed).min()>-1e-7
            assert abs(signed.sum())<1e-7
            if r.scenario=='partial_fill':
                if s not in minute: minute[s]=load(s,'1m').quote_volume
                f=g[~g.reason.isin(['boundary','data_gap'])]
                cap=.01*minute[s].reindex(f.time-pd.Timedelta(minutes=1)).to_numpy()
                assert np.all(f.quantity.to_numpy()*f.price.to_numpy()<=cap+1e-5)
        entry=pd.to_datetime(tr.entry_time,utc=True,format='mixed'); exit=pd.to_datetime(tr.exit_time,utc=True,format='mixed')
        assert (entry>=a).all() and (exit<b).all() and (exit>=entry).all()
        for _,t in tr.iterrows():
            et=pd.Timestamp(t.entry_time)
            if t.sid==IDS[0]: assert et.hour%4==0
            assert et.minute==0 and et.second==0
        checks+=10
    result={'status':'PASS','artifact_checks':checks,'synthetic_unit_tests':10,
      'scope':'account arithmetic, trade/fill reconciliation, no short inventory, minute participation cap, timing, source hashes',
      'limitations':'Does not verify historical status/filters, executable spreads/depth, or economic correctness of all provider observations'}
    (out/'validation_checks.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
