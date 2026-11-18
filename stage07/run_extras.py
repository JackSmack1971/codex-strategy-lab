"""Stage 07 extras (reporting only; recomputes the runner's deterministic series): pooled OOS daily returns CSV, descriptive stop-trading overlay, chart.
Run after run_stage07: PYTHONPATH=. scripts/lab python -m stage07.run_extras. Research only."""
from __future__ import annotations
import json
import numpy as np, pandas as pd
from . import core as C
from .run_stage07 import OUT, SCHEMES, clean, day


def overlay(r, t1=(0.08, 0.12, 0.15), m1=(0.5, 0.25, 0.0)):
    """APPROXIMATE return-level overlay of Stage 03 T1 (drawdown from high-water mark, daily), T2 (single-day loss >= 3 %) and T3 (7-day loss >= 5 %, half risk until 7d return > -2 %).
    Multipliers apply from the NEXT day; T2 is approximated as flat the next day. Thresholds are the Stage 03 proposals; nothing is tuned."""
    eq = 1.0; hwm = 1.0; out = np.zeros(len(r)); m = 1.0; hist = []; t3 = False; prev = [False, False, False]
    n = {"T1_8pct_dd_episodes": 0, "T1_12pct_dd_episodes": 0, "T1_15pct_dd_episodes": 0, "T2_day_loss_3pct_days": 0, "T3_7d_loss_5pct_episodes": 0}
    for i, x in enumerate(r):
        out[i] = m * x; eq *= 1 + out[i]; hwm = max(hwm, eq); dd = 1 - eq / hwm; hist.append(out[i])
        lv = [dd >= t1[0], dd >= t1[1], dd >= t1[2]]
        for j, k in enumerate(("T1_8pct_dd_episodes", "T1_12pct_dd_episodes", "T1_15pct_dd_episodes")):
            if lv[j] and not prev[j]: n[k] += 1
        prev = lv
        r7 = np.prod(1 + np.array(hist[-7:])) - 1 if len(hist) >= 7 else 0.0
        if r7 <= -0.05 and not t3: n["T3_7d_loss_5pct_episodes"] += 1
        t3 = (r7 <= -0.05) or (t3 and r7 < -0.02)
        if out[i] <= -0.03: n["T2_day_loss_3pct_days"] += 1
        m = m1[2] if lv[2] else (m1[1] if lv[1] else (m1[0] if lv[0] else 1.0))
        if t3: m = min(m, 0.5)
        if out[i] <= -0.03: m = 0.0
    return out, n


def main():
    R = json.loads((OUT / "stage07_results.json").read_text()); lab = C.Lab()
    P = {sc: [] for sc in SCHEMES}; Pm, Pv = [], []; dates = []
    for fd in C.FOLDS:
        rt = {sid: lab.sleeve(sid, fd["train"])["r"] for sid in C.SLEEVES}; sig, rho = C.estimate(rt[C.MOM], rt[C.VEX]); W = C.scheme_weights(sig, rho)
        for sc in SCHEMES: P[sc].append(lab.shared(sc, W[sc], fd["test"])["r"])
        Pm.append(lab.sleeve(C.MOM, fd["test"])["r"]); Pv.append(lab.sleeve(C.VEX, fd["test"])["r"]); dates += [day(fd["test"][0] + 24 * i) for i in range(len(Pm[-1]))]
    P = {k: np.concatenate(v) for k, v in P.items()}; Pm, Pv = np.concatenate(Pm), np.concatenate(Pv)
    for sc in SCHEMES: assert abs(C.sharpe(P[sc]) - R["oos"]["sharpe_ci"][sc]["sharpe"]) < 1e-9, "extras do not reproduce the runner"
    df = pd.DataFrame({"date_utc": dates, **{sc: P[sc] for sc in SCHEMES}, "MOM_ONLY": Pm, "VEX_ONLY": Pv}); df.to_csv(OUT / "oos_daily_returns.csv", index=False)
    susp = {}
    for sc in SCHEMES:
        o, n = overlay(P[sc]); susp[sc] = dict(events=n, plain=dict(sharpe=C.sharpe(P[sc]), max_dd=C.max_dd(P[sc]), total_return=float(np.prod(1 + P[sc]) - 1)),
                                               with_overlay=dict(sharpe=C.sharpe(o), max_dd=C.max_dd(o), total_return=float(np.prod(1 + o) - 1)))
    (OUT / "stage07_suspension_overlay.json").write_text(json.dumps(clean(dict(label="DESCRIPTIVE, APPROXIMATE return-level overlay of Stage 03 T1/T2/T3 on pooled OOS series; thresholds not tuned", results=susp)), indent=1))
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    col = {"EW": "#0072B2", "IV": "#E69F00", "RB": "#009E73", "CONS": "#CC79A7", "MOM_ONLY": "#555555"}
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw={"width_ratios": [1.5, 1]}); x = pd.to_datetime(df["date_utc"])
    for k, c in col.items():
        ax[0].plot(x, np.cumprod(1 + df[k].to_numpy()), color=c, lw=1.6 if k != "MOM_ONLY" else 1.2, ls="-" if k != "MOM_ONLY" else "--", label=k.replace("_", "-"))
    ax[0].axhline(1.0, color="#999", lw=0.8); ax[0].set_title("Pooled walk-forward OOS equity (folds chained; each fold a fresh book), baseline costs", fontsize=10); ax[0].set_ylabel("growth of 1.0")
    ax[0].legend(loc="upper left", fontsize=8, frameon=False, ncol=2); ax[0].spines[["top", "right"]].set_visible(False)
    c = R["asset_correlation"]; labs = ["calm days", "all days", "BTC worst\ndecile days", "BTC 90d-DD\n> 20% days"]
    vals = [c["calm"]["mean_pairwise"], c["full9"]["mean_pairwise"], c["btc_worst_decile"]["mean_pairwise"], c["btc_dd_gt20"]["mean_pairwise"]]
    eb = [c["calm"]["eff_bets"], c["full9"]["eff_bets"], c["btc_worst_decile"]["eff_bets"], c["btc_dd_gt20"]["eff_bets"]]
    ax[1].bar(range(4), vals, color="#0072B2", width=0.55)
    for i, (v, e) in enumerate(zip(vals, eb)): ax[1].text(i, v + 0.015, f"{v:.2f}\n({e:.1f} bets)", ha="center", fontsize=8)
    ax[1].set_xticks(range(4)); ax[1].set_xticklabels(labs, fontsize=8); ax[1].set_ylim(0, 1.0); ax[1].set_ylabel("mean pairwise daily correlation")
    ax[1].set_title("Nine-asset cohort: correlation rises in stress", fontsize=10); ax[1].spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "stage07_portfolio.png", dpi=150); print("ok"); print(json.dumps(clean(susp["CONS"]), indent=None)[:400])


if __name__ == "__main__": main()
