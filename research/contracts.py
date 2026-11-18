"""Contract validation: a documented JSON Schema SUBSET plus semantic checks.

This is NOT a full JSON Schema implementation. Supported keywords (anything else in a
schema file is rejected when the schema loads, so an unsupported constraint can never
be silently ignored):

  structure : type (string or list of string), enum, const, required, properties,
              additionalProperties (boolean or schema), items, minItems, maxItems,
              anyOf, $ref (local "#/$defs/x" or "common.schema.json#/$defs/x")
  scalars   : minLength, maxLength, pattern (re.fullmatch - a trailing newline never matches \"$\"), minimum, maximum
  custom    : x-format = "utc-timestamp"
  annotation: $schema, $defs, title, description, x-schema-version (ignored on validation)

Semantics: type "integer" means a JSON integer (floats such as 1.0 are rejected),
"number" is int or finite float, booleans are never numbers. Absent optional fields
are not the same as the literal "UNKNOWN" (a distinct value allowed only where the
schema says so) and null is never accepted. Unsupported schema_version values are
rejected; no migration exists yet, and any future migration must preserve original bytes.
UTC timestamps must be ISO-8601 with a trailing "Z" and at most microseconds.
"""
from __future__ import annotations
import json, math, re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .identifiers import CanonicalizationError, digest

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
KINDS = ("hypothesis", "preregistration", "observation", "trial", "adjudication", "run_manifest",
         "ledger_event", "objection")

SUPPORTED_KEYWORDS = frozenset({
    "type", "enum", "const", "required", "properties", "additionalProperties", "items",
    "minItems", "maxItems", "anyOf", "$ref", "minLength", "maxLength", "pattern",
    "minimum", "maximum", "x-format"})
ANNOTATION_KEYWORDS = frozenset({"$schema", "$defs", "title", "description", "x-schema-version"})
SCHEMA_DIALECT = "research-schema-subset/1"
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z")

# The Stage 02 test window was consumed (REPORT.md / lab.py WINDOWS['test']).
LEGACY_CONSUMED_WINDOW = ("2025-11-17T00:00:00Z", "2026-11-17T00:00:00Z")


@dataclass(frozen=True, order=True)
class Issue:
    path: str
    code: str
    message: str

    def __str__(self):
        return f"{self.code} {self.path or '/'}: {self.message}"


class ContractError(ValueError):
    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__("; ".join(str(i) for i in self.issues[:5]))

    @property
    def codes(self):
        return sorted({i.code for i in self.issues})


class SchemaError(ValueError):
    """The schema files themselves use an unsupported construct (fail closed)."""


class DuplicateKeyError(ValueError):
    """A JSON object repeats a key; last-wins resolution would hide which value was meant."""


def _no_dup_pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise DuplicateKeyError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def _reject_constant(name):
    raise ValueError(f"non-finite JSON constant {name}")


def strict_loads(text):
    """json.loads that rejects duplicate keys and NaN/Infinity (used for every record and artifact read)."""
    return json.loads(text, object_pairs_hook=_no_dup_pairs, parse_constant=_reject_constant)


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not _TS_RE.fullmatch(value):
        raise ValueError("not a UTC timestamp")
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)


# ---------------------------------------------------------------- schema loading
def _check_schema_node(node, where):
    if not isinstance(node, dict):
        raise SchemaError(f"{where}: schema node must be an object")
    for key, val in node.items():
        if key in ANNOTATION_KEYWORDS:
            continue
        if key not in SUPPORTED_KEYWORDS:
            raise SchemaError(f"{where}: unsupported keyword {key!r}")
        if key == "properties":
            for k, v in val.items():
                _check_schema_node(v, f"{where}/properties/{k}")
        elif key == "items":
            _check_schema_node(val, f"{where}/items")
        elif key == "anyOf":
            for i, v in enumerate(val):
                _check_schema_node(v, f"{where}/anyOf/{i}")
        elif key == "additionalProperties" and isinstance(val, dict):
            _check_schema_node(val, f"{where}/additionalProperties")
        elif key == "x-format" and val != "utc-timestamp":
            raise SchemaError(f"{where}: unsupported x-format {val!r}")
        elif key == "pattern":
            re.compile(val)


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.schema.json"
    schema = strict_loads(path.read_text(encoding="utf-8"))
    if schema.get("$schema") != SCHEMA_DIALECT:
        raise SchemaError(f"{name}: $schema must be {SCHEMA_DIALECT!r}")
    _check_schema_node({k: v for k, v in schema.items() if k != "$defs"}, name)
    for dname, dnode in schema.get("$defs", {}).items():
        _check_schema_node(dnode, f"{name}/$defs/{dname}")
    return schema


def supported_versions(kind: str) -> frozenset:
    return frozenset({load_schema(kind)["x-schema-version"]})


def _resolve(ref: str, current: str):
    """Return (node, defining_schema_name); local refs resolve in the file that holds them."""
    file_part, _, frag = ref.partition("#")
    name = file_part[: -len(".schema.json")] if file_part else current
    schema = load_schema(name)
    prefix = "/$defs/"
    if not frag.startswith(prefix) or frag[len(prefix):] not in schema.get("$defs", {}):
        raise SchemaError(f"unresolvable $ref {ref!r}")
    return schema["$defs"][frag[len(prefix):]], name


# ------------------------------------------------------------------- validation
def _type_ok(inst, t):
    if t == "object": return isinstance(inst, dict)
    if t == "array": return isinstance(inst, list)
    if t == "string": return isinstance(inst, str)
    if t == "boolean": return isinstance(inst, bool)
    if t == "integer": return isinstance(inst, int) and not isinstance(inst, bool)
    if t == "number":
        return isinstance(inst, (int, float)) and not isinstance(inst, bool) and (not isinstance(inst, float) or math.isfinite(inst))
    if t == "null": return inst is None
    raise SchemaError(f"unsupported type {t!r}")


def _validate(inst, node, path, current, out):
    if "$ref" in node:
        target, where = _resolve(node["$ref"], current)
        _validate(inst, target, path, where, out)
        return
    if "anyOf" in node:
        for branch in node["anyOf"]:
            sub = []
            _validate(inst, branch, path, current, sub)
            if not sub:
                break
        else:
            out.append(Issue(path, "ANYOF", "value matches none of the allowed forms"))
            return
    if "type" in node:
        types = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not any(_type_ok(inst, t) for t in types):
            out.append(Issue(path, "TYPE", f"expected {'|'.join(types)}, got {type(inst).__name__}"))
            return
    if "const" in node and (inst != node["const"] or type(inst) is not type(node["const"])):
        out.append(Issue(path, "CONST", f"must equal {node['const']!r}"))
    if "enum" in node and not any(inst == e and type(inst) is type(e) for e in node["enum"]):
        out.append(Issue(path, "ENUM", f"must be one of {node['enum']!r}"))
    if "x-format" in node and isinstance(inst, str):
        try:
            parse_utc(inst)
        except ValueError:
            out.append(Issue(path, "FORMAT", "must be an ISO-8601 UTC timestamp ending in 'Z'"))
    if isinstance(inst, str):
        if "minLength" in node and len(inst) < node["minLength"]:
            out.append(Issue(path, "LENGTH", f"shorter than {node['minLength']}"))
        if "maxLength" in node and len(inst) > node["maxLength"]:
            out.append(Issue(path, "LENGTH", f"longer than {node['maxLength']}"))
        if "pattern" in node and not re.fullmatch(node["pattern"], inst):
            out.append(Issue(path, "PATTERN", f"does not match {node['pattern']}"))
    if _type_ok(inst, "number") and not isinstance(inst, bool):
        if "minimum" in node and inst < node["minimum"]:
            out.append(Issue(path, "RANGE", f"below minimum {node['minimum']}"))
        if "maximum" in node and inst > node["maximum"]:
            out.append(Issue(path, "RANGE", f"above maximum {node['maximum']}"))
    if isinstance(inst, list):
        if "minItems" in node and len(inst) < node["minItems"]:
            out.append(Issue(path, "LENGTH", f"fewer than {node['minItems']} items"))
        if "maxItems" in node and len(inst) > node["maxItems"]:
            out.append(Issue(path, "LENGTH", f"more than {node['maxItems']} items"))
        if "items" in node:
            for i, v in enumerate(inst):
                _validate(v, node["items"], f"{path}/{i}", current, out)
    if isinstance(inst, dict):
        for req in node.get("required", []):
            if req not in inst:
                out.append(Issue(f"{path}/{req}", "REQUIRED", "missing required field"))
        props = node.get("properties", {})
        for k, v in inst.items():
            if k in props:
                _validate(v, props[k], f"{path}/{k}", current, out)
            else:
                ap = node.get("additionalProperties", True)
                if ap is False:
                    out.append(Issue(f"{path}/{k}", "ADDITIONAL_PROPERTY", "field not allowed"))
                elif isinstance(ap, dict):
                    _validate(v, ap, f"{path}/{k}", current, out)


def validate_structure(kind: str, instance) -> list:
    """Structural validation against the schema file only."""
    if kind not in KINDS:
        return [Issue("", "UNKNOWN_KIND", f"unknown contract kind {kind!r}")]
    schema = load_schema(kind)
    if not isinstance(instance, dict):
        return [Issue("", "TYPE", "record must be an object")]
    version = instance.get("schema_version")
    if version not in supported_versions(kind):
        return [Issue("/schema_version", "SCHEMA_VERSION_UNSUPPORTED",
                      f"{version!r} is not in {sorted(supported_versions(kind))}")]
    out = []
    _validate(instance, schema, "", kind, out)
    return sorted(set(out))


# -------------------------------------------------------------- semantic checks
def _ts(rec, *keys):
    cur = rec
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    try:
        return parse_utc(cur)
    except ValueError:
        return None


def _range_issues(rng, path):
    s, e = _ts(rng, "start_utc"), _ts(rng, "end_utc")
    return [Issue(path, "RANGE_ORDER", "start_utc must be before end_utc")] if s and e and s >= e else []


def _overlaps_legacy(rng):
    s, e = _ts(rng, "start_utc"), _ts(rng, "end_utc")
    ls, le = parse_utc(LEGACY_CONSUMED_WINDOW[0]), parse_utc(LEGACY_CONSUMED_WINDOW[1])
    return bool(s and e and s < le and e > ls)


def _split_issues(rec, path):
    out = []
    keymap = {"train": "train", "validation": "validation", "test": "test"}
    if "train_range" in rec:  # trial form
        keymap = {"train": "train_range", "validation": "validation_range", "test": "test_range"}
    names = [n for n in ("train", "validation", "test") if keymap[n] in rec]
    prev = None
    for n in names:
        rng = rec[keymap[n]]
        out += _range_issues(rng, f"{path}/{keymap[n]}")
        if prev:
            pe, cs = _ts(rec[keymap[prev]], "end_utc"), _ts(rng, "start_utc")
            if pe and cs and cs < pe:
                out.append(Issue(f"{path}/{keymap[n]}", "SPLIT_OVERLAP", f"{n} starts before {prev} ends"))
        prev = n
    test = rec.get(keymap["test"])
    if test and rec.get("holdout_class") == "UNTOUCHED" and _overlaps_legacy(test):
        out.append(Issue(f"{path}/holdout_class", "HOLDOUT_CONSUMED",
                         "range overlaps the consumed Stage 02 test window; cannot be UNTOUCHED"))
    return out


def _prereg_economics_issues(rec) -> list:
    """Frozen economics, multiplicity alpha, dataset identity and purge/embargo geometry (blueprint 5.7/8)."""
    out, eco, sp = [], rec["economics"], rec["splits"]
    if any(m <= 0 for m in eco["stress_multipliers"]):
        out.append(Issue("/economics/stress_multipliers", "STRESS_INVALID", "stress multipliers must be > 0"))
    if max(eco["stress_multipliers"]) <= 1:
        out.append(Issue("/economics/stress_multipliers", "STRESS_NOT_STRESSING", "at least one multiplier must exceed 1"))
    if len(set(eco["stress_multipliers"])) != len(eco["stress_multipliers"]):
        out.append(Issue("/economics/stress_multipliers", "DUPLICATE_ID", "stress multipliers must be unique"))
    if eco["evaluation_split"] == "test" and "test" not in sp:
        out.append(Issue("/economics/evaluation_split", "EVALUATION_SPLIT_ABSENT", "evaluation_split test needs splits.test"))
    if sp["holdout_class"] == "UNTOUCHED" and "test" not in sp:
        out.append(Issue("/splits/holdout_class", "UNTOUCHED_WITHOUT_TEST", "an UNTOUCHED holdout needs a preregistered test range"))
    if sp["holdout_class"] == "UNTOUCHED" and eco["evaluation_split"] != "test":
        out.append(Issue("/economics/evaluation_split", "CONFIRMATION_NOT_EVALUATED", "UNTOUCHED confirmation must evaluate the test split"))
    if not 0 < rec["multiplicity"]["alpha"] < 1:
        out.append(Issue("/multiplicity/alpha", "ALPHA_RANGE", "alpha must be strictly between 0 and 1"))
    ds = rec["datasets"]
    if len({d["snapshot_id"] for d in ds}) != len(ds):
        out.append(Issue("/datasets", "DUPLICATE_ID", "snapshot_id values must be unique"))
    need = max(rec["purge"]["label_horizon_s"], rec["purge"]["embargo_s"])
    for a, b in (("train", "validation"), ("validation", "test")):
        if a in sp and b in sp:
            gap = (_ts(sp[b], "start_utc") - _ts(sp[a], "end_utc")).total_seconds()
            if gap < need:
                out.append(Issue(f"/splits/{b}", "PURGE_GAP_TOO_SHORT",
                                 f"gap {a}->{b} is {int(gap)}s; label horizon / embargo needs >= {need}s"))
    return out


def semantic_issues(kind: str, rec: dict) -> list:
    """Cross-field rules the structural schema cannot express. Assumes structure is valid."""
    out = []
    if kind == "observation":
        pub = _ts(rec, "published_at_utc")
        av = _ts(rec, "available_at_utc")
        ing = _ts(rec, "ingested_at_utc")
        ev = _ts(rec, "event_at_utc")
        if ev and pub and pub < ev:
            out.append(Issue("/published_at_utc", "TIME_ORDER", "published_at_utc precedes event_at_utc"))
        if ev and av and av < ev:
            out.append(Issue("/available_at_utc", "TIME_ORDER", "available_at_utc precedes event_at_utc (data cannot be known before the event)"))
        if ev and ing and ing < ev:
            out.append(Issue("/ingested_at_utc", "TIME_ORDER", "ingested_at_utc precedes event_at_utc"))
        if pub and av and av < pub:
            out.append(Issue("/available_at_utc", "TIME_ORDER", "available_at_utc precedes published_at_utc"))
        if av and ing and ing < av:
            out.append(Issue("/ingested_at_utc", "TIME_ORDER", "ingested_at_utc precedes available_at_utc"))
        if pub and ing and ing < pub:
            out.append(Issue("/ingested_at_utc", "TIME_ORDER", "ingested_at_utc precedes published_at_utc"))
    elif kind == "preregistration":
        out += _split_issues(rec.get("splits", {}), "/splits")
        if rec["amendment"] > 0 and not ("amends_sha256" in rec and "amendment_reason" in rec):
            out.append(Issue("/amendment", "AMENDMENT_INCOMPLETE", "amendments need amends_sha256 and amendment_reason"))
        if rec["amendment"] == 0 and ("amends_sha256" in rec or "amendment_reason" in rec):
            out.append(Issue("/amendment", "AMENDMENT_INCOMPLETE", "amendment 0 cannot reference an amended record"))
        if rec["multiplicity"]["family_id"] != rec["family_id"]:
            out.append(Issue("/multiplicity/family_id", "FAMILY_MISMATCH", "must equal family_id"))
        if rec["multiplicity"]["planned_trials"] > rec["research_budget"]["max_trials"]:
            out.append(Issue("/multiplicity/planned_trials", "BUDGET_EXCEEDED", "planned_trials exceeds max_trials"))
        ids = [g["gate_id"] for g in rec["gate_rules"]["gates"]]
        if len(ids) != len(set(ids)):
            out.append(Issue("/gate_rules/gates", "DUPLICATE_ID", "gate_id values must be unique"))
        if not any(g["mandatory"] for g in rec["gate_rules"]["gates"]):
            out.append(Issue("/gate_rules/gates", "NO_MANDATORY_GATE", "at least one mandatory gate is required"))
        out += _prereg_economics_issues(rec)
    elif kind == "trial":
        out += _split_issues(rec, "")
        s, e = _ts(rec, "start_time"), _ts(rec, "end_time")
        if s and e and e < s:
            out.append(Issue("/end_time", "TIME_ORDER", "end_time precedes start_time"))
        if rec["status"] != "STARTED" and "end_time" not in rec:
            out.append(Issue("/end_time", "END_TIME_REQUIRED", f"status {rec['status']} requires end_time"))
        if rec["status"] == "STARTED" and "end_time" in rec:
            out.append(Issue("/end_time", "END_TIME_FORBIDDEN", "STARTED trials have no end_time"))
        if rec["status"] == "FAILED" and "failure_code" not in rec:
            out.append(Issue("/failure_code", "FAILURE_CODE_REQUIRED", "FAILED trials need failure_code"))
        if "test_range" not in rec and rec["test_access_count"] > 0:
            out.append(Issue("/test_access_count", "TEST_ACCESS_WITHOUT_RANGE", "test accessed but no test_range recorded"))
    elif kind == "adjudication":
        ids = [g["gate_id"] for g in rec["gate_results"]]
        if len(ids) != len(set(ids)):
            out.append(Issue("/gate_results", "DUPLICATE_ID", "gate_id values must be unique"))
        if rec["decision"] == "QUALIFIED":
            bad = [g["gate_id"] for g in rec["gate_results"] if g["mandatory"] and g["value"] != "PASS"]
            if bad:
                out.append(Issue("/decision", "QUALIFIED_WITH_NONPASS_GATE", f"mandatory gates not PASS: {bad}"))
            if rec["holdout_integrity"] != "UNTOUCHED":
                out.append(Issue("/decision", "QUALIFIED_WITHOUT_CLEAN_HOLDOUT", "QUALIFIED requires UNTOUCHED holdout_integrity"))
            if rec["economic_estimate"] == "UNKNOWN":
                out.append(Issue("/decision", "QUALIFIED_WITH_UNKNOWN_ESTIMATE", "economic_estimate must be known"))
        for g in rec["gate_results"]:
            if g["value"] == "PASS" and not g["proof_refs"]:
                out.append(Issue("/gate_results", "PROOF_REQUIRED", f"gate {g['gate_id']} PASS needs proof_refs"))
    elif kind == "objection":
        st, res, typ = rec["adjudication_status"], rec.get("test_result"), rec["test_specification"]["type"]
        if st in ("UPHELD", "REFUTED") and (res is None or typ == "MANUAL_POLICY"):
            out.append(Issue("/adjudication_status", "STATUS_WITHOUT_EXECUTED_TEST", "UPHELD/REFUTED need an executed, non-manual test_result"))
        if st == "UNRESOLVED_POLICY" and typ != "MANUAL_POLICY":
            out.append(Issue("/adjudication_status", "POLICY_STATUS_MISMATCH", "UNRESOLVED_POLICY requires a MANUAL_POLICY specification"))
        if st == "PENDING" and res is not None:
            out.append(Issue("/adjudication_status", "STATUS_STALE", "a recorded test_result requires UPHELD or REFUTED"))
        if res and st in ("UPHELD", "REFUTED") and ((st == "UPHELD") != (res["outcome"] == "CLAIM_HOLDS")):
            out.append(Issue("/adjudication_status", "STATUS_OUTCOME_MISMATCH", "status disagrees with the executed outcome"))
    elif kind == "run_manifest":
        s, e = _ts(rec, "start_utc"), _ts(rec, "end_utc")
        if s and e and e < s:
            out.append(Issue("/end_utc", "TIME_ORDER", "end_utc precedes start_utc"))
        if rec["status"] != "STARTED" and "end_utc" not in rec:
            out.append(Issue("/end_utc", "END_TIME_REQUIRED", f"status {rec['status']} requires end_utc"))
        if rec["tests_failed"] > rec["tests_executed"]:
            out.append(Issue("/tests_failed", "COUNT_ORDER", "tests_failed exceeds tests_executed"))
    return out


def validate(kind: str, instance) -> list:
    """Structure, canonical-serializability and semantics. Empty list means valid."""
    issues = validate_structure(kind, instance)
    if issues:
        return issues
    try:
        digest(instance)
    except CanonicalizationError as exc:
        return [Issue(exc.path, "NOT_CANONICALIZABLE", str(exc))]
    return sorted(set(semantic_issues(kind, instance)))


def require_valid(kind: str, instance) -> str:
    """Raise ContractError unless valid; return the canonical SHA-256 of the record."""
    issues = validate(kind, instance)
    if issues:
        raise ContractError(issues)
    return digest(instance)
