"""Stage 02 backtest engine for CRY-MOM-101 / CRY-REV-102 / CRY-VEX-103 (handoff v2, rules 0.1.0).
Research only: no orders, no credentials. Spot, long-only. Bars: UTC, timestamp = open time.
Design: (1) indicators/signals vectorised on completed bars; (2) each candidate trade's exit PATH depends only on the
market, so it is computed once; (3) a sequential portfolio layer accepts/sizes candidates (E frozen, caps, slots, cash).
"""
from __future__ import annotations
import math, heapq
from dataclasses import dataclass, field
import numpy as np, pandas as pd

T0_MS = int(pd.Timestamp("2021-05-01", tz="UTC").timestamp() * 1000)
HOUR = 3600_000
LOT = 1e-6          # ASSUMED lot step (venue filters UNAVAILABLE)
MIN_NOTIONAL = 10.0  # ASSUMED
WARM = 1000
SYMS = ["BTC", "ETH", "SOL", "XRP", "ADA", "LINK", "AVAX", "DOGE", "LTC"]
STRAT_ORDER = {"CRY-MOM-101": 0, "CRY-REV-102": 1, "CRY-VEX-103": 2}

# ---------------------------------------------------------------- indicators
def seg_pos(valid):
    """Consecutive valid bars up to and including i (0 if invalid)."""
    out = np.zeros(len(valid), dtype=np.int64); run = 0
    for i, v in enumerate(valid):
        run = run + 1 if v else 0; out[i] = run
    return out

def wilder_atr(h, l, c, valid, n):
    out = np.full(len(c), np.nan); a = np.nan; cnt = 0; acc = 0.0
    for i in range(len(c)):
        if not valid[i]: a = np.nan; cnt = 0; acc = 0.0; continue
        if i == 0 or not valid[i - 1]: cnt = 0; acc = 0.0; a = np.nan; continue
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        if cnt < n:
            cnt += 1; acc += tr
            if cnt == n: a = acc / n; out[i] = a
        else:
            a = ((n - 1) * a + tr) / n; out[i] = a
    return out

def wilder_rsi(c, valid, n):
    out = np.full(len(c), np.nan); ag = al = np.nan; cnt = 0; sg = sl = 0.0
    for i in range(len(c)):
        if not valid[i] or i == 0 or not valid[i - 1]:
            ag = al = np.nan; cnt = 0; sg = sl = 0.0; continue
        ch = c[i] - c[i - 1]; g = max(ch, 0.0); ls = max(-ch, 0.0)
        if cnt < n:
            cnt += 1; sg += g; sl += ls
            if cnt == n: ag, al = sg / n, sl / n
            else: continue
        else:
            ag = ((n - 1) * ag + g) / n; al = ((n - 1) * al + ls) / n
        out[i] = 50.0 if (ag == 0 and al == 0) else (100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out

def S(a): return pd.Series(a)

# ---------------------------------------------------------------- data container
@dataclass
class Sym:
    name: str
    o: np.ndarray; h: np.ndarray; l: np.ndarray; c: np.ndarray; q: np.ndarray; v: np.ndarray; valid: np.ndarray   # 1H grid
    cff: np.ndarray                       # forward-filled close (marking only)
    o4: np.ndarray = None; h4: np.ndarray = None; l4: np.ndarray = None; c4: np.ndarray = None; valid4: np.ndarray = None
    L1: np.ndarray = None; L2L3: np.ndarray = None; qmed168: np.ndarray = None
    ind: dict = field(default_factory=dict)

def build_grid(frames, n_hours):
    """frames: {sym: DataFrame(t[ms], o,h,l,c,v,q)} -> {sym: Sym} on the master 1H grid."""
    out = {}
    for s, d in frames.items():
        idx = ((d["t"].to_numpy() - T0_MS) // HOUR).astype(int)
        arr = {k: np.full(n_hours, np.nan) for k in "ohlcvq"}
        for k in arr: arr[k][idx] = d[k].to_numpy()
        valid = np.zeros(n_hours, bool); valid[idx] = True
        cff = pd.Series(arr["c"]).ffill().to_numpy()
        sy = Sym(s, arr["o"], arr["h"], arr["l"], arr["c"], arr["q"], arr["v"], valid, cff)
        nb = n_hours // 4
        v4 = valid[: nb * 4].reshape(nb, 4).all(axis=1)
        def agg(a, f): return f(a[: nb * 4].reshape(nb, 4), axis=1)
        sy.o4 = np.where(v4, sy.o[: nb * 4].reshape(nb, 4)[:, 0], np.nan)
        sy.c4 = np.where(v4, sy.c[: nb * 4].reshape(nb, 4)[:, 3], np.nan)
        sy.h4 = np.where(v4, agg(np.nan_to_num(sy.h, nan=-np.inf), np.max), np.nan)
        sy.l4 = np.where(v4, agg(np.nan_to_num(sy.l, nan=np.inf), np.min), np.nan)
        sy.valid4 = v4
        # liquidity gates (indexed by 1H bar i = last completed bar at signal time)
        q = S(sy.q); dq = np.nansum(sy.q[: (n_hours // 24) * 24].reshape(-1, 24), axis=1)
        roll30 = S(dq).rolling(30, min_periods=30).median().to_numpy()
        ii = np.arange(n_hours); dd = (ii + 1) // 24 - 1
        sy.L1 = np.where(dd >= 0, roll30[np.clip(dd, 0, None)] >= 20e6, False)
        s24 = q.rolling(24, min_periods=24).sum().to_numpy()
        mn24 = S(sy.v).rolling(24, min_periods=24).min().to_numpy()
        sy.L2L3 = (s24 >= 10e6) & (mn24 > 0)
        sy.qmed168 = q.rolling(168, min_periods=168).median().to_numpy()
        out[s] = sy
    return out

# ---------------------------------------------------------------- strategy definitions
DEFAULTS = {
    "CRY-MOM-101": dict(tf=4, lookback=180, thr=1.25, ext=1.30, stop_k=3.0, trail_k=3.5, time_bars=180, placebo=False, warm=WARM),
    "CRY-REV-102": dict(tf=4, rsi_thr=8.0, drop_k=2.0, stop_k=2.0, trail_k=1.5, arm_k=1.0, time_bars=12, rsi_exit=65.0, trend=True, ibs_min=0.20, warm=WARM),
    "CRY-VEX-103": dict(tf=1, donch=48, tr_k=1.8, vol_k=2.0, ibs_min=0.75, stop_k=2.0, trail_k=2.5, time_bars=48, fail_bars=6, warm=WARM),
}

def ready(valid, warm): return seg_pos(valid) > warm

def prep(sy: Sym, sid: str, P: dict):
    """Compute indicator arrays for one symbol/strategy on its tf grid. Returns dict."""
    cache = sy.ind; key = (sid, tuple(sorted((k, v) for k, v in P.items())))
    if key in cache: return cache[key]
    r = {}
    if sid == "CRY-MOM-101":
        c, h, l, v = sy.c4, sy.h4, sy.l4, sy.valid4
        n = P["lookback"]; cs = S(c)
        ret = np.log(cs / cs.shift(1)); sig = ret.rolling(n, min_periods=n).std(ddof=1)
        M = np.log(cs / cs.shift(n)) / (sig * math.sqrt(n))
        sma = cs.rolling(300, min_periods=300).mean()
        atr = wilder_atr(h, l, c, v, 20)
        rd = ready(v, P["warm"])
        r.update(M=M.to_numpy(), sma=sma.to_numpy(), sma30=sma.shift(30).to_numpy(), atr=atr, ready=rd, c=c, o=sy.o4, h=h, l=l, valid=v)
    elif sid == "CRY-REV-102":
        c, h, l, v = sy.c4, sy.h4, sy.l4, sy.valid4; cs = S(c)
        r.update(rsi=wilder_rsi(c, v, 3), atr=wilder_atr(h, l, c, v, 14), sma20=cs.rolling(20, min_periods=20).mean().to_numpy(),
                 sma=cs.rolling(300, min_periods=300).mean().to_numpy(), drop3=(cs.shift(3) - cs).to_numpy(),
                 ibs=np.where(h > l, (c - l) / np.where(h > l, h - l, 1), np.nan), ready=ready(v, P["warm"]), c=c, o=sy.o4, h=h, l=l, valid=v)
    else:
        c, h, l, v, q = sy.c, sy.h, sy.l, sy.valid, sy.q
        cs = S(c); hs = S(h)
        atr = wilder_atr(h, l, c, v, 24)
        tr = np.full(len(c), np.nan); tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
        dh = hs.shift(1).rolling(P["donch"], min_periods=P["donch"]).max().to_numpy()
        qm = S(q).shift(1).rolling(168, min_periods=168).median().to_numpy()
        c4s = S(sy.c4); sma50 = c4s.rolling(50, min_periods=50).mean().to_numpy()
        ctx4 = (sy.c4 > sma50)  # NaN compares False
        i = np.arange(len(c)); j = (i + 1) // 4 - 1
        ctx = np.where(j >= 0, ctx4[np.clip(j, 0, None)], False)
        r.update(atr=atr, atr_prev=np.concatenate([[np.nan], atr[:-1]]), tr=tr, dh=dh, qmed_x=qm, ctx=ctx,
                 ibs=np.where(h > l, (c - l) / np.where(h > l, h - l, 1), np.nan), ready=ready(v, P["warm"]), c=c, o=sy.o, h=h, l=l, q=q, valid=v)
    cache[key] = r
    return r

def liq_ok(sy, tf):
    """Liquidity gate L1-L3 evaluated at signal bar close; returns array on tf grid."""
    n1 = len(sy.valid)
    if tf == 1: return sy.L1 & sy.L2L3
    last = np.arange(n1 // 4) * 4 + 3
    return sy.L1[last] & sy.L2L3[last]

def raw_signal(sid, sy, P, btc=None, mode="signal"):
    """Boolean entry signal at each completed tf bar (before gap guard / cost gate / sizing).
    mode='pool': omit the strategy-specific trigger conditions (random-entry null pool)."""
    a = prep(sy, sid, P); rd = a["ready"] & liq_ok(sy, P["tf"])
    if sid == "CRY-MOM-101":
        base = rd & (a["c"] > a["sma"]) & (a["sma"] > a["sma30"]) & (a["c"] / a["sma"] <= P["ext"])
        b = prep(btc, sid, P); base &= b["ready"] & (b["c"] > b["sma"])
        if mode == "pool": return base
        trig = (a["M"] <= 0) if P["placebo"] else (a["M"] >= P["thr"])
        return base & trig
    if sid == "CRY-REV-102":
        base = rd.copy()
        if P["trend"]: base &= (a["c"] > a["sma"])
        if mode == "pool": return base
        return base & (a["rsi"] <= P["rsi_thr"]) & (a["drop3"] >= P["drop_k"] * a["atr"]) & (a["ibs"] >= P["ibs_min"])
    base = rd & a["ctx"] & (a["atr_prev"] > 0)
    if mode == "pool": return base
    sig = base & (a["c"] > a["dh"]) & (a["tr"] >= P["tr_k"] * a["atr_prev"]) & (a["ibs"] >= P["ibs_min"])
    if P["vol_k"] is not None: sig &= (a["q"] >= P["vol_k"] * a["qmed_x"])
    return sig

# ---------------------------------------------------------------- candidate construction + exit path
def exit_path(sid, P, a, b0, S0, tgt, atr_e, dh_sig, o1, end_b=None):
    """Market-only exit path. Entry at open of tf bar b0 (stop live from b0). Returns (exit_bar, kind, raw_price)
    kind in stop|target|open ; end_b: last allowed bar (exclusive) else None -> returns ('open'/'END') handled by caller."""
    o, h, l, c, valid = a["o"], a["h"], a["l"], a["c"], a["valid"]
    atr = a["atr"]; stop = S0; hc = -np.inf; armed = False; held = 0; pending = False
    n = len(c) if end_b is None else min(end_b, len(c))
    for b in range(b0, n):
        if not valid[b]: continue
        if pending: return b, "open", o[b]
        if l[b] <= stop: return b, "stop", min(stop, o[b])
        if tgt is not None and h[b] > tgt: return b, "target", tgt
        held += 1
        if c[b] > hc: hc = c[b]
        if not np.isnan(atr[b]):
            if sid == "CRY-REV-102":
                if not armed and c[b] >= o1 + P["arm_k"] * atr_e: armed = True
                if armed: stop = max(stop, o1, hc - P["trail_k"] * atr[b])
            else:
                stop = max(stop, hc - P["trail_k"] * atr[b])
        if held >= P["time_bars"]: pending = True
        elif sid == "CRY-MOM-101":
            if a["M"][b] < 0 or c[b] < a["sma"][b]: pending = True
        elif sid == "CRY-REV-102":
            if a["rsi"][b] >= P["rsi_exit"]: pending = True
        else:
            if held <= P["fail_bars"] and c[b] < dh_sig: pending = True
    return None, "END", None

def candidates(sid, sy, P, btc, f, s, mode="signal", end_b=None, stats=None):
    """List of candidate trades for one symbol (unsized). Each: dict with signal bar j, entry bar b0, S0, path result."""
    a = prep(sy, sid, P); sg = raw_signal(sid, sy, P, btc, mode); tf = P["tf"]; out = []
    o, c = a["o"], a["c"]; atr = a["atr"] if sid != "CRY-VEX-103" else a["atr_prev"]
    idx = np.where(sg)[0]
    st = stats if stats is not None else {}
    def bump(k): st[k] = st.get(k, 0) + 1
    for j in idx:
        bump("raw_signals")
        b0 = j + 1
        if b0 >= len(o) or not a["valid"][b0] or np.isnan(o[b0]): bump("no_entry_bar"); continue
        ref = atr[j]
        if not (ref > 0): bump("bad_atr"); continue
        O1 = o[b0]
        if abs(O1 - c[j]) > 0.5 * ref: bump("gap_guard"); continue   # gap guard
        S0 = O1 - P["stop_k"] * ref
        if S0 <= 0: bump("stop_nonpositive"); continue
        Pf = O1 * (1 + s)
        if 2 * (f + s) * Pf > 0.35 * (Pf - S0): bump("cost_gate"); continue   # cost-feasibility gate
        tgt = None
        if sid == "CRY-REV-102":
            tgt = a["sma20"][j]
            if not (tgt > O1) or (tgt - O1) / (O1 - S0) < 1.0: bump("target_structure"); continue
        dh_sig = a["dh"][j] if sid == "CRY-VEX-103" else None
        ex = exit_path(sid, P, a, b0, S0, tgt, ref, dh_sig, O1, end_b)
        Sx = S0 * (1 - s); d = (Pf - Sx) + f * (Pf + Sx)
        if d <= 0: bump("bad_d"); continue
        bump("candidates")
        out.append(dict(sid=sid, sym=sy.name, tf=tf, j=int(j), b0=int(b0), O1=O1, S0=S0, Pf=Pf, d=d, ref=ref,
                        exit_b=ex[0], kind=ex[1], raw=ex[2], tgt=tgt, t_entry=int(b0 * tf)))
    return out

def finalize(cd, f, s):
    """Attach per-unit exit economics. Exit time t_exit (hour idx), occupancy end (hour idx float)."""
    tf = cd["tf"]
    if cd["kind"] == "END": return cd
    xb = cd["exit_b"]; cd["t_exit"] = xb * tf
    cd["occ_end"] = cd["t_exit"] + 0.5 if cd["kind"] == "open" else cd["t_exit"] + tf   # symbol/slot freed
    cd["rel_cash"] = cd["t_exit"] if cd["kind"] == "open" else cd["t_exit"] + tf
    px = cd["raw"] * (1 - s); cd["xfill"] = px
    cd["pnl_u"] = px * (1 - f) - cd["Pf"] * (1 + f)
    cd["R_u"] = cd["pnl_u"] / cd["d"]
    return cd

# ---------------------------------------------------------------- portfolio layer
def floor_lot(x): return math.floor(x / LOT + 1e-12) * LOT

def simulate(cands, syms, ws, we, f, s, capital=10_000.0, max_pos=3, per_trade=0.01, total=0.03, ncap=0.33, part=0.01, order_key=None):
    """Sequential acceptance/sizing of finalized candidates whose entry hour is in [ws, we). Hours are master-grid indices.
    Returns dict(trades, skips, hourly equity, ...)."""
    el = [c for c in cands if ws <= c["t_entry"] < we]
    el.sort(key=lambda c: (c["t_entry"], STRAT_ORDER[c["sid"]], SYMS.index(c["sym"])))
    cash = capital; openp = []; done = []; skips = {}
    occ = {}; last_exit_b = {}
    def sk(k): skips[k] = skips.get(k, 0) + 1
    Efroz = None; Tfroz = None
    for cd in el:
        T = cd["t_entry"]
        for p in openp:   # release cash / slots / risk at release time
            if not p["rel"] and p["rel_cash"] <= T: p["rel"] = True; cash += p["proceeds"]
        live = [p for p in openp if not p["rel"]]
        if T != Tfroz:
            Efroz = cash + sum(p["q"] * syms[p["cd"]["sym"]].cff[T - 1] for p in live)
            Tfroz = T
        E = Efroz
        key = (cd["sid"], cd["sym"])
        if occ.get(cd["sym"], -1) > T: sk("symbol_occupied"); continue
        if key in last_exit_b and cd["j"] < last_exit_b[key] + 1: sk("cooldown"); continue
        if len(live) >= max_pos: sk("max_positions"); continue
        G = sum(p["risk"] for p in live)
        B = max(0.0, min(per_trade * E, total * E - G))
        if B <= 0: sk("risk_budget_zero"); continue
        sy = syms[cd["sym"]]; qm = sy.qmed168[T - 1]
        if not np.isfinite(qm): sk("no_qmed"); continue
        Pf = cd["Pf"]
        q = floor_lot(min(B / cd["d"], ncap * E / Pf, cash / (Pf * (1 + f)), part * qm / Pf))
        if q <= 0: sk("qty_zero"); continue
        if q * Pf < MIN_NOTIONAL: sk("below_min_notional"); continue
        # exit economics (forced close at window end)
        cdx = dict(cd)
        if cd["kind"] == "END" or cd["t_exit"] >= we:
            cdx["kind"] = "forced"; cdx["t_exit"] = we - 1; cdx["occ_end"] = we; cdx["rel_cash"] = we
            cdx["xfill"] = sy.cff[we - 1] * (1 - s); cdx["exit_b"] = None
        pnl_u = cdx["xfill"] * (1 - f) - Pf * (1 + f)
        cash -= q * Pf * (1 + f)
        p = dict(cd=cdx, q=q, risk=q * cd["d"], proceeds=q * cdx["xfill"] * (1 - f), rel=False, rel_cash=cdx["rel_cash"], 
                 pnl=q * pnl_u, E_entry=E, buy_notional=q * Pf, sell_notional=q * cdx["xfill"], fees=f * q * (Pf + cdx["xfill"]))
        openp.append(p); done.append(p)
        occ[cd["sym"]] = cdx["occ_end"]
        last_exit_b[key] = cdx["exit_b"] if cdx["exit_b"] is not None else 10**9
    # settle remaining releases (for cash at end handled in equity construction)
    # hourly equity
    H = we - ws
    cashd = np.zeros(H + 1); posv = np.zeros(H)
    cashd[0] = capital
    for p in done:
        cd = p["cd"]; te = cd["t_entry"] - ws; tx = cd["t_exit"] - ws
        cashd[te] -= p["q"] * cd["Pf"] * (1 + f)
        cashd[min(tx, H - 1)] += p["proceeds"]    # proceeds credited from the close of the exit hour onward (approximation)
        hi = min(tx, H)
        if hi > te: posv[te:hi] += p["q"] * syms[cd["sym"]].cff[cd["t_entry"]: cd["t_entry"] + (hi - te)]
    eq = np.cumsum(cashd[:H]) + posv
    trades = []
    for p in done:
        cd = p["cd"]
        trades.append(dict(strategy=cd["sid"], symbol=cd["sym"], entry_hour=cd["t_entry"], exit_hour=cd["t_exit"], kind=cd["kind"], tf=cd["tf"],
            qty=p["q"], entry_fill=cd["Pf"], exit_fill=cd["xfill"], S0=cd["S0"], O1=cd["O1"], d_unit=cd["d"], reserved_risk=p["risk"], pnl=p["pnl"],
            R=p["pnl"] / p["risk"], fees=p["fees"], buy_notional=p["buy_notional"], sell_notional=p["sell_notional"],
            bars=(None if cd["exit_b"] is None else cd["exit_b"] - cd["b0"] + 1), E_entry=p["E_entry"], forced=cd["kind"] == "forced"))
    return dict(trades=trades, skips=skips, equity=eq, posv=posv, ws=ws, we=we)
