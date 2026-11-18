"""Stage 02 analysis: metrics, bootstrap, nulls, benchmarks. Research only."""
from __future__ import annotations
import math, json
import numpy as np, pandas as pd
from . import engine as E

CAP = 10_000.0
def hr(date): return int((pd.Timestamp(date, tz="UTC").timestamp() * 1000 - E.T0_MS) // E.HOUR)
WINDOWS = {"train": (hr("2021-11-17"), hr("2024-11-17")), "validation": (hr("2024-11-17"), hr("2025-11-17")), "final": (hr("2025-11-17"), hr("2026-11-17"))}
def hdate(h): return pd.Timestamp(E.T0_MS + h * E.HOUR, unit="ms", tz="UTC")

# ------------------------------------------------------------------ candidates + sim
def cands_for(sid, P, syms, f, s, mode="signal", end_b=None, stats=None, only=None):
    out = []
    for name in (only or E.SYMS):
        c = E.candidates(sid, syms[name], P, syms["BTC"], f, s, mode, end_b, stats)
        out += [E.finalize(x, f, s) for x in c]
    return out

def run_window(cands, syms, win, f, s, **kw):
    ws, we = WINDOWS[win] if isinstance(win, str) else win
    return E.simulate(cands, syms, ws, we, f, s, **kw)

# ------------------------------------------------------------------ metrics
def daily_equity(res):
    eq = res["equity"]; H = len(eq); d = eq[23::24][: H // 24]; return d

def eq_metrics(d, cap=CAP):
    """d: daily equity array (end-of-day)."""
    n = len(d); ser = np.concatenate([[cap], d]); r = ser[1:] / ser[:-1] - 1
    yrs = n / 365.0; end = d[-1]
    cagr = (end / cap) ** (1 / yrs) - 1 if end > 0 else -1.0
    sd = r.std(ddof=1); vol = sd * math.sqrt(365)
    sharpe = r.mean() / sd * math.sqrt(365) if sd > 0 else float("nan")
    dd_dev = math.sqrt(np.mean(np.minimum(r, 0) ** 2))
    sortino = r.mean() / dd_dev * math.sqrt(365) if dd_dev > 0 else float("nan")
    peak = np.maximum.accumulate(ser); dd = ser / peak - 1; mdd = dd.min(); it = int(dd.argmin())
    ip = int(np.where(ser[: it + 1] == peak[it])[0][0]) if it > 0 else 0
    rec = np.where(ser[it:] >= peak[it])[0]
    recovered = len(rec) > 0
    rec_days = int(rec[0]) + (it - ip) if recovered else None            # peak -> recovery
    # longest underwater spell
    under = dd < 0; best = cur = 0
    for u in under:
        cur = cur + 1 if u else 0; best = max(best, cur)
    return dict(days=n, total_return=end / cap - 1, cagr=cagr, ann_vol=vol, sharpe=sharpe, sortino=sortino, max_dd=mdd,
                mdd_peak_to_trough_days=it - ip, mdd_peak_to_recovery_days=rec_days, mdd_recovered=recovered,
                longest_underwater_days=best, daily_returns=r)

def trade_metrics(tr):
    if not tr: return dict(n=0)
    pnl = np.array([t["pnl"] for t in tr]); risk = np.array([t["reserved_risk"] for t in tr]); R = pnl / risk
    gp = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
    return dict(n=len(tr), win_rate=float((pnl > 0).mean()), profit_factor=(gp / gl if gl > 0 else float("inf")), net_pnl=float(pnl.sum()),
                ratio=float(pnl.sum() / risk.sum()), expectancy_R=float(R.mean()), median_R=float(np.median(R)), R_sd=float(R.std(ddof=1)) if len(R) > 1 else float("nan"),
                avg_win_R=float(R[R > 0].mean()) if (R > 0).any() else None, avg_loss_R=float(R[R <= 0].mean()) if (R <= 0).any() else None,
                gross_profit=float(gp), gross_loss=float(gl), fees=float(sum(t["fees"] for t in tr)),
                avg_bars=float(np.mean([t["bars"] for t in tr if t["bars"]])) if any(t["bars"] for t in tr) else None,
                forced_closes=int(sum(t["forced"] for t in tr)), stop_exits=int(sum(t["kind"] == "stop" for t in tr)),
                target_exits=int(sum(t["kind"] == "target" for t in tr)), open_exits=int(sum(t["kind"] == "open" for t in tr)),
                worst5_loss=float(np.sort(pnl)[:5].clip(max=0).sum()), gt1R_loss=int((R < -1.0).sum()))

def full_metrics(res):
    d = daily_equity(res); m = eq_metrics(d); r = m.pop("daily_returns")
    tm = trade_metrics(res["trades"]); H = len(res["equity"]); ws, we = res["ws"], res["we"]
    inpos = np.zeros(H, bool)
    for t in res["trades"]: inpos[t["entry_hour"] - ws: max(t["exit_hour"] - ws, t["entry_hour"] - ws + 1)] = True
    eq = res["equity"]; yrs = H / 24 / 365
    tot = sum(t["buy_notional"] + t["sell_notional"] for t in res["trades"])
    m.update(tm); m.update(exposure_time=float(inpos.mean()), avg_invested_pct_equity=float(np.mean(res["posv"] / eq)),
        turnover_per_year=float(tot / eq.mean() / yrs), skips=res["skips"], final_equity=float(d[-1]))
    return m, r

# ------------------------------------------------------------------ bootstrap
def block_ratio_boot(trades, ws, we, reps=10_000, seed=20261118, block=14, conf=0.9917):
    D = (we - ws) // 24
    pnl = np.zeros(D); risk = np.zeros(D)
    for t in trades:
        k = (t["entry_hour"] - ws) // 24; pnl[k] += t["pnl"]; risk[k] += t["reserved_risk"]
    cp = np.concatenate([[0], np.cumsum(np.concatenate([pnl, pnl]))]); cr = np.concatenate([[0], np.cumsum(np.concatenate([risk, risk]))])
    nb = math.ceil(D / block); rng = np.random.default_rng(seed)
    st = rng.integers(0, D, size=(reps, nb))
    sp = (cp[st + block] - cp[st]).sum(1); sr = (cr[st + block] - cr[st]).sum(1)
    with np.errstate(divide="ignore", invalid="ignore"): ratio = np.where(sr > 0, sp / sr, np.nan)
    ok = ratio[~np.isnan(ratio)]
    return dict(reps=reps, valid_reps=int(len(ok)), point=float(pnl.sum() / risk.sum()) if risk.sum() > 0 else None,
                lower_one_sided=float(np.quantile(ok, 1 - conf)) if len(ok) else None, ci95=[float(np.quantile(ok, .025)), float(np.quantile(ok, .975))] if len(ok) else None,
                p_le_0=float((ok <= 0).mean()) if len(ok) else None, empty_resample_share=float(np.isnan(ratio).mean()))

def sharpe_boot(r, reps=2000, seed=20261118, block=14):
    n = len(r); rng = np.random.default_rng(seed); nb = math.ceil(n / block)
    rr = np.concatenate([r, r]); cs1 = np.concatenate([[0], np.cumsum(rr)]); cs2 = np.concatenate([[0], np.cumsum(rr ** 2)])
    st = rng.integers(0, n, size=(reps, nb)); m = nb * block
    s1 = (cs1[st + block] - cs1[st]).sum(1); s2 = (cs2[st + block] - cs2[st]).sum(1)
    mean = s1 / m; var = (s2 - m * mean ** 2) / (m - 1)
    sh = mean / np.sqrt(var) * math.sqrt(365)
    return [float(np.quantile(sh, .025)), float(np.quantile(sh, .975))]

# ------------------------------------------------------------------ random-entry null (F4)
def unit_pool(sid, P, syms, f, s, win):
    ws, we = WINDOWS[win]
    P2 = dict(P); tf = P["tf"]
    cands = []
    for name in E.SYMS:
        c = E.candidates(sid, syms[name], P2, syms["BTC"], f, s, mode="pool", end_b=we // tf)
        for x in c:
            if not (ws <= x["t_entry"] < we): continue
            if x["kind"] == "END" or (x["b0"] * tf >= we):
                px = syms[name].cff[we - 1] * (1 - s)
            else:
                px = x["raw"] * (1 - s)
            pnl_u = px * (1 - f) - x["Pf"] * (1 + f); cands.append((name, pnl_u / x["d"]))
    by = {}
    for name, R in cands: by.setdefault(name, []).append(R)
    return {k: np.array(v) for k, v in by.items()}

def null_test(real_trades, pool, draws=1000, seed=20261118):
    rng = np.random.default_rng(seed); syms = [t["symbol"] for t in real_trades]
    allR = np.concatenate(list(pool.values())) if pool else np.array([])
    real = float(np.mean([t["R"] for t in real_trades])) if real_trades else float("nan")
    if not len(allR) or not syms: return dict(real_mean_R=real, n_pool=int(len(allR)))
    means = np.zeros(draws)
    for k in range(draws):
        means[k] = np.mean([rng.choice(pool[s]) if s in pool and len(pool[s]) else rng.choice(allR) for s in syms])
    return dict(real_mean_R=real, null_mean=float(means.mean()), null_p05=float(np.quantile(means, .05)), null_p95=float(np.quantile(means, .95)),
                p_value=float((means >= real).mean()), n_pool=int(len(allR)), draws=draws, exceeds_p95=bool(real > np.quantile(means, .95)))

# ------------------------------------------------------------------ benchmarks
def daily_ohlc_btc(syms):
    sy = syms["BTC"]; n = len(sy.c) // 24
    o = pd.Series(sy.o).ffill().bfill().to_numpy()[: n * 24].reshape(n, 24)[:, 0]; c = sy.cff[: n * 24].reshape(n, 24)[:, -1]
    return o, c

def bench_daily_equity(syms, win, f, s, kind):
    ws, we = WINDOWS[win]; d0, d1 = ws // 24, we // 24
    if kind in ("EW_BH", "BTC_BH"):
        names = E.SYMS if kind == "EW_BH" else ["BTC"]; val = np.zeros(d1 - d0)
        for nme in names:
            sy = syms[nme]; op = pd.Series(sy.o).ffill().to_numpy()[ws]
            q = (CAP / len(names)) / (op * (1 + s) * (1 + f))
            val += q * sy.cff[ws:we][23::24][: d1 - d0]
        return val
    o, c = daily_ohlc_btc(syms); sma = pd.Series(c).rolling(200, min_periods=200).mean().to_numpy()
    cash, qty = CAP, 0.0; val = np.zeros(d1 - d0); pos = False
    for k, d in enumerate(range(d0, d1)):
        want = bool(c[d - 1] > sma[d - 1]) if np.isfinite(sma[d - 1]) else False   # signal known at prior daily close
        if want and not pos:
            qty = cash / (o[d] * (1 + s) * (1 + f)); cash = 0.0; pos = True
        elif (not want) and pos:
            cash = qty * o[d] * (1 - s) * (1 - f); qty = 0.0; pos = False
        val[k] = cash + qty * c[d]
    return val

# ------------------------------------------------------------------ regimes
def btc_regime_by_day(syms):
    o, c = daily_ohlc_btc(syms); sma = pd.Series(c).rolling(200, min_periods=200).mean().to_numpy()
    lr = np.log(c[1:] / c[:-1]); vol = pd.Series(np.concatenate([[np.nan], lr])).rolling(30, min_periods=30).std(ddof=1).to_numpy() * math.sqrt(365)
    lab = np.full(len(c), "NA", dtype=object)
    for d in range(1, len(c)):    # label for day d uses PRIOR day's close/vol (d-1)
        p = d - 1
        if np.isfinite(sma[p]) and np.isfinite(vol[p]):
            lab[d] = ("UP" if c[p] > sma[p] else "DOWN") + "_" + ("HIGHVOL" if vol[p] > 0.60 else "LOWVOL")
    return lab
