"""Stage 05 evaluation harness. Research only. Deterministic (seed 20261118).
PRE-DECLARED RULES (written before any factor-return statistic was computed):
  * Primary horizon h=7 days; target y = ln(C[t+7]/O[t+1]); IC = daily cross-sectional Spearman across the 9 assets.
  * Train signals t in [2022-05-01, 2024-11-09]; validation t in [2024-11-17, 2025-11-09]; (targets never cross a split boundary).
    CONSUMED_LEGACY (t >= 2025-11-17) is touched ONLY for the frozen model, AFTER freezing, descriptively.
  * Factor status: SUPPORTED if train mean IC>0 and validation block-bootstrap 95% lower bound>0; EXPERIMENTAL_WEAK if both means>0 but
    the validation lower bound<=0; EXCLUDED if train mean IC<=0 or validation mean IC<=0.  Signs are never flipped by data.
  * Weights fitted on TRAIN only. Candidate selection on VALIDATION: choose the lowest-complexity multi-factor candidate whose
    validation mean IC is not distinguishable (paired block-bootstrap 95% CI of the difference includes 0) from the best candidate.
  * Skill statement: none unless the chosen model's validation IC lower bound > 0.
"""
from __future__ import annotations
import json, math, hashlib
from pathlib import Path
import numpy as np, pandas as pd
from scipy.optimize import nnls
from . import factors as Fm

SEED = 20261118; BLOCK = 14; REPS = 10_000; H = 7; K_TOP = 3; COST_SIDE = 0.0015   # 10bp fee + 5bp adverse selection per side (Stage 01 assumed, NOT observed)
T = lambda s: pd.Timestamp(s, tz="UTC")
SPL = dict(train=(T("2022-05-01"), T("2024-11-09")), val=(T("2024-11-17"), T("2025-11-09")), legacy=(T("2025-11-17"), T("2026-11-10")))
TRAIN_FIRST_FULL = T("2022-05-01")   # first date at which the 365-day VALUE factor exists for all assets

# ---------------------------------------------------------------- bootstrap
def block_idx(n, reps=REPS, block=BLOCK, seed=SEED):
    rng = np.random.default_rng(seed); nb = math.ceil(n / block); st = rng.integers(0, n, size=(reps, nb))
    return ((st[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(reps, -1)[:, :n]

def boot_mean(x: np.ndarray, seed=SEED):
    x = np.asarray(x, float); x = x[np.isfinite(x)]; n = len(x)
    if n < 2 * BLOCK: return dict(n=n, mean=float(x.mean()) if n else float("nan"), lo95=float("nan"), hi95=float("nan"), p_le0=float("nan"))
    m = x[block_idx(n, seed=seed)].mean(axis=1)
    return dict(n=n, mean=float(x.mean()), lo95=float(np.quantile(m, .025)), hi95=float(np.quantile(m, .975)), p_le0=float((m <= 0).mean()), sd=float(x.std(ddof=1)))

def boot_diff(a: pd.Series, b: pd.Series, seed=SEED):
    d = (a - b).dropna()
    r = boot_mean(d.to_numpy(), seed); r["se"] = float(d.std(ddof=1) / math.sqrt(max(1, len(d) / 7))) if len(d) else float("nan")  # naive effective-n = days/7
    return r

def ic_stats(ic: pd.Series, seed=SEED):
    r = boot_mean(ic.to_numpy(), seed)
    r["ir_daily"] = float(ic.mean() / ic.std(ddof=1)) if len(ic) > 2 else float("nan"); r["hit_rate"] = float((ic > 0).mean()) if len(ic) else float("nan"); r["eff_weeks"] = round(len(ic) / 7, 1)
    return r

# ---------------------------------------------------------------- regime tags (BTC only, point-in-time)
def btc_regime_tags(P) -> pd.DataFrame:
    """Stage 04 direction rule (>=4 of 5 votes) and ADX structure on BTC; volatility tag via EXPANDING percentile of RV30 (prior history only, >=180 obs)."""
    from stage04 import regime as R
    d = pd.DataFrame(dict(o=P["o"]["BTC"], h=P["h"]["BTC"], l=P["l"]["BTC"], c=P["c"]["BTC"], q=P["q"]["BTC"]))
    d = d.ffill(limit=3)                                              # <=3 missing days: ffill for indicator continuity only
    x = R.indicators(d)
    votes = pd.DataFrame({"a": np.sign(x.c - x.ema200), "b": np.sign(x.ema50 - x.ema200), "c": np.sign(x.ema20 - x.ema50), "d": np.sign(x.pdi - x.mdi), "e": np.sign(x.ret30)})
    nb = (votes == 1).sum(axis=1); ns = (votes == -1).sum(axis=1)
    ok = x[["ema200", "pdi", "ret30"]].notna().all(axis=1)
    direction = pd.Series(np.where(~ok, "NA", np.where(nb >= 4, "Bullish", np.where(ns >= 4, "Bearish", "Other"))), index=d.index)
    structure = pd.Series(np.where(x.adx.isna(), "NA", np.where(x.adx >= 25, "Trending", "NonTrending")), index=d.index)
    rv = x.rv30.to_numpy(); vt = np.full(len(rv), "NA", dtype=object)
    for i in range(len(rv)):
        if not np.isfinite(rv[i]): continue
        prev = rv[:i][np.isfinite(rv[:i])]
        if len(prev) < 180: continue
        p = (prev < rv[i]).mean() * 100; vt[i] = "LowVol" if p < 25 else "NormalVol" if p < 75 else "HighVol"
    return pd.DataFrame(dict(direction=direction, structure=structure, vol=pd.Series(vt, index=d.index)))

# ---------------------------------------------------------------- portfolio test
def portfolio_series(S: pd.DataFrame, P, dates, k=K_TOP, cost=COST_SIDE):
    """Top-k equal-weight long-only from score S, weekly rebalance in 7 phases (every day belongs to exactly one phase).
    Signal at close t; trade at O[t+1]; hold to O[t+8] (next rebalance trade). Cost = cost * sum|w_new - w_prev| (target weights; drift ignored).
    Returns DataFrame indexed by signal date: gross, net, turnover(sum|dw|), and the equal-weight benchmark on the same dates."""
    O = P["o"]; A = Fm.ASSETS; Oa = O.to_numpy(); idx = O.index; pos = {d: i for i, d in enumerate(idx)}
    rows = {}
    sel_hist = {}
    for ph in range(7):
        ds = [d for d in dates][ph::7]; prev = np.zeros(len(A)); prev_b = np.zeros(len(A))
        for d in ds:
            i = pos[d]
            if i + 8 >= len(idx): continue
            s = S.loc[d].to_numpy(); ok = np.isfinite(s)
            r = Oa[i + 8] / Oa[i + 1] - 1
            if ok.sum() < Fm.PARAMS["min_assets"]: continue
            order = np.argsort(-np.where(ok, s, -np.inf), kind="stable")[:k]; w = np.zeros(len(A)); w[order] = 1.0 / k
            vb = np.isfinite(r)
            if vb.sum() == 0: continue
            wb = np.where(vb, 1.0, 0.0); wb = wb / wb.sum()
            if not np.all(np.isfinite(r[w > 0])): continue
            g = float((w * np.where(vb, r, 0)).sum()); gb = float((wb * np.where(vb, r, 0)).sum())
            to = float(np.abs(w - prev).sum()); tob = float(np.abs(wb - prev_b).sum()); prev, prev_b = w, wb
            rows[d] = dict(gross=g, net=g - cost * to, turnover=to, ew_gross=gb, ew_net=gb - cost * tob, ew_turnover=tob)
            sel_hist[d] = tuple(order.tolist())
    df = pd.DataFrame(rows).T.sort_index(); df["excess_gross"] = df.gross - df.ew_gross; df["excess_net"] = df.net - df.ew_net
    return df

def port_summary(df: pd.DataFrame, cost=COST_SIDE):
    if not len(df): return dict(n=0)
    b = boot_mean(df.excess_net.to_numpy()); bg = boot_mean(df.excess_gross.to_numpy())
    dT = float(df.turnover.mean() - df.ew_turnover.mean())
    be = float(df.excess_gross.mean() / dT) if dT > 0 else float("nan")
    return dict(n_rebalances=int(len(df)), mean_excess_net_per_week=b["mean"], excess_net_lo95=b["lo95"], excess_net_hi95=b["hi95"], mean_excess_gross_per_week=bg["mean"],
                mean_top_net_per_week=float(df.net.mean()), mean_ew_net_per_week=float(df.ew_net.mean()), one_way_turnover_per_rebalance=float(df.turnover.mean() / 2),
                breakeven_cost_per_side_bp=be * 1e4 if np.isfinite(be) else None, hit_rate_excess=float((df.excess_net > 0).mean()))

# ---------------------------------------------------------------- weights
def ic_weights(ics: dict[str, pd.Series]) -> dict[str, float]:
    m = {k: max(0.0, float(v.mean())) for k, v in ics.items()}; s = sum(m.values())
    return {k: (v / s if s > 0 else 0.0) for k, v in m.items()}

def nnls_ridge_fit(Z: dict, Y: pd.DataFrame, dates, ks, lam):
    """min ||y - Z w||^2 + lam||w||^2, w>=0, pooled over (date, asset) rows where every factor and y exist; y = cross-sectional rank-normal of the target."""
    Xs, ys = [], []
    yz = Fm.cs_normalise(Y, +1)
    for d in dates:
        x = np.column_stack([Z[k].loc[d].to_numpy() for k in ks]); y = yz.loc[d].to_numpy(); ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
        if ok.sum() >= 5: Xs.append(x[ok]); ys.append(y[ok])
    X = np.vstack(Xs); y = np.concatenate(ys); n = X.shape[1]
    w, _ = nnls(np.vstack([X, math.sqrt(lam) * np.eye(n)]), np.concatenate([y, np.zeros(n)])); return w

def fit_nnls_cv(Z, Y, dates, ks, lams=(0.0, 1e2, 1e3, 1e4, 1e5), folds=5, purge=H + 1):
    dates = list(dates); n = len(dates); edges = np.linspace(0, n, folds + 1).astype(int); res = {}
    for lam in lams:
        ic_all = []
        for f in range(folds):
            te = dates[edges[f]:edges[f + 1]]; lo, hi = edges[f] - purge, edges[f + 1] + purge
            tr = [d for i, d in enumerate(dates) if i < lo or i >= hi]
            w = nnls_ridge_fit(Z, Y, tr, ks, lam)
            if w.sum() <= 0: ic_all.append(0.0); continue
            S = Fm.composite({k: Z[k].loc[te] for k in ks}, dict(zip(ks, w / w.sum())))
            ic = Fm.sp_ic(S, Y.loc[te]); ic_all.append(float(ic.mean()) if len(ic) else 0.0)
        res[lam] = float(np.mean(ic_all))
    best = max(res, key=lambda l: (res[l], -l)); w = nnls_ridge_fit(Z, Y, dates, ks, best)
    return (w / w.sum() if w.sum() > 0 else np.zeros(len(ks))), best, res

def cond_weights(Z, Y, tags, dates, ks, k_shrink=250, min_days=60):
    """Regime-conditional weights: per BTC-direction regime, IC-proportional weights shrunk toward global: w_r = (n_r w_r_hat + k w_g)/(n_r+k)."""
    ic = {k: Fm.sp_ic(Z[k].loc[dates], Y.loc[dates]) for k in ks}; wg = ic_weights(ic); out = {}
    for r in ["Bullish", "Bearish", "Other"]:
        dr = [d for d in dates if tags.direction.get(d) == r]; n = len(dr)
        if n < min_days: out[r] = dict(wg, _n=n, _used="global"); continue
        ir = {k: Fm.sp_ic(Z[k].loc[dr], Y.loc[dr]) for k in ks}; wr = ic_weights(ir)
        if sum(wr.values()) == 0: out[r] = dict(wg, _n=n, _used="global(all IC<=0 in regime)"); continue
        w = {k: (n * wr[k] + k_shrink * wg[k]) / (n + k_shrink) for k in ks}; s = sum(w.values()); out[r] = dict({k: v / s for k, v in w.items()}, _n=n, _used="shrunk")
    return out

def composite_cond(Z, wc, tags, dates, ks):
    """Per-date weights chosen by the BTC direction tag at that date (point-in-time)."""
    S = pd.DataFrame(np.nan, index=pd.DatetimeIndex(dates), columns=Fm.ASSETS)
    for r in ["Bullish", "Bearish", "Other"]:
        dr = [d for d in dates if tags.direction.get(d, "NA") == r or (r == "Other" and tags.direction.get(d, "NA") == "NA")]
        if not dr: continue
        w = {k: v for k, v in wc[r].items() if not k.startswith("_")}
        S.loc[dr] = Fm.composite({k: Z[k].loc[dr] for k in ks}, w)
    return S

# ---------------------------------------------------------------- dependence
def avg_cs_corr(Z, ks, dates):
    M = np.zeros((len(ks), len(ks))); cnt = 0
    for d in dates:
        X = np.column_stack([Z[k].loc[d].to_numpy() for k in ks]); ok = np.isfinite(X).all(axis=1)
        if ok.sum() >= 5:
            R = np.column_stack([pd.Series(X[ok][:, j]).rank().to_numpy() for j in range(len(ks))])
            if (R.std(axis=0) > 0).all(): M += np.corrcoef(R.T); cnt += 1
    return M / cnt

def persistence(Z, k, dates, lag=7):
    """Mean cross-sectional rank autocorrelation of the z-score at lag 7 (high = slow factor, low turnover) and top-3 membership retention."""
    ac, ret = [], []
    for d in dates:
        d2 = d + pd.Timedelta(days=lag)
        if d2 not in Z[k].index: continue
        a, b = Z[k].loc[d].to_numpy(), Z[k].loc[d2].to_numpy(); ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() >= 5 and a[ok].std() > 0 and b[ok].std() > 0:
            ac.append(np.corrcoef(pd.Series(a[ok]).rank(), pd.Series(b[ok]).rank())[0, 1])
            ta = set(np.argsort(-np.where(np.isfinite(a), a, -9))[:3]); tb = set(np.argsort(-np.where(np.isfinite(b), b, -9))[:3]); ret.append(len(ta & tb) / 3)
    return float(np.mean(ac)), float(np.mean(ret))

def residualise(Z, k, others, dates):
    """Per-date cross-sectional OLS residual of z_k on the other factors (incremental information of k)."""
    R = Z[k].copy() * np.nan
    for d in dates:
        y = Z[k].loc[d].to_numpy(); X = np.column_stack([np.ones(len(Fm.ASSETS))] + [Z[o].loc[d].to_numpy() for o in others]); ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
        if ok.sum() > X.shape[1] + 1:
            b, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None); res = np.full(len(y), np.nan); res[ok] = y[ok] - X[ok] @ b; R.loc[d] = res
    return R

def sig(o): return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()
