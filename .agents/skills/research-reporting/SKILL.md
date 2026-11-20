---
name: research-reporting
description: "Produce evidence-linked reports from verified recorded adjudication or labeled diagnostics; not generating unexecuted metrics."
---
# Research Reporting

Inspect research/reporting/render.py and ledger. Preserve pipeline record, recorded, note and evidence_unavailable separately. Before calling build_report for an authoritative report, verify matching ADJUDICATION_RECORDED event, bound trial/run, replay and artifact availability; render does not perform this verification for you. If no verified event, recording failed, or evidence unavailable, return labeled provisional diagnostic (derived decision if available, recording status/error and missing evidence), not an authoritative qualification report; a previously recorded event with unavailable evidence is historical/unverified, not current verified success. Bind claims to artifact hashes, family, sample, holdout classification and gate values. Label synthetic outcomes as machinery checks only. Write only assigned derived reports under work, never ledger or historical evidence.

Return evidence, limitations, and next safe action. Follow AGENTS.md; this skill grants no authority.
