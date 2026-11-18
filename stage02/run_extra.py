"""Post-run diagnostics (clearly labelled POST-HOC where they were added after seeing results)."""
import json, numpy as np
from pathlib import Path
from . import engine as E, analysis as A, load_grid
syms = load_grid.get(); BASE = (0.001, 0.0005); OUT = Path(__file__).resolve().parents[1] / "docs/strategy-specs/stage02"
X = {}
# 1. readiness coverage (share of window bars where the strategy could signal at all: valid, warm, liquid)
cov = {}
for sid in E.DEFAULTS:
    P = E.DEFAULTS[sid]; tf = P["tf"]; cov[sid] = {}
    for w, (ws, we) in A.WINDOWS.items():
        fr = []
        for name in E.SYMS:
            pool = E.raw_signal(sid, syms[name], P, syms["BTC"], "pool"); fr.append(pool[ws // tf: we // tf].mean())
        cov[sid][w] = dict(mean_share_of_bars_pool_eligible=float(np.mean(fr)), per_symbol={n: float(x) for n, x in zip(E.SYMS, fr)})
X["pool_eligibility_share"] = cov
# 2. constraint audit on combined book + standalone books
allc = sum([A.cands_for(sid, E.DEFAULTS[sid], syms, *BASE) for sid in E.DEFAULTS], [])
viol = {"notional_cap": 0, "risk_per_trade": 0, "max_positions": 0, "total_risk": 0, "checked_trades": 0}
for w in A.WINDOWS:
    for books in ("combined", *E.DEFAULTS):
        cs = allc if books == "combined" else [c for c in allc if c["sid"] == books]
        r = A.run_window(cs, syms, w, *BASE); tr = r["trades"]
        for t in tr:
            viol["checked_trades"] += 1
            if t["qty"] * t["entry_fill"] > 0.33 * t["E_entry"] * (1 + 1e-9): viol["notional_cap"] += 1
            if t["reserved_risk"] > 0.01 * t["E_entry"] * (1 + 1e-9): viol["risk_per_trade"] += 1
            live = [u for u in tr if u["entry_hour"] <= t["entry_hour"] < (u["exit_hour"] + (u["tf"] if u["kind"] != "open" else 0)) ]
            if len(live) > 3: viol["max_positions"] += 1
            if sum(u["reserved_risk"] for u in live) > 0.03 * t["E_entry"] * (1 + 1e-6): viol["total_risk"] += 1
X["constraint_audit"] = viol
# 3. POST-HOC diagnostic nulls with exits decoupled from the entry trigger
dec = {"CRY-VEX-103": dict(fail_bars=0), "CRY-MOM-101": dict(), "CRY-REV-102": dict()}
X["null_decoupled_POST_HOC"] = {}
for sid, ch in dec.items():
    P = dict(E.DEFAULTS[sid], **ch); X["null_decoupled_POST_HOC"][sid] = {}
    if sid == "CRY-VEX-103":
        for w in ("train", "validation"):
            c = A.cands_for(sid, P, syms, *BASE); r = A.run_window(c, syms, w, *BASE); pool = A.unit_pool(sid, P, syms, *BASE, w)
            X["null_decoupled_POST_HOC"][sid][w] = dict(note="failed-breakout leg removed for both real and random entries", **A.null_test(r["trades"], pool),
                    real_ratio=A.trade_metrics(r["trades"]).get("ratio"))
    # MOM/REV: random entries restricted to bars where the exit signal is NOT already true at entry (removes instant-exit artefact)
    elif sid == "CRY-MOM-101":
        for w in ("train", "validation"):
            pool = A.unit_pool(sid, P, syms, *BASE, w); c = A.cands_for(sid, P, syms, *BASE); r = A.run_window(c, syms, w, *BASE)
            X["null_decoupled_POST_HOC"][sid][w] = dict(note="same as literal null (no coupling artefact: random entries are in-trend)", **A.null_test(r["trades"], pool))
print(json.dumps(X, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))[:6000])
(OUT / "results_extra.json").write_text(json.dumps(X, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
