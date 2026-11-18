"""Stage 03 chart: daily drawdown (baseline sizing) and hypothetical -20% gap-shock loss, by book. Research only."""
import numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates, pandas as pd
from pathlib import Path
from stage02 import load_grid, analysis as A
from stage03 import core as C
syms = load_grid.get(); f, s = C.BASE; cands = C.build_cands(syms, f, s); R = C.run_all(cands, syms, f, s)
COL = {"CRY-MOM-101": "#0072B2", "CRY-REV-102": "#D55E00", "CRY-VEX-103": "#009E73", "COMBINED": "#444444"}
fig, ax = plt.subplots(2, 1, figsize=(11, 8.2), constrained_layout=True)
for b in C.BOOKS:
    xs, dd, exp = [], [], []
    for w in C.WINS:
        res = R[b][w]; ws = res["ws"]; d = np.concatenate([[A.CAP], A.daily_equity(res)]); pk = np.maximum.accumulate(d); n = len(d) - 1
        xs += [A.hdate(ws + 24 * k) for k in range(n)]; dd += list(d[1:] / pk[1:] - 1)
        ls = C.gap_shock(res, syms, .20, 0.0, f, s); cnt = C.hourly_positions(res, syms)[1]; exp.append(ls[cnt > 0])
    ax[0].plot(xs, np.array(dd) * 100, color=COL[b], lw=1.1 if b != "COMBINED" else 1.4, ls="-" if b != "COMBINED" else "--", label=b)
    e = np.sort(np.concatenate(exp))[::-1] * 100; ax[1].plot(np.arange(1, len(e) + 1) / len(e) * 100, e, color=COL[b], lw=1.6, ls="-" if b != "COMBINED" else "--", label=b)
for w in ("validation", "final"): ax[0].axvline(A.hdate(A.WINDOWS[w][0]), color="#999", lw=.8, ls=":")
ax[0].text(A.hdate(A.WINDOWS["validation"][0]), 0.6, " validation", fontsize=7, color="#666", va="bottom"); ax[0].text(A.hdate(A.WINDOWS["final"][0]), 0.6, " final (consumed)", fontsize=7, color="#666", va="bottom")
ax[0].set_ylim(top=3); ax[0].grid(alpha=.25); ax[1].grid(alpha=.25)
ax[0].set_ylabel("Drawdown from running peak (%)"); ax[0].legend(loc="lower right", ncol=2, fontsize=8, frameon=False)
ax[0].set_title("Historical drawdown, baseline sizing (1% risk/trade, 3% open risk, 33% notional cap); each window is a fresh $10,000 book", fontsize=9, loc="left")
ax[0].xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=6)); ax[0].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
ax[1].axhline(3, color="#CC79A7", lw=1, ls="--"); ax[1].text(1, 3.4, "planned open-risk cap (3%)", fontsize=8, color="#CC79A7", ha="left")
ax[1].set_ylabel("Loss if all open positions gap -20%\n(% of equity)"); ax[1].set_xlabel("Share of in-position hours with loss at least this large (%)"); ax[1].legend(loc="upper right", fontsize=8, frameon=False, bbox_to_anchor=(1, .93))
ax[1].set_title("HYPOTHETICAL instant -20% gap with stops failing, applied to every historical hour with an open position", fontsize=9, loc="left")
out = Path(__file__).resolve().parents[1] / "docs/strategy-specs/stage03/risk_drawdown_shock.png"; fig.savefig(out, dpi=150); print(out)
