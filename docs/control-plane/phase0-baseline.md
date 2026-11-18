# Phase 0 baseline record (finding M3) - recorded at remediation start, not backdated

The P0 audit found no Phase 0 baseline record. This file records the baseline **as observed when remediation
began** (2026-11-18); it is an addition, not a rewrite of any historical evidence, and it does not claim to be
what Phase 0 saw at the time.

| Item | Observed value (LOCAL / OBSERVED) |
|---|---|
| Git HEAD | `09fdca655193452966740d2236c4a5d5aebdd4e5` (branch `main`) |
| Tracked protected files | 183 (`REPORT.md`, `PREREGISTRATION.md`, `STAGE_01_HANDOFF.json`, every tracked file under `results/`) |
| Each protected file vs HEAD blob | identical (`git hash-object` equals `git rev-parse HEAD:<path>` for all 183, per the audit and re-checked by hash listing) |
| SHA-256 of the sorted `sha256sum` listing of those 183 files | `74d49e524cfdb0238d7b803291f7ddfdf9b15bf15845813a8ec319492a3df6fc` |
| Modified tracked files before remediation | `.github/workflows/cloud-readiness.yml`, `AGENTS.md`, `scripts/lab` |

Reproduce (read-only): `git ls-files REPORT.md PREREGISTRATION.md STAGE_01_HANDOFF.json results | xargs sha256sum | sha256sum`.
The listing digest is the figure to compare before and after any setup, test or run. Stage 02 evidence is never a valid
output location for the research workbench.
