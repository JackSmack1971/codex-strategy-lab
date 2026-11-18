"""Stage 06 chart: (left) pooled walk-forward OOS dSharpe per family vs the +0.15 gate; (right) naive in-sample-best optimiser: in-sample vs out-of-sample dSharpe per fold."""
import json
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
OUT = Path(__file__).resolve().parents[1] / "docs" / "strategy-specs" / "stage06"
r = json.loads((OUT / "stage06_dev_results.json").read_text())
INK, MUTED, ACC, GR = "#1f2933", "#6b7280", "#2563eb", "#b8bec7"
fig, (a, b) = plt.subplots(1, 2, figsize=(13, 6.2), gridspec_kw=dict(width_ratios=[1.25, 1]), dpi=160)
items = sorted(r["families"].items(), key=lambda kv: kv[1]["pooled"]["dSharpe"])
for i, (k, f) in enumerate(items):
    v = f["pooled"]["dSharpe"]; a.barh(i, v, color=ACC if f["finalist"] else GR, height=.62)
    a.text(v + (.015 if v >= 0 else -.015), i, f"{v:+.2f}  p_holm={f['holm_adj_p']:.2f}", va="center", ha="left" if v >= 0 else "right", fontsize=7.5, color=INK)
a.set_yticks(range(len(items))); a.set_yticklabels([k.replace("CRY-", "").replace("-101", "").replace("-103", "").replace("|", " ") for k, _ in items], fontsize=8, color=INK)
a.axvline(0.15, color=INK, ls="--", lw=1); a.text(0.155, -0.9, "gate +0.15", fontsize=7.5, color=INK); a.axvline(0, color=MUTED, lw=.8)
a.set_xlim(-0.55, 0.85); a.set_xlabel("pooled out-of-sample dSharpe vs baseline (5 anchored folds, 2023-05..2025-11)", fontsize=8.5, color=INK)
a.set_title("Only 3 of 18 families pass all gates (blue); none survives Holm", fontsize=10, loc="left", color=INK)
for s in ("top", "right"): a.spines[s].set_visible(False)
a.grid(axis="x", color="#e5e7eb", lw=.6); a.set_axisbelow(True)
x = 0
for sid, mk in (("CRY-MOM-101", "o"), ("CRY-VEX-103", "s")):
    for n in r["selection_bias"][sid]["naive_insample_best"]:
        b.plot([x, x], [n["ins_dS"], n["oos_dS"]], color=GR, lw=1.2, zorder=1)
        b.scatter(x, n["ins_dS"], marker=mk, s=38, color=ACC, zorder=3, label="in-sample (train)" if x == 0 else None)
        b.scatter(x, n["oos_dS"], marker=mk, s=38, facecolor="white", edgecolor=INK, zorder=3, label="out-of-sample (test)" if x == 0 else None); x += 1
    x += 1
b.axhline(0, color=MUTED, lw=.8); b.set_xticks([2, 8]); b.set_xticklabels(["MOM (folds 0-4)", "VEX (folds 0-4)"], fontsize=8.5)
b.set_ylabel("dSharpe vs baseline", fontsize=8.5); b.legend(frameon=False, fontsize=8, loc="lower left")
b.set_title("Naive optimiser (best train Sharpe of all configs)\nloses its edge out of sample", fontsize=10, loc="left", color=INK)
for s in ("top", "right"): b.spines[s].set_visible(False)
b.grid(axis="y", color="#e5e7eb", lw=.6); b.set_axisbelow(True)
fig.text(.01, .005, "Costs assumed (15bp/side). DEV history is not untouched; adjacent-asset holdout shares calendar time. Research only.", fontsize=7, color=MUTED)
plt.tight_layout(rect=(0, .02, 1, 1)); fig.savefig(OUT / "stage06_walkforward.png")
