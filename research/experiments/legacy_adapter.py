"""Limited bridge to Stage 02 signal code (PROPOSED; explicit limitations).

What it does: builds the hourly DataFrame the legacy code expects from the side-effect-free
OhlcvSource and calls the PURE function lab.features() to obtain signal plans.
What it does NOT do: construct lab.Market (its __init__ writes results/data_audit.json), call
lab.simulate, run.py, verify_data or download, change any legacy behaviour, or claim anything about
performance. Using the legacy engine for full simulation needs a separate, reviewed Market substitute.
Requires numpy/pandas (imported lazily so the rest of the workbench stays stdlib-only).
"""
from __future__ import annotations


def hourly_frame(source, symbol):
    import pandas as pd
    bars, _ = source.read_bars(symbol, "1h")
    ix = pd.to_datetime([b["open_ms"] for b in bars], unit="ms", utc=True)
    cols = ["open", "high", "low", "close", "volume", "quote_volume", "trades"]
    return pd.DataFrame({c: [b[c] for b in bars] for c in cols}, index=ix)


def signal_plans(source, symbol):
    """Return lab.features() signal plans for one symbol. Pure computation; no file writes."""
    import lab  # importing lab has no side effects; only lab.Market() writes results/
    _, plans, _ = lab.features(hourly_frame(source, symbol))
    return plans
