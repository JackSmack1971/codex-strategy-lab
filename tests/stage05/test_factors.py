import unittest, math, numpy as np, pandas as pd
from stage05 import factors as F, evaluate as V

def panel(n=700, seed=3, drift=None):
    rng = np.random.default_rng(seed); idx = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC"); P = {}
    ret = rng.normal(0, 0.03, (n, 9)) + (np.array(drift) if drift is not None else 0)
    c = pd.DataFrame(100 * np.exp(np.cumsum(ret, 0)), index=idx, columns=F.ASSETS); o = c.shift(1).fillna(c.iloc[0])
    P.update(c=c, o=o, h=c * 1.01, l=c * 0.99, q=pd.DataFrame(rng.lognormal(18, .3, (n, 9)), index=idx, columns=F.ASSETS), nbar=pd.DataFrame(24, index=idx, columns=F.ASSETS)); return P

class T(unittest.TestCase):
    def test_rank_normal_properties(self):
        z = F.rank_normal_row(np.array([5., 1, 3, 2, 4, 9, 8, 7, 6]), 5, 2.0); self.assertAlmostEqual(float(np.nansum(z)), 0.0, places=9); self.assertTrue(np.argmax(z) == 5 and np.argmin(z) == 1)
        self.assertTrue(np.isnan(F.rank_normal_row(np.array([1., 2, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]), 5, 2.0)).all())
    def test_sign_orientation(self):
        df = pd.DataFrame([np.arange(9.)], columns=F.ASSETS); self.assertGreater(F.cs_normalise(df, +1).iloc[0]["LTC"], 0); self.assertLess(F.cs_normalise(df, -1).iloc[0]["LTC"], 0)
    def test_no_lookahead_truncation(self):
        P = panel(); _, Z = F.build_z(P); d = P["c"].index[500]; Pt = {k: v.loc[:d] for k, v in P.items()}; _, Zt = F.build_z(Pt)
        for k in F.PRIMARY: np.testing.assert_allclose(np.nan_to_num(Zt[k].loc[d].to_numpy(), nan=-9), np.nan_to_num(Z[k].loc[d].to_numpy(), nan=-9), atol=1e-12)
    def test_target_timing_and_leak_sensitivity(self):
        P = panel(); y = F.targets(P, 7); i = 100; self.assertAlmostEqual(float(y.iloc[i]["BTC"]), math.log(P["c"].iloc[i + 7]["BTC"] / P["o"].iloc[i + 1]["BTC"]))
        leak = F.cs_normalise(y, +1); ic = F.sp_ic(leak.iloc[50:600], y.iloc[50:600]); self.assertGreater(ic.mean(), 0.95)           # harness detects a deliberately leaked factor
        Z = F.build_z(P)[1]; self.assertLess(abs(F.sp_ic(Z["MOM"].iloc[250:600], y.iloc[250:600]).mean()), 0.12)                             # random walk: no spurious IC
    def test_planted_signal_is_found(self):
        drift = np.array([0.004, 0.003, 0.002, 0.001, 0, -0.001, -0.002, -0.003, -0.004]); P = panel(900, 5, drift); raw, Z = F.build_z(P); y = F.targets(P, 7)
        self.assertGreater(F.sp_ic(Z["TREND"].iloc[300:850], y.iloc[300:850]).mean(), 0.1)
    def test_composite_renormalises_missing(self):
        idx = pd.date_range("2024-01-01", periods=1, tz="UTC"); a = pd.DataFrame([[1.0] * 9], index=idx, columns=F.ASSETS); b = a * 2; b.iloc[0, 0] = np.nan; cc = a * 0 + 3; cc.iloc[0, 0] = np.nan
        S = F.composite({"MOM": a, "TREND": b, "VOL": cc}, {"MOM": .5, "TREND": .25, "VOL": .25}); self.assertAlmostEqual(S.iloc[0, 1], .5 * 1 + .25 * 2 + .25 * 3)
        self.assertTrue(np.isnan(S.iloc[0, 0]))           # only 1 factor available (<3) -> NaN, not imputed
    def test_portfolio_cost_arithmetic(self):
        P = panel(60, 1); S = pd.DataFrame(np.tile(np.arange(9.), (60, 1)), index=P["c"].index, columns=F.ASSETS); df = V.portfolio_series(S, P, list(P["c"].index[:40]), cost=0.0015)
        self.assertTrue((abs(df.turnover.iloc[:7] - 1.0) < 1e-12).all()); self.assertTrue((df.turnover.iloc[7:] < 1e-12).all())   # each of 7 phases pays entry once, then no turnover; self.assertAlmostEqual(df.net.iloc[0], df.gross.iloc[0] - 0.0015)
    def test_bootstrap_deterministic_and_ic_weights(self):
        x = np.random.default_rng(0).normal(0.1, 1, 300); a = V.boot_mean(x); b = V.boot_mean(x); self.assertEqual(a, b); self.assertLess(a["lo95"], a["mean"] < a["hi95"] and a["mean"] or 9)
        w = V.ic_weights({"A": pd.Series([.1, .1]), "B": pd.Series([-.2, -.2]), "C": pd.Series([.3, .3])}); self.assertEqual(w["B"], 0.0); self.assertAlmostEqual(sum(w.values()), 1.0)
if __name__ == "__main__": unittest.main()
