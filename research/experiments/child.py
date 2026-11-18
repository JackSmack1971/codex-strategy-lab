"""Child side of the brokered experiment protocol (runs in a separate Python process).

The child holds NO dataset and has NO handle to the run directory or the ledger. It can obtain data only by
asking the parent over stdin/stdout, and the parent counts the request BEFORE it answers. Whatever the
experiment returns is handed back to the parent, which writes the artifacts.

This is a process boundary, not an OS sandbox: the child still runs as the same user and could read
files that exist on disk. Therefore the parent only treats the boundary as ENFORCED for datasets that
exist solely in the parent's memory (see dispatch.run_candidate).
"""
import importlib
import json
import sys


def main():
    repo, spec = sys.argv[1], sys.argv[2]
    proto = sys.stdout
    sys.stdout = sys.stderr                       # stray prints must not corrupt the protocol channel
    sys.path.insert(0, repo)
    module, _, name = spec.partition(":")
    fn = getattr(importlib.import_module(module), name)
    hello = json.loads(sys.stdin.readline())

    class Ctx:
        run_id = hello["run_id"]
        config = hello["config"]
        splits = tuple(hello["splits"])

        def data(self, split):
            proto.write(json.dumps({"op": "data", "split": split}) + "\n")
            proto.flush()
            resp = json.loads(sys.stdin.readline())
            if "error" in resp:
                raise KeyError(resp["error"])
            return resp["rows"]

    result = fn(Ctx()) or {}
    proto.write(json.dumps({"op": "result", "result": result}) + "\n")
    proto.flush()


main()
