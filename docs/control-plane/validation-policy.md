# Validation and adjudication policy (PROPOSED project design)

Implemented in `research/validation/*` and `research/experiments/{isolation,dispatch,pipeline,legacy_adapter}.py`.

## Boundaries
- Research only. `dispatch.check_scope` refuses requests/configs that mention order placement, live
  trading, exchange accounts or credentials (`UNSUPPORTED_SCOPE`) before any file or ledger write.
  There is no trading, account or credential code path.
- Candidate output goes only to `work/research-runs/<run_id>/` (git-ignored). Existing run
  directories are never reused; run ids and artifact names are simple identifiers; symlinked `work/`
  is refused. `REPORT.md`, `PREREGISTRATION.md`, `STAGE_01_HANDOFF.json` and `results/` are hashed
  before and after each run; any change fails the trial with `PROTECTED_MODIFIED`.
- The ledger records the trial `STARTED` before the experiment runs. A crash leaves it `STARTED`
  (blocking completion) until `reconcile_interrupted_trials`. A failed run is recorded `FAILED`
  and stays in the family count; it is not a `REJECT` of the hypothesis.
- Legacy engine reuse is limited to the pure `lab.features()` via `legacy_adapter`; `lab.Market`
  (which writes `results/data_audit.json`) is not constructed.

## Test-set access and the global holdout registry
Brokered experiments (`"module:function"` run in a child process) obtain data only through
`ctx.data(split)`; the parent counts every `test` read BEFORE serving it. In-process callables
cannot be hidden from their own process, so those runs are recorded `IN_PROCESS_UNENFORCED`; file-backed
data stays readable by a same-user child, so those runs are `FILE_BACKED_UNENFORCED`. Only a child process
over datasets that exist solely in the parent's memory is `IN_MEMORY_BROKERED`, and only that can support an
`UNTOUCHED` confirmation. This is a process boundary, not an OS sandbox.

`research/holdout.py` derives a registry from the ledger that ignores hypothesis id, version, family and run:
the key is (instrument named in the frozen preregistration `datasets`, test time range).
Exposure policy: a trial whose preregistration claims `UNTOUCHED` consumes its test range from the moment it is
recorded `STARTED` (a crash makes the number of reads unknowable); any trial with `test_access_count >= 1` or that
did not end `COMPLETED` consumes it; an exploratory trial that completed without reading its test range consumes
nothing; train/validation reads do not consume a confirmation holdout by themselves. The Stage 02 window is
consumed for every instrument. Correlated-instrument contamination is NOT modelled. A conflicting
`UNTOUCHED` claim is rejected at preregistration freeze (`HOLDOUT_CONFLICT`), at trial start (`HOLDOUT_CONSUMED`)
and on replay.

## Adjudication (research/validation/adjudicate.py, derive.py)
Gate values come ONLY from metrics recomputed from verified execution artifacts (`execution.json`: fills and trades)
and the FROZEN preregistered `economics` (cost per trade, stress multipliers, evaluation split), `purge` and
`multiplicity.alpha`. The experiment's `metrics.json` is descriptive and must agree with the recomputation.
Gate families: `sys-*` (integrity), `core-*` (minimum sample, positive net return at EVERY frozen cost stress,
multiplicity-adjusted p-value <= alpha - no preregistration can omit them) and the preregistered gates.
1. Any `sys-*` gate not PASS -> **BLOCKED**.
2. Any mandatory gate FAIL -> **REJECT**.
3. Any mandatory gate UNKNOWN (required evidence missing) -> **BLOCKED** (blueprint section 8).
4. Any mandatory gate NOT_APPLICABLE -> **INVESTIGATE**.
5. All mandatory PASS and holdout integrity `UNTOUCHED` -> **QUALIFIED** (research-qualified only).
6. All mandatory PASS otherwise -> **PROMISING_UNVALIDATED**.
The ledger re-derives the same record from authoritative state on append and on every replay
(`ADJUDICATION_MISMATCH` otherwise); see alpha-ledger-policy.md. Reviewer independence stays UNVERIFIED until Phase 6.

## Multiplicity
Every attempted trial in the family (failed, aborted, interrupted, superseded) counts. Supported
methods: COUNT_ONLY, BONFERRONI, SIDAK. Others block. Deflated Sharpe and PBO are not implemented.

## What this does not establish
Passing machinery tests on synthetic data says nothing about market profitability. Cost models are
preregistered assumptions; fills, capacity and venue filters remain unverified for the legacy OHLCV data.
