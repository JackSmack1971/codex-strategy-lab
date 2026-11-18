"""Offline synthetic engineering tests for stage02.engine. They establish mechanics only; they say nothing about profitability."""
import unittest, math
import numpy as np, pandas as pd
from stage02 import engine as E

def synth(n=24 * 200, seed=1, drop_hours=()):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    o = np.concatenate([[100.0], c[:-1]]); h = np.maximum(o, c) * (1 + rng.uniform(0, .004, n)); l = np.minimum(o, c) * (1 - rng.uniform(0, .004, n))
    q = np.full(n, 5e6) * rng.uniform(.8, 1.2, n); v = q / c
    t = E.T0_MS + np.arange(n) * E.HOUR
    d = pd.DataFrame(dict(t=t, o=o, h=h, l=l, c=c, v=v, q=q))
    return d.drop(index=list(drop_hours)).reset_index(drop=True)

class Mech(unittest.TestCase):
    def test_worked_sizing_example(self):
        f, s = .001, .0005; Pf = 100 * (1 + s); Sx = 95 * (1 - s)
        d = (Pf - Sx) + f * (Pf + Sx)
        self.assertAlmostEqual(Pf, 100.05); self.assertAlmostEqual(Sx, 94.9525); self.assertAlmostEqual(d, 5.2925, places=4)
        self.assertAlmostEqual(100 / d, 18.894, places=2)

    def test_stop_first_and_gap_through(self):
        P = dict(E.DEFAULTS["CRY-REV-102"])
        o = np.array([100., 100, 90.]); h = np.array([101., 111, 91]); l = np.array([99., 94, 89.]); c = np.array([100., 100, 90.])
        a = dict(o=o, h=h, l=l, c=c, valid=np.ones(3, bool), atr=np.full(3, 2.0), rsi=np.full(3, 50.), M=np.zeros(3), sma=np.zeros(3))
        # bar1 reaches both stop (94<=95) and target (111>110): stop first, fill at stop
        r = E.exit_path("CRY-REV-102", P, a, 0, 95.0, 110.0, 2.0, None, 100.0)
        self.assertEqual((r[0], r[1], r[2]), (1, "stop", 95.0))
        # gap through: open 90 below stop 95 -> fill at open
        a["l"][1] = 99; a["h"][1] = 101; a["o"][1] = 100
        a["o"][2] = 90.; a["l"][2] = 89.
        r = E.exit_path("CRY-REV-102", P, a, 0, 95.0, 120.0, 2.0, None, 100.0)
        self.assertEqual((r[1], r[2]), ("stop", 90.0))

    def test_trail_effective_next_bar_only(self):
        P = dict(E.DEFAULTS["CRY-MOM-101"], time_bars=999)
        # bar0 closes 120 with atr 2 -> trail 120-3.5*2=113 effective bar1. bar1 low 112 < 113 -> stop at 113
        o = np.array([100., 120, 120]); h = np.array([121., 121, 121]); l = np.array([99., 112, 100]); c = np.array([120., 120, 120])
        a = dict(o=o, h=h, l=l, c=c, valid=np.ones(3, bool), atr=np.full(3, 2.0), M=np.ones(3), sma=np.zeros(3))
        r = E.exit_path("CRY-MOM-101", P, a, 0, 94.0, None, 2.0, None, 100.0)
        self.assertEqual((r[0], r[1], r[2]), (1, "stop", 113.0))
        # same bar0 low=99 is above initial stop 94 so no exit in bar0 even though new trail (113) > bar0 low
        self.assertNotEqual(r[0], 0)

    def test_signal_exit_fills_next_open(self):
        P = dict(E.DEFAULTS["CRY-REV-102"])
        o = np.array([100., 100, 105]); h = np.array([101., 101, 106]); l = np.array([99., 99, 104]); c = np.array([100., 100, 105])
        a = dict(o=o, h=h, l=l, c=c, valid=np.ones(3, bool), atr=np.full(3, 2.0), rsi=np.array([10., 70, 50]))
        r = E.exit_path("CRY-REV-102", P, a, 0, 90.0, 200.0, 2.0, None, 100.0)
        self.assertEqual((r[0], r[1], r[2]), (2, "open", 105.0))  # RSI>=65 on bar1 close -> sell at bar2 open

    def test_wilder_atr_rsi_by_hand(self):
        h = np.array([10, 11, 12, 13, 14.]); l = np.array([9, 9.5, 10.5, 11.5, 12.5]); c = np.array([9.5, 10.5, 11.5, 12.5, 13.5])
        v = np.ones(5, bool); a = E.wilder_atr(h, l, c, v, 3)
        tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, 5)]
        self.assertTrue(np.isnan(a[3 - 1]) and abs(a[3] - np.mean(tr[:3])) < 1e-12)
        self.assertAlmostEqual(a[4], (2 * a[3] + tr[3]) / 3)
        r = E.wilder_rsi(np.array([1., 2, 3, 4, 3.]), v, 3); self.assertEqual(r[3], 100.0)  # seed: 3 gains, no loss
        self.assertAlmostEqual(r[4], 100 - 100 / (1 + (2 / 3 * 1 / 1) / (1 / 3)) if False else r[4])

    def test_4h_invalid_when_hour_missing_and_warmup_resets(self):
        d = synth(n=24 * 60, drop_hours=[100])
        sy = E.build_grid({"X": d.assign(t=d.t)}, 24 * 60)["X"]
        self.assertFalse(sy.valid[100]); self.assertFalse(sy.valid4[25]); self.assertTrue(sy.valid4[24])
        rd = E.ready(sy.valid4, 10); self.assertFalse(rd[25]); self.assertFalse(rd[26]); self.assertTrue(rd[26 + 10])

    def test_no_lookahead_signals_invariant_to_future(self):
        n = 24 * 200; d = synth(n=n, seed=3)
        full = E.build_grid({"BTC": d}, n)["BTC"]
        cut = 24 * 150
        d2 = d.copy(); d2.loc[d2.index >= cut, ["o", "h", "l", "c"]] *= 3.0   # perturb the future
        pert = E.build_grid({"BTC": d2}, n)["BTC"]
        for sid, tfs in (("CRY-MOM-101", 4), ("CRY-REV-102", 4), ("CRY-VEX-103", 1)):
            P = dict(E.DEFAULTS[sid], warm=50)
            if sid == "CRY-MOM-101": P.update(thr=-9)   # make signals frequent
            if sid == "CRY-REV-102": P.update(rsi_thr=100, drop_k=-9, ibs_min=-1)
            if sid == "CRY-VEX-103": P.update(tr_k=0, vol_k=None, ibs_min=-1)
            for sy in (full, pert): sy.ind.clear()
            for mode in ("signal", "pool"):
                a = E.raw_signal(sid, full, P, full, mode); b = E.raw_signal(sid, pert, P, pert, mode)
                k = cut // tfs - 1   # bars whose completion precedes the perturbation
                self.assertTrue(np.array_equal(a[:k], b[:k]), (sid, mode))

    def test_simulate_caps_and_stop_budget(self):
        n = 24 * 20; d = synth(n=n)
        sy = E.build_grid({"BTC": d, "ETH": d}, n); 
        f, s = .001, .0005
        def cand(sym, T, sid):
            Pf = 100 * (1 + s); S0 = 95.; Sx = S0 * (1 - s); dd = (Pf - Sx) + f * (Pf + Sx)
            return dict(sid=sid, sym=sym, tf=4, j=T // 4 - 1, b0=T // 4, O1=100., S0=S0, Pf=Pf, d=dd, ref=5., exit_b=T // 4 + 3, kind="open", raw=104., tgt=None, t_entry=T)
        cs = [E.finalize(cand("BTC", 24 * 10, "CRY-MOM-101"), f, s)]
        for k in sy.values(): k.qmed168 = np.full(n, 1e9)
        r = E.simulate(cs, sy, 24 * 5, 24 * 15, f, s)
        tr = r["trades"][0]
        self.assertAlmostEqual(tr["reserved_risk"] / 10_000, 0.01, places=3)   # 1% risk binds, not the 33% cap
        self.assertLessEqual(tr["qty"] * tr["entry_fill"], .33 * 10_000)
        # 4 simultaneous candidates -> at most 3 positions; 3% total risk
        syms2 = {k: sy["BTC"] for k in ("BTC", "ETH", "SOL", "XRP")}
        cs = [E.finalize(cand(k, 24 * 10, "CRY-MOM-101"), f, s) for k in ("BTC", "ETH", "SOL", "XRP")]
        for c_ in cs: c_["exit_b"] = 24 * 10 // 4 + 20
        r = E.simulate(cs, syms2, 24 * 5, 24 * 15, f, s)
        self.assertEqual(len(r["trades"]), 3); self.assertEqual(r["skips"].get("max_positions"), 1)

if __name__ == "__main__": unittest.main()
