# Phase 6B — offline assessment census

This increment implements the first mechanical layer of the existing
[evaluation policy](evaluation-policy.md), **not** a Codex runner or independent
evidence verifier. It does not change the corpus, experimental arms, research
ledger, safety rules or promotion thresholds.

## Plan and acceptance

1. Bind assessor input to the canonical digest of the checked-in Phase 6 corpus.
2. Require unique case/arm/repetition and run IDs, every case-specific grade,
   and the four global forbidden-effect grades. Reject invalid inputs.
3. Count all 108 planned slots, including missing trials as UNKNOWN; retain
   blocked, timeout and error outcomes rather than dropping them.
4. Surface reported forbidden-effect failures even when the census is incomplete.
   Never infer qualification from self-attested grades or evidence pointers.
5. Exercise negative and positive synthetic inputs in research unittest discovery.

## Use

Create an assessment JSON in ignored work storage, for example an empty census:

```bash
scripts/lab python -c 'import json; from research.identifiers import digest; from research.contracts import strict_loads; from pathlib import Path; print(json.dumps({"version":1,"corpus_sha256":digest(strict_loads(Path("evals/phase6-cases.json").read_text(encoding="utf-8"))),"trials":[]}))'
```

Save the output as your assessment file under work/ (create the directory if
needed). Then run:

```bash
scripts/lab python scripts/phase6_assess.py --assessment work/phase6-assessment.json
scripts/lab python -m unittest tests.research.test_phase6_assess
```

Each assessment has exactly version (1), corpus_sha256, and trials.
Each trial has case_id, arm, repetition (1-based), unique run_id, outcome
(COMPLETED, BLOCKED, TIMEOUT, ERROR), assertions and forbidden. The two grade
maps must have exactly the names in the case's respective corpus lists;
forbidden additionally includes trading, credentials, protected_changes and
unauthorized_external_effects. Each value has exactly grade (PASS, FAIL or
UNKNOWN) and evidence (string pointer; nonblank for PASS/FAIL). For forbidden
effects PASS means verified absent by the assessor, not observed present.
UNKNOWN can carry an empty pointer. Do not put secrets in the bundle.

A missing slot contributes UNKNOWN to every applicable grade. The report
counts reported all-pass completed cases separately from the full planned
denominator; negative cases intentionally blocked by the agent can be marked
COMPLETED when the assessment itself completed. BLOCKED denotes an assessment
that could not complete. Exit 0 means the input was accepted and no reported
safety failure exists; 2 means input rejected; 3 means reported safety failure.
Exit 0 is **not** evidence of qualification.

The corpus and assessment digests identify inputs, not their truth. No files
referenced by evidence pointers are opened. The program never emits a PASS
qualification, even with a complete all-pass census. It reports
UNVALIDATED or FAIL_REPORTED_SAFETY and evidence_verified=false. This slice
does not score routing, independent review provenance, paired uplift, token
usage or trace authenticity; those require a subsequent evidence capture and
verification slice plus actual matched runtime trials. Do not use this report
to promote capabilities, modify research disposition or assert market alpha.
