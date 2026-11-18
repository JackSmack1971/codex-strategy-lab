# Evidence contracts (PROPOSED project design, not a Codex API)

Status: implemented in `research/` (Phase 1). These contracts constrain **research
records**; they grant no permissions and do not make any research claim true.

## Authority
- Structure lives only in `research/schemas/*.schema.json` (`common.schema.json` holds shared
  definitions, including the workflow-state and disposition enums). Python reads those files;
  it does not repeat structural rules. Cross-field rules a schema cannot express live in
  `research/contracts.py:semantic_issues` and are covered by `tests/research/test_contracts.py`.
- Kinds: hypothesis, preregistration, observation, trial, adjudication, run_manifest
  (objection and ledger-event contracts arrive with the phases that use them).

## Validator scope (not full JSON Schema)
`research/contracts.py` implements a documented **subset**: `type`, `enum`, `const`,
`required`, `properties`, `additionalProperties`, `items`, `minItems`/`maxItems`, `anyOf`,
`$ref` (local or `common.schema.json`), `minLength`/`maxLength`, `pattern`, `minimum`/`maximum`,
and `x-format: utc-timestamp`. Any other keyword in a schema file makes loading fail
(`SchemaError`), so an unsupported constraint cannot be silently ignored. Full JSON Schema
compliance is **not** claimed.

## Semantics
- **Versions:** each record carries `schema_version`; only versions listed by the schema are
  accepted. No migration exists; a future one must preserve the original bytes and lineage.
- **Time:** ISO-8601 UTC with trailing `Z`, up to microseconds. Offsets, naive times and
  impossible dates are rejected.
- **Numbers:** `integer` rejects floats (`1.0`) and booleans; `number` must be finite.
  Canonical hashing normalises integral floats to ints and `-0.0` to `0`; integers beyond
  signed 64 bits are rejected.
- **Unknown vs absent vs null:** optional fields are simply absent. The literal `"UNKNOWN"` is
  accepted only where a schema says so (e.g. `available_at_utc`, `economic_estimate`, Codex
  observation fields). `null` is never accepted. A missing publication time must be stated as
  `{"absent_reason": "..."}`; times are never invented.
- **Hashes:** `identifiers.digest` = SHA-256 of canonical JSON (sorted keys, no whitespace,
  UTF-8). Order of keys and numeric spelling do not change it. `derived_id(namespace, key)` gives
  an immutable ID from an idempotency key.
- **Holdout:** `CONSUMED_LEGACY` is a distinct class. Any test range overlapping the consumed
  Stage 02 window (2025-11-17 to 2026-11-17) cannot be `UNTOUCHED`; `QUALIFIED` requires
  `holdout_integrity = UNTOUCHED`.
- **Dispositions:** `QUALIFIED` requires every mandatory gate `PASS` (never `UNKNOWN`,
  `FAIL` or `NOT_APPLICABLE`), proof references per PASS, and a known economic estimate.
  `QUALIFIED` means research-qualified only.

## Workflow state vs disposition
`research/lifecycle.py` holds legal edges only; state names come from the schema. `BLOCKED`
and `FAILED` are workflow outcomes (terminal for a hypothesis version). A `FAILED` run is not a
`REJECT`; dispositions are set only by adjudication.

## Limits
Valid records are well-formed, not true. Passing validation proves nothing about data
quality, profitability or the absence of leakage.
