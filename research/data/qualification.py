"""Dataset admission: turn a dataset manifest into a QUALIFIED/BLOCKED certificate.

No statistical thresholds are invented here: every tolerance is an explicit argument supplied
from the frozen preregistration. Anything not demonstrated is BLOCKED or listed as a limitation.
"""
from __future__ import annotations
from ..contracts import parse_utc
from ..identifiers import digest
from .types import DATASET_KINDS

OHLCV_LIMITATIONS = (
    "no order-book depth, spread, queue position or cancellation timestamps",
    "no executed-liquidation or funding data",
    "publication time absent; availability modelled as bar end",
    "historical venue filters and true fee tiers unverified",
)


def qualify_ohlcv(manifest: dict, *, require_start_utc: str, require_end_utc: str, max_missing_bars: int,
                  max_off_grid_bars: int = 0) -> dict:
    """Certificate for an OHLCV manifest from OhlcvSource.manifest. Tolerances are caller-supplied."""
    issues = []
    if manifest.get("kind") != "OHLCV":
        issues.append("WRONG_KIND")
    else:
        if parse_utc(manifest["first_open_utc"]) > parse_utc(require_start_utc):
            issues.append("COVERAGE_STARTS_LATE")
        if parse_utc(manifest["last_open_utc"]) < parse_utc(require_end_utc):
            issues.append("COVERAGE_ENDS_EARLY")
        if manifest["missing_bars"] > max_missing_bars:
            issues.append("MISSING_BARS_EXCEED_TOLERANCE")
        if manifest["off_grid_bars"] > max_off_grid_bars:
            issues.append("OFF_GRID_BARS")
        if not manifest.get("archives"):
            issues.append("NO_ARCHIVES")
        retrieved = manifest.get("retrieved_utc")
        try:
            if retrieved is None:
                issues.append("RETRIEVAL_TIME_UNKNOWN")
            elif parse_utc(manifest["last_open_utc"]) > parse_utc(retrieved):
                issues.append("COVERAGE_CLAIM_IN_FUTURE")      # data cannot cover a period after it was retrieved
        except ValueError:
            issues.append("RETRIEVAL_TIME_UNKNOWN")
    cert = {"status": "BLOCKED" if issues else "QUALIFIED", "issues": sorted(issues),
            "manifest_sha256": manifest.get("manifest_sha256"),
            "tolerances": {"max_missing_bars": max_missing_bars, "max_off_grid_bars": max_off_grid_bars,
                           "require_start_utc": require_start_utc, "require_end_utc": require_end_utc},
            "limitations": list(OHLCV_LIMITATIONS)}
    cert["certificate_sha256"] = digest(cert)
    return cert


def microstructure_admission(manifests) -> dict:
    """Microstructure research needs a real ORDER_BOOK dataset. OHLCV never substitutes (blueprint G14)."""
    books = [m for m in manifests if m.get("kind") == "ORDER_BOOK"]
    unknown = [m for m in manifests if m.get("kind") not in DATASET_KINDS]
    if unknown:
        return {"status": "BLOCKED", "issues": ["UNKNOWN_DATASET_KIND"]}
    if not books:
        return {"status": "BLOCKED", "issues": ["NO_ORDER_BOOK_DATASET"],
                "note": "OHLCV cannot be used to reconstruct depth; microstructure stays blocked"}
    missing = [m.get("manifest_sha256") for m in books if not (m.get("sequence_ok") is True and m.get("license_reviewed") is True)]
    if missing:
        return {"status": "BLOCKED", "issues": ["ORDER_BOOK_NOT_ADMITTED"], "manifests": missing}
    return {"status": "QUALIFIED", "issues": []}


def check_cost_model_provenance(cost_model: dict, *, venue: str, instrument_type: str) -> list:
    """A cost/fee model must name the venue and instrument type it was derived for; never reuse silently."""
    issues = []
    if cost_model.get("source_venue") in (None, "UNKNOWN"):
        issues.append("COST_MODEL_VENUE_UNKNOWN")
    elif cost_model["source_venue"] != venue:
        issues.append("COST_MODEL_VENUE_MISMATCH")
    if cost_model.get("instrument_type") != instrument_type:
        issues.append("COST_MODEL_INSTRUMENT_TYPE_MISMATCH")
    return sorted(issues)
