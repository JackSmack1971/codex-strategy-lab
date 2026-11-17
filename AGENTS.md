# Codex Strategy Lab

## Start here

Read `docs/CODEX_CLOUD.md` for environment setup and `PREREGISTRATION.md` before
research changes. Use Python 3.12 through `scripts/lab`; it selects the repository
virtual environment and a headless plotting backend without relying on shell
activation surviving across commands.

```bash
bash .codex/setup.sh              # idempotent dependency install and checks
scripts/lab doctor --network      # dependency + public HTTPS checks
scripts/lab test                  # offline synthetic/engineering tests
```

## Research integrity

- Research only. Do not place orders, connect trading credentials or add trading
  execution. Public historical data require no exchange or OpenAI API keys.
- Preserve `REPORT.md`, `results/`, `PREREGISTRATION.md` and the original handoff
  as historical evidence. Setup/start/maintenance must not run a backtest or
  rewrite those files. Existing performance is conditional and test data consumed.
- Use `scripts/lab reproduce` (or append `--sensitivity`) for a new, isolated
  detached worktree under `work/runs/`. It uses committed source at HEAD; commit
  source changes before reproducing them. New research is never an untouched
  holdout simply because it ran in a new directory.
- Distinguish measured facts, research hypotheses and unavailable information.
  Never infer profitability from engineering test success or synthetic fixtures.
- Do not alter signal timing, costs, risk limits or parameters as part of setup.
  Changes to research rules require a version and updated methodological record.

## Network and setup

The requested environment policy is full **public** internet access during setup
and the agent phase. This is a Codex Cloud environment setting, not a repo-file
permission. A successful endpoint check does not establish unrestricted access.
Preserve inherited proxy variables, CA configuration and TLS verification. Do not
change sandbox policy, firewall rules, authentication helpers or shell profiles.
If blocked, diagnose the actual service and report the relevant environment setting.

Dependencies: runtime direct pins in `requirements.txt`; complete Cloud Python
pins in `requirements-cloud.lock`. Regenerate the latter in a clean Python 3.12
venv after dependency changes; validate both. No extra testing package is needed:
the project uses standard-library unittest. Install only into `.venv/`.

## Verification and commands

For setup changes, run `scripts/lab test`, clean install, warm maintenance, and
`scripts/lab doctor --network`. A routine setup change does not justify rerunning
historical backtests. Network tests must use tiny public requests, not download
the full market dataset by default.

`scripts/lab prefetch hourly|full` optionally prepares checksum-verified data in
ignored `data/` and an ignored cache manifest. It does not touch tracked evidence.
`scripts/lab reproduce --sensitivity` explicitly runs the full research pipeline;
the isolated run path is printed and retained. Review its source hashes, audit
and metrics before making new performance claims. Raw downloads, `.venv/`, cache
and `work/` must remain untracked. Do not commit secrets or environment dumps.
