#!/usr/bin/env bash
# Explicit opt-in research run. Never executed by setup, maintenance or CI.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
lab_require_python
cd "$LAB_ROOT"
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != '--sensitivity' ) ]]; then
  printf '%s\n' 'Usage: scripts/lab reproduce [--sensitivity]' >&2
  exit 2
fi
"$LAB_PYTHON" "$LAB_ROOT/scripts/doctor.py" --network
if ! git cat-file -e HEAD:scripts/reproduce.sh 2>/dev/null; then
  printf '%s\n' 'Commit the Cloud setup files first; isolated reproduction uses committed HEAD.' >&2
  exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  printf '%s\n' 'Tracked edits are not included: this run uses committed HEAD only.' >&2
fi
mkdir -p work/runs
run_dir="$(mktemp -d "$LAB_ROOT/work/runs/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
git worktree add --detach "$run_dir" HEAD
printf 'Isolated research run retained at: %s\n' "$run_dir"
cd "$run_dir"
# Copy only checksum-backed raw cache; never reuse derived pickle caches or links.
if [[ -d "$LAB_ROOT/data/raw" ]]; then
  "$LAB_PYTHON" - "$LAB_ROOT/data/raw" "$run_dir/data/raw" <<'PY'
import shutil,sys
from pathlib import Path
Path(sys.argv[2]).parent.mkdir(parents=True,exist_ok=True)
shutil.copytree(sys.argv[1],sys.argv[2])
PY
fi
"$LAB_PYTHON" download.py
"$LAB_PYTHON" - <<'PY'
import json
from pathlib import Path
rows=json.loads(Path('results/data_manifest.json').read_text())
if len(rows)!=492 or any(r.get('status')!='verified' for r in rows):
    raise SystemExit('Primary data incomplete or unverified: refusing backtest.')
PY
"$LAB_PYTHON" verify_data.py
"$LAB_PYTHON" - <<'PY'
import json
from pathlib import Path
rows=json.loads(Path('results/native_4h_sample_manifest.json').read_text())
if len(rows)!=6 or any(r.get('status')!='verified' for r in rows):
    raise SystemExit('Native 4H sample incomplete or unverified: refusing backtest.')
PY
"$LAB_PYTHON" -m unittest -v test_lab
# Parameter stability is part of make_report.py's required inputs.
"$LAB_PYTHON" -W ignore::FutureWarning run.py --sensitivity
"$LAB_PYTHON" validate_results.py
"$LAB_PYTHON" make_report.py
printf 'Completed isolated report: %s/REPORT.md\n' "$run_dir"
