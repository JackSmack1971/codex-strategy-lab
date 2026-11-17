"""Synthetic correctness tests, never reported as historical performance."""
import unittest
from types import SimpleNamespace
import numpy as np
import pandas as pd
from lab import IDS, SYMBOLS, simulate, ema, atr, metrics

class EngineTests(unittest.TestCase):
    def market(self,hours=5,kind='stop',qv=1e6):
        start=pd.Timestamp('2024-01-01',tz='UTC'); ix=pd.date_range(start,periods=hours,freq='1h')
        full=pd.date_range(start-pd.Timedelta(hours=1),periods=hours+2,freq='1h')
        h={s:pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.},index=full) for s in SYMBOLS}
        plans={}
        for s in SYMBOLS:
            plans[s]={}
            for sid in IDS:
                plans[s][sid]=pd.DataFrame({'signal':False,'atr':1.,'qmin':1e6,'target':103.,'D':99.,'exit':False},index=full)
        plans['BTCUSDT'][IDS[1]].loc[ix[0],'signal']=True
        if kind=='scheduled': plans['BTCUSDT'][IDS[1]].loc[ix[1],'exit']=True
        mix=pd.date_range(start,periods=hours*60,freq='1min')
        arrays={}
        for s in SYMBOLS:
            arr=np.tile([100.,100.5,99.5,100.,qv],(hours*60,1))
            if s=='BTCUSDT' and kind=='stop': arr[1,1:3]=[104.,97.]
            arrays[s]=(mix.asi8,arr)
        def minutes(sym,t):
            ts,a=arrays[sym]; lo,hi=np.searchsorted(ts,[t.value,(t+pd.Timedelta(hours=1)).value])
            return ts[lo:hi],a[lo:hi],qv
        return SimpleNamespace(h=h,plans=plans,minutes=minutes),start,start+pd.Timedelta(hours=hours)

    def test_seeded_ema(self):
        r=ema(pd.Series([1.,2.,3.,4.]),3)
        self.assertTrue(np.isnan(r.iloc[1])); self.assertAlmostEqual(r.iloc[2],2.); self.assertAlmostEqual(r.iloc[3],3.)

    def test_indicator_reset(self):
        r=ema(pd.Series([1.,2.,3.,np.nan,5.,6.,7.]),3)
        self.assertTrue(np.isnan(r.iloc[5])); self.assertAlmostEqual(r.iloc[6],6.)

    def test_stop_first_and_costs(self):
        m,a,b=self.market(); e,t,f,c=simulate(m,[IDS[1]],a,b)
        self.assertEqual(len(t),1); self.assertEqual(t.iloc[0].reason,'stop')
        self.assertLess(t.iloc[0].pnl,0); self.assertLessEqual(t.iloc[0].initial_risk,100)
        self.assertAlmostEqual(e.equity.iloc[-1]-10000,t.pnl.sum(),places=6)
        self.assertEqual(t.iloc[0].exit_time,a+pd.Timedelta(minutes=1))

    def test_close_signal_next_open(self):
        m,a,b=self.market(kind='scheduled'); e,t,f,c=simulate(m,[IDS[1]],a,b)
        self.assertEqual(t.iloc[0].exit_time,a+pd.Timedelta(hours=1))
        self.assertEqual(t.iloc[0].reason,'scheduled')

    def test_partial_fill_and_cash(self):
        m,a,b=self.market(kind='quiet',qv=10000); e,t,f,c=simulate(m,[IDS[1]],a,b,partial=True)
        self.assertEqual(c['counters']['partial_entries'],1)
        buy=f[f.side=='buy'].iloc[0]
        self.assertLessEqual(buy.quantity*buy.price,100.0001)
        self.assertGreaterEqual(e.cash.min(),0)

    def test_no_signal_no_trades(self):
        m,a,b=self.market(); m.plans['BTCUSDT'][IDS[1]]['signal']=False
        e,t,f,c=simulate(m,[IDS[1]],a,b)
        self.assertTrue(t.empty); self.assertTrue((e.equity==10000).all())

    def test_one_full_bar_cooldown_after_boundary_exit(self):
        m,a,b=self.market(kind='scheduled')
        m.plans['BTCUSDT'][IDS[1]].loc[a+pd.Timedelta(hours=2),'signal']=True
        e,t,f,c=simulate(m,[IDS[1]],a,b)
        buys=f[f.side=='buy']
        self.assertEqual(len(buys),2)
        self.assertEqual(buys.iloc[1].time,a+pd.Timedelta(hours=2))

    def test_future_prices_do_not_change_prior_fills(self):
        m,a,b=self.market(kind='quiet'); e,t,f,c=simulate(m,[IDS[1]],a,b)
        m.h['BTCUSDT'].loc[a+pd.Timedelta(hours=3):,'close']=1000.
        e2,t2,f2,c2=simulate(m,[IDS[1]],a,b)
        pd.testing.assert_frame_equal(e.iloc[:3],e2.iloc[:3])
        pd.testing.assert_frame_equal(f[f.time<a+pd.Timedelta(hours=3)],f2[f2.time<a+pd.Timedelta(hours=3)])

    def test_gap_exits_at_resume_not_before_missing_information(self):
        m,a,b=self.market(kind='quiet'); original=m.minutes
        def minutes(s,t):
            ts,arr,prev=original(s,t)
            if s=='BTCUSDT' and t==a:
                return np.delete(ts,15),np.delete(arr,15,axis=0),prev
            return ts,arr,prev
        m.minutes=minutes
        e,t,f,c=simulate(m,[IDS[1]],a,b)
        self.assertEqual(t.iloc[0].exit_time,a+pd.Timedelta(minutes=16))
        self.assertEqual(t.iloc[0].reason,'data_gap')

    def test_partial_exit_capacity_not_reused_across_assets(self):
        m,a,b=self.market(kind='scheduled',qv=100.)
        m.plans['ETHUSDT'][IDS[1]].loc[a,'signal']=True
        m.plans['ETHUSDT'][IDS[1]].loc[a+pd.Timedelta(hours=1),'exit']=True
        original=m.minutes
        def minutes(s,t):
            ts,arr,prev=original(s,t)
            return ts,arr,1e9 if t==a else 100.
        m.minutes=minutes
        e,t,f,c=simulate(m,[IDS[1]],a,b,partial=True)
        sells=f[(f.side=='sell')&(f.time==a+pd.Timedelta(hours=1))]
        for sym,g in sells.groupby('symbol'):
            self.assertLessEqual((g.quantity*g.price).sum(),1.00001)

if __name__=='__main__': unittest.main()
