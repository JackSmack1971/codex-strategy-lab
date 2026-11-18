import json, time, numpy as np
from . import engine as E, analysis as A, load_grid
t0 = time.time(); syms = load_grid.get(); print("grid", round(time.time() - t0, 1), "s")
f, s = 0.001, 0.0005
for sid in E.DEFAULTS:
    P = E.DEFAULTS[sid]; st = {}
    t0 = time.time(); c = A.cands_for(sid, P, syms, f, s, stats=st); print(sid, "candidates", len(c), "funnel", st, round(time.time() - t0, 1), "s")
    for w in A.WINDOWS:
        r = A.run_window(c, syms, w, f, s); m, _ = A.full_metrics(r)
        print(f"  {w:10s} n={m['n']:4d} ratio={m.get('ratio',float('nan')):+.3f} E[R]={m.get('expectancy_R',float('nan')):+.3f} win={m.get('win_rate',float('nan')):.2f} PF={m.get('profit_factor',float('nan')):.2f} "
              f"ret={m['total_return']:+.3f} cagr={m['cagr']:+.3f} sh={m['sharpe']:+.2f} mdd={m['max_dd']:.3f} skips={r['skips']}")
