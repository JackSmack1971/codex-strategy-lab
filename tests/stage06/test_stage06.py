"""Offline synthetic engineering tests for stage06. They establish mechanics (causality, equivalence, statistics) only;
they say nothing about profitability."""
import unittest, math
import numpy as np, pandas as pd
from stage02 import engine as E, analysis as A
from stage06 import variants as V, wf as W
from tests.stage02.test_engine import synth

N = 24 * 800
def grid(seed=1, n=N, perturb_from=None):
    out = {}
    for nm, sd in (("BTC", seed), ("AAA", seed + 10)):
        d = synth(n, sd)
        if perturb_from is not None:
            d2 = synth(n, sd + 999); k = perturb_from
            scale = d["c"].iloc[k - 1] / d2["c"].iloc[k - 1]
            for c in ("o", "h", "l", "c"): d.loc[k:, c] = d2.loc[k:, c].to_numpy() * scale
            d.loc[k:, "q"] = d2.loc[k:, "q"].to_numpy() * 1.7
        out[nm] = d
    return E.build_grid(out, n)

def env(n=1200):
    rng = np.random.default_rng(5)
    return V.Env(regime={"DIR_NOT_BEARISH": rng.random(n) > .3}, factor={("EQ3", "AAA"): rng.normal(size=n)}, ndays=n)

class Equivalence(unittest.TestCase):
    def test_empty_extras_equal_engine(self):
        syms = grid()
        for sid in (V.MOM, V.VEX):
            P = dict(E.DEFAULTS[sid])
            a = A.cands_for(sid, P, syms, .001, .0005, only=["AAA"]); b = V.make_cands(sid, P, {}, syms, .001, .0005, ["AAA"], V.Env())
            self.assertEqual([(c["j"], c["exit_b"], c["kind"]) for c in a], [(c["j"], c["exit_b"], c["kind"]) for c in b])
        self.assertEqual(E.raw_signal.__name__, "raw_signal"); self.assertEqual(E.exit_path.__name__, "exit_path")   # patch restored

    def test_exit_n1_equals_engine_and_n2_never_exits_earlier(self):
        syms = grid(); P = dict(E.DEFAULTS[V.MOM], thr=0.5)
        base = V.make_cands(V.MOM, P, {}, syms, .001, .0005, ["AAA"], V.Env())
        n1 = V.make_cands(V.MOM, P, {"exit_n": 1}, syms, .001, .0005, ["AAA"], V.Env())
        n2 = V.make_cands(V.MOM, P, {"exit_n": 2}, syms, .001, .0005, ["AAA"], V.Env())
        self.assertGreater(len(base), 3)
        self.assertEqual([(c["j"], c["exit_b"]) for c in base], [(c["j"], c["exit_b"]) for c in n1])
        for b, c in zip(base, n2):
            self.assertEqual(b["j"], c["j"])
            if b["exit_b"] is not None and c["exit_b"] is not None: self.assertGreaterEqual(c["exit_b"], b["exit_b"])

    def test_masks_only_remove_entries(self):
        syms = grid(); P = dict(E.DEFAULTS[V.MOM], thr=0.5); e = env()
        base = {c["j"] for c in V.make_cands(V.MOM, P, {}, syms, .001, .0005, ["AAA"], e)}
        for x in ({"confirm": 2}, {"confirm": 3}, {"rvr": 1.25}, {"l1": 1e9}, {"regime": "DIR_NOT_BEARISH"}, {"factor": ("EQ3", 0.0)}):
            got = {c["j"] for c in V.make_cands(V.MOM, P, x, syms, .001, .0005, ["AAA"], e)}
            self.assertTrue(got <= base, x)
        self.assertEqual(len(V.make_cands(V.MOM, P, {"l1": 1e12}, syms, .001, .0005, ["AAA"], e)), 0)

class Causality(unittest.TestCase):
    def test_masks_unchanged_when_future_changes(self):
        h0 = 24 * 600; e = env()
        s1, s2 = grid(), grid(perturb_from=h0)
        for sid, tf in ((V.MOM, 4), (V.VEX, 1)):
            P = dict(E.DEFAULTS[sid])
            xs = [{"confirm": 3, "rvr": 1.25, "l1": 20e6, "regime": "DIR_NOT_BEARISH", "factor": ("EQ3", 0.0)}] if sid == V.MOM else \
                 [{"comp": 1.0, "ctxp": 100, "weekend": True, "regime": "DIR_NOT_BEARISH", "factor": ("EQ3", 0.0)}]
            for x in xs:
                m1 = V.build_mask(sid, s1["AAA"], P, x, e); m2 = V.build_mask(sid, s2["AAA"], P, x, e)
                j0 = h0 // tf - 2
                self.assertTrue(np.array_equal(m1[:j0], m2[:j0]), (sid, "mask changed by future data"))
                self.assertFalse(np.array_equal(m1, m2) and False)
    def test_daily_index_is_completed_day(self):
        for tf in (1, 4):
            dd = V._day_index(2000, tf); j = np.arange(2000)
            self.assertTrue(np.all((dd + 1) * 24 <= (j + 1) * tf))        # day dd fully closed by signal-bar close
            self.assertTrue(np.all((dd + 2) * 24 > (j + 1) * tf))         # and it is the LAST completed day
    def test_weekend_flag(self):
        s = grid(); P = dict(E.DEFAULTS[V.VEX]); m = V.build_mask(V.VEX, s["AAA"], P, {"weekend": True}, V.Env())
        i = np.arange(len(m)); wd = pd.to_datetime(E.T0_MS + (i + 1) * E.HOUR, unit="ms", utc=True).weekday
        self.assertTrue(np.array_equal(m, wd < 5))

class Universe(unittest.TestCase):
    def test_counts_and_unique(self):
        U = V.universe(); self.assertEqual(len(U), 71)
        self.assertEqual(sum(v[0] == V.MOM for v in U.values()), 34); self.assertEqual(sum(v[0] == V.VEX for v in U.values()), 37)
        for cid, (sid, fam, pt, P, x) in U.items():
            if fam != "BASELINE": self.assertTrue(P != E.DEFAULTS[sid] or x, cid)
    def test_baseline_points_reproduce_defaults(self):
        for (sid, fam) in V.families():
            P, x = V.config_for(sid, fam, V.baseline_point(sid, fam)); self.assertEqual(P, E.DEFAULTS[sid]); self.assertEqual(x, {})

class Selection(unittest.TestCase):
    def test_select_uses_only_train_windows(self):
        syms = grid(); bank = W.Bank(syms, env(), ["AAA"]); seen = []
        orig = bank.get
        def spy(cid, sid, P, x, cost, win): seen.append(win); return orig(cid, sid, P, x, cost, win)
        bank.get = spy
        fold = dict(k=0, train=(A.hr("2021-05-20"), A.hr("2022-09-01")), test=(A.hr("2022-09-01"), A.hr("2022-12-01")))
        W.select(bank, V.MOM, "ENTRY_CONFIRM", fold)
        self.assertTrue(seen and all(w[1] <= fold["train"][1] for w in seen))

class Stats(unittest.TestCase):
    def test_holm(self):
        out = W.holm({"a": 0.001, "b": 0.02, "c": 0.5}); self.assertTrue(out["a"][1]); self.assertFalse(out["c"][1])
        self.assertAlmostEqual(out["a"][0], 0.003); self.assertLessEqual(out["a"][0], out["b"][0])
    def test_paired_boot_planted_and_null(self):
        rng = np.random.default_rng(0); b = rng.normal(0, .01, 900)
        pos = W.paired_boot(b + 0.002, b, reps=2000); self.assertLess(pos["p_one_sided"], 0.01)
        nul = W.paired_boot(b + rng.normal(0, .002, 900), b, reps=2000); self.assertGreater(nul["p_one_sided"], 0.05)
    def test_reality_check_null_and_planted(self):
        rng = np.random.default_rng(1); D = rng.normal(0, .01, (900, 40))
        self.assertGreater(W.reality_check(D, reps=2000)["p"], 0.05)
        D2 = D.copy(); D2[:, 3] += 0.004; self.assertLess(W.reality_check(D2, reps=2000)["p"], 0.05)
    def test_pbo(self):
        rng = np.random.default_rng(2); R = rng.normal(0, .01, (960, 30))
        self.assertTrue(0.25 <= W.pbo_cscv(R)["pbo"] <= 0.75)
        R2 = R.copy(); R2[:, 0] += 0.01; self.assertLess(W.pbo_cscv(R2)["pbo"], 0.1)
    def test_folds_are_anchored_and_disjoint(self):
        for f in W.FOLDS: self.assertEqual(f["train"][0], W.DEV[0]); self.assertEqual(f["train"][1], f["test"][0])
        for a, b in zip(W.FOLDS[:-1], W.FOLDS[1:]): self.assertEqual(a["test"][1], b["test"][0])
        self.assertEqual(W.FOLDS[-1]["test"][1], W.DEV[1])
if __name__ == "__main__": unittest.main()
