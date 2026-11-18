# Dataset admission and point-in-time rules (PROPOSED project design)

Implemented in `research/asof.py`, `research/data/{types,legacy_ohlcv,qualification}.py`.

## Legacy OHLCV adapter boundary
`OhlcvSource` reads `<data_root>/raw/<SYMBOL>/<interval>/*.zip` plus `.json` sidecars with the
standard library only. It does not import `lab`, `download`, `verify_data`, pandas or numpy, never
writes (no `results/`, no `.pkl` cache), never uses the network, and has no trading path. This
is deliberate: legacy `lab.Market.__init__` writes `results/data_audit.json`, `verify_data.main`
writes `results/*.json`, and `download.load` writes a `.pkl` cache, so none of them may be used
against the real tree. `tests/research/test_legacy_compat.py` redirects the legacy loader to a temp
directory, checks the adapter returns identical bars and identical legacy signal plans on synthetic
data, and re-hashes the protected files afterwards.

Archives are accepted only if the sidecar says `verified` and the file hash equals both `sha256`
and `official_sha256`; duplicates across archives are refused.

## What the data can and cannot say
- Availability: archives carry no publication time. A bar is modelled as available at its end
  (open + interval), flagged `ESTIMATED`, with `published_at_utc = {absent_reason: ...}`.
- Not available and never fabricated: order-book depth, spread, queue position, cancellation
  timestamps, executed liquidations, funding, true fee tiers, historical venue filters.
- `microstructure_admission` is `BLOCKED` (`NO_ORDER_BOOK_DATASET`) without an admitted
  `ORDER_BOOK` manifest; OHLCV never substitutes.

## As-of admissibility (`asof.admissibility`)
Rejection codes: `AVAILABLE_UNKNOWN`, `AVAILABLE_AFTER_DECISION` (available_at + latency budget
> decision), `EVENT_AFTER_DECISION`, `VENUE_MISMATCH`, `INSTRUMENT_MISMATCH`,
`INSTRUMENT_TYPE_MISMATCH`, `UNIT_MISMATCH`, `STALE_DATA`, `CLOCK_UNCERTAIN`, `INVALID_RECORD`,
and (opt-in for live-captured feeds only) `INGESTED_AFTER_DECISION`. The latency budget in
milliseconds is a required argument; zero latency is never assumed. `select_as_of` keeps the
latest revision admissible at decision time and reports later revisions as excluded.
Admissibility is necessary, not sufficient.

## Qualification
`qualify_ohlcv` returns QUALIFIED or BLOCKED with the manifest hash. Coverage and tolerances
(`max_missing_bars`, `max_off_grid_bars`) are caller arguments taken from the frozen
preregistration; this code supplies no defaults. A QUALIFIED certificate says the archive is complete
under those tolerances, not that results from it are valid.
