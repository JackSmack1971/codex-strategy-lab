import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import shutil
import sys
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

doctor = module('doctor')
prefetch = module('prefetch')

class Response:
    status = 200
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, length): return self.body[:length]

class CloudSetupTests(unittest.TestCase):
    def test_lock_covers_direct_requirements(self):
        direct = doctor.pins(ROOT / 'requirements.txt')
        locked = doctor.pins(ROOT / 'requirements-cloud.lock')
        self.assertTrue(all(locked.get(k) == v for k, v in direct.items()))

    def test_pin_parser_rejects_unbounded_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'requirements.txt'; p.write_text('numpy>=2\n')
            with self.assertRaises(ValueError): doctor.pins(p)

    def test_checksum_probe_rejects_html_success_page(self):
        with patch.object(doctor.urllib.request, 'urlopen', return_value=Response(b'<html>blocked</html>')):
            self.assertFalse(doctor.probe('Binance archive checksum', 'https://example.test')['ok'])

    def test_checksum_probe_accepts_well_formed_digest(self):
        body = b'a' * 64 + b'  archive.zip\n'
        with patch.object(doctor.urllib.request, 'urlopen', return_value=Response(body)):
            self.assertTrue(doctor.probe('Binance archive checksum', 'https://example.test')['ok'])

    def test_network_failure_redacts_exception_message(self):
        error = urllib.error.URLError('https://user:secret@example.test')
        with patch.object(doctor.urllib.request, 'urlopen', side_effect=error):
            result = doctor.probe('Test', 'https://example.test')
        self.assertFalse(result['ok']); self.assertNotIn('secret', json.dumps(result))

    def test_http_denial_is_not_reported_as_reachability_success(self):
        error = urllib.error.HTTPError('https://example.test', 403, 'denied', {}, None)
        with patch.object(doctor.urllib.request, 'urlopen', side_effect=error):
            result = doctor.probe('Test', 'https://example.test')
        self.assertFalse(result['ok']); self.assertEqual(result['http_status'], 403)

    def test_prefetch_scopes_are_complete_and_unique(self):
        hourly = prefetch.build_specs('hourly'); full = prefetch.build_specs('full')
        self.assertEqual(len(hourly), 246); self.assertEqual(len(full), 498)
        self.assertEqual(len(set(full)), len(full))
        self.assertTrue(set(hourly).issubset(set(full)))
        self.assertTrue(all(spec[1] == '1h' for spec in hourly))

    def test_prefetch_matches_frozen_primary_manifest(self):
        manifest = json.loads((ROOT / 'results' / 'data_manifest.json').read_text())
        records = set()
        for r in manifest:
            symbol, interval = r['symbol'], r['interval']
            date = r['url'].rsplit('/', 1)[-1][len(f'{symbol}-{interval}-'):-4]
            frequency = 'monthly' if len(date) == 7 else 'daily'
            records.add((symbol, interval, frequency, date))
        generated = {s for s in prefetch.build_specs('full') if s[1] != '4h'}
        self.assertEqual(generated, records)

    def test_all_shell_entrypoints_parse(self):
        for path in list((ROOT / '.codex').glob('*.sh')) + list((ROOT / 'scripts').glob('*.sh')) + [ROOT / 'scripts' / 'lab']:
            with self.subTest(path=path.name):
                subprocess.run(['bash', '-n', str(path)], check=True, capture_output=True)

    def reproduction_fixture(self, base, complete=True):
        """Tiny fake pipeline to test shell orchestration, never financial results."""
        base.mkdir(); (base / 'scripts').mkdir(); (base / 'results').mkdir()
        for name in ('common.sh', 'reproduce.sh'):
            shutil.copy2(ROOT / 'scripts' / name, base / 'scripts' / name)
        (base / '.venv' / 'bin').mkdir(parents=True)
        (base / '.venv' / 'bin' / 'python').symlink_to(sys.executable)
        (base / '.gitignore').write_text('.venv/\nwork/\n')
        (base / 'scripts' / 'doctor.py').write_text('# Fake doctor for orchestration only\n')
        (base / 'results' / 'sentinel.txt').write_text('preserve historical evidence\n')
        (base / 'REPORT.md').write_text('original report\n')
        count = 492 if complete else 1
        (base / 'download.py').write_text(
            'from pathlib import Path\nimport json\n'
            f"Path('results/data_manifest.json').write_text(json.dumps([{{'status':'verified'}}]*{count}))\n")
        (base / 'verify_data.py').write_text(
            'from pathlib import Path\nimport json\n'
            "Path('results/native_4h_sample_manifest.json').write_text(json.dumps([{'status':'verified'}]*6))\n")
        (base / 'test_lab.py').write_text('import unittest\nclass Fixture(unittest.TestCase):\n    def test_fixture(self): self.assertTrue(True)\n')
        (base / 'run.py').write_text(
            'from pathlib import Path\nimport sys,json\n'
            "Path('results/orchestration.json').write_text(json.dumps({'args':sys.argv[1:]}))\n")
        (base / 'validate_results.py').write_text('pass\n')
        (base / 'make_report.py').write_text("from pathlib import Path\nPath('REPORT.md').write_text('isolated fixture report\\n')\n")
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=base, check=True)
        subprocess.run(['git', 'add', '.'], cwd=base, check=True)
        subprocess.run(['git', '-c', 'user.name=Setup Test', '-c', 'user.email=setup-test@example.invalid', '-c', 'commit.gpgsign=false',
                        'commit', '-qm', 'synthetic orchestration fixture'], cwd=base, check=True)

    def test_reproduction_keeps_root_evidence_and_uses_isolated_head(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / 'repo with spaces'; self.reproduction_fixture(base)
            result = subprocess.run(['bash', str(base / 'scripts' / 'reproduce.sh')],
                                    cwd=d, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual((base / 'REPORT.md').read_text(), 'original report\n')
            self.assertEqual((base / 'results' / 'sentinel.txt').read_text(), 'preserve historical evidence\n')
            runs = list((base / 'work' / 'runs').iterdir()); self.assertEqual(len(runs), 1)
            self.assertEqual((runs[0] / 'REPORT.md').read_text(), 'isolated fixture report\n')
            args = json.loads((runs[0] / 'results' / 'orchestration.json').read_text())['args']
            self.assertIn('--sensitivity', args)
            self.assertFalse((base / 'results' / 'orchestration.json').exists())

    def test_reproduction_refuses_incomplete_archive_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / 'repo'; self.reproduction_fixture(base, complete=False)
            result = subprocess.run(['bash', str(base / 'scripts' / 'reproduce.sh')],
                                    cwd=d, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('refusing backtest', result.stderr)
            runs = list((base / 'work' / 'runs').iterdir())
            self.assertFalse((runs[0] / 'results' / 'orchestration.json').exists())
            self.assertEqual((base / 'REPORT.md').read_text(), 'original report\n')

if __name__ == '__main__': unittest.main()
