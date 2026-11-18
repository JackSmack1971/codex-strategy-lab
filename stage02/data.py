"""Load + audit 1H klines. Timestamps normalised (>1e14 => microseconds). Bar time = OPEN time, UTC."""
import io, json, zipfile
from pathlib import Path
import numpy as np, pandas as pd
RAW = Path(__file__).resolve().parents[1] / "data" / "s2raw"
SYMS = ["BTC","ETH","SOL","XRP","ADA","LINK","AVAX","DOGE","LTC"]
COLS = ["t","o","h","l","c","v","ct","q","n","tb","tq","ig"]
def load(sym):
    frames, files = [], 0
    for z in sorted((RAW / (sym + "USDT")).glob("*.zip")):
        with zipfile.ZipFile(z) as zf:
            for nm in zf.namelist():
                df = pd.read_csv(zf.open(nm), header=None, names=COLS)
                if not str(df.iloc[0, 0]).lstrip("-").isdigit(): df = df.iloc[1:]
                frames.append(df.astype({"t": "int64"})); files += 1
    d = pd.concat(frames, ignore_index=True)
    raw_n = len(d)
    t = d["t"].to_numpy()
    d["t"] = np.where(t > 10**14, t // 1000, t)
    d["ts"] = pd.to_datetime(d["t"], unit="ms", utc=True)
    for c in "ohlcvq": d[c] = d[c].astype(float)
    dups = int(d.duplicated("t").sum())
    d = d.drop_duplicates("t", keep="first").sort_values("t").reset_index(drop=True)
    return d[["ts","t","o","h","l","c","v","q","n"]], {"files": files, "raw_rows": raw_n, "duplicates": dups}
def audit(sym, d, meta):
    t = d["t"].to_numpy(); step = 3600_000
    gaps = np.diff(t); gi = np.where(gaps != step)[0]
    missing = int(((gaps[gi] // step) - 1).sum())
    ret = np.abs(np.log(d["c"].to_numpy()[1:] / d["c"].to_numpy()[:-1]))
    bad_ohlc = ((d.h < d[["o","c","l"]].max(axis=1)) | (d.l > d[["o","c","h"]].min(axis=1)) | (d[["o","h","l","c"]] <= 0).any(axis=1)).sum()
    return {"symbol": sym, **meta, "first": str(d.ts.iloc[0]), "last_open": str(d.ts.iloc[-1]), "rows": len(d),
        "gap_events": int(len(gi)), "missing_bars": missing, "max_gap_hours": int((gaps.max() // step) - 1) if len(gaps) else 0,
        "gap_list": [(str(d.ts.iloc[i]), int(gaps[i] // step - 1)) for i in gi][:30],
        "nonfinite": int((~np.isfinite(d[["o","h","l","c","v","q"]].to_numpy())).sum()),
        "ohlc_violations": int(bad_ohlc), "zero_volume_bars": int((d.v <= 0).sum()),
        "jumps_gt_20pct": int((ret > np.log(1.2)).sum()), "max_abs_1h_logret": float(ret.max()),
        "jump_list": [(str(d.ts.iloc[i+1]), float(ret[i])) for i in np.where(ret > np.log(1.2))[0]][:10]}
if __name__ == "__main__":
    out = []
    for s in SYMS:
        d, m = load(s); a = audit(s, d, m); out.append(a)
        print({k: v for k, v in a.items() if k not in ("gap_list","jump_list")})
        if a["gap_list"]: print("  gaps:", a["gap_list"][:8])
        if a["jump_list"]: print("  jumps:", a["jump_list"])
    Path(__file__).with_name("audit.json").write_text(json.dumps(out, indent=1))
