# Research workbench architecture (PROPOSED project design, not a Codex API)

Scope delivered: blueprint P0 (phases 0-5). It is a testable research workbench around the
frozen Stage 02 laboratory, **not** an operational autonomous research system and not a trading system.
Nothing here grants permissions to Codex, Claude Code or any other agent.

## Layout
```text
research/
  schemas/*.schema.json     authoritative structure (hypothesis, preregistration, observation, trial,
                            adjudication, run_manifest, ledger_event, objection) + common defs
  contracts.py identifiers.py lifecycle.py   validation (JSON Schema SUBSET), canonical hashing, workflow states
  ledger.py prereg.py provenance.py          hash-chained single-writer ledger, prereg freeze, read-only provenance
  asof.py data/                              point-in-time admissibility; side-effect-free legacy OHLCV adapter
  experiments/                               isolation, dispatch (no trading path), pipeline, legacy_adapter
  validation/                                timing, economics, multiple_testing, adversarial, adjudicate
  reporting/                                 evidence index, deterministic Markdown/JSON report
scripts/research.py         CLI (`scripts/lab research ...`)
tests/research/             unit, negative-control and synthetic end-to-end tests
```

## Authority and ownership
| Concern | Owner | Not owned by |
|---|---|---|
| Structure of records | schema files | Python rules (they only enforce / add cross-field checks) |
| Workflow state | ledger + `lifecycle.py` | agents, reports |
| Disposition | `validation/adjudicate.py` from recorded evidence | prose, reviewer opinions, manual override |
| Test-set exposure | counting broker (child process) + global holdout registry derived from the ledger | experiment code; in-process runs are advisory only |
| Protected Stage 02 evidence | hashed before/after every run | any new code path |

## Blueprint gate coverage (what is tested, where)
G01 `test_isolation`, `test_vertical_slice` (protected hashes) | G02-G04 `test_asof` | G05-G07 `test_ledger`,
`test_isolation` | G08-G11, G13 `test_adjudication`, `test_vertical_slice`, `test_contracts` | G12
`test_isolation`, `test_vertical_slice` | G14 `test_asof` | G15 legacy `test_lab` run separately |
G16 final diff review (manual).

## Deferred (not implemented)
Phase 6 native custom agents, Skills, project orchestration configuration and evaluation corpus are authored; see `orchestration.md` and `evaluation-policy.md`. Runtime qualification, additional research CLI integration and automated capability promotion remain deferred. Synthetic orchestration testing does not require a real provider or untouched confirmation set.
Real historical order-book/derivatives/catalyst data (7-8), memory and adaptive models (9), and governance/cost evaluation (10) remain deferred; provider/licence, preregistered thresholds and a genuinely unopened confirmation set remain prerequisites where applicable.

## Known limitations
- Legacy OHLCV has no depth, spread, queue, funding or liquidation data; costs are preregistered assumptions.
- `lab.Market` / `simulate` are not driven (Market writes into `results/`); only the pure `features()` is bridged.
- The ledger is tamper-evident, not tamper-proof; one host, file-based, O(n) replay.
- The schema validator is a documented subset, not full JSON Schema.
- Synthetic tests prove machinery behaviour only; they say nothing about markets.
