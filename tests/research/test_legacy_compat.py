import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from research.contracts import validate
from research.data import qualification as q
from research.data.legacy_ohlcv import ArchiveError, OhlcvSource
from research.provenance import hash_tree
from tests.research import archives as a

REPO = Path(__file__).resolve().parents[2]
START = "2021-11-17T00:00:00Z"


class Adapter(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="research-data-"))
        a.make_archive(self.root, "BTCUSDT", "1h", START, 48)
        self.src = OhlcvSource(self.root)

    def test_reads_without_writing_anything(self):
        before = a.tree(self.root)
        self.src.read_bars("BTCUSDT", "1h"); self.src.manifest("BTCUSDT", "1h"); self.src.close_observations("BTCUSDT", "1h")
        self.assertEqual(a.tree(self.root), before)
        self.assertFalse(list(self.root.rglob("*.pkl")))

    def test_adapter_imports_no_legacy_or_numeric_modules(self):
        code = ("import sys; sys.path.insert(0, %r); import research.data.legacy_ohlcv as m; "
                "print(sorted(x for x in ('lab','download','verify_data','run','make_report','pandas','numpy','urllib.request') if x in sys.modules))") % str(REPO)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tempfile.gettempdir())
        self.assertEqual(out.stdout.strip(), "[]", out.stderr)

    def test_emits_valid_observations_with_honest_timing(self):
        obs = self.src.close_observations("BTCUSDT", "1h", limit=3)
        for o in obs:
            self.assertEqual(validate("observation", o), [])
        o = obs[0]
        self.assertEqual((o["event_at_utc"], o["available_at_utc"]), ("2021-11-17T00:00:00.000000Z", "2021-11-17T01:00:00.000000Z"))
        self.assertIn("absent_reason", o["published_at_utc"])
        self.assertEqual((o["instrument_type"], o["venue"], o["quality_flags"]), ("SPOT", "BINANCE_SPOT", ["ESTIMATED"]))

    def test_microsecond_timestamps_normalised_like_legacy_loader(self):
        root = Path(tempfile.mkdtemp(prefix="research-data-"))
        a.make_archive(root, "BTCUSDT", "1h", START, 5, micros=True)
        self.assertEqual([x["open_ms"] for x in OhlcvSource(root).read_bars("BTCUSDT", "1h")[0]],
                         [x["open_ms"] for x in OhlcvSource(self.root).read_bars("BTCUSDT", "1h")[0]][:5])

    def test_bad_archives_are_refused(self):
        for kw, code in (({"tamper": True}, "CHECKSUM_MISMATCH"), ({"verified": False}, "NOT_VERIFIED")):
            root = Path(tempfile.mkdtemp(prefix="research-data-"))
            a.make_archive(root, "BTCUSDT", "1h", START, 5, **kw)
            with self.assertRaises(ArchiveError) as ctx:
                OhlcvSource(root).read_bars("BTCUSDT", "1h")
            self.assertEqual(ctx.exception.code, code)
        root = Path(tempfile.mkdtemp(prefix="research-data-"))
        p = a.make_archive(root, "BTCUSDT", "1h", START, 5); p.with_suffix(".json").unlink()
        with self.assertRaises(ArchiveError) as ctx:
            OhlcvSource(root).read_bars("BTCUSDT", "1h")
        self.assertEqual(ctx.exception.code, "SIDECAR_MISSING")
        with self.assertRaises(ArchiveError):
            OhlcvSource(root).read_bars("ETHUSDT", "1h")

    def test_duplicate_bars_across_archives_are_refused(self):
        a.make_archive(self.root, "BTCUSDT", "1h", START, 10, name_suffix="2021-12")
        with self.assertRaises(ArchiveError) as ctx:
            self.src.read_bars("BTCUSDT", "1h")
        self.assertEqual(ctx.exception.code, "DUPLICATE_BAR")

    def test_manifest_gaps_and_qualification_use_explicit_tolerances(self):
        root = Path(tempfile.mkdtemp(prefix="research-data-"))
        a.make_archive(root, "BTCUSDT", "1h", START, 48, skip={10, 11, 30})
        m = OhlcvSource(root).manifest("BTCUSDT", "1h")
        self.assertEqual((m["bars"], m["missing_bars"], m["off_grid_bars"]), (45, 3, 0))
        self.assertEqual(m, OhlcvSource(root).manifest("BTCUSDT", "1h"))             # deterministic
        end = "2021-11-18T23:00:00Z"
        self.assertEqual(q.qualify_ohlcv(m, require_start_utc=START, require_end_utc=end, max_missing_bars=3)["status"], "QUALIFIED")
        cert = q.qualify_ohlcv(m, require_start_utc=START, require_end_utc=end, max_missing_bars=2)
        self.assertEqual((cert["status"], cert["issues"]), ("BLOCKED", ["MISSING_BARS_EXCEED_TOLERANCE"]))
        late = q.qualify_ohlcv(m, require_start_utc="2021-11-16T00:00:00Z", require_end_utc="2021-11-20T00:00:00Z", max_missing_bars=9)
        self.assertEqual(late["issues"], ["COVERAGE_ENDS_EARLY", "COVERAGE_STARTS_LATE"])
        self.assertIn("no order-book depth, spread, queue position or cancellation timestamps", cert["limitations"])
        with self.assertRaises(TypeError):
            q.qualify_ohlcv(m, require_start_utc=START, require_end_utc=end)         # tolerance is mandatory


class LegacyEquivalence(unittest.TestCase):
    """The adapter must hand legacy code exactly the data legacy code would have loaded."""

    @classmethod
    def setUpClass(cls):
        try:
            import numpy, pandas  # noqa: F401
            import download, lab  # noqa: F401  (import has no side effects; Market() is never constructed)
        except ImportError as exc:
            raise unittest.SkipTest(f"legacy engine dependencies unavailable: {exc}")

    def test_shipped_adapter_matches_legacy_loader_and_yields_nonzero_signals(self):  # finding M4: invokes the SHIPPED adapter
        import pandas as pd, download, lab
        from research.experiments import legacy_adapter
        protected = ["results", "REPORT.md", "PREREGISTRATION.md", "STAGE_01_HANDOFF.json"]
        before = hash_tree(REPO, protected)
        root = Path(tempfile.mkdtemp(prefix="research-legacy-"))
        a.make_archive(root, "BTCUSDT", "1h", START, 6000, seed=3, quote_volume=1e6)     # liquid enough to pass legacy filters
        original = download.DATA
        download.DATA = root                              # legacy load() would cache a .pkl: redirect to the temp dir
        try:
            legacy = download.load("BTCUSDT", "1h")
        finally:
            download.DATA = original
        source = OhlcvSource(root)
        mine = legacy_adapter.hourly_frame(source, "BTCUSDT")                           # the shipped code path
        pd.testing.assert_frame_equal(mine, legacy, check_freq=False)
        _, plans_legacy, _ = lab.features(legacy)
        plans_mine = legacy_adapter.signal_plans(source, "BTCUSDT")                     # the shipped code path
        total = 0
        for sid in lab.IDS:
            pd.testing.assert_frame_equal(plans_mine[sid], plans_legacy[sid])
            total += int(plans_mine[sid]["signal"].astype(bool).sum())
        self.assertGreater(total, 0, "fixture must exercise nonzero signals or the equivalence check is vacuous")
        self.assertEqual(hash_tree(REPO, protected), before)
        self.assertFalse((REPO / "data").exists() and list((REPO / "data").glob("BTCUSDT-1h.pkl")))


if __name__ == "__main__":
    unittest.main()
