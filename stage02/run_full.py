"""Full Stage 02 study. Executes the frozen plan; no parameter changes. Output: docs/strategy-specs/stage02/*"""
import json, math, time, copy, sys
from pathlib import Path
import numpy as np, pandas as pd
from . import engine as E, analysis as A, load_grid
OUT = Path(__file__).resolve().parents[1] / "docs" / "strategy-specs" / "stage02"; OUT.mkdir(parents=True, exist_ok=True)
syms = load_grid.get()
BASE = (0.001, 0.0005); STRESS = {"stressA_fee0.002_adv0.001": (0.002, 0.001), "stressB_fee0.001_adv0.002": (0.001, 0.002)}
MULTS = [0.0, 0.5, 1.0, 2.0, 3.0]
SIDS = list(E.DEFAULTS)
lab = A.btc_regime_by_day(syms)
_cache = {}
def C(sid, P, f, s):
    k = (sid, json.dumps(P, sort_keys=True), f, s)
    if k not in _cache: _cache[k] = A.cands_for(sid, P, syms, f, s)
    return _cache[k]
def ratio_of(tr): return float(sum(t["pnl"] for t in tr) / sum(t["reserved_risk"] for t in tr)) if tr else None
def jsonable(o):
    if isinstance(o, (np.floating, np.integer)): return o.item()
    if isinstance(o, np.ndarray): return o.tolist()
    if isinstance(o, (np.bool_,)): return bool(o)
    return str(o)
import subprocess, hashlib, platform
def _git(*a): return subprocess.run(["git", *a], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1]).stdout.strip()
_side = sorted((Path(__file__).resolve().parents[1] / "data" / "s2raw").glob("*/*.json"))
_dm = hashlib.sha256("".join(json.loads(x.read_text())["sha256"] for x in _side).encode()).hexdigest()
R = {"meta": dict(code_commit=_git("rev-parse", "HEAD"), source_dirty=bool(_git("status", "--porcelain", "stage02", "tests/stage02")), data_files=len(_side),
        data_manifest_sha256=_dm, data_checksum_status={k: sum(1 for x in _side if json.loads(x.read_text())["status"] == k) for k in ("verified", "checksum_missing", "CHECKSUM_MISMATCH")},
        python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__, rules_version="0.1.0-draft", plan="docs/strategy-specs/STAGE_02_ANALYSIS_PLAN.md", windows={k: [str(A.hdate(a)), str(A.hdate(b))] for k, (a, b) in A.WINDOWS.items()},
        baseline_costs=dict(fee=BASE[0], adverse=BASE[1], status="ASSUMED_NOT_OBSERVED"), lot=E.LOT, min_notional=E.MIN_NOTIONAL, bootstrap=dict(block_days=14, reps=10000, seed=20261118))}
trade_rows = []; eq_rows = []
def sim_all(sid, P, f, s, win, **kw): return A.run_window(C(sid, P, f, s), syms, win, f, s, **kw)
for sid in SIDS:
    t0 = time.time(); P = E.DEFAULTS[sid]; out = {"params": P}
    # ---- funnel
    st = {}; A.cands_for(sid, P, syms, *BASE, stats=st); out["funnel_full_period"] = st
    # ---- baseline windows
    out["windows"] = {}; res = {}
    for w in A.WINDOWS:
        r = sim_all(sid, P, *BASE, w); res[w] = r; m, rets = A.full_metrics(r)
        m["sharpe_ci95_block_boot"] = A.sharpe_boot(rets)
        m["ratio_bootstrap"] = A.block_ratio_boot(r["trades"], *A.WINDOWS[w])
        out["windows"][w] = m
        d = A.daily_equity(r); ws = A.WINDOWS[w][0]
        for k, v in enumerate(d): eq_rows.append((sid, w, str(A.hdate(ws + 24 * k + 23).date()), float(v)))
        for t in r["trades"]: trade_rows.append(dict(t, window=w, entry_utc=str(A.hdate(t["entry_hour"])), exit_utc=str(A.hdate(t["exit_hour"])),
                              regime=lab[t["entry_hour"] // 24], tf_h=t["tf"]))
    tv = res["train"]["trades"] + res["validation"]["trades"]
    out["pooled_train_validation"] = dict(trade_metrics=A.trade_metrics(tv), ratio_bootstrap_note="see subperiods")
    # pooled bootstrap over contiguous train+validation (concatenate day axes)
    ws0, we1 = A.WINDOWS["train"][0], A.WINDOWS["validation"][1]
    out["pooled_train_validation"]["ratio_bootstrap"] = A.block_ratio_boot(tv, ws0, we1)
    # ---- F8 subperiods (equal-length thirds of train+validation by entry time)
    edges = np.linspace(ws0, we1, 4); sp = []
    for a, b in zip(edges[:-1], edges[1:]):
        sub = [t for t in tv if a <= t["entry_hour"] < b]; sp.append(dict(start=str(A.hdate(int(a))), end=str(A.hdate(int(b))), n=len(sub), ratio=ratio_of(sub)))
    out["F8_subperiods"] = sp
    # ---- cost sensitivity
    cs = {}
    for name, (f, s) in dict(baseline=BASE, **STRESS).items():
        cs[name] = {w: (lambda m: dict(n=m["n"], ratio=m.get("ratio"), expectancy_R=m.get("expectancy_R"), total_return=m["total_return"], sharpe=m["sharpe"], max_dd=m["max_dd"]))(A.full_metrics(sim_all(sid, P, f, s, w))[0]) for w in A.WINDOWS}
    out["cost_stress"] = cs
    grid = {}
    for mlt in MULTS:
        f, s = BASE[0] * mlt, BASE[1] * mlt
        grid[str(mlt)] = {w: (lambda m: dict(n=m["n"], ratio=m.get("ratio"), total_return=m["total_return"]))(A.full_metrics(sim_all(sid, P, f, s, w))[0]) for w in A.WINDOWS}
    out["cost_multiple_grid"] = grid
    # ---- neighbours & ablations (single-parameter)
    nb = {}
    variants = {"CRY-MOM-101": [("lookback", 90), ("lookback", 270), ("thr", 1.0), ("thr", 1.5)],
                "CRY-REV-102": [("rsi_thr", 5.0), ("rsi_thr", 12.0), ("drop_k", 1.5), ("drop_k", 2.5)],
                "CRY-VEX-103": [("tr_k", 1.5), ("tr_k", 2.2), ("vol_k", 1.5), ("vol_k", 2.5), ("donch", 36), ("donch", 72)]}[sid]
    for k, v in variants:
        P2 = dict(P, **{k: v}); key = f"{k}={v}"; nb[key] = {}
        for w in ("train", "validation"):
            r = sim_all(sid, P2, *BASE, w); m = A.trade_metrics(r["trades"]); nb[key][w] = dict(n=m["n"], ratio=m.get("ratio"))
    out["neighbours"] = nb
    abl = {"CRY-MOM-101": ("placebo_M<=0", dict(placebo=True)), "CRY-REV-102": ("no_SMA300_filter", dict(trend=False)), "CRY-VEX-103": ("no_volume_condition", dict(vol_k=None))}[sid]
    out["ablation"] = {"name": abl[0]}
    for w in ("train", "validation"):
        P2 = dict(P, **abl[1])
        if sid == "CRY-MOM-101": pass
        r = sim_all(sid, P2, *BASE, w); m = A.trade_metrics(r["trades"]); out["ablation"][w] = dict(n=m["n"], ratio=m.get("ratio"), expectancy_R=m.get("expectancy_R"))
    # ---- random-entry null
    out["null"] = {}
    for w in ("train", "validation"):
        pool = A.unit_pool(sid, P, syms, *BASE, w); out["null"][w] = A.null_test(res[w]["trades"], pool)
    # ---- F6 outlier removal
    def drop_best(tr):
        k = math.ceil(0.05 * len(tr)); keep = sorted(tr, key=lambda t: t["R"])[:-k] if k and len(tr) > k else []
        return ratio_of(keep), k
    out["F6"] = {"validation": drop_best(res["validation"]["trades"]), "pooled_train_validation": drop_best(tv)}
    # ---- breakdowns by year / regime / symbol (baseline, all three windows)
    allt = [dict(t, window=w) for w in A.WINDOWS for t in res[w]["trades"]]
    yr = {}
    for w in A.WINDOWS:
        d = A.daily_equity(res[w]); ser = np.concatenate([[10000.0], d]); rets = ser[1:] / ser[:-1] - 1; ws = A.WINDOWS[w][0]
        for k, r_ in enumerate(rets):
            y = A.hdate(ws + 24 * k).year; yr.setdefault(y, {"growth": 1.0, "days": 0}); yr[y]["growth"] *= 1 + r_; yr[y]["days"] += 1
    byyear = {}
    for y, v in sorted(yr.items()):
        tt = [t for t in allt if A.hdate(t["entry_hour"]).year == y]
        byyear[y] = dict(days=v["days"], partial_year=v["days"] < 365, return_chained=v["growth"] - 1, n_trades=len(tt), ratio=ratio_of(tt), win_rate=(float(np.mean([t["pnl"] > 0 for t in tt])) if tt else None))
    out["by_year"] = byyear
    reg = {}
    for g in sorted(set(lab[t["entry_hour"] // 24] for t in allt)):
        tt = [t for t in allt if lab[t["entry_hour"] // 24] == g]; reg[g] = dict(n=len(tt), ratio=ratio_of(tt), expectancy_R=float(np.mean([t["R"] for t in tt])), win_rate=float(np.mean([t["pnl"] > 0 for t in tt])))
    day_lab = lab[A.WINDOWS["train"][0] // 24: A.WINDOWS["final"][1] // 24]
    out["by_regime_trades"] = reg; out["regime_day_share"] = {g: float(np.mean(day_lab == g)) for g in sorted(set(day_lab))}
    out["by_symbol"] = {sy: dict(n=len([t for t in allt if t["symbol"] == sy]), ratio=ratio_of([t for t in allt if t["symbol"] == sy])) for sy in E.SYMS if any(t["symbol"] == sy for t in allt)}
    # ---- warm-up sensitivity
    P3 = dict(P, warm=400); out["warmup_400_sensitivity"] = {w: (lambda m: dict(n=m["n"], ratio=m.get("ratio")))(A.trade_metrics(sim_all(sid, P3, *BASE, w)["trades"])) for w in A.WINDOWS}
    R[sid] = out; print(sid, "done", round(time.time() - t0), "s", flush=True)
# ---- combined book (handoff order, shared 3-position / 3% risk)
allc = sum([C(sid, E.DEFAULTS[sid], *BASE) for sid in SIDS], [])
R["combined_book"] = {}
for w in A.WINDOWS:
    r = A.run_window(allc, syms, w, *BASE); m, rets = A.full_metrics(r); m["sharpe_ci95_block_boot"] = A.sharpe_boot(rets)
    m["by_strategy"] = {sid: A.trade_metrics([t for t in r["trades"] if t["strategy"] == sid]) for sid in SIDS}; R["combined_book"][w] = m
# ---- benchmarks
R["benchmarks"] = {}
for w in A.WINDOWS:
    R["benchmarks"][w] = {}
    for kind in ("EW_BH", "BTC_BH", "BTC_SMA200"):
        d = A.bench_daily_equity(syms, w, *BASE, kind); m = A.eq_metrics(d); r_ = m.pop("daily_returns"); m["sharpe_ci95_block_boot"] = A.sharpe_boot(r_); R["benchmarks"][w][kind] = m
R["data_audit"] = json.loads((Path(__file__).parent / "audit.json").read_text())
(OUT / "results.json").write_text(json.dumps(R, indent=1, default=jsonable))
pd.DataFrame(trade_rows).to_csv(OUT / "trades_baseline.csv", index=False)
pd.DataFrame(eq_rows, columns=["strategy", "window", "date_utc", "equity"]).to_csv(OUT / "daily_equity_baseline.csv", index=False)
print("written", OUT)
