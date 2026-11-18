# P0 Independent Acceptance Audit (Original, Failing)

> **STATUS: ORIGINAL FAILING ASSESSMENT — PRESERVED UNCHANGED.**
> This is the independent P0 acceptance audit of Phases 0-5 as delivered before remediation
> (baseline HEAD `09fdca655193452966740d2236c4a5d5aebdd4e5`, dirty worktree). Its conclusions
> MUST NOT be rewritten after remediation. Adjudication: **P0 acceptance FAIL**. Post-remediation
> results are recorded separately in `docs/control-plane/p0-remediation-verification.md`.
> Sections: (1) coordinator's synthesized report, (2) raw reviewer report: goal-contract-reviewer,
> (3) raw reviewer report: experiment-integrity-reviewer. Reviewer disagreements are preserved
> in section 1 and visible in the raw reports. Text below is reproduced verbatim from the session
> transcript; only these section wrappers were added.

---

## Section 1 — Synthesized audit report

# P0 Independent Acceptance Audit: Phases 0–5

**Recommendation: do not accept P0.** Both reviewers returned a failing or blocked verdict, and there are three CRITICAL findings. The blocker is that an experiment, or a hand-written ledger record, can reach a recorded `QUALIFIED` decision that the blueprint says must be impossible.

I wrote no files and made no fixes. The findings below are the reviewers' reproduced results. I did not re-run their probes, so they carry the reviewers' evidence, not mine.

## 1. Baseline and scope
- **Target:** `src/codex-strategy-lab`, HEAD `09fdca655193452966740d2236c4a5d5aebdd4e5`, branch main.
- **Workspace:** Phases 0–5 are uncommitted. Three tracked files are modified: `.github/workflows/cloud-readiness.yml`, `AGENTS.md` and `scripts/lab`. There are 53 untracked files, plus four `research/data/*.py` files that `.gitignore` hides (finding H1).
- **Reviewers:** `goal-contract-reviewer` (verdict **BLOCKED**) and `experiment-integrity-reviewer` (verdict **FAIL**). Both were available and neither was substituted by me.
- **Permissions:** Both had Read, Grep, Glob and unsandboxed Bash, so read-only was enforced only by instructions and their own discipline.
  - Their before and after fingerprints (`git status`, `git diff`, protected files) were identical.
  - Their writes went to the scratchpad only. The integrity reviewer also created NTFS junctions there for the link-escape probe.
  - The contract reviewer's first few `git status` calls ran without `GIT_OPTIONAL_LOCKS=0`. These may have refreshed index stat data, with no content change.
  - My own `git status --short` calls carry the same caveat.
- **Commands:**
  - Tests: `-m unittest discover -s tests/research -t .` ran 144 tests, OK, with 2 skipped (symlink privilege). The equivalent of `scripts/lab test` was run as well.
  - Git checks: `git diff --check` (exit 0) and `git hash-object` against HEAD for all 183 tracked protected files (0 mismatches).
  - Syntax and CLI checks: `bash -n` on the shell scripts, and direct `scripts/research.py` exit-code checks.
  - Probes: about a dozen scratchpad-only Python probes, `p_canon` through `p_junction`.

## 2. G01–G16 matrix
Source and test references are in the reviewers' reports. Status is the combined result.

| Gate | Requirement | Status | Basis |
|---|---|---|---|
| G01 | Protected files identical before and after | **PASS** for tests; setup half UNVERIFIED | All 183 tracked protected files match their HEAD blobs. Setup scripts were not run (prohibited). |
| G02 | `+1ms` availability rejected | **PASS** | `asof.py:55-57` |
| G03 | Perp funding vs spot rejected | **PASS** (function level) | The ledger never requires as-of output before DATA_QUALIFIED (F6). |
| G04 | Late revision excluded | **PASS** | An as-of tie is broken silently (F20). |
| G05 | Duplicate registration is idempotent | **PASS** | `ledger.py:440-445` |
| G06 | Stale writer rejected | **PASS** (threads, one host) | There is no multi-process test. |
| G07 | Crash recovery must examine artifacts | **FAIL** (both) | `ledger.py:529-535` accepts COMPLETED on a made-up hash. Run manifests are never reconciled. |
| G08 | Corrupt artifact gives BLOCKED | **PASS** | `adjudicate.py:69,95` |
| G09 | Negative net return under cost stress cannot QUALIFY | **FAIL** (both, different mechanisms) | The preregistration needs no stress gate (H3), and the experiment supplies its own costs and metrics (F2). |
| G10 | Seeded leakage caught, miss rate measured | **FAIL** (integrity) / validator PASS, reviewer half UNVERIFIED (contract) | Miss rate is not measured. The ledger doesn't enforce review outcomes. |
| G11 | CONSUMED_LEGACY never confirmation | **FAIL** (both) | A forged record is accepted (H2/F3). A test window used by an earlier version is reusable as UNTOUCHED (F1). |
| G12 | No trading path | **PASS** for "no path"; scope reporting weak | "submit a market buy for 2 BTC" was allowed, and `order_book_levels` was refused. This is a low-severity regex issue. |
| G13 | UNKNOWN gate never QUALIFIED | **FAIL** at the ledger boundary (both) | The `adjudicate()` path itself passes. |
| G14 | No order book means BLOCKED | **PASS** | Admission rests on caller-supplied booleans (F23), and the function isn't wired into any pipeline. |
| G15 | `scripts/lab test` passes | **BLOCKED** | The literal command fails with "Missing .venv". `common.sh` expects `.venv/bin/python`, but this Windows venv has `Scripts\python.exe`. With the equivalent interpreter, `test_lab` passes 10 of 10 and cloud-setup 8 of 10. The 2 errors are host limits (`bash -n` path mangling, WinError 1314). No regression is attributable to the change. |
| G16 | Final `git diff --check` and scoped diff | **PASS** as worded | Exit 0. Three additive tracked-file diffs and no weakened tests. The change set that would actually be committed is incomplete (H1). |

## 3. Findings

### CRITICAL (integrity reviewer; the contract reviewer ranked the ledger-forgery issue HIGH)
- **C1. Consumed test window reusable as UNTOUCHED (G11).**
  - Evidence: `ledger.py:96-98,197` and `contracts.py:261` count test access per `(hypothesis, version)`, and only a hard-coded legacy window counts as consumed.
  - Probe: version 1 read the test split and was REJECTED. Version 2 froze the same range as UNTOUCHED and got QUALIFIED.
  - Fix: track consumed ranges ledger-wide and refuse UNTOUCHED for any overlap.
- **C2. Cost stress bypassed (G09).**
  - Evidence: `pipeline.py:319-321` and `economics.py:189` take costs and stress multipliers from the experiment's own `trades.json`. `adjudicate.py:83` gates on the experiment's own metrics.
  - Probe: the experiment reported zero cost and a fabricated stress metric, and got QUALIFIED. The true stressed return was −0.00093.
  - Fix: put machine-readable cost and stress fields in the preregistration, and BLOCK any gate metric that wasn't independently recomputed. This also covers `economic_estimate` (M5) and `p_value`.
- **C3. Forged adjudication accepted by the ledger (G11/G13).**
  - Evidence: `ledger.py:255-264` checks only state and that a completed trial exists.
  - Probe: a hand-written QUALIFIED on a CONSUMED_LEGACY trial was appended, `ledger-verify` reported OK, and the state became ADJUDICATED.
  - Fix: on replay, re-derive the gate set, holdout integrity and rule digest from ledger state, and reject any mismatch.
  - The existing test `test_ledger.py:51-53` relies on this hole.

### HIGH
- **H1. `research/data/` is gitignored.**
  - `.gitignore:1` has `data/`, and both reviewers confirmed it with `git check-ignore`. A normal commit drops the package.
  - A clean CI checkout would then hit ImportError in four test files. I infer this from the ignore rule and did not observe it in CI.
- **H2. Repeated holdout peeking still QUALIFIES (F4).** The multiplicity adjustment applies only if the experiment reports `p_value` and a gate references it. With three trials all reading the test split, the best one QUALIFIED.
- **H3. Test reads can go uncounted (F5).** The experiment reads the split through `ctx._datasets` (`dispatch.py:56-68`) with `test_access_count=0`. A gate-dropping amendment was then accepted, and the result was QUALIFIED. This also covers the contract reviewer's M2: there is no permission-limited launch, and the protected set omits `lab.py`, `run.py` and `research/`.
- **H4. Self-attested data certificate and review (F6).** `{"status":"QUALIFIED"}` was enough for the data gate. The ledger accepted DATA_QUALIFIED and REVIEW_RECORDED with the free-text evidence "i-say-so".
- **H5. Multiplicity family can be escaped (F7).** Version 2 may declare a new `family_id`, and `re.search` with `$` lets `"id\n"` register as a new hypothesis.

### MEDIUM
- **M1/F11.** The ledger records a false COMPLETED through reconciliation (see G07).
- **F9.** Purge and embargo are free text. Zero-gap splits are accepted, and only strict overlap is rejected.
- **F10.** A run can be left half-complete with no recovery path. `hash_tree` includes `.pyc` files, and a mid-run lazy import raises RUN_ID_REUSE after the trial is already COMPLETED.
- **F12.** An NTFS junction at `work/` sends the ledger outside the repo, and `isolation.py:201-203` creates directories through the link before refusing. Symlink tests were skipped on this host.
- **F13, F14, F15.** Trailing-newline patterns are accepted. Duplicate JSON keys resolve last-wins. Observations available before their own `event_at`, and test ranges in 2030–31, pass validation.
- **M3.** There is no Phase 0 baseline record.
- **M4.** The legacy-equivalence test rebuilds the frame inline and never calls the shipped `legacy_adapter`. Its fixture produces 0 signals, so the signal check is vacuous. The reviewer did confirm that `hourly_frame` equals `download.load` on that fixture, and pandas 2.2.3 is installed.
- **M6.** Missing mandatory evidence gives INVESTIGATE, but blueprint §8 says BLOCKED. The test accepts either, so it can't tell them apart.

### LOW
- The CLI exits 1 on a root escape, outside its documented codes 0/2/3/4.
- The scope-filter regex has both false negatives and false positives.
- The vertical slice never records REPORTED.
- `adjudication_code_digest` covers only `adjudicate.py`, and it depends on line endings (`core.autocrlf=true`).
- Orphan run directories.
- A legacy adapter timezone shift.
- A synthetic QUALIFIED carries no synthetic marker.
- The tail-reconciliation window.
- `microstructure_admission` trusts caller booleans.
- Leaked temp dirs.

## 4. Reviewer disagreements, preserved
- **G10:** The contract reviewer rates the validator half PASS and the reviewer half UNVERIFIED, since reviewer agents arrive in Phase 6. The integrity reviewer rates it FAIL, because the ledger doesn't enforce review outcomes, the experiment can read the test split uncounted, and no miss rate is measured.
- **Severity of the ledger-forgery issue:** HIGH (contract) versus CRITICAL (integrity).
- **G12:** The contract reviewer reproduced both missed order phrasings and over-blocking. The integrity reviewer rated it PASS on the keyword-filter basis. Both agree there is no trading path.
- **Overlap:** The integrity reviewer's F8 and the contract reviewer's H1 are the same gitignore defect, found independently.

## 5. Required corrections versus optional
- **Required before P0 acceptance:** C1–C3, H1–H5, M1/F11, and a Phase 0 baseline record (M3). Fix G09 and G07 as part of these.
- **Required verification:**
  - A literal `scripts/lab test` run on a Linux or Cloud host (G15).
  - An observed GitHub Actions run of the new CI step, once H1 is fixed. No local approximation substitutes for it.
  - Symlink-escape tests on a host with symlink privilege.
  - A clean-checkout test run after H1.
- **Optional:** the LOW items, M4 and M6 (the blueprint decision), and the F16–F23 hardening.

## 6. Verification results

| Check | Result |
|---|---|
| Research suite, 144 tests | passed, 2 skipped |
| Literal `scripts/lab test` | blocked (host venv layout) |
| Equivalent `scripts/lab test` run | partial: 2 host-limit errors, no attributable regression |
| `scripts/lab research` via the wrapper | blocked (same). Direct `scripts/research.py` runs: usage errors exit 2, `ledger-verify` and `status` exit 0, root escape exits 1 |
| pandas legacy adapter equivalence | passed, weak evidence (M4) |
| CI step | not run (no GitHub Actions run observed) |
| `git diff --check` | passed |

## 7. Residual risks
- Multi-process lock contention is unverified.
- Linux line-ending and digest parity are unverified.
- G10 miss-rate measurement is not implemented.
- The ledger detects tampering but does not prevent it.
- Both reviewers read the same repository, so shared blind spots remain possible.

## 8. Final recommendation
**No unconditional P0 acceptance.** Three CRITICAL findings and several failing mandatory gates (G07, G09, G11, G13, plus G10 per the integrity reviewer) remain unresolved. G15 is blocked. Phase 6 should not start.

I've stopped for your adjudication. I haven't saved this report to `reports/codex-strategy-lab/`, so tell me if you want it written there.

---

## Section 2 — Raw reviewer report: goal-contract-reviewer

VERDICT: BLOCKED

Phases 0-5 should not be accepted yet. Four gates fail with reproduced evidence (G07, G09, G11, G13). Separately, the whole `research/data/` package is gitignored, so a normal commit would leave it out and break the new CI step. G15 could not be run in its literal form on this host. I changed nothing in the repository; the before and after fingerprints are identical.

**Tool permissions.** I had Read, Grep, Glob and Bash. Bash was not technically sandboxed: staying read-only was my own discipline, not an enforced limit. My only writes were to the session scratchpad (`C:\Users\click\AppData\Local\Temp\claude\b3e3c631186fa8ab\28e5305c-fb3c-4e21-bcc4-b13414f147b8\scratchpad\`): one probe script and temp dirs, with tests' TEMP/TMP pointed there. I made no git writes, installed nothing, used no network and ran no setup scripts. After my first few calls, every git command used `GIT_OPTIONAL_LOCKS=0`. The earliest `git status` calls ran without it and may have refreshed `.git/index` stat data (no content change).

## 1. Baseline and workspace state

| Fingerprint | Before | After |
|---|---|---|
| HEAD / branch | `09fdca655193452966740d2236c4a5d5aebdd4e5` / main | same |
| `git status --porcelain=v1 -uall` sha256 | `b94f8842…3b2622` | identical |
| `git diff` sha256 | `e6b7491a…62c574` | identical |
| Protected tree raw sha256 (REPORT.md, PREREGISTRATION.md, STAGE_01_HANDOFF.json, results/) | `74d49e52…3df6fc` | identical |
| New/modified files, including ignored `research/data/*.py` | `784ad062…68b154` | identical |
| `*.pyc` outside `.venv` (50 files, created before my audit) | `19e4a2e8…9908e6` | identical |
| `.venv` file count | 8447 | 8447 |
| `work/`, `data/`, `.cache/` | absent | absent |

## 2. What I examined and ran

**Read in full:** the blueprint (all sections), `AGENTS.md` and its diff, `scripts/lab`, `scripts/common.sh`, the workflow diff, `.gitignore`, `.python-version`, `.venv/pyvenv.cfg`. Every file under `research/` (schemas, contracts, ledger, lifecycle, asof, data/, experiments/, validation/, reporting/), plus `scripts/research.py`, all of `tests/research/*`, `docs/control-plane/*`, `download.py`, `test_lab.py` and `tests/test_cloud_setup.py`. Top-level statements of `lab.py`, `scripts/doctor.py` and `scripts/prefetch.py`, checked for import-time side effects.

**Commands run** (Python runs used `PYTHONDONTWRITEBYTECODE=1` with `-B`, and TEMP pointed at the scratchpad):
- `git rev-parse HEAD`, `git status --porcelain=v1 -uall [--ignored]`, `git diff`, `git diff --stat`, `git diff --check` (exit 0), `git check-ignore -v research/data/*.py`, `git ls-files --eol`.
- `git hash-object` vs `git rev-parse HEAD:&lt;f&gt;` for all 183 tracked protected files: 0 mismatches.
- `bash scripts/lab test` → exit 1. `bash scripts/lab research status` → exit 1. `bash scripts/lab help` → exit 0.
- `.venv/Scripts/python.exe -B -m unittest -v test_lab tests.test_cloud_setup` (the equivalent of `scripts/lab test`).
- `.venv/Scripts/python.exe -B -m unittest discover -s tests/research -t . -v` → 144 tests, OK, 2 skipped.
- `bash -n` on `scripts/lab`, the HEAD version of `scripts/lab`, `common.sh`, `reproduce.sh` and the three `.codex/*.sh` scripts.
- `scripts/research.py` exit-code checks: `ledger-verify`, `status`, no arguments, unknown subcommand, `--root ../outside`, missing actor.
- My probe script `scratchpad\probe\probe.py`, which only uses scratch dirs.

## 3. G01–G16 acceptance matrix

| Gate | Requirement | Code and tests | What I ran | Status |
|---|---|---|---|---|
| G01 | REPORT.md and tracked results/ identical before and after setup/tests | `isolation.py:16,29-34`; `test_isolation::test_successful_run…`, `test_vertical_slice::test_valid…` (temp repos only) | All 183 tracked protected files equal their HEAD blobs; the raw fingerprint did not change across my test runs | **PASS** for tests. Setup was not run (prohibited). There is no Phase 0 baseline record (see M3). |
| G02 | `available_at = decision_at + 1ms` rejected before simulation | `asof.py:55-57`; `test_asof::test_available_one_millisecond_after_decision_is_rejected` (+1 ms rejected; equal time and latency budget also covered) | Suite passed | **PASS** |
| G03 | Perp funding mixed up with spot quotes is rejected | `asof.py:44-51`; `test_perp_funding_cannot_stand_in_for_spot_quote` asserts instrument, type and unit mismatch codes | Passed | **PASS** |
| G04 | A revision available after the decision is excluded | `asof.py:76-99`; `test_revised_headline_after_decision_is_excluded` | Passed | **PASS** |
| G05 | Duplicate registration: same ID, one event | `ledger.py:440-445,548`; `test_duplicate_registration_one_event`, and CLI `created=False` | Passed | **PASS** |
| G06 | Concurrent stale update: one wins, stale writer fails, no data loss | `ledger.py:384-396,446-447,166-167`; `test_stale_writer_rejected_without_data_loss`, 12-thread test, held-lock test | Passed. Only threads are tested, not multiple processes. | **PASS** |
| G07 | Crash between output and ledger append: recover by examining actual artifacts, no false completion | `ledger.py:518-541` accepts `COMPLETED` when the caller supplies any `artifact_manifest_hash`; it never reads the disk | Probe: a fabricated hash `f*64` with no artifacts → trial `COMPLETED`, then `EXPERIMENT_COMPLETE` was accepted. The repo's own `test_completion_with_evidence_is_accepted` (`test_ledger.py:318-322`) builds this in. | **FAIL** (the default INTERRUPTED path is correct) |
| G08 | Corrupted trial artifact hash → BLOCKED | `adjudicate.py:69,95`; `test_corrupted_or_missing_artifact_blocks` (changed, deleted and extra artifact) | Passed | **PASS** |
| G09 | Positive Sharpe but negative net return under cost stress cannot be QUALIFIED | `adjudicate.py:78-104` only gates on preregistered metrics; the prereg schema does not require a cost-stress gate | Probe: prereg without a stress gate, stress_x2 = −0.0005 → **QUALIFIED**. The repo test passes only because its fixture includes `g-net-stress`. | **FAIL** |
| G10 | Seeded leakage: reviewer and validator catch or block it; miss rate measured | `timing.py:27-42`, `adversarial.py`; `test_seeded_future_feature_is_caught`, `test_fabricated_future_data_is_caught…` | Passed | Validator half **PASS**. Reviewer catch and miss-rate measurement **UNVERIFIED** (reviewer agents arrive in Phase 6). The audit only sees self-declared feature timestamps. |
| G11 | `CONSUMED_LEGACY` can never become an untouched confirmation | `contracts.py:245-264`; `adjudicate.py:93-94,114`; `test_consumed_legacy_window_never_qualifies` and the contract test | Probe: a forged `ADJUDICATION_RECORDED` (QUALIFIED, `holdout_integrity=UNTOUCHED`, made-up gate, placeholder digests) on a CONSUMED_LEGACY hypothesis was accepted by `ledger.append`; `ledger-verify` reports OK and the state reaches REPORTED | **FAIL** at the ledger layer; the adjudicator path passes |
| G12 | Order or credential request: no trading path, unsupported scope reported | No exchange/client code (`test_no_trading_or_credential_code…` static scan); `dispatch.py:24-50` regex | Probe: "submit a market buy for 2 BTC" and "execute the trade on Binance now" were allowed; `order_book_levels` and `accounting_basis` were refused | **PASS** for "no trading path". Scope reporting **FAIL** on the reproduced phrasings (low severity, because there is no path to misuse). |
| G13 | Agents agree but a required gate is UNKNOWN: never QUALIFIED | `adjudicate.py:99`; `contracts.py:312-319`; G13 tests | Same forgery probe as G11: a fabricated PASS gate with proof "trust me" was accepted | **FAIL** at the ledger layer; the adjudicator path passes |
| G14 | No real order-book dataset: microstructure BLOCKED, no OHLCV fabrication | `qualification.py:45-57`; `test_microstructure_blocked_without_order_book` | Passed. The function is not wired into any pipeline. | **PASS** |
| G15 | Existing `scripts/lab test` passes after each P0 phase, or the regression is reported precisely | `scripts/lab:26` unchanged | Literal command → exit 1 "Missing .venv": `common.sh:4` expects `.venv/bin/python`, but this Windows venv has `Scripts\python.exe`. With the equivalent interpreter: all 10 `test_lab` engine tests pass, and 8 of 10 cloud-setup tests pass. The two that do not, shell-parse (7 subtests) and the 2 reproduction tests, error on host limits: Windows backslash-path mangling in `bash -n` (also hits the unchanged `start.sh`) and WinError 1314 (symlink privilege). `bash -n scripts/lab` passes when run directly. | **BLOCKED** (literal command cannot run here; no regression attributable to the change) |
| G16 | Final `git diff --check` and scoped diff review: no unrelated change, no weakened tests | Diff touches only 3 tracked files, all additive; `test_lab.py` and `test_cloud_setup.py` unchanged | `git diff --check` exit 0; no trailing whitespace in new files | **PASS** as worded. The change set that would actually be committed is incomplete (H1). |

**Phase-level points not covered by a G gate:**
- Phase 0: there is no durable baseline record (protected-file hashes, CLI inventory) in the plane or under `reports/`. **UNVERIFIED.**
- Phase 1: schema versions are checked and unknown versions rejected, but no migration path exists. That limit is documented; low risk.
- Phase 3: the shipped `research/experiments/legacy_adapter.py` is never exercised by any test (M4).
- Phase 4: "permission-limited launch" is not implemented (M2).

## 4. Findings, ranked

**HIGH**

- **H1 — The whole `research/data/` package is gitignored. Demonstrated defect.** `.gitignore:1` has `data/`, which matches `research/data/` (`git check-ignore -v` confirms all four files). A normal commit leaves the package out, so on a fresh CI checkout `tests/research/{slice,vertical,test_asof,test_legacy_compat}.py` would fail with ImportError. `AGENTS.md:70` and `docs/control-plane/dataset-admission.md:3` would then point at a file that is not in the repo. Inferred from the ignore rule; not observed in GitHub Actions.
- **H2 — The ledger accepts any schema-valid adjudication, so a manual QUALIFIED goes through. Demonstrated defect.** The `ADJUDICATION_RECORDED` rule at `research/ledger.py:255-264` only checks the hypothesis state and that a completed trial exists. It does not bind the record to the preregistered rules, gate IDs, the trial's holdout class or test access, or the adjudicator's code digest. My probe recorded a forged QUALIFIED on a CONSUMED_LEGACY hypothesis and `ledger-verify` still reports OK. `tests/research/test_ledger.py:51-53` already relies on this: it records a hand-built QUALIFIED with placeholder digests and no test access. This defeats invariant 6, the §5.6 ban on manual override, G11 and G13. The rule "dispositions only from adjudicate.py" exists only as AGENTS.md text, which nothing enforces.
- **H3 — Cost stress only blocks QUALIFIED if the preregistration happens to include a stress gate. Demonstrated defect.** `adjudicate.py:78-104` evaluates only preregistered gates, and `preregistration.schema.json` (`gate_rules`) does not require a cost-stress gate. Probe result: QUALIFIED with a negative net return under stress. This contradicts G09 and §8 ("net alpha must beat benchmark after these costs").

**MEDIUM**

- **M1 — G07 accepts a completion it never checked. Demonstrated defect.** `ledger.py:529-535` takes `COMPLETED` on a caller-asserted hash without examining any artifacts. Adjudication would later BLOCK on missing artifacts, but the ledger already records a false completion.
- **M2 — There is no permission-limited launch. Plausible vulnerability, by inspection.** `dispatch.py:120` runs the experiment in-process with full rights. The protected set (`isolation.py:16`) covers only REPORT.md, PREREGISTRATION.md, STAGE_01_HANDOFF.json and results/, so changes to `lab.py`, `run.py` or `research/` go undetected. That contradicts the docstring claim at `dispatch.py:14` that it never changes `lab.py` or `run.py`.
- **M3 — Phase 0 baseline is missing. Missing evidence.** No record of protected-file SHA-256s or the existing CLI and reproduction commands was found.
- **M4 — The legacy-equivalence evidence is weak. Missing evidence.** `test_legacy_compat.py:99-119` rebuilds the frame inline instead of calling `legacy_adapter.hourly_frame`/`signal_plans`. Its fixture produces 0 signals for all three strategies (probe), so the signal-equivalence check is vacuous for the signal column. My probe did confirm `hourly_frame` equals `download.load` on that fixture.
- **M5 — `economic_estimate` is whatever the experiment reports. Demonstrated defect.** `adjudicate.py:92` takes it from the experiment's metrics and never recomputes it. A reported 999.0 was accepted with decision QUALIFIED.
- **M6 — Missing mandatory evidence gives INVESTIGATE, while blueprint §8 says BLOCKED. Contract divergence.** Implemented at `adjudicate.py:99`. The test at `test_vertical_slice.py:56` accepts either value, so it cannot tell the two apart.

**LOW**

- The CLI exits 1 on a root escape (`scripts/research.py:29`, `SystemExit(str)`); its own documented codes are 0/2/3/4.
- The scope-filter regex (`dispatch.py:24-26`) both misses order phrasings and blocks legitimate keys such as `order_book_levels` (G12b).
- The vertical slice never records REPORTED or the report hash in the ledger (`tests/research/vertical.py:175-186`).
- Tests create temp dirs with `mkdtemp` and never clean them up (outside the repo).
- The host can't run `scripts/lab` because `common.sh` expects a Linux-style `.venv/bin/python`. This predates the change.

## 5. Smallest correction or discriminating test for each

- **H1:** Root-anchor the ignore pattern (`/data/`) or add `!research/data/`. Either changes a tracked file outside the blueprint's MODIFY list, and so does renaming the package, so the user should choose. Test: `git check-ignore research/data/legacy_ohlcv.py` must return non-zero, and the suite must pass in a clean clone of the commit.
- **H2:** In the ledger's adjudication rule, require:
  - `decision_rule_digest == rule_digest(current prereg)`;
  - gate IDs equal to the system gates plus the preregistered gates;
  - QUALIFIED only when the prereg holdout is UNTOUCHED and the cited trial has `test_access_count ≥ 1` and the same holdout class;
  - `adjudication_code_digest` from an approved set.

  Re-running `adjudicate()` during replay is the alternative. Test: my forged-record probe must be rejected and the existing `test_ledger.py:51-53` fixture must fail.
- **H3:** Add a contract check that refuses a preregistration without a mandatory cost-stress gate, or add a system gate driven by the recomputed stress series. Test: probe 1 must not return QUALIFIED.
- **M1:** Verify `isolation.verify_artifacts` on the run directory before accepting `COMPLETED` in reconcile. Test: probe 3 must be rejected.
- **M2:** Add tracked source to the after-run check (e.g. compare `git diff`), or document in-process execution as a limitation. Test: an experiment that writes to `lab.py` in the bench must end FAILED.
- **M3:** Record the baseline hashes and command inventory in a Phase 0 document, after user authorization.
- **M4:** Call the shipped `legacy_adapter` functions in the test and assert that the fixture produces at least one signal.
- **M5:** Derive `economic_estimate` from the recomputed metrics. Test: probe 1b.
- **M6:** Decide INVESTIGATE vs BLOCKED against §8, then assert one exact value in the test.
- **LOW items:** fix the documented exit code, refine the scope filter, and add the REPORTED transition with the report hash.

## 6. Integration checks

| Check | Result |
|---|---|
| `scripts/lab research` dispatch | Help text and dispatch line present and parse with `bash -n`. Running the literal command is BLOCKED on this host (same `.venv/bin/python` problem). Running `scripts/research.py` directly works: `ledger-verify`/`status` exit 0 and create no `work/`; usage errors exit 2; root escape exits 1. |
| Existing `scripts/lab test` | Literal command BLOCKED; equivalent run as described under G15, no regression attributed. |
| pandas legacy-adapter equivalence | pandas 2.2.3 and numpy 2.3.5 are present in `.venv`. The test ran and passed, with the M4 caveat. |
| New CI step (`cloud-readiness.yml:28-29`) | Prerequisites (setup.sh, py3.12, `tests/__init__.py`, `-t .`) are plausible. I did not observe a GitHub Actions run and do not claim CI passes. Because of H1, the step would fail if `research/data/` is committed the normal way. |
| Research suite | 144 tests run, OK, 2 skipped (symlink privilege); workspace unchanged afterwards. |

## 7. Residual risks and scope creep

- No Phase 6+ work was pulled forward: no `.codex/agents`, no Skills, no real data adapters. No trading, credential or network code was found (static scan).
- The ledger detects tampering but does not prevent it, as its docs say. H2 is a separate issue: the sanctioned write API itself lets an invalid disposition through.
- Symlink-escape tests were skipped on this host, so those protections are unverified here.
- I did not rerun the setup, maintenance or start scripts, so G01's "before/after setup" half is unverified.

**Advance decision:** the parent may **not** move on to Phase 6. Minimum fixes first: H1, H2, H3 and M1. After that, G15 needs a literal `scripts/lab test` run on a Linux/Cloud host, and the new CI step needs an observed CI run before Phases 0-5 can be re-reviewed.

---

## Section 3 — Raw reviewer report: experiment-integrity-reviewer

**VERDICT: FAIL**

The test suite passes (144 tests, 2 skipped), but probes I ran show several ways an experiment can reach a recorded QUALIFIED decision it should not get. These include reusing a test window that was already used, running cost stress against costs the experiment chose itself, forging an adjudication, and a data certificate the caller can simply assert. The tests don't exercise these paths.

## 1. Baseline and workspace state
- **Target:** `C:\TEST-repos\codex-control-plane-expert\src\codex-strategy-lab`. HEAD is `09fdca655193452966740d2236c4a5d5aebdd4e5`. Phases 0-5 are uncommitted: 3 files modified, 53 untracked.
- **Before:** `git status --porcelain=v1 -uall` showed 56 entries (3 ` M`, 53 `??`). Neither `work/` nor `data/` existed.
- **After:** the same 56 entries, and still no `work/` or `data/`. Nothing in the repo is newer than my first test run except the `.git` directory's own timestamp (22:35), which is most likely `git status` refreshing its index. No tracked file and no untracked set changed.
- **Not shown by `git status`:** `research/data/` (`__init__.py`, `types.py`, `legacy_ohlcv.py`, `qualification.py`) is matched by `.gitignore:1 data/`, so it does not appear in the untracked list. This is finding F8.
- **My actual permissions:** Read, Grep, Glob and an unsandboxed Bash. Read-only behaviour was enforced only by my own discipline. All writes went to the scratchpad `C:\Users\click\AppData\Local\Temp\claude\b3e3c631186fa8ab\28e5305c-fb3c-4e21-bcc4-b13414f147b8\scratchpad`: probe scripts in `probes\`, temp ledgers and benches in `t1`–`t3`, and two NTFS junctions in `jx`/`jx2`. No git writes, installs, network use or credentials.

## 2. What I examined and ran
- **Read in full:** the blueprint; `AGENTS.md` (and its diff); all of `docs/control-plane/*`; `research/{identifiers,contracts,ledger,lifecycle,prereg,provenance,asof}.py`; `research/data/*`; `research/experiments/*`; `research/validation/*`; `research/reporting/*`; all 9 schemas; `scripts/research.py`; `tests/research/{builders,flow,slice,vertical,archives}.py`, `test_adjudication.py`, `test_vertical_slice.py`, `test_legacy_compat.py`; the relevant parts of `test_ledger.py`, `test_cli.py` and `test_isolation.py`. Also checked `download.py` and `lab.py` for import-time side effects.
- **Commands:**
  - The suite: `.venv/Scripts/python.exe -I -B -m unittest discover -s tests/research -t .`, with `TMP`/`TEMP`/`TMPDIR` pointed at the scratchpad and `PYTHONDONTWRITEBYTECODE=1`. Result: **144 tests OK, 2 skipped** — both symlink tests (`test_cli.py:76`, `test_isolation.py:53`), because this host lacks the symlink privilege.
  - Probes `p_canon`, `p_ledger`, `p_run`, `p_amend`, `p_time`, `p_cli`, `p_junction`, `p_pyc`, `p_regex`, run with `-I -B` from the scratchpad.
  - Read-only checks: `git check-ignore -v`, `git status --ignored`, `git config core.autocrlf` (`true`), and a CR byte count.

## 3. Gate results in my scope

| Gate | Where it's enforced | Tests | Evidence I ran | Status / missing evidence |
|---|---|---|---|---|
| G02 | `asof.py:admissibility:55-57` | `test_asof:33` | suite | **PASS** |
| G03 | `asof.py:44-51` | `test_asof:51` | suite | **PASS** at the function level. The ledger never requires as-of output before DATA_QUALIFIED (see F6). |
| G04 | `asof.py:select_as_of:76-99` | `test_asof:77,84` | suite, P16 | **PASS**, but a tie between equally available revisions is broken silently (F20). |
| G05 | `ledger.py:append:440-445` | `test_ledger:78`, `test_cli:41` | suite | **PASS** |
| G06 | `ledger.py:446-447,166-167` | `test_ledger:92,103,115` | suite | **PASS** on one host with threads. There is no multi-process test. |
| G07 | `ledger.py:reconcile_interrupted_trials:518-541` | `test_ledger:304`, `test_isolation:115` | P10, P11b | **FAIL**. The code never examines artifacts. An asserted COMPLETED with a made-up hash is accepted, and run manifests are never reconciled. |
| G08 | `isolation.py:verify_artifacts:241-256` | `test_adjudication:213` | suite | **PASS** |
| G09 | `pipeline.py:319-321`, `economics.py:compare_metrics:186-196` | `test_adjudication:171,223` | P8 | **FAIL**. Recorded QUALIFIED while the true net return under 2x cost stress was −0.00093. |
| G10 | `timing.py:leakage_audit`, `adversarial.py:review_outcome` | `test_vertical_slice:37` | P-cli, P7 | **FAIL**. The ledger doesn't enforce the review outcome (`ledger.py:174`), the experiment can read the test split without it being counted, and the miss rate is never measured. |
| G11 | `contracts.py:261`, `adjudicate.py:93-94` | `test_contracts:101`, `test_adjudication:184` | P5, P6, P3 | **FAIL**. Only the hard-coded legacy window is treated as consumed. A window used by an earlier version was accepted as UNTOUCHED and the result QUALIFIED. |
| G12 | `dispatch.py:check_scope` | `test_vertical_slice:110`, `test_isolation:89` | suite | **PASS**. The check is a keyword filter. |
| G13 | `adjudicate.py:99`, `contracts.py:312-315` | `test_adjudication:199,207` | P3 | **FAIL** at the ledger boundary: a forged QUALIFIED record that simply omits the UNKNOWN gate is accepted. Only the `adjudicate()` path itself passes. |
| G14 | `qualification.py:microstructure_admission` | `test_asof:106` | suite | **PASS**. Admission rests on booleans the caller supplies (F23). |
| G01 (preservation) | `isolation.py:protected_*` | `test_vertical_slice:16` | `git status` | **PASS**: no protected tracked file changed. |

## 4. Findings

### CRITICAL
- **F1 — An already-used test window can be reused as UNTOUCHED and QUALIFY (G11). Demonstrated.**
  - Cause: `ledger.py:View.test_access:96-98` and the `AMENDMENT_AFTER_EXPOSURE` check at `:197` count test access per `(hypothesis_id, version)` only. `contracts.py:_split_issues:261` treats only the hard-coded legacy window as consumed. `adjudicate.py:93-94` trusts the trial's own `holdout_class`.
  - P5: version 1 read the test split (`test_access_count=1`) and was REJECTED. Version 2 then froze the same test range as UNTOUCHED and got `('QUALIFIED','UNTOUCHED', recorded=True)`.
  - Smallest fix: track consumed test ranges across the whole ledger (every version and family), and refuse UNTOUCHED for any overlapping range. Test: re-run P5 and expect a contract or ledger rejection, or PROMISING_UNVALIDATED.
- **F2 — Cost stress can be bypassed: the experiment supplies its own costs and unrecomputed metrics (G09). Demonstrated.**
  - Cause: `pipeline.py:adjudicate_trial:319-321` takes `cost_per_trade` and `stress_multipliers` from the experiment-written `trades.json`, not from the preregistration (whose `cost_capacity_assumptions` is free text). `economics.py:compare_metrics:189` compares only metrics present in both sets. `adjudicate.py:83` then gates on the experiment-reported values.
  - P8: the experiment reported cost 0, no stress multipliers, and a fabricated `mean_net_return_stress_x2=0.0123`. Result: decision QUALIFIED, `g-net-stress` PASS, `sys-independent-recompute` PASS. The true value at the preregistered cost was −0.00093.
  - Smallest fix: make cost and stress parameters machine-readable preregistration fields, and BLOCK any gate metric that wasn't independently recomputed (including `economic_estimate` and `p_value`). Test: P8 should end BLOCKED or REJECT.
- **F3 — The ledger accepts a forged adjudication. Demonstrated.**
  - Cause: `ledger.py:apply_event:255-264` checks only the state, the subject, and that a COMPLETED trial exists. `contracts.py:312-319` checks the record only against itself. Nothing ties the record to the preregistration's gates, the trial's `holdout_class`, `rule_digest`, or a recomputed decision.
  - P3: a hand-written QUALIFIED record (one made-up gate, `holdout_integrity=UNTOUCHED`) for a CONSUMED_LEGACY trial whose real decision was REJECT was appended. The ledger then verified as `OK` and the state became ADJUDICATED.
  - This contradicts `AGENTS.md:67` and the architecture doc ("Dispositions come only from adjudicate.py") and the ledger policy ("Replay = rules").
  - Smallest fix: during replay, re-derive the gate set, `holdout_integrity` and `decision_rule_digest` from ledger state, and reject any mismatch. Test: P3 should be rejected with a specific error code.

### HIGH
- **F4 — Peeking at the holdout repeatedly and picking the best trial still QUALIFIES. Demonstrated.**
  - Cause: `adjudicate.py:61-62` applies a multiplicity adjustment only when the experiment reports a `p_value` *and* a gate references `p_value_adjusted`. `COUNT_ONLY` (`multiple_testing.py:149`) adjusts nothing. `confirmed` at `:93` looks only at the selected trial's access count.
  - P6: three trials each read the test split; adjudicating the best one gave `('QUALIFIED','UNTOUCHED')`.
  - Fix or test: when the family's total test access is above 1, or more than one trial accessed the test split, cap the decision at PROMISING_UNVALIDATED, or require a gate whose metric the multiplicity method actually adjusts.
- **F5 — Test-split reads can go uncounted, which then unlocks preregistration amendments. Demonstrated.**
  - Cause: `dispatch.py:RunContext:56-68` exposes `ctx._datasets`.
  - P7: the experiment read the test split through `ctx._datasets` and recorded `test_access_count=0`. An amendment dropping the failing stress gate was then ACCEPTED, and the final result was QUALIFIED. The control run with a counted read was rejected with `AMENDMENT_AFTER_EXPOSURE`.
  - The architecture doc says experiment code does not own test-set exposure. This shows it does.
  - Fix: run the experiment out of process, or hand it a proxy that holds no reference to the test loader. Test: P7.
- **F6 — Data qualification and review are self-attested. Demonstrated.**
  - Cause: the adjudicator's data gate (`adjudicate.py:72`) only checks `data_certificate.get("status")=="QUALIFIED"`; the certificate is supplied by the caller at `pipeline.py:303` and is never checked against the run's `dataset_manifest_digests`. Separately, the ledger accepts DATA_QUALIFIED and REVIEW_RECORDED with any free-text evidence (`ledger.py:174`).
  - P9: passing `{"status":"QUALIFIED"}` gave a QUALIFIED decision with `data_limitations=['dataset_manifest:None']`.
  - P-cli: `advance` reached DATA_QUALIFIED and REVIEW_RECORDED with evidence strings `"i-say-so"` and `"objections-ignored"`.
  - Fix or test: record the certificate and the objection outcomes as ledger events, and require their digests on these transitions.
- **F7 — Multiplicity family can be escaped. Demonstrated.**
  - Cause: `ledger.py:138-150` lets version 2 of a hypothesis declare a new `family_id` (P4: ACCEPTED). The schema patterns use `re.search` with `$`, which matches before a trailing newline (`contracts.py:174`), so a look-alike ID `"hyp-synthetic-001\n"` registered as a new version 1 in a new family (P-regex).
  - Fix: make `family_id` immutable across versions, and use `re.fullmatch` or `\Z`.
- **F8 — The point-in-time modules are gitignored, so they can't be committed or reproduced. Demonstrated.**
  - Cause: `.gitignore:1 data/` matches all four `research/data/*.py` files.
  - Effect: committing Phases 0-5 would silently leave them out. A fresh CI checkout would then fail at import (`tests/research/test_asof.py:6`, `slice.py:6`, `test_legacy_compat.py:8-9`). `source_digests` in run manifests would include files that aren't at `git_head_oid`.
  - Fix: add a negation rule (`!research/data/`) or rename the directory, then confirm with `git check-ignore`.

### MEDIUM
- **F9 — Purge and embargo are not enforced. Demonstrated.**
  - The preregistration's `embargo_purge` is free text. Zero-gap train/validation/test splits are accepted (P15), and `contracts.py:257` only rejects ranges that strictly overlap.
  - `timing.label_overlap_issues` runs only if a reviewer files an objection, and it never checks the validation→test boundary.
  - Fix: add machine-readable horizon and embargo fields, and check every boundary when freezing.
- **F10 — A run can end half-completed with no recovery path. Demonstrated.**
  - Cause: `provenance.hash_tree` includes 26 `__pycache__/*.pyc` entries (P11), and `source_digests` cannot change once recorded (`ledger.py:36`).
  - P11b: a file appearing under `research/` mid-run (as a lazy import's `.pyc` would) raised `RUN_ID_REUSE` after the trial was already recorded COMPLETED. The run stayed STARTED, adjudication was BLOCKED, and no run-reconciliation path exists (`ledger.py:518-541` handles trials only). A crash between `dispatch.py:136` and `:138` would leave the same state.
- **F11 — Reconciliation accepts a COMPLETED status with an unverified hash. Demonstrated.**
  - Cause: `ledger.py:529-535`.
  - P10: an asserted hash of `"e"*64` produced a COMPLETED trial and EXPERIMENT_COMPLETE was accepted. Adjudication was BLOCKED, which contains the damage, but the ledger still holds a false completion. This contradicts the alpha-ledger-policy doc.
- **F12 — Output roots can escape the repo through a link. Demonstrated with an NTFS junction.**
  - `scripts/research.py:resolve_root:22-30` resolves `work/` itself, so a linked `work/` sends the ledger outside the repo (P-junction).
  - `isolation.py:201-203` runs `mkdir` through the link before refusing with ESCAPE, which created `research-runs/` outside the repo (jx2).
  - The symlink tests skip on this host and only cover a link *under* `work/`.
- **F13 — Patterns and run names accept a trailing newline** (`contracts.py:174`, `isolation.py:161`). This diverges from standard JSON Schema `pattern` semantics. Demonstrated for identifiers, sha256 and `code_commit` fields, and for run names.
- **F14 — Duplicate JSON keys are silently resolved last-wins** in `scripts/research.py:load_json:37`. A reader of the file sees `fam-synthetic`; the ledger recorded `fam-SHADOW`. Demonstrated.
- **F15 — Incomplete time-ordering checks. Demonstrated.**
  - An observation available or published 10 minutes before its own `event_at` passes validation (`contracts.py:270-279`; P14).
  - A 2030–31 test range frozen in 2026 passes (P15b), and the "valid" synthetic slice QUALIFIES on it.

### LOW
- **F16** — `adjudication_code_digest` hashes only `adjudicate.py` (`:34-35`), not `economics`, `multiple_testing`, `pipeline` or `contracts`. It also depends on line endings: `core.autocrlf=true`, `lab.py` already has CRLF in the working tree, and `adjudicate.py` is LF while untracked.
- **F17** — Orphan run directories: `dispatch.py:105` creates the directory before the ledger rejects the STARTED event (P12: directory exists, ledger has no record). Trial IDs and run IDs both allow `:`, so the key `"t:r"+"x"` collides with `"t"+"r:x"`; this fails closed.
- **F18** — Integral floats of 2^63 or more are rejected with `INT_RANGE`; a lone surrogate in a dict key raises an uncaught `UnicodeEncodeError` (`identifiers.py:36-37,51-53`). I found no hash collision.
- **F19** — The legacy adapter reads a timestamp without an offset as host-local time (a −0500 shift, P13), and a missing `retrieved_utc` raises `TypeError`. It also stamps the bar close with the bar-open `event_at` (`legacy_ohlcv.py:303,311`). The real sidecars include an offset (`download.py:20` in the job function), so impact is low.
- **F20** — An as-of tie is resolved by lexicographic `revision_id` with no flag (`asof.py:89-91`; P16).
- **F21** — A synthetic-fixture QUALIFIED record in the ledger carries the OHLCV limitations and no synthetic marker. `data_kind` exists only in the report, as a string the caller supplies.
- **F22** — `reconcile_tail` truncates the file, releases the lock, and only then appends the RECONCILIATION event (`ledger.py:505-515`). A crash in that window loses the record of the truncation; the quarantine copy survives.
- **F23** — `microstructure_admission` trusts the caller's `sequence_ok` and `license_reviewed` booleans (`qualification.py:175`).

## 5. Methodological contract map
| Contract | Status | Evidence |
|---|---|---|
| Temporal / look-ahead | AFFECTED (FAIL) | F5, F15, F9 |
| Split / holdout | AFFECTED (FAIL) | F1, F4, F5, F9 |
| Hypothesis / multiplicity | AFFECTED (FAIL) | F4, F7, F2 (`p_value` not recomputed) |
| Feature / label / eligibility | AFFECTED | F6, F9; an UNKNOWN eligibility gate correctly gives INVESTIGATE (`test_vertical_slice:49`) |
| Missingness / UNKNOWN | AFFECTED (mostly PASS) | `adjudicate.py:84-99`, `asof.py:52`; F6 is the self-attested exception |
| Scoring / promotion | AFFECTED (FAIL) | F1–F4, F6 |
| Backtest execution / accounting | AFFECTED (FAIL) | Metrics come from experiment-written `trades.json`, not from a ledger the simulator owns (F2) |
| Determinism / identity | AFFECTED | F8, F10, F13, F14, F16 |
| Offline boundary | UNAFFECTED (PASS) | `test_vertical_slice:119`, `test_legacy_compat:29` |

## 6. Focused validation and residual risk
- **What the suite covers:** contract rejection codes, the transition table, tail and corruption recovery, idempotency, stale-writer rejection, artifact tampering, the hard-coded legacy holdout, and an honestly reported cost-stress failure.
- **What it lacks:** negative tests for adversarial experiment code (F2, F5), forged ledger events (F3), test windows consumed across versions (F1), repeated holdout reads (F4), self-attested certificate or review (F6), family change across versions (F7), and a commit-ability check on `research/data` (F8). Many of the existing tests replay the implementation's own happy path.
- **BROADER GATE: JUSTIFIED.** F8 changes what a fresh checkout and CI see, so a clean-checkout run of `scripts/lab test` plus the research suite should follow the fix. I did not run `scripts/lab test` (G15).

Residual risks:
- **BLOCKED:** symlink escape on a host with symlink privilege. Only the junction variant was exercised.
- **UNVERIFIED:** multi-process lock contention on the real filesystem; Linux line-ending and digest parity; miss-rate measurement for G10, which isn't implemented.
