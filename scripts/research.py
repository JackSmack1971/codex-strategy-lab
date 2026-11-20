#!/usr/bin/env python3
"""Research workbench CLI (PROPOSED project tool; research only, no trading, no network).

Ledger data lives under <repo>/work/research (git-ignored). The root is resolved and must stay
inside <repo>/work; symlink or '..' escapes are refused. The actor must be stated explicitly.
Exit codes: 0 ok | 2 usage (including a ledger root that escapes <repo>/work) | 3 rejected (contract or rule) |
4 ledger corrupt / needs reconcile / locked / evidence unverifiable on this machine.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research import ledger as lg                      # noqa: E402
from research.contracts import ContractError, strict_loads  # noqa: E402
from research.evidence_store import EvidenceError, EvidenceStore  # noqa: E402
from research.experiments import isolation            # noqa: E402
from research.prereg import freeze                     # noqa: E402

CATEGORIES = ["HUMAN", "CODEX", "CLAUDE_CODE", "SCRIPT", "REVIEWER_AGENT"]

# Navigation metadata only: never dynamically import or dispatch from this catalog.
CLI_EFFECTS = {
    "register": "active_state_write",
    "prereg-freeze": "active_state_write",
    "advance": "active_state_write",
    "abort": "active_state_write",
    "evidence-put": "active_state_write",
    "status": "read_only",
    "ledger-verify": "read_only",
    "reconcile-tail": "active_state_write",
    "reconcile-trials": "active_state_write",
    "capability-list": "read_only",
}

PYTHON_CAPABILITIES = (
    ("research/data/legacy_ohlcv.py", "OhlcvSource", "read_only",
     "OHLCV only; inspect archive provenance and data availability."),
    ("research/data/qualification.py", "qualify_ohlcv", "derived_only",
     "Requires manifest and explicit preregistered tolerances; does not record admission."),
    ("research/data/qualification.py", "microstructure_admission", "derived_only",
     "Requires actual admitted order-book evidence; OHLCV cannot substitute."),
    ("research/experiments/dispatch.py", "run_candidate", "active_state_write",
     "Supervisor only; registered dispatch, frozen prerequisites and isolation checks required."),
    ("research/experiments/pipeline.py", "adjudicate_trial", "active_state_write",
     "Supervisor only for recording; record_it=False is provisional, not recorded adjudication."),
    ("research/reporting/render.py", "build_report", "derived_only",
     "Requires evidence-linked inputs; does not prove a disposition was recorded."),
    ("research/validation/adversarial.py", "execute", "derived_only",
     "Requires actual admissible evidence; does not establish reviewer independence."),
)


def capability_catalog():
    """List known interfaces, without reading data or claiming runtime availability."""
    commands = [
        {"name": name, "interface": "cli", "command": f"scripts/lab research {name}",
         "effect": effect, "owner": "supervisor_only" if effect == "active_state_write" else "authorized_reader"}
        for name, effect in sorted(CLI_EFFECTS.items())
    ]
    modules = [
        {"name": symbol, "interface": "python", "source": source, "effect": effect,
         "owner": "supervisor_only" if effect == "active_state_write" else "authorized_reader",
         "limitations": limitations}
        for source, symbol, effect, limitations in PYTHON_CAPABILITIES
    ]
    return {"schema_version": 1, "status": "navigation_only",
            "authorization": "not_evaluated", "runtime_availability": "not_evaluated",
            "capabilities": commands + modules}


class RootRefused(Exception):
    pass


def resolve_root(repo: Path, value) -> Path:
    """Validate the lexical path (no symlink/junction component, no '..' escape) BEFORE resolving or creating anything."""
    repo = Path(repo)
    base = repo / "work"
    root = (Path(value) if value else base / "research")
    root = Path(os.path.abspath(root if root.is_absolute() else repo / root))
    try:
        root.relative_to(Path(os.path.abspath(base)))
    except ValueError:
        raise RootRefused(f"refusing ledger root outside {base}: {root}") from None
    try:
        isolation.assert_no_links(repo, root)
    except isolation.IsolationError as exc:
        raise RootRefused(f"refusing ledger root: {exc}") from None
    return root


def load_json(path):
    p = Path(path)
    if not p.is_file():
        raise ContractError([lg.Issue(str(path), "NOT_A_FILE", "input must be an existing regular file")])
    return strict_loads(p.read_text(encoding="utf-8"))


def parser():
    ap = argparse.ArgumentParser(prog="scripts/lab research", description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="ledger directory (must be inside <repo>/work)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def actor(p):
        p.add_argument("--actor-category", required=True, choices=CATEGORIES)
        p.add_argument("--actor-id", required=True)
        p.add_argument("--reason", required=True)
    p = sub.add_parser("register", help="register a hypothesis version from JSON"); p.add_argument("--file", required=True); actor(p)
    p = sub.add_parser("prereg-freeze", help="freeze or amend a preregistration from JSON"); p.add_argument("--file", required=True); actor(p)
    p = sub.add_parser("advance", help="record a workflow transition")
    p.add_argument("--hypothesis-id", required=True); p.add_argument("--version", type=int, required=True)
    p.add_argument("--to", required=True); p.add_argument("--evidence", action="append", default=[]); actor(p)
    p = sub.add_parser("abort", help="record a STARTED trial as ABORTED")
    p.add_argument("--trial-id", required=True); p.add_argument("--failure-code", default="E_ABORTED"); actor(p)
    p = sub.add_parser("evidence-put", help="store a JSON evidence bundle (content-addressed) and print its digest")
    p.add_argument("--file", required=True)
    sub.add_parser("capability-list", help="list research interfaces without accessing the ledger or data")
    p = sub.add_parser("status", help="summarise ledger state (read-only)")
    p = sub.add_parser("ledger-verify", help="verify chain and rules (read-only)")
    p = sub.add_parser("reconcile-tail", help="explicitly resolve an incomplete/unterminated tail"); actor(p)
    p = sub.add_parser("reconcile-trials", help="mark STARTED trials INTERRUPTED"); actor(p)
    return ap


def run(argv, repo=REPO, out=None):
    out = out or sys.stdout
    args = parser().parse_args(argv)
    emit = lambda obj: print(json.dumps(obj, indent=2, sort_keys=True), file=out)
    try:
        root = resolve_root(Path(repo), args.root)
    except RootRefused as exc:
        emit({"error": "ROOT_REFUSED", "message": str(exc)})
        return 2
    if args.cmd == "capability-list":
        emit(capability_catalog()); return 0
    led = lg.Ledger(root)
    try:
        if args.cmd == "evidence-put":
            sha = EvidenceStore(root).put(load_json(args.file))
            emit({"sha256": sha}); return 0
        if args.cmd == "ledger-verify":
            rep = led.verify(); emit(rep)
            return 0 if rep["status"] == "OK" and rep["evidence"]["status"] == "VERIFIED" else 4
        if args.cmd == "status":
            sc = led.scan(); rep = sc.as_dict()
            rep["hypotheses"] = {f"{k[0]}@{k[1]}": {"state": v["state"], "prereg_sha256": v["prereg_sha"]}
                                 for k, v in sc.view.hyp.items()}
            rep["trials"] = {t["trial_id"]: t["status"] for t in sc.view.trials.values()}
            rep["family_trial_counts"] = {k: len(v) for k, v in sc.view.family_trials.items()}
            rep["unfinished_trials"] = sc.view.unfinished_trials()
            rep["evidence_status"] = rep["evidence"]["status"]
            emit(rep)
            return 0 if sc.status == "OK" and rep["evidence"]["status"] == "VERIFIED" else 4
        who = {"category": args.actor_category, "id": args.actor_id}
        if args.cmd == "register":
            ev, created = led.register_hypothesis(load_json(args.file), who, args.reason)
        elif args.cmd == "prereg-freeze":
            ev, created = freeze(led, load_json(args.file), who, args.reason)
        elif args.cmd == "advance":
            ev, created = led.transition(args.hypothesis_id, args.version, args.to, who, args.reason, args.evidence)
        elif args.cmd == "abort":
            cur = led.view().trials.get(args.trial_id)
            if cur is None:
                raise lg.RuleViolation("unknown trial", "UNKNOWN_TRIAL")
            new = dict(cur, status="ABORTED", end_time=led.clock(), failure_code=args.failure_code)
            subject = {"hypothesis_id": cur["hypothesis_id"], "hypothesis_version": cur["hypothesis_version"],
                       "trial_id": args.trial_id}
            ev, created = led.append("TRIAL_RECORDED", subject=subject, payload=new, actor=who, reason=args.reason,
                                     idempotency_key=lg.derived_id("abort", args.trial_id))
        elif args.cmd == "reconcile-tail":
            emit(led.reconcile_tail(who, args.reason)); return 0
        elif args.cmd == "reconcile-trials":
            emit({"reconciled": led.reconcile_interrupted_trials(who, args.reason)}); return 0
        emit({"created": created, "seq": ev["seq"], "event_hash": ev["event_hash"], "event_type": ev["event_type"],
              "resulting_state": ev.get("resulting_state")})
        return 0
    except (ContractError, lg.RuleViolation, lg.StaleState) as exc:
        codes = exc.codes if isinstance(exc, ContractError) else [exc.code]
        emit({"error": "REJECTED", "codes": codes, "message": str(exc)})
        return 3
    except (lg.LedgerCorrupt, lg.LedgerNeedsReconcile, lg.LockHeld) as exc:
        emit({"error": exc.code, "message": str(exc)})
        return 4
    except (EvidenceError, isolation.IsolationError) as exc:
        emit({"error": "REJECTED", "codes": [exc.code], "message": str(exc)})
        return 3
    except (OSError, ValueError) as exc:
        emit({"error": "INPUT", "message": str(exc)})
        return 3


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
