---
name: experiment-preregistration
description: "Prepare, independently review and supervisor-freeze quantitative methodology; not post-result tuning."
---
# Experiment Preregistration

Read research/schemas/preregistration.schema.json, research/prereg.py, research/lifecycle.py and docs/control-plane/orchestration.md. Draft chronological splits, purge/embargo, minimum sample, costs/stresses, family multiplicity, budget and gates without test access. Supervisor registers and reaches REVIEW_PENDING after data qualification. Methodology reviewer receives exact draft digest and evidence; adversarial reviewer challenges it. Supervisor verifies handoffs and executable objection evidence; unresolved material objections block progression. Record review through the engine (REVIEW_RECORDED), then freeze that exact reviewed draft through prereg-freeze. No worker freezes or mutates state. Changed draft invalidates its prior review; if already recorded, stop and reconcile with the engine's legal lifecycle instead of inventing a transition. After freeze, review compliance against the frozen digest, never retroactively tune thresholds. Amend only through the established versioned path preserving exposure history.

Return evidence, limitations, and next safe action. Follow AGENTS.md; this skill grants no authority.
