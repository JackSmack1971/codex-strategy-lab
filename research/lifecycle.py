"""Workflow-state machine (PROPOSED project schema, not a Codex API).

Workflow state (where a hypothesis version is in the process) is deliberately separate
from research disposition (the adjudicated verdict). BLOCKED and FAILED are workflow
outcomes: FAILED means an execution failed and is NOT a REJECT of the hypothesis.
BLOCKED and FAILED are terminal for a hypothesis version; a new version is required.
State names come from common.schema.json (single authority); only the legal edges live here.
"""
from __future__ import annotations
from .contracts import load_schema, Issue, ContractError, parse_utc
from .identifiers import digest

STATES = tuple(load_schema("common")["$defs"]["workflow_state"]["enum"])
DISPOSITIONS = tuple(load_schema("common")["$defs"]["disposition"]["enum"])

TRANSITIONS = {
    "DRAFT": {"REGISTERED"},
    "REGISTERED": {"DATA_PENDING", "BLOCKED"},
    "DATA_PENDING": {"DATA_QUALIFIED", "BLOCKED"},
    "DATA_QUALIFIED": {"REVIEW_PENDING"},
    "REVIEW_PENDING": {"REVIEW_RECORDED", "BLOCKED"},
    "REVIEW_RECORDED": {"PREREG_FROZEN"},
    "PREREG_FROZEN": {"EXPERIMENT_PENDING"},
    "EXPERIMENT_PENDING": {"EXPERIMENT_COMPLETE", "FAILED"},
    "EXPERIMENT_COMPLETE": {"ADJUDICATED"},
    "ADJUDICATED": {"REPORTED"},
    "REPORTED": set(), "BLOCKED": set(), "FAILED": set(),
}
TERMINAL = frozenset(s for s, nxt in TRANSITIONS.items() if not nxt)
INITIAL = "DRAFT"


def is_legal(current: str, target: str) -> bool:
    return current in TRANSITIONS and target in TRANSITIONS[current]


def check_transition(current: str, target: str) -> None:
    if current not in TRANSITIONS or target not in STATES:
        raise ContractError([Issue("/state", "UNKNOWN_STATE", f"{current!r} -> {target!r}")])
    if current in TERMINAL:
        raise ContractError([Issue("/state", "TERMINAL_STATE", f"{current} is terminal; register a new version")])
    if target not in TRANSITIONS[current]:
        raise ContractError([Issue("/state", "ILLEGAL_TRANSITION", f"{current} -> {target}")])


def make_transition(*, hypothesis_id, hypothesis_version, current, target, actor, reason,
                    evidence_refs, timestamp_utc, prior_state_digest) -> dict:
    """Build a transition record (validated; carries actor, prior digest, evidence, time)."""
    check_transition(current, target)
    parse_utc(timestamp_utc)
    for name, val in (("actor", actor), ("reason", reason)):
        if not isinstance(val, str) or not val.strip():
            raise ContractError([Issue(f"/{name}", "REQUIRED", f"{name} must be non-empty")])
    rec = {"hypothesis_id": hypothesis_id, "hypothesis_version": hypothesis_version,
           "from_state": current, "to_state": target, "actor": actor, "reason": reason,
           "evidence_refs": list(evidence_refs), "timestamp_utc": timestamp_utc,
           "prior_state_digest": prior_state_digest}
    rec["transition_digest"] = digest(rec)
    return rec


def state_digest(hypothesis_id, hypothesis_version, state, last_transition_digest=None) -> str:
    return digest({"hypothesis_id": hypothesis_id, "hypothesis_version": hypothesis_version,
                   "state": state, "last_transition_digest": last_transition_digest})
