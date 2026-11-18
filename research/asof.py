"""Point-in-time admissibility: may this observation be used for a decision at time T?

Event time, publication time, availability time, ingestion time and decision time are separate.
Rules (blueprint section 7):
* available_at_utc "UNKNOWN" is inadmissible - it is never assumed to mean zero latency.
* A latency budget (ms) for decide+compute+submit is REQUIRED from the caller (no default);
  available_at + budget must be <= decision_at.
* Venue, instrument, instrument type (spot vs perpetual...) and unit must match the expectation.
* Later revisions that became available after the decision are excluded; the latest revision
  that was admissible at decision time is used.
* Ingestion time is checked only when Expectation.require_ingested_by_decision is set (live-captured feeds).
* STALE-flagged data, clocks of UNKNOWN provenance and CLOCK_UNCERTAIN data are inadmissible,
  and max_age_seconds (if given) bounds event age.
Admissibility is necessary, not sufficient: it does not prove the data are correct.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from .contracts import parse_utc, validate


@dataclass(frozen=True)
class Expectation:
    venue: str
    instrument_id: str
    instrument_type: str
    unit: str
    max_age_seconds: Optional[int] = None
    # True only for feeds WE captured live: our receipt time then bounds what a live process could know.
    # Historical archives are downloaded long after the fact, so their ingestion time says nothing about availability.
    require_ingested_by_decision: bool = False


def admissibility(obs: dict, decision_at_utc: str, expect: Expectation, *, latency_budget_ms: int) -> tuple:
    """Return a sorted tuple of rejection codes; empty means admissible."""
    if isinstance(latency_budget_ms, bool) or not isinstance(latency_budget_ms, int) or latency_budget_ms < 0:
        raise ValueError("latency_budget_ms must be a non-negative integer chosen by the caller")
    decision = parse_utc(decision_at_utc)
    codes = set()
    if validate("observation", obs):
        return ("INVALID_RECORD",)
    if obs["venue"] != expect.venue:
        codes.add("VENUE_MISMATCH")
    if obs["instrument_id"] != expect.instrument_id:
        codes.add("INSTRUMENT_MISMATCH")
    if obs["instrument_type"] != expect.instrument_type:
        codes.add("INSTRUMENT_TYPE_MISMATCH")
    if obs["unit"] != expect.unit:
        codes.add("UNIT_MISMATCH")
    if obs["available_at_utc"] == "UNKNOWN":
        codes.add("AVAILABLE_UNKNOWN")
    else:
        usable_at = parse_utc(obs["available_at_utc"]) + timedelta(milliseconds=latency_budget_ms)
        if usable_at > decision:
            codes.add("AVAILABLE_AFTER_DECISION")
    if expect.require_ingested_by_decision and parse_utc(obs["ingested_at_utc"]) > decision and "AVAILABLE_AFTER_DECISION" not in codes:
        codes.add("INGESTED_AFTER_DECISION")
    if parse_utc(obs["event_at_utc"]) > decision:
        codes.add("EVENT_AFTER_DECISION")
    flags = set(obs["quality_flags"])
    if "STALE" in flags:
        codes.add("STALE_DATA")
    if "CLOCK_UNCERTAIN" in flags or obs["clock"] == "UNKNOWN":
        codes.add("CLOCK_UNCERTAIN")
    if expect.max_age_seconds is not None and decision - parse_utc(obs["event_at_utc"]) > timedelta(seconds=expect.max_age_seconds):
        codes.add("STALE_DATA")
    return tuple(sorted(codes))


def _key(o):
    return (o.get("source_id"), o.get("instrument_id"), o.get("event_at_utc"), o.get("unit"))


def select_as_of(observations, decision_at_utc: str, expect: Expectation, *, latency_budget_ms: int):
    """As-of join. Returns (chosen, excluded) where excluded is [(observation_id, codes), ...].

    One observation per logical key (source, instrument, event time, unit): the admissible
    revision with the latest availability. Output order is deterministic.
    """
    chosen, excluded, verdicts = {}, [], []
    for o in observations:
        codes = admissibility(o, decision_at_utc, expect, latency_budget_ms=latency_budget_ms)
        verdicts.append((o, codes))
        if codes:
            continue
        k = _key(o)
        rank = (parse_utc(o["available_at_utc"]), parse_utc(o["ingested_at_utc"]), o["revision_id"])
        if k not in chosen or rank > chosen[k][0]:
            chosen[k] = (rank, o)
    for o, codes in verdicts:
        if codes:
            extra = ("REVISION_AFTER_DECISION",) if "AVAILABLE_AFTER_DECISION" in codes and _key(o) in chosen else ()
            excluded.append((o.get("observation_id", "UNKNOWN"), tuple(sorted(set(codes) | set(extra)))))
        elif chosen[_key(o)][1] is not o:
            excluded.append((o["observation_id"], ("SUPERSEDED_REVISION",)))
    ordered = [chosen[k][1] for k in sorted(chosen)]
    return ordered, sorted(excluded)


def sequence_gaps(sequence_ids) -> dict:
    """Detect gaps, duplicates and reordering in an integer sequence (snapshot/delta feeds)."""
    ids = list(sequence_ids)
    gaps = [(a, b) for a, b in zip(ids, ids[1:]) if b > a + 1]
    dups = sorted({x for i, x in enumerate(ids) if x in ids[:i]})
    backwards = [(a, b) for a, b in zip(ids, ids[1:]) if b < a]
    return {"gaps": gaps, "duplicates": dups, "reordered": backwards, "ok": not (gaps or dups or backwards)}
