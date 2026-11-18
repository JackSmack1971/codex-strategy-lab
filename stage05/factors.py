"""Stage 05 factor construction. Research only: read-only public data, no orders, no credentials.
Every factor value at date t uses ONLY information available at the close of UTC day t (on-chain: value stamped <= t-1).
Cross-sectional normalisation at date t uses only the other assets' values at the same date t (no time-series look-ahead).
Factor signs are FIXED BY HYPOTHESIS here, before any factor-return relationship was examined; they are never flipped by data."""
from __future__ import annotations
import json, math, sys
from pathlib import Path
from statistics import NormalDist
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ["BTC", "ETH", "SOL", "XRP", "ADA", "LINK", "AVAX", "DOGE", "LTC"]
CM = {"BTC": "btc", "ETH": "eth", "ADA": "ada", "XRP": "xrp", "DOGE": "doge", "LINK": "link", "LTC": "ltc", "AVAX": "avaxc"}  # SOL: not in Coinmetrics community MVRV
PRIMARY = ["MOM", "TREND", "VOL", "LIQ", "VALUE"]          # candidate composite members (VALUE = price-based long-horizon reversal proxy)
EXPERIMENTAL = ["VALUE_MVRV"]                               # on-chain; community tier, no point-in-time vintages -> never in the composite by default
SIGN_RATIONALE = {  # hypothesised direction of the RAW factor vs future return; fixed a priori
    "MOM": +1, "TREND": +1, "VOL": -1, "LIQ": +1, "VALUE": -1, "VALUE_MVRV": -1}
PARAMS = dict(mom_n=30, ema_fast=50, ema_slow=200, vol_n=30, vol_minobs=27, liq_short=7, liq_base=90, liq_lag=7,
              val_far=365, val_near=90, min_assets=5, clip=2.0, min_factors=3, ema_minobs=200)

# ---------------------------------------------------------------- data
def load_panel(snap=None):
    """Daily panel (UTC) from the Stage 02 archive + fresh Binance spot klines (Stage 04 extension). A day is valid only if all 24 hourly bars exist."""
    from stage04 import regime as R
    snap = snap or R.latest_snapshot()
    syms, n, ovl = R.extended_grid(snap)
    fr = {s: R.daily_frame(syms[s], n) for s in ASSETS}
    idx = fr["BTC"].index; P = {}
    for k in "ohlcq":
        P[k] = pd.DataFrame({s: fr[s][k].where(fr[s]["nbar"] == 24) for s in ASSETS}, index=idx)
    P["nbar"] = pd.DataFrame({s: fr[s]["nbar"] for s in ASSETS}, index=idx)
    # first valid day per asset (drop leading empties)
    return P, dict(snapshot=str(snap.name), n_hours=int(n), overlap=ovl)

def load_mvrv(raw=None):
    raw = Path(raw or ROOT / "data" / "s5raw"); out = {}
    for a, c in CM.items():
        d = json.loads((raw / f"cm_{c}.json").read_text())["data"]
        s = pd.Series({pd.Timestamp(r["time"]).tz_convert("UTC").normalize(): float(r["CapMVRVCur"]) if r.get("CapMVRVCur") not in (None, "") else np.nan for r in d})
        out[a] = s
    return pd.DataFrame(out).reindex(columns=ASSETS)

# ---------------------------------------------------------------- raw factors (time-series per asset, no cross-sectional info)
def ema(x: pd.DataFrame, n: int, minobs: int) -> pd.DataFrame:
    return x.ewm(span=n, adjust=False, min_periods=minobs).mean()

def raw_factors(P, mvrv=None, p=PARAMS):
    C, Q = P["c"], P["q"]; lc = np.log(C); r1 = lc.diff()
    F = {}
    F["MOM"] = lc - lc.shift(p["mom_n"])                                                  # 30d log return (close_t / close_{t-30})
    F["TREND"] = np.log(ema(C, p["ema_fast"], p["ema_slow"]) / ema(C, p["ema_slow"], p["ema_slow"]))  # ln(EMA50/EMA200)
    F["VOL"] = r1.rolling(p["vol_n"], min_periods=p["vol_minobs"]).std(ddof=1) * math.sqrt(365)    # RAW = realised vol; hypothesis sign -1 (low vol preferred)
    qs = Q.rolling(p["liq_short"], min_periods=p["liq_short"]).mean()
    qb = Q.shift(p["liq_lag"]).rolling(p["liq_base"], min_periods=int(p["liq_base"] * 0.9)).median()
    F["LIQ"] = np.log(qs / qb)                                                           # abnormal dollar volume: 7d mean / prior-90d median
    F["VALUE"] = lc.shift(p["val_near"]) - lc.shift(p["val_far"])                         # ln(C_{t-90}/C_{t-365}); hypothesis sign -1 (long-horizon reversal)
    if mvrv is not None:
        m = mvrv.reindex(C.index).shift(1)                                               # stamped <= t-1 only
        F["VALUE_MVRV"] = np.log(m.where(m > 0))                                          # ln(MVRV); hypothesis sign -1 (cheap = low MVRV)
    return F

# ---------------------------------------------------------------- normalisation
_ND = NormalDist()
_PPF = np.vectorize(_ND.inv_cdf)

def rank_normal_row(v: np.ndarray, min_assets: int, clip: float) -> np.ndarray:
    """Rank-normal score: z = Phi^-1((rank-0.5)/N) over assets valid at this date, ties by average rank; NaN if N < min_assets. Clipped to +-clip."""
    out = np.full(v.shape, np.nan); ok = np.isfinite(v); n = int(ok.sum())
    if n < min_assets: return out
    rk = pd.Series(v[ok]).rank(method="average").to_numpy()
    out[ok] = np.clip(_PPF((rk - 0.5) / n), -clip, clip)
    return out

def cs_normalise(F: pd.DataFrame, sign: int, p=PARAMS) -> pd.DataFrame:
    """Cross-sectional rank-normal z at each date, oriented by the a-priori sign so that higher z = hypothesised higher future return."""
    A = F.to_numpy() * sign
    Z = np.vstack([rank_normal_row(A[i], p["min_assets"], p["clip"]) for i in range(A.shape[0])])
    return pd.DataFrame(Z, index=F.index, columns=F.columns)

def build_z(P, mvrv=None, p=PARAMS):
    raw = raw_factors(P, mvrv, p)
    Z = {k: cs_normalise(v, SIGN_RATIONALE[k], p) for k, v in raw.items()}
    return raw, Z

# ---------------------------------------------------------------- aggregation
def composite(Z: dict, w: dict, p=PARAMS) -> pd.DataFrame:
    """S_{i,t} = sum_k w_k z_{k,i,t} / sum_{k available} w_k ; needs >= min_factors available factors with positive weight, else NaN.
    Missing factors are renormalised out (never imputed with zero z or look-ahead values)."""
    ks = [k for k in w if w[k] > 0 and k in Z]
    num = sum(Z[k].fillna(0.0) * w[k] for k in ks); den = sum(Z[k].notna().astype(float) * w[k] for k in ks)
    cnt = sum(Z[k].notna().astype(int) for k in ks)
    S = num / den.where(den > 0)
    return S.where(cnt >= min(p["min_factors"], len(ks)))

# ---------------------------------------------------------------- targets
def targets(P, h):
    """y_h(t) = ln(C[t+h] / O[t+1]): enter at next day's open (signal known at close t), exit at close t+h. Uses data AFTER t by construction (label only)."""
    return np.log(P["c"].shift(-h) / P["o"].shift(-1))

def sp_ic(Z: pd.DataFrame, Y: pd.DataFrame, min_assets=5) -> pd.Series:
    """Daily cross-sectional Spearman rank IC."""
    out = {}
    za, ya = Z.to_numpy(), Y.to_numpy()
    for i, d in enumerate(Z.index):
        ok = np.isfinite(za[i]) & np.isfinite(ya[i])
        if ok.sum() >= min_assets:
            a = pd.Series(za[i][ok]).rank().to_numpy(); b = pd.Series(ya[i][ok]).rank().to_numpy()
            if a.std() > 0 and b.std() > 0: out[d] = float(np.corrcoef(a, b)[0, 1])
    return pd.Series(out, dtype=float)
