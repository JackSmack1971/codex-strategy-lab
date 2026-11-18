"""Generate STAGE_06 report + handoff from results JSON (no new analysis)."""
import csv, json
from pathlib import Path
from . import variants as V
ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "docs" / "strategy-specs"; S6 = OUT / "stage06"
d = json.loads((S6 / "stage06_dev_results.json").read_text()); h = json.loads((S6 / "stage06_holdout_results.json").read_text()); c = json.loads((S6 / "stage06_cost_sensitivity.json").read_text())
rows = list(csv.DictReader(open(S6 / "trials.csv"))); FAM = d["families"]; ver = h["verdict"]
sname = lambda s: s.replace("CRY-", "")
GATE_TXT = {"G1": "dSharpe<+0.15", "G2": "worst-fold DD worse >1pp", "G3": "trades<0.75x", "G4": "turnover>1.25x", "G5": "unstable/never selected (<3/5 folds)", "G6": "not cost-robust", "G7": "neighbours/full-DEV not positive"}
def det(k, f):
    if f["finalist"]:
        v = ver.get(f["modal_cid"], {})
        if v.get("holdout") == "INCONSISTENT": return "REJECT", f"passed G1-G7 but adjacent-asset holdout inconsistent (dSharpe {v['dSharpe']:+.3f}, maxDD {v['max_dd']:.3f} vs {v['base_max_dd']:.3f})"
        return "UNVERIFIED_HYPOTHESIS", "passed G1-G7; Holm p=%.2f; not testable on holdout (needs cross-section >=5 assets)" % f["holm_adj_p"]
    fails = [GATE_TXT[g] for g, ok in f["gates"].items() if not ok]
    if f["switches"] == 0: return "REJECT", "baseline retained in all 5 folds (no train-supported improvement)"
    return "REJECT", "fails: " + "; ".join(fails)
D = {k: det(k, f) for k, f in FAM.items()}
L = []; P = L.append
P("# STAGE 06 - Limited, predeclared changes to eligible strategies: validation report\n")
P("Research only. No orders, credentials or execution. Baselines, `REPORT.md`, `results/`, `PREREGISTRATION.md` and the Stage 01-05 handoffs are unchanged.\n")
P("## Headline\n")
P("**KEEP BASELINE for both CRY-MOM-101 and CRY-VEX-103. No candidate change is supported by independent validation.**\n")
P("* 71 configurations (34 MOM, 37 VEX) in 18 predeclared families were tested, each under assumed costs (15bp/side) in every trial. Three MOM families passed every walk-forward gate (ENTRY_CONFIRM confirm=3, STOP 2.5/4.0, FACTOR_OVERLAY EQ3).")
P("* None survives multiple-testing correction (Holm over 18 families: adjusted p 0.39, 0.51, 1.00). Selection skill is not distinguishable from chance (PBO 0.47 MOM / 0.46 VEX; reality check p=0.12 / 0.83).")
P("* On the never-run adjacent assets (BNB, DOT, ATOM, BCH; single shot) ENTRY_CONFIRM was neutral-to-negative (dSharpe -0.015) and STOP clearly worse (dSharpe -0.215, maxDD -20.6% vs -12.8%): both REJECT. FACTOR_OVERLAY and the combo cannot be tested there: UNVERIFIED_HYPOTHESIS.")
P("* **New adverse finding about the baselines:** on the adjacent assets MOM baseline Sharpe is -0.20 (3 of 4 assets lose) and VEX baseline Sharpe -1.71 with maxDD -46.5% (loses on all 4 assets). VEX is also cost-fragile (Sharpe +1.78 at zero cost, +0.64 at 1x, -0.20 at 2x). Neither baseline generalises beyond the survivor-selected cohort on this evidence.")
P("* Limits: there is no untouched temporal holdout (2025-11-17..2026-11-17 is CONSUMED_LEGACY; DEV history was seen in Stages 02-05). The adjacent-asset holdout shares calendar time and BTC beta and has few trades. Costs, venue and fills are assumed. Thresholds are judgement-based and uncalibrated.\n")
P("![Walk-forward](stage06/stage06_walkforward.png)\n")
P("## 0. Design, splits and acceptance thresholds (committed before any real-data run: `STAGE_06_ANALYSIS_PLAN.md`, commit 8da94ed)\n")
P("* Eligible: MOM-101, VEX-103. REV-102 excluded (Stage 02 REJECT / Stage 03 NOT_ELIGIBLE).")
P("* DEV 2021-11-17..2025-11-17; anchored folds, test = 6 months from 2023-05-17 (5 folds: " + "; ".join(f"{f['test'][0][:10]}..{f['test'][1][:10]}" for f in d["folds"]) + "). Train = [2021-11-17, test start). Every window is a fresh $10,000 book, force-closed at window end.")
P("* Baseline reproduction (asserted before any candidate ran): " + "; ".join(f"{k.replace('CRY-','')}: n={v['n']}, ratio {v['ratio']:+.4f}, match={v['match']}" for k, v in d["baseline_reproduction"].items()) + ".")
P("* Selection on TRAIN only: score = neighbour-smoothed dSharpe; constraints trades>=0.75x, maxDD within 2pp, turnover<=1.25x; switch only if score>=0.10 (ordered) / 0.20 (categorical). Gates G1-G7 on pooled OOS: dSharpe>=+0.15; worst-fold DD within 1pp; trades>=0.75x; turnover<=1.25x; modal config selected in >=3/5 folds; positive under cost stress A and B; positive on full DEV with >=2/3 positive neighbours.")
P("* ACCEPT needs finalist + Holm-adjusted p<0.05 + consistent holdout (dSharpe>=0, trades>=0.75x, DD within 1pp). Otherwise UNVERIFIED_HYPOTHESIS or REJECT. Block bootstrap: 14-day blocks, 10,000 reps, seed 20261118.")
P(f"* Configurations tested: {d['counts']['configurations']} x {d['counts']['windows_per_config']} windows ({d['counts']['simulations_run']} simulations incl. cost scenarios); {d['counts']['selection_decisions']} walk-forward selection decisions; 18 families -> Holm family size 18 (19 with the combo).\n")
P("## A. Baseline versus candidate (pooled walk-forward OOS, baseline costs)\n")
P("| family | switched folds | modal config | OOS Sharpe cand / base | dSharpe | worst-fold maxDD cand / base | trades cand / base | turnover cand / base | raw p | Holm p |\n|---|---|---|---|---|---|---|---|---|---|")
for k, f in FAM.items():
    p = f["pooled"]; mc = (f["modal_cid"] or "-").split("|", 2)[-1]
    P(f"| {sname(k.replace('|',' '))} | {f['switches']}/5 | {mc} | {p['sharpe']:+.2f} / {p['base_sharpe']:+.2f} | {p['dSharpe']:+.2f} | {p['worst_fold_mdd']:.3f} / {p['base_worst_fold_mdd']:.3f} | {p['n']} / {p['base_n']} | {p['turnover']:.1f} / {p['base_turnover']:.1f} | {f.get('boot',{}).get('p_one_sided','n/a') if not isinstance(f.get('boot',{}).get('p_one_sided'),float) else round(f['boot']['p_one_sided'],3)} | {f['holm_adj_p']:.2f} |")
P("\nSample: MOM 116 baseline OOS trades, VEX 671, over 915 OOS days. Baseline pooled OOS Sharpe MOM +1.07 / VEX +0.64 is itself noisy (Stage 02 bootstrap lower bounds were all < 0).\n")
P("## B. Walk-forward results (per fold, finalist families)\n")
for k in [k for k, f in FAM.items() if f["finalist"]] + ["CRY-VEX-103|FACTOR_OVERLAY"]:
    f = FAM[k]; P(f"**{sname(k)}** (train-only selection; in-sample dS of chosen vs OOS dS)\n\n| fold | chosen | train-selection score | in-sample dS | OOS dS | OOS trades cand / base |\n|---|---|---|---|---|---|")
    for x in f["folds"]:
        ch = ("baseline" if not x["switched"] else json.dumps(x["chosen"])); sc = "n/a" if x["score"] is None else f"{x['score']:+.2f}"
        P(f"| {x['fold']} | {ch} | {sc} | {x['ins_dS']:+.2f} | {x['oos_dS']:+.2f} | {x['oos']['n']} / {x['base_oos']['n']} |")
    P(f"\nDegradation (switched folds): in-sample dS {f['degradation']['mean_ins_dS_switched']:+.2f} -> OOS {f['degradation']['mean_oos_dS_switched']:+.2f}. Paired bootstrap dSharpe 95% CI " + (f"[{f['boot']['dSharpe_ci95'][0]:+.2f}, {f['boot']['dSharpe_ci95'][1]:+.2f}]" if 'boot' in f else "n/a") + ".\n")
P("Fold-level OOS windows hold only 11-31 MOM trades, so single folds are noise-dominated; only pooled results are interpreted.\n")
P("**Selection-bias diagnostics (per strategy, all configurations on full DEV vs baseline):**\n")
P("| strategy | K configs | reality-check p (best dev config) | PBO (CSCV, S=8, 70 splits) | median OOS rank of IS-best |\n|---|---|---|---|---|")
for s, v in d["selection_bias"].items():
    P(f"| {sname(s)} | {v['n_configs']} | {v['reality_check']['p']:.2f} ({v['reality_check']['argmax_cfg'].split('|',1)[1]}) | {v['pbo']['pbo']:.2f} | {v['pbo']['median_oos_rel_rank']:.2f} |")
P("\nNaive optimiser (best train Sharpe among ALL configs of the strategy, per fold): MOM in-sample dS +0.56..+1.04 vs OOS -1.45..+0.52 (mean " + f"{sum(n['oos_dS'] for n in d['selection_bias']['CRY-MOM-101']['naive_insample_best'])/5:+.2f}" + "); VEX in-sample +0.35..+1.03 vs OOS " + f"mean {sum(n['oos_dS'] for n in d['selection_bias']['CRY-VEX-103']['naive_insample_best'])/5:+.2f}" + ". This is why highest-in-sample-Sharpe was never the selection rule.\n")
P("## C. Parameter stability (full-DEV dSharpe vs baseline for every point; neighbours)\n")
P("| family | point | DEV n | DEV Sharpe | dS vs base |\n|---|---|---|---|---|")
base_dev = {r["strategy"]: float(r["sharpe"]) for r in rows if r["window"] == "dev" and r["family"] == "BASELINE"}
for r in rows:
    if r["window"] == "dev" and r["family"] != "BASELINE":
        P(f"| {sname(r['strategy'])} {r['family']} | {r['point']} | {r['n']} | {float(r['sharpe']):+.2f} | {float(r['sharpe'])-base_dev[r['strategy']]:+.2f} |")
P("\nModal-config neighbour check (G7): " + "; ".join(f"{sname(k)} modal dS {f['neighbour_dev']['modal_dev_dS']:+.2f}, neighbours {[round(x,2) for x in f['neighbour_dev']['neighbour_dev_dS']]}" for k, f in FAM.items() if f.get('neighbour_dev') and f['finalist']) + ". STOP passes G7 only marginally (one neighbour exactly 0.00 of three). Categorical families (FACTOR_OVERLAY, REGIME_ACTIVATION) have no grid neighbours, so G7's neighbour part is vacuous for them; the higher 0.20 selection margin is the only compensation.\n")
P("## D. Cost sensitivity (pooled OOS test folds; per-side fee+adverse multiples; modal config held fixed across folds, so slightly optimistic)\n")
P("| config | 0x | 0.5x | 1x | 2x | 3x | stress A | stress B |\n|---|---|---|---|---|---|---|---|")
for cid, row in c.items(): P(f"| {sname(cid.replace('|',' '))[:60]} | " + " | ".join(f"{row[k]['sharpe']:+.2f}" for k in ('0x', '0.5x', '1x', '2x', '3x', 'stressA', 'stressB')) + " |")
P("\nMOM variants stay positive to 3x cost. VEX baseline and the VEX variants turn non-positive or ~0 at 2x-3x: VEX's edge is a thin gross edge consumed by turnover, and costs are assumed, not observed.\n")
P("## E. Holdout evaluation (adjacent assets BNB, DOT, ATOM, BCH; single shot; DEV window 2021-11-17..2025-11-17)\n")
P("Data audit: 48,641 hourly rows per asset, 7 missing bars (3 gap events), no OHLC violations. Holdout is cross-sectional only (same calendar time and BTC beta), 4 assets.\n")
P("| config | trades | Sharpe | ratio | maxDD | dSharpe vs baseline | stress A / B dSharpe | holdout verdict |\n|---|---|---|---|---|---|---|---|")
for cid, r in h["results"].items():
    if not r["testable"]: P(f"| {sname(cid.replace('|',' '))[:60]} | - | - | - | - | - | - | NOT_TESTABLE (factor cross-section) |"); continue
    v = ver.get(cid); dv = f"{v['dSharpe']:+.3f}" if v else "-"; st = f"{v['stressA_dSharpe']:+.2f} / {v['stressB_dSharpe']:+.2f}" if v else "-"
    P(f"| {sname(cid.replace('|',' '))[:60]} | {r['dev']['n']} | {r['dev']['sharpe']:+.2f} | {r['dev']['ratio']:+.3f} | {r['dev']['max_dd']:.3f} | {dv} | {st} | {v['holdout'] if v else 'baseline'} |")
P("\nPost-hoc per-asset diagnostic (descriptive; changes no determination): MOM baseline ratio BNB +0.14 (35 trades), DOT -0.24, ATOM -0.21, BCH -0.62; VEX loses on all four (-0.12 to -0.41). Buy-and-hold log return over DEV: BNB +0.46, BCH -0.21, ATOM -2.32, DOT -2.68. Consumed-window numbers (CONSUMED_LEGACY, descriptive only) are in the JSON files and were never a criterion: MOM baseline Sharpe -0.47, its three finalists -0.32 / -0.20 / -0.34, VEX baseline +0.47, VEX factor overlay -1.51.\n")
P("## F. Determination\n")
P("| candidate family | determination | reason |\n|---|---|---|")
for k, (dd, why) in D.items(): P(f"| {sname(k.replace('|',' '))} | **{dd}** | {why} |")
P("| MOM combo (confirm=3 + stop 2.5/4.0 + factor EQ3) | **UNVERIFIED_HYPOTHESIS** | built after seeing which families passed; raw p=0.0044, Holm over 19 hypotheses ~0.084; modal config fixed across folds uses later folds' selections (optimistic); untestable on holdout |")
P("\n**CRY-MOM-101: KEEP BASELINE.** **CRY-VEX-103: KEEP BASELINE** (no candidate improved it; the baseline itself fails the adjacent-asset holdout and is cost-fragile, supporting Stage 03's shadow-only stance). Counts: 0 ACCEPT_CANDIDATE, 2 UNVERIFIED_HYPOTHESIS (FACTOR_OVERLAY on MOM; combo), 17 REJECT (15 families that failed gates and 2 finalists that failed the holdout: ENTRY_CONFIRM, STOP) - 18 families + 1 combo = 19 determinations.\n")
P("Retained as unverified hypotheses only: MOM entry persistence (K=3) and wider trailing stop (4.0 ATR with 2.5 ATR initial) are not supported but not refuted in direction; the first was neutral on the holdout. The Stage 05 factor overlay has low prior (Stage 05 found no demonstrated factor skill; VEX overlay was -1.51 Sharpe in the consumed window).\n")
P("## Limitations and unresolved concerns\n")
for x in ["No untouched temporal holdout; walk-forward folds 4-5 overlap the Stage 02 validation window and the whole DEV history informed Stage 01-05 design.", "Adjacent-asset holdout shares calendar time/BTC beta; 4 assets; MOM 71 trades, so a real improvement of ~0.2 Sharpe would not be detectable (dSharpe CI width ~0.9).", "Costs (15bp/side), fills, lot sizes and venue are assumed; stop-through slippage is not modelled beyond open-gap fills.", "Gate thresholds (+0.15, 0.75x, 1.25x, 1pp, 0.10/0.20 margins) are judgement-based, not calibrated.", "Factor overlay uses Stage 05 scores that exist only from 2022-05-01 (baseline rule applies before); not holdout-testable.", "Regime tags are the uncalibrated Stage 04 rules; REGIME_ACTIVATION never beat the baseline in train and was never selected.", "Stop changes alter risk-based position size (fixed 1% risk / tighter stop = larger notional); Sharpe comparisons embed that.", "Survivor-selected cohort; the adjacent-asset result is direct evidence against generalisation of both baselines.", "`research/validation/adjudicate.py` not run; preregistration not frozen (needs independent review). Ledger: 18 hypotheses registered."]: P("* " + x)
P("\n## Files\n\n`stage06/` (code), `tests/stage06/` (14 offline tests), `docs/strategy-specs/stage06/`: `stage06_dev_results.json`, `frozen_candidates.json` (sha256 " + d["frozen_candidates_sha256"] + "), `stage06_holdout_results.json`, `stage06_cost_sensitivity.json`, `trials.csv` (every configuration x window), `diag_holdout_posthoc.txt`, `stage06_walkforward.png`. Reproduce: `PYTHONPATH=. scripts/lab python -m stage06.run_dev` (~45 s, deterministic).")
(OUT / "STAGE_06_VALIDATION_REPORT.md").write_text("\n".join(L) + "\n")
dets = {k: dict(determination=a, reason=b) for k, (a, b) in D.items()}; dets["MOM|COMBO"] = dict(determination="UNVERIFIED_HYPOTHESIS", reason="post-selection union; untestable on holdout")
hand = dict(handoff_type="STAGE_06_HANDOFF", schema_version="1.0.0", status="RESEARCH_ONLY_NO_EXECUTION", created="2026-11-18", code_commit=d["code_commit"],
  inputs=["STAGE_01_HANDOFF.v2.json", "STAGE_02_HANDOFF.json", "STAGE_03_HANDOFF.json", "STAGE_04_HANDOFF.json", "STAGE_05_HANDOFF.json"],
  decision=dict(overall="KEEP BASELINE", accepted_candidates=[], per_strategy={"CRY-MOM-101": "KEEP BASELINE", "CRY-VEX-103": "KEEP BASELINE", "CRY-REV-102": "NOT_EVALUATED (rejected/ineligible)"}),
  frozen_model_specifications=dict(rules_version="0.1.0 (unchanged)", baselines={s: V._base(s) for s in ("CRY-MOM-101", "CRY-VEX-103")}, costs=dict(fee=0.001, adverse=0.0005, status="ASSUMED_NOT_OBSERVED"),
    risk="Stage 01 sizing for evaluation; Stage 03 risk budgets (half size, paper-forward only for MOM, shadow-only for VEX) remain the operating policy", eligibility=dict(MOM="ELIGIBLE_CONTINUED_RESEARCH_PAPER_FORWARD_ONLY", VEX="CONDITIONAL_SHADOW_PAPER_ONLY (adverse new evidence)", REV="NOT_ELIGIBLE_SHADOW_ONLY"),
    unverified_hypotheses_for_forward_test=[dict(id="MOM-FACTOR-OVERLAY-EQ3", change="entry allowed only if Stage 05 EQ3 composite at last completed day >= 0 (baseline applies when undefined)", status="UNVERIFIED_HYPOTHESIS"), dict(id="MOM-COMBO", change=d["combo"].get("CRY-MOM-101"), status="UNVERIFIED_HYPOTHESIS")],
    rejected=[k for k, v in dets.items() if v["determination"] == "REJECT"]),
  counts=d["counts"], determinations=dets, splits=dict(dev=["2021-11-17", "2025-11-17"], folds=d["folds"], consumed_window="CONSUMED_LEGACY descriptive only", holdout=dict(assets=h["assets"], status="SINGLE_SHOT done", caveat=h["caveat"])),
  thresholds=dict(G1_dSharpe=0.15, trades_frac=0.75, turnover_mult=1.25, dd_tol_fold=0.01, selection_dd_tol=0.02, delta_ordered=0.10, delta_categorical=0.20, holm_alpha=0.05, bootstrap=dict(block_days=14, reps=10000, seed=20261118)),
  key_measurements=dict(selection_bias=d["selection_bias"], holdout_verdicts=ver, baseline_holdout={k: dict(n=v["dev"]["n"], sharpe=v["dev"]["sharpe"], max_dd=v["dev"]["max_dd"]) for k, v in h["results"].items() if v["kind"] == "baseline"}, vex_cost_fragility=c["CRY-VEX-103|BASELINE"]),
  ledger=dict(registered="18 hypotheses fam-crypto-stage06-v1 (REGISTERED)", preregistration_frozen=False, adjudicate_py_run=False), frozen_candidates_sha256=d["frozen_candidates_sha256"],
  unresolved=["no untouched temporal holdout: forward paper evaluation from 2026-11-18 (>=6 months, >=100 trades) is the only clean test", "baselines fail the adjacent-asset holdout; decide whether VEX should remain even shadow-only before forward test", "execution venue, observed fees/spreads/depth", "survivorship-free second data source", "preregistration freeze after independent review; adjudicate.py", "calibrate Stage 04 regime thresholds before any regime activation", "a forward test of the factor overlay needs >=5-asset cross-section at signal time", "gate thresholds uncalibrated"],
  limitations=["see STAGE_06_VALIDATION_REPORT.md"])
(OUT / "STAGE_06_HANDOFF.json").write_text(json.dumps(hand, indent=1, default=str))
print("ok", len(L))
