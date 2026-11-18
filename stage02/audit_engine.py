"""Independent checks of the engine on real data: reconciliation + hand recomputation of sample trades from raw 1H bars."""
import numpy as np, pandas as pd
from . import engine as E, analysis as A, load_grid, data as D
syms = load_grid.get(); f, s = .001, .0005
raw = {k: D.load(k)[0].set_index("t") for k in ("BTC", "ETH", "SOL")}
def h2t(h): return E.T0_MS + int(h) * E.HOUR
bad = 0
for sid in E.DEFAULTS:
    P = E.DEFAULTS[sid]; c = A.cands_for(sid, P, syms, f, s)
    for w in A.WINDOWS:
        r = A.run_window(c, syms, w, f, s); eq0 = 10_000.0
        pnl = sum(t["pnl"] for t in r["trades"]); end = r["equity"][-1]
        ok = abs(eq0 + pnl - end) < 1e-6 * 10_000
        mins = min([t["exit_hour"] - t["entry_hour"] for t in r["trades"]] or [0])
        ex = max(1.0 * t["qty"] * t["entry_fill"] / 10_000 for t in r["trades"]) if r["trades"] else 0
        worst = min((t["R"] for t in r["trades"]), default=0)
        print(f"{sid} {w}: reconcile {'OK' if ok else 'FAIL'} (eq_end-10000={end-eq0:.4f}, sum pnl={pnl:.4f}); min hold hrs={mins}; max position/E at entry={ex:.3f}; worst R={worst:.2f}")
        bad += (not ok)
print("reconciliation failures:", bad)
# hand recomputation of the first train trade per strategy from raw bars (independent of engine arrays)
for sid in E.DEFAULTS:
    P = E.DEFAULTS[sid]; c = A.cands_for(sid, P, syms, f, s); r = A.run_window(c, syms, "train", f, s)
    t = r["trades"][0]; d = raw[t["symbol"]] if t["symbol"] in raw else D.load(t["symbol"])[0].set_index("t")
    te, tx = h2t(t["entry_hour"]), h2t(t["exit_hour"])
    tf = 4 if t["tf"] == 4 else 1
    print(f"\n{sid} first train trade {t['symbol']} entry {pd.Timestamp(te, unit='ms', tz='UTC')} exit-bar {pd.Timestamp(tx, unit='ms', tz='UTC')} kind={t['kind']}")
    o_entry = d.loc[te, "o"]; print("  raw entry-bar open", o_entry, "engine O1", t["O1"], "match", abs(o_entry - t["O1"]) < 1e-9, "| fill", t["entry_fill"], "expected", o_entry * (1 + s))
    bar = d.loc[tx: tx + (tf - 1) * E.HOUR]; lo, hi, op = bar.l.min(), bar.h.max(), bar.o.iloc[0]
    print("  exit bar raw O/H/L", op, hi, lo, "| exit fill", t["exit_fill"], "| S0", t["S0"], "| qty", t["qty"], "pnl", round(t["pnl"], 2), "R", round(t["R"], 3))
