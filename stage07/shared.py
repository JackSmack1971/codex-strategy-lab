"""Stage 07 shared-book simulator: a port of stage02.engine.simulate with per-sleeve risk/notional parameters and portfolio-level
admission control (open-risk cap, position cap, single-asset and gross notional caps). With uniform parameters and no extra caps it reproduces
engine.simulate exactly (asserted in the runner on real data). The engine itself is unchanged. Research only."""
from __future__ import annotations
import numpy as np
from stage02 import engine as E


def simulate_shared(cands, syms, ws, we, f, s, capital=10_000.0, max_pos=3, per_trade=0.01, total=0.03, ncap=0.33, part=0.01,
                    single_cap=None, gross_cap=None):
    """per_trade / ncap may be dicts keyed by strategy id. single_cap / gross_cap are fractions of frozen equity (None = off)."""
    pt = (lambda sid: per_trade[sid]) if isinstance(per_trade, dict) else (lambda sid: per_trade)
    nc = (lambda sid: ncap[sid]) if isinstance(ncap, dict) else (lambda sid: ncap)
    el = [c for c in cands if ws <= c["t_entry"] < we]
    el.sort(key=lambda c: (c["t_entry"], E.STRAT_ORDER[c["sid"]], E.SYMS.index(c["sym"])))
    cash = capital; openp = []; done = []; skips = {}; occ = {}; last_exit_b = {}; Efroz = None; Tfroz = None
    def sk(k): skips[k] = skips.get(k, 0) + 1
    for cd in el:
        T = cd["t_entry"]
        for p in openp:
            if not p["rel"] and p["rel_cash"] <= T: p["rel"] = True; cash += p["proceeds"]
        live = [p for p in openp if not p["rel"]]
        if T != Tfroz:
            Efroz = cash + sum(p["q"] * syms[p["cd"]["sym"]].cff[T - 1] for p in live); Tfroz = T
        Eq = Efroz; key = (cd["sid"], cd["sym"])
        if occ.get(cd["sym"], -1) > T: sk("symbol_occupied"); continue
        if key in last_exit_b and cd["j"] < last_exit_b[key] + 1: sk("cooldown"); continue
        if len(live) >= max_pos: sk("max_positions"); continue
        G = sum(p["risk"] for p in live); B = max(0.0, min(pt(cd["sid"]) * Eq, total * Eq - G))
        if B <= 0: sk("risk_budget_zero"); continue
        sy = syms[cd["sym"]]; qm = sy.qmed168[T - 1]
        if not np.isfinite(qm): sk("no_qmed"); continue
        Pf = cd["Pf"]; ncp = nc(cd["sid"]) if single_cap is None else min(nc(cd["sid"]), single_cap)
        lim = [B / cd["d"], ncp * Eq / Pf, cash / (Pf * (1 + f)), part * qm / Pf]
        if gross_cap is not None:
            Gn = sum(p["q"] * syms[p["cd"]["sym"]].cff[T - 1] for p in live)
            room = (gross_cap * Eq - Gn) / Pf
            if room <= 0: sk("gross_cap"); continue
            lim.append(room)
        q = E.floor_lot(min(lim))
        if q <= 0: sk("qty_zero"); continue
        if q * Pf < E.MIN_NOTIONAL: sk("below_min_notional"); continue
        cdx = dict(cd)
        if cd["kind"] == "END" or cd["t_exit"] >= we:
            cdx["kind"] = "forced"; cdx["t_exit"] = we - 1; cdx["occ_end"] = we; cdx["rel_cash"] = we; cdx["xfill"] = sy.cff[we - 1] * (1 - s); cdx["exit_b"] = None
        pnl_u = cdx["xfill"] * (1 - f) - Pf * (1 + f); cash -= q * Pf * (1 + f)
        p = dict(cd=cdx, q=q, risk=q * cd["d"], proceeds=q * cdx["xfill"] * (1 - f), rel=False, rel_cash=cdx["rel_cash"], pnl=q * pnl_u, E_entry=Eq,
                 buy_notional=q * Pf, sell_notional=q * cdx["xfill"], fees=f * q * (Pf + cdx["xfill"]))
        openp.append(p); done.append(p); occ[cd["sym"]] = cdx["occ_end"]; last_exit_b[key] = cdx["exit_b"] if cdx["exit_b"] is not None else 10 ** 9
    H = we - ws; cashd = np.zeros(H + 1); posv = np.zeros(H); cashd[0] = capital; sids = sorted({p["cd"]["sid"] for p in done}); pn = {x: np.zeros(H + 1) for x in sids}; pv = {x: np.zeros(H) for x in sids}
    for p in done:
        cd = p["cd"]; te = cd["t_entry"] - ws; tx = cd["t_exit"] - ws; x = cd["sid"]
        a = -p["q"] * cd["Pf"] * (1 + f); b = p["proceeds"]; cashd[te] += a; cashd[min(tx, H - 1)] += b; pn[x][te] += a; pn[x][min(tx, H - 1)] += b
        hi = min(tx, H)
        if hi > te: v = p["q"] * syms[cd["sym"]].cff[cd["t_entry"]: cd["t_entry"] + (hi - te)]; posv[te:hi] += v; pv[x][te:hi] += v
    eq = np.cumsum(cashd[:H]) + posv; pnl_by = {x: np.cumsum(pn[x][:H]) + pv[x] for x in sids}
    trades = [dict(strategy=p["cd"]["sid"], symbol=p["cd"]["sym"], entry_hour=p["cd"]["t_entry"], exit_hour=p["cd"]["t_exit"], kind=p["cd"]["kind"], tf=p["cd"]["tf"], qty=p["q"],
                   entry_fill=p["cd"]["Pf"], exit_fill=p["cd"]["xfill"], S0=p["cd"]["S0"], O1=p["cd"]["O1"], d_unit=p["cd"]["d"], reserved_risk=p["risk"], pnl=p["pnl"], R=p["pnl"] / p["risk"],
                   fees=p["fees"], buy_notional=p["buy_notional"], sell_notional=p["sell_notional"], bars=(None if p["cd"]["exit_b"] is None else p["cd"]["exit_b"] - p["cd"]["b0"] + 1),
                   E_entry=p["E_entry"], forced=p["cd"]["kind"] == "forced") for p in done]
    return dict(trades=trades, skips=skips, equity=eq, pnl_by=pnl_by, ws=ws, we=we)
