"""Warm the public archive cache without rewriting committed research artifacts."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from download import SYMBOLS, job
import pandas as pd

def build_specs(scope: str) -> list[tuple[str, str, str, str]]:
    if scope not in ('hourly', 'full'):
        raise ValueError('scope must be hourly or full')
    specs = []
    for symbol in SYMBOLS:
        for interval in (('1h',) if scope == 'hourly' else ('1h', '1m')):
            for date in pd.date_range('2021-05-01', '2026-10-01', freq='MS'):
                specs.append((symbol, interval, 'monthly', date.strftime('%Y-%m')))
            for date in pd.date_range('2026-11-01', '2026-11-16', freq='D'):
                specs.append((symbol, interval, 'daily', date.strftime('%Y-%m-%d')))
        if scope == 'full':
            specs.extend((symbol, '4h', 'monthly', month) for month in ('2021-11', '2026-10'))
    return specs

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scope', choices=['hourly', 'full'])
    parser.add_argument('--workers', type=int, default=6, choices=range(1, 11))
    args = parser.parse_args()
    specs = build_specs(args.scope)
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for n, record in enumerate(pool.map(job, specs), 1):
            records.append(record)
            if n % 25 == 0 or n == len(specs):
                print(f'Archive cache: {n}/{len(specs)} checked', flush=True)
    cache = ROOT / '.cache' / 'codex-cloud'
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / f'prefetch-{args.scope}.json'
    destination.write_text(json.dumps(records, indent=2) + '\n')
    failed = sum(r.get('status') != 'verified' for r in records)
    print(f'{len(records)-failed}/{len(records)} verified; cache manifest: {destination}')
    if failed:
        print('Archive cache incomplete. Check the cache manifest; no backtest was run.', file=sys.stderr)
    return 1 if failed else 0

if __name__ == '__main__':
    raise SystemExit(main())
