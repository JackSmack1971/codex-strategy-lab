"""Offline synthetic tests for Stage 03 risk helpers. These test arithmetic only; they say nothing about profitability."""
import unittest
from types import SimpleNamespace as NS
import numpy as np
from stage03 import core as C

def tr(pnl, entry=0, exit_=10, kind="stop", tf=1, sym="X", q=10.0, risk=100.0):
    return dict(pnl=pnl, R=pnl / risk, entry_hour=entry, exit_hour=exit_, kind=kind, tf=tf, symbol=sym, qty=q, reserved_risk=risk)

class T(unittest.TestCase):
    def test_exit_end(self):
        self.assertEqual(C.exit_end(tr(0, exit_=10, kind="stop", tf=4)), 14)
        self.assertEqual(C.exit_end(tr(0, exit_=10, kind="open", tf=4)), 10)
        self.assertEqual(C.exit_end(tr(0, exit_=10, kind="forced")), 11)

    def test_var_es(self):
        r = np.array([-0.1] * 10 + [0.1] * 90)
        v, e = C.var_es(r, .95); self.assertAlmostEqual(v, 0.1); self.assertAlmostEqual(e, 0.1)
        r2 = np.concatenate([[-0.5], np.zeros(99)]); v2, e2 = C.var_es(r2, .99); self.assertGreaterEqual(e2, v2)

    def test_loss_runs_and_summary(self):
        seq = [-1, -1, 2, -1, -1, -1]; trades = [tr(p, entry=i, exit_=i + 1, kind="open") for i, p in enumerate(seq)]
        runs = C.loss_runs(trades); self.assertEqual([x[0] for x in runs], [2, 3])
        s = C.streak_summary([trades]); self.assertEqual((s["max_run"], s["runs_ge5"], s["n_losses"]), (3, 0, 5))

    def test_gap_shock_arithmetic(self):
        sy = NS(cff=np.full(20, 100.0), l=np.full(20, 100.0), valid=np.ones(20, bool))
        res = dict(ws=0, we=20, trades=[tr(0, entry=2, exit_=6, kind="open")], equity=np.full(20, 10_000.0))
        ls = C.gap_shock(res, {"X": sy}, 0.20, 0.0, 0.001, 0.0005)
        fill = 100 * 0.8 * (1 - 0.0005); expect = 10 * (100 - fill * (1 - 0.001)) / 10_000
        self.assertAlmostEqual(ls[3], expect, places=9); self.assertEqual(ls[0], 0.0); self.assertEqual(ls[6], 0.0)

    def test_fwd_min_low_and_freeze(self):
        sy = NS(cff=np.array([10., 9, 8, 7, 6]), l=np.array([10., 9, 8, 7, 6]), valid=np.ones(5, bool))
        fm = C.fwd_min_low(sy, 2); self.assertEqual(fm[0], 8.0); self.assertEqual(fm[3], 6.0); self.assertTrue(np.isnan(fm[4]))
        res = dict(ws=0, we=5, trades=[tr(0, entry=0, exit_=2, kind="open", q=1.0)], equity=np.full(5, 1000.0))
        ls = C.freeze_loss(res, {"X": sy}, 2, 0.0, 0.0, {}); self.assertAlmostEqual(ls[0], (10 - 8) / 1000.0)

    def test_throttle_halts_and_never_adds_pnl(self):
        trades = [tr(-300.0, entry=10 * i, exit_=10 * i + 5, kind="open") for i in range(12)]
        out = C.throttle_replay(trades); self.assertTrue(out["halted"]); self.assertGreater(out["net_pnl"], sum(t["pnl"] for t in trades))
        self.assertLessEqual(out["max_dd_closed"], -0.2 + 1e-9)

if __name__ == "__main__": unittest.main()
