"""Stage 06: fetch adjacent-asset HOLDOUT klines (BNB, DOT, ATOM, BCH) from the Binance public archive. Checksum verified.
Writes only to ignored data/s6hold/. No credentials. NO strategy is run on these assets here: data-quality audit only."""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from stage02 import fetch as F
F.ROOT = Path(__file__).resolve().parents[1] / "data" / "s6hold"
HOLD = ["BNB", "DOT", "ATOM", "BCH"]
if __name__ == "__main__":
    jobs = [(s, "m", t) for s in HOLD for t in F.months()] + [(s, "d", t) for s in HOLD for t in F.days()]
    res = {}
    with ThreadPoolExecutor(12) as ex:
        for a, st in ex.map(F.job, jobs): res[st] = res.get(st, 0) + 1; (st not in ("verified", "cached")) and print(a, st)
    print(res)
