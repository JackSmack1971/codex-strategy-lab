#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Reconcile pins against the newly checked-out branch; existing downloads survive.
exec bash "$ROOT/scripts/setup.sh" "$@"
