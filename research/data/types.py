"""Shared data-contract vocabulary. Enumerations come from the schema files (single authority)."""
from __future__ import annotations
from ..contracts import load_schema

_OBS = load_schema("observation")["properties"]
INSTRUMENT_TYPES = tuple(_OBS["instrument_type"]["enum"])
CLOCKS = tuple(_OBS["clock"]["enum"])
QUALITY_FLAGS = tuple(_OBS["quality_flags"]["items"]["enum"])

INTERVAL_SECONDS = {"1m": 60, "1h": 3600, "4h": 14400}
LEGACY_VENUE = "BINANCE_SPOT"          # public spot archives only; no derivatives, no order book
LEGACY_PROVIDER = "binance-vision-klines"
DATASET_KINDS = ("OHLCV", "ORDER_BOOK", "TRADES", "CATALYST")
