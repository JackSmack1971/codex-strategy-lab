"""Run isolation: candidate outputs live only under <repo>/work/research-runs/<run_id>/.

* run ids and artifact names are simple identifiers (no separators, no '..');
* every resolved path must stay inside the run directory (symlinks anywhere along it are refused);
* an existing run directory is never reused or overwritten;
* a protected-artifact baseline (REPORT.md, PREREGISTRATION.md, STAGE_01_HANDOFF.json, results/)
  is hashed before a run and compared after it.
"""
from __future__ import annotations
import os, re
from pathlib import Path

from ..contracts import strict_loads
from ..identifiers import canonical_bytes, digest, sha256_hex
from ..provenance import compare_baseline, hash_tree

PROTECTED = ("REPORT.md", "PREREGISTRATION.md", "STAGE_01_HANDOFF.json", "results")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class IsolationError(Exception):
    code = "ISOLATION"

    def __init__(self, message, code=None):
        super().__init__(message)
        if code:
            self.code = code


def is_link(p) -> bool:
    """True for a symlink or a Windows directory junction (both redirect the path elsewhere)."""
    p = Path(p)
    return p.is_symlink() or bool(getattr(os.path, "isjunction", lambda _p: False)(p))


def assert_no_links(base, target):
    """Refuse when any EXISTING component from `base` (exclusive) down to `target` is a symlink/junction.

    Checked on the lexical path BEFORE anything is created or resolved, because resolve() would silently
    follow the redirect and make an escaped path look like it is still inside the base.
    """
    base, target = Path(os.path.abspath(base)), Path(os.path.abspath(target))
    try:
        rel = target.relative_to(base)
    except ValueError:
        raise IsolationError(f"{target} is not under {base}", "ESCAPE") from None
    cur = base
    if is_link(cur):
        raise IsolationError(f"{cur} is a link", "SYMLINK")
    for part in rel.parts:
        cur = cur / part
        if is_link(cur):
            raise IsolationError(f"{cur} is a symlink or junction", "SYMLINK")
        if not cur.exists():
            break


def protected_baseline(repo) -> dict:
    return hash_tree(repo, [p for p in PROTECTED if (Path(repo) / p).exists()])


def protected_changes(repo, baseline: dict) -> dict:
    return compare_baseline(baseline, protected_baseline(repo))


class RunDir:
    BASES = ("research-runs", "research-reports")

    def __init__(self, repo, run_id: str, base_name: str = "research-runs"):
        if not _NAME.match(run_id) or run_id in (".", ".."):
            raise IsolationError(f"unsafe run_id {run_id!r}", "UNSAFE_NAME")
        if base_name not in self.BASES:
            raise IsolationError(f"unknown base {base_name!r}", "UNSAFE_NAME")
        self.repo = Path(repo).resolve()
        self.base_name = base_name
        base = self.repo / "work" / base_name
        assert_no_links(self.repo, base / run_id)
        self.path = base / run_id
        self.artifacts = {}

    def create(self):
        assert_no_links(self.repo, self.path)
        if self.path.exists() or is_link(self.path):
            raise IsolationError(f"run directory already exists: {self.path.name}", "RUN_EXISTS")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.resolve() != (self.repo / "work" / self.base_name):
            raise IsolationError("run directory resolves outside work/research-runs", "ESCAPE")
        self.path.mkdir()
        return self

    def write(self, name: str, obj) -> str:
        """Write a JSON artifact (canonical bytes). Returns its SHA-256."""
        if not _NAME.match(name) or not name.endswith(".json"):
            raise IsolationError(f"unsafe artifact name {name!r}", "UNSAFE_NAME")
        if name in self.artifacts:
            raise IsolationError(f"artifact {name} already written", "ARTIFACT_EXISTS")
        target = self.path / name
        if target.resolve().parent != self.path.resolve() or target.is_symlink():
            raise IsolationError("artifact path escapes the run directory", "ESCAPE")
        data = canonical_bytes(obj)
        with open(target, "xb") as fh:
            fh.write(data)
        self.artifacts[name] = sha256_hex(data)
        return self.artifacts[name]

    def write_text(self, name: str, text: str) -> str:
        """Write a UTF-8 text artifact (.md or .txt) once; returns its SHA-256."""
        if not _NAME.match(name) or not name.endswith((".md", ".txt")):
            raise IsolationError(f"unsafe artifact name {name!r}", "UNSAFE_NAME")
        if name in self.artifacts:
            raise IsolationError(f"artifact {name} already written", "ARTIFACT_EXISTS")
        target = self.path / name
        if target.resolve().parent != self.path.resolve() or target.is_symlink():
            raise IsolationError("artifact path escapes the run directory", "ESCAPE")
        data = text.encode("utf-8")
        with open(target, "xb") as fh:
            fh.write(data)
        self.artifacts[name] = sha256_hex(data)
        return self.artifacts[name]

    def manifest_hash(self) -> str:
        return digest(dict(sorted(self.artifacts.items())))


def verify_artifacts(run_path, expected_hashes: dict, expected_manifest_hash: str) -> dict:
    """Re-read every artifact from disk and compare with recorded hashes (missing/extra/changed)."""
    run_path = Path(run_path)
    problems = []
    if digest(dict(sorted(expected_hashes.items()))) != expected_manifest_hash:
        problems.append("MANIFEST_HASH_MISMATCH")
    on_disk = {p.name for p in run_path.glob("*") if p.is_file()} if run_path.is_dir() else set()
    for name, sha in sorted(expected_hashes.items()):
        p = run_path / name
        if not p.is_file():
            problems.append(f"MISSING:{name}")
        elif sha256_hex(p.read_bytes()) != sha:
            problems.append(f"HASH_MISMATCH:{name}")
    for extra in sorted(on_disk - set(expected_hashes)):
        problems.append(f"UNRECORDED:{extra}")
    return {"ok": not problems, "problems": problems}


def load_artifact(run_path, name):
    return strict_loads((Path(run_path) / name).read_text(encoding="utf-8"))


def observed_hashes(run_path) -> dict:
    """SHA-256 of every regular file actually on disk in a run directory (for crash reconciliation)."""
    run_path = Path(run_path)
    return {p.name: sha256_hex(p.read_bytes()) for p in sorted(run_path.glob("*")) if p.is_file() and not is_link(p)} \
        if run_path.is_dir() else {}
