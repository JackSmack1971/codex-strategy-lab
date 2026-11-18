"""Stage 04: public, read-only market/macro/on-chain snapshot. No credentials, no orders.
Raw responses go to ignored data/s4raw/<UTC stamp>/ with SHA-256 manifest; failures are recorded, not hidden."""
import json, hashlib, time, io, zipfile, sys
from pathlib import Path
from datetime import datetime, timezone
import urllib.request, urllib.error

SYMS = ["BTC", "ETH", "SOL", "XRP", "ADA", "LINK", "AVAX", "DOGE", "LTC"]
ROOT = Path(__file__).resolve().parents[1] / "data" / "s4raw"
HDR = {"User-Agent": "research-client/1.0"}
HL = "https://api.hyperliquid.xyz/info"

def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); out = ROOT / stamp; out.mkdir(parents=True)
    man = []
    def get(name, url, post=None, tries=3):
        for k in range(tries):
            t0 = datetime.now(timezone.utc).isoformat()
            r = None
            try:
                data = json.dumps(post).encode() if post else None
                h = dict(HDR); 
                if post: h["Content-Type"] = "application/json"
                with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=30) as resp:
                    body = resp.read(); code = resp.status
                ok = code == 200
            except urllib.error.HTTPError as e:
                body = e.read(); code = e.code; ok = False
            except Exception as e:
                body = str(e).encode(); code = None; ok = False
            if ok or k == tries - 1: break
            time.sleep(2 * (k + 1))
        (out / name).write_bytes(body)
        man.append(dict(name=name, url=url, post=post, fetched_utc=t0, http=code, ok=ok, bytes=len(body), sha256=hashlib.sha256(body).hexdigest()))
        return body if ok else None
    now_ms = int(time.time() * 1000)
    # 1) Binance spot 1H klines (data-api.binance.vision: public market-data mirror), from 2026-11-10 to now
    start = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp() * 1000)
    for s in SYMS:
        get(f"binance_1h_{s}.json", f"https://data-api.binance.vision/api/v3/klines?symbol={s}USDT&interval=1h&startTime={start}&limit=1000")
        get(f"binance_24h_{s}.json", f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={s}USDT")
        get(f"binance_depth_{s}.json", f"https://data-api.binance.vision/api/v3/depth?symbol={s}USDT&limit=100")
    # 2) Cross-venue spot: Coinbase 1H candles + tickers, Kraken tickers
    for s in SYMS:
        get(f"coinbase_1h_{s}.json", f"https://api.exchange.coinbase.com/products/{s}-USD/candles?granularity=3600")
        get(f"coinbase_book_{s}.json", f"https://api.exchange.coinbase.com/products/{s}-USD/book?level=2")
    get("kraken_ticker.json", "https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD,SOLUSD,XRPUSD,ADAUSD,LINKUSD,AVAXUSD,XDGUSD,LTCUSD")
    # 3) Derivatives: Hyperliquid (funding/OI/premium), OKX (funding, OI, liquidations)
    get("hl_meta_ctxs.json", HL, {"type": "metaAndAssetCtxs"})
    for s in ["BTC", "ETH", "SOL"]:
        get(f"hl_fundinghist_{s}.json", HL, {"type": "fundingHistory", "coin": s, "startTime": now_ms - 31 * 86400_000})
    for s in SYMS:
        inst = f"{s}-USDT-SWAP"
        get(f"okx_funding_{s}.json", f"https://www.okx.com/api/v5/public/funding-rate?instId={inst}")
        get(f"okx_oi_{s}.json", f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst}")
    for s in ["BTC", "ETH"]:
        get(f"okx_fundinghist_{s}.json", f"https://www.okx.com/api/v5/public/funding-rate-history?instId={s}-USDT-SWAP&limit=100")
        get(f"okx_oihist_{s}.json", f"https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy={s}&period=1D")
        get(f"okx_liq_{s}.json", f"https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&uly={s}-USDT&state=filled&limit=100")
    # 4) Sentiment / market structure / on-chain
    get("fng.json", "https://api.alternative.me/fng/?limit=60")
    get("coingecko_global.json", "https://api.coingecko.com/api/v3/global")
    get("coinmetrics_btc.json", "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapMVRVCur,AdrActCnt,FlowInExUSD,FlowOutExUSD,HashRate,TxCnt&frequency=1d&start_time=2026-09-01&page_size=200")
    get("blockchain_stats.json", "https://api.blockchain.info/stats")
    get("mempool_diff.json", "https://mempool.space/api/v1/difficulty-adjustment")
    get("mempool_hashrate.json", "https://mempool.space/api/v1/mining/hashrate/3m")
    # 5) Macro: FRED public CSV (may arrive zipped)
    b = get("fred_raw.bin", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500,DGS10,VIXCLS,DTWEXBGS,DFF&cosd=2025-10-01")
    if b:
        try:
            z = zipfile.ZipFile(io.BytesIO(b)); (out / "fred_unzipped_names.json").write_text(json.dumps(z.namelist()))
            for nm in z.namelist():
                (out / ("fred_" + nm.replace("/", "_"))).write_bytes(z.read(nm))
        except zipfile.BadZipFile:
            (out / "fred.csv").write_bytes(b)
    (out / "MANIFEST.json").write_text(json.dumps(dict(stamp=stamp, items=man), indent=1))
    bad = [m["name"] for m in man if not m["ok"]]
    print(stamp, "items", len(man), "failed", bad)
    return stamp

if __name__ == "__main__": main()
