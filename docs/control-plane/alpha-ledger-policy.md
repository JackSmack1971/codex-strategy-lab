# Alpha evidence ledger policy (PROPOSED project design, not a Codex API)

Implemented in `research/ledger.py`, `research/prereg.py`, `research/provenance.py` and
`scripts/research.py` (`scripts/lab research ...`). Data lives in the git-ignored
`work/research/` directory; the CLI refuses roots that resolve outside `work/`.

## What the ledger is - and is not
An append-only JSONL file of canonical-JSON events, each carrying `seq`, `prev_hash` and
`event_hash`. This is **tamper evidence only**. It is not tamper prevention, not independent
attestation, and a valid chain proves nothing about whether the recorded observations,
prices or results are true. Whoever can rewrite the whole file can rebuild a consistent chain;
remote or immutable retention would need separately authorised infrastructure.

## Admission rules
- **Single writer:** exclusive lock file; contention waits briefly then fails with `LOCK_HELD`.
  Stale locks are never stolen automatically.
- **Idempotency:** each event has an `idempotency_key`; same key + same content returns the
  original event (`created=false`), same key + different content is `IDEMPOTENCY_CONFLICT`.
- **Optimistic concurrency:** `expected_head` rejects stale writers (`STALE_STATE`); lifecycle
  transitions must cite the current per-hypothesis state digest.
- **Ordering:** `seq` is contiguous, timestamps may not go backwards.
- **Replay = rules:** every committed event is re-validated on every scan with the same rules
  used at append time, so a hash-valid but rule-breaking forged event is detected (`CORRUPT`).
- **Trials:** a trial is first recorded `STARTED`, must cite the current frozen preregistration
  digest, use the preregistered splits and holdout class, take the next `trial_sequence`, and fit
  the family `max_trials`. A `trial_id` cannot be reused with different immutable fields.
  Failed, aborted, interrupted and superseded trials stay in the family count.
- **Preregistration:** frozen only from `REVIEW_RECORDED`; amendments chain by digest and are
  refused once any trial exists for the hypothesis version (`AMENDMENT_AFTER_EXPOSURE`). A hypothesis keeps its
  `family_id` across versions (`FAMILY_REASSIGNMENT`); a migration that carries the old multiplicity obligations is not implemented.
- **Evidence-gated states:** `DATA_QUALIFIED` needs `dataset-qualification:<sha256>` and `REVIEW_RECORDED` needs
  `review:<sha256>` references into the content-addressed `evidence/` store; the ledger re-derives the dataset certificate
  and re-executes every objection test, so free text never satisfies them. Preregistered datasets must be among the
  qualified manifests (`DATASET_NOT_QUALIFIED`).
- **Adjudications are derived, not accepted:** `ADJUDICATION_RECORDED` is compared with the record that
  `validation/derive.py` re-derives from ledger state, hash-verified run artifacts and the evidence store
  (`ADJUDICATION_MISMATCH`). Appending requires the evidence to be present (`EVIDENCE_UNAVAILABLE`); replaying on a machine
  without it reports `evidence.status = UNVERIFIABLE` (exit 4 from the CLI), never a silent OK. Artifacts or evidence that are
  present but changed fail replay as `CORRUPT`.
- **Dedicated events:** `PREREG_FROZEN` and `ADJUDICATED` are reachable only through their own
  events, never through a generic transition.

## Failure classes and recovery
| Scan status | Meaning | Behaviour |
|---|---|---|
| `OK` | all lines committed and consistent | appends allowed |
| `INCOMPLETE_TAIL` | trailing bytes with no newline that are not a valid event (torn write) | appends refused (`NEEDS_RECONCILE`); `reconcile_tail` copies the bytes to `quarantine/`, truncates only that uncommitted tail, appends a `RECONCILIATION` event |
| `UNTERMINATED_VALID_TAIL` | complete valid last event missing only its newline | `reconcile_tail` adds the newline; nothing discarded |
| `CORRUPT` | any newline-terminated record is invalid, reordered, duplicated, missing, non-canonical or rule-breaking | never repaired or truncated; a copy goes to `quarantine/`, `QUARANTINED.json` is written, all appends fail closed until a human reconciles |
| `QUARANTINED` | marker present | fail closed even if the file is later "fixed" |

`verify` and `status` are read-only. `reconcile_*` are explicit calls and never run implicitly.

## Interrupted experiments
A trial left `STARTED` after a crash blocks `EXPERIMENT_COMPLETE`. `reconcile_interrupted_trials`
marks it `INTERRUPTED` (still counted in the family) and reconciles its run manifest. `COMPLETED` is accepted only
when the run directory on disk holds `metrics.json` and `execution.json` whose digest equals the supplied
`artifact_manifest_hash`; the recorded hashes come from the files actually present. Output files without a ledger record are
not completions. Interpreter caches (`__pycache__`, `*.pyc`) never enter source or artifact digests.

## Limits
Single host, file-based, O(n) replay per operation; no multi-host locking guarantees on network
filesystems. Hash chaining does not hide or protect secrets: never put credentials in payloads.
