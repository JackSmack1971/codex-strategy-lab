"""Synthetic Binance-style kline archives for tests (random walk from a fixed seed; no market data)."""
import csv
import hashlib
import io
import json
import random
import zipfile
from datetime import datetime, timezone
from pathlib import Path

STEP = {"1m": 60_000, "1h": 3_600_000, "4h": 14_400_000}


def make_archive(data_root, symbol, interval, start_utc, n, *, name_suffix="2021-11", skip=(), micros=False,
                 verified=True, tamper=False, seed=1, quote_volume=1000.0):
    start = int(datetime.fromisoformat(start_utc.replace("Z", "+00:00")).timestamp() * 1000)
    rnd = random.Random(seed)
    price, rows = 100.0, []
    for i in range(n):
        if i in skip:
            continue
        o = price
        price = max(1.0, price * (1 + rnd.uniform(-0.01, 0.01)))
        hi, lo = max(o, price) * 1.001, min(o, price) * 0.999
        t = start + i * STEP[interval]
        rows.append([t * (1000 if micros else 1), o, hi, lo, price, 10.0, t + STEP[interval] - 1, quote_volume, 5, 1.0, 1.0, 0])
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    folder = Path(data_root) / "raw" / symbol / interval
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{symbol}-{interval}-{name_suffix}.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{symbol}-{interval}-{name_suffix}.csv", buf.getvalue())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = {"symbol": symbol, "interval": interval, "url": f"https://example.invalid/{path.name}",
            "retrieved_utc": "2026-11-17T12:00:00+00:00",
            "status": "verified" if verified else "unavailable", "sha256": sha, "official_sha256": sha}
    path.with_suffix(".json").write_text(json.dumps(meta))
    if tamper:
        path.write_bytes(path.read_bytes() + b"x")
    return path


def tree(root):
    return sorted((p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
                  for p in Path(root).rglob("*") if p.is_file())
