"""Small, read-only runtime checks; no research runs or credential inspection."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NETWORK_TARGETS = {
    'PyPI metadata': 'https://pypi.org/pypi/numpy/2.3.5/json',
    'GitHub repository': 'https://github.com/JackSmack1971/codex-strategy-lab',
    'Binance archive checksum': 'https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2021-10.zip.CHECKSUM',
}

def pins(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;]+)', line)
        if not match:
            raise ValueError(f'Expected an exact package pin in {path.name}')
        result[match[1].lower().replace('_', '-')] = match[2]
    return result

def probe(label: str, url: str) -> dict:
    try:
        # urllib honors inherited proxies and TLS trust; never print env or headers.
        with urllib.request.urlopen(url, timeout=20) as response:
            status = response.status
            body = response.read(1_000_000)
        ok = status == 200
        if label == 'Binance archive checksum':
            ok = ok and bool(re.match(rb'^[0-9a-f]{64}\s', body))
        elif label == 'PyPI metadata':
            metadata = json.loads(body)
            ok = ok and metadata['info']['version'] == '2.3.5'
        return {'service': label, 'url': url, 'ok': ok, 'http_status': status}
    except urllib.error.HTTPError as error:
        return {'service': label, 'url': url, 'ok': False, 'http_status': error.code}
    except Exception as error:
        # Exception messages can contain proxy URLs with credentials. Log class only.
        return {'service': label, 'url': url, 'ok': False, 'error_type': type(error).__name__}

def runtime_checks() -> tuple[list[str], dict]:
    errors = []
    if sys.version_info[:2] != (3, 12):
        errors.append('Python 3.12 is required.')
    locked = pins(ROOT / 'requirements-cloud.lock')
    direct = pins(ROOT / 'requirements.txt')
    if not all(locked.get(k) == v for k, v in direct.items()):
        errors.append('requirements-cloud.lock does not match direct runtime pins.')
    installed = {}
    for name, required in locked.items():
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed[name] = None
        if installed[name] != required:
            errors.append(f'{name}: expected {required}, installed {installed[name]}.')
    if not shutil.which('git'):
        errors.append('git executable is missing.')
    # Import and save a tiny chart in ignored scratch storage, no historical inputs.
    try:
        os.environ['MPLBACKEND'] = 'Agg'
        os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.cache' / 'matplotlib'))
        import numpy as np
        import pandas as pd
        import matplotlib.pyplot as plt
        assert pd.Series(np.array([1., 2.])).sum() == 3.
        cache = ROOT / '.cache' / 'codex-cloud'
        cache.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(1, 1)); ax.plot([0, 1], [0, 1])
        fig.savefig(cache / 'plot-smoke.png'); plt.close(fig)
    except Exception as error:
        errors.append(f'Numeric/plot import smoke check failed: {type(error).__name__}.')
    policy = 'unknown'
    try:
        snapshot = json.loads(Path('/etc/codex/network-policy.json').read_text())
        policy = snapshot.get('http_network_policy', {}).get('type', 'unknown')
    except (OSError, ValueError):
        pass
    # Startup snapshot is diagnostic only, not a substitute for live platform status.
    info = {'python': platform.python_version(), 'executable': sys.executable,
            'packages': installed, 'network_policy_startup_snapshot': policy,
            'available_disk_GiB': round(shutil.disk_usage(ROOT).free / 2**30, 2),
            'lock_sha256': hashlib.sha256((ROOT / 'requirements-cloud.lock').read_bytes()).hexdigest()}
    return errors, info

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', action='store_true')
    parser.add_argument('--write-state', action='store_true')
    args = parser.parse_args()
    errors, info = runtime_checks()
    network = []
    if args.network:
        with ThreadPoolExecutor(max_workers=3) as pool:
            network = list(pool.map(lambda item: probe(*item), NETWORK_TARGETS.items()))
        if not all(r['ok'] for r in network):
            errors.append('Public HTTPS check failed. See docs/CODEX_CLOUD.md; preserve proxy and TLS settings.')
    result = {'ok': not errors, 'checked_utc': datetime.now(timezone.utc).isoformat(),
              'runtime': info, 'network_checks': network, 'errors': errors,
              'network_scope': 'Endpoint checks establish only these public HTTPS routes, not unrestricted access.'}
    if args.write_state and not errors:
        path = ROOT / '.cache' / 'codex-cloud' / 'setup-state.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1

if __name__ == '__main__':
    raise SystemExit(main())
