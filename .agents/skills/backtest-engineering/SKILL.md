---
name: backtest-engineering
description: "Prepare verified candidate implementation and supervisor-owned isolated dispatch; not historical reproduction or live execution."
---
# Backtest Engineering

Inspect research/experiments/dispatch.py, research/experiments/isolation.py and tests/research/vertical.py. Quant engineer prepares code, exact experiment/inputs/config and focused synthetic verification; supervisor alone dispatches a registered trial through run_candidate, which writes trial and run records. Confirm ledger identity, REVIEW_RECORDED then PREREG_FROZEN then EXPERIMENT_PENDING, frozen input digest, budget and unused trial/run IDs. Reconcile STARTED trials and artifacts before retry, not blind replay.

For run_candidate, keep in_memory_datasets=False unless the supervisor verifies and records evidence that data exists exclusively in memory, the child receives only brokered inputs, and no accessible files, caches, network, inherited handles or alternate path can supply the reserved split. Inspect actual loaders, experiment implementation and runtime boundary; record dataset and source digests and scope of the check. A module:function string or a temporary working directory alone is not isolation proof. Callable experiments remain IN_PROCESS_UNENFORCED regardless of flag. Same-user file access is FILE_BACKED_UNENFORCED. Unknown isolation remains unqualified; do not open genuine reserved file-backed holdouts or run an untouched confirmation without independently verified isolation. Synthetic fixtures may exercise broker accounting, not establish market qualification or OS enforcement. Never write protected results or construct lab.Market in the real tree. Capture trial/run/artifact identities and enforcement evidence; every candidate attempt counts.

Return evidence, limitations, and next safe action. Follow AGENTS.md; this skill grants no authority.
