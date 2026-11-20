---
name: research-adjudication
description: "Derive or inspect deterministic disposition for a research trial; not narrative evaluation or threshold changes."
---
# Research Adjudication

Read research/experiments/pipeline.py and research/validation/derive.py. Verify ledger and select exact trial. Use adjudicate_trial with record_it=False for inspection; only designated writer may record via existing pipeline. Return recorded status and evidence gaps, never override gate precedence or promote a synthetic result as market qualification.

Return evidence, limitations, and next safe action. Follow AGENTS.md; this skill grants no authority.
