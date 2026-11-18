"""Stage 04 regime measurement. Research only. Read-only public data; no orders, no credentials.
THRESHOLDS below are fixed BEFORE the current readings were computed (they are conventional values; see TH_STATUS for which still need calibration)."""
from __future__ import annotations
import json, pickle, math, hashlib, sys, glob
from pathlib import Path
from datetime import datetime, timezone
import numpy as np, pandas as pd
from stage02 import engine as E, analysis as A

ROOT = Path(__file__).resolve().parents[1]
SYMS = E.SYMS
TH = dict(
    ema=(20, 50, 200), adx_n=14, atr_n=14,
    adx_trend=25.0, adx_range=20.0, er_range=0.30, er_n=30,
    dir_votes_needed=4, side_ret30=0.05,
    vol_pct=(25.0, 75.0, 95.0), rv_n=30,
    liq_strong=1.25, liq_weak=0.75, vol_base_days=30,
    breadth=0.60, stale_hours=2.0, xvenue_bp=30.0,
    fund_crowd_ann=0.30, mom_M=1.25,
    corr_high=0.90,
)
TH_STATUS = {
    "ema (20/50/200), adx 14, atr 14": "PRESELECTED (conventional; also spec-mandated by the task)",
    "adx_trend 25 / adx_range 20": "PRESELECTED (Wilder convention); not calibrated to this universe",
    "er_range 0.30 (Kaufman efficiency, 30d)": "REQUIRES CALIBRATION (arbitrary cut)",
    "direction needs >=4 of 5 votes": "REQUIRES CALIBRATION (agreement rule, not tested for stability)",
    "sideways: |30d return| < 5%": "REQUIRES CALIBRATION",
    "volatility percentile cuts 25/75/95 of own history (RV30)": "PRESELECTED cut points; the history (2021-05..now, includes consumed windows) is a descriptive reference only; calibration of cuts REQUIRED",
    "liquidity ratio 1.25 / 0.75 vs 30d median daily quote volume": "REQUIRES CALIBRATION",
    "breadth 0.60 for market-level label": "REQUIRES CALIBRATION",
    "staleness > 2h; cross-venue gap > 30bp": "PRESELECTED operational limits",
    "funding crowding |annualised| > 30%": "REQUIRES CALIBRATION",
}

# --------------------------------------------------------------- data
def latest_snapshot():
    return sorted((ROOT / "data" / "s4raw").glob("2*"))[-1]

def jl(snap, name):
    p = snap / name
    return json.loads(p.read_text()) if p.exists() else None

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def extended_grid(snap):
    """Archive grid (to 2026-11-17) + fresh Binance spot 1H klines (complete bars only). Returns syms, n, overlap_check."""
    old = pickle.loads((ROOT / "data" / "s2grid.pkl").read_bytes())
    man = jl(snap, "MANIFEST.json"); fetched = {m["name"]: m["fetched_utc"] for m in man["items"]}
    frames, ovl, last_close_ms = {}, {}, 0
    for s in SYMS:
        sy = old[s]; idx = np.where(sy.valid)[0]
        base = pd.DataFrame(dict(t=E.T0_MS + idx.astype(np.int64) * E.HOUR, o=sy.o[idx], h=sy.h[idx], l=sy.l[idx], c=sy.c[idx], v=sy.v[idx], q=sy.q[idx]))
        k = jl(snap, f"binance_1h_{s}.json")
        ft = pd.Timestamp(fetched[f"binance_1h_{s}.json"]).value // 10**6
        fr = pd.DataFrame([[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), float(x[7]), int(x[6])] for x in k], columns=["t", "o", "h", "l", "c", "v", "q", "ct"])
        fr = fr[fr["ct"] < ft].drop(columns="ct")           # complete bars only
        m = base.merge(fr, on="t", suffixes=("_a", "_n"))
        ovl[s] = dict(n_overlap=int(len(m)), max_rel_close_diff=float((m.c_a / m.c_n - 1).abs().max()) if len(m) else None,
                      max_rel_q_diff=float((m.q_a / m.q_n - 1).abs().max()) if len(m) else None)
        new = fr[~fr["t"].isin(base["t"])]
        frames[s] = pd.concat([base, new], ignore_index=True).sort_values("t").reset_index(drop=True)
        last_close_ms = max(last_close_ms, int(frames[s]["t"].iloc[-1]))
    nh = (last_close_ms - E.T0_MS) // E.HOUR + 1; n = int(math.ceil(nh / 24) * 24)
    return E.build_grid(frames, n), n, ovl

def daily_frame(sy, n):
    nd = n // 24
    r = lambda a: a[: nd * 24].reshape(nd, 24)
    v = r(sy.valid); o = r(sy.o); h = r(sy.h); l = r(sy.l); c = r(sy.c); q = r(sy.q)
    cnt = v.sum(axis=1)
    with np.errstate(all="ignore"):
        d = pd.DataFrame(dict(o=np.where(v[:, 0], o[:, 0], np.nan), h=np.nanmax(np.where(v, h, np.nan), axis=1), l=np.nanmin(np.where(v, l, np.nan), axis=1),
                              c=np.where(v[:, 23], c[:, 23], np.nan), q=np.nansum(np.where(v, q, 0), axis=1), nbar=cnt))
    d.index = pd.to_datetime(E.T0_MS + np.arange(nd) * 86400_000, unit="ms", utc=True)
    return d

# --------------------------------------------------------------- indicators
def ema(x, n): return x.ewm(span=n, adjust=False, min_periods=n).mean()

def adx(d, n=14):
    h, l, c = d.h, d.l, d.c; up = h.diff(); dn = -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = 1.0 / n; atr = tr.ewm(alpha=a, adjust=False, min_periods=n).mean()
    pdi = 100 * pd.Series(pdm, index=d.index).ewm(alpha=a, adjust=False, min_periods=n).mean() / atr
    mdi = 100 * pd.Series(mdm, index=d.index).ewm(alpha=a, adjust=False, min_periods=n).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi); adx_ = dx.ewm(alpha=a, adjust=False, min_periods=n).mean()
    return adx_, pdi, mdi, atr

def indicators(d):
    """d: completed-day frame. Returns DataFrame of indicators (value at each day = using that day's close)."""
    x = pd.DataFrame(index=d.index); c = d.c
    for n in TH["ema"]: x[f"ema{n}"] = ema(c, n)
    x["adx"], x["pdi"], x["mdi"], atr = adx(d, TH["adx_n"]); x["atr_pct"] = atr / c
    lr = np.log(c).diff(); x["rv30"] = lr.rolling(30, min_periods=30).std(ddof=1) * math.sqrt(365); x["rv7"] = lr.rolling(7, min_periods=7).std(ddof=1) * math.sqrt(365)
    n = TH["er_n"]; x["er30"] = (c - c.shift(n)).abs() / c.diff().abs().rolling(n, min_periods=n).sum()
    for k in (7, 30, 90): x[f"ret{k}"] = np.log(c / c.shift(k))
    x["c"] = c; x["qv"] = d.q; x["qmed30"] = d.q.shift(1).rolling(30, min_periods=30).median(); x["vratio"] = d.q / x["qmed30"]
    x["adx_chg5"] = x["adx"] - x["adx"].shift(5)
    return x

def pct_rank(series, value):
    s = series.dropna(); return float((s < value).mean() * 100) if len(s) else float("nan")

def classify_asset(x, hist_end):
    """x: indicator frame, last row = last COMPLETED day. Returns dict of raw readings + labels."""
    r = x.iloc[-1]; prev = x.iloc[:-1]
    votes = {"close>EMA200": int(np.sign(r.c - r.ema200)), "EMA50>EMA200": int(np.sign(r.ema50 - r.ema200)), "EMA20>EMA50": int(np.sign(r.ema20 - r.ema50)),
             "+DI>-DI": int(np.sign(r.pdi - r.mdi)), "ret30>0": int(np.sign(r.ret30))}
    nb = sum(v == 1 for v in votes.values()); ns = sum(v == -1 for v in votes.values()); need = TH["dir_votes_needed"]
    if nb >= need: direction = "Bullish"
    elif ns >= need: direction = "Bearish"
    elif r.adx < TH["adx_range"] and abs(r.ret30) < TH["side_ret30"]: direction = "Sideways"
    else: direction = "Uncertain"
    rvp = pct_rank(prev.rv30, r.rv30); lo, mid, hi = TH["vol_pct"]
    vol = "Low" if rvp < lo else "Normal" if rvp < mid else "Elevated" if rvp < hi else "Extreme"
    if r.adx >= TH["adx_trend"]: struct = "Trending"
    elif r.adx < TH["adx_range"] and r.er30 < TH["er_range"]: struct = "Mean-reverting"
    else: struct = "Transitioning"
    sg = [r.ret7, r.ret30, r.ret90]
    mom = "Positive" if all(v > 0 for v in sg) else "Negative" if all(v < 0 for v in sg) else "Mixed"
    return dict(date=str(x.index[-1].date()), close=float(r.c), ema20=float(r.ema20), ema50=float(r.ema50), ema200=float(r.ema200),
                ema_stack=("20>50>200" if r.ema20 > r.ema50 > r.ema200 else "20<50<200" if r.ema20 < r.ema50 < r.ema200 else "mixed"),
                c_vs_ema200=float(r.c / r.ema200 - 1), adx=float(r.adx), pdi=float(r.pdi), mdi=float(r.mdi), adx_chg5=float(r.adx_chg5), atr_pct=float(r.atr_pct),
                atr_pct_pctile=pct_rank(prev.atr_pct, r.atr_pct), rv30=float(r.rv30), rv30_pctile=rvp, rv7=float(r.rv7), rv7_pctile=pct_rank(prev.rv7, r.rv7),
                er30=float(r.er30), ret7=float(r.ret7), ret30=float(r.ret30), ret90=float(r.ret90), vratio=float(r.vratio), votes=votes, votes_bull=nb, votes_bear=ns,
                direction=direction, volatility=vol, structure=struct, momentum=mom, hist_days=int(prev.rv30.notna().sum()))

# --------------------------------------------------------------- strategy gate states (engine, latest complete bars)
def gate_states(syms):
    out = {}; btc = syms["BTC"]
    for sid, P in E.DEFAULTS.items():
        tf = P["tf"]; bm = {}
        for s in SYMS:
            sy = syms[s]; a = E.prep(sy, sid, P); sg = E.raw_signal(sid, sy, P, btc)
            vl = a["valid"]; j = int(np.where(vl)[0].max()); rec = dict(last_bar_utc=str(A.hdate(j * tf)), ready=bool(a["ready"][j]), liq_gates=bool(E.liq_ok(sy, tf)[j]), signal_now=bool(sg[j]),
                                                                        signals_last_24h=int(sg[max(0, j - 24 // tf + 1): j + 1].sum()), signals_last_7d=int(sg[max(0, j - 7 * 24 // tf + 1): j + 1].sum()))
            if sid == "CRY-MOM-101":
                bb = E.prep(btc, sid, P)
                rec.update(M=float(a["M"][j]), M_thr=P["thr"], c_gt_sma300=bool(a["c"][j] > a["sma"][j]), sma300_rising=bool(a["sma"][j] > a["sma30"][j]), ext=float(a["c"][j] / a["sma"][j]),
                           ext_ok=bool(a["c"][j] / a["sma"][j] <= P["ext"]), btc_filter=bool(bb["c"][j] > bb["sma"][j]))
            elif sid == "CRY-REV-102":
                rec.update(rsi3=float(a["rsi"][j]), rsi_thr=P["rsi_thr"], c_gt_sma300=bool(a["c"][j] > a["sma"][j]), drop3_atr=float(a["drop3"][j] / a["atr"][j]), ibs=float(a["ibs"][j]))
            else:
                rec.update(ctx=bool(a["ctx"][j]), break_donch=bool(a["c"][j] > a["dh"][j]), tr_atr=float(a["tr"][j] / a["atr_prev"][j]), ibs=float(a["ibs"][j]), vol_ratio=float(a["q"][j] / a["qmed_x"][j]))
            bm[s] = rec
        out[sid] = bm
    return out

# --------------------------------------------------------------- historical conditional performance (descriptive)
def hist_by_regime():
    """BTC regime tag known at the prior daily close; Stage 02 baseline standalone trades by entry-day tag. DESCRIPTIVE ONLY."""
    from stage03.core import build_cands, run_all
    syms = pickle.loads((ROOT / "data" / "s2grid.pkl").read_bytes()); n = 48648
    d = daily_frame(syms["BTC"], n).dropna(subset=["c"]); x = indicators(d)
    tag = {}
    for i in range(len(x)):
        r = x.iloc[i]
        if not np.isfinite(r.ema200) or not np.isfinite(r.adx) or not np.isfinite(r.er30): continue
        v = [np.sign(r.c - r.ema200), np.sign(r.ema50 - r.ema200), np.sign(r.ema20 - r.ema50), np.sign(r.pdi - r.mdi), np.sign(r.ret30)]
        nb = sum(u == 1 for u in v); ns = sum(u == -1 for u in v)
        dr = "Bullish" if nb >= 4 else "Bearish" if ns >= 4 else "Sideways" if (r.adx < 20 and abs(r.ret30) < 0.05) else "Uncertain"
        st = "Trending" if r.adx >= 25 else "Mean-reverting" if (r.adx < 20 and r.er30 < 0.30) else "Transitioning"
        tag[x.index[i] + pd.Timedelta(days=1)] = (dr, st)     # applies to the NEXT day
    f, s = 0.001, 0.0005; cands = build_cands(syms, f, s); runs = run_all(cands, syms, f, s)
    rows = []
    for sid in ["CRY-MOM-101", "CRY-REV-102", "CRY-VEX-103"]:
        for w, res in runs[sid].items():
            for t in res["trades"]:
                day = pd.Timestamp(E.T0_MS + t["entry_hour"] * E.HOUR, unit="ms", tz="UTC").normalize()
                dr, st = tag.get(day, ("NA", "NA")); rows.append(dict(sid=sid, win=w, dr=dr, st=st, R=t["R"], pnl=t["pnl"]))
    df = pd.DataFrame(rows); out = {}
    for sid, g in df.groupby("sid"):
        out[sid] = {}
        for key, col in (("direction", "dr"), ("structure", "st"), ("dir_x_struct", None)):
            gg = g.assign(k=g.dr + "|" + g.st) if col is None else g.assign(k=g[col])
            tb = gg.groupby("k").agg(n=("R", "size"), mean_R=("R", "mean"), win_rate=("R", lambda z: float((z > 0).mean())), pnl=("pnl", "sum"))
            out[sid][key] = {k: dict(n=int(v.n), mean_R=float(v.mean_R), win_rate=float(v.win_rate), pnl_usd=float(v.pnl)) for k, v in tb.iterrows()}
    # day counts per tag over the same span
    days = pd.Series({k: v for k, v in tag.items()}); dc = {"direction": days.map(lambda v: v[0]).value_counts().to_dict(), "structure": days.map(lambda v: v[1]).value_counts().to_dict(),
                                                         "dir_x_struct": days.map(lambda v: v[0] + "|" + v[1]).value_counts().to_dict()}
    return out, {k: {a: int(b) for a, b in v.items()} for k, v in dc.items()}


# --------------------------------------------------------------- live context
def book_stats(bids, asks, bp=10):
    b = [(float(x[0]), float(x[1])) for x in bids]; a = [(float(x[0]), float(x[1])) for x in asks]
    bb, ba = max(p for p, _ in b), min(p for p, _ in a); mid = (bb + ba) / 2; lim = bp / 1e4
    bd = sum(p * q for p, q in b if p >= mid * (1 - lim)); ad = sum(p * q for p, q in a if p <= mid * (1 + lim))
    return dict(mid=mid, spread_bp=(ba / bb - 1) * 1e4, bid_depth_usd_10bp=bd, ask_depth_usd_10bp=ad, bid_span_bp=(mid - min(p for p, _ in b)) / mid * 1e4,
                ask_span_bp=(max(p for p, _ in a) - mid) / mid * 1e4, levels=(len(b), len(a)))

def cross_venue(snap, syms, n):
    out = {}; kr = jl(snap, "kraken_ticker.json"); krm = {}
    if kr and kr.get("result"):
        for k, v in kr["result"].items():
            for s, tag in (("BTC", "XBT"), ("ETH", "ETH"), ("SOL", "SOL"), ("XRP", "XRP"), ("ADA", "ADA"), ("LINK", "LINK"), ("AVAX", "AVAX"), ("DOGE", "XDG"), ("LTC", "LTC")):
                if tag in k: krm[s] = float(v["c"][0])
    man = {m["name"]: m for m in jl(snap, "MANIFEST.json")["items"]}
    for s in SYMS:
        sy = syms[s]; j = int(np.where(sy.valid)[0].max()); bin_c = float(sy.c[j]); bar_open_ms = E.T0_MS + j * E.HOUR
        rec = dict(binance_last_bar_open=str(pd.Timestamp(bar_open_ms, unit="ms", tz="UTC")), binance_close=bin_c, age_hours_at_fetch=None)
        ft = pd.Timestamp(man[f"binance_1h_{s}.json"]["fetched_utc"]); rec["age_hours_at_fetch"] = float((ft.value // 10**6 - bar_open_ms - E.HOUR) / E.HOUR)
        cb = jl(snap, f"coinbase_1h_{s}.json")
        if isinstance(cb, list):
            m = {int(r[0]) * 1000: r for r in cb}; r = m.get(bar_open_ms)
            if r is not None:
                rec["coinbase_close_same_bar"] = float(r[4]); rec["basis_bp_binance_vs_coinbase"] = float((bin_c / r[4] - 1) * 1e4)
                # 24 matching bars: realised dispersion
                diffs = []
                for k in range(24):
                    t = bar_open_ms - k * E.HOUR; jj = j - k
                    if t in m and sy.valid[jj]: diffs.append(float(np.log(sy.c[jj] / m[t][4])))
                rec["basis_bp_24h_mean_absdev_from_mean"] = float(np.mean(np.abs(np.array(diffs) - np.mean(diffs))) * 1e4) if diffs else None
                rec["ret24_binance"] = float(np.log(sy.c[j] / sy.c[j - 24])); rec["ret24_coinbase"] = float(np.log(r[4] / m[bar_open_ms - 24 * E.HOUR][4])) if (bar_open_ms - 24 * E.HOUR) in m else None
        if s in krm: rec["kraken_last"] = krm[s]
        d = jl(snap, f"binance_depth_{s}.json")
        if d: rec["binance_book"] = book_stats(d["bids"], d["asks"])
        cbb = jl(snap, f"coinbase_book_{s}.json")
        if cbb: rec["coinbase_book"] = book_stats(cbb["bids"], cbb["asks"])
        t24 = jl(snap, f"binance_24h_{s}.json")
        if t24: rec["binance_24h_quote_vol_usdt"] = float(t24["quoteVolume"]); rec["binance_24h_chg_pct"] = float(t24["priceChangePercent"])
        out[s] = rec
    return out

def derivatives(snap):
    out = {"hyperliquid": {}, "okx": {}}
    hm = jl(snap, "hl_meta_ctxs.json")
    if hm:
        uni, ctx = hm[0]["universe"], hm[1]
        for u, c in zip(uni, ctx):
            if u["name"] in SYMS:
                f = float(c["funding"]); mk = float(c["markPx"]); oi = float(c["openInterest"])
                out["hyperliquid"][u["name"]] = dict(funding_1h=f, funding_ann=f * 24 * 365, premium=float(c["premium"]) if c.get("premium") is not None else None, mark=mk, oracle=float(c["oraclePx"]),
                                                     oi_usd=oi * mk, day_ntl_vol=float(c["dayNtlVlm"]), prev_day_px=float(c["prevDayPx"]))
    for s in ["BTC", "ETH", "SOL"]:
        h = jl(snap, f"hl_fundinghist_{s}.json")
        if h and s in out["hyperliquid"]:
            fr = np.array([float(x["fundingRate"]) for x in h]); cur = out["hyperliquid"][s]["funding_1h"]
            out["hyperliquid"][s].update(fund_hist_n=len(fr), fund_hist_start=str(pd.Timestamp(h[0]["time"], unit="ms", tz="UTC")), fund_pctile_31d=float((fr < cur).mean() * 100), fund_mean_31d_ann=float(fr.mean() * 24 * 365), fund_min_ann=float(fr.min() * 24 * 365), fund_max_ann=float(fr.max() * 24 * 365))
    for s in SYMS:
        f = jl(snap, f"okx_funding_{s}.json"); o = jl(snap, f"okx_oi_{s}.json")
        rec = {}
        if f and f.get("data"): d = f["data"][0]; rec.update(funding_8h=float(d["fundingRate"]), funding_ann=float(d["fundingRate"]) * 3 * 365, next_funding_time=str(pd.Timestamp(int(d["fundingTime"]), unit="ms", tz="UTC")))
        if o and o.get("data"): rec["oi_usd"] = float(o["data"][0]["oiUsd"]); rec["oi_ts"] = str(pd.Timestamp(int(o["data"][0]["ts"]), unit="ms", tz="UTC"))
        out["okx"][s] = rec
    for s, ct in (("BTC", 0.01), ("ETH", 0.1)):
        fh = jl(snap, f"okx_fundinghist_{s}.json")
        if fh and fh.get("data"):
            fr = np.array([float(x["realizedRate"]) if x.get("realizedRate") not in (None, "") else float(x["fundingRate"]) for x in fh["data"]]); cur = out["okx"][s]["funding_8h"]
            out["okx"][s].update(fund_hist_n=len(fr), fund_pctile=float((fr < cur).mean() * 100), fund_mean_ann=float(fr.mean() * 3 * 365))
        oh = jl(snap, f"okx_oihist_{s}.json")
        if oh and oh.get("data"):
            rows = [[r[0], float(r[1]), float(r[2])] for r in oh["data"]]; out["okx"][s].update(oi_hist_latest=float(rows[0][1]), oi_chg_1d=float(rows[0][1] / rows[1][1] - 1), oi_chg_7d=float(rows[0][1] / rows[7][1] - 1), oi_hist_latest_day=str(pd.Timestamp(int(rows[0][0]), unit="ms", tz="UTC").date()), oi_hist_n=len(rows))
        lq = jl(snap, f"okx_liq_{s}.json")
        if lq and lq.get("data"):
            det = [x for blk in lq["data"] for x in blk.get("details", [])]
            if det:
                usd = lambda x: float(x["sz"]) * ct * float(x["bkPx"])
                ts = [int(x["ts"]) for x in det]; longs = sum(usd(x) for x in det if x["posSide"] == "long"); shorts = sum(usd(x) for x in det if x["posSide"] == "short")
                out["okx"][s].update(liq_n=len(det), liq_span_min=float((max(ts) - min(ts)) / 60000), liq_first=str(pd.Timestamp(min(ts), unit="ms", tz="UTC")), liq_last=str(pd.Timestamp(max(ts), unit="ms", tz="UTC")), liq_long_usd=longs, liq_short_usd=shorts, liq_contract_value_ASSUMED=ct)
    return out

def read_fred(snap, sid):
    p = snap / f"f_{sid}.csv"
    if not p.exists(): return None
    d = pd.read_csv(p); d.columns = ["date", "v"]; d["v"] = pd.to_numeric(d["v"], errors="coerce"); d = d.dropna(); d["date"] = pd.to_datetime(d["date"]); return d.set_index("date")["v"]

def macro(snap, btc_daily):
    out = {}; S = {k: read_fred(snap, k) for k in ("SP500", "VIXCLS", "DGS10", "DTWEXBGS")}
    for k, s in S.items():
        if s is None or not len(s): out[k] = None; continue
        out[k] = dict(last_date=str(s.index[-1].date()), last=float(s.iloc[-1]), chg_20obs=float(s.iloc[-1] - s.iloc[-21]) if len(s) > 21 else None, pct_20obs=float(s.iloc[-1] / s.iloc[-21] - 1) if len(s) > 21 else None,
                      high_252=float(s.tail(252).max()), from_high=float(s.iloc[-1] / s.tail(252).max() - 1), pctile_1y=float((s.tail(252) < s.iloc[-1]).mean() * 100), above_50obs_mean=bool(s.iloc[-1] > s.tail(50).mean()))
    sp = S["SP500"]
    if sp is not None:
        lr = np.log(sp).diff().dropna(); b = np.log(btc_daily).diff(); b.index = b.index.tz_localize(None).normalize()
        j = pd.concat([lr.rename("spx"), b.rename("btc")], axis=1, join="inner").dropna().tail(30)
        out["corr_btc_spx_30obs"] = dict(n=int(len(j)), corr=float(j.corr().iloc[0, 1]), window_end=str(j.index[-1].date()), caveat="SPX close 21:00 UTC vs crypto UTC-day close: asynchronous; US trading days only")
    return out

def onchain_sent(snap):
    out = {}
    f = jl(snap, "fng.json")
    if f:
        v = [int(x["value"]) for x in f["data"]]
        out["fear_greed"] = dict(latest=v[0], latest_class=f["data"][0]["value_classification"], latest_ts=str(pd.Timestamp(int(f["data"][0]["timestamp"]), unit="s", tz="UTC")), min_60d=min(v), max_60d=max(v), mean_30d=float(np.mean(v[:30])), n=len(v), pct_days_le20_60d=float(np.mean(np.array(v) <= 20)))
    g = jl(snap, "coingecko_global.json")
    if g:
        d = g["data"]; out["global"] = dict(btc_dominance=float(d["market_cap_percentage"]["btc"]), eth_dominance=float(d["market_cap_percentage"]["eth"]), mcap_chg_24h_pct=float(d["market_cap_change_percentage_24h_usd"]), total_mcap_usd=float(d["total_market_cap"]["usd"]), updated=str(pd.Timestamp(d["updated_at"], unit="s", tz="UTC")))
    c = jl(snap, "coinmetrics_btc.json")
    if c and c.get("data"):
        rows = c["data"]; last = rows[-1]; mv = [float(r["CapMVRVCur"]) for r in rows if r.get("CapMVRVCur")]
        out["coinmetrics"] = dict(last_time=last["time"], mvrv=float(last["CapMVRVCur"]), mvrv_pctile_in_window=float((np.array(mv) < float(last["CapMVRVCur"])).mean() * 100), mvrv_window_n=len(mv), mvrv_status=last.get("CapMVRVCur-status"),
                                  flow_in_ex_usd=float(last["FlowInExUSD"]) if last.get("FlowInExUSD") else None, flow_out_ex_usd=float(last["FlowOutExUSD"]) if last.get("FlowOutExUSD") else None, flow_status=last.get("FlowInExUSD-status"),
                                  netflow_7d_usd=float(sum(float(r["FlowInExUSD"]) - float(r["FlowOutExUSD"]) for r in rows[-7:] if r.get("FlowInExUSD") and r.get("FlowOutExUSD"))), active_addr=float(last["AdrActCnt"]), active_addr_pctile_window=float((np.array([float(r["AdrActCnt"]) for r in rows if r.get("AdrActCnt")]) < float(last["AdrActCnt"])).mean() * 100))
    b = jl(snap, "blockchain_stats.json"); m = jl(snap, "mempool_hashrate.json"); dd = jl(snap, "mempool_diff.json")
    if b: out["blockchain_info"] = dict(hash_rate_GHs=float(b["hash_rate"]), market_price_usd=float(b["market_price_usd"]), n_tx_24h=b.get("n_tx"), ts=str(pd.Timestamp(int(b["timestamp"]), unit="ms", tz="UTC")))
    if m and m.get("hashrates"):
        hr = m["hashrates"]; out["mempool"] = dict(current_hashrate_Hs=float(m["currentHashrate"]), hash_90d_ago_Hs=float(hr[0]["avgHashrate"]), chg_90d=float(m["currentHashrate"] / hr[0]["avgHashrate"] - 1), difficulty_next_chg_pct=float(dd["difficultyChange"]) if dd else None)
    return out

def run():
    snap = latest_snapshot(); man = jl(snap, "MANIFEST.json")
    syms, n, ovl = extended_grid(snap)
    now = pd.Timestamp(man["stamp"], tz="UTC") if False else pd.Timestamp(datetime.strptime(man["stamp"], "%Y%m%dT%H%M%SZ"), tz="UTC")
    res = dict(snapshot=man["stamp"], fetched_utc=str(now), overlap_check=ovl, thresholds=TH, threshold_status=TH_STATUS)
    assets, daily = {}, {}
    for s in SYMS:
        d = daily_frame(syms[s], n); d = d[d.index < now.normalize()]            # completed UTC days only
        d = d[d.nbar >= 1]; dc = d.copy(); dc.loc[dc.nbar < 24, "c"] = np.nan
        ff = d.copy(); ff["c"] = ff["c"].ffill(); x = indicators(ff.dropna(subset=["o", "h", "l"]).copy()); daily[s] = (ff, x)
        assets[s] = classify_asset(x, None); assets[s]["days_incomplete_last30"] = int((d.tail(30).nbar < 24).sum()); assets[s]["last_complete_day_bars"] = int(d.nbar.iloc[-1])
        # intraday (partial day 2026-11-18) for volume
        t24 = jl(snap, f"binance_24h_{s}.json")
        if t24: assets[s]["rolling24h_vratio"] = float(float(t24["quoteVolume"]) / daily[s][1].qmed30.iloc[-1])
    for s in SYMS:
        a = assets[s]; g_ok = all(res_g for res_g in [True]); lab = lambda v: "Strong" if v >= TH["liq_strong"] else "Weak" if v < TH["liq_weak"] else "Average"
        l1, l2 = lab(a["vratio"]), lab(a.get("rolling24h_vratio", a["vratio"])); a["liquidity_by_completed_day"] = l1; a["liquidity_by_rolling24h"] = l2
        a["liquidity"] = l1 if l1 == l2 else "Average"; a["liquidity_conflict"] = l1 != l2
    # relative strength vs BTC and basket
    ret = {s: {k: assets[s][k] for k in ("ret7", "ret30", "ret90")} for s in SYMS}
    alts = [s for s in SYMS if s != "BTC"]
    for s in SYMS:
        for k in ("ret7", "ret30", "ret90"):
            assets[s][f"rs_{k}_vs_BTC"] = float(ret[s][k] - ret["BTC"][k]) if s != "BTC" else 0.0
        ratio = (daily[s][0].c / daily["BTC"][0].c).dropna() if s != "BTC" else None
        if ratio is not None and len(ratio) > 60: e20, e50 = ema(ratio, 20), ema(ratio, 50); assets[s]["ratio_ema20_gt_ema50"] = bool(e20.iloc[-1] > e50.iloc[-1])
    for k in ("ret7", "ret30", "ret90"): assets["BTC"][f"rs_{k}_vs_altbasket"] = float(ret["BTC"][k] - np.mean([ret[s][k] for s in alts]))
    breadth = dict(share_bullish=float(np.mean([assets[s]["direction"] == "Bullish" for s in SYMS])), share_bearish=float(np.mean([assets[s]["direction"] == "Bearish" for s in SYMS])),
                   share_above_ema200=float(np.mean([assets[s]["c_vs_ema200"] > 0 for s in SYMS])), share_trending=float(np.mean([assets[s]["structure"] == "Trending" for s in SYMS])),
                   share_ret30_pos=float(np.mean([assets[s]["ret30"] > 0 for s in SYMS])))
    # 30d mean pairwise correlation of daily log returns (concentration rule T9)
    R = pd.concat({s: np.log(daily[s][0].c).diff() for s in SYMS}, axis=1).tail(30); cm = R.corr().to_numpy(); breadth["mean_pairwise_corr_30d"] = float(cm[np.triu_indices(len(SYMS), 1)].mean())
    cv = cross_venue(snap, syms, n); der = derivatives(snap); mac = macro(snap, daily["BTC"][0].c); ocs = onchain_sent(snap)
    res.update(assets=assets, breadth=breadth, cross_venue=cv, derivatives=der, macro=mac, onchain_sentiment=ocs)
    # data quality
    stale = {s: cv[s]["age_hours_at_fetch"] for s in SYMS}; res["data_quality"] = dict(max_age_hours=max(stale.values()), stale_assets=[s for s, a in stale.items() if a > TH["stale_hours"]],
        max_abs_basis_bp=max(abs(cv[s].get("basis_bp_binance_vs_coinbase", 0)) for s in SYMS), n_hours_grid=n, missing_inputs=["FRED combined request timed out (single-series requests used)", "no verified on-chain source beyond Coinmetrics community (provisional flash data) and mempool/blockchain.info hashrate", "no options/IV data", "no historical liquidation feed (OKX returns only the latest ~100 events)", "no spot-ETF flow data", "Binance perp funding/OI blocked (HTTP 451); Bybit blocked (403)"])
    res["gates"] = gate_states(syms)
    trig = {}; P = E.DEFAULTS["CRY-MOM-101"]
    for s in SYMS:
        a = E.prep(syms[s], "CRY-MOM-101", P); j = int(np.where(a["valid"])[0].max()); x = daily[s][1].iloc[-1]; c = float(syms[s].cff[-1] if False else a["c"][j])
        trig[s] = dict(close_4h=c, sma300_4h=float(a["sma"][j]), pct_to_sma300=float(a["sma"][j] / c - 1), pct_to_ema20=float(x.ema20 / x.c - 1), pct_to_ema50=float(x.ema50 / x.c - 1), pct_to_ema200=float(x.ema200 / x.c - 1),
                       daily_atr_pct=float(x.atr_pct), pct_to_sma300_in_daily_atr=float((a["sma"][j] / c - 1) / x.atr_pct), adx=float(x.adx), adx_to_trend_floor=float(TH["adx_trend"] - x.adx), M=float(a["M"][j]))
    res["triggers_distance"] = trig
    rv = daily["BTC"][1].rv30.dropna(); res["btc_rv30_cuts"] = {f"p{q}": float(np.percentile(rv.iloc[:-1], q)) for q in (25, 50, 75, 95)}; res["btc_rv30_hist_n"] = int(len(rv) - 1); res["btc_rv30_hist_start"] = str(rv.index[0].date())
    adxs = daily["BTC"][1].adx.dropna(); res["btc_adx_hist"] = dict(share_ge25=float((adxs >= 25).mean()), share_lt20=float((adxs < 20).mean()), n=int(len(adxs)))
    hr, dc = hist_by_regime(); res["hist_by_regime"] = hr; res["hist_regime_day_counts"] = dc
    res["evidence_hashes"] = {m["name"]: m["sha256"] for m in man["items"] if m["ok"]}
    for k in ("SP500", "VIXCLS", "DGS10", "DTWEXBGS"): res["evidence_hashes"][f"f_{k}.csv"] = sha(snap / f"f_{k}.csv")
    for s in SYMS: pass
    # save BTC daily series for chart
    ff, x = daily["BTC"]; x.tail(420).to_csv(ROOT / "docs/strategy-specs/stage04/btc_daily_indicators.csv", float_format="%.6g")
    (ROOT / "docs/strategy-specs/stage04/regime_results.json").write_text(json.dumps(res, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print("done", man["stamp"], "BTC", assets["BTC"]["direction"], assets["BTC"]["structure"], assets["BTC"]["volatility"], assets["BTC"]["momentum"])

if __name__ == "__main__": run()
