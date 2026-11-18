"""Stage 06 candidate-change harness. Research only: no orders, no credentials.

Every candidate is the Stage 02 baseline rule (engine.DEFAULTS, rules_version 0.1.0) plus ONE predeclared change, expressed as
(a) engine parameter overrides P and/or (b) extra causal entry masks / an exit-confirmation counter `x`.
The Stage 02 engine is NOT modified: its module-level raw_signal / exit_path are wrapped inside a context manager and restored.
With x == {} and P == DEFAULTS the wrapped path returns the engine's own results (asserted in the runner and in tests).

CAUSALITY: every mask at tf-bar j uses information completed at the close of bar j (= hour (j+1)*tf) only.
Daily external series (regime tags, factor scores) are read at the last COMPLETED UTC day: dd = ((j+1)*tf)//24 - 1.
Missing external information (NaN/NA) never blocks an entry: the baseline rule applies (documented, no imputation)."""
from __future__ import annotations
import contextlib, math
import numpy as np, pandas as pd
from stage02 import engine as E, analysis as A

DAY0 = pd.Timestamp("2021-05-01", tz="UTC")
MOM, REV, VEX = "CRY-MOM-101", "CRY-REV-102", "CRY-VEX-103"


class Env:
    """Daily external arrays aligned to engine day index (day 0 = 2021-05-01 UTC). regime[name] -> bool allowed array (NaN-free);
    factor[(weights, asset)] -> float array of composite score (NaN where unavailable)."""
    def __init__(self, regime=None, factor=None, ndays=2100):
        self.regime = regime or {}; self.factor = factor or {}; self.ndays = ndays


def _S(a): return pd.Series(a)


def _shift_bool(ok, k):
    out = np.zeros(len(ok), bool)
    if k == 0: return ok.copy()
    out[k:] = ok[:-k]; return out


def _day_index(n_tf, tf):
    return ((np.arange(n_tf) + 1) * tf) // 24 - 1


def _daily_roll30_median_q(sy):
    n = len(sy.q); dq = np.nansum(sy.q[: (n // 24) * 24].reshape(-1, 24), axis=1)
    return _S(dq).rolling(30, min_periods=30).median().to_numpy()


def build_mask(sid, sy, P, x, env: Env):
    """Boolean mask on the strategy tf grid (True = entry allowed) or None when x adds no entry restriction for this symbol."""
    if not x: return None
    tf = P["tf"]; a = E.prep(sy, sid, P); n = len(a["c"]); m = np.ones(n, bool); used = False
    dd = _day_index(n, tf)
    if sid == MOM:
        K = x.get("confirm", 1)
        if K > 1:
            ok = np.nan_to_num(a["M"], nan=-1e9) >= P["thr"]
            for i in range(1, K): m &= _shift_bool(ok, i)
            used = True
        if x.get("rvr") is not None:
            r = np.log(_S(sy.c4) / _S(sy.c4).shift(1))
            ratio = (r.rolling(42, min_periods=42).std(ddof=1) / r.rolling(180, min_periods=180).std(ddof=1)).to_numpy()
            m &= np.nan_to_num(ratio, nan=np.inf) <= x["rvr"]; used = True
        if x.get("l1") is not None:
            roll = _daily_roll30_median_q(sy); i1 = np.arange(n) * 4 + 3; d1 = (i1 + 1) // 24 - 1
            val = np.where(d1 >= 0, roll[np.clip(d1, 0, len(roll) - 1)], np.nan)
            m &= np.nan_to_num(val, nan=-1.0) >= x["l1"]; used = True
    elif sid == VEX:
        if x.get("comp") is not None:
            ap = _S(a["atr_prev"]); med = ap.rolling(720, min_periods=720).median().to_numpy()
            comp = a["atr_prev"] / med
            m &= np.nan_to_num(comp, nan=np.inf) <= x["comp"]; used = True
        if x.get("ctxp") is not None:
            c4s = _S(sy.c4); sma = c4s.rolling(x["ctxp"], min_periods=x["ctxp"]).mean().to_numpy()
            ctx4 = sy.c4 > sma; i = np.arange(n); j = (i + 1) // 4 - 1
            m &= np.where(j >= 0, ctx4[np.clip(j, 0, None)], False); used = True
        if x.get("weekend"):   # entry bar i+1 must open Mon-Fri UTC (2021-05-01 is a Saturday: weekday 5)
            k = (np.arange(n) + 1) // 24; m &= ((5 + k) % 7) < 5; used = True
    if x.get("regime") is not None:
        allowed = env.regime[x["regime"]]
        m &= np.where(dd >= 0, allowed[np.clip(dd, 0, len(allowed) - 1)], True); used = True
    if x.get("factor") is not None:
        wname, tau = x["factor"]
        key = (wname, sy.name)
        if key not in env.factor: raise KeyError(f"factor score unavailable for {sy.name}: overlay not testable on this asset")
        S = env.factor[key]; sv = np.where(dd >= 0, S[np.clip(dd, 0, len(S) - 1)], np.nan)
        m &= np.where(np.isfinite(sv), sv >= tau, True); used = True
    return m if used else None


def exit_path_mom_n(P, a, b0, S0, atr_e, o1, end_b, n_exit):
    """Copy of engine.exit_path (MOM branch) with the signal exit requiring n_exit consecutive completed bars of (M<0 or C<SMA300)."""
    o, h, l, c, valid = a["o"], a["h"], a["l"], a["c"], a["valid"]
    atr = a["atr"]; stop = S0; hc = -np.inf; held = 0; pending = False; cnt = 0
    n = len(c) if end_b is None else min(end_b, len(c))
    for b in range(b0, n):
        if not valid[b]: continue
        if pending: return b, "open", o[b]
        if l[b] <= stop: return b, "stop", min(stop, o[b])
        held += 1
        if c[b] > hc: hc = c[b]
        if not np.isnan(atr[b]): stop = max(stop, hc - P["trail_k"] * atr[b])
        if held >= P["time_bars"]: pending = True
        else:
            cnt = cnt + 1 if (a["M"][b] < 0 or c[b] < a["sma"][b]) else 0
            if cnt >= n_exit: pending = True
    return None, "END", None


@contextlib.contextmanager
def patched(x, env):
    orig_rs, orig_ep = E.raw_signal, E.exit_path

    def rs(sid, sy, P, btc=None, mode="signal"):
        sg = orig_rs(sid, sy, P, btc, mode)
        if mode != "signal": return sg
        m = build_mask(sid, sy, P, x, env)
        return sg if m is None else (sg & m)

    def ep(sid, P, a, b0, S0, tgt, atr_e, dh_sig, o1, end_b=None):
        n = x.get("exit_n", 1) if x else 1
        if sid == MOM and n > 1: return exit_path_mom_n(P, a, b0, S0, atr_e, o1, end_b, n)
        return orig_ep(sid, P, a, b0, S0, tgt, atr_e, dh_sig, o1, end_b)

    E.raw_signal, E.exit_path = rs, ep
    try: yield
    finally: E.raw_signal, E.exit_path = orig_rs, orig_ep


@contextlib.contextmanager
def symbols(names):
    """Temporarily set engine.SYMS (used only for deterministic tie-ordering in simulate) - needed for non-cohort (holdout) assets."""
    old = E.SYMS
    if names: E.SYMS = list(names)
    try: yield
    finally: E.SYMS = old


def make_cands(sid, P, x, syms, f, s, names=None, env=None):
    with patched(x or {}, env or Env()):
        return A.cands_for(sid, P, syms, f, s, only=names)


# ---------------------------------------------------------------- candidate universe (predeclared in STAGE_06_ANALYSIS_PLAN.md)
def _grid(**dims):
    keys = list(dims); out = [{}]
    for k in keys: out = [dict(o, **{k: v}) for o in out for v in dims[k]]
    return out


def _base(sid): return dict(E.DEFAULTS[sid])


def families():
    """{(sid, family): dict(dims=ordered dim names with their value lists (baseline value included), categorical=[...], make=lambda point -> (P_over, x))}.
    A 'point' is a dict dim->value. The baseline point is the one equal to engine defaults / no extra mask."""
    F = {}
    fac = [None, ("EQ3", 0.0), ("PRIOR5", 0.0), ("VOLONLY", 0.0), ("EQ3", 0.5)]
    reg = [None, "DIR_NOT_BEARISH", "STRUCT_TRENDING", "VOL_NOT_HIGH"]
    def fam(sid, name, ordered, cat, mk): F[(sid, name)] = dict(ordered=ordered, cat=cat, mk=mk)
    # ---- MOM-101 (4H)
    fam(MOM, "PARAM", {"lookback": [150, 180, 210], "thr": [1.0, 1.25, 1.5]}, {}, lambda p: (dict(p), {}))
    fam(MOM, "ENTRY_CONFIRM", {"confirm": [1, 2, 3]}, {}, lambda p: ({}, {"confirm": p["confirm"]}))
    fam(MOM, "VOL_FILTER", {"rvr": [None, 1.5, 1.25]}, {}, lambda p: ({}, {"rvr": p["rvr"]}))
    fam(MOM, "TREND_FILTER", {"ext": [1.2, 1.3, 1.45]}, {}, lambda p: (dict(p), {}))
    fam(MOM, "LIQ_FILTER", {"l1": [None, 50e6, 100e6]}, {}, lambda p: ({}, {"l1": p["l1"]}))
    fam(MOM, "STOP", {"stop_k": [2.5, 3.0, 3.5], "trail_k": [3.0, 3.5, 4.0]}, {}, lambda p: (dict(p), {}))
    fam(MOM, "EXIT_CONFIRM", {"exit_n": [1, 2, 3]}, {}, lambda p: ({}, {"exit_n": p["exit_n"]}))
    fam(MOM, "FACTOR_OVERLAY", {}, {"factor": fac}, lambda p: ({}, {"factor": p["factor"]}))
    fam(MOM, "REGIME_ACTIVATION", {}, {"regime": reg}, lambda p: ({}, {"regime": p["regime"]}))
    # ---- VEX-103 (1H)
    fam(VEX, "PARAM", {"donch": [36, 48, 72], "tr_k": [1.5, 1.8, 2.2]}, {}, lambda p: (dict(p), {}))
    fam(VEX, "ENTRY_CONFIRM", {"ibs_min": [0.65, 0.75, 0.85]}, {}, lambda p: (dict(p), {}))
    fam(VEX, "VOL_FILTER", {"comp": [None, 1.0, 0.8]}, {}, lambda p: ({}, {"comp": p["comp"]}))
    fam(VEX, "TREND_FILTER", {"ctxp": [None, 100, 200]}, {}, lambda p: ({}, {"ctxp": p["ctxp"]}))
    fam(VEX, "LIQ_FILTER", {"vol_k": [1.5, 2.0, 2.5]}, {"weekend": [False, True]}, lambda p: ({"vol_k": p["vol_k"]}, {"weekend": p["weekend"]}))
    fam(VEX, "STOP", {"stop_k": [1.5, 2.0, 2.5], "trail_k": [2.0, 2.5, 3.0]}, {}, lambda p: (dict(p), {}))
    fam(VEX, "EXIT_CONFIRM", {"fail_bars": [3, 6, 12]}, {}, lambda p: (dict(p), {}))
    fam(VEX, "FACTOR_OVERLAY", {}, {"factor": fac}, lambda p: ({}, {"factor": p["factor"]}))
    fam(VEX, "REGIME_ACTIVATION", {}, {"regime": reg}, lambda p: ({}, {"regime": p["regime"]}))
    return F


def baseline_point(sid, fam_name):
    """The point of a family that reproduces the baseline."""
    fm = families()[(sid, fam_name)]; b = _base(sid); pt = {}
    for k, vals in fm["ordered"].items():
        if k in b: pt[k] = b[k]
        else: pt[k] = {"confirm": 1, "exit_n": 1, "rvr": None, "l1": None, "comp": None, "ctxp": None}[k]
    for k, vals in fm["cat"].items(): pt[k] = vals[0]
    return pt


def points(sid, fam_name):
    fm = families()[(sid, fam_name)]
    dims = dict(fm["ordered"]); dims.update(fm["cat"])
    return _grid(**dims)


def config_for(sid, fam_name, pt):
    """-> (P, x) with P the full engine parameter dict (defaults + overrides) and x the extras dict (empty extras dropped)."""
    over, x = families()[(sid, fam_name)]["mk"](pt)
    P = dict(_base(sid)); P.update({k: v for k, v in over.items()})
    xs = {}
    for k, v in x.items():
        if v is None or v is False: continue
        if k in ("confirm", "exit_n") and v == 1: continue
        xs[k] = v
    return P, xs


def cfg_id(sid, fam_name, pt):
    return f"{sid}|{fam_name}|" + ",".join(f"{k}={pt[k]}" for k in sorted(pt))


def neighbours(sid, fam_name, pt):
    """Points differing by <=1 grid step in ordered dims, identical in categorical dims (excluding pt itself)."""
    fm = families()[(sid, fam_name)]; out = []
    for q in points(sid, fam_name):
        if q == pt: continue
        if any(q[k] != pt[k] for k in fm["cat"]): continue
        ok = True
        for k, vals in fm["ordered"].items():
            if abs(vals.index(q[k]) - vals.index(pt[k])) > 1: ok = False; break
        if ok: out.append(q)
    return out


def universe():
    """Unique configurations per strategy: {cfg_id: (sid, fam, pt, P, x)} - the baseline appears once per strategy under key '<sid>|BASELINE'."""
    U = {}
    for (sid, fam_name) in families():
        bp = baseline_point(sid, fam_name)
        for pt in points(sid, fam_name):
            if pt == bp: continue
            P, x = config_for(sid, fam_name, pt)
            U[cfg_id(sid, fam_name, pt)] = (sid, fam_name, pt, P, x)
    for sid in (MOM, VEX): U[f"{sid}|BASELINE"] = (sid, "BASELINE", {}, _base(sid), {})
    return U
