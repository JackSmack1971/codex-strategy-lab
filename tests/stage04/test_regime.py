import unittest, numpy as np, pandas as pd
from stage04 import regime as G

def frame(path):
    n = len(path); c = pd.Series(path); idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    d = pd.DataFrame(dict(o=c.shift(1).fillna(c[0]).values, h=(c * 1.01).values, l=(c * 0.99).values, c=c.values, q=np.full(n, 1e8), nbar=24), index=idx); return d

class T(unittest.TestCase):
    def test_uptrend_bullish_trending(self):
        d = frame(100 * np.exp(0.004 * np.arange(500) + 0.002 * np.sin(np.arange(500))))
        a = G.classify_asset(G.indicators(d), None); self.assertEqual(a["direction"], "Bullish"); self.assertEqual(a["structure"], "Trending"); self.assertEqual(a["momentum"], "Positive")
    def test_downtrend_bearish(self):
        d = frame(100 * np.exp(-0.004 * np.arange(500) + 0.002 * np.sin(np.arange(500))))
        a = G.classify_asset(G.indicators(d), None); self.assertEqual(a["direction"], "Bearish"); self.assertEqual(a["momentum"], "Negative")
    def test_flat_noise_not_trending(self):
        rng = np.random.default_rng(1); d = frame(100 * np.exp(np.cumsum(rng.normal(0, 0.002, 500)) * 0 + 0.01 * np.sin(np.arange(500) / 3)))
        a = G.classify_asset(G.indicators(d), None); self.assertNotEqual(a["structure"], "Trending")
    def test_pct_rank_and_book(self):
        self.assertAlmostEqual(G.pct_rank(pd.Series([1, 2, 3, 4]), 3.5), 75.0)
        b = G.book_stats([[99.99, 10], [99.0, 5]], [[100.01, 10], [101.0, 5]], bp=10); self.assertAlmostEqual(b["bid_depth_usd_10bp"], 99.99 * 10); self.assertAlmostEqual(b["spread_bp"], (100.01 / 99.99 - 1) * 1e4)
if __name__ == "__main__": unittest.main()
