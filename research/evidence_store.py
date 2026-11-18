"""Content-addressed evidence store and the verifiers that the ledger applies to evidence references.

Files live in <ledger root>/evidence/<sha256>.json and are stored as canonical bytes, so the file name IS
the digest of its content. A reference such as "dataset-qualification:<sha256>" is accepted by the
ledger only if the bundle exists, hashes to that name AND its claims are re-derived here by
deterministic code (the certificate is recomputed from the stored manifest; every objection test is
re-executed from its stored evidence). A free-text or self-attested field never satisfies a gate.

Known limits (disclosed, not hidden): the manifest's archive hashes are not re-hashed against archive
bytes here (the data root may be absent); reviewer INDEPENDENCE (separate agent context) is a Phase 6
property and stays UNVERIFIED; a writer who controls both the ledger and this directory can forge both.
"""
from __future__ import annotations
import os
from pathlib import Path

from .contracts import ContractError, parse_utc, strict_loads
from .identifiers import canonical_bytes, digest, sha256_hex

DATASET_PREFIX = "dataset-qualification:"
REVIEW_PREFIX = "review:"


class EvidenceError(Exception):
    def __init__(self, message, code="EVIDENCE_INVALID"):
        super().__init__(message)
        self.code = code


class Unavailable(EvidenceError):
    """The referenced evidence is not present (replay on a machine without the store)."""

    def __init__(self, message):
        super().__init__(message, "EVIDENCE_UNAVAILABLE")


class EvidenceStore:
    def __init__(self, ledger_root):
        self.dir = Path(ledger_root) / "evidence"

    def put(self, obj) -> str:
        data = canonical_bytes(obj)
        sha = sha256_hex(data)
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{sha}.json"
        if path.exists():
            if path.read_bytes() != data:
                raise EvidenceError("existing evidence file does not match its name", "EVIDENCE_CONFLICT")
            return sha
        with open(path, "xb") as fh:
            fh.write(data)
        return sha

    def get(self, sha: str):
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise EvidenceError(f"malformed evidence digest {sha!r}", "EVIDENCE_REF_MALFORMED")
        path = self.dir / f"{sha}.json"
        if not path.is_file():
            raise Unavailable(f"evidence {sha[:12]} is not in the store")
        data = path.read_bytes()
        if sha256_hex(data) != sha:
            raise EvidenceError(f"evidence {sha[:12]} does not hash to its name", "EVIDENCE_TAMPERED")
        try:
            return strict_loads(data.decode("utf-8"))
        except ValueError as exc:
            raise EvidenceError(f"evidence {sha[:12]} unreadable: {exc}", "EVIDENCE_TAMPERED") from None


def refs_with(prefix, refs):
    return [r[len(prefix):] for r in refs if isinstance(r, str) and r.startswith(prefix)]


def verify_dataset_bundle(store, sha: str) -> dict:
    """Re-derive a dataset qualification. Returns {manifest_sha256, instrument_id, criteria, certificate_sha256}."""
    from .data import qualification as q
    b = store.get(sha)
    if not isinstance(b, dict) or set(b) != {"manifest", "certificate", "criteria"}:
        raise EvidenceError("dataset bundle must be {manifest, certificate, criteria}")
    man, cert, crit = b["manifest"], b["certificate"], b["criteria"]
    if not isinstance(man, dict) or "manifest_sha256" not in man:
        raise EvidenceError("manifest lacks manifest_sha256")
    if digest({k: v for k, v in man.items() if k != "manifest_sha256"}) != man["manifest_sha256"]:
        raise EvidenceError("manifest_sha256 does not match the manifest body", "MANIFEST_DIGEST")
    try:
        again = q.qualify_ohlcv(man, **crit)
    except (TypeError, KeyError, ValueError) as exc:
        raise EvidenceError(f"certificate cannot be re-derived: {exc}") from None
    if again != cert:
        raise EvidenceError("stored certificate differs from the re-derived certificate", "CERTIFICATE_MISMATCH")
    if cert["status"] != "QUALIFIED":
        raise EvidenceError(f"dataset is {cert['status']}: {cert['issues']}", "DATASET_NOT_QUALIFIED")
    return {"manifest_sha256": man["manifest_sha256"], "instrument_id": man.get("instrument_id"),
            "criteria": crit, "certificate_sha256": cert["certificate_sha256"], "limitations": cert["limitations"]}


def verify_review_bundle(store, sha: str, hid: str, ver: int) -> dict:
    """Re-execute every objection test; REVIEW_RECORDED only if every material objection is REFUTED."""
    from .validation import adversarial
    b = store.get(sha)
    if not isinstance(b, dict) or set(b) != {"objections", "evidence"} or not isinstance(b["objections"], list) \
            or not b["objections"]:
        raise EvidenceError("review bundle must be {objections: [>=1], evidence: {...}}")
    for o in b["objections"]:
        if (o.get("hypothesis_id"), o.get("hypothesis_version")) != (hid, ver):
            raise EvidenceError("objection is about a different hypothesis version", "REVIEW_SUBJECT")
        stripped = {k: v for k, v in o.items() if k != "test_result"}
        stripped["adjudication_status"] = "PENDING"
        spec = o.get("test_specification", {})
        if spec.get("type") == "MANUAL_POLICY":
            again = adversarial.execute(stripped, {}, "2000-01-01T00:00:00Z")
        else:
            res = o.get("test_result")
            if not res:
                raise EvidenceError(f"objection {o.get('objection_id')} has no executed test", "REVIEW_UNEXECUTED")
            try:
                parse_utc(res["executed_at_utc"])
                again = adversarial.execute(stripped, b["evidence"].get(o["objection_id"], {}), res["executed_at_utc"])
            except (KeyError, ValueError, TypeError, ContractError) as exc:
                raise EvidenceError(f"objection {o.get('objection_id')} cannot be re-executed: {exc}") from None
        if again != o:
            raise EvidenceError(f"objection {o.get('objection_id')} differs from its re-executed result", "REVIEW_MISMATCH")
    outcome = adversarial.review_outcome(b["objections"])
    if outcome["state"] != "REVIEW_RECORDED":
        raise EvidenceError(f"material objections not refuted: {outcome['blocking']}", "REVIEW_BLOCKED")
    return {"review_sha256": sha, "objection_ids": sorted(o["objection_id"] for o in b["objections"])}
