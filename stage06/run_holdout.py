"""Stage 06 adjacent-asset holdout (BNB, DOT, ATOM, BCH): SINGLE SHOT. Research only.
Run once, after stage06_dev_results.json and frozen_candidates.json are committed: PYTHONPATH=. scripts/lab python -m stage06.run_holdout
Evaluates the unmodified baseline and each frozen finalist (and combo) with the SAME rules and costs. No parameter, gate or threshold is read from or changed by the result.
The holdout shares calendar time and BTC beta with the development cohort: it tests asset-selection overfitting only, not time/regime overfitting."""
from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path
import numpy as np, pandas as pd
from stage02 import engine as E, analysis as A, data as D, load_grid
from . import variants as V, wf as W
from .run_dev import clean, git

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "docs" / "strategy-specs" / "stage06"
HOLD = ["BNB", "DOT", "ATOM", "BCH"]; RAWH = ROOT / "data" / "s6hold"
CONSIST = dict(dSharpe_min=0.0, trade_frac=W.MIN_TRADE_FRAC, dd_tol=W.G2_DD_TOL)   # predeclared in plan section 7


def build_holdout_syms():
    syms = load_grid.get(); old = D.RAW; D.RAW = RAWH; frames = {}; aud = {}
    try:
        for s in HOLD:
            d, meta = D.load(s); aud[s] = {k: v for k, v in D.audit(s, d, meta).items() if k not in ("gap_list", "jump_list")}
            frames[s] = d.assign(t=d["t"])[["t", "o", "h", "l", "c", "v", "q"]]
    finally: D.RAW = old
    g = E.build_grid(frames, 48648)
    return {"BTC": syms["BTC"], **g}, aud



def evaluate(syms, names, frozen):
    """Baselines + frozen finalists/combo on `names`: returns (results, verdict). Pure function of its inputs (used for the cohort smoke test too)."""
    bank = W.Bank(syms, V.Env(), names); jobs = {}
    for sid in frozen["baselines"]: jobs[f"{sid}|BASELINE"] = dict(sid=sid, P=V._base(sid), x={}, kind="baseline")
    for f in frozen["finalists"]:
        P = dict(V._base(f["sid"])); P.update(f["P_overrides"]); jobs[f["cid"]] = dict(sid=f["sid"], P=P, x=f["x"], kind="finalist", key=f["key"])
    for sid, c in frozen.get("combo", {}).items():
        P = dict(V._base(sid)); P.update(c["P_overrides"]); jobs[f"{sid}|COMBO"] = dict(sid=sid, P=P, x=c["x"], kind="combo", key=f"{sid}|COMBO")
    res = {}
    for cid, j in jobs.items():
        sid = j["sid"]
        try:
            out = {}
            for nm, win in (("dev", W.DEV), ("consumed_descriptive", W.CONSUMED)):
                m = bank.get(cid, sid, j["P"], j["x"], W.BASE_COST, win); out[nm] = {k: v for k, v in m.items() if k != "daily"}
            for nm, cost in (("stress_A", W.STRESS_A), ("stress_B", W.STRESS_B)):
                m = bank.get(cid, sid, j["P"], j["x"], cost, W.DEV); out[nm] = {k: m[k] for k in ("n", "sharpe", "ratio", "max_dd")}
            res[cid] = dict(kind=j["kind"], sid=sid, testable=True, **out)
        except KeyError as e: res[cid] = dict(kind=j["kind"], sid=sid, testable=False, reason=str(e))
    verdict = {}
    for sid in frozen["baselines"]:
        bcid = f"{sid}|BASELINE"; bm = res[bcid]; bd = bank.get(bcid, sid, V._base(sid), {}, W.BASE_COST, W.DEV)["daily"]
        for cid, j in jobs.items():
            if j["sid"] != sid or j["kind"] == "baseline": continue
            r = res[cid]
            if not r["testable"]: verdict[cid] = dict(holdout="NOT_TESTABLE", reason=r["reason"]); continue
            cd = bank.get(cid, sid, j["P"], j["x"], W.BASE_COST, W.DEV)["daily"]; pb = W.paired_boot(cd, bd)
            dS = r["dev"]["sharpe"] - bm["dev"]["sharpe"]
            chk = dict(dSharpe=dS, dSharpe_ok=bool(dS >= CONSIST["dSharpe_min"]), trades=r["dev"]["n"], base_trades=bm["dev"]["n"], trades_ok=bool(r["dev"]["n"] >= CONSIST["trade_frac"] * bm["dev"]["n"]),
                       max_dd=r["dev"]["max_dd"], base_max_dd=bm["dev"]["max_dd"], dd_ok=bool(r["dev"]["max_dd"] >= bm["dev"]["max_dd"] - CONSIST["dd_tol"]),
                       stressA_dSharpe=r["stress_A"]["sharpe"] - bm["stress_A"]["sharpe"], stressB_dSharpe=r["stress_B"]["sharpe"] - bm["stress_B"]["sharpe"], paired_boot=pb)
            chk["holdout"] = "CONSISTENT" if (chk["dSharpe_ok"] and chk["trades_ok"] and chk["dd_ok"]) else "INCONSISTENT"; verdict[cid] = chk
    return res, verdict


def main():
    head = git("rev-parse", "HEAD"); dirty = [l for l in git("status", "--porcelain", "--untracked-files=no").splitlines() if l.strip()]
    if dirty: sys.exit("refusing to run: tracked files modified:\n" + "\n".join(dirty))
    fz = (OUT / "frozen_candidates.json").read_bytes(); dev = json.loads((OUT / "stage06_dev_results.json").read_text())
    if hashlib.sha256(fz).hexdigest() != dev["frozen_candidates_sha256"]: sys.exit("frozen_candidates.json does not match the dev results hash")
    if git("ls-files", "docs/strategy-specs/stage06/frozen_candidates.json") == "": sys.exit("frozen file is not committed")
    frozen = json.loads(fz); syms, aud = build_holdout_syms()
    res, verdict = evaluate(syms, HOLD, frozen)
    out = dict(head=head, frozen_candidates_sha256=hashlib.sha256(fz).hexdigest(), assets=HOLD, windows=dict(dev=[str(A.hdate(W.DEV[0])), str(A.hdate(W.DEV[1]))], consumed=[str(A.hdate(W.CONSUMED[0])), str(A.hdate(W.CONSUMED[1]))]),
               data_audit=aud, criteria=CONSIST, results=res, verdict=verdict, status="SINGLE_SHOT: not re-run, not used to modify any candidate",
               caveat="same calendar period and BTC beta as development cohort; cross-sectional (asset) holdout only; 4 assets; small trade counts")
    (OUT / "stage06_holdout_results.json").write_text(json.dumps(clean(out), indent=1))
    for cid, v in verdict.items(): print(cid, v.get("holdout"), {k: (round(x, 3) if isinstance(x, float) else x) for k, x in v.items() if k in ("dSharpe", "trades", "base_trades", "max_dd", "base_max_dd")})
    for cid in res:
        if res[cid].get("testable"): print(cid, "dev", {k: round(res[cid]["dev"][k], 3) for k in ("n", "sharpe", "max_dd", "ratio")}, "consumed", {k: round(res[cid]["consumed_descriptive"][k], 3) for k in ("n", "sharpe", "max_dd")})


if __name__ == "__main__": main()
