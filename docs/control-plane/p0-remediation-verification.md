# P0 remediation verification record (follow-up to the failing audit)

`docs/control-plane/p0-acceptance-audit.md` is the **original failing assessment** and is preserved byte-for-byte
(SHA-256 `36752e11b5b49be4a0099c2ac0614d18f3c3f28dbc4e15cc39f906ed9e0f3696`, unchanged after remediation).
This file is a separate record of the remediation cycle. It does not revise the audit's conclusions.

Labels: **OBSERVED** = executed in this cycle; **LOCAL** = inspected; **INFERENCE**; **UNVERIFIED**; **NOT RUN**.
Host: Windows 11 (Python 3.12 `.venv`, pandas 2.2.3); POSIX evidence: WSL2 Ubuntu-24.04, Python 3.12.3 (stdlib only, no pandas).
The remediation was written by the implementer and has **not** been re-reviewed by the independent reviewers.

## 1. Finding-to-fix traceability

| Finding | Fix (files) | Regression evidence (OBSERVED) | Status |
|---|---|---|---|
| H1 `data/` ignores `research/data/` | `.gitignore:1` -> `/data/` | `Packaging` test (`git check-ignore`); clean-checkout copy of tracked + untracked-non-ignored files imports and passes | FIXED |
| C1 consumed holdout reusable | new `research/holdout.py` (global registry: instrument x test range, independent of id/version/family/run), checks in `ledger.py` at prereg freeze, trial start and replay; prereg `datasets`; legacy window consumed for every instrument | `GlobalHoldout` (9 tests: version change, renamed hypothesis+family, partial/disjoint overlap, interrupted run, second trial, exploratory policy, replay of a buggy writer, adjudication integrity) | FIXED, limits in 6 |
| C2 cost stress bypass | prereg `economics`, `purge`, `multiplicity.alpha` (frozen); `validation/economics.py` derives every gate metric from `execution.json` (fills + trades) incl. t-test p-value; `validation/adjudicate.py` gates only on recomputed values, adds `core-*` gates (min sample, EVERY cost stress > 0, adjusted p <= alpha); trial must bind `cost_model_hash` = digest(frozen economics) | `IndependentEconomics`, `Dispositions` (G09 also without any stress gate), mutation checks | FIXED |
| C3 forged adjudication accepted | new `validation/derive.py`; `ledger.py` re-derives and compares on append (strict) and on every replay (`ADJUDICATION_MISMATCH`, `EVIDENCE_UNAVAILABLE`, scan `evidence.status`) | `LedgerRefusesSelfAttestedAdjudication` (8 tests) | FIXED, limits in 6 |
| H2 repeated peeking / optional p-gate | one UNTOUCHED trial per claim (`HOLDOUT_CONSUMED`), `core-multiplicity`, every attempt counted | `test_a_second_untouched_trial...`, `test_qualification_cannot_bypass_multiplicity...`, Bonferroni test | FIXED (COUNT_ONLY applies no correction by definition) |
| H3 uncounted reads / `ctx._datasets` | `RunContext` has no dataset attributes; counting `Broker`; child-process runner (`experiments/child.py`); enforcement recorded in the run manifest; only `IN_MEMORY_BROKERED` can support UNTOUCHED | `AccessBoundary` (3 tests) | FIXED conservatively: in-process / file-backed runs are capped at `PROMISING_UNVALIDATED`; not an OS sandbox |
| H4 self-attested certificate and review | new `research/evidence_store.py`; `DATA_QUALIFIED` and `REVIEW_RECORDED` need content-addressed bundles that are re-derived / re-executed by the ledger | `VerifiableEvidence` (6 tests), CLI free-text test | FIXED for what is checkable; reviewer **independence UNVERIFIED (Phase 6)** and archive bytes are not re-hashed |
| H5 family / identity escape | `re.fullmatch` patterns, `FAMILY_REASSIGNMENT`, `strict_loads` (duplicate keys, NaN) for ledger, CLI, artifacts | `IdentityAndParsing` | FIXED; family migration deliberately not implemented |
| M1/F11, G07 false COMPLETED | `reconcile_interrupted_trials` verifies files on disk, reconciles run manifests | `test_completion_with_a_made_up_hash_is_refused`, `test_reconcile_completes_only_from_artifacts_actually_on_disk` | FIXED |
| F9 purge/embargo | prereg `purge` geometry check (`PURGE_GAP_TOO_SHORT`); trade labels may not cross the split end or start inside the embargo | `IndependentEconomics` | FIXED |
| F10 RUN_ID_REUSE / caches | `__pycache__`, `*.pyc` excluded from digests; interrupted runs reconcilable | `test_interpreter_caches_never_enter_digests` | FIXED (cause removed; not reproduced end to end) |
| F12 links/junctions | `isolation.assert_no_links` on the lexical path before any mkdir or resolve; CLI root refusal exits 2 | Windows junction (CLI and `RunDir`) OBSERVED; POSIX symlink OBSERVED in WSL | FIXED |
| F13-F15 | `fullmatch`, duplicate keys, `event_at <= published/available/ingested`, future coverage claim -> `COVERAGE_CLAIM_IN_FUTURE` | tests in `IdentityAndParsing`, `VerifiableEvidence` | FIXED |
| M3 | `docs/control-plane/phase0-baseline.md` (post-hoc, labelled as such) | digest re-computed identical | DONE |
| M4 | `test_legacy_compat` now calls the shipped `legacy_adapter` and asserts nonzero signals (fixture `quote_volume` passes the legacy liquidity filter) | OBSERVED, 6000 bars give nonzero signals | FIXED |
| M6 | missing mandatory evidence -> `BLOCKED` (blueprint 8); tests assert `BLOCKED` exactly | `Dispositions`, vertical slice | FIXED |
| LOW (not required) | CLI root escape now exits 2; scope filter reworked (whole-token keys, buy/sell phrasings); engine digest CRLF-normalised | `test_cli`, `test_isolation` | FIXED |
| LOW (not addressed) | vertical slice never records REPORTED; orphan run dirs; legacy adapter timezone shift; synthetic QUALIFIED marker; tail-reconciliation window; `microstructure_admission` trusts caller booleans; leaked temp dirs | - | OPEN (out of the authorised list) |

Mutation check (OBSERVED, copies of the tree, real tree untouched): re-introducing each original defect made the matching
regression tests fail in 7 of 7 cases (C3 no re-derivation; C1 registry never conflicts; C2 gate values from reported metrics; C2 no
intrinsic stress gate; H5 `re.search`; G07 trusted hash; H3 enforcement ignored).

## 2. Files changed in this cycle

Tracked: `.gitignore` (1 line). New: `research/holdout.py`, `research/evidence_store.py`, `research/experiments/child.py`,
`research/validation/derive.py`, `tests/research/fixture_experiments.py`, `tests/research/test_p0_remediation.py`,
`docs/control-plane/p0-acceptance-audit.md`, `phase0-baseline.md`, `p0-remediation-verification.md`.
Modified (previously untracked Phase 0-5 files): `research/contracts.py`, `ledger.py`, `data/qualification.py`, `data/legacy_ohlcv.py`,
`experiments/dispatch.py`, `isolation.py`, `pipeline.py`, `provenance.py`, `validation/adjudicate.py`, `economics.py`,
schemas `preregistration`, `run_manifest`, `adjudication`, `scripts/research.py`, docs `validation-policy.md`, `alpha-ledger-policy.md`,
`architecture.md`, tests `builders`, `flow`, `slice`, `vertical`, `archives`, `test_adjudication`, `test_cli`, `test_contracts`, `test_isolation`,
`test_ledger`, `test_legacy_compat`, `test_vertical_slice`.
Schema note: preregistration, run manifest and adjudication gained REQUIRED fields without a version bump (`1.0.0`) because no
ledger had been committed or deployed; any pre-existing ledger would no longer validate.

Tests changed and why (no check was weakened to pass): the old tests that **asserted the defects** were inverted
(`test_completion_with_evidence_is_accepted` accepted a made-up hash; `Happy.test_full_lifecycle...` appended a self-attested adjudication;
the INVESTIGATE-or-BLOCKED assertions now require BLOCKED). `test_data_not_qualified_blocks` took an external certificate that no longer
exists; its intent is covered by the dataset-evidence tests. Fixtures gained the new required fields; fixture dates moved into the past so
no fixture claims future coverage. Multi-trial family tests use `EXPLORATORY_OR_REUSED` because a second UNTOUCHED trial is now correctly refused.

## 3. Tests executed (OBSERVED)

| Check | Result |
|---|---|
| `python -m unittest discover -s tests/research -t .` on the work tree (Windows) | 193 tests OK, 2 skipped (symlink privilege) |
| same suite on a copy of tracked + untracked-non-ignored files (clean-checkout equivalent, not committed) | 193 OK, 3 skipped (adds the git-only ignore test) |
| same suite on POSIX (WSL2, Python 3.12.3, copy of the above) | 192 OK, 3 skipped (pandas legacy-equivalence class, Windows junction test, git test); POSIX symlink tests ran and passed |
| `test_lab` + `tests.test_cloud_setup` (Windows interpreter) | 9 errors, **identical** to a pristine `git archive HEAD` run: `bash -n` path mangling (7 sub-cases) and `WinError 1314` symlink privilege (2). No regression attributable |
| real `scripts/research.py` process | usage 2, root escape 2, `status` 0 (OBSERVED in tests) |
| POSIX `scripts/lab research ...` wrapper (scratch copy with LF scripts and a stdlib interpreter) | `status` 0, root escape 2, usage 2, `ledger-verify` 0 |
| `git diff --check` (tracked) | exit 0 |
| per-file whitespace/marker check of all 65 untracked non-cache files (`git diff --no-index --check`) | 0 findings |
| process-level lock test | second process sees `LOCK_HELD`, then acquires after release; multi-process concurrent appends NOT run |
| GitHub Actions | **NOT RUN** (no remote run authorised; nothing pushed) |

## 4. G01-G16 after remediation

| Gate | Status | Basis |
|---|---|---|
| G01 | **PASS for tests; setup half UNVERIFIED** | 183/183 protected files identical before/after; setup scripts not run (prohibited) |
| G02 | PASS | `test_asof` |
| G03 | PASS (function level) | the ledger still does not require as-of output before `DATA_QUALIFIED` (F6, unchanged) |
| G04 | PASS | `test_asof`; as-of tie-break is silent (F20, unchanged) |
| G05 | PASS | ledger and CLI tests |
| G06 | PASS (threads; process-level lock exclusion) | multi-process contended appends NOT run |
| G07 | PASS | reconcile verifies files on disk; run manifests reconciled |
| G08 | PASS | corrupt / missing / extra artifact -> BLOCKED |
| G09 | PASS | core stress gates; forged metrics BLOCKED; works without a preregistered stress gate |
| G10 | **P0 synthetic leakage detection: PASS. Phase 6 independent-agent catch/miss-rate: UNVERIFIED, not claimed** | review bundles are re-executed deterministically; reviewer independence and miss-rate measurement belong to Phase 6 |
| G11 | PASS | registry + ledger-side re-derivation; forged records refused |
| G12 | PASS (no trading path); scope reporting improved, still keyword-based | |
| G13 | PASS | UNKNOWN mandatory gate -> BLOCKED; forged PASS refused at the ledger |
| G14 | PASS | `microstructure_admission` still trusts caller booleans (F23, unchanged) and is not wired into a pipeline |
| G15 | **BLOCKED** | literal command `bash scripts/lab test` on this Windows host: fails with `Missing .venv` (`common.sh` wants `.venv/bin/python`; this venv has `Scripts\python.exe`). Equivalent Windows-interpreter run: 9 host-limit errors, identical to pristine HEAD. POSIX scratch copy: `scripts/lab test` rc 1 (`numpy` absent in WSL). Not a run of the real repo on Linux/Cloud |
| G16 | PASS as worded | tracked diff check exit 0; all 65 untracked files checked; 4 tracked files modified (3 additive pre-existing + `.gitignore`); no test deleted without replacement (section 2) |

## 5. Remaining blockers and unverified behaviour

- No independent re-review of this remediation; no observed GitHub Actions run; literal `scripts/lab test` not run on a supported Linux/Cloud host.
- The access boundary is a process boundary, not an OS sandbox. `QUALIFIED` is reachable only for child-process runs over in-memory datasets; real file-backed data is capped at `PROMISING_UNVALIDATED` until an OS-level boundary exists.
- Hash chain + evidence store give tamper evidence, not prevention: a writer who controls the ledger, the evidence directory and the run directory can forge all three consistently. Recorded fills are the experiment's fills, not exchange fills.
- Dataset manifests are re-derived but their archive hashes are not re-hashed against archive bytes; correlated-instrument holdout contamination is not modelled; reviewer independence UNVERIFIED (Phase 6); no family migration path.
- Cross-host digest parity (Windows vs Linux) beyond passing tests, multi-process contended appends, and end-to-end reproduction of the original `RUN_ID_REUSE` are NOT run.
- LOW items listed in section 1 remain open.

## 6. Protected Stage 02 artifacts (OBSERVED)
Before and after remediation: 183 tracked protected files (`REPORT.md`, `PREREGISTRATION.md`, `STAGE_01_HANDOFF.json`, `results/**`) have identical per-file
SHA-256 and equal their `HEAD` blobs; listing digest `74d49e524cfdb0238d7b803291f7ddfdf9b15bf15845813a8ec319492a3df6fc` both times.

## 7. Recommendation: **CONDITIONAL**
The three CRITICAL and five HIGH defects are fixed with executed regression evidence and mutation checks, and no protected artifact changed. Not ACCEPT because the
fixes are unreviewed by an independent reviewer, G15 and CI are unrun, G10's Phase 6 half is unverified, and the stated limits above remain. Conditions: independent
re-audit of this change set, an authorised Linux/Cloud run of the literal `scripts/lab test` and an observed CI run, then an explicit commit decision. Phase 6 has not been started.
