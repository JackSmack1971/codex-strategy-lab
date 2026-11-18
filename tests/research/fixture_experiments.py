"""Importable synthetic experiments (fixtures only; every number is made up, none is evidence about markets).

They must be module-level functions so the brokered runner can start them in a child process.
Each builds an execution artifact (fills + trades) from gross returns it reads through ctx.data().
"""
from datetime import datetime, timedelta, timezone

from research.validation import economics


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def execution_from_returns(returns, range_start_utc, split="test", direction="LONG", gap_hours=2):
    """Fills+trades whose prices realise the given gross returns (entry at 100, exit at 100*(1+r))."""
    t0 = datetime.fromisoformat(range_start_utc.replace("Z", "+00:00")).astimezone(timezone.utc) + timedelta(hours=2)
    fills, trades = [], []
    for i, r in enumerate(returns):
        te = t0 + timedelta(hours=gap_hours * i)
        entry_px, exit_px = 100.0, 100.0 * (1.0 + (r if direction == "LONG" else -r))
        e, x = f"f{i}e", f"f{i}x"
        fills.append({"fill_id": e, "side": "BUY" if direction == "LONG" else "SELL", "at_utc": _iso(te), "price": entry_px, "quantity": 1})
        fills.append({"fill_id": x, "side": "SELL" if direction == "LONG" else "BUY", "at_utc": _iso(te + timedelta(hours=1)),
                      "price": exit_px, "quantity": 1})
        trades.append({"trade_id": f"t{i}", "direction": direction, "entry_fill_id": e, "exit_fill_id": x, "split": split,
                       "gross_return": exit_px / entry_px - 1.0 if direction == "LONG" else -(exit_px / entry_px - 1.0)})
    return {"fills": fills, "trades": trades}


def edge_experiment(ctx):
    """Reads train, validation and the configured evaluation split; reports honest descriptive metrics."""
    cfg = ctx.config
    ctx.data("train")
    ctx.data("validation")
    rs = ctx.data(cfg["eval_split"])
    ex = execution_from_returns(rs, cfg["range_start_utc"], split=cfg["eval_split"])
    gross = [t["gross_return"] for t in ex["trades"]]
    mutate = cfg.get("mutate", "none")
    if mutate == "gross":                      # declare a far better return than the fills support
        ex["trades"][0]["gross_return"] += 0.5
    elif mutate == "orphan":                   # a fill that belongs to no trade
        ex["fills"].append({"fill_id": "orphan", "side": "BUY", "at_utc": ex["fills"][0]["at_utc"], "price": 100.0, "quantity": 1})
    elif mutate == "side":                     # long trade whose exit is another BUY
        ex["fills"][1]["side"] = "BUY"
    elif mutate == "outside":                  # a fill after the end of the preregistered split
        ex["fills"][1]["at_utc"] = "2030-01-01T00:00:00Z"
    m = economics.recompute_metrics(gross, cost_per_trade=cfg["cost"], stress_multipliers=cfg["stress"])
    m["economic_estimate"] = m["mean_net_return"]
    m.update(cfg.get("report_override") or {})
    return {"metrics": m, "artifacts": {"execution.json": ex}}


def validation_only_experiment(ctx):
    """Never touches the test split (evaluates validation)."""
    cfg = ctx.config
    ctx.data("train")
    rs = ctx.data("validation")
    ex = execution_from_returns(rs, cfg["range_start_utc"], split="validation")
    return {"metrics": {}, "artifacts": {"execution.json": ex}}


def peeking_experiment(ctx):
    """Reads the test split but hands back validation-based output (a peek)."""
    cfg = ctx.config
    ctx.data("test")
    rs = ctx.data("validation")
    return {"metrics": {}, "artifacts": {"execution.json": execution_from_returns(rs, cfg["range_start_utc"], split="validation")}}


def raising_experiment(ctx):
    raise RuntimeError("synthetic failure")
