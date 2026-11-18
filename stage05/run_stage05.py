"""Stage 05 runner: PYTHONPATH=. scripts/lab python -m stage05.run_stage05   (research only; no orders; deterministic)."""
from __future__ import annotations
import json, pickle, subprocess, sys
from pathlib import Path
import numpy as np, pandas as pd
from . import factors as Fm, evaluate as V

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "docs" / "strategy-specs" / "stage05"
PRIM = Fm.PRIMARY; ALLK = PRIM + Fm.EXPERIMENTAL
PRIOR_W = dict(MOM=0.30, TREND=0.25, VOL=0.15, LIQ=0.10, VALUE=0.20)     # initial HYPOTHESIS weights (not estimated)
COMPLEXITY = dict(EQ=0, PRIOR=0, EQ_TRAINPOS=5, ICP=5, NNLS=6, COND=15)
END = dict(train=V.T("2024-11-17"), val=V.T("2025-11-17"), legacy=V.T("2026-11-18"))
ND = 0   # count of statistical evaluations performed (multiplicity disclosure)

def dr(split, h=V.H, idx=None):
    lo, hi = V.SPL[split]; hi = END[split] - pd.Timedelta(days=h + 1); lo = max(lo, V.TRAIN_FIRST_FULL) if split == "train" else lo
    return idx[(idx >= lo) & (idx <= hi)]

def ic_table(Z, Y, ks, dates, seed=V.SEED):
    global ND; out = {}; ser = {}
    for k in ks:
        ic = Fm.sp_ic(Z[k].loc[dates], Y.loc[dates]); ser[k] = ic; out[k] = V.ic_stats(ic, seed); ND += 1
    return out, ser

def by_tag(ic: pd.Series, col: pd.Series):
    t = col.reindex(ic.index); r = {}
    for g in sorted(set(t.dropna())):
        x = ic[t == g]; r[g] = dict(n_days=int(len(x)), mean_ic=float(x.mean()), share_pos=float((x > 0).mean())) if len(x) >= 20 else dict(n_days=int(len(x)), mean_ic=None, note="<20 days")
    return r

def run():
    global ND
    P, meta, mv = pickle.loads((ROOT / "data" / "s5panel.pkl").read_bytes()) if (ROOT / "data" / "s5panel.pkl").exists() else (*Fm.load_panel(), Fm.load_mvrv())
    idx = P["c"].index; raw, Z = Fm.build_z(P, mv); tags = V.btc_regime_tags(P)
    Y = {h: Fm.targets(P, h) for h in (1, 7, 30)}; Y7 = Y[7]
    res = dict(created="2026-11-18", panel=dict(first=str(idx[0].date()), last_complete=str(P["c"].dropna(how="all").index[-1].date()), assets=Fm.ASSETS, missing_days=int(P["c"].isna().all(axis=1).sum()), snapshot=meta["snapshot"]))
    dtr, dva = dr("train", idx=idx), dr("val", idx=idx)
    res["dates"] = dict(train=[str(dtr[0].date()), str(dtr[-1].date()), len(dtr)], val=[str(dva[0].date()), str(dva[-1].date()), len(dva)])

    # ---------- 1. single-factor IC: train, validation (h=7 primary), other horizons descriptive
    ic_tr, ser_tr = ic_table(Z, Y7, ALLK, dtr); ic_va, ser_va = ic_table(Z, Y7, ALLK, dva)
    hz = {}
    for h in (1, 30):
        a, _ = ic_table(Z, Y[h], ALLK, dr("train", h, idx)); b, _ = ic_table(Z, Y[h], ALLK, dr("val", h, idx)); hz[h] = dict(train={k: a[k]["mean"] for k in ALLK}, val={k: b[k]["mean"] for k in ALLK})
    status = {}
    for k in ALLK:
        t, v = ic_tr[k], ic_va[k]
        status[k] = "EXCLUDED" if not (t["mean"] > 0 and v["mean"] > 0) else ("SUPPORTED" if v["lo95"] > 0 else "EXPERIMENTAL_WEAK")
    res["factor_ic"] = dict(h7_train=ic_tr, h7_val=ic_va, other_horizons_mean_ic=hz, status_rule="SUPPORTED: train IC>0 & val 95% lower>0; EXPERIMENTAL_WEAK: both means>0, val lower<=0; EXCLUDED: otherwise", status=status)

    # ---------- 2. dependence (train sample; plus val for stability)
    dep = {}
    for nm, ds in (("train", dtr), ("val", dva)):
        M = V.avg_cs_corr(Z, PRIM, ds); Mi = np.corrcoef(pd.DataFrame(ser_tr if nm == "train" else ser_va).dropna()[PRIM].to_numpy().T)
        ev = np.sort(np.linalg.eigvalsh(M))[::-1]; vif = np.diag(np.linalg.inv(M))
        dep[nm] = dict(cs_rank_corr=pd.DataFrame(M, PRIM, PRIM).round(3).to_dict(), ic_series_corr=pd.DataFrame(Mi, PRIM, PRIM).round(3).to_dict(), eigenvalues=ev.round(3).tolist(),
                       effective_n_factors=float(ev.sum() ** 2 / (ev ** 2).sum()), vif=dict(zip(PRIM, vif.round(2).tolist())), condition_number=float(ev[0] / ev[-1]))
    pers = {k: dict(zip(["rank_autocorr_lag7", "top3_retention_lag7"], V.persistence(Z, k, dtr))) for k in ALLK}
    resid = {}
    for k in PRIM:
        oth = [o for o in PRIM if o != k]; Rk = V.residualise(Z, k, oth, dtr.union(dva))
        resid[k] = dict(train=V.ic_stats(Fm.sp_ic(Rk.loc[dtr], Y7.loc[dtr]))["mean"], val=V.ic_stats(Fm.sp_ic(Rk.loc[dva], Y7.loc[dva]))["mean"]); ND += 2
    res["dependence"] = dict(by_split=dep, persistence=pers, residual_ic=resid)

    # ---------- 3. candidate weights: FIT ON TRAIN ONLY
    ic_trp = {k: ser_tr[k] for k in PRIM}; wicp = V.ic_weights(ic_trp)
    pos = [k for k in PRIM if ic_tr[k]["mean"] > 0]; weqp = {k: (1 / len(pos) if k in pos else 0.0) for k in PRIM} if pos else {k: 0.0 for k in PRIM}
    wn, lam, cvres = V.fit_nnls_cv(Z, Y7, dtr, PRIM); wnn = dict(zip(PRIM, map(float, wn)))
    wc = V.cond_weights(Z, Y7, tags, list(dtr), PRIM)
    W = dict(EQ={k: 0.2 for k in PRIM}, PRIOR=PRIOR_W, EQ_TRAINPOS=weqp, ICP=wicp, NNLS=wnn)
    res["weights"] = dict(candidates={k: {a: round(b, 4) for a, b in v.items()} for k, v in W.items()}, COND={r: {a: (round(b, 4) if not a.startswith("_") else b) for a, b in v.items()} for r, v in wc.items()},
                          nnls_cv=dict(chosen_lambda=lam, cv_mean_ic={str(k): v for k, v in cvres.items()}), prior_note="PRIOR = initial hypothesis weights, not estimated",
                          cond_shrink_k=250, cond_min_days=60, estimation_sample=res["dates"]["train"])

    # ---------- 4. validation comparison
    S = {n: Fm.composite(Z, w) for n, w in W.items()}; S["COND"] = V.composite_cond(Z, wc, tags, idx, PRIM)
    cand = {}; icv = {}
    for n in S:
        a = Fm.sp_ic(S[n].loc[dtr], Y7.loc[dtr]); b = Fm.sp_ic(S[n].loc[dva], Y7.loc[dva]); icv[n] = b
        cand[n] = dict(complexity=COMPLEXITY[n], train=V.ic_stats(a), val=V.ic_stats(b)); ND += 2
    for k in PRIM: icv[k] = ser_va[k]
    best = max(cand, key=lambda n: cand[n]["val"]["mean"])
    for n in cand: cand[n]["val_vs_best_diff"] = V.boot_diff(icv[best], icv[n]) if n != best else None; ND += 1
    comparable = [n for n in cand if n == best or (cand[n]["val_vs_best_diff"]["lo95"] <= 0 <= cand[n]["val_vs_best_diff"]["hi95"])]
    chosen = min(comparable, key=lambda n: (COMPLEXITY[n], list(COMPLEXITY).index(n)))
    mom_only = V.boot_diff(icv[best], icv["MOM"]); eq_vs = {n: V.boot_diff(icv[n], icv["EQ"]) for n in cand if n != "EQ"}
    res["candidates_ic"] = cand; res["selection"] = dict(best_by_val_mean_ic=best, comparable_to_best=comparable, chosen=chosen, rule="lowest complexity among candidates whose paired-bootstrap 95% CI of (best - cand) contains 0",
                                                         best_vs_MOM_only=mom_only, vs_EQ=eq_vs, best_single_factor_val_ic={k: ic_va[k]["mean"] for k in PRIM})

    # ---------- 5. frozen spec (unsupported factors -> weight 0 / experimental), then FREEZE before any consumed-window access
    wch = (wc if chosen == "COND" else W[chosen])
    def freeze_w(w):
        w = {k: (0.0 if status[k] == "EXCLUDED" else v) for k, v in w.items() if not k.startswith("_")}; s = sum(w.values()); return {k: v / s for k, v in w.items()} if s > 0 else w
    frozen_w = {r: freeze_w(w) for r, w in wch.items()} if chosen == "COND" else freeze_w(wch)
    fz = dict(model_id="CRY-MFS-201", version="0.1.0-draft", chosen_candidate=chosen, factor_signs=Fm.SIGN_RATIONALE, params=Fm.PARAMS, weights=frozen_w, composite_experimental=Fm.EXPERIMENTAL,
              factor_status=status, horizon_days=V.H, topk=V.K_TOP, rebalance_days=7, cost_per_side=V.COST_SIDE, seed=V.SEED, regime_tag_source="BTC Stage 04 direction rule (>=4/5 votes)")
    fz["sha256"] = V.sig(fz); OUT.mkdir(parents=True, exist_ok=True); (OUT / "frozen_model.json").write_text(json.dumps(fz, indent=1))
    res["frozen"] = fz
    Sf = (V.composite_cond(Z, {r: dict(w, _n=0) for r, w in frozen_w.items()}, tags, idx, PRIM) if chosen == "COND" else Fm.composite(Z, frozen_w))
    fz_val = V.ic_stats(Fm.sp_ic(Sf.loc[dva], Y7.loc[dva])); res["frozen_val_ic_POST_SELECTION_optimistic"] = fz_val; ND += 1

    # ---------- 6. portfolio: cost & turnover (train/val), per factor and candidates
    port = {}
    for nm, Sx in list(S.items()) + [("FROZEN", Sf)] + [(k, Z[k]) for k in ALLK]:
        port[nm] = {sp: V.port_summary(V.portfolio_series(Sx, P, list(d), cost=V.COST_SIDE)) for sp, d in (("train", dtr), ("val", dva))}; ND += 2
    res["portfolio_top3_weekly"] = port
    cs = {}
    for c in (0.0, 0.0015, 0.003, 0.006):
        df = V.portfolio_series(Sf, P, list(dva), cost=c); cs[f"{int(c*1e4)}bp_per_side"] = V.port_summary(df, c)["mean_excess_net_per_week"]
    res["cost_sensitivity_frozen_val_mean_excess_net_per_week"] = cs

    # ---------- 7. regime stability (BTC tags): factors, candidates, frozen
    stab = {}
    for nm, (st, sv) in {**{k: (ser_tr[k], ser_va[k]) for k in ALLK}, "FROZEN": (Fm.sp_ic(Sf.loc[dtr], Y7.loc[dtr]), Fm.sp_ic(Sf.loc[dva], Y7.loc[dva])), "EQ": (Fm.sp_ic(S["EQ"].loc[dtr], Y7.loc[dtr]), icv["EQ"])}.items():
        stab[nm] = dict(direction=dict(train=by_tag(st, tags.direction), val=by_tag(sv, tags.direction)), structure=dict(train=by_tag(st, tags.structure), val=by_tag(sv, tags.structure)),
                        vol=dict(train=by_tag(st, tags.vol), val=by_tag(sv, tags.vol)),
                        year=by_tag(pd.concat([st, sv]), pd.Series(pd.concat([st, sv]).index.year.astype(str), index=pd.concat([st, sv]).index)),
                        train_halves=dict(first=float(st.iloc[:len(st) // 2].mean()), second=float(st.iloc[len(st) // 2:].mean())))
    res["regime_stability"] = stab
    res["regime_day_counts"] = dict(train=dict(tags.direction.loc[dtr].value_counts()), val=dict(tags.direction.loc[dva].value_counts()))

    # ---------- 8. exploratory ablation of frozen composite (hypothesis-generating; NOT a test)
    abl = {}
    base_w = frozen_w if chosen != "COND" else {k: float(np.mean([frozen_w[r][k] for r in frozen_w])) for k in PRIM}
    for lab, w in [("ALL", base_w)] + [(f"drop_{k}", {a: (0.0 if a == k else b) for a, b in base_w.items()}) for k in PRIM] + [("add_VALUE_MVRV_0.2", dict({a: b * 0.8 for a, b in base_w.items()}, VALUE_MVRV=0.2)),
                                                                                                                              ("MOM_only", {"MOM": 1.0}), ("MOM+TREND", {"MOM": .5, "TREND": .5})]:
        s = sum(w.values()); w = {k: v / s for k, v in w.items()} if s > 0 else w; Sx = Fm.composite(Z, w)
        abl[lab] = dict(weights={k: round(v, 3) for k, v in w.items() if v > 0}, train_ic=V.ic_stats(Fm.sp_ic(Sx.loc[dtr], Y7.loc[dtr]))["mean"], val_ic=V.ic_stats(Fm.sp_ic(Sx.loc[dva], Y7.loc[dva]))["mean"],
                        val_net_excess_per_week=V.port_summary(V.portfolio_series(Sx, P, list(dva)))["mean_excess_net_per_week"]); ND += 3
    res["ablation_exploratory"] = abl

    # ---------- 9. consumed-window descriptive (AFTER freeze; frozen model and two comparators only; no inference)
    dlg = dr("legacy", idx=idx); leg = {}
    for nm, Sx in (("FROZEN", Sf), ("EQ", S["EQ"]), ("MOM_only", Z["MOM"])):
        leg[nm] = dict(ic=V.ic_stats(Fm.sp_ic(Sx.loc[dlg], Y7.loc[dlg])), portfolio=V.port_summary(V.portfolio_series(Sx, P, list(dlg)))); ND += 2
    res["consumed_legacy_descriptive"] = dict(status="CONSUMED_LEGACY: descriptive only, not evidence of skill; frozen before access; no changes made afterwards", window=[str(dlg[0].date()), str(dlg[-1].date()), len(dlg)], results=leg)

    # ---------- 9b. robustness (validation/train; legacy per-factor is DIAGNOSTIC ONLY - the frozen model is not changed after it)
    rob = {}
    def ic_blk(ic, b):
        x = ic.dropna().to_numpy(); m = x[V.block_idx(len(x), block=b)].mean(axis=1); return dict(block=b, mean=float(x.mean()), lo95=float(np.quantile(m, .025)), hi95=float(np.quantile(m, .975)))
    icf_v = Fm.sp_ic(Sf.loc[dva], Y7.loc[dva]); icf_t = Fm.sp_ic(Sf.loc[dtr], Y7.loc[dtr])
    rob["block_length_sensitivity_val"] = {nm: [ic_blk(ic, b) for b in (14, 30, 60, 90)] for nm, ic in (("VOL", ser_va["VOL"]), ("FROZEN", icf_v), ("EQ", icv["EQ"]))}
    acf = lambda x, l: float(x.autocorr(l)); rob["ic_autocorr"] = {nm: {f"lag{l}": acf(ic, l) for l in (1, 7, 14, 30)} for nm, ic in (("VOL", ser_va["VOL"]), ("FROZEN", icf_v))}
    stat = pd.DataFrame([raw["VOL"].loc[dtr].mean()] * len(idx), index=idx)                       # static rank by TRAIN-mean realised vol (constant over time)
    Zs = Fm.cs_normalise(stat, -1)
    rob["VOL_static_vs_dynamic"] = dict(static_train_ic=V.ic_stats(Fm.sp_ic(Zs.loc[dtr], Y7.loc[dtr]))["mean"], static_val_ic=V.ic_stats(Fm.sp_ic(Zs.loc[dva], Y7.loc[dva]))["mean"],
                                        dynamic_train_ic=ic_tr["VOL"]["mean"], dynamic_val_ic=ic_va["VOL"]["mean"], static_asset_order_low_to_high_vol=[a for a in stat.iloc[0].sort_values().index])
    loao = {}
    for a in Fm.ASSETS:
        keep = [x for x in Fm.ASSETS if x != a]; Zl = {k: Fm.cs_normalise(raw[k][keep], Fm.SIGN_RATIONALE[k]) for k in ("MOM", "VOL", "VALUE")}
        Sl = Fm.composite(Zl, {k: 1 / 3 for k in Zl}); Yl = Y7[keep]
        loao[a] = dict(VOL_val=float(Fm.sp_ic(Zl["VOL"].loc[dva], Yl.loc[dva]).mean()), VOL_train=float(Fm.sp_ic(Zl["VOL"].loc[dtr], Yl.loc[dtr]).mean()),
                       FROZEN_val=float(Fm.sp_ic(Sl.loc[dva], Yl.loc[dva]).mean()), FROZEN_train=float(Fm.sp_ic(Sl.loc[dtr], Yl.loc[dtr]).mean())); ND += 4
    rob["leave_one_asset_out"] = loao
    # point-in-time truncation test: recompute factors from data truncated at t and compare with the full-sample values at t
    pit = []
    for d in [idx[i] for i in (400, 800, 1200, 1600, 1900)]:
        Pt = {k: (v.loc[:d] if hasattr(v, "loc") else v) for k, v in P.items() if k in ("o", "h", "l", "c", "q", "nbar")}; _, Zt = Fm.build_z(Pt, mv.loc[:d])
        diffs = [float(np.nanmax(np.abs(Zt[k].loc[d].to_numpy() - Z[k].loc[d].to_numpy()))) for k in ALLK if Z[k].loc[d].notna().any()]; pit.append(dict(date=str(d.date()), max_abs_diff=max(diffs)))
    rob["point_in_time_truncation_test"] = dict(cases=pit, passed=bool(all(c["max_abs_diff"] < 1e-12 for c in pit)))
    rob["extra_1day_lag_val_ic_frozen"] = float(Fm.sp_ic(Sf.shift(1).loc[dva], Y7.loc[dva]).mean())
    res["robustness"] = rob
    res["portfolio_top3_weekly"]["STATIC_LOWVOL_ARM"] = {sp: V.port_summary(V.portfolio_series(Zs, P, list(d))) for sp, d in (("train", dtr), ("val", dva), ("legacy_DESCRIPTIVE", dlg))}; ND += 3
    rob["STATIC_LOWVOL_ic"] = dict(train=rob["VOL_static_vs_dynamic"]["static_train_ic"], val=rob["VOL_static_vs_dynamic"]["static_val_ic"], legacy_DESCRIPTIVE=float(Fm.sp_ic(Zs.loc[dlg], Y7.loc[dlg]).mean()))
    res["consumed_legacy_descriptive"]["per_factor_ic_DIAGNOSTIC_ONLY"] = {k: V.ic_stats(Fm.sp_ic(Z[k].loc[dlg], Y7.loc[dlg]))["mean"] for k in ALLK}; ND += len(ALLK)
    res["consumed_legacy_descriptive"]["frozen_by_btc_direction"] = by_tag(Fm.sp_ic(Sf.loc[dlg], Y7.loc[dlg]), tags.direction)

    # ---------- 10. current cross-section (last complete day) - research record, not a trade signal
    last = P["c"].dropna(how="all").index[-1]
    cur = dict(date=str(last.date()), btc_direction_tag=str(tags.direction.loc[last]), btc_structure=str(tags.structure.loc[last]), btc_vol=str(tags.vol.loc[last]),
               scores={a: (None if not np.isfinite(Sf.loc[last, a]) else round(float(Sf.loc[last, a]), 3)) for a in Fm.ASSETS},
               z={k: {a: (None if not np.isfinite(Z[k].loc[last, a]) else round(float(Z[k].loc[last, a]), 2)) for a in Fm.ASSETS} for k in ALLK})
    res["current"] = cur
    Sf.dropna(how="all").to_csv(OUT / "frozen_scores_daily.csv", float_format="%.4f")
    pd.concat({k: ser_tr[k] for k in ALLK}, axis=1).pipe(lambda t: pd.concat([t, pd.concat({k: ser_va[k] for k in ALLK}, axis=1)], sort=True)).to_csv(OUT / "factor_ic_daily_h7.csv", float_format="%.4f")
    res["n_statistical_evaluations"] = ND
    res["git"] = dict(head=subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
                      dirty=bool(subprocess.run(["git", "status", "--porcelain", "--", "stage05", "tests/stage05"], cwd=ROOT, capture_output=True, text=True).stdout.strip()))
    (OUT / "stage05_results.json").write_text(json.dumps(res, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    return res

if __name__ == "__main__": r = run(); print(json.dumps({k: r[k] for k in ("selection", "weights", "frozen_val_ic_POST_SELECTION_optimistic")}, indent=1, default=str)[:6000])
