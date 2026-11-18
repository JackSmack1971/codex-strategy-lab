"""Stage 03 runner: risk metrics, stress scenarios, risk-variant sensitivity. Research only; no orders.
Run: PYTHONPATH=. scripts/lab python -m stage03.run_stage03"""
import json, math, subprocess, hashlib, sys
from pathlib import Path
import numpy as np, pandas as pd
from stage02 import load_grid, engine as E, analysis as A
from stage03 import core as C

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "docs/strategy-specs/stage03"; OUT.mkdir(parents=True, exist_ok=True)
syms = load_grid.get(); f, s = C.BASE; BOOKS = C.BOOKS; WINS = C.WINS
J = lambda o: o.item() if hasattr(o, "item") else str(o)

# ---------------------------------------------------------------- baseline books + reconciliation
cands = C.build_cands(syms, f, s); R = C.run_all(cands, syms, f, s)
csv = pd.read_csv(ROOT / "docs/strategy-specs/stage02/trades_baseline.csv")
recon = {}
for b in BOOKS[:3]:
    for w in WINS:
        recon[f"{b}/{w}"] = dict(n_engine=len(R[b][w]["trades"]), n_stage02_csv=int(((csv.strategy == b) & (csv.window == w)).sum()),
            pnl_engine=round(sum(t["pnl"] for t in R[b][w]["trades"]), 6), pnl_csv=round(float(csv[(csv.strategy == b) & (csv.window == w)].pnl.sum()), 6))
recon_ok = all(v["n_engine"] == v["n_stage02_csv"] and abs(v["pnl_engine"] - v["pnl_csv"]) < 1e-4 for v in recon.values())

# ---------------------------------------------------------------- cohort / market series
n_days = len(syms["BTC"].cff) // 24
dclose = {n: syms[n].cff[: n_days * 24].reshape(n_days, 24)[:, -1] for n in E.SYMS}
dret = {n: np.concatenate([[np.nan], dclose[n][1:] / dclose[n][:-1] - 1]) for n in E.SYMS}
ew = np.nanmean(np.vstack([dret[n] for n in E.SYMS]), axis=0)
d0 = A.WINDOWS["train"][0] // 24; d1 = A.WINDOWS["final"][1] // 24
ew_eval = ew[d0:d1]; day_utc = lambda d: str(A.hdate(d * 24).date())
ew_p5 = float(np.quantile(ew_eval, .05)); ew_p1 = float(np.quantile(ew_eval, .01))
stress_day = np.zeros(n_days, bool); stress_day[d0:d1] = ew_eval <= ew_p5
retmat = np.vstack([dret[n][d0:d1] for n in E.SYMS]); cm = np.corrcoef(retmat); iu = np.triu_indices(9, 1)
st = ew_eval <= ew_p5; cm_s = np.corrcoef(retmat[:, st]); ev = np.linalg.eigvalsh(cm)[::-1]; ev_s = np.linalg.eigvalsh(cm_s)[::-1]
cohort = dict(days=int(d1 - d0), ew_daily_ret_p1=ew_p1, ew_daily_ret_p5=ew_p5, ew_daily_worst=float(ew_eval.min()), ew_worst_day=day_utc(d0 + int(np.argmin(ew_eval))),
    days_le_minus10pct=int((ew_eval <= -0.10).sum()), days_le_minus15pct=int((ew_eval <= -0.15).sum()), days_le_minus20pct=int((ew_eval <= -0.20).sum()),
    mean_pairwise_corr_all=float(cm[iu].mean()), mean_pairwise_corr_worst5pct_days=float(cm_s[iu].mean()), n_stress_days=int(st.sum()),
    pc1_share_all=float(ev[0] / 9), pc1_share_worst5pct_days=float(ev_s[0] / ev_s.sum()),
    btc_worst_day=float(np.nanmin(dret["BTC"][d0:d1])), btc_worst_day_utc=day_utc(d0 + int(np.nanargmin(dret["BTC"][d0:d1]))))
# worst rolling EW cohort declines
cum = np.cumsum(np.log1p(np.nan_to_num(ew_eval)))
def worst_roll(k):
    x = cum[k:] - cum[:-k]; i = int(np.argmin(x)); return dict(days=k, log_ret=float(x[i]), simple=float(np.expm1(x[i])), start=day_utc(d0 + i + 1), end=day_utc(d0 + i + k))
cohort["worst_rolling"] = [worst_roll(k) for k in (1, 3, 7, 14)]
# regime
reg = A.btc_regime_by_day(syms)

# ---------------------------------------------------------------- A. dashboard
def book_dash(b):
    Rb = R[b]; out = dict(windows={}); pooled_tr = []; all_dr = []; per_win_tr = []
    cmap = {(c["sym"], c["t_entry"], c["sid"]): c for c in cands[b]}
    for w in WINS:
        res = Rb[w]; tr = res["trades"]; pooled_tr += tr; per_win_tr.append(tr)
        m, dr = A.full_metrics(res); all_dr.append(dr)
        rr = np.array([t["reserved_risk"] for t in tr]); E0 = np.array([t["E_entry"] for t in tr]); Rr = np.array([t["R"] for t in tr]); pnl = np.array([t["pnl"] for t in tr])
        notional = np.array([t["qty"] * t["entry_fill"] for t in tr]); sd = np.array([(t["entry_fill"] - t["S0"]) / t["entry_fill"] for t in tr])
        gross, cnt, rk = C.hourly_positions(res, syms)
        d = dict(n=len(tr))
        if len(tr):
            d.update(risk_usd=dict(mean=float(rr.mean()), median=float(np.median(rr)), p05=float(np.quantile(rr, .05)), min=float(rr.min()), max=float(rr.max())),
                risk_pct_equity=dict(mean=float((rr / E0).mean()), median=float(np.median(rr / E0)), p05=float(np.quantile(rr / E0, .05)), max=float((rr / E0).max())),
                share_trades_below_budget_pct=float(((rr / E0) < 0.0099).mean()),
                notional_pct_equity=dict(median=float(np.median(notional / E0)), p95=float(np.quantile(notional / E0, .95)), max=float((notional / E0).max())),
                stop_distance_pct=dict(median=float(np.median(sd)), p05=float(np.quantile(sd, .05)), p95=float(np.quantile(sd, .95))),
                avg_win_usd=float(pnl[pnl > 0].mean()) if (pnl > 0).any() else None, avg_loss_usd=float(pnl[pnl <= 0].mean()) if (pnl <= 0).any() else None,
                expectancy_usd=float(pnl.mean()), worst_trade_usd=float(pnl.min()), worst_trade_R=float(Rr.min()), best_trade_R=float(Rr.max()),
                realized_rr=(float(Rr[Rr > 0].mean() / -Rr[Rr <= 0].mean()) if (Rr > 0).any() and (Rr <= 0).any() else None))
            if b in ("CRY-REV-102",) or any(c["sid"] == "CRY-REV-102" for c in cands[b]):
                prr = [ (cmap[(t["symbol"], t["entry_hour"], "CRY-REV-102")]["tgt"] - cmap[(t["symbol"], t["entry_hour"], "CRY-REV-102")]["O1"]) /
                        (cmap[(t["symbol"], t["entry_hour"], "CRY-REV-102")]["O1"] - t["S0"]) for t in tr if t["strategy"] == "CRY-REV-102" and (t["symbol"], t["entry_hour"], "CRY-REV-102") in cmap]
                if prr: d["planned_rr_REV_gross"] = dict(n=len(prr), median=float(np.median(prr)), p05=float(np.quantile(prr, .05)), p95=float(np.quantile(prr, .95)))
        d.update(max_dd_daily=m["max_dd"], max_dd_hourly=C.hourly_maxdd(res["equity"]), mdd_recovered=m["mdd_recovered"], mdd_peak_to_recovery_days=m["mdd_peak_to_recovery_days"],
                 longest_underwater_days=m["longest_underwater_days"], total_return=m["total_return"], ratio=m.get("ratio"), expectancy_R=m.get("expectancy_R"), win_rate=m.get("win_rate"), profit_factor=m.get("profit_factor"),
                 avg_win_R=m.get("avg_win_R"), avg_loss_R=m.get("avg_loss_R"), exposure_time=m["exposure_time"], avg_invested_pct=m["avg_invested_pct_equity"],
                 max_gross_pct_equity=float((gross / res["equity"]).max()), p99_gross_pct_equity=float(np.quantile(gross / res["equity"], .99)), max_open=int(cnt.max()),
                 hours_share_open=dict((int(k), float((cnt == k).mean())) for k in range(0, 4)), max_open_risk_pct=float((rk / res["equity"]).max()),
                 var_es_95_1d=dict(zip(("var", "es"), C.var_es(dr, .95))), skips=res["skips"])
        out["windows"][w] = d
    dr = np.concatenate(all_dr); out["pooled_days"] = int(len(dr)); out["share_zero_return_days"] = float((np.abs(dr) < 1e-12).mean())
    out["var_es_pooled"] = {}
    for a in (.95, .99):
        v, e = C.var_es(dr, a); gv, ge = C.gauss_var_es(dr, a); civ, cie = C.block_var_es_ci(dr, a)
        out["var_es_pooled"][str(a)] = dict(hist_var=v, hist_es=e, gauss_var=gv, gauss_es=ge, var_ci95=civ, es_ci95=cie, tail_obs=int(math.ceil((1 - a) * len(dr))),
                                          adequacy=("limited (<30 tail observations)" if math.ceil((1 - a) * len(dr)) < 30 else "ok for 1-day horizon"))
    invd = np.concatenate([(C.hourly_positions(R[b][w], syms)[1][: ((R[b][w]["we"] - R[b][w]["ws"]) // 24) * 24].reshape(-1, 24).max(1) > 0) for w in WINS])
    if invd.sum() >= 20:
        vc, ec = C.var_es(dr[invd], .95); out["var_es_95_conditional_on_invested_days"] = dict(n_days=int(invd.sum()), var=vc, es=ec, mean=float(dr[invd].mean()))
    wk = np.concatenate([C.rolling_horizon_ret(R[b][w], 7) for w in WINS]); v7, e7 = C.var_es(wk, .95)
    out["var_es_7d_95_overlapping"] = dict(var=v7, es=e7, n=len(wk), note="overlapping windows: serially dependent, effective sample ~ n/7")
    out["worst_7d_return"] = float(wk.min()); out["worst_1d_return"] = float(dr.min())
    # trade-level tail (R)
    Rall = np.array([t["R"] for t in pooled_tr]); q5 = np.quantile(Rall, .05)
    out["trade_R_var_es_95"] = dict(var=float(-q5), es=float(-Rall[Rall <= q5].mean()), n=len(Rall), adequacy="limited" if len(Rall) < 600 else "ok")
    out["loss_streaks"] = C.streak_summary(per_win_tr)
    st_ = out["loss_streaks"]; out["loss_streaks"]["iid_expected_runs_ge10_ILLUSTRATIVE"] = C.iid_expected_runs_ge(st_["n_trades"], st_["loss_share"], 10)
    out["loss_streaks"]["iid_expected_runs_ge8_ILLUSTRATIVE"] = C.iid_expected_runs_ge(st_["n_trades"], st_["loss_share"], 8)
    # gap / slippage / liquidity (trade level)
    stop_tr = [t for t in pooled_tr if t["kind"] == "stop"]; over = [t["R"] for t in pooled_tr if t["R"] < -1.0]
    out["gap_trade_level"] = dict(n_stop_exits=len(stop_tr), n_loss_worse_than_1R=len(over), worst_R=float(Rall.min()), mean_R_of_those=(float(np.mean(over)) if over else None),
        share_of_stop_exits_worse_than_1R=(len(over) / len(stop_tr) if stop_tr else None))
    part_e, part_x, cap_ratio = [], [], []
    for t in pooled_tr:
        sy = syms[t["symbol"]]; a0 = t["entry_hour"]; qv = np.nansum(sy.q[a0:a0 + t["tf"]]); part_e.append(t["qty"] * t["entry_fill"] / qv if qv > 0 else np.nan)
        x0 = t["exit_hour"]; qx = np.nansum(sy.q[x0:x0 + (t["tf"] if t["kind"] in ("stop", "target") else 1)])
        part_x.append(t["qty"] * t["exit_fill"] / qx if qx > 0 else np.nan)
        qm = sy.qmed168[a0 - 1]; cap_ratio.append(t["qty"] * t["entry_fill"] / (qm) if qm > 0 else np.nan)
    pe, px_, cr = np.array(part_e), np.array(part_x), np.array(cap_ratio)
    q = lambda a: dict(median=float(np.nanmedian(a)), p99=float(np.nanquantile(a, .99)), max=float(np.nanmax(a))) if len(a) else None
    out["liquidity_trade_level"] = dict(entry_notional_over_entry_bar_quote_volume=q(pe), exit_notional_over_exit_bar_quote_volume=q(px_), entry_notional_over_median168_hourly_volume=q(cr),
                                        participation_cap=0.01, share_at_cap=float((cr >= 0.0099).mean()) if len(cr) else None)
    # concentration
    ent = {}
    for t in pooled_tr: ent.setdefault((t["entry_hour"]), []).append(t["symbol"])
    co = sum(len(v) for v in ent.values() if len(v) > 1)
    cc = {}
    for c in cands[b]:
        cc.setdefault(c["t_entry"], set()).add(c["sym"])
    cand_shared = sum(1 for c in cands[b] if len(cc[c["t_entry"]]) > 1)
    sk = {}
    for w in WINS:
        for k, v in R[b][w]["skips"].items(): sk[k] = sk.get(k, 0) + v
    # worst realised exit cluster
    ex = sorted((C.exit_end(t), t["pnl"]) for t in pooled_tr); xe = np.array([e for e, _ in ex]); pp = np.array([p for _, p in ex])
    worst24 = 0.0; worstn = 0
    for i in range(len(xe)):
        m_ = (xe >= xe[i]) & (xe < xe[i] + 24); v = pp[m_].sum()
        if v < worst24: worst24 = float(v)
        losers = int((pp[m_] <= 0).sum()); worstn = max(worstn, losers)
    out["concentration"] = dict(share_trades_entered_same_hour_as_another=co / len(pooled_tr) if pooled_tr else None, candidate_share_with_simultaneous_candidate=cand_shared / max(1, len(cands[b])),
        skips_total=sk, worst_realised_24h_exit_cluster_usd=worst24, max_losing_exits_within_24h=worstn)
    # exposure in extreme conditions
    ex_ = dict()
    for lab, sel in (("worst5pct_cohort_days", lambda d: stress_day[d]), ("high_vol_regime_days", lambda d: reg[d].endswith("HIGHVOL")), ("normal_days", lambda d: (not stress_day[d]) and not reg[d].endswith("HIGHVOL"))):
        gp, pl, nd = [], [], 0
        for w in WINS:
            res = R[b][w]; ws = res["ws"]; gross, _, _ = C.hourly_positions(res, syms); g = gross / res["equity"]; dailyeq = np.concatenate([[A.CAP], A.daily_equity(res)])
            for k in range((res["we"] - ws) // 24):
                dd = ws // 24 + k
                if sel(dd): gp.append(g[24 * k:24 * k + 24].mean()); pl.append((dailyeq[k + 1] / dailyeq[k] - 1)); nd += 1
        ex_[lab] = dict(days=nd, mean_gross_exposure=float(np.mean(gp)) if gp else None, max_day_gross_exposure=float(np.max(gp)) if gp else None, mean_daily_return=float(np.mean(pl)) if pl else None, worst_daily_return=float(np.min(pl)) if pl else None)
    out["extreme_condition_exposure"] = ex_
    return out

dash = {b: book_dash(b) for b in BOOKS}
# cross-book dependence
dr_books = {b: np.concatenate([C.daily_ret(R[b][w]) for w in WINS]) for b in BOOKS[:3]}
cross = dict(daily_return_corr={f"{a}~{b}": float(np.corrcoef(dr_books[a], dr_books[b])[0, 1]) for i, a in enumerate(BOOKS[:3]) for b in BOOKS[:3][i + 1:]})
ov = {}
for i, a in enumerate(BOOKS[:3]):
    for b2 in BOOKS[:3][i + 1:]:
        n_ov = 0
        for w in WINS:
            for ta in R[a][w]["trades"]:
                for tb in R[b2][w]["trades"]:
                    if ta["symbol"] == tb["symbol"] and ta["entry_hour"] < C.exit_end(tb) and tb["entry_hour"] < C.exit_end(ta): n_ov += 1
        ov[f"{a}~{b2}"] = n_ov
cross["same_symbol_overlapping_position_pairs_standalone_books"] = ov
cross["share_days_ge2_books_invested"] = None
inv = []
for w in WINS:
    H = R["COMBINED"][w]["we"] - R["COMBINED"][w]["ws"]; k = np.zeros((3, H // 24), bool)
    for j, b in enumerate(BOOKS[:3]):
        g, c, _ = C.hourly_positions(R[b][w], syms); k[j] = c[: (H // 24) * 24].reshape(-1, 24).max(1) > 0
    inv.append(k.sum(0))
inv = np.concatenate(inv); cross["share_days_ge2_books_invested"] = float((inv >= 2).mean()); cross["share_days_3_books_invested"] = float((inv >= 3).mean())

# ---------------------------------------------------------------- B. stress scenarios
SC = {}
# S1 historical replay + hypothetical gap
s1 = dict(historical=dict(cohort=cohort, books={}), hypothetical={})
for b in BOOKS:
    row = {}
    for lab, k in (("worst_1d_cohort_day", 1), ("worst_7d_cohort_window", 7)):
        wr = worst_roll(k); a_ = int(pd.Timestamp(wr["start"], tz="UTC").timestamp() // 86400) - int(E.T0_MS / 86400000); b_ = int(pd.Timestamp(wr["end"], tz="UTC").timestamp() // 86400) - int(E.T0_MS / 86400000)
        chg = None; expo = {}
        for w in WINS:
            ws, we = A.WINDOWS[w]
            if ws // 24 <= a_ and b_ < we // 24:
                eq = np.concatenate([[A.CAP], A.daily_equity(R[b][w])]); i0 = a_ - ws // 24; i1 = b_ - ws // 24 + 1; chg = float(eq[i1] / eq[i0] - 1)
                g_, c_, _ = C.hourly_positions(R[b][w], syms); gg = (g_ / R[b][w]["equity"])[i0 * 24:i1 * 24]; expo = dict(mean_gross_exposure=float(gg.mean()), max_gross_exposure=float(gg.max()), in_warmup_or_flat=bool(gg.max() == 0))
        row[lab] = dict(window_utc=[wr["start"], wr["end"]], cohort_ret=wr["simple"], book_return=chg, **expo)
    s1["historical"]["books"][b] = row
for b in BOOKS:
    r_ = {}
    for lab, (sh, ex_s) in {"gap_-20pct": (0.20, 0.0), "gap_-20pct_plus_2pct_illiquid_exit": (0.20, 0.02)}.items():
        arrs = []; tops = []
        for w in WINS:
            ls = C.gap_shock(R[b][w], syms, sh, ex_s, f, s); gross, cnt, _ = C.hourly_positions(R[b][w], syms); arrs.append((ls, cnt > 0))
            tops += [dict(window=w, **e) for e in C.top_episodes(ls, R[b][w]["ws"], 2)]
        allv = np.concatenate([a for a, _ in arrs]); mask = np.concatenate([m for _, m in arrs]); stt = C.dist_stats(allv, mask)
        stt["share_exposed_hours_loss_gt_3pct"] = float((allv[mask] > 0.03).mean()); stt["share_exposed_hours_loss_gt_5pct"] = float((allv[mask] > 0.05).mean())
        stt["unconditional_p999"] = float(np.quantile(allv, .999)); stt["top_episodes"] = sorted(tops, key=lambda x: -x["value"])[:3]
        r_[lab] = stt
    s1["hypothetical"][b] = r_
SC["S1_sudden_20pct_decline"] = s1

# S2 volatility doubles / S3 costs x3 / S4 liquidity: full engine re-runs
def scaled_syms(k=None, volq=None):
    frames = {}
    for n in E.SYMS:
        sy = syms[n]; idx = np.where(sy.valid)[0]
        o, h, l, c, v, q = (a[idx].copy() for a in (sy.o, sy.h, sy.l, sy.c, sy.v, sy.q))
        if k:
            y = np.log(c); i = np.arange(len(y)); mu = (y[-1] - y[0]) / (len(y) - 1); y2 = y[0] + mu * i + k * (y - y[0] - mu * i); c2 = np.exp(y2)
            o, h, l, c = (c2 * np.exp(k * np.log(a / c)) if a is not c else c2 for a in (o, h, l, c))
        if volq: v, q = v * volq, q * volq
        frames[n] = pd.DataFrame(dict(t=E.T0_MS + idx.astype(np.int64) * E.HOUR, o=o, h=h, l=l, c=c, v=v, q=q))
    return E.build_grid(frames, len(syms["BTC"].valid))

def summarize_run(RR):
    out = {}
    for b in BOOKS:
        pn = sum(t["pnl"] for w in WINS for t in RR[b][w]["trades"]); rk = sum(t["reserved_risk"] for w in WINS for t in RR[b][w]["trades"]); n = sum(len(RR[b][w]["trades"]) for w in WINS)
        dr = np.concatenate([C.daily_ret(RR[b][w]) for w in WINS]); v, e = C.var_es(dr, .95)
        out[b] = dict(n_trades=n, net_pnl_usd_3books_windows=float(pn), ratio=float(pn / rk) if rk > 0 else None,
            max_dd_daily_worst_window=min(A.eq_metrics(A.daily_equity(RR[b][w]))["max_dd"] for w in WINS), max_dd_by_window={w: A.eq_metrics(A.daily_equity(RR[b][w]))["max_dd"] for w in WINS},
            es95_1d=e, worst_1d=float(dr.min()), worst_trade_R=float(min([t["R"] for w in WINS for t in RR[b][w]["trades"]] or [0])), n_loss_worse_than_1R=int(sum(t["R"] < -1 for w in WINS for t in RR[b][w]["trades"])),
            max_gross_pct_equity=float(max((C.hourly_positions(RR[b][w], SY_CUR)[0] / RR[b][w]["equity"]).max() for w in WINS)))
    return out
SY_CUR = syms
SC["baseline"] = summarize_run(R)
syms2 = scaled_syms(k=2.0); SY_CUR = syms2
c2 = C.build_cands(syms2, f, s); R2 = C.run_all(c2, syms2, f, s); SC["S2_volatility_x2_HYPOTHETICAL"] = summarize_run(R2)
SC["S2_volatility_x2_HYPOTHETICAL"]["_check"] = dict(btc_daily_logret_sd_before=float(np.nanstd(np.diff(np.log(syms["BTC"].cff[23::24])))), btc_daily_logret_sd_after=float(np.nanstd(np.diff(np.log(syms2["BTC"].cff[23::24])))),
    btc_min_max_price_ratio_before=float(np.nanmax(syms["BTC"].c) / np.nanmin(syms["BTC"].c)), btc_min_max_price_ratio_after=float(np.nanmax(syms2["BTC"].c) / np.nanmin(syms2["BTC"].c)))
SY_CUR = syms
f3, s3 = 3 * f, 3 * s
c3 = C.build_cands(syms, f3, s3); R3 = C.run_all(c3, syms, f3, s3); SC["S3_costs_x3_HYPOTHETICAL"] = summarize_run(R3)
syms4 = scaled_syms(volq=0.1); SY_CUR = syms4
c4 = C.build_cands(syms4, f, s); R4 = C.run_all(c4, syms4, f, s); SC["S4a_volume_x0.1_HYPOTHETICAL"] = summarize_run(R4)
s4b = 4 * s; c4b = C.build_cands(syms4, f, s4b); R4b = C.run_all(c4b, syms4, f, s4b); SC["S4b_volume_x0.1_and_slippage_x4_HYPOTHETICAL"] = summarize_run(R4b)
SY_CUR = syms
# gate attrition under S4 (how many raw candidates survive)
SC["S4a_volume_x0.1_HYPOTHETICAL"]["_candidates_vs_baseline"] = {b: [len(c4[b]), len(cands[b])] for b in BOOKS}
SC["S4a_volume_x0.1_HYPOTHETICAL"]["_skips"] = {b: {k: sum(R4[b][w]["skips"].get(k, 0) for w in WINS) for k in {kk for w in WINS for kk in R4[b][w]["skips"]}} for b in BOOKS}

# S5 ten consecutive losses
S5 = {}
for b in BOOKS:
    tr = [t for w in WINS for t in R[b][w]["trades"]]; Rl = np.array([t["R"] for t in tr if t["pnl"] <= 0]); rf = float(np.mean([t["reserved_risk"] / t["E_entry"] for t in tr]))
    cases = {"planned_-1R": -1.0, "mean_realised_loss_R": float(Rl.mean()), "p90_realised_loss_R(worst decile edge)": float(np.quantile(Rl, .10)), "worst_realised_R_repeated": float(Rl.min())}
    S5[b] = dict(avg_risk_fraction_of_equity=rf, n_losses_sampled=len(Rl), cases={k: dict(R_per_loss=v, equity_loss_pct_10_in_row=float(1 - (1 + rf * v) ** 10)) for k, v in cases.items()},
        historical=dash[b]["loss_streaks"], note="HYPOTHETICAL sequential compounding at the realised mean risk fraction; the 3% open-risk cap does not bound this (losses are sequential, not simultaneous)")
SC["S5_ten_consecutive_losses"] = S5

# S2b / stops-failing replay: stops fill inside the exit bar's range (HISTORICAL bars, HYPOTHETICAL fill assumption)
def overshoot(b, alpha, mult=1.0):
    rows = []; per_w = {}
    for w in WINS:
        adj = []
        for t in R[b][w]["trades"]:
            extra = 0.0
            if t["kind"] == "stop":
                sy = syms[t["symbol"]]; x0 = t["exit_hour"]; low = np.nanmin(np.where(sy.valid[x0:x0 + t["tf"]], sy.l[x0:x0 + t["tf"]], np.nan))
                exc = max(0.0, t["exit_fill"] - low * (1 - s)); extra = alpha * mult * exc * t["qty"] * (1 - f)
                rows.append(dict(stop_wick_pct=exc / t["exit_fill"], extraR=extra / t["reserved_risk"], R_adj=(t["pnl"] - extra) / t["reserved_risk"]))
            tt = dict(t); tt["pnl"] = t["pnl"] - extra; adj.append(tt)
        dd0, p0 = C.closed_dd(R[b][w]["trades"]); dd1, p1 = C.closed_dd(adj)
        per_w[w] = dict(closed_dd_base=dd0, closed_dd_adjusted=dd1, net_pnl_base=p0, net_pnl_adjusted=p1)
    d = pd.DataFrame(rows)
    return dict(n_stop_exits=len(d), share_wick_beyond_modelled_fill=float((d.stop_wick_pct > 1e-9).mean()) if len(d) else None, wick_pct_p50=float(d.stop_wick_pct.median()) if len(d) else None,
                wick_pct_p95=float(d.stop_wick_pct.quantile(.95)) if len(d) else None, wick_pct_max=float(d.stop_wick_pct.max()) if len(d) else None,
                extraR_mean=float(d.extraR.mean()) if len(d) else None, extraR_p95=float(d.extraR.quantile(.95)) if len(d) else None, extraR_max=float(d.extraR.max()) if len(d) else None,
                worst_R_adjusted=float(d.R_adj.min()) if len(d) else None, share_R_adjusted_below_minus1_5=float((d.R_adj < -1.5).mean()) if len(d) else None,
                share_R_adjusted_below_minus2=float((d.R_adj < -2.0).mean()) if len(d) else None,
                mean_loss_R_adjusted=float(d.R_adj[d.R_adj <= 0].mean()) if len(d) and (d.R_adj <= 0).any() else None, by_window=per_w)
OV = {}
for b in BOOKS:
    OV[b] = {"stop_fills_at_50pct_of_wick_below_modelled_fill": overshoot(b, 0.5), "stop_fills_at_exit_bar_low": overshoot(b, 1.0), "wick_depth_x2_vol_doubles_fill_at_exit_bar_low": overshoot(b, 1.0, 2.0)}
SC["S2b_stops_fail_inside_bar"] = OV
for b in BOOKS:   # augment S5 with an overshoot-based loss size
    S5[b]["cases"]["mean_loss_R_if_stops_fill_at_exit_bar_low_HYPOTHETICAL"] = dict(R_per_loss=OV[b]["stop_fills_at_exit_bar_low"]["mean_loss_R_adjusted"], equity_loss_pct_10_in_row=float(1 - (1 + S5[b]["avg_risk_fraction_of_equity"] * OV[b]["stop_fills_at_exit_bar_low"]["mean_loss_R_adjusted"]) ** 10))
    S5[b]["cases"]["p95_extra_R_added_to_planned_-1R_HYPOTHETICAL"] = dict(R_per_loss=-1.0 - OV[b]["stop_fills_at_exit_bar_low"]["extraR_p95"], equity_loss_pct_10_in_row=float(1 - (1 + S5[b]["avg_risk_fraction_of_equity"] * (-1.0 - OV[b]["stop_fills_at_exit_bar_low"]["extraR_p95"])) ** 10))

# stop-fill tolerance: share alpha of the in-bar wick (stop - bar low) that can be lost before pooled/validation net P&L reaches zero
BE = {}
for b in BOOKS:
    BE[b] = {}
    for w in WINS + ["pooled_all"]:
        pn = 0.0; ex = 0.0; wick_bps = []; ws_ = WINS if w == "pooled_all" else [w]
        for ww in ws_:
            for t in R[b][ww]["trades"]:
                pn += t["pnl"]
                if t["kind"] == "stop":
                    sy = syms[t["symbol"]]; x0 = t["exit_hour"]; low = np.nanmin(np.where(sy.valid[x0:x0 + t["tf"]], sy.l[x0:x0 + t["tf"]], np.nan))
                    exc = max(0.0, t["exit_fill"] - low * (1 - s)); ex += exc * t["qty"] * (1 - f); wick_bps.append(1e4 * exc / t["exit_fill"])
        BE[b][w] = dict(net_pnl_baseline=pn, extra_loss_if_alpha_1=ex, breakeven_alpha=(pn / ex if (pn > 0 and ex > 0) else (0.0 if pn <= 0 else None)),
                        mean_wick_bps=float(np.mean(wick_bps)) if wick_bps else None, breakeven_extra_bps_per_stop_exit=(float(pn / ex * np.mean(wick_bps)) if (pn > 0 and ex > 0) else 0.0))
SC["S2b_stop_fill_tolerance"] = BE

# S6 venue unavailable
aud = json.load(open(ROOT / "stage02/audit.json")); gl = aud[0]["gap_list"]; S6 = dict(historical_data_gaps=[], hypothetical_freeze={}, unquantified=[])
for ts, nh in gl:
    h = A.hr(pd.Timestamp(ts).date()) + pd.Timestamp(ts).hour; mv = {}
    for n in E.SYMS:
        sy = syms[n]; before = sy.cff[h]; after = sy.cff[h + nh + 1] if h + nh + 1 < len(sy.cff) else np.nan   # audit timestamp = last present bar; missing hours follow
        mv[n] = float(np.log(after / before)) if np.isfinite(after) else None
    nvals = [abs(x) for x in mv.values() if x is not None]
    typ = float(np.nanmedian([np.nanstd(np.diff(np.log(syms[n].cff[h - 499:h + 1]))) for n in E.SYMS]))
    S6["historical_data_gaps"].append(dict(last_present_bar_utc=ts, hours=nh, same_hours_missing_in_all_symbols=True, max_abs_logmove_across_gap=max(nvals), median_abs_logmove_across_gap=float(np.median(nvals)), median_1h_sd_prior_500h=typ))
cache = {}
for T in (24, 72, 168):
    S6["hypothetical_freeze"][str(T)] = {}
    for b in BOOKS:
        arrs, masks, tops = [], [], []
        for w in WINS:
            ls = C.freeze_loss(R[b][w], syms, T, f, s, cache); gross, cnt, _ = C.hourly_positions(R[b][w], syms); arrs.append(ls); masks.append(cnt > 0)
            tops += [dict(window=w, **e) for e in C.top_episodes(ls, R[b][w]["ws"], 2)]
        allv, mk = np.concatenate(arrs), np.concatenate(masks); stt = C.dist_stats(allv, mk); stt["top_episodes"] = sorted(tops, key=lambda x: -x["value"])[:3]
        stt["share_exposed_hours_loss_gt_3pct"] = float((allv[mk] > 0.03).mean()); stt["effective_independent_episodes_note"] = f"windows overlap by up to {T}h; exposed hours are serially dependent"
        S6["hypothetical_freeze"][str(T)][b] = stt
S6["unquantified"] = ["exchange insolvency / withdrawal suspension (counterparty loss up to full venue balance)", "regulatory restriction or delisting of an asset while held", "API/connectivity failure with open exposure and no exit",
                      "stablecoin (USDT) depeg while holding USDT balances", "probability of any of these cannot be estimated from this sample"]
SC["S6_venue_unavailable"] = S6

# ---------------------------------------------------------------- C. risk-variant sensitivity (exploratory, not selection)
VAR = {}
VAR["baseline"] = SC["baseline"]
Rm1 = C.run_all(cands, syms, f, s, per_trade=0.005, total=0.015); VAR["M1_risk_0.5pct_open_1.5pct"] = summarize_run(Rm1)
Rm2 = C.run_all(cands, syms, f, s, ncap=0.133); VAR["M2_notional_cap_13.3pct_per_position"] = summarize_run(Rm2)
gs2 = {}
for b in BOOKS:
    arr = np.concatenate([C.gap_shock(Rm2[b][w], syms, .20, 0.0, f, s) for w in WINS]); mk = np.concatenate([C.hourly_positions(Rm2[b][w], syms)[1] > 0 for w in WINS]); gs2[b] = C.dist_stats(arr, mk)
VAR["M2_gap20_shock"] = gs2
gs1 = {}
for b in BOOKS:
    arr = np.concatenate([C.gap_shock(Rm1[b][w], syms, .20, 0.0, f, s) for w in WINS]); mk = np.concatenate([C.hourly_positions(Rm1[b][w], syms)[1] > 0 for w in WINS]); gs1[b] = C.dist_stats(arr, mk)
VAR["M1_gap20_shock"] = gs1
th = {}
for b in BOOKS:
    th[b] = {}
    for w in WINS:
        tr = R[b][w]["trades"]; base_dd, base_pnl = C.closed_dd(tr); tt = C.throttle_replay(tr); th[b][w] = dict(closed_dd_base=base_dd, net_pnl_base=base_pnl, **{f"throttle_{k}": v for k, v in tt.items()})
VAR["M3_drawdown_throttle_replay_APPROX"] = th
SC["variants"] = VAR

# ---------------------------------------------------------------- D. efficiency diagnostics (descriptive only)
EFF = {}
vx = []
for w in WINS:
    for t in R["CRY-VEX-103"][w]["trades"]:
        cost = t["fees"] + t["qty"] * (t["entry_fill"] - t["O1"]) + t["sell_notional"] * s / (1 - s); vx.append(dict(w=w, cr=cost / t["reserved_risk"], R=t["R"], pnl=t["pnl"], cost=cost))
vd = pd.DataFrame(vx); vd["bin"] = pd.qcut(vd.cr, 3, labels=["low", "mid", "high"])
EFF["E1_VEX_cost_to_risk_terciles_DESCRIPTIVE_POST_HOC"] = {w: {str(k): dict(n=int(len(g)), mean_R=float(g.R.mean()), mean_cost_over_risk=float(g.cr.mean())) for k, g in vd[vd.w == w].groupby("bin", observed=True)} for w in WINS}
EFF["E1_VEX_cost_to_risk_terciles_DESCRIPTIVE_POST_HOC"]["_tercile_cutpoints_pooled"] = [float(x) for x in vd.cr.quantile([1 / 3, 2 / 3])]
EFF["E1_VEX_cost_share_of_gross"] = {w: dict(total_cost_usd=float(vd[vd.w == w].cost.sum()), net_pnl_usd=float(vd[vd.w == w].pnl.sum()), gross_pnl_before_cost_usd=float(vd[vd.w == w].pnl.sum() + vd[vd.w == w].cost.sum())) for w in WINS}
comb = {}
for w in WINS:
    ms = np.mean([C.daily_ret(R[b][w]) for b in BOOKS[:3]], axis=0); cb = C.daily_ret(R["COMBINED"][w])
    eqm = np.cumprod(1 + ms); eqc = np.cumprod(1 + cb)
    dd = lambda e: float((np.concatenate([[1], e]) / np.maximum.accumulate(np.concatenate([[1], e])) - 1).min())
    comb[w] = dict(split_equal_capital=dict(total_return=float(eqm[-1] - 1), ann_vol=float(ms.std(ddof=1) * math.sqrt(365)), max_dd=dd(eqm)), shared_book=dict(total_return=float(eqc[-1] - 1), ann_vol=float(cb.std(ddof=1) * math.sqrt(365)), max_dd=dd(eqc)))
EFF["E2_combined_vs_equal_capital_split_DESCRIPTIVE"] = comb
cs = {}
for b in BOOKS[:3]:
    cs[b] = {}
    for w in WINS:
        tr = R[b][w]["trades"]; cost = sum(t["fees"] + t["qty"] * (t["entry_fill"] - t["O1"]) + t["sell_notional"] * s / (1 - s) for t in tr); pn = sum(t["pnl"] for t in tr)
        cs[b][w] = dict(total_cost_usd=float(cost), net_pnl_usd=float(pn), gross_pnl_before_cost_usd=float(pn + cost), cost_over_abs_gross=float(cost / abs(pn + cost)) if abs(pn + cost) > 0 else None)
EFF["cost_share_of_gross_all_books"] = cs
# E2: inverse-volatility sleeve weights from TRAIN daily vol (MOM and VEX only; REV excluded by Stage 02 label), applied to validation/final standalone daily returns
sd_tr = {b: float(C.daily_ret(R[b]["train"]).std(ddof=1)) for b in ("CRY-MOM-101", "CRY-VEX-103")}; iv = {b: (1 / v) / sum(1 / x for x in sd_tr.values()) for b, v in sd_tr.items()}
def stat(r):
    e = np.cumprod(1 + r); pk = np.maximum.accumulate(np.concatenate([[1], e])); return dict(total_return=float(e[-1] - 1), ann_vol=float(r.std(ddof=1) * math.sqrt(365)), max_dd=float((np.concatenate([[1], e]) / pk - 1).min()), sharpe=float(r.mean() / r.std(ddof=1) * math.sqrt(365)))
e2 = dict(weights_from_train_daily_sd=iv, train_daily_sd=sd_tr, evaluation={})
for w in ("train", "validation", "final"):
    rm, rv = C.daily_ret(R["CRY-MOM-101"][w]), C.daily_ret(R["CRY-VEX-103"][w])
    e2["evaluation"][w] = dict(equal_weight_MOM_VEX=stat(0.5 * rm + 0.5 * rv), inverse_vol_MOM_VEX=stat(iv["CRY-MOM-101"] * rm + iv["CRY-VEX-103"] * rv), MOM_alone=stat(rm), VEX_alone=stat(rv), shared_combined_book=stat(C.daily_ret(R["COMBINED"][w])))
EFF["E2_inverse_vol_sleeves_EXPLORATORY_one_configuration"] = e2

# ---------------------------------------------------------------- trigger replay counts (policy calibration; descriptive)
TRG = {}
for b in BOOKS:
    row = {}
    for w in WINS:
        d = np.concatenate([[A.CAP], A.daily_equity(R[b][w])]); pk = np.maximum.accumulate(d); dd = d / pk - 1; dr = d[1:] / d[:-1] - 1
        crossings = lambda thr: int(((dd[1:] <= -thr) & (dd[:-1] > -thr)).sum())
        row[w] = dict(dd_cross_5pct=crossings(.05), dd_cross_10pct=crossings(.10), dd_cross_15pct=crossings(.15), dd_cross_20pct=crossings(.20), days_loss_ge_2pct=int((dr <= -.02).sum()), days_loss_ge_3pct=int((dr <= -.03).sum()), max_dd=float(dd.min()))
    TRG[b] = row
SC["trigger_replay_counts"] = TRG
TRG1 = {}
for b in BOOKS:
    TRG1[b] = {}
    for w in WINS:
        d = np.concatenate([[A.CAP], A.daily_equity(Rm1[b][w])]); pk = np.maximum.accumulate(d); dd = d / pk - 1; dr = d[1:] / d[:-1] - 1
        cr = lambda thr: int(((dd[1:] <= -thr) & (dd[:-1] > -thr)).sum())
        TRG1[b][w] = dict(dd_cross_4pct=cr(.04), dd_cross_8pct=cr(.08), dd_cross_12pct=cr(.12), dd_cross_15pct=cr(.15), days_loss_ge_1_5pct=int((dr <= -.015).sum()), days_loss_ge_3pct=int((dr <= -.03).sum()), max_dd=float(dd.min()))
SC["trigger_replay_counts_at_M1_sizing"] = TRG1
rc = pd.DataFrame(retmat.T[:, :]).rolling(30)
roll = []
for k in range(30, retmat.shape[1] + 1):
    cmk = np.corrcoef(retmat[:, k - 30:k]); roll.append(cmk[iu].mean())
roll = np.array(roll); cohort["rolling30d_mean_pairwise_corr"] = dict(p05=float(np.quantile(roll, .05)), p50=float(np.quantile(roll, .5)), p95=float(np.quantile(roll, .95)), max=float(roll.max()), n=int(len(roll)))

# ---------------------------------------------------------------- proposed policy replay (single pre-declared configuration; descriptive, development windows)
def policy_stats(RR, keys):
    out = {}
    for b in keys:
        pn = sum(t["pnl"] for w in WINS for t in RR[b][w]["trades"]); rk = sum(t["reserved_risk"] for w in WINS for t in RR[b][w]["trades"])
        shock = np.concatenate([C.gap_shock(RR[b][w], syms, .20, 0.0, f, s) for w in WINS]); mk = np.concatenate([C.hourly_positions(RR[b][w], syms)[1] > 0 for w in WINS])
        fz = np.concatenate([C.freeze_loss(RR[b][w], syms, 72, f, s, cache) for w in WINS]); dr = np.concatenate([C.daily_ret(RR[b][w]) for w in WINS]); v, e = C.var_es(dr, .95)
        out[b] = dict(n_trades=int(sum(len(RR[b][w]["trades"]) for w in WINS)), net_pnl_usd=float(pn), ratio=float(pn / rk) if rk > 0 else None,
            max_dd_by_window={w: A.eq_metrics(A.daily_equity(RR[b][w]))["max_dd"] for w in WINS}, es95_1d=e, worst_1d=float(dr.min()), worst_7d=float(np.concatenate([C.rolling_horizon_ret(RR[b][w], 7) for w in WINS]).min()),
            gap20_shock_max=float(shock[mk].max()), gap20_shock_p99=float(np.quantile(shock[mk], .99)), freeze72h_max=float(fz[mk].max()),
            max_gross_pct_equity=float(max((C.hourly_positions(RR[b][w], syms)[0] / RR[b][w]["equity"]).max() for w in WINS)), max_open_risk_pct=float(max((C.hourly_positions(RR[b][w], syms)[2] / RR[b][w]["equity"]).max() for w in WINS)))
    return out
P1 = {}
Rp_mom = {w: A.run_window(cands["CRY-MOM-101"], syms, w, f, s, per_trade=0.005, total=0.015, ncap=0.133) for w in WINS}
Rp_vex = {w: A.run_window(cands["CRY-VEX-103"], syms, w, f, s, per_trade=0.0025, total=0.0075, ncap=0.10) for w in WINS}
P1 = policy_stats({"CRY-MOM-101": Rp_mom, "CRY-VEX-103": Rp_vex}, ["CRY-MOM-101", "CRY-VEX-103"])
mv = [c for c in cands["COMBINED"] if c["sid"] in ("CRY-MOM-101", "CRY-VEX-103")]
Rp_port = {w: A.run_window(mv, syms, w, f, s, per_trade=0.005, total=0.015, ncap=0.133) for w in WINS}
P2 = policy_stats({"PORTFOLIO_MOM_VEX": Rp_port}, ["PORTFOLIO_MOM_VEX"])
SC["policy_replay"] = dict(sleeves=P1, portfolio=P2, note="Proposed limits replayed once on the Stage 02 development/evaluation/consumed windows. Descriptive only: not optimised, not validated, not an out-of-sample test.")

# ---------------------------------------------------------------- write
try: commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(); dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--", "stage02", "stage03"], cwd=ROOT, text=True).strip())
except Exception: commit, dirty = None, None
res = dict(meta=dict(stage="03", head_commit=commit, stage03_source_dirty=dirty, stage02_handoff="docs/strategy-specs/STAGE_02_HANDOFF.json", reconciliation_ok=recon_ok, reconciliation=recon,
                     costs=dict(fee=f, adverse=s, status="ASSUMED_NOT_OBSERVED"), windows={w: [str(A.hdate(a)), str(A.hdate(b_))] for w, (a, b_) in A.WINDOWS.items()},
                     window_status=dict(train="development", validation="evaluation (not untouched)", final="CONSUMED_LEGACY descriptive only"),
                     bootstrap=dict(block_days=14, reps=2000, seed=20261118)),
           cohort=cohort, dashboard=dash, cross_book=cross, scenarios=SC, efficiency=EFF)
(OUT / "risk_results.json").write_text(json.dumps(res, indent=1, default=J))
print("reconciliation_ok", recon_ok); print("wrote", OUT / "risk_results.json", (OUT / "risk_results.json").stat().st_size)
