"""Independent metric recomputation and cost stress (plain formulas, math.fsum for determinism).

Qualifying metrics are derived ONLY here, from verified execution artifacts (fills + trades) and the
FROZEN preregistered economics (cost per trade, stress multipliers, evaluation split). An
experiment's own metrics.json is descriptive: it is compared with these values and any
disagreement blocks the evaluation, but it never supplies a gate value.
"""
from __future__ import annotations
import math

from ..contracts import parse_utc

GROSS_TOL = 1e-9          # declared gross_return must equal the fill-derived value to this absolute tolerance


def _mk(m):
    """Metric-name suffix for a stress multiplier: 2.0 -> '2', 1.5 -> '1.5'."""
    return str(int(m)) if float(m) == int(m) else repr(float(m))


def stress_metric(m) -> str:
    return f"mean_net_return_stress_x{_mk(m)}"


def _mean(xs):
    return math.fsum(xs) / len(xs)


def recompute_metrics(trade_returns, *, cost_per_trade: float, stress_multipliers) -> dict:
    """Metrics derived only from the series. Returns None-valued metrics when there are no trades."""
    xs = [float(x) for x in trade_returns]
    if any(not math.isfinite(x) for x in xs) or not math.isfinite(cost_per_trade) or cost_per_trade < 0:
        raise ValueError("returns and cost must be finite, cost non-negative")
    out = {"n_trades": len(xs)}
    names = ["mean_gross_return", "mean_net_return"] + [stress_metric(m) for m in stress_multipliers]
    if not xs:
        return {**out, **{n: None for n in names}, "gross_return_sharpe": None}
    out["mean_gross_return"] = _mean(xs)
    out["mean_net_return"] = _mean([x - cost_per_trade for x in xs])
    for m in stress_multipliers:
        out[stress_metric(m)] = _mean([x - m * cost_per_trade for x in xs])
    if len(xs) > 1:
        mu = _mean(xs)
        sd = math.sqrt(math.fsum((x - mu) ** 2 for x in xs) / (len(xs) - 1))
        out["gross_return_sharpe"] = (mu / sd) if sd > 0 else None   # per-trade, descriptive only; never gated implicitly
    else:
        out["gross_return_sharpe"] = None
    return out


def compare_metrics(reported: dict, recomputed: dict, *, rel_tol: float = 1e-12, abs_tol: float = 1e-12) -> list:
    """Keys present in both must agree; returns a sorted list of disagreeing metric names."""
    bad = []
    for k in sorted(set(reported) & set(recomputed)):
        a, b = reported[k], recomputed[k]
        if a is None or b is None:
            if a is not b:
                bad.append(k)
        elif isinstance(a, bool) or not isinstance(a, (int, float)) or not math.isfinite(a):
            bad.append(k)
        elif not math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol):
            bad.append(k)
    return bad


# ------------------------------------------------------------------ execution-derived evaluation
class ExecutionError(ValueError):
    """The execution artifact is inconsistent or unverifiable; the evaluation must be BLOCKED."""


def _betacf(a, b, x):
    tiny, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def _betainc(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbeta) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbeta) * _betacf(b, a, 1.0 - x) / b


def one_sided_t_p_value(xs):
    """P(T >= t) for H0: mean <= 0 (Student t, n-1 dof). None when undefined (n < 2 or zero variance)."""
    n = len(xs)
    if n < 2:
        return None
    mu = _mean(xs)
    sd = math.sqrt(math.fsum((x - mu) ** 2 for x in xs) / (n - 1))
    if sd == 0:
        return None
    t, df = mu / (sd / math.sqrt(n)), n - 1
    tail = 0.5 * _betainc(df / 2.0, 0.5, df / (df + t * t))      # P(|T| >= |t|) / 2
    return tail if t >= 0 else 1.0 - tail


def _num(v):
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def trades_from_execution(execution: dict, prereg: dict) -> list:
    """Verify an execution artifact (fills + trades) against the preregistration; return gross returns.

    Everything the metrics rest on is re-derived from fill prices: a trade's declared gross_return must
    equal the fill-derived value, fills must be well formed, unique, ordered and inside the
    preregistered evaluation range (so labels cannot cross a split boundary), and long/short sides
    must match the fills. Any inconsistency raises ExecutionError (the evaluation is BLOCKED).
    """
    if not isinstance(execution, dict) or set(execution) != {"fills", "trades"} \
            or not isinstance(execution["fills"], list) or not isinstance(execution["trades"], list):
        raise ExecutionError("EXECUTION_SHAPE: execution artifact must be {fills: [...], trades: [...]}")
    split = prereg["economics"]["evaluation_split"]
    rng = prereg["splits"][split]
    lo, hi = parse_utc(rng["start_utc"]), parse_utc(rng["end_utc"])
    embargo = prereg["purge"]["embargo_s"]
    fills = {}
    for f in execution["fills"]:
        need = {"fill_id", "side", "at_utc", "price", "quantity"}
        if not isinstance(f, dict) or set(f) != need:
            raise ExecutionError("FILL_SHAPE: fills need exactly fill_id, side, at_utc, price, quantity")
        if not isinstance(f["fill_id"], str) or f["fill_id"] in fills:
            raise ExecutionError(f"FILL_DUPLICATE:{f['fill_id']}")
        if f["side"] not in ("BUY", "SELL"):
            raise ExecutionError(f"FILL_SIDE:{f['fill_id']}")
        for k in ("price", "quantity"):
            if not _num(f[k]) or f[k] <= 0:
                raise ExecutionError(f"FILL_{k.upper()}:{f['fill_id']}")
        try:
            parse_utc(f["at_utc"])
        except ValueError:
            raise ExecutionError(f"FILL_TIME:{f['fill_id']}") from None
        fills[f["fill_id"]] = f
    out, used, seen = [], set(), set()
    for t in execution["trades"]:
        need = {"trade_id", "direction", "entry_fill_id", "exit_fill_id", "split", "gross_return"}
        if not isinstance(t, dict) or set(t) != need:
            raise ExecutionError("TRADE_SHAPE: trades need exactly " + ", ".join(sorted(need)))
        if t["trade_id"] in seen:
            raise ExecutionError(f"TRADE_DUPLICATE:{t['trade_id']}")
        seen.add(t["trade_id"])
        if t["split"] != split:
            raise ExecutionError(f"TRADE_SPLIT:{t['trade_id']} is {t['split']!r}, evaluation split is {split!r}")
        e, x = fills.get(t["entry_fill_id"]), fills.get(t["exit_fill_id"])
        if e is None or x is None:
            raise ExecutionError(f"TRADE_FILL_MISSING:{t['trade_id']}")
        if t["entry_fill_id"] in used or t["exit_fill_id"] in used or t["entry_fill_id"] == t["exit_fill_id"]:
            raise ExecutionError(f"FILL_REUSED:{t['trade_id']}")
        used |= {t["entry_fill_id"], t["exit_fill_id"]}
        if t["direction"] not in ("LONG", "SHORT"):
            raise ExecutionError(f"TRADE_DIRECTION:{t['trade_id']}")
        want = ("BUY", "SELL") if t["direction"] == "LONG" else ("SELL", "BUY")
        if (e["side"], x["side"]) != want:
            raise ExecutionError(f"TRADE_SIDE_MISMATCH:{t['trade_id']}")
        te, tx = parse_utc(e["at_utc"]), parse_utc(x["at_utc"])
        if not te < tx:
            raise ExecutionError(f"TRADE_CHRONOLOGY:{t['trade_id']}")
        if te < lo or tx > hi:
            raise ExecutionError(f"TRADE_OUTSIDE_SPLIT:{t['trade_id']} (labels may not cross the {split} boundary)")
        if (te - lo).total_seconds() < embargo:
            raise ExecutionError(f"TRADE_INSIDE_EMBARGO:{t['trade_id']}")
        px = x["price"] / e["price"] - 1.0
        derived = px if t["direction"] == "LONG" else -px
        if not _num(t["gross_return"]) or abs(t["gross_return"] - derived) > GROSS_TOL:
            raise ExecutionError(f"TRADE_RETURN_INCONSISTENT:{t['trade_id']} declared {t['gross_return']!r}, fills imply {derived!r}")
        out.append(derived)
    if set(fills) - used:
        raise ExecutionError("FILL_ORPHAN: fills not belonging to any trade")
    return out


def evaluate(execution: dict, prereg: dict) -> dict:
    """Deterministic qualifying metrics from verified execution artifacts and FROZEN preregistered economics."""
    gross = trades_from_execution(execution, prereg)
    eco = prereg["economics"]
    m = recompute_metrics(gross, cost_per_trade=eco["cost_per_trade"], stress_multipliers=eco["stress_multipliers"])
    m["p_value"] = one_sided_t_p_value([g - eco["cost_per_trade"] for g in gross])
    m["economic_estimate"] = m["mean_net_return"]
    return m
