"""Stage 06 walk-forward, selection and multiple-testing statistics. Research only.

PREDECLARED RULES (frozen in docs/strategy-specs/STAGE_06_ANALYSIS_PLAN.md before any real-data run):
 * Anchored walk-forward on DEV 2021-11-17..2025-11-17: train = [DEV0, test_start), test = 6-month blocks starting 2023-05-17 (5 folds).
 * Per fold and family, select on TRAIN ONLY: score = mean over {cfg}+grid neighbours of dSharpe(vs baseline, same train window);
   constraints on the cfg itself: trades >= 0.75x base, maxDD no worse than base-2pp, turnover <= 1.25x base. Switch from the baseline only if
   score >= DELTA (0.10 ordered family, 0.20 categorical family); otherwise KEEP BASELINE for that fold.
 * Gates on pooled out-of-sample folds (G1..G7) -> finalist; finalists alone are evaluated once on the adjacent-asset holdout."""
from __future__ import annotations
import itertools, math
import numpy as np
from stage02 import engine as E, analysis as A
from . import variants as V

DEV0, DEV1 = "2021-11-17", "2025-11-17"
TEST_STARTS = ["2023-05-17", "2023-11-17", "2024-05-17", "2024-11-17", "2025-05-17"]
TEST_ENDS = ["2023-11-17", "2024-05-17", "2024-11-17", "2025-05-17", "2025-11-17"]
FOLDS = [dict(k=i, train=(A.hr(DEV0), A.hr(ts)), test=(A.hr(ts), A.hr(te))) for i, (ts, te) in enumerate(zip(TEST_STARTS, TEST_ENDS))]
DEV = (A.hr(DEV0), A.hr(DEV1)); CONSUMED = (A.hr("2025-11-17"), A.hr("2026-11-17"))
BASE_COST = (0.001, 0.0005); STRESS_A = (0.002, 0.001); STRESS_B = (0.001, 0.002)
DELTA_ORD, DELTA_CAT = 0.10, 0.20
MIN_TRADE_FRAC, DD_TOL, TURN_MULT = 0.75, 0.02, 1.25
G1_DSHARPE, G2_DD_TOL = 0.15, 0.01
SEED, REPS, BLOCK = 20261118, 10_000, 14


# ---------------------------------------------------------------- metrics
def metrics(res):
    m, r = A.full_metrics(res)
    keep = ("n", "ratio", "sharpe", "sortino", "max_dd", "total_return", "cagr", "ann_vol", "turnover_per_year", "exposure_time", "win_rate",
            "profit_factor", "expectancy_R", "worst5_loss", "forced_closes")
    out = {k: (None if m.get(k) is None else float(m[k])) for k in keep if k in m}
    out["n"] = int(m.get("n", 0)); out["daily"] = r
    return out


class Bank:
    """Caches candidates per (cfg, cost) and simulated windows per (cfg, cost, window)."""
    def __init__(self, syms, env, names=None):
        self.syms, self.env, self.names = syms, env, names; self.cands = {}; self.sims = {}; self.n_sims = 0

    def get(self, cid, sid, P, x, cost, win):
        ck = (cid, cost)
        if ck not in self.cands: self.cands[ck] = V.make_cands(sid, P, x, self.syms, cost[0], cost[1], self.names, self.env)
        wk = (cid, cost, win)
        if wk not in self.sims:
            with V.symbols(self.names): self.sims[wk] = metrics(A.run_window(self.cands[ck], self.syms, win, cost[0], cost[1]))
            self.n_sims += 1
        return self.sims[wk]


def sh(r):
    r = np.asarray(r); sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(365)) if sd > 0 else float("nan")


def mdd(r):
    eq = np.concatenate([[1.0], np.cumprod(1 + np.asarray(r))]); pk = np.maximum.accumulate(eq); return float((eq / pk - 1).min())


# ---------------------------------------------------------------- selection (TRAIN ONLY)
def select(bank, sid, fam, fold, cost=BASE_COST, universe=None):
    """Returns dict(chosen=point|None, score, table) for one fold. Uses only fold['train']."""
    F = V.families()[(sid, fam)]; bp = V.baseline_point(sid, fam); win = fold["train"]
    base = bank.get(f"{sid}|BASELINE", sid, V._base(sid), {}, cost, win); bsh = base["sharpe"]
    tab = {}
    for pt in V.points(sid, fam):
        cid = f"{sid}|BASELINE" if pt == bp else V.cfg_id(sid, fam, pt)
        P, x = V.config_for(sid, fam, pt); m = bank.get(cid, sid, P, x, cost, win)
        ok = (m["n"] >= MIN_TRADE_FRAC * base["n"] and m["max_dd"] >= base["max_dd"] - DD_TOL
              and m["turnover_per_year"] <= TURN_MULT * base["turnover_per_year"] and np.isfinite(m["sharpe"]))
        tab[json_key(pt)] = dict(pt=pt, dS=(m["sharpe"] - bsh) if np.isfinite(m["sharpe"]) else float("nan"), ok=bool(ok), n=m["n"], sharpe=m["sharpe"], max_dd=m["max_dd"])
    best, best_sc = None, -1e9
    for k, rec in tab.items():
        pt = rec["pt"]
        if pt == bp or not rec["ok"]: continue
        nb = [tab[json_key(q)]["dS"] for q in V.neighbours(sid, fam, pt)]
        vals = [rec["dS"]] + [v for v in nb if np.isfinite(v)]
        sc = float(np.mean(vals)) if F["ordered"] else rec["dS"]
        rec["score"] = sc
        if sc > best_sc: best, best_sc = pt, sc
    delta = DELTA_ORD if F["ordered"] else DELTA_CAT
    chosen = best if (best is not None and best_sc >= delta) else None
    return dict(chosen=chosen, score=(best_sc if best is not None else None), best=best, delta=delta, table=tab)


def json_key(pt): return "|".join(f"{k}={pt[k]}" for k in sorted(pt))


# ---------------------------------------------------------------- walk-forward for one family
def walk_forward(bank, sid, fam, cost=BASE_COST):
    bp = V.baseline_point(sid, fam); folds = []
    for fd in FOLDS:
        sel = select(bank, sid, fam, fd, cost); pt = sel["chosen"] or bp
        cid = f"{sid}|BASELINE" if pt == bp else V.cfg_id(sid, fam, pt)
        P, x = V.config_for(sid, fam, pt)
        ins = bank.get(cid, sid, P, x, cost, fd["train"]); base_in = bank.get(f"{sid}|BASELINE", sid, V._base(sid), {}, cost, fd["train"])
        oos = bank.get(cid, sid, P, x, cost, fd["test"]); base_oos = bank.get(f"{sid}|BASELINE", sid, V._base(sid), {}, cost, fd["test"])
        folds.append(dict(fold=fd["k"], chosen=pt, switched=pt != bp, cid=cid, score=sel["score"], best=sel["best"],
                          ins_dS=ins["sharpe"] - base_in["sharpe"], oos=_slim(oos), base_oos=_slim(base_oos),
                          oos_dS=(oos["sharpe"] - base_oos["sharpe"]) if np.isfinite(oos["sharpe"]) and np.isfinite(base_oos["sharpe"]) else float("nan"),
                          _r=oos["daily"], _rb=base_oos["daily"]))
    return folds


def _slim(m): return {k: v for k, v in m.items() if k != "daily"}


def pooled(folds):
    r = np.concatenate([f["_r"] for f in folds]); rb = np.concatenate([f["_rb"] for f in folds])
    n = sum(f["oos"]["n"] for f in folds); nb = sum(f["base_oos"]["n"] for f in folds)
    to = np.mean([f["oos"]["turnover_per_year"] for f in folds]); tob = np.mean([f["base_oos"]["turnover_per_year"] for f in folds])
    return dict(sharpe=sh(r), base_sharpe=sh(rb), dSharpe=sh(r) - sh(rb), mdd=mdd(r), base_mdd=mdd(rb),
                worst_fold_mdd=min(f["oos"]["max_dd"] for f in folds), base_worst_fold_mdd=min(f["base_oos"]["max_dd"] for f in folds),
                n=int(n), base_n=int(nb), turnover=float(to), base_turnover=float(tob), total_return=float(np.prod(1 + r) - 1), base_total_return=float(np.prod(1 + rb) - 1),
                days=int(len(r)), r=r, rb=rb)


# ---------------------------------------------------------------- bootstrap / multiple testing
def _block_idx(n, reps, block, rng):
    nb = int(math.ceil(n / block)); st = rng.integers(0, n, size=(reps, nb))
    return ((st[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(reps, -1)[:, :n]


def paired_boot(r, rb, reps=REPS, block=BLOCK, seed=SEED):
    """Paired circular block bootstrap of (cand - base): mean daily diff and Sharpe diff. One-sided p = P*(mean diff <= 0) (add-one)."""
    d = np.asarray(r) - np.asarray(rb); n = len(d); rng = np.random.default_rng(seed); idx = _block_idx(n, reps, block, rng)
    md = d[idx].mean(axis=1)
    R, RB = np.asarray(r)[idx], np.asarray(rb)[idx]
    def shp(X):
        sd = X.std(axis=1, ddof=1); return np.where(sd > 0, X.mean(axis=1) / np.where(sd > 0, sd, 1) * math.sqrt(365), np.nan)
    ds = shp(R) - shp(RB)
    return dict(mean_diff=float(d.mean()), p_one_sided=float((1 + (md <= 0).sum()) / (reps + 1)), ci95_mean_diff=[float(np.quantile(md, .025)), float(np.quantile(md, .975))],
                dSharpe_ci95=[float(np.nanquantile(ds, .025)), float(np.nanquantile(ds, .975))], dSharpe_lower90=float(np.nanquantile(ds, .10)), n_days=n)


def holm(pvals: dict, alpha=0.05):
    """Holm-Bonferroni step-down. Returns {key: (adj_p, reject)}."""
    items = sorted(pvals.items(), key=lambda kv: kv[1]); m = len(items); out = {}; run = 0.0; stop = False
    for i, (k, p) in enumerate(items):
        adj = min(1.0, (m - i) * p); run = max(run, adj); out[k] = (run, (not stop) and p <= alpha / (m - i))
        if not out[k][1]: stop = True
    return out


def reality_check(D, reps=REPS, block=BLOCK, seed=SEED):
    """White (2000) reality check on a (T x K) matrix of daily return DIFFERENCES vs baseline (candidate - base); H0: max_k E[d_k] <= 0."""
    T, K = D.shape; obs = D.mean(axis=0); rng = np.random.default_rng(seed); mx = np.empty(reps); chunk = 1000
    for a in range(0, reps, chunk):
        b = min(reps, a + chunk); idx = _block_idx(T, b - a, block, rng)
        bm = D[idx].mean(axis=1) - obs[None, :]           # centred bootstrap means (reps x K)
        mx[a:b] = bm.max(axis=1)
    return dict(max_obs_mean=float(obs.max()), argmax=int(obs.argmax()), p=float((1 + (mx >= obs.max()).sum()) / (reps + 1)), K=int(K), T=int(T))


def pbo_cscv(R, S=8, seed=SEED):
    """Probability of backtest overfitting (Bailey et al.) by CSCV on (T x K) daily returns; ranks by Sharpe. Returns pbo and mean OOS rank of the IS-best."""
    T, K = R.shape; T2 = (T // S) * S; R = R[:T2]; blocks = np.split(np.arange(T2), S); logits = []; rel = []
    def shp(X):
        sd = X.std(axis=0, ddof=1); return np.where(sd > 0, X.mean(axis=0) / np.where(sd > 0, sd, 1), -np.inf)
    for comb in itertools.combinations(range(S), S // 2):
        is_i = np.concatenate([blocks[b] for b in comb]); oos_i = np.concatenate([blocks[b] for b in range(S) if b not in comb])
        s_is, s_oos = shp(R[is_i]), shp(R[oos_i]); best = int(np.argmax(s_is))
        rank = (s_oos < s_oos[best]).sum() + 0.5 * ((s_oos == s_oos[best]).sum() - 1)   # 0..K-1, higher is better
        w = (rank + 1) / (K + 1); logits.append(math.log(w / (1 - w))); rel.append(float(w))
    logits = np.array(logits)
    return dict(pbo=float((logits <= 0).mean()), median_oos_rel_rank=float(np.median(rel)), n_combinations=len(logits), K=int(K), T=int(T2))
