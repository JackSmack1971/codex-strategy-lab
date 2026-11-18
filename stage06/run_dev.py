"""Stage 06 development runner (anchored walk-forward on DEV 2021-11-17..2025-11-17). Research only.
Run: PYTHONPATH=. scripts/lab python -m stage06.run_dev
Order (enforced in code): baseline reproduction -> train-only selection -> reporting windows -> statistics -> FREEZE file -> consumed-window descriptive.
Does NOT touch the adjacent-asset holdout."""
from __future__ import annotations
import csv, hashlib, json, pickle, subprocess, sys, time
from pathlib import Path
import numpy as np, pandas as pd
from stage02 import engine as E, analysis as A, load_grid
from stage05 import factors as Fm, evaluate as EV
from . import variants as V, wf as W

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "docs" / "strategy-specs" / "stage06"; OUT.mkdir(parents=True, exist_ok=True)
STRATS = (V.MOM, V.VEX)


def git(*a): return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.floating,)): return None if not np.isfinite(o) else float(o)
    if isinstance(o, float): return None if not np.isfinite(o) else o
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.bool_,)): return bool(o)
    return o


def build_env(ndays=2100):
    P, meta, mv = pickle.loads((ROOT / "data" / "s5panel.pkl").read_bytes())
    raw, Z = Fm.build_z(P, mv); tags = EV.btc_regime_tags(P)
    days = pd.date_range(V.DAY0, periods=ndays, freq="D", tz="UTC")
    def arr(s, fill): return s.reindex(days).to_numpy()
    reg = {"DIR_NOT_BEARISH": (tags["direction"] != "Bearish"), "STRUCT_TRENDING": (tags["structure"] != "NonTrending"), "VOL_NOT_HIGH": (tags["vol"] != "HighVol")}
    regime = {k: np.nan_to_num(arr(v.astype(float), 1.0), nan=1.0).astype(bool) for k, v in reg.items()}
    W5 = {"EQ3": {"MOM": 1 / 3, "VOL": 1 / 3, "VALUE": 1 / 3}, "PRIOR5": {"MOM": .30, "TREND": .25, "VOL": .15, "LIQ": .10, "VALUE": .20}, "VOLONLY": {"VOL": 1.0}}
    factor = {}
    for wn, w in W5.items():
        S = Fm.composite(Z, w)
        for a in Fm.ASSETS: factor[(wn, a)] = arr(S[a], np.nan)
    return V.Env(regime=regime, factor=factor, ndays=ndays), meta


def modal(folds):
    ch = [f["cid"] for f in folds if f["switched"]]
    if not ch: return None, 0
    cid = max(set(ch), key=ch.count); return cid, ch.count(cid)


def main():
    t0 = time.time(); head = git("rev-parse", "HEAD"); dirty = [l for l in git("status", "--porcelain", "--untracked-files=no").splitlines() if l.strip()]
    if dirty: sys.exit("refusing to run: tracked files modified:\n" + "\n".join(dirty))
    syms = load_grid.get(); env, meta = build_env(); U = V.universe(); bank = W.Bank(syms, env)
    # ---------------------------------------------------------------- 1. baseline reproduction (Stage 02 handoff)
    h2 = json.loads((ROOT / "docs" / "strategy-specs" / "STAGE_02_HANDOFF.json").read_text())["strategies"]; repro = {}
    for sid in STRATS:
        for w, win in (("train", A.WINDOWS["train"]), ("validation", A.WINDOWS["validation"])):
            m = bank.get(f"{sid}|BASELINE", sid, V._base(sid), {}, W.BASE_COST, win); ref = h2[sid]["windows"][w]
            ok = m["n"] == ref["n"] and abs(m["ratio"] - ref["ratio"]) < 1e-9 and abs(m["max_dd"] - ref["max_dd"]) < 1e-9
            repro[f"{sid}|{w}"] = dict(n=m["n"], ratio=m["ratio"], sharpe=m["sharpe"], max_dd=m["max_dd"], ref_n=ref["n"], ref_ratio=ref["ratio"], match=bool(ok))
            if not ok: sys.exit(f"BASELINE DOES NOT REPRODUCE Stage 02: {sid} {w} {repro[f'{sid}|{w}']}")
    # ---------------------------------------------------------------- 2. train-only selection (all families, all folds)
    WF = {}
    for (sid, fam) in V.families(): WF[(sid, fam)] = W.walk_forward(bank, sid, fam)
    selection_record = {f"{s}|{f}": [dict(fold=x["fold"], chosen=x["chosen"], switched=x["switched"], score=x["score"], best=x["best"], ins_dS=x["ins_dS"]) for x in v] for (s, f), v in WF.items()}
    sel_hash = hashlib.sha256(json.dumps(clean(selection_record), sort_keys=True).encode()).hexdigest()
    # ---------------------------------------------------------------- 3. reporting windows for ALL configs (reporting only; selection above is already fixed)
    rows = []; dev_daily = {}
    for cid, (sid, fam, pt, P, x) in U.items():
        for k, fd in enumerate(W.FOLDS):
            for nm, win in (("train", fd["train"]), ("test", fd["test"])):
                m = bank.get(cid, sid, P, x, W.BASE_COST, win); rows.append(dict(cfg=cid, strategy=sid, family=fam, point=json.dumps(clean(pt)), fold=k, window=nm, **{q: m[q] for q in ("n", "ratio", "sharpe", "max_dd", "total_return", "turnover_per_year", "win_rate", "profit_factor")}))
        m = bank.get(cid, sid, P, x, W.BASE_COST, W.DEV); dev_daily[cid] = m["daily"]
        rows.append(dict(cfg=cid, strategy=sid, family=fam, point=json.dumps(clean(pt)), fold=-1, window="dev", **{q: m[q] for q in ("n", "ratio", "sharpe", "max_dd", "total_return", "turnover_per_year", "win_rate", "profit_factor")}))
    # ---------------------------------------------------------------- 4. per-family evaluation
    FAM = {}; pvals = {}
    def dev_dS(sid, cid):
        P, x = (V._base(sid), {}) if cid.endswith("BASELINE") else (U[cid][3], U[cid][4])
        return W.sh(dev_daily[cid]) - W.sh(dev_daily[f"{sid}|BASELINE"])
    for (sid, fam), folds in WF.items():
        key = f"{sid}|{fam}"; pl = W.pooled(folds); mc, cnt = modal(folds); F = V.families()[(sid, fam)]
        rec = dict(sid=sid, family=fam, n_nonbase_configs=len(V.points(sid, fam)) - 1, modal_cid=mc, modal_count=cnt, switches=int(sum(f["switched"] for f in folds)),
                   folds=[dict(fold=f["fold"], chosen=f["chosen"], switched=f["switched"], score=f["score"], ins_dS=f["ins_dS"], oos_dS=f["oos_dS"], oos=f["oos"], base_oos=f["base_oos"]) for f in folds],
                   pooled={k: v for k, v in pl.items() if k not in ("r", "rb")})
        sw = [f for f in folds if f["switched"]]
        rec["degradation"] = dict(mean_ins_dS_switched=float(np.mean([f["ins_dS"] for f in sw])) if sw else None, mean_oos_dS_switched=float(np.nanmean([f["oos_dS"] for f in sw])) if sw else None)
        g = {}
        g["G1"] = bool(pl["dSharpe"] >= W.G1_DSHARPE); g["G2"] = bool(pl["worst_fold_mdd"] >= pl["base_worst_fold_mdd"] - W.G2_DD_TOL)
        g["G3"] = bool(pl["n"] >= W.MIN_TRADE_FRAC * pl["base_n"]); g["G4"] = bool(pl["turnover"] <= W.TURN_MULT * pl["base_turnover"])
        g["G5"] = bool(mc is not None and cnt >= 3)
        if mc is not None:
            sid_, fam_, pt, P, x = U[mc]
            res = {}
            for nm, cost in (("A", W.STRESS_A), ("B", W.STRESS_B)):
                r = np.concatenate([bank.get(mc, sid, P, x, cost, fd["test"])["daily"] for fd in W.FOLDS]); rb = np.concatenate([bank.get(f"{sid}|BASELINE", sid, V._base(sid), {}, cost, fd["test"])["daily"] for fd in W.FOLDS])
                res[nm] = dict(sharpe=W.sh(r), base_sharpe=W.sh(rb), dSharpe=W.sh(r) - W.sh(rb))
            r0 = np.concatenate([bank.get(mc, sid, P, x, W.BASE_COST, fd["test"])["daily"] for fd in W.FOLDS]); rb0 = np.concatenate([bank.get(f"{sid}|BASELINE", sid, V._base(sid), {}, W.BASE_COST, fd["test"])["daily"] for fd in W.FOLDS])
            res["base_cost_modal_fixed"] = dict(sharpe=W.sh(r0), base_sharpe=W.sh(rb0), dSharpe=W.sh(r0) - W.sh(rb0))
            rec["cost_modal_fixed"] = res; g["G6"] = bool(res["A"]["dSharpe"] > 0 and res["B"]["dSharpe"] > 0)
            nbs = [V.cfg_id(sid, fam, q) if q != V.baseline_point(sid, fam) else f"{sid}|BASELINE" for q in V.neighbours(sid, fam, pt)]
            nd = [dev_dS(sid, c) for c in nbs]; mdS = dev_dS(sid, mc)
            rec["neighbour_dev"] = dict(modal_dev_dS=mdS, neighbour_dev_dS=nd, frac_positive=(float(np.mean(np.array(nd) > 0)) if nd else None))
            g["G7"] = bool(mdS > 0 and (not nd or np.mean(np.array(nd) > 0) >= 2 / 3))
        else: g["G6"] = g["G7"] = False
        rec["gates"] = g; rec["finalist"] = bool(all(g.values()))
        if mc is not None:
            bt = W.paired_boot(pl["r"], pl["rb"]); rec["boot"] = bt; pvals[key] = bt["p_one_sided"]
        else: pvals[key] = 1.0
        FAM[key] = rec
    hm = W.holm(pvals)
    for k, rec in FAM.items(): rec["holm_adj_p"] = hm[k][0]; rec["holm_reject_at_0.05"] = bool(hm[k][1])
    # ---------------------------------------------------------------- 5. strategy-level selection-bias diagnostics
    SB = {}
    for sid in STRATS:
        cids = [c for c, u in U.items() if u[0] == sid]; bcid = f"{sid}|BASELINE"
        Dm = np.column_stack([dev_daily[c] - dev_daily[bcid] for c in cids if c != bcid]); Rm = np.column_stack([dev_daily[c] for c in cids])
        rc = W.reality_check(Dm); pb = W.pbo_cscv(Rm); cidn = [c for c in cids if c != bcid]
        naive = []   # naive in-sample optimiser: argmax train Sharpe over ALL configs of the strategy, per fold, vs baseline OOS
        for fd in W.FOLDS:
            sh_tr = {c: bank.get(c, sid, U[c][3], U[c][4], W.BASE_COST, fd["train"])["sharpe"] for c in cids}
            best = max((c for c in cids if np.isfinite(sh_tr[c])), key=lambda c: sh_tr[c])
            oo = bank.get(best, sid, U[best][3], U[best][4], W.BASE_COST, fd["test"]); bo = bank.get(bcid, sid, V._base(sid), {}, W.BASE_COST, fd["test"])
            naive.append(dict(fold=fd["k"], cfg=best, ins_dS=sh_tr[best] - sh_tr[bcid], oos_dS=oo["sharpe"] - bo["sharpe"]))
        rc["argmax_cfg"] = cidn[rc["argmax"]]; SB[sid] = dict(reality_check=rc, pbo=pb, naive_insample_best=naive, n_configs=len(cids))
    # ---------------------------------------------------------------- 6. FREEZE
    fin = [k for k, r in FAM.items() if r["finalist"]]; combo = {}
    for sid in STRATS:
        fs = [k for k in fin if FAM[k]["sid"] == sid]
        if len(fs) >= 2:
            P = dict(V._base(sid)); x = {}
            for k in fs: _, _, _, Pk, xk = U[FAM[k]["modal_cid"]]; P.update({a: b for a, b in Pk.items() if Pk[a] != V._base(sid)[a]}); x.update(xk)
            r = np.concatenate([bank.get(f"{sid}|COMBO", sid, P, x, W.BASE_COST, fd["test"])["daily"] for fd in W.FOLDS]); rb = np.concatenate([bank.get(f"{sid}|BASELINE", sid, V._base(sid), {}, W.BASE_COST, fd["test"])["daily"] for fd in W.FOLDS])
            combo[sid] = dict(members=fs, P_overrides={a: b for a, b in P.items() if b != V._base(sid)[a]}, x=x, oos_dSharpe=W.sh(r) - W.sh(rb), boot=W.paired_boot(r, rb))
    frozen = dict(code_commit=head, plan="docs/strategy-specs/STAGE_06_ANALYSIS_PLAN.md", selection_record_sha256=sel_hash, finalists=[dict(key=k, sid=FAM[k]["sid"], family=FAM[k]["family"], cid=FAM[k]["modal_cid"], P_overrides={a: b for a, b in U[FAM[k]["modal_cid"]][3].items() if b != V._base(FAM[k]["sid"])[a]}, x=U[FAM[k]["modal_cid"]][4]) for k in fin], combo=combo, baselines=list(STRATS))
    fb = json.dumps(clean(frozen), indent=1, sort_keys=True); (OUT / "frozen_candidates.json").write_text(fb); fsha = hashlib.sha256(fb.encode()).hexdigest()
    # ---------------------------------------------------------------- 7. consumed window, DESCRIPTIVE ONLY (after freeze; never read by any rule above)
    cons = {}
    for sid in STRATS:
        for cid in [f"{sid}|BASELINE"] + sorted({FAM[k]["modal_cid"] for k in FAM if FAM[k]["sid"] == sid and FAM[k]["modal_cid"]}):
            P, x = (V._base(sid), {}) if cid.endswith("BASELINE") else (U[cid][3], U[cid][4]); m = bank.get(cid, sid, P, x, W.BASE_COST, W.CONSUMED)
            cons[cid] = {q: v for q, v in m.items() if q != "daily"}
    res = dict(created_utc=pd.Timestamp.now(tz="UTC").isoformat(), code_commit=head, data=dict(grid="data/s2grid.pkl", panel=meta), counts=dict(configurations=len(U), mom=sum(u[0] == V.MOM for u in U.values()), vex=sum(u[0] == V.VEX for u in U.values()),
               families=len(FAM), selection_decisions=len(FAM) * len(W.FOLDS), simulations_run=bank.n_sims, windows_per_config=len(W.FOLDS) * 2 + 1),
               costs=dict(base=W.BASE_COST, stress_A=W.STRESS_A, stress_B=W.STRESS_B, status="ASSUMED_NOT_OBSERVED"), folds=[dict(k=f["k"], train=[str(A.hdate(f["train"][0])), str(A.hdate(f["train"][1]))], test=[str(A.hdate(f["test"][0])), str(A.hdate(f["test"][1]))]) for f in W.FOLDS],
               baseline_reproduction=repro, families=FAM, selection_bias=SB, frozen_candidates_sha256=fsha, finalists=fin, combo=combo, consumed_window_descriptive=dict(status="CONSUMED_LEGACY: descriptive only, never a criterion", results=cons),
               selection_record_sha256=sel_hash, runtime_s=time.time() - t0)
    (OUT / "stage06_dev_results.json").write_text(json.dumps(clean(res), indent=1))
    with open(OUT / "trials.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(clean(rows))
    print(f"done in {time.time() - t0:.0f}s; sims={bank.n_sims}; finalists={fin}; frozen sha={fsha[:12]}")


if __name__ == "__main__": main()
