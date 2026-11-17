#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cd "$LAB_ROOT"

offline=0
if [[ "${1:-}" == '--offline' ]]; then offline=1; shift; fi
if [[ $# -ne 0 ]]; then
  printf '%s\n' 'Usage: bash .codex/setup.sh [--offline]' >&2
  exit 2
fi
base="${STRATEGY_LAB_PYTHON:-python3.12}"
if ! command -v "$base" >/dev/null 2>&1; then
  base=python3
fi
if ! "$base" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3,12))' 2>/dev/null; then
  printf '%s\n' 'Python 3.12 is required. Select it in the Cloud image or set STRATEGY_LAB_PYTHON to its executable.' >&2
  exit 1
fi
command -v git >/dev/null || { printf '%s\n' 'git is required by run provenance and isolated reproduction.' >&2; exit 1; }
mkdir -p .cache/codex-cloud .cache/matplotlib .cache/pip work
if [[ ! -e .venv ]]; then "$base" -m venv .venv; fi
if [[ ! -x "$LAB_PYTHON" ]] || ! "$LAB_PYTHON" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3,12))'; then
  printf '%s\n' 'Existing .venv is incompatible. Move it aside and rerun setup; it has not been deleted.' >&2
  exit 1
fi
pip_args=(--disable-pip-version-check --only-binary=:all: -r requirements-cloud.lock)
if [[ $offline -eq 1 ]]; then
  # Offline maintenance verifies the existing environment without any install.
  "$LAB_PYTHON" scripts/doctor.py
else
  "$LAB_PYTHON" -m pip install "${pip_args[@]}"
fi
"$LAB_PYTHON" -m pip check
"$LAB_PYTHON" -m unittest -v test_lab tests.test_cloud_setup
prefetch="${STRATEGY_LAB_PREFETCH:-none}"
case "$prefetch" in
  none) ;;
  hourly|full)
    if [[ $offline -eq 1 ]]; then printf '%s\n' 'Prefetch is disabled by --offline.'; else "$LAB_PYTHON" scripts/prefetch.py "$prefetch"; fi ;;
  *) printf '%s\n' 'STRATEGY_LAB_PREFETCH must be none, hourly or full.' >&2; exit 2 ;;
esac
doctor_args=(--write-state)
if [[ $offline -eq 0 ]]; then doctor_args+=(--network); fi
"$LAB_PYTHON" scripts/doctor.py "${doctor_args[@]}"
printf '%s\n' 'Codex Cloud setup ready. Run commands through scripts/lab; shell activation is not required.'
