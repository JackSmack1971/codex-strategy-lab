import numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates
from . import analysis as A, load_grid
syms = load_grid.get(); BASE = (0.001, 0.0005)
eq = pd.read_csv(A.__file__.replace("analysis.py", "../docs/strategy-specs/stage02/daily_equity_baseline.csv"))
COL = {"CRY-MOM-101": "#0072B2", "CRY-REV-102": "#D55E00", "CRY-VEX-103": "#009E73"}
BEN = {"EW_BH": ("Equal-weight B&H (9 assets)", "#6b7280", ":"), "BTC_SMA200": ("BTC SMA200 long/cash", "#6b7280", "--")}
INK, GRID = "#1f2937", "#e5e7eb"
fig, ax = plt.subplots(2, 3, figsize=(14, 7.2), sharex="col", dpi=150, facecolor="white")
for c, w in enumerate(A.WINDOWS):
    ws, we = A.WINDOWS[w]; dates = pd.to_datetime([str(A.hdate(ws + 24 * k + 23).date()) for k in range((we - ws) // 24)])
    series = {}
    for sid in COL: series[sid] = eq[(eq.strategy == sid) & (eq.window == w)].equity.to_numpy()
    for k, (lab, col, ls) in BEN.items(): series[k] = A.bench_daily_equity(syms, w, *BASE, k)
    for k, v in series.items():
        idx = v / 10000 * 100; pk = np.maximum.accumulate(np.concatenate([[10000], v]))[1:]; dd = (v / pk - 1) * 100
        col = COL.get(k) or BEN[k][1]; ls = "-" if k in COL else BEN[k][2]; lab = k if k in COL else BEN[k][0]
        ax[0, c].plot(dates, idx, color=col, ls=ls, lw=1.6 if k in COL else 1.3, label=lab)
        ax[1, c].plot(dates, dd, color=col, ls=ls, lw=1.3)
    ax[0, c].set_title(f"{w}" + (" (consumed legacy window: descriptive only)" if w == "final" else ""), color=INK, fontsize=10, loc="left")
    ax[0, c].axhline(100, color=GRID, lw=1)
    for r in (0, 1):
        ax[r, c].grid(True, color=GRID, lw=.6); ax[r, c].spines[["top", "right"]].set_visible(False); ax[r, c].tick_params(colors=INK, labelsize=8); ax[r, c].xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=5)); ax[r, c].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
ax[0, 0].set_ylabel("Equity, start = 100", color=INK); ax[1, 0].set_ylabel("Drawdown, %", color=INK)
h, l = ax[0, 0].get_legend_handles_labels(); fig.legend(h, l, loc="lower center", ncol=5, frameon=False, fontsize=9)
fig.suptitle("Stage 02 backtests (separate $10,000 book per window, baseline assumed costs; benchmarks fully invested)", color=INK, fontsize=11, x=0.01, ha="left")
fig.tight_layout(rect=(0, .05, 1, .96)); fig.savefig("docs/strategy-specs/stage02/equity_drawdown.png"); print("ok")
