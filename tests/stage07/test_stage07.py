import unittest, numpy as np, pandas as pd
from stage07 import core as C

class T(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1); self.n = 400
        self.rm = rng.normal(0.001, 0.01, self.n); self.rv = 0.3 * self.rm + rng.normal(0.0005, 0.02, self.n)

    def test_weights_sum_and_order(self):
        sig, rho = C.estimate(self.rm, self.rv); W = C.scheme_weights(sig, rho)
        for k in ("EW", "IV", "RB"): self.assertAlmostEqual(sum(W[k].values()), 1.0, 9)
        self.assertGreater(W["IV"][C.MOM], 0.5); self.assertAlmostEqual(W["CONS"][C.MOM] + W["CONS"][C.VEX], 0.75)

    def test_riskbudget_hits_target(self):
        sig = {C.MOM: 0.01, C.VEX: 0.02}
        for rho in (0.0, 0.5, 0.9):
            w = C.w_riskbudget(sig, rho); rc = C.risk_contrib(w, sig, rho)
            self.assertAlmostEqual(rc[C.MOM], 2 / 3, 6); self.assertAlmostEqual(rc[C.MOM] + rc[C.VEX], 1.0, 9)

    def test_combine_cash_and_weights(self):
        g = {C.MOM: np.linspace(1, 1.1, 10), C.VEX: np.linspace(1, 0.9, 10)}
        r = C.combine({C.MOM: 0.5, C.VEX: 0.25}, g); eq = np.cumprod(1 + r)
        self.assertAlmostEqual(eq[-1], 0.25 + 0.5 * 1.1 + 0.25 * 0.9, 9)
        self.assertTrue(np.allclose(C.combine({C.MOM: 0.0, C.VEX: 0.0}, g), 0))     # all cash

    def test_rebalance_daily_equals_weighted_returns(self):
        r = {C.MOM: self.rm, C.VEX: self.rv}; w = {C.MOM: 0.5, C.VEX: 0.5}
        out, tr = C.rebalance_path(r, w, 1); self.assertTrue(np.allclose(out, 0.5 * self.rm + 0.5 * self.rv))
        self.assertGreater(tr, 0)
        nev, tr0 = C.rebalance_path(r, w, None); self.assertEqual(tr0, 0.0)
        eq = 0.5 * np.prod(1 + self.rm) + 0.5 * np.prod(1 + self.rv); self.assertAlmostEqual(np.prod(1 + nev), eq, 9)

    def test_var_es_ordering_and_ci(self):
        r = np.random.default_rng(2).standard_t(4, 5000) * 0.01
        v, e, n = C.var_es(r, 0.99); self.assertGreaterEqual(e, v); self.assertEqual(n, 50)
        lo, hi = C.es_ci(r, 0.99, reps=300); self.assertLess(lo, e); self.assertGreater(hi, e)
        self.assertGreater(C.horizon_es(r, 7)[0], C.var_es(r, 0.95)[1] * 0.9)

    def test_corr_summary_one_factor(self):
        rng = np.random.default_rng(3); f = rng.normal(size=1000); R = pd.DataFrame({f"a{i}": 0.9 * f + 0.3 * rng.normal(size=1000) for i in range(6)})
        s = C.corr_summary(R); self.assertGreater(s["mean_pairwise"], 0.8); self.assertLess(s["eff_bets"], 1.5)
        I = pd.DataFrame(rng.normal(size=(1000, 6))); self.assertGreater(C.corr_summary(I)["eff_bets"], 5)
        self.assertGreater(C.tail_coexceed(R), 0.3); self.assertLess(C.tail_coexceed(I), 0.12)

    def test_holm_monotone(self):
        h = C.holm({"a": 0.01, "b": 0.04, "c": 0.5}); self.assertAlmostEqual(h["a"], 0.03); self.assertLessEqual(h["a"], h["b"]); self.assertLessEqual(h["b"], h["c"])

    def test_paired_boot_detects_shift(self):
        rng = np.random.default_rng(4); b = rng.normal(0, 0.01, 800); r = b + 0.003
        p = C.paired_boot(r, b, reps=500); self.assertLess(p["p_one_sided"], 0.05); self.assertGreater(p["dSharpe_ci95"][0], 0)

    def test_exposure_scaling(self):
        tr = [dict(entry_hour=10, exit_hour=20, tf=1, kind="stop", reserved_risk=100.0, qty=10.0, entry_fill=50.0, symbol="X")]
        e = C.exposure({C.MOM: (tr, 10_000.0)}, {C.MOM: 0.5}, 0, 100, None)
        self.assertAlmostEqual(e["open_risk"].max(), 0.005); self.assertAlmostEqual(e["gross"].max(), 0.05 * 0.5 / 0.5 * 0.5, 9); self.assertEqual(e["positions"].max(), 1)

if __name__ == "__main__": unittest.main()
