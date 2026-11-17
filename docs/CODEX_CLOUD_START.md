Read the repository's `AGENTS.md` and `docs/CODEX_CLOUD.md`.

From the `codex-strategy-lab` checkout, run:

```bash
bash .codex/maintenance.sh
bash .codex/start.sh
```

Both commands must succeed before declaring the runtime ready. Use `scripts/lab`
for subsequent Python and test commands. This project needs no server or port.
Do not run a backtest or rewrite historical results merely to start the environment.
Keep full public internet access enabled in the environment configuration, and
preserve its inherited proxy and certificate settings. If a route fails, report
the failed service and status code; repository scripts cannot change platform
network policy. No trading or OpenAI API credentials are required.
