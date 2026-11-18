"""Candidate runner. There is NO trading path: no orders, no exchange accounts, no credentials.

run_candidate() takes an already-registered, preregistered hypothesis (ledger state
EXPERIMENT_PENDING) and a trial record, then:
  1. refuses out-of-scope requests (order placement, credentials, live trading);
  2. creates a fresh isolated run directory under work/research-runs/;
  3. snapshots the protected-artifact baseline;
  4. records the trial STARTED (and a run manifest) in the ledger BEFORE running anything;
  5. runs the experiment with a context that only exposes the preregistered data splits
     (every test-split read is counted);
  6. records COMPLETED or FAILED with artifact hashes, re-checks the protected baseline,
     and records the terminal run manifest.
A crash between 4 and 6 leaves the trial STARTED, which the ledger blocks and reconciles explicitly.
It never resumes or overwrites a run; it never changes lab.py, run.py or results/.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, tempfile, threading
from pathlib import Path

from ..identifiers import derived_id, digest
from ..provenance import file_sha256, git_state, hash_tree
from . import isolation

# Keys are matched as whole tokens so research vocabulary (order_book_levels, accounting_basis) is not refused.
_FORBIDDEN_KEY_TOKENS = frozenset({"apikey", "secret", "secrets", "credential", "credentials", "passphrase", "withdraw",
                                   "withdrawal", "broker", "brokerage", "placeorder", "neworder", "orderid", "ordertype"})
_FORBIDDEN_KEY_PAIRS = ({"api", "key"}, {"place", "order"}, {"new", "order"}, {"exchange", "account"}, {"live", "trading"},
                        {"account", "id"}, {"account", "number"}, {"leverage", "live"}, {"order", "type"}, {"order", "id"},
                        {"order", "side"}, {"order", "size"}, {"order", "qty"}, {"order", "quantity"})
_FORBIDDEN_TEXT = re.compile(
    r"(place\s+(an?\s+)?(order|trade)|live\s+trad|market\s+order|limit\s+order|api[\s_-]?key|"
    r"secret\s+key|exchange\s+account|withdraw|send\s+funds|connect\s+(my\s+)?(wallet|exchange)|"
    r"(submit|send|execute|enter|open)\s+(an?\s+|the\s+)?(market\s+|limit\s+)?(buy|sell|order|trade)\b|"
    r"\b(market|limit)\s+(buy|sell)\b|\b(buy|sell)\s+[\d.,]+\s*[A-Za-z]{2,6}\b|execute\s+(the\s+)?trade)", re.I)


def _forbidden_key(key: str) -> bool:
    tokens = [t for t in re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", str(key)).lower()) if t]
    return bool(set(tokens) & _FORBIDDEN_KEY_TOKENS) or any(pair <= set(tokens) for pair in _FORBIDDEN_KEY_PAIRS)


CODE_ROOT = Path(__file__).resolve().parents[2]      # where `research` (and importable experiments) live; NOT the run repo


class UnsupportedScope(Exception):
    code = "UNSUPPORTED_SCOPE"


class ProtectedArtifactError(Exception):
    code = "PROTECTED_MODIFIED"


def check_scope(request) -> None:
    """Raise UnsupportedScope if a request/config asks for trading, orders or credentials."""
    def walk(x, path="$"):
        if isinstance(x, dict):
            for k, v in x.items():
                if _forbidden_key(k):
                    raise UnsupportedScope(f"{path}.{k}: trading/credential key is out of scope (research only)")
                walk(v, f"{path}.{k}")
        elif isinstance(x, (list, tuple)):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")
        elif isinstance(x, str) and _FORBIDDEN_TEXT.search(x):
            raise UnsupportedScope(f"{path}: request mentions order placement, live trading or credentials (out of scope)")
    walk(request)


class Broker:
    """Counts every split read BEFORE serving it. The only way brokered experiment code obtains data."""

    def __init__(self, splits: dict, datasets: dict):
        self._splits, self._datasets = splits, datasets
        self.test_accesses = 0

    def serve(self, split):
        if split not in ("train", "validation", "test"):
            raise KeyError(split)
        if split not in self._splits or split not in self._datasets:
            raise KeyError(f"split {split!r} is not preregistered / not provided")
        if split == "test":
            self.test_accesses += 1
        return self._datasets[split]()


class RunContext:
    """In-process context. Python cannot hide objects from in-process code, so this mode is ADVISORY:
    runs are recorded IN_PROCESS_UNENFORCED and can never be adjudicated as an untouched confirmation."""

    def __init__(self, run_id: str, broker: Broker, config: dict):
        self.run_id, self.config, self._broker = run_id, config, broker

    def data(self, split: str):
        return self._broker.serve(split)

    @property
    def test_accesses(self):
        return self._broker.test_accesses


def _run_brokered(repo, spec, broker, run_id, config, timeout):
    """Run `module:function` in a child process that can only reach data through the counting broker."""
    child = Path(__file__).resolve().with_name("child.py")
    with tempfile.TemporaryDirectory(prefix="research-child-") as scratch:
        env = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT", "PATH", "TEMP", "TMP", "LANG", "LC_ALL", "PYTHONHASHSEED")}
        proc = subprocess.Popen([sys.executable, "-B", str(child), str(CODE_ROOT), spec], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=scratch, env=env)
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        try:
            proc.stdin.write(json.dumps({"run_id": run_id, "config": config, "splits": sorted(broker._splits)}) + "\n")
            proc.stdin.flush()
            for line in proc.stdout:
                msg = json.loads(line)
                if msg["op"] == "data":
                    try:
                        reply = {"rows": broker.serve(msg["split"])}
                    except KeyError as exc:
                        reply = {"error": str(exc)}
                    proc.stdin.write(json.dumps(reply) + "\n")
                    proc.stdin.flush()
                elif msg["op"] == "result":
                    proc.stdin.close()
                    proc.wait(timeout=30)
                    return msg["result"]
            raise RuntimeError(f"experiment process ended without a result (exit {proc.wait()}): "
                               f"{(proc.stderr.read() or '')[-400:]}")
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    pipe.close()
                except OSError:
                    pass


def _manifest(trial, run, repo, *, status, end_utc, dataset_digests, config, enforcement, tests=(0, 0), clock):
    git = git_state(repo)
    lock = Path(repo) / "requirements-cloud.lock"
    rec = {"schema_version": "1.0.0", "run_id": trial["run_id"], "recorded_at": clock(),
           "git_head_oid": git["git_head_oid"], "source_dirty_state": git["source_dirty_state"],
           "source_digests": hash_tree(repo, [p for p in ("research", "scripts/research.py") if (Path(repo) / p).exists()]),
           "prereg_sha256": trial["preregistration_sha256"], "dataset_manifest_digests": sorted(dataset_digests),
           "experiment_configuration_digest": digest(config), "python_version": sys.version.split()[0],
           "dependency_lock_sha256": file_sha256(lock) if lock.is_file() else "UNKNOWN",
           "runner_command_redacted": "research dispatch <arguments redacted>", "execution_surface": "LOCAL_SCRIPT",
           "codex_version_if_observed": "UNKNOWN", "effective_permissions_if_observed": "UNKNOWN",
           "network_policy_if_observed": "UNKNOWN", "start_utc": trial["start_time"],
           "artifact_hashes": dict(sorted(run.artifacts.items())), "tests_executed": tests[0],
           "tests_failed": tests[1], "status": status, "data_access_enforcement": enforcement}
    if status != "STARTED":
        rec["end_utc"] = end_utc
    return rec


def run_candidate(ledger, repo, trial: dict, experiment, datasets: dict, actor: dict, *, config: dict,
                  dataset_digests=(), request=None, reason="candidate run", in_memory_datasets=False, timeout=300):
    """Execute one candidate. Returns {"trial": record, "run_dir": Path, "status": str, "error": str|None}.

    `experiment` is a callable (in-process, ADVISORY access accounting) or a "module:function" string
    (child process; every data read goes through the counting broker). The access boundary is recorded as
    ENFORCED (IN_MEMORY_BROKERED) only for a child process whose datasets exist solely in memory
    (`in_memory_datasets=True`, asserted by the trusted caller). File-backed data stays readable by a
    same-user child, so that mode is FILE_BACKED_UNENFORCED and can never support an untouched confirmation.
    """
    check_scope(request or {})
    check_scope(config)
    enforcement = ("IN_PROCESS_UNENFORCED" if callable(experiment)
                   else "IN_MEMORY_BROKERED" if in_memory_datasets else "FILE_BACKED_UNENFORCED")
    repo = Path(repo)
    view = ledger.view()
    if trial["trial_id"] in view.trials:
        raise isolation.IsolationError("trial already recorded; reconcile instead of re-running", "TRIAL_EXISTS")
    h = view.hyp.get((trial["hypothesis_id"], trial["hypothesis_version"]))
    if h is None or h["prereg"] is None:
        raise isolation.IsolationError("hypothesis has no frozen preregistration", "PREREG_REQUIRED")
    run = isolation.RunDir(repo, trial["run_id"]).create()
    baseline = isolation.protected_baseline(repo)
    subj = {"hypothesis_id": trial["hypothesis_id"], "hypothesis_version": trial["hypothesis_version"]}
    t_subj = dict(subj, trial_id=trial["trial_id"])
    key = lambda what: derived_id(what, f"{trial['trial_id']}:{trial['run_id']}")
    started = dict(trial, status="STARTED")
    ledger.append("TRIAL_RECORDED", subject=t_subj, payload=started, actor=actor, reason=reason,
                  idempotency_key=key("trial-start"))
    ledger.append("RUN_RECORDED", subject=dict(subj, run_id=trial["run_id"]), actor=actor, reason=reason,
                  idempotency_key=key("run-start"),
                  payload=_manifest(trial, run, repo, status="STARTED", end_utc=None, dataset_digests=dataset_digests,
                                    config=config, enforcement=enforcement, clock=ledger.clock))
    broker = Broker(h["prereg"]["splits"], datasets)
    status, error, failure_code = "COMPLETED", None, None
    try:
        if callable(experiment):
            result = experiment(RunContext(trial["run_id"], broker, config)) or {}
        else:
            result = _run_brokered(repo, experiment, broker, trial["run_id"], config, timeout) or {}
        run.write("metrics.json", result.get("metrics", {}))
        for name, obj in sorted(result.get("artifacts", {}).items()):
            run.write(name, obj)
    except Exception as exc:            # a failed run is evidence, not an exception to swallow silently
        status, error, failure_code = "FAILED", f"{type(exc).__name__}: {exc}", "E_EXPERIMENT_EXCEPTION"
    changes = isolation.protected_changes(repo, baseline)
    if any(changes.values()):
        status, failure_code = "FAILED", "PROTECTED_MODIFIED"
        error = f"protected artifacts changed: {changes}"
    end = ledger.clock()
    final = dict(started, status=status, end_time=end, test_access_count=broker.test_accesses)
    if run.artifacts:
        final["artifact_manifest_hash"] = run.manifest_hash()
    if failure_code:
        final["failure_code"] = failure_code
    ledger.append("TRIAL_RECORDED", subject=t_subj, payload=final, actor=actor, reason=reason,
                  idempotency_key=key(f"trial-end-{status}"))
    ledger.append("RUN_RECORDED", subject=dict(subj, run_id=trial["run_id"]), actor=actor, reason=reason,
                  idempotency_key=key(f"run-end-{status}"),
                  payload=_manifest(trial, run, repo, status=status, end_utc=end, dataset_digests=dataset_digests,
                                    config=config, enforcement=enforcement, clock=ledger.clock))
    if failure_code == "PROTECTED_MODIFIED":
        raise ProtectedArtifactError(error)
    return {"trial": final, "run_dir": run.path, "status": status, "error": error}
