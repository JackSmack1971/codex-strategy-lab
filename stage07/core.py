"""Stage 07 portfolio construction primitives. Research only: no orders, credentials or execution.
Sleeves run the FROZEN Stage 02/06 baseline rules (engine.DEFAULTS) unchanged. A scheme is a vector of capital weights; each sleeve is a
segregated sub-book of w x $10,000 (linear-in-capital approximation of a shared book, checked by `subbook_equivalence`)."""
from __future__ import annotations
import math
import numpy as np, pandas as pd
from stage02 import engine as E, analysis as A, load_grid
from .shared import simulate_shared

MOM, VEX, REV = "CRY-MOM-101", "CRY-VEX-103", "CRY-REV-102"
SLEEVES = [MOM, VEX]
BASE = (0.001, 0.0005); STRESS_A = (0.002, 0.001); STRESS_B = (0.001, 0.002)
DEV0, DEV1 = "2021-11-17", "2025-11-17"
TEST_STARTS = ["2023-05-17", "2023-11-17", "2024-05-17", "2024-11-17", "2025-05-17"]
TEST_ENDS = ["2023-11-17", "2024-05-17", "2024-11-17", "2025-05-17", "2025-11-17"]
FOLDS = [dict(k=i, train=(A.hr(DEV0), A.hr(a)), test=(A.hr(a), A.hr(b))) for i, (a, b) in enumerate(zip(TEST_STARTS, TEST_ENDS))]
DEV = (A.hr(DEV0), A.hr(DEV1)); CONSUMED = (A.hr("2025-11-17"), A.hr("2026-11-17"))
REPS, BLOCK, SEED = 10_000, 14, 20261118
CONS_W = {MOM: 0.50, VEX: 0.25}                 # Stage 03 risk budgets as capital weights (risk/trade 0.5% and 0.25%)
CONS_NCAP_TOTAL = {MOM: 0.133, VEX: 0.10}        # Stage 03 per-position notional caps, % of TOTAL equity
BUDGET_RB = {MOM: 2 / 3, VEX: 1 / 3}


# ------------------------------------------------------------------ weights
def sharpe(r):
    r = np.asarray(r, float); sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(365)) if sd > 0 else float("nan")


def max_dd(r):
    eq = np.concatenate([[1.0], np.cumprod(1 + np.asarray(r, float))]); pk = np.maximum.accumulate(eq); return float((eq / pk - 1).min())


def w_equal(): return {MOM: 0.5, VEX: 0.5}


def w_invvol(sig):
    inv = {k: 1.0 / sig[k] for k in SLEEVES}; s = sum(inv.values()); return {k: inv[k] / s for k in SLEEVES}


def risk_contrib(w, sig, rho):
    a, b = w[MOM], w[VEX]; sa, sb = sig[MOM], sig[VEX]
    var = (a * sa) ** 2 + (b * sb) ** 2 + 2 * a * b * rho * sa * sb
    return {MOM: a * (a * sa ** 2 + b * rho * sa * sb) / var, VEX: b * (b * sb ** 2 + a * rho * sa * sb) / var}


def w_riskbudget(sig, rho, budget=BUDGET_RB):
    """Weights summing to 1 whose volatility risk contributions equal `budget` (monotone in w_MOM: bisection)."""
    lo, hi = 1e-6, 1 - 1e-6
    for _ in range(200):
        mid = 0.5 * (lo + hi); rc = risk_contrib({MOM: mid, VEX: 1 - mid}, sig, rho)[MOM]
        if rc < budget[MOM]: lo = mid
        else: hi = mid
    m = 0.5 * (lo + hi); return {MOM: m, VEX: 1 - m}


def estimate(rm, rv):
    """Sleeve volatility (daily) and correlation from estimation-window daily returns of the w=1 sleeves."""
    return {MOM: float(np.std(rm, ddof=1)), VEX: float(np.std(rv, ddof=1))}, float(np.corrcoef(rm, rv)[0, 1])


def scheme_params(sc, w):
    """Shared-book admission parameters of a scheme (design choices declared in the plan amendment): per-trade risk = w_i x 1 % of equity."""
    if sc == "CONS":
        return dict(per_trade={k: w[k] * 0.01 for k in SLEEVES}, total=0.015, max_pos=3, ncap=dict(CONS_NCAP_TOTAL), single_cap=0.15, gross_cap=0.40)
    return dict(per_trade={k: w[k] * 0.01 for k in SLEEVES}, total=0.03, max_pos=6, ncap=0.33, single_cap=0.15, gross_cap=0.60)


def scheme_weights(sig, rho):
    return {"EW": w_equal(), "IV": w_invvol(sig), "RB": w_riskbudget(sig, rho), "CONS": dict(CONS_W)}


# ------------------------------------------------------------------ portfolio assembly
def combine(w, growth):
    """Portfolio equity (start 1.0) = cash + sum w_i * growth_i (segregated sub-books); returns daily return array."""
    n = len(next(iter(growth.values()))); eq = np.full(n, 1.0 - sum(w.values()))
    for k, wk in w.items(): eq = eq + wk * growth[k]
    ser = np.concatenate([[1.0], eq]); return ser[1:] / ser[:-1] - 1


def daily_ret_from_growth(g):
    ser = np.concatenate([[1.0], np.asarray(g, float)]); return ser[1:] / ser[:-1] - 1


def rebalance_path(r, w, every):
    """Return-level model: sleeve daily returns r[k] (w=1 sub-books); capital reset to target weights every `every` days (None = never).
    Returns portfolio daily returns and the average annual capital transfer (sum |dw| per year, fraction of equity)."""
    n = len(r[MOM]); cashw = 1 - sum(w.values()); V = {k: w[k] for k in SLEEVES}; cash = cashw; out = np.zeros(n); transfer = 0.0
    for t in range(n):
        tot0 = cash + sum(V.values())
        for k in SLEEVES: V[k] *= 1 + r[k][t]
        tot1 = cash + sum(V.values()); out[t] = tot1 / tot0 - 1
        if every and (t + 1) % every == 0 and t + 1 < n:
            target = {k: w[k] * tot1 for k in SLEEVES}; transfer += sum(abs(V[k] - target[k]) for k in SLEEVES) / tot1; V = target; cash = cashw * tot1
    return out, transfer / (n / 365.0)


# ------------------------------------------------------------------ risk statistics
def _blocks(n, reps, block, rng):
    nb = int(math.ceil(n / block)); st = rng.integers(0, n, size=(reps, nb))
    return ((st[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(reps, -1)[:, :n]


def var_es(r, a):
    r = np.asarray(r, float); q = np.quantile(r, 1 - a); tail = r[r <= q]
    return float(-q), float(-tail.mean()) if len(tail) else float("nan"), int(len(tail))


def es_ci(r, a, reps=2000, seed=SEED, block=BLOCK):
    r = np.asarray(r, float); n = len(r); idx = _blocks(n, reps, block, np.random.default_rng(seed)); x = np.sort(r[idx], axis=1)
    k = max(1, int(math.ceil((1 - a) * n))); es = -x[:, :k].mean(axis=1)
    return [float(np.quantile(es, .025)), float(np.quantile(es, .975))]


def gauss_es(r, a):
    from statistics import NormalDist
    nd = NormalDist(); mu, sd = float(np.mean(r)), float(np.std(r, ddof=1)); z = nd.inv_cdf(1 - a)
    return float(-(mu - sd * nd.pdf(z) / (1 - a)))


def horizon_es(r, days, a=0.95):
    r = np.asarray(r, float); c = np.cumprod(1 + r); c = np.concatenate([[1.0], c]); h = c[days:] / c[:-days] - 1
    q = np.quantile(h, 1 - a); return float(-h[h <= q].mean()), int((h <= q).sum()), float(h.min())


def stats(r):
    r = np.asarray(r, float); n = len(r); eq = np.concatenate([[1.0], np.cumprod(1 + r)]); pk = np.maximum.accumulate(eq); dd = eq / pk - 1
    under = dd < 0; best = cur = 0
    for u in under: cur = cur + 1 if u else 0; best = max(best, cur)
    sd = r.std(ddof=1); dsd = math.sqrt(np.mean(np.minimum(r, 0) ** 2))
    return dict(days=n, total_return=float(eq[-1] - 1), cagr=float(eq[-1] ** (365.0 / n) - 1) if eq[-1] > 0 else -1.0, ann_vol=float(sd * math.sqrt(365)),
                sharpe=sharpe(r), sortino=float(r.mean() / dsd * math.sqrt(365)) if dsd > 0 else float("nan"), max_dd=float(dd.min()), longest_underwater_days=int(best))


def paired_boot(r, rb, reps=REPS, block=BLOCK, seed=SEED):
    r, rb = np.asarray(r, float), np.asarray(rb, float); d = r - rb; n = len(d); idx = _blocks(n, reps, block, np.random.default_rng(seed))
    def shp(X):
        sd = X.std(axis=1, ddof=1); return np.where(sd > 0, X.mean(axis=1) / np.where(sd > 0, sd, 1) * math.sqrt(365), np.nan)
    ds = shp(r[idx]) - shp(rb[idx]); md = d[idx].mean(axis=1)
    return dict(dSharpe=sharpe(r) - sharpe(rb), p_one_sided=float((1 + (md <= 0).sum()) / (reps + 1)), dSharpe_ci95=[float(np.nanquantile(ds, .025)), float(np.nanquantile(ds, .975))])


def sharpe_ci(r, reps=REPS, block=BLOCK, seed=SEED):
    r = np.asarray(r, float); n = len(r); idx = _blocks(n, reps, block, np.random.default_rng(seed)); X = r[idx]
    sd = X.std(axis=1, ddof=1); s = np.where(sd > 0, X.mean(axis=1) / np.where(sd > 0, sd, 1) * math.sqrt(365), np.nan)
    return [float(np.nanquantile(s, .025)), float(np.nanquantile(s, .975))], float(np.nanmean(s <= 0))


def holm(p: dict):
    items = sorted(p.items(), key=lambda kv: kv[1]); m = len(items); out = {}; run = 0.0
    for i, (k, v) in enumerate(items): run = max(run, min(1.0, (m - i) * v)); out[k] = run
    return out


# ------------------------------------------------------------------ correlation structure
def corr_summary(R):
    """R: DataFrame of daily returns (columns=assets). Returns mean pairwise corr, PCA share, effective number of bets (participation ratio)."""
    C = R.corr().to_numpy(); n = C.shape[0]; iu = np.triu_indices(n, 1); ev = np.sort(np.linalg.eigvalsh(C))[::-1]
    return dict(mean_pairwise=float(np.nanmean(C[iu])), min_pairwise=float(np.nanmin(C[iu])), pc1_share=float(ev[0] / ev.sum()), eff_bets=float(ev.sum() ** 2 / (ev ** 2).sum()), n_assets=n)


def tail_coexceed(R, q=0.05):
    """Mean over pairs of P(B <= its q-quantile | A <= its q-quantile) (symmetrised); independence would give q."""
    X = R.to_numpy(); lo = X <= np.nanquantile(X, q, axis=0); n = X.shape[1]; vals = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = lo[:, i], lo[:, j]; vals.append(0.5 * ((a & b).sum() / max(a.sum(), 1) + (a & b).sum() / max(b.sum(), 1)))
    return float(np.mean(vals))


# ------------------------------------------------------------------ simulation lab (real data only)
class Lab:
    def __init__(self, syms=None):
        self.syms = syms or load_grid.get(); self._c = {}; self._s = {}; self.n_sims = 0

    def cands(self, sid, cost):
        k = (sid, cost)
        if k not in self._c: self._c[k] = A.cands_for(sid, E.DEFAULTS[sid], self.syms, cost[0], cost[1])
        return self._c[k]

    def shared(self, sc, w, win, cost=BASE):
        prm = scheme_params(sc, w); k = ("shared", sc, tuple(sorted((a, round(b, 9)) for a, b in w.items())), win, cost)
        if k not in self._s:
            cands = self.cands(MOM, cost) + self.cands(VEX, cost)
            res = simulate_shared(cands, self.syms, win[0], win[1], cost[0], cost[1], **prm); self.n_sims += 1; self._s[k] = _shared_view(res)
        return self._s[k]

    def sleeve(self, sid, win, cost=BASE, frac=1.0, ncap=0.33):
        k = (sid, win, cost, round(frac, 9), ncap)
        if k not in self._s:
            res = A.run_window(self.cands(sid, cost), self.syms, win, cost[0], cost[1], capital=A.CAP * frac, ncap=ncap); self.n_sims += 1
            d = A.daily_equity(res) / (A.CAP * frac)
            self._s[k] = dict(g=d, r=daily_ret_from_growth(d), trades=res["trades"], hourly=res["equity"] / (A.CAP * frac), ws=res["ws"], we=res["we"], cap=A.CAP * frac)
        return self._s[k]


def _shared_view(res, cap=A.CAP):
    d = res["equity"][23::24][: len(res["equity"]) // 24]; ser = np.concatenate([[cap], d]); r = ser[1:] / ser[:-1] - 1
    contrib = {sid: np.diff(np.concatenate([[0.0], pn[23::24][: len(pn) // 24]])) / cap for sid, pn in res["pnl_by"].items()}
    by = {sid: [t for t in res["trades"] if t["strategy"] == sid] for sid in SLEEVES}
    return dict(r=r, contrib=contrib, trades=res["trades"], trades_by=by, eqh=res["equity"], skips=res["skips"], growth=d / cap)


def exposure(trades_by_sleeve, w, ws, we, syms, eq=None):
    """Hourly open risk, gross notional, positions and per-symbol notional (fractions of TOTAL equity ~ E_entry) from realised trades scaled by sleeve weight.
    `trades_by_sleeve[sid]` = (trades, cap) where cap is the sub-book capital in $ the trades were simulated on."""
    H = we - ws; risk = np.zeros(H); notl = np.zeros(H); npos = np.zeros(H); per = {}; occ = {sid: {} for sid in trades_by_sleeve}
    for sid, (trs, cap) in trades_by_sleeve.items():
        sc = w[sid] * A.CAP / cap if cap else 0.0       # scale to a sleeve of weight w on $10k total
        for t in trs:
            a = max(t["entry_hour"], ws) - ws; b = min(t["exit_hour"] + (t["tf"] if t["kind"] in ("stop", "target") else 1), we) - ws
            if b <= a: continue
            r = t["reserved_risk"] * sc; nt = t["qty"] * t["entry_fill"] * sc
            risk[a:b] += r; notl[a:b] += nt; npos[a:b] += 1; per.setdefault(t["symbol"], np.zeros(H))[a:b] += nt
            occ[sid].setdefault(t["symbol"], np.zeros(H, bool))[a:b] = True
    den = np.full(H, A.CAP) if eq is None else np.asarray(eq, float)       # contemporaneous total equity in $ (default: initial capital)
    risk, notl = risk / den, notl / den; per = {k: v / den for k, v in per.items()}
    maxsym = np.max(np.vstack(list(per.values())), axis=0) if per else np.zeros(H)
    overlap = np.zeros(H, bool)
    if len(trades_by_sleeve) > 1:
        sids = list(trades_by_sleeve)
        for s in occ[sids[0]]:
            if s in occ[sids[1]]: overlap |= occ[sids[0]][s] & occ[sids[1]][s]
    return dict(open_risk=risk, gross=notl, positions=npos, max_single_asset=maxsym, same_symbol_overlap=overlap)
