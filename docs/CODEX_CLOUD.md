# Codex Cloud setup

The repository supplies installation, cached-environment maintenance, runtime
diagnostics and isolated research-run scripts. It requires Bash, Git and Python
3.12 with `venv`; Linux with binary wheels is the tested target. No exchange,
OpenAI API or other application credentials are needed.

## Configure the reusable environment

In **Settings → Codex Cloud → Environments**, create or edit an environment for
`JackSmack1971/codex-strategy-lab`, branch `main`.

1. In network settings, enable **Enable all public internet access**. Keep this
   enabled for agent tasks, not just installation. Full public access includes
   package-manager and additional-host destinations; those narrower controls may
   be disabled in this mode. Workspace Agent Security requirements still apply.
2. Choose a Linux image providing Python 3.12, Bash and Git. Recommended resources:
   at least 8 GiB RAM and 8 GiB free disk for full research runs and isolated output
   copies. Setup and unit tests require much less. Each retained run consumes disk.
3. Set the **Install script** to the following command, run from this repository:

   ```bash
   bash .codex/setup.sh
   ```

4. Paste the instructions in [CODEX_CLOUD_START.md](CODEX_CLOUD_START.md) into the
   environment's **Start skill** field. This repo is a batch research tool: it
   needs a runtime check, not a continuously running server.
5. Run setup and inspect its successful dependency, HTTPS and unit-test checks.
   Save and **Publish** (or republish) the reusable environment. Start a **new task**
   from that published version and run `bash .codex/start.sh` to verify persistence.

The repo is not attached automatically merely because its URL is in a document.
The selected GitHub connection must grant access to this repository. Publishing
an environment and changing platform networking are separate from committing files.

**Repository files cannot switch on Cloud networking.** No `.codex/config.toml`
setting, shell `export`, environment variable or network probe overrides the Cloud
environment policy. This repository intentionally does not install a pretend
network-policy file or disable sandboxing/TLS. The current projectless environment
was observed with unrestricted public networking during implementation; that does
not configure a reusable environment for future tasks.

Official reference: [Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments).
UI labels can change; use the full-public-access setting in the environment editor.

### Codex Cloud Legacy environments

For the older setup/maintenance interface, use:

| Field | Value |
| --- | --- |
| Repository | `JackSmack1971/codex-strategy-lab` |
| Python | `3.12` |
| Setup script | `bash .codex/setup.sh` |
| Maintenance script | `bash .codex/maintenance.sh` |
| Agent internet access | On |
| Allowed domains | All / unrestricted |
| Allowed HTTP methods | All methods, if offered |

Setup runs in its own shell. Activation and `export` from that shell do not
automatically persist into agent commands. Use `scripts/lab` instead of relying on
`source .venv/bin/activate`. In the newer interface, the start instructions perform
the same maintenance after a checkout/snapshot resume.

Official references: [Legacy environment setup](https://learn.chatgpt.com/docs/environments/cloud-environment)
and [Legacy internet access](https://learn.chatgpt.com/docs/cloud/internet-access).

## Files and behavior

| File | Purpose |
| --- | --- |
| `.python-version` | Python 3.12 version hint |
| `requirements.txt` | Original direct runtime pins, preserved |
| `requirements-cloud.lock` | Complete exact Python package pins, matching the original installed research runtime |
| `.codex/setup.sh` | Idempotent initial installation entrypoint |
| `.codex/maintenance.sh` | Reconcile the current branch's pins after cache/snapshot reuse |
| `.codex/start.sh` | Verify runtime and public HTTPS routes |
| `scripts/lab` | Stable command entrypoint using `.venv/bin/python` |
| `scripts/doctor.py` | Version/import/plot, lock consistency and optional HTTPS checks |
| `scripts/prefetch.py` | Optional checksum-verified market archive cache |
| `scripts/reproduce.sh` | Full pipeline in a separate detached worktree |
| `AGENTS.md` | Commands and research integrity rules for future agents |
| `.github/workflows/cloud-readiness.yml` | CI installation, maintenance and smoke tests |

Setup creates only ignored `.venv/`, `.cache/` and `work/` state. It installs binary
wheels in the repository venv, verifies exact pins and `pip check`, saves a tiny
headless chart, probes public HTTPS services, and runs the ten original synthetic
engine tests plus eleven Cloud setup tests. It does **not** download five years of data by default, run a
backtest, rewrite results, change trading parameters or configure credentials.
The numeric/plotting package pins include dependencies, not only top-level packages;
this is an exact-version lock, not an artifact-hash lock.

The scripts preserve inherited proxy variables and certificate trust, never write
shell profiles, and never install globally. Logs omit environment values, request
headers and network exception messages that could contain credentials.

## Daily commands

From the repository root:

```bash
bash .codex/setup.sh
scripts/lab doctor --network
scripts/lab test
```

The shell entrypoints also resolve their location when invoked from another
directory. Shell activation is unnecessary.

After a cached environment resumes, `bash .codex/maintenance.sh` reconciles the
lock. If the environment is already installed and deliberately offline,
`bash .codex/maintenance.sh --offline` verifies pins/imports and tests without
attempting package installation or HTTPS requests. It fails when dependencies
are missing or differ; it does not silently downgrade the checks.

Optional platform environment variables:

| Name | Default | Meaning |
| --- | --- | --- |
| `STRATEGY_LAB_PYTHON` | `python3.12`, with compatible `python3` fallback | Base interpreter executable; must be Python 3.12 |
| `STRATEGY_LAB_PREFETCH` | `none` | `none`, `hourly` or `full`; optional cache warm-up during setup/maintenance |

Use environment settings for persistent choices. No `.env` file is loaded, and
no secret is needed. Thread counts and provider/proxy settings are left inherited.

### Optional archive cache

```bash
scripts/lab prefetch hourly
# Or cache all primary data and the six native-4H verification samples:
scripts/lab prefetch full
```

Hourly scope verifies 246 files; full scope verifies 498 files, including six 4H
samples. These use the original frozen historical horizon, not a moving latest
date. Cache warming writes `data/` and `.cache/codex-cloud/prefetch-*.json`, never
the committed download manifest. Missing files and checksum failures return a
nonzero exit. Cache directories may be discarded by the platform; scripts can
recreate them. Archive access, not Binance's geographically restricted trading
API, is the required data route.

### Explicit full reproduction

```bash
scripts/lab reproduce
```

Commit source edits first: reproduction always uses committed **HEAD**. The command
creates and retains a detached worktree in `work/runs/<UTC timestamp>-<suffix>`.
It copies any local raw cache into the worktree without shared mutable links or
derived pickle caches; the downloader rechecks each cached archive's saved hash.
Without a cache it downloads the data. It refuses to backtest if the complete
primary or native-4H manifests are not verified, then runs the full original
pipeline, including training-only parameter sensitivity, artifact validation and
report generation. `--sensitivity` is accepted explicitly as well; sensitivities
are always included because the report requires them.

The final run directory is printed, including on startup before calculations.
Failure leaves it available for diagnosis. Original `REPORT.md` and `results/`
remain untouched. To remove a reviewed run later, use `git worktree remove
<run-directory>`; Git refuses to discard changed/untracked results without force.
Preserve any useful outputs before removing a worktree.

These are consumed historical test data. Isolation protects files and provenance;
it does not create new out-of-sample evidence or authorize orders.

## Diagnostics

`scripts/lab doctor --network` checks PyPI metadata, the public GitHub repository
and a tiny Binance archive checksum. It records status codes and safe error
classes. The startup policy snapshot, if available, is labelled as such; only live
platform status can establish the current enforced policy. Working routes do not
prove unrestricted internet access to every service or raw TCP port.

- **Denied domain / HTTP 403:** inspect Cloud networking and any workspace Agent
  Security restriction. A service's own denial is different from a platform block.
- **Binance API HTTP 451:** the research downloader uses `data.binance.vision`,
  not authenticated/trading API endpoints. Test the actual archive route.
- **TLS/proxy failure:** preserve the inherited proxy and CA configuration; do not
  use `curl -k`, change certificate verification, or bypass network enforcement.
- **Missing Python 3.12/venv:** choose a compatible image/interpreter. Scripts fail
  with a direct message rather than using a different Python or requiring sudo.
- **Incompatible `.venv`:** move it aside and rerun setup. No script deletes it.
- **Pins changed:** update both requirements files and rerun maintenance. Validate
  a clean install before republishing the reusable setup.
- **GitHub writes unavailable:** checkout permission, full internet access and
  repository write authentication are separate. Use the configured Git connection;
  the scripts do not mint tokens or change authentication helpers.

## Verification scope

CI runs setup, the engineering tests, offline maintenance and a fresh network
check, then verifies tracked files stayed unchanged. It never reruns market
performance. Runtime readiness is not financial validation. Existing research
limitations and assessments remain in [REPORT.md](../REPORT.md).
