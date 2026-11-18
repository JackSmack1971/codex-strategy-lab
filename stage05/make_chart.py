import json, pandas as pd, numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from pathlib import Path
OUT = Path(__file__).resolve().parents[1] / "docs" / "strategy-specs" / "stage05"; r = json.loads((OUT / "stage05_results.json").read_text())
C = dict(MOM="#0072B2", TREND="#E69F00", VOL="#009E73", LIQ="#D55E00", VALUE="#CC79A7", VALUE_MVRV="#56B4E9")
ks = list(C); f = r["factor_ic"]; leg = r["consumed_legacy_descriptive"]["per_factor_ic_DIAGNOSTIC_ONLY"]
fig, ax = plt.subplots(2, 1, figsize=(10, 9), constrained_layout=True)
x = np.arange(len(ks)); w = 0.26
tr = [f["h7_train"][k]["mean"] for k in ks]; va = [f["h7_val"][k]["mean"] for k in ks]; lg = [leg[k] for k in ks]
lo = [f["h7_val"][k]["mean"] - f["h7_val"][k]["lo95"] for k in ks]; hi = [f["h7_val"][k]["hi95"] - f["h7_val"][k]["mean"] for k in ks]
ax[0].bar(x - w, tr, w, label="train 2022-05..2024-11", color="#0072B2"); ax[0].bar(x, va, w, yerr=[lo, hi], capsize=3, label="validation 2024-11..2025-11 (95% block-bootstrap CI)", color="#E69F00")
ax[0].bar(x + w, lg, w, label="consumed window 2025-11..2026-11 (DIAGNOSTIC ONLY)", color="#999999", hatch="//", edgecolor="white")
ax[0].axhline(0, color="k", lw=0.8); ax[0].set_xticks(x); ax[0].set_xticklabels(ks); ax[0].set_ylabel("mean daily rank IC vs 7-day forward return"); ax[0].legend(frameon=False, fontsize=8, loc="upper right")
ax[0].set_title("Factor information coefficient by period (9 assets; IC SE ~0.05 per year)", loc="left", fontsize=10)
ic = pd.read_csv(OUT / "factor_ic_daily_h7.csv", index_col=0, parse_dates=True)
for k in ["MOM", "TREND", "VOL", "LIQ", "VALUE"]: ax[1].plot(ic.index, ic[k].rolling(90, min_periods=60).mean(), color=C[k], lw=1.4, label=k)
ax[1].axhline(0, color="k", lw=0.8); ax[1].axvline(pd.Timestamp("2024-11-17", tz="UTC") if ic.index.tz else pd.Timestamp("2024-11-17"), color="#555", ls="--", lw=1); ax[1].text(ic.index[-1], ax[1].get_ylim()[1] * 0.9, "validation starts at dashed line", ha="right", fontsize=8)
ax[1].set_ylabel("rolling 90-day mean IC"); ax[1].legend(ncol=5, frameon=False, fontsize=8, loc="lower left"); ax[1].set_title("Stability over time (train + validation; gap = purged days)", loc="left", fontsize=10)
for a in ax: a.spines[["top", "right"]].set_visible(False)
fig.savefig(OUT / "factor_ic.png", dpi=130)
