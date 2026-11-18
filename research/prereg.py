"""Preregistration freeze/amend through the ledger (no separate store).

Freezing hashes the canonical record and appends PREREG_FROZEN; the ledger rules enforce
order (REVIEW_RECORDED first), amendment chaining (amends_sha256 = current digest,
amendment = previous + 1) and refuse amendments once any test access has been recorded.
Old preregistrations are never overwritten: every version stays in the ledger.
"""
from __future__ import annotations
from .contracts import require_valid
from .identifiers import derived_id


def prereg_digest(record: dict) -> str:
    return require_valid("preregistration", record)


def freeze(ledger, record: dict, actor: dict, reason: str, expected_head=None):
    sha = prereg_digest(record)
    subject = {"hypothesis_id": record["hypothesis_id"], "hypothesis_version": record["hypothesis_version"]}
    return ledger.append("PREREG_FROZEN", subject=subject, payload=record, actor=actor, reason=reason,
                         idempotency_key=derived_id("prereg", sha), expected_head=expected_head)
