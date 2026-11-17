"""Deterministic bar-close signals and minute-resolved spot simulation, v1.1.0."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, math
import numpy as np
import pandas as pd
from download import ROOT, SYMBOLS, load

VERSION='1.1.0'
IDS=['CRY-TF-001','CRY-MR-002','CRY-BO-003']
START=pd.Timestamp('2021-11-17',tz='UTC')
END=pd.Timestamp('2026-11-17',tz='UTC')
WINDOWS={'train':(START,pd.Timestamp('2024-11-17',tz='UTC')),
         'validation':(pd.Timestamp('2024-11-17',tz='UTC'),pd.Timestamp('2025-11-17',tz='UTC')),
         'test':(pd.Timestamp('2025-11-17',tz='UTC'),END)}
STEPS={'BTCUSDT':1e-6,'ETHUSDT':1e-5,'SOLUSDT':1e-3}

def smooth(s,n,alpha=None):
    """SMA-seeded recursive smoother, resetting after missing values."""
    x=s.to_numpy(float); out=np.full(len(x),np.nan); buf=[]; last=np.nan
    a=1/n if alpha is None else alpha
    for i,v in enumerate(x):
        if not np.isfinite(v): buf=[]; last=np.nan; continue
        if not np.isfinite(last):
            buf.append(v)
            if len(buf)==n: last=float(np.mean(buf)); out[i]=last
        else: last=a*v+(1-a)*last; out[i]=last
    return pd.Series(out,index=s.index)

def ema(s,n): return smooth(s,n,2/(n+1))
def atr(b,n=14):
    p=b.close.shift()
    tr=pd.concat([b.high-b.low,(b.high-p).abs(),(b.low-p).abs()],axis=1).max(axis=1)
    tr[b.close.isna()]=np.nan
    return smooth(tr,n)

def features(hourly, overrides=None):
    p={'ema20':20,'ema50':50,'ema200':200,'slope':6,'atr':14,'er':20,
       'mean':20,'breakout':20,'compression':120,'volume':20}
    p.update(overrides or {})
    ix=pd.date_range(hourly.index.min().floor('4h'),END,freq='1h',inclusive='left')
    h=hourly.reindex(ix).copy()
    f=h.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','quote_volume':'sum'})
    counts=h.close.resample('4h').count(); f.loc[counts!=4,:]=np.nan
    valid=f.close.notna(); groups=(~valid).cumsum(); streak=valid.groupby(groups).cumsum()
    warm=(streak>=1000)
    # Recursions reset after missing observations; rolling indicators require full windows.
    for name in ['ema20','ema50','ema200']: f[name]=ema(f.close,p[name])
    f['atr']=atr(f,p['atr'])
    den=f.close.diff().abs().rolling(p['er']).sum()
    f['er']=(f.close.diff(p['er']).abs()/den).where(den!=0,0)
    f['warm']=warm
    four=f.copy(); four.index=four.index+pd.Timedelta(hours=4)
    # Features indexed by the time when their information becomes available.
    regime=four.reindex(ix,method='ffill')
    out={}
    a=f.copy()
    a['signal']=(warm & (a.ema50>a.ema200)&(a.ema200>a.ema200.shift(p['slope']))&
                 (a.close>a.ema200)&(a.close.shift()<=a.ema20.shift())&
                 (a.close>a.ema20)&(a.close>a.high.shift()))
    a['exit']=(a.close<a.ema50)
    a.index=a.index+pd.Timedelta(hours=4)
    out[IDS[0]]=a.reindex(ix)
    one=h.copy(); one.index=one.index+pd.Timedelta(hours=1)
    one=one.reindex(ix)
    # Completed hourly indicators before shifting to availability timestamps.
    mean=h.close.rolling(p['mean']).mean(); sd=h.close.rolling(p['mean']).std(ddof=0)
    z=(h.close-mean)/sd.replace(0,np.nan); bw=4*sd/mean
    ah=atr(h,p['atr'])
    mr=pd.DataFrame(index=h.index)
    mr['signal']=(z.shift()<-2)&(z>=-2)&(z<-1)&(h.close>h.close.shift())
    mr['target']=mean; mr['atr']=ah
    mr.index+=pd.Timedelta(hours=1); mr=mr.reindex(ix)
    mr['signal']=mr.signal.fillna(False)&(regime.er<=0.25)&regime.warm.fillna(False)
    mr['exit']=regime.er>0.40
    out[IDS[1]]=mr
    bo=pd.DataFrame(index=h.index)
    d=h.high.shift().rolling(p['breakout']).max()
    # rank 24/120 for default; generalized nearest-rank for sensitivity.
    quant=bw.shift().rolling(p['compression']).apply(lambda x:np.partition(x,math.ceil(.2*len(x))-1)[math.ceil(.2*len(x))-1],raw=True)
    bo['signal']=(bw.shift()<=quant)&(h.close>d)&(bw>bw.shift())&(
        h.quote_volume>=1.5*h.quote_volume.shift().rolling(p['volume']).median())
    bo['D']=d; bo['atr']=ah
    bo.index+=pd.Timedelta(hours=1); bo=bo.reindex(ix)
    bo['signal']=bo.signal.fillna(False)&(regime.close>regime.ema50)&regime.warm.fillna(False)
    out[IDS[2]]=bo
    daily=h.quote_volume.resample('1D').sum(min_count=24)
    dv=daily.rolling(30).median(); dv.index+=pd.Timedelta(days=1)
    daily_med=dv.reindex(ix,method='ffill')
    q24=h.quote_volume.rolling(24).sum().shift()
    qmin=h.quote_volume.rolling(24).min().shift()
    liq=(q24>=20e6)&(daily_med>=20e6)&(qmin>=1e5)
    for sid in IDS:
        out[sid]['signal']=out[sid].signal.fillna(False)&liq&one.close.notna()&regime.warm.fillna(False)
        out[sid]['qmin']=qmin
    return h,out,regime

def audit(symbol,h,m):
    result={'symbol':symbol,'venue':'Binance.com spot','timezone':'UTC','intervals':{}}
    for iv,df,freq in [('1h',h,'1h'),('1m',m,'1min')]:
        expected=pd.date_range(max(df.index.min(),START),min(df.index.max()+pd.Timedelta(freq),END),freq=freq,inclusive='left')
        missing=expected.difference(df.index)
        invalid=(~np.isfinite(df.to_numpy()).all(axis=1))|(df[['open','high','low','close']]<=0).any(axis=1)|(
            df.high<df[['open','low','close']].max(axis=1))|(
            df.low>df[['open','high','close']].min(axis=1))|(df[['volume','quote_volume','trades']]<0).any(axis=1)
        jump=df.close.pct_change(fill_method=None).abs()>.2
        wide=(df.high/df.low-1)>.3
        sus=df.index[jump|wide]
        result['intervals'][iv]={'rows':len(df),'first':str(df.index.min()),'last_open':str(df.index.max()),
          'expected_evaluation_rows':len(expected),'missing_count':len(missing),
          'missing_timestamps':[str(x) for x in missing[:200]],'duplicate_count':int(df.index.duplicated().sum()),
          'invalid_count':int(invalid.sum()),'zero_volume_count':int((df.volume==0).sum()),
          'suspicious_count':len(sus),'suspicious_timestamps':[str(x) for x in sus[:200]]}
        if invalid.any() or df.index.duplicated().any(): raise ValueError(f'Invalid/duplicate observations: {symbol} {iv}')
    agg=m.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last','quote_volume':'sum'})
    n=m.close.resample('1h').count(); both=agg.join(h,lsuffix='_m',rsuffix='_h',how='inner'); both=both[n.reindex(both.index)==60]
    mismatches={}
    for c in ['open','high','low','close','quote_volume']:
        bad=~np.isclose(both[c+'_m'],both[c+'_h'],rtol=1e-7,atol=1e-6)
        mismatches[c]=int(bad.sum())
    result['aggregation_mismatches']=mismatches
    return result

class Market:
    def __init__(self, with_minutes=True):
        self.h={}; self.plans={}; self.minute={}; self.audit=[]
        for sym in SYMBOLS:
            raw=load(sym,'1h'); minute=load(sym,'1m') if with_minutes else None
            if minute is not None: self.audit.append(audit(sym,raw,minute))
            self.h[sym],self.plans[sym],_=features(raw)
            if minute is not None:
                self.minute[sym]=(minute.index.asi8,minute[['open','high','low','close','quote_volume']].to_numpy())
            print('Loaded and audited',sym,len(raw),0 if minute is None else len(minute),flush=True)
        (ROOT/'results'/'data_audit.json').write_text(json.dumps(self.audit,indent=2))
        b=self.h['BTCUSDT']; daily=b.close.resample('1D').last(); ma=daily.rolling(200).mean()
        vol=daily.pct_change(fill_method=None).rolling(30).std()*np.sqrt(365.25)
        reg=pd.Series(np.where(daily>ma,'bull','bear'),index=daily.index)+'_'+pd.Series(np.where(vol>.6,'highvol','lowvol'),index=daily.index)
        reg[ma.isna()|vol.isna()]='unknown'; reg.index+=pd.Timedelta(days=1)
        self.regime=reg

    def minutes(self,sym,t):
        ts,arr=self.minute[sym]; start=t.value; end=start+3600*10**9
        lo,hi=np.searchsorted(ts,[start,end]); previous=arr[lo-1,4] if lo else 0
        return ts[lo:hi],arr[lo:hi],previous

@dataclass
class Position:
    symbol:str; sid:str; q:float; initial_q:float; entry:float; stop:float; initial_stop:float
    target:float; D:float; risk:float; entry_time:pd.Timestamp; entry_fee:float
    highest:float; bars:int=0; trailing:bool=False; pending:bool=False
    proceeds:float=0.; exit_fees:float=0.; exit_notional:float=0.; last_exit:str=''

def floor_qty(q,step): return math.floor((q+1e-12)/step)*step
def stop_round(x): return math.floor(x*100)/100
def target_round(x): return math.ceil(x*100)/100

def simulate(market,sids,start,end,fee=.001,adverse=.0005,partial=False,atr_multipliers=None):
    """Returns hourly marked account and completed trades; test data never tune rules."""
    mult={'CRY-TF-001':(2.5,3.),'CRY-MR-002':(1.5,0.),'CRY-BO-003':(2.,2.)}
    mult.update(atr_multipliers or {})
    ix=pd.date_range(start,end,freq='1h',inclusive='left')
    h={s:market.h[s].reindex(ix).to_dict('list') for s in SYMBOLS}
    # Access plans as records, converting NA signal/exit explicitly to false.
    plans={}
    for s in SYMBOLS:
        for sid in sids:
            frame=market.plans[s][sid].reindex(ix)
            plans[s,sid]={c:frame[c].to_numpy() for c in frame}
    cash=10000.; positions={}; cooldown={}; trades=[]; fills=[]; rows=[]; events=[]
    realized=0.; entry_risk=0.; turnover=0.; counters={'partial_entries':0,'partial_exits':0,'missing_execution_hours':0,'boundary_uncapped':0,'signal_candidates':0,'accepted_entries':0}
    last_prices={s:float(market.h[s].loc[:start-pd.Timedelta(hours=1),'close'].dropna().iloc[-1]) for s in SYMBOLS}

    def close(pos,ref,t,reason,cap=math.inf):
        nonlocal cash,realized,turnover
        price=ref*(1-adverse); qty=min(pos.q,cap/max(price,1e-20))
        if qty<=1e-12: return
        notional=qty*price; cost=fee*notional; cash+=notional-cost
        pos.q-=qty; pos.proceeds+=notional-cost; pos.exit_fees+=cost; pos.exit_notional+=notional
        turnover+=notional; pos.last_exit=reason
        fills.append({'time':t,'symbol':pos.symbol,'sid':pos.sid,'side':'sell','quantity':qty,'price':price,'fee':cost,'reason':reason})
        if pos.q>1e-10:
            counters['partial_exits']+=1
            if reason!='target': pos.pending=True
            return
        pnl=pos.proceeds-pos.initial_q*pos.entry-pos.entry_fee
        trades.append({'sid':pos.sid,'symbol':pos.symbol,'entry_time':pos.entry_time,'exit_time':t,
          'quantity':pos.initial_q,'entry_price':pos.entry,'exit_vwap':pos.exit_notional/pos.initial_q,
          'initial_risk':pos.risk,'pnl':pnl,'R':pnl/pos.risk,'reason':reason,
          'holding_hours':(t-pos.entry_time).total_seconds()/3600,
          'fees':pos.entry_fee+pos.exit_fees})
        realized+=pnl
        dur=4 if pos.sid==IDS[0] else 1
        cooldown[pos.symbol]=t.ceil(f'{dur}h')+pd.Timedelta(hours=dur)
        positions.pop(pos.symbol,None)

    for i,t in enumerate(ix):
        realized=0.; entry_risk=0.; turn_start=turnover
        for sym in SYMBOLS:
            op=h[sym]['open'][i]
            if np.isfinite(op): last_prices[sym]=op
        # First process opening exits for all assets, then freeze allocation equity.
        for sym,pos in list(positions.items()):
            op=h[sym]['open'][i]
            if not np.isfinite(op): continue
            if pos.pending or op<=pos.stop:
                _,_,prev=market.minutes(sym,t)
                close(pos,op,t,'stop_gap' if op<=pos.stop else 'scheduled',.01*prev if partial else math.inf)
        equity=cash+sum(p.q*last_prices[s] for s,p in positions.items())
        reserved=sum(p.risk for p in positions.values())
        for sid in sorted(sids):
            for sym in SYMBOLS:
                plan=plans[sym,sid]
                signal=plan['signal'][i]
                if pd.isna(signal) or not signal: continue
                counters['signal_candidates']+=1
                if sym in positions or len(positions)>=3 or t<cooldown.get(sym,start): continue
                op=h[sym]['open'][i]; at=plan['atr'][i]; qmin=plan['qmin'][i]
                if not np.isfinite(op) or not np.isfinite(at) or at<=0: continue
                price=op*(1+adverse); stop=stop_round(price-mult[sid][0]*at)
                if stop<=0 or price<=stop: continue
                target=math.inf; d_level=np.nan
                if sid==IDS[1]:
                    target=target_round(plan['target'][i])
                    if target<=price or (target-price)/(price-stop)<1: continue
                if sid==IDS[2]:
                    target=target_round(price+3*(price-stop)); d_level=plan['D'][i]
                unit=price-stop+fee*price+(fee+adverse)*stop
                budget=max(0,min(.01*equity,.03*equity-reserved))
                desired=floor_qty(min(budget/unit,.33*equity/price,cash/(price*(1+fee)),.001*qmin/price),STEPS[sym])
                qty=desired
                if partial:
                    ts,arr,prev=market.minutes(sym,t)
                    if not len(ts) or ts[0]!=t.value: continue
                    qty=floor_qty(min(qty,.01*prev/price),STEPS[sym])
                if qty*price<10 or qty<=0: continue
                if qty<desired: counters['partial_entries']+=1
                risk=qty*unit; entryfee=qty*price*fee; cash-=qty*price+entryfee; reserved+=risk; entry_risk+=risk
                p=Position(sym,sid,qty,qty,price,stop,stop,target,d_level,risk,t,entryfee,price)
                positions[sym]=p; turnover+=qty*price; counters['accepted_entries']+=1
                fills.append({'time':t,'symbol':sym,'sid':sid,'side':'buy','quantity':qty,'price':price,'fee':entryfee,'reason':'signal'})
        for sym,pos in list(positions.items()):
            ts,arr,previous=market.minutes(sym,t)
            if len(ts)!=60:
                counters['missing_execution_hours']+=1
                events.append({'time':str(t),'symbol':sym,'kind':'minute_gap_while_invested','minute_count':len(ts)})
                if not len(ts): pos.pending=True; continue
            gap_resume=np.flatnonzero(np.r_[ts[0]!=t.value,np.diff(ts)!=60*10**9])
            # Full-fill path skips minutes until the earliest possible trigger.
            if not partial and not pos.pending:
                hits=np.flatnonzero((arr[:,2]<=pos.stop)|(arr[:,1]>pos.target))
                if len(gap_resume): hits=np.unique(np.r_[hits,gap_resume])
                if len(hits):
                    j=int(hits[0]); op,hi,lo,cl,qv=arr[j]; tm=pd.Timestamp(ts[j],tz='UTC')
                    if j in gap_resume: close(pos,op,tm,'data_gap')
                    elif lo<=pos.stop: close(pos,min(op,pos.stop),tm,'stop')
                    else: close(pos,pos.target,tm,'target')
            else:
                for j,(op,hi,lo,cl,qv) in enumerate(arr):
                    if sym not in positions: break
                    tm=pd.Timestamp(ts[j],tz='UTC'); cap=.01*(previous if j==0 else arr[j-1,4])
                    if j in gap_resume:
                        close(pos,op,tm,'data_gap'); break
                    # Opening partial exit already consumed this minute's capacity.
                    if j==0 and fills and fills[-1]['time']==t and fills[-1]['side']=='sell' and fills[-1]['symbol']==sym: continue
                    if pos.pending: close(pos,op,tm,'pending_market',cap)
                    elif lo<=pos.stop: close(pos,min(op,pos.stop),tm,'stop',cap)
                    elif hi>pos.target: close(pos,pos.target,tm,'target',cap)
            if sym not in positions: continue
            if ts[-1]!=t.value+59*60*10**9: pos.pending=True
            pos.highest=max(pos.highest,float(np.max(arr[:,1])))
            dur=4 if pos.sid==IDS[0] else 1
            available=t+pd.Timedelta(hours=1)
            if available.hour%dur: continue
            pos.bars+=1
            # Current native-bar indicators become visible at 'available'.
            fr=market.plans[sym][pos.sid]
            if available not in fr.index: continue
            row=fr.loc[available]; at=row.get('atr',np.nan); cl=h[sym]['close'][i]
            if pos.sid==IDS[0] and np.isfinite(at):
                pos.stop=max(pos.stop,stop_round(pos.highest-mult[pos.sid][1]*at))
            elif pos.sid==IDS[2] and np.isfinite(at):
                if cl>=pos.entry+(pos.entry-pos.initial_stop): pos.trailing=True
                if pos.trailing: pos.stop=max(pos.stop,stop_round(pos.highest-mult[pos.sid][1]*at))
            exit_flag=row.get('exit',False)
            if pd.isna(exit_flag): exit_flag=False
            if pos.sid==IDS[2]: exit_flag=cl<pos.D
            limit={IDS[0]:60,IDS[1]:12,IDS[2]:24}[pos.sid]
            if exit_flag or pos.bars>=limit: pos.pending=True
        for sym in SYMBOLS:
            cl=h[sym]['close'][i]
            if np.isfinite(cl): last_prices[sym]=cl
        # Flat window boundaries prevent trades leaking between split samples.
        if i==len(ix)-1:
            for sym,p in list(positions.items()):
                if partial: counters['boundary_uncapped']+=1
                close(p,last_prices[sym],end-pd.Timedelta(nanoseconds=1),'boundary')
        gross=sum(p.q*last_prices[s] for s,p in positions.items())
        eq=cash+gross
        rows.append({'time':t+pd.Timedelta(hours=1),'equity':eq,'cash':cash,'gross':gross,'positions':len(positions),
                     'realized_pnl':realized,'entry_risk':entry_risk,'turnover':turnover-turn_start})
        if cash<-.001 or len(positions)>3: raise AssertionError('Capital constraint violated')
        if sum(p.risk for p in positions.values())>.03*equity+1e-5 and entry_risk>0: raise AssertionError('Risk constraint violated')
    return pd.DataFrame(rows).set_index('time'),pd.DataFrame(trades),pd.DataFrame(fills),dict(counters=counters,events=events)

def daily_frame(eq,start):
    # hourly labels are end timestamps, assign 00:00 end to preceding UTC day.
    x=eq.copy(); x.index=x.index-pd.Timedelta(nanoseconds=1)
    end=x.equity.resample('1D').last()
    ret=end.pct_change(fill_method=None); ret.iloc[0]=end.iloc[0]/10000-1
    d=pd.DataFrame({'equity':end,'return':ret,'pnl':end.diff()})
    d.iloc[0,d.columns.get_loc('pnl')]=end.iloc[0]-10000
    d['risk']=x.entry_risk.resample('1D').sum()
    return d

def metrics(eq,tr,start,end):
    d=daily_frame(eq,start); ret=d['return']; years=(end-start).total_seconds()/(365.25*86400)
    hourly=pd.concat([pd.Series([10000.],index=[start]),eq.equity]); peak=hourly.cummax(); dd=hourly/peak-1
    worst=dd.idxmin(); peak_time=hourly.loc[:worst].idxmax(); recovered=hourly.loc[worst:][hourly.loc[worst:]>=hourly.loc[peak_time]]
    recovery_end=recovered.index[0] if len(recovered) else end
    v=ret.std(ddof=1)*np.sqrt(365.25); downside=np.sqrt(np.mean(np.minimum(ret,0)**2))*np.sqrt(365.25)
    pnl=tr.pnl if len(tr) else pd.Series(dtype=float)
    gains=pnl[pnl>0].sum(); losses=-pnl[pnl<0].sum()
    return {'CAGR':(eq.equity.iloc[-1]/10000)**(1/years)-1,'annual_volatility':v,
      'Sharpe':ret.mean()*365.25/v if v>0 else None,
      'Sortino':ret.mean()*365.25/downside if downside>0 else None,
      'max_drawdown':float(dd.min()),'drawdown_peak':str(peak_time),'drawdown_trough':str(worst),
      'recovery_end':str(recovery_end),'recovery_days':(recovery_end-peak_time).total_seconds()/86400,
      'recovery_censored':not bool(len(recovered)),
      'win_rate':float((pnl>0).mean()) if len(tr) else None,
      'profit_factor':float(gains/losses) if losses>0 else None,
      'expectancy_R':float(tr.R.mean()) if len(tr) else None,
      'aggregate_pnl_per_risk':float(tr.pnl.sum()/tr.initial_risk.sum()) if len(tr) else None,
      'mean_gross_exposure':float((eq.gross/eq.equity).mean()),
      'time_in_market':float((eq.positions>0).mean()),
      'annual_two_way_turnover':float(eq.turnover.sum()/eq.equity.mean()/years),
      'trade_count':len(tr),'daily_observations':len(d),'ending_equity':float(eq.equity.iloc[-1]),
      'net_pnl':float(eq.equity.iloc[-1]-10000),'fees':float(tr.fees.sum()) if len(tr) else 0,
      'forced_boundary_trades':int((tr.reason=='boundary').sum()) if len(tr) else 0}

def bootstrap(eq,start,reps=10000):
    d=daily_frame(eq,start); arr=d[['pnl','risk']].to_numpy(); n=len(arr); rng=np.random.default_rng(20261117)
    vals=[]
    for _ in range(reps):
        starts=rng.integers(0,n,size=math.ceil(n/14)); ix=((starts[:,None]+np.arange(14))%n).ravel()[:n]
        p,r=arr[ix].sum(axis=0)
        if r>0: vals.append(p/r)
    if not vals: return {'valid_replications':0,'lower_adjusted':None,'ci95':[None,None]}
    return {'valid_replications':len(vals),'lower_adjusted':float(np.quantile(vals,.0167)),
            'ci95':np.quantile(vals,[.025,.975]).tolist(),'estimand':'total_net_PnL/total_initial_reserved_risk'}

def benchmark(market,start,end,kind,fee=.001,adverse=.0005):
    ix=pd.date_range(start,end,freq='1h',inclusive='left'); cash=10000.; qty={s:0. for s in SYMBOLS}; rows=[]
    b=market.h['BTCUSDT']; daily=b.close.resample('1D').last(); signal=(daily>daily.rolling(200).mean()); signal.index+=pd.Timedelta(days=1)
    turn=0.
    valuation={s:market.h[s].close.ffill() for s in SYMBOLS}
    for i,t in enumerate(ix):
        old=turn
        if kind=='equal_weight' and i==0:
            for s in SYMBOLS:
                price=market.h[s].loc[t,'open']*(1+adverse); allocation=10000/3
                qty[s]=allocation/(price*(1+fee)); cash-=allocation; turn+=qty[s]*price
        elif kind=='btc_sma200' and t.hour==0:
            want=bool(signal.get(t,False)); op=market.h['BTCUSDT'].loc[t,'open']
            if want and qty['BTCUSDT']==0:
                price=op*(1+adverse); q=cash/(price*(1+fee)); qty['BTCUSDT']=q; turn+=q*price; cash=0.
            elif not want and qty['BTCUSDT']>0:
                val=qty['BTCUSDT']*op*(1-adverse); cash+=val*(1-fee); turn+=val; qty['BTCUSDT']=0.
        gross=sum(qty[s]*valuation[s].loc[t] for s in SYMBOLS)
        if i==len(ix)-1:
            for s in SYMBOLS:
                val=qty[s]*market.h[s].loc[t,'close']*(1-adverse); cash+=val*(1-fee); turn+=val; qty[s]=0.
            gross=0.
        rows.append({'time':t+pd.Timedelta(hours=1),'equity':cash+gross,'cash':cash,'gross':gross,'positions':sum(q>0 for q in qty.values()),'entry_risk':0.,'realized_pnl':0.,'turnover':turn-old})
    return pd.DataFrame(rows).set_index('time')
