"""POST-HOC descriptive diagnostic (not a criterion, changes no determination): per-asset trade P&L of the baselines on the adjacent-asset holdout, DEV window,
and buy-and-hold of each holdout asset vs the cohort over the same window. Research only."""
import json
import numpy as np
from stage02 import engine as E, analysis as A
from . import variants as V, wf as W, run_holdout as H
syms, _ = H.build_holdout_syms(); out = {}
with V.symbols(H.HOLD):
    for sid in (V.MOM, V.VEX):
        c = V.make_cands(sid, V._base(sid), {}, syms, *W.BASE_COST, H.HOLD, V.Env()); r = A.run_window(c, syms, W.DEV, *W.BASE_COST); per = {}
        for t in r["trades"]:
            d = per.setdefault(t["symbol"], dict(n=0, pnl=0.0, risk=0.0)); d["n"] += 1; d["pnl"] += t["pnl"]; d["risk"] += t["reserved_risk"]
        out[sid] = {k: dict(n=v["n"], pnl=round(v["pnl"], 1), ratio=round(v["pnl"] / v["risk"], 3)) for k, v in per.items()}
bh = {}
for s in list(H.HOLD) + ["BTC", "ETH", "SOL", "XRP", "ADA", "LINK", "AVAX", "DOGE", "LTC"]:
    sy = syms.get(s) or None
    if sy is None: continue
    a, b = W.DEV; bh[s] = round(float(np.log(sy.cff[b - 1] / sy.cff[a])), 3)
out["buy_hold_logret_DEV"] = bh
print(json.dumps(out, indent=0))
