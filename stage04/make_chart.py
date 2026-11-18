import json, numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
R = Path(__file__).resolve().parents[1] / "docs/strategy-specs/stage04"
x = pd.read_csv(R / "btc_daily_indicators.csv", index_col=0, parse_dates=True).tail(300); r = json.load(open(R / "regime_results.json"))
B, O, G, V, K = "#0072B2", "#E69F00", "#009E73", "#CC79A7", "#555555"
fig, ax = plt.subplots(3, 1, figsize=(10, 9), sharex=True, gridspec_kw=dict(height_ratios=[3, 1.6, 1.6]))
ax[0].plot(x.index, x.c, color="black", lw=1.4, label="BTCUSDT daily close")
for n, col in ((20, O), (50, G), (200, V)): ax[0].plot(x.index, x[f"ema{n}"], color=col, lw=1.2, label=f"EMA{n}")
ax[0].set_ylabel("USDT"); ax[0].legend(loc="upper left", ncol=4, frameon=False, fontsize=8); ax[0].set_title(f"BTC regime inputs (last completed day {r['assets']['BTC']['date']}, Binance spot, UTC)", fontsize=10, loc="left")
ax[1].plot(x.index, x.adx, color=B, lw=1.3, label="ADX(14)"); ax[1].plot(x.index, x.pdi, color=G, lw=0.9, label="+DI"); ax[1].plot(x.index, x.mdi, color=O, lw=0.9, label="-DI")
ax[1].axhline(25, color=K, ls="--", lw=0.8); ax[1].axhline(20, color=K, ls=":", lw=0.8); ax[1].legend(loc="upper left", ncol=3, frameon=False, fontsize=8); ax[1].set_ylabel("ADX / DI")
ax[2].plot(x.index, x.rv30 * 100, color=B, lw=1.3, label="30d realised vol (ann., %)"); ax[2].plot(x.index, x.rv7 * 100, color=O, lw=0.9, label="7d")
ax[2].legend(loc="upper left", ncol=2, frameon=False, fontsize=8); ax[2].set_ylabel("%")
for a in ax: a.grid(alpha=.2); a.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(R / "regime_btc.png", dpi=150)
