# Codex Strategy Lab

Reproducible Stage 02 research for BTCUSDT, ETHUSDT and SOLUSDT on Binance spot.
This repository contains executed historical calculations, source code, data audits,
trade/fill ledgers and an independent research assessment. No orders or trading
credentials are used.

**Start with [REPORT.md](REPORT.md).** Results are conditional on explicitly assumed
execution costs and filters. Historical market status and order-book data remain
unverified. The fixed surviving cohort and correctness reruns limit validation.
No strategy receives an unconditional Pass.

## Codex Cloud

Use the [Cloud setup guide](docs/CODEX_CLOUD.md) to attach this repository and
enable **all public internet access** for setup and agent tasks. Install script:

```bash
bash .codex/setup.sh
```

Paste [the start instructions](docs/CODEX_CLOUD_START.md) into the Cloud
environment's Start skill field, then save/publish it. The legacy maintenance
script is `bash .codex/maintenance.sh`. Repository files cannot enable the
platform's internet-access setting.

After installation:

```bash
scripts/lab doctor --network
scripts/lab test
scripts/lab reproduce
```

Setup uses Python 3.12, a local `.venv`, and fully pinned dependencies. It checks
public HTTPS access and runs fast synthetic tests. Full reproduction is explicit
and runs in an isolated worktree, preserving the committed research evidence.
No API keys are required. See [AGENTS.md](AGENTS.md) for agent instructions.

## Reproduce

For Cloud, prefer `scripts/lab reproduce` above. The original direct commands
below run **in place** and overwrite the current checkout's research artifacts.

Python 3.12; dependencies pinned in `requirements.txt`.

```bash
python -m pip install -r requirements.txt
python download.py
python verify_data.py
python -m unittest -v test_lab
python -W ignore::FutureWarning run.py --sensitivity
python validate_results.py
python make_report.py
```

Downloads use the public Binance archive without authentication. The primary
dataset contains 492 official-checksum-verified monthly/daily files for 1H and
1-minute candles, including warm-up from May 2021. Raw data are cached locally
and excluded from Git. Allow roughly 2 GB of disk space and several GB RAM.
Sample native 4H verification artifacts are recorded separately in `results/`.

The frozen evaluation interval is November 17, 2021 through November 16, 2026
UTC, split into three-year training, one-year validation and one-year final test.
Each split is a separate $10,000 experiment. Signal parameters are unchanged
from the normalized [STAGE_01_HANDOFF](STAGE_01_HANDOFF.json).

- [Preregistration](PREREGISTRATION.md): dates, metrics, costs, decision rules
- [Report](REPORT.md): final results, caveats and assessment
- `lab.py`: indicators, risk allocator, minute execution and metrics
- `download.py`: checksum-verifying provider ingestion
- `run.py`: split evaluation, benchmarks, uncertainty, parameter/cost sensitivity
- `test_lab.py`: synthetic correctness checks, never historical performance
- `validate_results.py`: independent artifact arithmetic checks
- `results/`: reproducible metrics, equity, fills, trades, audits and provenance

Sharpe uses daily returns and 365.25-day annualization. Dollar labels assume
USDT=USD; no depeg robustness is claimed. No future profitability is established.
