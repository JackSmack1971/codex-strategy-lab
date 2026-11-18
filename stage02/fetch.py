"""Stage 02 data fetch: Binance public archive (data.binance.vision), spot 1h klines, checksum verified.
Writes only to ignored data/s2raw/. No credentials. Network: public HTTPS GET."""
import hashlib, json, sys, urllib.request, urllib.error, zipfile, io, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / "data" / "s2raw"
SYMS = ["BTC","ETH","SOL","XRP","ADA","LINK","AVAX","DOGE","LTC"]
BASE = "https://data.binance.vision/data/spot"
def months():
    y, m = 2021, 5
    while (y, m) <= (2026, 10):
        yield f"{y}-{m:02d}"; m += 1
        if m == 13: y, m = y + 1, 1
def days():
    d = dt.date(2026, 11, 1)
    while d <= dt.date(2026, 11, 17):
        yield d.isoformat(); d += dt.timedelta(days=1)
def get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, b""
    except Exception as e: return -1, str(e).encode()
def job(a):
    sym, kind, tag = a
    pair = sym + "USDT"
    sub = "monthly" if kind == "m" else "daily"
    name = f"{pair}-1h-{tag}.zip"
    out = ROOT / pair / name
    meta = out.with_suffix(".json")
    if out.exists() and meta.exists(): return a, "cached"
    url = f"{BASE}/{sub}/klines/{pair}/1h/{name}"
    for _ in range(3):
        st, body = get(url)
        if st == 200: break
    if st != 200: return a, f"HTTP{st}"
    st2, ck = get(url + ".CHECKSUM")
    official = ck.decode().split()[0] if st2 == 200 and ck else None
    h = hashlib.sha256(body).hexdigest()
    status = "verified" if official == h else ("checksum_missing" if official is None else "CHECKSUM_MISMATCH")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    meta.write_text(json.dumps({"url": url, "sha256": h, "official_sha256": official, "status": status, "bytes": len(body),
        "retrieved_utc": dt.datetime.now(dt.timezone.utc).isoformat()}))
    return a, status
if __name__ == "__main__":
    jobs = [(s, "m", t) for s in SYMS for t in months()] + [(s, "d", t) for s in SYMS for t in days()]
    res = {}
    with ThreadPoolExecutor(12) as ex:
        for a, st in ex.map(job, jobs): res[st] = res.get(st, 0) + 1; (st not in ("verified","cached")) and print(a, st)
    print(res)
