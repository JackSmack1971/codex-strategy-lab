"""Public Binance archives with official checksums. No credentials."""
from __future__ import annotations
import concurrent.futures as cf
import hashlib, io, json, time, urllib.request, urllib.error, zipfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
COLS = ['time','open','high','low','close','volume','close_time','quote_volume','trades','tb','tq','ignore']
SYMBOLS = ['BTCUSDT','ETHUSDT','SOLUSDT']

def fetch(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code in (404, 403): raise
            if attempt == 3: raise
        except Exception:
            if attempt == 3: raise
        time.sleep(0.5 * 2**attempt)

def job(spec):
    symbol, interval, freq, date = spec
    name = f'{symbol}-{interval}-{date}.zip'
    url = f'https://data.binance.vision/data/spot/{freq}/klines/{symbol}/{interval}/{name}'
    dest = DATA / 'raw' / symbol / interval / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    meta = {'symbol':symbol,'interval':interval,'url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat()}
    side = dest.with_suffix('.json')
    if dest.exists() and side.exists():
        old = json.loads(side.read_text())
        if hashlib.sha256(dest.read_bytes()).hexdigest() == old.get('sha256'):
            return old
    try:
        check, _ = fetch(url+'.CHECKSUM')
        expected = check.decode().split()[0]
        raw, headers = fetch(url)
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected: raise ValueError(f'Checksum mismatch {url}')
        dest.write_bytes(raw)
        meta.update(status='verified',sha256=actual,official_sha256=expected,bytes=len(raw),headers=headers)
        side.write_text(json.dumps(meta,indent=2))
    except Exception as e:
        meta.update(status='unavailable',error=str(e))
    return meta

def download(intervals=('1h','1m')):
    specs=[]
    for sym in SYMBOLS:
        for iv in intervals:
            for date in pd.date_range('2021-05-01','2026-10-01',freq='MS'):
                specs.append((sym,iv,'monthly',date.strftime('%Y-%m')))
            for date in pd.date_range('2026-11-01','2026-11-16',freq='D'):
                specs.append((sym,iv,'daily',date.strftime('%Y-%m-%d')))
    manifest=[]
    with cf.ThreadPoolExecutor(max_workers=10) as pool:
        for i, result in enumerate(pool.map(job,specs)):
            manifest.append(result)
            if i%25==0: print(f'{i+1}/{len(specs)} {result["symbol"]} {result["interval"]} {result["status"]}',flush=True)
    (ROOT/'results').mkdir(exist_ok=True)
    (ROOT/'results'/'data_manifest.json').write_text(json.dumps(manifest,indent=2))
    print(pd.Series([m['status'] for m in manifest]).value_counts().to_dict(),flush=True)

def load(symbol, interval):
    cache=DATA/f'{symbol}-{interval}.pkl'
    if cache.exists(): return pd.read_pickle(cache)
    frames=[]
    for path in sorted((DATA/'raw'/symbol/interval).glob('*.zip')):
        with zipfile.ZipFile(path) as z:
            df=pd.read_csv(z.open(z.namelist()[0]),header=None,names=COLS)
        ts=pd.to_numeric(df.time,errors='coerce')
        df=df[ts.notna()].copy(); ts=ts[ts.notna()]
        df.index=pd.to_datetime(np.where(ts>1e14,ts/1000,ts),unit='ms',utc=True)
        df=df[['open','high','low','close','volume','quote_volume','trades']].astype(float)
        frames.append(df)
    if not frames: raise ValueError(f'No data {symbol} {interval}')
    result=pd.concat(frames).sort_index()
    result.to_pickle(cache)
    return result

if __name__=='__main__':
    import sys
    download(tuple(sys.argv[1:]) or ('1h','1m'))
