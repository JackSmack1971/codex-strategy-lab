#!/usr/bin/env bash
# Shared shell helpers. Source from repository scripts, never shell profiles.
LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
LAB_PYTHON="$LAB_ROOT/.venv/bin/python"
export TZ=UTC
export MPLBACKEND=Agg
export MPLCONFIGDIR="${MPLCONFIGDIR:-$LAB_ROOT/.cache/matplotlib}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$LAB_ROOT/.cache/pip}"
export PYTHONUNBUFFERED=1

lab_require_python() {
  if [[ ! -x "$LAB_PYTHON" ]]; then
    printf '%s\n' 'Missing .venv. Run: bash .codex/setup.sh' >&2
    return 1
  fi
}
