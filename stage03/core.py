"""Stage 03 risk analytics. Research only: reads Stage 02 engine output; places no orders.
Every function returns plain numbers; labels (HISTORICAL / HYPOTHETICAL / UNQUANTIFIED) are attached by the runner."""
from __future__ import annotations
import math
from statistics import NormalDist
import numpy as np, pandas as pd
from stage02 import engine as E, analysis as A

BASE = (0.001, 0.0005)
BOOKS = ["CRY-MOM-101", "CRY-REV-102", "CRY-VEX-103", "COMBINED"]
WINS = list(A.WINDOWS)


def build_cands(syms, f, s):
    c = {sid: A.cands_for(sid, E.DEFAULTS[sid], syms, f, s) for sid in E.DEFAULTS}
    c["COMBINED"] = sum(c.values(), [])
    return c


def run_all(cands, syms, f, s, **kw):
    return {b: {w: A.run_window(cands[b], syms, w, f, s, **kw) for w in WINS} for b in BOOKS}


def exit_end(t):
    """First hour index at which the position no longer exists (intrabar stop/target frees at bar end)."""
    if t["kind"] in ("stop", "target"): return t["exit_hour"] + t["tf"]
    if t["kind"] == "forced": return t["exit_hour"] + 1
    return t["exit_hour"]


# ------------------------------------------------------------------ distribution risk
def var_es(r, a):
    r = np.asarray(r); q = np.quantile(r, 1 - a); tail = r[r <= q]
    return float(-q), float(-tail.mean()) if len(tail) else float("nan")

def gauss_var_es(r, a):
    nd = NormalDist(); mu, sd = float(np.mean(r)), float(np.std(r, ddof=1)); z = nd.inv_cdf(1 - a)
    return float(-(mu + z * sd)), float(-(mu - sd * nd.pdf(z) / (1 - a)))

def block_var_es_ci(r, a, reps=2000, seed=20261118, block=14):
    r = np.asarray(r); n = len(r); rng = np.random.default_rng(seed); nb = math.ceil(n / block)
    rr = np.concatenate([r, r]); st = rng.integers(0, n, size=(reps, nb))
    idx = (st[:, :, None] + np.arange(block)[None, None, :]).reshape(reps, -1)[:, :n]
    x = np.sort(rr[idx], axis=1); k = max(1, int(math.ceil((1 - a) * n)))
    q = x[:, k - 1]; es = x[:, :k].mean(axis=1)
    return [float(np.quantile(-q, .025)), float(np.quantile(-q, .975))], [float(np.quantile(-es, .025)), float(np.quantile(-es, .975))]

def hourly_maxdd(eq, cap=A.CAP):
    ser = np.concatenate([[cap], eq]); pk = np.maximum.accumulate(ser); return float((ser / pk - 1).min())

def daily_ret(res):
    d = A.daily_equity(res); ser = np.concatenate([[A.CAP], d]); return ser[1:] / ser[:-1] - 1

def rolling_horizon_ret(res, days):
    d = np.concatenate([[A.CAP], A.daily_equity(res)]); return d[days:] / d[:-days] - 1


# ------------------------------------------------------------------ loss streaks
def loss_runs(trades):
    """Chronological by exit time; a loss is pnl <= 0. Returns list of (length, cum_R, cum_pnl)."""
    tr = sorted(trades, key=lambda t: (exit_end(t), t["entry_hour"]))
    runs, cur = [], []
    for t in tr:
        if t["pnl"] <= 0: cur.append(t)
        elif cur: runs.append(cur); cur = []
    if cur: runs.append(cur)
    return [(len(r), float(sum(x["R"] for x in r)), float(sum(x["pnl"] for x in r))) for r in runs]

def streak_summary(per_window_trades):
    allruns = []
    for tr in per_window_trades: allruns += loss_runs(tr)
    lens = [x[0] for x in allruns]; n = sum(len(t) for t in per_window_trades)
    hist = {}
    for l in lens: hist[l] = hist.get(l, 0) + 1
    worst = max(allruns, key=lambda x: x[0]) if allruns else None
    worst_cost = min(allruns, key=lambda x: x[2]) if allruns else None
    nl = sum(1 for tr in per_window_trades for t in tr if t["pnl"] <= 0); p = nl / n if n else float("nan")
    return dict(n_trades=n, n_losses=nl, loss_share=p, runs=len(lens), max_run=max(lens) if lens else 0, histogram={int(k): v for k, v in sorted(hist.items())},
                runs_ge5=int(sum(l >= 5 for l in lens)), runs_ge8=int(sum(l >= 8 for l in lens)), runs_ge10=int(sum(l >= 10 for l in lens)),
                worst_run_R=worst_cost[1] if worst_cost else None, worst_run_len_of_costliest=worst_cost[0] if worst_cost else None,
                worst_run_pnl_usd=worst_cost[2] if worst_cost else None)

def iid_expected_runs_ge(n, p, k):
    """Model-based (iid) expected count of loss runs of length >= k in n trades: approx (n)(1-p) p^k + p^k (boundary). ILLUSTRATIVE."""
    return float(n * (1 - p) * p ** k + p ** k) if 0 < p < 1 else float("nan")


# ------------------------------------------------------------------ exposure / shocks
def hourly_positions(res, syms, with_fwd=None):
    """Per-hour arrays over the window: gross mark-notional, open count; shock-relevant sums.
    A position is held through the end of hour h if entry_hour <= h < exit_end."""
    ws, we = res["ws"], res["we"]; H = we - ws
    gross = np.zeros(H); cnt = np.zeros(H, int); risk = np.zeros(H)
    for t in res["trades"]:
        a = max(t["entry_hour"], ws); b = min(exit_end(t), we)
        if b <= a: continue
        h = np.arange(a, b); mk = syms[t["symbol"]].cff[h]
        gross[a - ws:b - ws] += t["qty"] * mk; cnt[a - ws:b - ws] += 1; risk[a - ws:b - ws] += t["reserved_risk"]
    return gross, cnt, risk

def gap_shock(res, syms, shock, extra_slip, f, s):
    """HYPOTHETICAL: instantaneous fall of `shock` in every open position's mark at the close of each hour; stops do not protect
    (fill at gapped price*(1-s-extra_slip)), exit fee f. Returns loss as fraction of that hour's equity (positions only)."""
    ws, we = res["ws"], res["we"]; H = we - ws; loss = np.zeros(H)
    for t in res["trades"]:
        a = max(t["entry_hour"], ws); b = min(exit_end(t), we)
        if b <= a: continue
        h = np.arange(a, b); mk = syms[t["symbol"]].cff[h]
        fill = mk * (1 - shock) * (1 - s - extra_slip)
        loss[a - ws:b - ws] += t["qty"] * (mk - fill * (1 - f))
    return loss / res["equity"]

def fwd_min_low(sy, T):
    """min low over hours (h+1 .. h+T); NaN-safe via pandas rolling on reversed series."""
    l = pd.Series(sy.l).where(sy.valid)
    rev = l.iloc[::-1].rolling(T, min_periods=1).min().iloc[::-1]
    return rev.shift(-1).to_numpy()

def freeze_loss(res, syms, T, f, s, cache):
    """HYPOTHETICAL venue outage: positions cannot be exited for T hours; loss = worst adverse excursion vs mark, exit at the trough."""
    ws, we = res["ws"], res["we"]; H = we - ws; loss = np.zeros(H)
    for t in res["trades"]:
        a = max(t["entry_hour"], ws); b = min(exit_end(t), we)
        if b <= a: continue
        key = (t["symbol"], T)
        if key not in cache: cache[key] = fwd_min_low(syms[t["symbol"]], T)
        h = np.arange(a, b); mk = syms[t["symbol"]].cff[h]; fm = cache[key][h]
        fm = np.where(np.isfinite(fm), fm, mk)
        loss[a - ws:b - ws] += t["qty"] * np.maximum(0.0, mk - fm * (1 - s) * (1 - f))
    return loss / res["equity"]

def dist_stats(x, mask=None):
    x = np.asarray(x); xs = x[mask] if mask is not None else x
    if len(xs) == 0: return dict(n_hours=0)
    return dict(n_hours=int(len(xs)), max=float(xs.max()), p99=float(np.quantile(xs, .99)), p95=float(np.quantile(xs, .95)), mean=float(xs.mean()))

def top_episodes(x, ws, k=3, sep=168):
    """Dates of the k largest values at least `sep` hours apart."""
    x = np.asarray(x); order = np.argsort(-x); out = []
    for i in order:
        if x[i] <= 0: break
        if all(abs(i - j) >= sep for j, _ in out): out.append((int(i), float(x[i])))
        if len(out) == k: break
    return [dict(utc=str(A.hdate(ws + i)), value=v) for i, v in out]


# ------------------------------------------------------------------ throttle replay (approximation)
def throttle_replay(trades, cap=A.CAP, l1=0.10, l2=0.20, m1=0.5):
    """Replay a drawdown throttle on realised closed-trade equity by scaling later trades' P&L linearly.
    NOT a re-simulation: ignores cash/slot/participation interactions and compounding of sizing. The multiplier is decided at
    entry from closed-trade equity (trades whose exit_end <= entry_hour): 1.0 above -l1, m1 between -l1 and -l2, 0 (halt) at/below -l2."""
    tr = sorted(trades, key=lambda t: t["entry_hour"]); scaled = []; halted = False; events = []
    for t in tr:
        h = t["entry_hour"]; done = sorted((xe, p) for xe, p in scaled if xe <= h)
        ser = cap + np.cumsum([p for _, p in done]) if done else np.array([cap])
        dd = ser[-1] / max(cap, ser.max()) - 1
        if dd <= -l2 and not halted: halted = True; events.append(("HALT", int(h)))
        m = 0.0 if halted else (m1 if dd <= -l1 else 1.0)
        scaled.append((exit_end(t), t["pnl"] * m))
    mdd, net = closed_dd_pts(scaled, cap)
    return dict(max_dd_closed=mdd, net_pnl=net, halted=halted, events=events, trades_taken=int(sum(1 for _, p in scaled if p != 0)))

def closed_dd_pts(pts, cap=A.CAP):
    pts = sorted(pts); ser = np.concatenate([[cap], cap + np.cumsum([p for _, p in pts])]) if pts else np.array([cap])
    pk = np.maximum.accumulate(ser); return float((ser / pk - 1).min()), float(ser[-1] - cap)

def closed_dd(trades, cap=A.CAP):
    return closed_dd_pts([(exit_end(t), t["pnl"]) for t in trades], cap)
