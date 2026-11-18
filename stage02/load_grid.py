import pickle, time
from pathlib import Path
from . import engine as E, data as D
CACHE = Path(__file__).resolve().parents[1] / "data" / "s2grid.pkl"
def get():
    if CACHE.exists(): return pickle.loads(CACHE.read_bytes())
    frames = {}
    for s in E.SYMS:
        d, _ = D.load(s); frames[s] = d.assign(t=d["t"])[["t", "o", "h", "l", "c", "v", "q"]]
    n = 48648
    syms = E.build_grid(frames, n); CACHE.write_bytes(pickle.dumps(syms)); return syms
