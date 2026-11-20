---
name: research-adjudication
description: "Derive, record or inspect deterministic trial disposition with evidence status; not narrative evaluation or threshold changes."
---
# Research Adjudication

Read research/experiments/pipeline.py and research/validation/derive.py. Verify ledger and exact trial. Inspection uses adjudicate_trial(..., record_it=False); only supervisor may invoke record_it=True. Preserve four return fields: record (derived decision), recorded (whether this call recorded it), note (recording error or None), evidence_unavailable (separate evidence flag). A derived result is not a ledger disposition. For recorded=False check note; inspect actual ledger even after a failure because EXPERIMENT_COMPLETE may already have been appended. For recorded=True verify matching ADJUDICATION_RECORDED event and replay, and report evidence availability separately. A prior verified event can establish a historical recorded disposition even when a new read-only derivation has recorded=False; identify both distinctly. If evidence unavailable, do not claim verified qualification. Never override gate precedence or present synthetic outcomes as market qualification.

Return evidence, limitations, and next safe action. Follow AGENTS.md; this skill grants no authority.
