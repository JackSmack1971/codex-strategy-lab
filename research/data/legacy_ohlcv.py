"""Read-only adapter over the Stage 02 Binance spot kline archives.

Side-effect boundary: this module only READS `<data_root>/raw/<SYMBOL>/<interval>/*.zip` and the
matching `.json` sidecars. It never imports `lab`, `download`, `verify_data` or pandas, never
writes (no results/, no .pkl cache, no manifests), never touches the network, and has no
code path that places orders. (Legacy `lab.Market.__init__`, `verify_data.main` and
`download.download` write into results/ or data/, so they are intentionally not used.)

Honesty about time: the archives carry no publication timestamp. A bar is treated as available
at its END (open time + interval) as a modelled assumption, flagged ESTIMATED, with a
`published_at_utc` absent_reason. Archives give no order-book depth, spread, queue or liquidation
data and none is fabricated.
"""
from __future__ import annotations
import csv, io, json, zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..identifiers import derived_id, digest, sha256_hex
from .types import INTERVAL_SECONDS, LEGACY_PROVIDER, LEGACY_VENUE

COLS = ["time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "tb", "tq", "ignore"]


class ArchiveError(ValueError):
    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _norm_ms(raw: float) -> int:
    """Binance spot archives switched to microseconds in 2025; legacy loader uses the same >1e14 rule."""
    return int(raw / 1000) if raw > 1e14 else int(raw)


def _retrieved(records):
    """Latest archive retrieval time as a UTC 'Z' timestamp (None when any archive lacks one)."""
    vals = [r.get("retrieved_utc") for r in records]
    if not vals or any(not v for v in vals):
        return None
    return max(datetime.fromisoformat(v).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ") for v in vals)


class OhlcvSource:
    def __init__(self, data_root):
        self.root = Path(data_root)

    def archives(self, symbol, interval):
        return sorted((self.root / "raw" / symbol / interval).glob("*.zip"))

    def verify_archive(self, path: Path) -> dict:
        """Check bytes against the sidecar (status verified, sha256 == official_sha256 == file hash)."""
        side = path.with_suffix(".json")
        if not side.is_file():
            raise ArchiveError("SIDECAR_MISSING", path.name)
        meta = json.loads(side.read_text(encoding="utf-8"))
        actual = sha256_hex(path.read_bytes())
        if meta.get("status") != "verified":
            raise ArchiveError("NOT_VERIFIED", path.name)
        if not (actual == meta.get("sha256") == meta.get("official_sha256")):
            raise ArchiveError("CHECKSUM_MISMATCH", path.name)
        return {"name": path.name, "sha256": actual, "retrieved_utc": meta.get("retrieved_utc"), "url": meta.get("url")}

    def read_bars(self, symbol, interval):
        """Return (bars, archive_records); bars are dicts sorted by open time, duplicates rejected."""
        if interval not in INTERVAL_SECONDS:
            raise ArchiveError("INTERVAL_UNSUPPORTED", interval)
        paths = self.archives(symbol, interval)
        if not paths:
            raise ArchiveError("NO_ARCHIVES", f"{symbol} {interval}")
        bars, records = [], []
        for path in paths:
            rec = self.verify_archive(path)
            records.append(rec)
            with zipfile.ZipFile(path) as z:
                text = io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8", newline="")
                for row in csv.reader(text):
                    if not row:
                        continue
                    try:
                        t = float(row[0])
                    except ValueError:
                        continue                                  # header row
                    if len(row) < 8:
                        raise ArchiveError("SCHEMA", f"{path.name}: expected >= 8 columns")
                    bars.append({"open_ms": _norm_ms(t), "open": float(row[1]), "high": float(row[2]),
                                 "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]),
                                 "quote_volume": float(row[7]), "trades": float(row[8]) if len(row) > 8 else 0.0,
                                 "archive": rec["name"]})
        bars.sort(key=lambda b: b["open_ms"])
        for a, b in zip(bars, bars[1:]):
            if a["open_ms"] == b["open_ms"]:
                raise ArchiveError("DUPLICATE_BAR", f"{symbol} {interval} {_iso(a['open_ms'])}")
        return bars, records

    def manifest(self, symbol, interval):
        """Dataset manifest (deterministic, hashable); gap counts use only the bars' own timestamps."""
        bars, records = self.read_bars(symbol, interval)
        step = INTERVAL_SECONDS[interval] * 1000
        missing = sum((b["open_ms"] - a["open_ms"]) // step - 1 for a, b in zip(bars, bars[1:]) if b["open_ms"] - a["open_ms"] > step)
        off_grid = sum(1 for b in bars if b["open_ms"] % step)
        body = {"kind": "OHLCV", "venue": LEGACY_VENUE, "instrument_id": symbol, "instrument_type": "SPOT",
                "interval": interval, "provider": LEGACY_PROVIDER, "bars": len(bars),
                "first_open_utc": _iso(bars[0]["open_ms"]), "last_open_utc": _iso(bars[-1]["open_ms"]),
                "missing_bars": int(missing), "off_grid_bars": off_grid,
                "retrieved_utc": _retrieved(records),
                "archives": [{"name": r["name"], "sha256": r["sha256"]} for r in records]}
        return dict(body, manifest_sha256=digest(body))

    def close_observations(self, symbol, interval, limit=None):
        """Observation records for each bar close (a modelled availability: the bar end)."""
        bars, records = self.read_bars(symbol, interval)
        by_name = {r["name"]: r for r in records}
        step = INTERVAL_SECONDS[interval] * 1000
        out = []
        for b in bars[:limit]:
            rec = by_name[b["archive"]]
            ingested = (datetime.fromisoformat(rec["retrieved_utc"]).astimezone(timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
            out.append({
                "schema_version": "1.0.0",
                "observation_id": derived_id("obs", f"{symbol}:{interval}:{b['open_ms']}"),
                "source_id": derived_id("src", f"{LEGACY_PROVIDER}:{symbol}:{interval}"),
                "provider_version": LEGACY_PROVIDER, "retrieval_id": derived_id("ret", rec["sha256"]),
                "venue": LEGACY_VENUE, "instrument_id": symbol, "instrument_type": "SPOT",
                "unit": "USDT", "clock": "EXCHANGE", "event_at_utc": _iso(b["open_ms"]),
                "published_at_utc": {"absent_reason": "archive carries no publication timestamp"},
                "available_at_utc": _iso(b["open_ms"] + step),
                "ingested_at_utc": ingested, "revision_id": derived_id("rev", rec["sha256"]),
                "value": b["close"], "raw_sha256": rec["sha256"], "precision": 8,
                "quality_flags": ["ESTIMATED"]})
        return out
