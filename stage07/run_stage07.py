"""Stage 07 portfolio analysis runner. Research only. Run once from a clean tree after the plan commit:
PYTHONPATH=. scripts/lab python -m stage07.run_stage07
Writes docs/strategy-specs/stage07/stage07_results.json. No parameter or gate is read back from the results."""
from __future__ import annotations
import json, math, subprocess, sys
from pathlib import Path
import numpy as np, pandas as pd
from stage02 import engine as E, analysis as A
from stage06.run_holdout import build_holdout_syms
from . import core as C

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "docs" / "strategy-specs" / "stage07"; OUT.mkdir(parents=True, exist_ok=True)
SCHEMES = ["EW", "IV", "RB", "CONS"]; HOLD = ["BNB", "DOT", "ATOM", "BCH"]


def git(*a): return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)): return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.bool_,)): return bool(o)
    if isinstance(o, np.ndarray): return clean(o.tolist())
    return o
def day(h): return str(A.hdate(h).date())


def daily_close(sy, d0, d1): return sy.cff[: (d1 * 24)].reshape(d1, 24)[:, -1][d0 - 1: d1]


def asset_returns(syms, names, win):
    d0, d1 = win[0] // 24, win[1] // 24; cols = {}
    for n in names:
        c = daily_close(syms[n], d0, d1); cols[n] = c[1:] / c[:-1] - 1
    return pd.DataFrame(cols, index=pd.RangeIndex(d0, d1))


def build_scheme_returns(lab, W, win, cost=C.BASE):
    """Shared-book simulation of every scheme in a window with weights W[scheme] (plan amendment 1)."""
    return {sc: lab.shared(sc, W[sc], win, cost) for sc in SCHEMES}


def seg_exposure(lab, W, win):
    """Run-1 exhibit: segregated sub-books, exposures normalised by contemporaneous equity."""
    out = {}
    for sc in SCHEMES:
        w = W[sc]
        if sc == "CONS": sl = {sid: lab.sleeve(sid, win, C.BASE, frac=w[sid], ncap=C.CONS_NCAP_TOTAL[sid] / w[sid]) for sid in C.SLEEVES}
        else: sl = {sid: lab.sleeve(sid, win) for sid in C.SLEEVES}
        hh = (1 - sum(w.values())) + sum(w[sid] * sl[sid]["hourly"] for sid in C.SLEEVES)
        e = C.exposure({sid: (sl[sid]["trades"], sl[sid]["cap"]) for sid in C.SLEEVES}, w, win[0], win[1], lab.syms, eq=A.CAP * hh); capr = 0.015 if sc == "CONS" else 0.03
        out[sc] = dict(peak_open_risk=float(e["open_risk"].max()), hours_open_risk_gt_cap=int((e["open_risk"] > capr + 1e-12).sum()), peak_positions=int(e["positions"].max()),
                       hours_positions_gt_limit=int((e["positions"] > (3 if sc == "CONS" else 6)).sum()), peak_single_asset=float(e["max_single_asset"].max()),
                       hours_single_asset_gt_15pct=int((e["max_single_asset"] > 0.15).sum()), peak_gross=float(e["gross"].max()), hours_same_symbol_overlap=int(e["same_symbol_overlap"].sum()))
    return out


def main():
    head = git("rev-parse", "HEAD"); dirty = [l for l in git("status", "--porcelain", "--untracked-files=no").splitlines() if l.strip()]
    if dirty: sys.exit("refusing to run: tracked files modified:\n" + "\n".join(dirty))
    lab = C.Lab(); syms = lab.syms; R = {"head": head}
    # ---------- 0. reproduce Stage 02 baselines (engine unchanged)
    tr = pd.read_csv(ROOT / "docs/strategy-specs/stage02/trades_baseline.csv"); rep = {}
    for sid in C.SLEEVES:
        for wn, win in (("train", A.WINDOWS["train"]), ("validation", A.WINDOWS["validation"]), ("final", A.WINDOWS["final"])):
            n = len(lab.sleeve(sid, win)["trades"]); ref = int(((tr.strategy == sid) & (tr.window == wn)).sum()); rep[f"{sid}/{wn}"] = dict(n=n, stage02=ref)
            assert n == ref, f"baseline reproduction failed {sid}/{wn}: {n} != {ref}"
    R["reproduction"] = rep
    # ---------- 1. sub-book equivalence (segregated sub-book of fraction w vs w x full-book growth)
    eqv = {}
    for sid in C.SLEEVES:
        full = lab.sleeve(sid, C.DEV)["g"]; half = lab.sleeve(sid, C.DEV, frac=0.5)["g"]
        eqv[sid] = dict(max_abs_diff_total_equity=float(np.max(np.abs(0.5 * (half - full)))), final_full=float(full[-1]), final_half=float(half[-1]),
                        trades_full=len(lab.sleeve(sid, C.DEV)["trades"]), trades_half=len(lab.sleeve(sid, C.DEV, frac=0.5)["trades"]))
    R["subbook_equivalence"] = eqv
    comb = lab.cands(C.MOM, C.BASE) + lab.cands(C.VEX, C.BASE); ref = A.run_window(comb, syms, C.DEV, C.BASE[0], C.BASE[1])
    from .shared import simulate_shared
    mine = simulate_shared(comb, syms, C.DEV[0], C.DEV[1], C.BASE[0], C.BASE[1]); key = lambda T: [(t["strategy"], t["symbol"], t["entry_hour"], t["exit_hour"], round(t["qty"], 9), round(t["pnl"], 6)) for t in T]
    assert key(ref["trades"]) == key(mine["trades"]) and np.allclose(ref["equity"], mine["equity"]), "shared simulator does not reproduce engine.simulate"
    R["shared_simulator_equivalence"] = dict(trades=len(ref["trades"]), identical=True, max_abs_equity_diff=float(np.max(np.abs(ref["equity"] - mine["equity"]))))
    # ---------- 2. asset correlations
    hsyms, haud = build_holdout_syms(); allsyms = {**syms, **{k: hsyms[k] for k in HOLD}}
    names9 = list(E.SYMS); names13 = names9 + HOLD
    Rall = asset_returns(allsyms, names13, C.DEV); R9 = Rall[names9]; btc = Rall["BTC"]
    stressmask = (btc <= btc.quantile(0.10)).to_numpy(); c90 = pd.Series(np.cumprod(1 + btc.to_numpy())); dd90 = (c90 / c90.rolling(90, min_periods=1).max() - 1).to_numpy()
    ddmask = dd90 <= -0.20
    roll = R9.rolling(30).corr(); rm = [float(roll.loc[i].to_numpy()[np.triu_indices(9, 1)].mean()) for i in R9.index[30::7] if not roll.loc[i].isna().all().all()]
    cor = dict(full9=C.corr_summary(R9), full13=C.corr_summary(Rall), btc_worst_decile=C.corr_summary(R9[stressmask]), btc_dd_gt20=C.corr_summary(R9[ddmask]) if ddmask.sum() > 30 else None,
               calm=C.corr_summary(R9[~stressmask]), n_stress_days=int(stressmask.sum()), n_dd20_days=int(ddmask.sum()),
               tail_coexceed_5pct=C.tail_coexceed(R9, 0.05), tail_coexceed_indep_benchmark=0.05, rolling30_mean_pairwise=dict(min=float(np.min(rm)), median=float(np.median(rm)), max=float(np.max(rm)), frac_gt_0p9=float(np.mean(np.array(rm) > 0.9))),
               pairwise_vs_BTC={n: float(R9[n].corr(btc)) for n in names9 if n != "BTC"}, adjacent_vs_BTC={n: float(Rall[n].corr(btc)) for n in HOLD},
               ann_vol={n: float(Rall[n].std() * math.sqrt(365)) for n in names13}, worst_day={n: float(Rall[n].min()) for n in names13},
               ew9_daily_rebalanced=C.stats((R9.mean(axis=1)).to_numpy()), btc_bh=C.stats(btc.to_numpy()))
    # equal-weight of 9 assets: how many assets fall on BTC's worst 5 % days
    w5 = btc <= btc.quantile(0.05); cor["share_assets_down_on_btc_worst5"] = float((R9[w5] < 0).to_numpy().mean())
    R["asset_correlation"] = cor
    # ---------- 3. walk-forward weights and OOS pooled series
    folds = []; oos = {sc: [] for sc in SCHEMES}; oos_mom, oos_vex, oos_contrib = [], [], {sc: {sid: [] for sid in C.SLEEVES} for sc in SCHEMES}; oos_tr = {sc: [] for sc in SCHEMES}; seg = {sc: [] for sc in SCHEMES}
    for fd in C.FOLDS:
        rt = {sid: lab.sleeve(sid, fd["train"])["r"] for sid in C.SLEEVES}; sig, rho = C.estimate(rt[C.MOM], rt[C.VEX]); W = C.scheme_weights(sig, rho)
        bs = build_scheme_returns(lab, W, fd["test"]); sl = {sid: lab.sleeve(sid, fd["test"]) for sid in C.SLEEVES}
        for sc in SCHEMES:
            oos[sc].append(bs[sc]["r"]); oos_tr[sc] += bs[sc]["trades"]
            for sid in C.SLEEVES: oos_contrib[sc][sid].append(bs[sc]["contrib"].get(sid, np.zeros(len(bs[sc]["r"]))))
        for sc in SCHEMES:
            wv = W[sc]; gg = {sid: lab.sleeve(sid, fd["test"], C.BASE, frac=wv[sid], ncap=C.CONS_NCAP_TOTAL[sid] / wv[sid])["g"] for sid in C.SLEEVES} if sc == "CONS" else {sid: sl[sid]["g"] for sid in C.SLEEVES}
            seg[sc].append(C.combine(wv, gg))
        oos_mom.append(sl[C.MOM]["r"]); oos_vex.append(sl[C.VEX]["r"])
        folds.append(dict(k=fd["k"], train_end=day(fd["train"][1]), test=[day(fd["test"][0]), day(fd["test"][1])], sigma=sig, rho=rho, weights=W,
                          oos_sharpe={sc: C.sharpe(bs[sc]["r"]) for sc in SCHEMES}, sleeve_oos_sharpe={C.MOM: C.sharpe(sl[C.MOM]["r"]), C.VEX: C.sharpe(sl[C.VEX]["r"])},
                          oos_trades={sc: {sid: len(bs[sc]["trades_by"][sid]) for sid in C.SLEEVES} for sc in SCHEMES}, standalone_trades={sid: len(sl[sid]["trades"]) for sid in C.SLEEVES},
                          segregated_oos_sharpe={sc: C.sharpe(seg[sc][-1]) for sc in SCHEMES}, fold_maxdd={sc: C.max_dd(bs[sc]["r"]) for sc in SCHEMES}, skips={sc: bs[sc]["skips"] for sc in SCHEMES}))
    P = {sc: np.concatenate(oos[sc]) for sc in SCHEMES}; Pm, Pv = np.concatenate(oos_mom), np.concatenate(oos_vex)
    d_idx = np.concatenate([np.arange(f["test"][0] // 24, f["test"][1] // 24) for f in C.FOLDS]); Pcash = np.zeros_like(Pm)
    R["folds"] = folds
    # benchmarks over the same OOS days
    Rall_full = asset_returns(allsyms, names9, (C.FOLDS[0]["test"][0], C.FOLDS[-1]["test"][1]))
    ew_bh = Rall_full.loc[d_idx].mean(axis=1).to_numpy(); btc_bh = Rall_full.loc[d_idx, "BTC"].to_numpy()
    def block(r):
        d = C.stats(r); v95, e95, n95 = C.var_es(r, .95); v99, e99, n99 = C.var_es(r, .99)
        d.update(var95=v95, es95=e95, es95_ci=C.es_ci(r, .95), tail_obs95=n95, var99=v99, es99=e99, es99_ci=C.es_ci(r, .99), tail_obs99=n99, gauss_es99=C.gauss_es(r, .99),
                 es7d_95=C.horizon_es(r, 7, .95)[0], worst_7d=C.horizon_es(r, 7, .95)[2], worst_day=float(np.min(r))); return d
    oosres = {sc: block(P[sc]) for sc in SCHEMES}
    oosres.update({"MOM_ONLY": block(Pm), "VEX_ONLY": block(Pv), "EW_BH_9": block(ew_bh), "BTC_BH": block(btc_bh)})
    oosres["CASH"] = dict(days=len(Pcash), total_return=0.0, sharpe=None, max_dd=0.0)
    ci = {}
    for sc in SCHEMES + ["MOM_ONLY", "VEX_ONLY"]:
        r = P.get(sc) if sc in P else (Pm if sc == "MOM_ONLY" else Pv); (lo, hi), pnon = C.sharpe_ci(r); ci[sc] = dict(sharpe=C.sharpe(r), ci95=[lo, hi], p_sharpe_le_0=pnon)
    pb = {sc: C.paired_boot(P[sc], Pm) for sc in SCHEMES}; hp = C.holm({sc: pb[sc]["p_one_sided"] for sc in SCHEMES})
    for sc in SCHEMES: pb[sc]["holm_p"] = hp[sc]
    segp = {sc: np.concatenate(seg[sc]) for sc in SCHEMES}
    R["oos"] = dict(segregated_subbook_approx={sc: dict(sharpe=C.sharpe(segp[sc]), max_dd=C.max_dd(segp[sc]), total_return=float(np.prod(1 + segp[sc]) - 1), es99=C.var_es(segp[sc], .99)[1]) for sc in SCHEMES}, days=int(len(Pm)), results=oosres, sharpe_ci=ci, vs_mom_only=pb, per_scheme_oos_trades={sc: {sid: int(sum(f["oos_trades"][sc][sid] for f in folds)) for sid in C.SLEEVES} for sc in SCHEMES}, standalone_oos_trades={sid: int(sum(f["standalone_trades"][sid] for f in folds)) for sid in C.SLEEVES},
                    sleeve_corr_daily=float(np.corrcoef(Pm, Pv)[0, 1]))
    # ---------- 4. in-sample (weights estimated on all of DEV) and consumed descriptive
    rD = {sid: lab.sleeve(sid, C.DEV)["r"] for sid in C.SLEEVES}; sigD, rhoD = C.estimate(rD[C.MOM], rD[C.VEX]); WD = C.scheme_weights(sigD, rhoD)
    insm = build_scheme_returns(lab, WD, C.DEV); R["in_sample"] = dict(weights=WD, sigma=sigD, rho=rhoD, results={sc: block(insm[sc]["r"]) for sc in SCHEMES},
        sleeves={sid: block(rD[sid]) for sid in C.SLEEVES}, trades={sc: {sid: len(insm[sc]["trades_by"][sid]) for sid in C.SLEEVES} for sc in SCHEMES}, ew_bh_9=block(R9.mean(axis=1).to_numpy()), btc_bh=block(btc.to_numpy()))
    cons = build_scheme_returns(lab, WD, C.CONSUMED); cc = asset_returns(allsyms, names9, C.CONSUMED)
    R["consumed_descriptive"] = dict(note="CONSUMED_LEGACY 2025-11-17..2026-11-17; weights from DEV; descriptive only", results={sc: C.stats(cons[sc]["r"]) for sc in SCHEMES},
        sleeves={sid: C.stats(lab.sleeve(sid, C.CONSUMED)["r"]) for sid in C.SLEEVES}, trades={sc: {sid: len(cons[sc]["trades_by"][sid]) for sid in C.SLEEVES} for sc in SCHEMES},
        ew_bh_9=C.stats(cc.mean(axis=1).to_numpy()), btc_bh=C.stats(cc["BTC"].to_numpy()))
    # ---------- 5. strategy-level correlations (in-sample DEV, w=1 sleeves)
    rm_, rv_ = rD[C.MOM], rD[C.VEX]; ex = C.exposure({sid: (lab.sleeve(sid, C.DEV)["trades"], lab.sleeve(sid, C.DEV)["cap"]) for sid in C.SLEEVES}, {C.MOM: 1.0, C.VEX: 1.0}, C.DEV[0], C.DEV[1], syms)
    inm = np.array([ex["positions"][i * 24:(i + 1) * 24].max() > 0 for i in range(len(rm_))])   # any position that day (either sleeve)
    mom_in = np.array([lab.sleeve(C.MOM, C.DEV)["g"][i] != (lab.sleeve(C.MOM, C.DEV)["g"][i - 1] if i else 1.0) for i in range(len(rm_))]); vex_in = np.array([lab.sleeve(C.VEX, C.DEV)["g"][i] != (lab.sleeve(C.VEX, C.DEV)["g"][i - 1] if i else 1.0) for i in range(len(rv_))])
    both = mom_in & vex_in; bdays = C.DEV[0] // 24 + np.arange(len(rm_)); bt = btc.to_numpy()
    wk = lambda x: pd.Series(x).groupby(np.arange(len(x)) // 7).apply(lambda s: float(np.prod(1 + s) - 1)).to_numpy()
    cc_ = lambda a, b, m=None: float(np.corrcoef(a[m], b[m])[0, 1]) if (m is None or m.sum() > 5) and np.std(a[m] if m is not None else a) > 0 and np.std(b[m] if m is not None else b) > 0 else None
    R["sleeve_correlation"] = dict(daily=cc_(rm_, rv_), weekly=float(np.corrcoef(wk(rm_), wk(rv_))[0, 1]), days_both_active=int(both.sum()), corr_both_active=cc_(rm_, rv_, both),
        btc_worst_decile_days=cc_(rm_, rv_, stressmask), n_btc_stress=int(stressmask.sum()), corr_each_vs_btc=dict(MOM=cc_(rm_, bt), VEX=cc_(rv_, bt)),
        corr_each_vs_ew9=dict(MOM=cc_(rm_, R9.mean(axis=1).to_numpy()), VEX=cc_(rv_, R9.mean(axis=1).to_numpy())),
        same_symbol_overlap_hours=int(ex["same_symbol_overlap"].sum()), same_symbol_overlap_days=int(sum(ex["same_symbol_overlap"][i * 24:(i + 1) * 24].any() for i in range(len(rm_)))),
        days_any_position=int(inm.sum()), days=len(rm_), trades={sid: len(lab.sleeve(sid, C.DEV)["trades"]) for sid in C.SLEEVES},
        both_lose_on_btc_worst_decile=float(np.mean((rm_[stressmask] < 0) & (rv_[stressmask] < 0))), either_lose_on_btc_worst_decile=float(np.mean((rm_[stressmask] < 0) | (rv_[stressmask] < 0))),
        both_flat_on_btc_worst_decile=float(np.mean((rm_[stressmask] == 0) & (rv_[stressmask] == 0))))
    # ---------- 6. exposure / risk-budget utilisation (in-sample DEV timelines with in-sample weights)
    expo = {}; EX = {}
    for sc in SCHEMES:
        w = WD[sc]; e = C.exposure({sid: (insm[sc]["trades_by"][sid], A.CAP) for sid in C.SLEEVES}, {sid: 1.0 for sid in C.SLEEVES}, C.DEV[0], C.DEV[1], syms, eq=insm[sc]["eqh"]); EX[sc] = e
        prm = C.scheme_params(sc, w); capr = prm["total"]
        expo[sc] = dict(weights=w, cash_weight=1 - sum(w.values()), limits=dict(open_risk=capr, positions=prm["max_pos"], single_asset=prm["single_cap"], gross=prm["gross_cap"], risk_per_trade=prm["per_trade"]),
            peak_open_risk=float(e["open_risk"].max()), mean_open_risk=float(e["open_risk"].mean()), p95_open_risk=float(np.quantile(e["open_risk"], .95)), peak_util=float(e["open_risk"].max() / capr), mean_util=float(e["open_risk"].mean() / capr),
            frac_hours_any_position=float((e["positions"] > 0).mean()), peak_gross=float(e["gross"].max()), mean_gross=float(e["gross"].mean()), peak_positions=int(e["positions"].max()), peak_single_asset=float(e["max_single_asset"].max()),
            frac_hours_invested_2022=float((e["positions"][A.hr("2022-01-01") - C.DEV[0]: A.hr("2022-12-31") - C.DEV[0]] > 0).mean()), mean_gross_2022=float(e["gross"][A.hr("2022-01-01") - C.DEV[0]: A.hr("2022-12-31") - C.DEV[0]].mean()),
            hours_single_asset_gt_limit=int((e["max_single_asset"] > prm["single_cap"] + 1e-9).sum()), hours_gross_gt_limit=int((e["gross"] > prm["gross_cap"] + 1e-9).sum()), hours_positions_gt_limit=int((e["positions"] > prm["max_pos"]).sum()),
            hours_same_symbol_overlap=int(e["same_symbol_overlap"].sum()), hours_open_risk_gt_limit=int((e["open_risk"] > capr + 1e-9).sum()), hours_open_risk_gt_1p05x=int((e["open_risk"] > 1.05 * capr).sum()),
            hours_single_asset_gt_1p05x=int((e["max_single_asset"] > 1.05 * prm["single_cap"]).sum()), hours_gross_gt_1p05x=int((e["gross"] > 1.05 * prm["gross_cap"]).sum()), skips=insm[sc]["skips"],
            max_trade_risk_frac_reserved=float(max((t["reserved_risk"] / t["E_entry"] for t in insm[sc]["trades"]), default=0.0)))
    R["exposure_and_budget"] = expo; R["segregated_exhibit_run1_corrected_normalisation"] = seg_exposure(lab, WD, C.DEV)
    # hypothetical shocks on the realised timeline
    shock = {}
    for sc in SCHEMES:
        e = EX[sc]
        shock[sc] = dict(gap20_all_open_loss_max=float(0.20 * e["gross"].max()), gap20_vs_planned_open_risk_max=float((0.20 * e["gross"]).max() / max(e["open_risk"].max(), 1e-12)),
                         stop_fill_minus_2R_all_open=float(2 * e["open_risk"].max()), stop_fill_minus_1p5R_all_open=float(1.5 * e["open_risk"].max()),
                         all_open_hit_planned_stop=float(e["open_risk"].max()))
    R["hypothetical_shocks"] = dict(label="HYPOTHETICAL arithmetic on realised exposure timelines (not measurements)", results=shock)
    # ---------- 7. tail concentration (worst 5 % days, in-sample and OOS pooled)
    def tailc(r, contrib):
        k = max(1, int(math.ceil(0.05 * len(r)))); idx = np.argsort(r)[:k]; tot = sum(c[idx].sum() for c in contrib.values())
        return dict(n_days=int(k), threshold=float(np.sort(r)[k - 1]), sleeve_share={sid: float(contrib[sid][idx].sum() / tot) if tot != 0 else None for sid in contrib},
                    sleeve_sum={sid: float(contrib[sid][idx].sum()) for sid in contrib}, both_negative_share=float(np.mean([(contrib[C.MOM][i] < 0) and (contrib[C.VEX][i] < 0) for i in idx])))
    R["tail_concentration"] = dict(in_sample={sc: tailc(insm[sc]["r"], insm[sc]["contrib"]) for sc in SCHEMES}, oos={sc: tailc(P[sc], {sid: np.concatenate(oos_contrib[sc][sid]) for sid in C.SLEEVES}) for sc in SCHEMES})
    # by asset: exit-day realised pnl of the trades on worst-5% days (in-sample EW)
    r_ew = insm["EW"]["r"]; kk = max(1, int(math.ceil(0.05 * len(r_ew)))); worst = set(np.argsort(r_ew)[:kk].tolist()); by_asset = {}; by_asset_all = {}
    for sid in C.SLEEVES:
        for t in insm["EW"]["trades_by"][sid]:
            di = (t["exit_hour"] - C.DEV[0]) // 24; by_asset_all[t["symbol"]] = by_asset_all.get(t["symbol"], 0) + t["pnl"] / A.CAP
            if di in worst: by_asset[t["symbol"]] = by_asset.get(t["symbol"], 0) + t["pnl"] / A.CAP
    R["tail_concentration"]["asset_realised_pnl_on_worst5_days_EW_insample"] = by_asset; R["tail_concentration"]["asset_realised_pnl_total_EW"] = by_asset_all
    # ---------- 8. cost sensitivity (pooled OOS; weights fixed from base-cost estimation)
    costs = {"0x": (0.0, 0.0), "1x": C.BASE, "2x": (0.002, 0.001), "3x": (0.003, 0.0015), "stressA": C.STRESS_A, "stressB": C.STRESS_B}; cs = {}
    for cn, cost in costs.items():
        pooled = {sc: [] for sc in SCHEMES}; pm, pv = [], []
        for fd, fr in zip(C.FOLDS, folds):
            bs = build_scheme_returns(lab, fr["weights"], fd["test"], cost)
            for sc in SCHEMES: pooled[sc].append(bs[sc]["r"])
            pm.append(lab.sleeve(C.MOM, fd["test"], cost)["r"]); pv.append(lab.sleeve(C.VEX, fd["test"], cost)["r"])
        cs[cn] = dict(cost=cost, **{sc: dict(sharpe=C.sharpe(np.concatenate(pooled[sc])), total_return=float(np.prod(1 + np.concatenate(pooled[sc])) - 1), max_dd=C.max_dd(np.concatenate(pooled[sc]))) for sc in SCHEMES},
                      MOM_ONLY=dict(sharpe=C.sharpe(np.concatenate(pm)), total_return=float(np.prod(1 + np.concatenate(pm)) - 1)), VEX_ONLY=dict(sharpe=C.sharpe(np.concatenate(pv)), total_return=float(np.prod(1 + np.concatenate(pv)) - 1)))
    R["cost_sensitivity"] = cs
    # ---------- 9. turnover and rebalancing
    turn = {}
    for sid in C.SLEEVES:
        trs = lab.sleeve(sid, C.DEV)["trades"]; yrs = (C.DEV[1] - C.DEV[0]) / 24 / 365
        turn[sid] = dict(trades_per_year=len(trs) / yrs, traded_notional_per_year_over_capital=float(sum(t["buy_notional"] + t["sell_notional"] for t in trs) / A.CAP / yrs),
                         fees_over_gross_pnl=float(sum(t["fees"] for t in trs) / max(sum(abs(t["pnl"]) for t in trs), 1e-9)))
    reb = {}
    for sc in SCHEMES:
        w = WD[sc]; rr = {sid: rD[sid] for sid in C.SLEEVES}; reb[sc] = {}
        for lab_k, every in (("daily", 1), ("monthly30d", 30), ("quarterly91d", 91), ("semiannual182d", 182), ("never", None)):
            rp, tr_ = C.rebalance_path(rr, w, every); reb[sc][lab_k] = dict(sharpe=C.sharpe(rp), total_return=float(np.prod(1 + rp) - 1), max_dd=C.max_dd(rp), capital_transfer_per_year=tr_)
        reb[sc]["market_turnover_per_year_over_equity"] = float(sum(w[s] * turn[s]["traded_notional_per_year_over_capital"] for s in C.SLEEVES))
    R["turnover_rebalancing"] = dict(sleeves=turn, schemes=reb, note="rebalancing moves capital between segregated sub-books (cash transfers), not market trades; return-level model on DEV w=1 sleeve returns")
    # ---------- 10. liquidity / capacity
    cap = {}
    for sid in C.SLEEVES:
        ratios = []
        for t in lab.sleeve(sid, C.DEV)["trades"]:
            qm = syms[t["symbol"]].qmed168[t["entry_hour"] - 1]
            if np.isfinite(qm) and t["qty"] * t["entry_fill"] > 0: ratios.append(0.01 * qm / (t["qty"] * t["entry_fill"]))
        ratios = np.array(ratios); cap[sid] = dict(n=int(len(ratios)), k_p05=float(np.quantile(ratios, .05)), k_p50=float(np.median(ratios)), frac_cap_binding_at_10k=float(np.mean(ratios < 1.05)),
            account_size_p05_if_sleeve_full=float(A.CAP * np.quantile(ratios, .05)))
    sch_cap = {}
    for sc in SCHEMES:
        ratios = np.array([0.01 * syms[t["symbol"]].qmed168[t["entry_hour"] - 1] / (t["qty"] * t["entry_fill"]) for t in insm[sc]["trades"] if np.isfinite(syms[t["symbol"]].qmed168[t["entry_hour"] - 1])])
        sch_cap[sc] = dict(n=int(len(ratios)), k_p05=float(np.quantile(ratios, .05)), k_p50=float(np.median(ratios)), frac_trades_cap_binding_at_10k=float(np.mean(ratios < 1.05)), account_size_p05=float(A.CAP * np.quantile(ratios, .05)))
    R["liquidity_capacity"] = dict(sleeves_standalone=cap, schemes=sch_cap, participation_cap=0.01, note="ratio = (1% of median 168h quote volume)/(entry notional) at $10k; account size scales trade size linearly; impact beyond the 1% cap is not modelled; real fills not observed")
    # ---------- 11. regimes (BTC regime label on the day, Stage 02 definition) and cash share
    lab_r = A.btc_regime_by_day(syms)[C.DEV[0] // 24: C.DEV[1] // 24]; rg = {}
    for lbl in sorted(set(lab_r)):
        m = lab_r == lbl; rg[lbl] = dict(days=int(m.sum()), **{sid: dict(sum_ret=float(rD[sid][m].sum()), mean_ret=float(rD[sid][m].mean()), active_days=int((rD[sid][m] != 0).sum())) for sid in C.SLEEVES},
                                          EW=dict(sum_ret=float(insm["EW"]["r"][m].sum())), CONS=dict(sum_ret=float(insm["CONS"]["r"][m].sum())), btc=dict(sum_ret=float(bt[m].sum())))
    sg = {sc: dict(DR=float(sum(WD[sc][s_] * sigD[s_] for s_ in C.SLEEVES) / np.std(insm[sc]["r"], ddof=1)), risk_contrib=C.risk_contrib({s_: WD[sc][s_] for s_ in C.SLEEVES}, sigD, rhoD)) for sc in SCHEMES}
    R["diversification"] = dict(regime_attribution=rg, ratios=sg, frac_days_flat_both_sleeves=float(np.mean((rD[C.MOM] == 0) & (rD[C.VEX] == 0))), frac_days_flat_mom=float(np.mean(rD[C.MOM] == 0)), frac_days_flat_vex=float(np.mean(rD[C.VEX] == 0)))
    # ---------- 12. estimation-error sensitivity
    rng = np.random.default_rng(C.SEED); n = len(rD[C.MOM]); idx = C._blocks(n, 500, C.BLOCK, rng); bw = {"IV": [], "RB": []}
    for ix in idx:
        s_, r_ = C.estimate(rD[C.MOM][ix], rD[C.VEX][ix]); bw["IV"].append(C.w_invvol(s_)[C.MOM]); bw["RB"].append(C.w_riskbudget(s_, r_)[C.MOM])
    q = lambda a: dict(mean=float(np.mean(a)), sd=float(np.std(a)), p05=float(np.quantile(a, .05)), p95=float(np.quantile(a, .95)))
    grid = []
    for rho in (0.0, 0.25, 0.5, 0.75, 0.9):
        for vm in (0.7, 1.0, 1.3):
            sg2 = {C.MOM: sigD[C.MOM], C.VEX: sigD[C.VEX] * vm}; w_iv = C.w_invvol(sg2); w_rb = C.w_riskbudget(sg2, rho)
            def pv(w): return math.sqrt((w[C.MOM] * sg2[C.MOM]) ** 2 + (w[C.VEX] * sg2[C.VEX]) ** 2 + 2 * w[C.MOM] * w[C.VEX] * rho * sg2[C.MOM] * sg2[C.VEX]) * math.sqrt(365)
            grid.append(dict(rho=rho, vex_vol_mult=vm, IV_wMOM=w_iv[C.MOM], RB_wMOM=w_rb[C.MOM], ann_vol_EW=pv(C.w_equal()), ann_vol_IV=pv(w_iv), ann_vol_RB=pv(w_rb), ann_vol_CONS=pv(C.CONS_W)))
    hair = {}
    for h in (0.0, 0.5, 1.0):
        hh = {}
        for sc in SCHEMES:
            rp = [0.0] * 0; parts = {sid: np.concatenate(oos_mom if sid == C.MOM else oos_vex) for sid in C.SLEEVES}
            rp = sum(WD[sc][sid] * (parts[sid] - h * parts[sid].mean()) for sid in C.SLEEVES); hh[sc] = C.sharpe(rp)
        hair[str(h)] = hh
    R["estimation_sensitivity"] = dict(bootstrap_weights_wMOM=dict(IV=q(bw["IV"]), RB=q(bw["RB"])), grid=grid, sleeve_mean_haircut_oos_sharpe_approx_daily_rebalanced=hair,
        insample_estimates=dict(sigma_daily=sigD, rho=rhoD, sharpe=dict(MOM=C.sharpe(rD[C.MOM]), VEX=C.sharpe(rD[C.VEX]))), fold_weight_range={sc: [min(f["weights"][sc][C.MOM] for f in folds), max(f["weights"][sc][C.MOM] for f in folds)] for sc in SCHEMES})
    # ---------- 13. historical stress windows (in-sample series)
    def win_ret(r, a, b):
        i0, i1 = (pd.Timestamp(a, tz="UTC").value // 86_400_000_000_000 - (E.T0_MS // 86_400_000) - C.DEV[0] // 24), (pd.Timestamp(b, tz="UTC").value // 86_400_000_000_000 - (E.T0_MS // 86_400_000) - C.DEV[0] // 24)
        seg = r[max(i0, 0): i1]; return dict(total=float(np.prod(1 + seg) - 1), max_dd=C.max_dd(seg), days=int(len(seg)))
    stw = {}
    for sc in SCHEMES:
        r = insm[sc]["r"]; h7 = [(np.prod(1 + r[i:i + 7]) - 1, i) for i in range(len(r) - 6)]; h30 = [(np.prod(1 + r[i:i + 30]) - 1, i) for i in range(len(r) - 29)]
        w7, w30 = min(h7), min(h30)
        stw[sc] = dict(worst_day=float(r.min()), worst_day_date=day(C.DEV[0] + 24 * int(r.argmin())), worst_7d=float(w7[0]), worst_7d_start=day(C.DEV[0] + 24 * w7[1]), worst_30d=float(w30[0]), worst_30d_start=day(C.DEV[0] + 24 * w30[1]),
                       luna_2022_05_01_to_06_30=win_ret(r, "2022-05-01", "2022-06-30"), ftx_2022_11_01_to_12_15=win_ret(r, "2022-11-01", "2022-12-15"), bear_2022_full=win_ret(r, "2022-01-01", "2022-12-31"))
    stw["EW_BH_9"] = dict(luna=win_ret(R9.mean(axis=1).to_numpy(), "2022-05-01", "2022-06-30"), ftx=win_ret(R9.mean(axis=1).to_numpy(), "2022-11-01", "2022-12-15"), bear_2022=win_ret(R9.mean(axis=1).to_numpy(), "2022-01-01", "2022-12-31"))
    stw["BTC_BH"] = dict(luna=win_ret(bt, "2022-05-01", "2022-06-30"), ftx=win_ret(bt, "2022-11-01", "2022-12-15"), bear_2022=win_ret(bt, "2022-01-01", "2022-12-31"))
    # sleeve-failure arithmetic: each trade at -0.2R
    fail = {}; yrs = (C.DEV[1] - C.DEV[0]) / 24 / 365
    for sc in SCHEMES:
        fail[sc] = {sid: float(sum(-0.2 * t["reserved_risk"] / t["E_entry"] for t in insm[sc]["trades_by"][sid]) / yrs) for sid in C.SLEEVES}
    R["stress"] = dict(historical=stw, sleeve_expectancy_minus_0p2R_per_year_frac_equity_uncompounded_HYPOTHETICAL=fail)
    # ---------- 14. V-gates (predeclared in the plan)
    h06 = json.loads((ROOT / "docs/strategy-specs/stage06/stage06_holdout_results.json").read_text()); h04 = json.loads((ROOT / "docs/strategy-specs/STAGE_04_HANDOFF.json").read_text())
    hb = {sid: h06["results"][f"{sid}|BASELINE"]["dev"]["sharpe"] for sid in C.SLEEVES}
    best_sc = max(SCHEMES, key=lambda s: ci[s]["sharpe"]); gates = {}
    for sc in SCHEMES:
        gates[sc] = dict(V1_sleeves_validated=bool(all(hb[s] > 0 for s in C.SLEEVES if WD[sc][s] > 0)), V1_detail=hb, V2_forward_evidence=False, V3_venue_and_observed_costs=False, V4_prereg_frozen_adjudicated=False,
                         V5_oos_sharpe_ci_lower_gt_0=bool(ci[sc]["ci95"][0] > 0), V5_oos_maxdd_ok=bool(oosres[sc]["max_dd"] >= -0.15),
                         V6_stage04_gates_open_now=bool(any(v.get("assets_passing") for v in h04["strategy_suitability"].values())),
                         V6_detail={k: v.get("now") for k, v in h04["strategy_suitability"].items()})
        gates[sc]["ALL_PASS"] = bool(gates[sc]["V1_sleeves_validated"] and gates[sc]["V2_forward_evidence"] and gates[sc]["V3_venue_and_observed_costs"] and gates[sc]["V4_prereg_frozen_adjudicated"]
                                     and gates[sc]["V5_oos_sharpe_ci_lower_gt_0"] and gates[sc]["V5_oos_maxdd_ok"] and gates[sc]["V6_stage04_gates_open_now"])
    R["validation_gates"] = gates; R["determination"] = "ALLOCATION_PERMITTED" if any(g["ALL_PASS"] for g in gates.values()) else "NO_ALLOCATION"
    R["counts"] = dict(schemes=4, benchmarks=5, simulations=lab.n_sims, folds=5, oos_days=int(len(Pm)), dev_days=int(len(rD[C.MOM])), bootstrap_reps=C.REPS)
    R["holdout_assets_audit"] = {k: {kk: vv for kk, vv in v.items() if kk in ("rows", "first", "last", "gaps", "n_gaps")} for k, v in haud.items()}
    (OUT / "stage07_results.json").write_text(json.dumps(clean(R), indent=1))
    print("determination", R["determination"], "sims", lab.n_sims)
    for sc in SCHEMES: print(sc, {k: round(v, 3) for k, v in WD[sc].items()}, "OOS sharpe", round(ci[sc]["sharpe"], 3), [round(x, 3) for x in ci[sc]["ci95"]], "maxDD", round(oosres[sc]["max_dd"], 3), "ES99", round(oosres[sc]["es99"], 4))
    print("MOM_ONLY", round(ci["MOM_ONLY"]["sharpe"], 3), "VEX_ONLY", round(ci["VEX_ONLY"]["sharpe"], 3), "sleeve corr", round(R["oos"]["sleeve_corr_daily"], 3))


if __name__ == "__main__": main()
