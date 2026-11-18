"""Stage 06 cost sensitivity (reporting only): pooled walk-forward-TEST-fold results for baselines and every family's modal config at 0x, 0.5x, 1x, 2x, 3x of the
baseline per-side cost (fee .001, adverse .0005) and at handoff stress A/B. Candidates are rebuilt for each cost (cost gate and sizing depend on cost).
Run: PYTHONPATH=. scripts/lab python -m stage06.run_cost"""
import json, sys
import numpy as np
from stage02 import load_grid
from . import variants as V, wf as W
from .run_dev import build_env, clean, OUT

def main():
    dev = json.loads((OUT / "stage06_dev_results.json").read_text()); syms = load_grid.get(); env, _ = build_env(); U = V.universe(); bank = W.Bank(syms, env)
    cids = {}
    for sid in (V.MOM, V.VEX):
        cids[f"{sid}|BASELINE"] = (sid, V._base(sid), {})
    for k, f in dev["families"].items():
        if f["modal_cid"]: sid, fam, pt, P, x = U[f["modal_cid"]]; cids[f["modal_cid"]] = (sid, P, x)
    mult = {"0x": 0.0, "0.5x": 0.5, "1x": 1.0, "2x": 2.0, "3x": 3.0}; out = {}
    for cid, (sid, P, x) in cids.items():
        row = {}
        for nm, m in mult.items():
            cost = (W.BASE_COST[0] * m, W.BASE_COST[1] * m)
            r = np.concatenate([bank.get(cid, sid, P, x, cost, fd["test"])["daily"] for fd in W.FOLDS]); n = sum(bank.get(cid, sid, P, x, cost, fd["test"])["n"] for fd in W.FOLDS)
            row[nm] = dict(sharpe=W.sh(r), total_return=float(np.prod(1 + r) - 1), mdd=W.mdd(r), n=int(n))
        for nm, cost in (("stressA", W.STRESS_A), ("stressB", W.STRESS_B)):
            r = np.concatenate([bank.get(cid, sid, P, x, cost, fd["test"])["daily"] for fd in W.FOLDS]); row[nm] = dict(sharpe=W.sh(r), total_return=float(np.prod(1 + r) - 1), mdd=W.mdd(r))
        out[cid] = row
    (OUT / "stage06_cost_sensitivity.json").write_text(json.dumps(clean(out), indent=1))
    for cid, row in out.items(): print(cid.split("|", 1)[1][:44].ljust(44), " ".join(f"{k}:{row[k]['sharpe']:+.2f}" for k in mult), f"A:{row['stressA']['sharpe']:+.2f} B:{row['stressB']['sharpe']:+.2f}")
if __name__ == "__main__": main()
