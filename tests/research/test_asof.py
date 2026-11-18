import unittest
from datetime import datetime, timedelta, timezone

from research import asof
from research.asof import Expectation
from research.data import qualification as q
from tests.research import builders as b

EXP = Expectation(venue="SYNTHETIC", instrument_id="SYN-USD", instrument_type="SPOT", unit="USD")
DECISION = "2026-01-01T00:00:10Z"


def ts(base, **delta):
    dt = datetime.fromisoformat(base.replace("Z", "+00:00")) + timedelta(**delta)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def obs(available="2026-01-01T00:00:05Z", **over):
    kw = dict(available_at_utc=available, published_at_utc=ts(available, seconds=-1),
              ingested_at_utc=ts(available, seconds=1))
    kw.update(over)
    return b.observation(**kw)


def verdict(o, decision=DECISION, expect=EXP, budget=0):
    return asof.admissibility(o, decision, expect, latency_budget_ms=budget)


class Admissibility(unittest.TestCase):
    def test_valid_observation_is_admissible(self):
        self.assertEqual(verdict(obs()), ())

    def test_available_one_millisecond_after_decision_is_rejected(self):  # G02
        self.assertEqual(verdict(obs(available=ts(DECISION, milliseconds=1))), ("AVAILABLE_AFTER_DECISION",))
        self.assertEqual(verdict(obs(available=DECISION)), ())          # equal is allowed with zero budget

    def test_latency_budget_is_required_and_applied(self):
        with self.assertRaises(TypeError):
            asof.admissibility(obs(), DECISION, EXP)                    # no default: zero latency is never assumed
        for bad in (-1, 1.5, True, None):
            with self.assertRaises(ValueError):
                asof.admissibility(obs(), DECISION, EXP, latency_budget_ms=bad)
        o = obs(available=ts(DECISION, seconds=-1))
        self.assertEqual(verdict(o, budget=999), ())
        self.assertEqual(verdict(o, budget=1001), ("AVAILABLE_AFTER_DECISION",))

    def test_unknown_availability_is_inadmissible_not_zero_latency(self):
        o = b.observation(available_at_utc="UNKNOWN", ingested_at_utc="2026-01-01T00:00:06Z")
        self.assertIn("AVAILABLE_UNKNOWN", verdict(o))

    def test_perp_funding_cannot_stand_in_for_spot_quote(self):  # G03
        o = obs(instrument_type="PERPETUAL", unit="USD_PER_8H", instrument_id="SYN-PERP")
        self.assertEqual(verdict(o), ("INSTRUMENT_MISMATCH", "INSTRUMENT_TYPE_MISMATCH", "UNIT_MISMATCH"))
        self.assertEqual(verdict(obs(venue="OTHER")), ("VENUE_MISMATCH",))

    def test_other_inadmissible_conditions(self):
        self.assertIn("STALE_DATA", verdict(obs(quality_flags=["STALE"])))
        self.assertIn("CLOCK_UNCERTAIN", verdict(obs(quality_flags=["CLOCK_UNCERTAIN"])))
        self.assertIn("CLOCK_UNCERTAIN", verdict(obs(clock="UNKNOWN")))
        old = Expectation("SYNTHETIC", "SYN-USD", "SPOT", "USD", max_age_seconds=1)
        self.assertIn("STALE_DATA", asof.admissibility(obs(), DECISION, old, latency_budget_ms=0))
        self.assertEqual(verdict(b.observation(value=float("nan"))), ("INVALID_RECORD",))
        late_ingest = obs(ingested_at_utc=ts(DECISION, seconds=1), available="2026-01-01T00:00:05Z")
        self.assertEqual(verdict(late_ingest), ())      # backfilled archives: our download time is irrelevant
        live = Expectation("SYNTHETIC", "SYN-USD", "SPOT", "USD", require_ingested_by_decision=True)
        self.assertEqual(asof.admissibility(late_ingest, DECISION, live, latency_budget_ms=0), ("INGESTED_AFTER_DECISION",))

    def test_naive_timestamps_are_rejected_as_invalid(self):
        self.assertEqual(verdict(obs(event_at_utc="2026-01-01T00:00:00")), ("INVALID_RECORD",))


class AsOfJoin(unittest.TestCase):
    def rev(self, rev_id, available, value, oid):
        return obs(available=available, revision_id=rev_id, value=value, observation_id=oid,
                   ingested_at_utc=ts(available, seconds=1))

    def test_revised_headline_after_decision_is_excluded(self):  # G04
        first = self.rev("rev-0001", "2026-01-01T00:00:05Z", 1.0, "obs-0001")
        revised = self.rev("rev-0002", "2026-01-01T00:00:20Z", 2.0, "obs-0002")
        chosen, excluded = asof.select_as_of([revised, first], DECISION, EXP, latency_budget_ms=0)
        self.assertEqual([o["value"] for o in chosen], [1.0])
        self.assertEqual(excluded, [("obs-0002", ("AVAILABLE_AFTER_DECISION", "REVISION_AFTER_DECISION"))])

    def test_latest_admissible_revision_wins_and_order_is_deterministic(self):
        r1 = self.rev("rev-0001", "2026-01-01T00:00:05Z", 1.0, "obs-0001")
        r2 = self.rev("rev-0002", "2026-01-01T00:00:08Z", 2.0, "obs-0002")
        a = asof.select_as_of([r1, r2], DECISION, EXP, latency_budget_ms=0)
        b_ = asof.select_as_of([r2, r1], DECISION, EXP, latency_budget_ms=0)
        self.assertEqual(a, b_)
        self.assertEqual([o["value"] for o in a[0]], [2.0])
        self.assertEqual(a[1], [("obs-0001", ("SUPERSEDED_REVISION",))])

    def test_mixed_timestamp_precision_ranks_by_time_not_text(self):
        r1 = self.rev("rev-0001", "2026-01-01T00:00:05Z", 1.0, "obs-0001")
        r2 = self.rev("rev-0002", "2026-01-01T00:00:05.500000Z", 2.0, "obs-0002")
        chosen, _ = asof.select_as_of([r1, r2], DECISION, EXP, latency_budget_ms=0)
        self.assertEqual([o["value"] for o in chosen], [2.0])


class SequencesAndAdmission(unittest.TestCase):
    def test_sequence_gap_duplicate_and_reorder_detection(self):
        self.assertTrue(asof.sequence_gaps([1, 2, 3, 4])["ok"])
        r = asof.sequence_gaps([1, 2, 4, 4, 3])
        self.assertEqual((r["gaps"], r["duplicates"], r["reordered"], r["ok"]), ([(2, 4)], [4], [(4, 3)], False))

    def test_microstructure_blocked_without_order_book(self):  # G14
        self.assertEqual(q.microstructure_admission([])["issues"], ["NO_ORDER_BOOK_DATASET"])
        ohlcv = {"kind": "OHLCV", "manifest_sha256": "a" * 64}
        self.assertEqual(q.microstructure_admission([ohlcv])["status"], "BLOCKED")
        book = {"kind": "ORDER_BOOK", "manifest_sha256": "b" * 64}
        self.assertEqual(q.microstructure_admission([ohlcv, book])["issues"], ["ORDER_BOOK_NOT_ADMITTED"])
        self.assertEqual(q.microstructure_admission([dict(book, sequence_ok=True, license_reviewed=True)])["status"], "QUALIFIED")
        self.assertEqual(q.microstructure_admission([{"kind": "NEWS"}])["issues"], ["UNKNOWN_DATASET_KIND"])

    def test_cost_model_must_belong_to_the_venue_and_instrument_type(self):
        ok = {"source_venue": "SYNTHETIC", "instrument_type": "SPOT"}
        self.assertEqual(q.check_cost_model_provenance(ok, venue="SYNTHETIC", instrument_type="SPOT"), [])
        self.assertEqual(q.check_cost_model_provenance(dict(ok, source_venue="OTHER"), venue="SYNTHETIC", instrument_type="SPOT"),
                         ["COST_MODEL_VENUE_MISMATCH"])
        self.assertEqual(q.check_cost_model_provenance({"instrument_type": "PERPETUAL"}, venue="SYNTHETIC", instrument_type="SPOT"),
                         ["COST_MODEL_INSTRUMENT_TYPE_MISMATCH", "COST_MODEL_VENUE_UNKNOWN"])


if __name__ == "__main__":
    unittest.main()
