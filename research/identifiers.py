"""Deterministic canonical serialization, digests and derived identifiers.

Canonical form (version 1): UTF-8 JSON, sorted keys, no whitespace, finite numbers
only. Integral floats are normalised to ints (1.0 -> 1, -0.0 -> 0) so equal values
hash equally. Ints must fit in signed 64 bits. Tuples, sets, NaN/Inf, non-string keys
and lone surrogates are rejected rather than coerced.
"""
from __future__ import annotations
import hashlib, json, math

CANONICAL_VERSION = 1
_INT_LIMIT = 2**63 - 1


class CanonicalizationError(ValueError):
    def __init__(self, code: str, path: str, message: str):
        super().__init__(f"{code} at {path}: {message}")
        self.code, self.path = code, path


def _norm(value, path):
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise CanonicalizationError("BAD_STRING", path, "string is not valid UTF-8") from None
        return value
    if isinstance(value, int):
        if abs(value) > _INT_LIMIT:
            raise CanonicalizationError("INT_RANGE", path, "integer exceeds signed 64-bit range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("NON_FINITE", path, "NaN/Infinity are not representable")
        if value == int(value):
            return _norm(int(value), path)
        return value
    if isinstance(value, list):
        return [_norm(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise CanonicalizationError("BAD_KEY", path, f"non-string key {k!r}")
            out[k] = _norm(v, f"{path}.{k}")
        return out
    raise CanonicalizationError("BAD_TYPE", path, f"unsupported type {type(value).__name__}")


def canonical_bytes(value) -> bytes:
    return json.dumps(_norm(value, "$"), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value) -> str:
    """SHA-256 of the canonical serialization (stable across key order)."""
    return sha256_hex(canonical_bytes(value))


def derived_id(namespace: str, key: str) -> str:
    """Immutable ID derived from a namespace and an idempotency key (same key -> same ID)."""
    if not namespace or not key:
        raise ValueError("namespace and key are required")
    return f"{namespace}-{sha256_hex((namespace + chr(0) + key).encode('utf-8'))[:32]}"
