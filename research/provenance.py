"""Read-only provenance helpers: file digests, protected-baseline comparison, git state."""
from __future__ import annotations
import subprocess
from pathlib import Path

from .identifiers import sha256_hex


def file_sha256(path) -> str:
    h = Path(path)
    return sha256_hex(h.read_bytes())


def _volatile(path: Path) -> bool:
    """Interpreter caches change between runs and must never enter an artifact or source digest."""
    return "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo")


def hash_tree(root, relpaths_or_dirs) -> dict:
    """SHA-256 of each file (directories are walked); keys are POSIX paths relative to root."""
    root = Path(root)
    out = {}
    for rel in relpaths_or_dirs:
        p = root / rel
        files = [p] if p.is_file() else sorted(q for q in p.rglob("*") if q.is_file() and not _volatile(q))
        for f in files:
            out[f.relative_to(root).as_posix()] = file_sha256(f)
    return dict(sorted(out.items()))


def compare_baseline(baseline: dict, current: dict) -> dict:
    """Differences between two {path: sha256} maps (protected-artifact check)."""
    return {"added": sorted(set(current) - set(baseline)), "removed": sorted(set(baseline) - set(current)),
            "changed": sorted(k for k in baseline.keys() & current.keys() if baseline[k] != current[k])}


def git_state(root) -> dict:
    """HEAD and dirty state via read-only git commands; UNKNOWN when git is unavailable."""
    def run(*args):
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    try:
        head, status = run("rev-parse", "HEAD"), run("status", "--porcelain=v1")
    except (OSError, subprocess.SubprocessError):
        return {"git_head_oid": "UNKNOWN", "source_dirty_state": "UNKNOWN"}
    if head.returncode or status.returncode:
        return {"git_head_oid": "UNKNOWN", "source_dirty_state": "UNKNOWN"}
    return {"git_head_oid": head.stdout.strip(), "source_dirty_state": "DIRTY" if status.stdout.strip() else "CLEAN"}
