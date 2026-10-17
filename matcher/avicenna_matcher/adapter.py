"""Canonical patient packet (avicenna.patient-packet/1.1.0) → matcher-internal packet.

PATIENT_MATCHING_FORMAT_STANDARD.md is the hospital contract; the engine evaluates the
internal shape (avicenna.matcher-packet/1.0.0). This adapter is the only bridge and is
*loss-aware*: anything it cannot carry with its full meaning is downgraded toward
UNKNOWN (never toward a definite value) and listed in the adaptation report.

It never invents precision, absence, completeness or review authorization:
  * reduced-precision times keep their precision and time basis (a month stays a month);
  * an interval / inequality value becomes a band that is a *superset* of the original;
  * stage, biomarker and scored_instrument values are not interpretable yet → indeterminate;
  * a completeness assertion is carried only when its authorization matches a pinned
    local authorization policy supplied by the caller; otherwise it is dropped (and the
    matching `not_exists` stays unresolved);
  * unexpected fields are rejected, not given semantics.

Deterministic and offline: no clock, no network, no randomness.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from .errors import StructuralError
from .timing import span_of

CANONICAL_VERSION = "avicenna.patient-packet/1.1.0"
INTERNAL_VERSION = "avicenna.matcher-packet/1.0.0"
ADAPTER_VERSION = "avicenna.adapter/1.0.0"

# Pinned unit alias table (documented-unit → UCUM). Anything else stays unmapped.
UNIT_ALIASES_V1 = {
    "a": "a", "year": "a", "years": "a", "yr": "a", "yrs": "a",
    "mo": "mo", "month": "mo", "months": "mo",
    "wk": "wk", "week": "wk", "weeks": "wk",
    "d": "d", "day": "d", "days": "d",
}

_PRECISION_RE = {
    "year": re.compile(r"^\d{4}$"),
    "month": re.compile(r"^\d{4}-(0[1-9]|1[0-2])$"),
    "day": re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"),
    "second": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"),
}
_BASES = ("shifted_patient_local", "unshifted_verified", "unknown")
_SETTINGS = ("neoadjuvant", "adjuvant", "advanced", "palliative")
_THERAPY_CLASSES = ("chemotherapy", "immunotherapy", "endocrine", "targeted", "adc", "parp_inhibitor",
                    "radiation", "surgery", "transplant", "other", "unknown")
_QUALIFIERS = ("disease_fact_ref", "specimen_ref", "assay", "qtc_method", "reference_low", "reference_high",
               "reference_ucum_code", "interpretation", "confirmation_method")
_UNSUPPORTED_KINDS = ("stage",)

# Pinned instrument registry: (system, code) → (band unit, scale_min, scale_max, step).
# The unit names the instrument, so ECOG and Karnofsky can never be compared with each other.
INSTRUMENT_REGISTRY_VERSION = "avicenna-instruments/1.0.0"
INSTRUMENTS_V1 = {
    ("http://loinc.org", "89247-1"): ("{ECOG}", 0, 4, 1),
    ("http://loinc.org", "89243-0"): ("{Karnofsky}", 0, 100, 10),
}


class _Report:
    def __init__(self) -> None:
        self.losses: List[Dict[str, str]] = []

    def loss(self, where: str, code: str) -> None:
        self.losses.append({"where": where, "code": code})


def _exact(obj: Any, required: Tuple[str, ...], optional: Tuple[str, ...], where: str) -> dict:
    if not isinstance(obj, dict):
        raise StructuralError(f"{where}: expected object")
    missing = [k for k in required if k not in obj]
    extra = sorted(set(obj) - set(required) - set(optional))
    if missing:
        raise StructuralError(f"{where}: missing {missing}")
    if extra:
        raise StructuralError(f"{where}: unexpected fields {extra}")
    return obj


def _finite(x: Any, where: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise StructuralError(f"{where}: expected a finite number")
    return x


def _str(x: Any, where: str) -> str:
    if not isinstance(x, str) or not x:
        raise StructuralError(f"{where}: expected a non-empty string")
    return x


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def _timepoint(tp: Any, where: str) -> Optional[dict]:
    if tp is None:
        return None
    _exact(tp, ("kind", "value", "precision", "time_basis"), (), where)
    if tp["kind"] != "point":
        raise StructuralError(f"{where}: TimePoint kind must be 'point'")
    precision, value, basis = tp["precision"], tp["value"], tp["time_basis"]
    if precision not in _PRECISION_RE or not isinstance(value, str) or not _PRECISION_RE[precision].match(value):
        raise StructuralError(f"{where}: value does not match precision {precision!r}")
    if basis not in _BASES:
        raise StructuralError(f"{where}: unknown time_basis {basis!r}")
    if precision == "year":
        ts = f"{value}-01-01T00:00:00Z"
    elif precision == "month":
        ts = f"{value}-01T00:00:00Z"
    elif precision == "day":
        ts = f"{value}T00:00:00Z"
    else:
        ts = value
    # The timestamp marks the start of the unit; `precision` says it denotes the whole unit.
    out = {"timestamp": ts, "precision": precision, "time_basis": basis}
    if span_of(out) is None:
        raise StructuralError(f"{where}: invalid date {value!r}")
    return out


def _time(t: Any, where: str) -> Optional[dict]:
    if t is None:
        return None
    if isinstance(t, dict) and t.get("kind") == "interval":
        _exact(t, ("kind", "start", "end"), (), where)
        start, end = _timepoint(t["start"], f"{where}.start"), _timepoint(t["end"], f"{where}.end")
        if start is None and end is None:
            raise StructuralError(f"{where}: interval needs at least one bound")
        if start and end and start["time_basis"] != end["time_basis"]:
            raise StructuralError(f"{where}: interval bounds on different time bases")
        return {"start": start, "end": end}
    return _timepoint(t, where)


def _iso(dt) -> str:
    return dt.isoformat(timespec="microseconds") + "Z"


# ---------------------------------------------------------------------------
# Scope (shared by scoped_absence facts and completeness assertions)
# ---------------------------------------------------------------------------

def _scope(scope: Any, where: str, fact_ids: set) -> dict:
    _exact(scope, ("concepts", "disease_setting", "disease_fact_ref", "disease_scope", "time"), (), where)
    concepts = _exact(scope["concepts"], ("system", "registry_version", "classes", "agents"), (), f"{where}.concepts")
    _str(concepts["system"], f"{where}.concepts.system")
    _str(concepts["registry_version"], f"{where}.concepts.registry_version")
    for k in ("classes", "agents"):
        if not isinstance(concepts[k], list) or not all(isinstance(c, str) and c for c in concepts[k]):
            raise StructuralError(f"{where}.concepts.{k}: expected an array of code strings")
    if not concepts["classes"] and not concepts["agents"]:
        raise StructuralError(f"{where}.concepts: unrestricted 'any' scope is not allowed")
    setting = scope["disease_setting"]
    if setting not in _SETTINGS + ("all_settings", "unknown"):
        raise StructuralError(f"{where}: unknown disease_setting {setting!r}")
    if scope["disease_scope"] == "referenced_disease":
        if scope["disease_fact_ref"] not in fact_ids:
            raise StructuralError(f"{where}: referenced_disease needs a resolvable disease_fact_ref")
    elif scope["disease_scope"] != "all_diseases":
        raise StructuralError(f"{where}: unknown disease_scope {scope['disease_scope']!r}")

    out = {
        "scope_type": "reviewed_reconciliation",
        "completeness": "complete",
        "agents": list(concepts["agents"]),
        "classes": list(concepts["classes"]),
        "registry_version": concepts["registry_version"],
        # `unknown` setting clears nothing setting-specific, and never "all settings".
        "settings": ["all_settings"] if setting == "all_settings" else ([] if setting == "unknown" else [setting]),
        "disease_scope": scope["disease_scope"],
    }
    t = scope["time"]
    if not isinstance(t, dict) or t.get("extent") not in ("bounded", "lifetime"):
        raise StructuralError(f"{where}.time: extent must be bounded or lifetime")
    if t["extent"] == "bounded":
        _exact(t, ("extent", "interval"), (), f"{where}.time")
        iv = _time(t["interval"], f"{where}.time.interval")
        if not isinstance(iv, dict) or not iv.get("start") or not iv.get("end"):
            raise StructuralError(f"{where}.time: bounded closure needs both interval bounds")
        # Conservative: covered for certain only from the END of the start unit to the
        # START of the end unit.
        out.update(time_basis="bounded", chronology=iv["start"]["time_basis"],
                   time_start=_iso(span_of(iv["start"]).end), time_end=_iso(span_of(iv["end"]).start))
    else:
        _exact(t, ("extent", "time_basis", "through"), (), f"{where}.time")
        through = _timepoint(t["through"], f"{where}.time.through")
        if through is None or through["time_basis"] != t["time_basis"]:
            raise StructuralError(f"{where}.time: lifetime needs a cutoff on the declared time_basis")
        out.update(time_basis="lifetime", chronology=t["time_basis"], through=_iso(span_of(through).start))
    return out


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

def _unit(raw: Any) -> Optional[str]:
    return UNIT_ALIASES_V1.get(raw.strip().lower()) if isinstance(raw, str) else None


def _band(lo: Optional[float], hi: Optional[float], unit: Optional[str]) -> dict:
    """Integer band that contains [lo, hi] (a superset — sound, possibly less decisive)."""
    out = {"kind": "band",
           "lower_inclusive": None if lo is None else math.floor(lo),
           "upper_inclusive": None if hi is None else math.ceil(hi)}
    if unit is not None:
        out["unit"] = unit
    return out


def _coded(c: Any, where: str) -> dict:
    _exact(c, ("system", "code"), ("display", "normalized"), where)
    src = c
    if c.get("normalized") is not None:
        src = _exact(c["normalized"], ("system", "code"), ("display", "mapping_provenance"), f"{where}.normalized")
    out = {"kind": "coded", "system": _str(src["system"], where), "code": _str(src["code"], where)}
    if isinstance(src.get("display"), str):
        out["display"] = src["display"]
    return out


def _value(v: Any, fact: dict, where: str, report: _Report) -> Tuple[str, Any]:
    """→ (disposition, internal value). disposition: 'known' | 'absence' | 'indeterminate'."""
    if not isinstance(v, dict) or "kind" not in v:
        raise StructuralError(f"{where}: typed value needs a kind")
    kind = v["kind"]
    if kind == "boolean":
        _exact(v, ("kind", "value"), (), where)
        if not isinstance(v["value"], bool):
            raise StructuralError(f"{where}: boolean value must be true/false")
        return "known", v["value"]
    if kind == "integer":
        _exact(v, ("kind", "value"), ("unit",), where)
        if isinstance(v["value"], bool) or not isinstance(v["value"], int):
            raise StructuralError(f"{where}: integer value must be an integer")
        if v.get("unit") is None:
            return "known", _band(v["value"], v["value"], None)
        unit = _unit(v["unit"])
        if unit is None:
            report.loss(where, "unit_not_in_pinned_alias_table")
            return "known", {"kind": "quantity", "value": v["value"], "unit": v["unit"],
                             "normalization_status": "unmapped"}
        return "known", {"kind": "quantity", "value": v["value"], "unit": unit, "normalization_status": "validated"}
    if kind == "interval":
        _exact(v, ("kind", "lower", "upper", "lower_inclusive", "upper_inclusive", "unit"), (), where)
        lo = None if v["lower"] is None else _finite(v["lower"], f"{where}.lower")
        hi = None if v["upper"] is None else _finite(v["upper"], f"{where}.upper")
        if lo is not None and hi is not None and lo > hi:
            raise StructuralError(f"{where}: lower > upper")
        unit = _unit(v["unit"])
        if unit is None:
            report.loss(where, "unit_not_in_pinned_alias_table")
            return "indeterminate", "unsupported_unit"
        exact = all(b is None or float(b).is_integer() for b in (lo, hi)) \
            and v["lower_inclusive"] is not False and v["upper_inclusive"] is not False
        if not exact:
            report.loss(where, "interval_widened_to_integer_band")
        return "known", _band(lo, hi, unit)
    if kind == "coded":
        return "known", _coded({k: x for k, x in v.items() if k != "kind"}, where)
    if kind == "quantity":
        _exact(v, ("kind", "value", "comparator", "unit_original", "ucum_code", "normalization_status"), (), where)
        x = _finite(v["value"], f"{where}.value")
        status = v["normalization_status"]
        if status not in ("validated", "unmapped", "unsupported"):
            raise StructuralError(f"{where}: unknown normalization_status")
        if status == "validated" and not v["ucum_code"]:
            report.loss(where, "validated_without_ucum_code")
            status = "unsupported"
        comp = v["comparator"]
        if comp == "eq":
            unit = v["ucum_code"] if status == "validated" else _str(v["unit_original"], where)
            return "known", {"kind": "quantity", "value": x, "unit": unit, "normalization_status": status}
        if comp not in ("lt", "le", "gt", "ge"):
            raise StructuralError(f"{where}: unknown comparator {comp!r}")
        if status != "validated":
            report.loss(where, "inequality_with_unvalidated_unit")
            return "indeterminate", "unsupported_unit"
        report.loss(where, "inequality_widened_to_integer_band")
        lo, hi = (None, x) if comp in ("lt", "le") else (x, None)
        return "known", _band(lo, hi, v["ucum_code"])
    if kind == "therapy_event":
        _exact(v, ("kind", "agents", "classes", "evidence_kind", "line", "line_context", "intent", "start", "end",
                   "progression_time", "best_response", "disease_fact_ref"), (), where)
        agents = []
        for i, a in enumerate(v["agents"] or []):
            a = _exact(a, ("system", "code"), ("display",), f"{where}.agents[{i}]")
            agents.append({k: _str(a[k], where) for k in ("system", "code")})
        classes = v["classes"] or []
        if any(c not in _THERAPY_CLASSES for c in classes):
            raise StructuralError(f"{where}: unknown therapy class")
        if v["intent"] not in _SETTINGS + ("other", "unknown"):
            raise StructuralError(f"{where}: unknown intent")
        if v["evidence_kind"] not in ("prescription", "billing", "administration", "narrative", "review"):
            raise StructuralError(f"{where}: unknown evidence_kind")
        for k in ("start", "end", "progression_time"):
            _timepoint(v[k], f"{where}.{k}")          # validated; not used for matching yet
        if any(v[k] is not None for k in ("line", "start", "end", "progression_time", "best_response")):
            report.loss(where, "therapy_line_timing_response_not_evaluated")
        return "known", {"kind": "therapy_event", "agents": agents, "classes": list(classes),
                         "intent": v["intent"], "evidence_kind": v["evidence_kind"]}
    if kind == "scoped_absence":
        _exact(v, ("kind", "absent"), (), where)
        if v["absent"] is not True or fact.get("assertion") != "explicit_negative" or fact.get("scope") is None:
            raise StructuralError(f"{where}: scoped_absence needs absent=true, explicit_negative and a Scope")
        return "absence", None
    if kind == "scored_instrument":
        return _scored_instrument(v, where, report)
    if kind == "biomarker":
        _exact(v, ("kind", "marker", "result", "assay", "specimen_ref", "disease_fact_ref"), (), where)
        res = v["result"]
        if not isinstance(res, dict):
            raise StructuralError(f"{where}.result: expected a coded or quantity value")
        if "comparator" in res:
            disposition, inner = _value(dict(res, kind="quantity"), fact, f"{where}.result", report)
        else:
            disposition, inner = "known", _coded(res, f"{where}.result")
        return "biomarker", (disposition, inner, _coded(v["marker"], f"{where}.marker"),
                             {k: v[k] for k in ("assay", "specimen_ref", "disease_fact_ref") if v[k] is not None})
    if kind in _UNSUPPORTED_KINDS:
        report.loss(where, f"{kind}_not_supported_by_matcher")
        return "indeterminate", "unsupported_code"
    raise StructuralError(f"{where}: unknown value kind {kind!r}")


def _scored_instrument(v: dict, where: str, report: _Report):
    if v.get("representation") == "ordinal":
        _exact(v, ("kind", "instrument", "registry_version", "representation", "no_interconversion",
                   "ordinal_code", "ordinal_code_high"), (), where)
        report.loss(where, "ordinal_instrument_not_supported")
        return "indeterminate", "unsupported_code"
    _exact(v, ("kind", "instrument", "registry_version", "representation", "no_interconversion", "value",
               "value_high", "scale_min", "scale_max", "step"), (), where)
    if v["representation"] != "numeric" or v["no_interconversion"] is not True:
        raise StructuralError(f"{where}: numeric scored_instrument with no_interconversion=true required")
    inst = _exact(v["instrument"], ("system", "code"), ("display",), f"{where}.instrument")
    pinned = INSTRUMENTS_V1.get((inst["system"], inst["code"]))
    if v["registry_version"] != INSTRUMENT_REGISTRY_VERSION or pinned is None:
        report.loss(where, "instrument_not_in_pinned_registry")
        return "indeterminate", "unsupported_code"
    unit, lo, hi, step = pinned
    if (v["scale_min"], v["scale_max"], v["step"]) != (lo, hi, step):
        raise StructuralError(f"{where}: scale/step disagree with the pinned instrument registry")
    x = _finite(v["value"], f"{where}.value")
    x_hi = x if v["value_high"] is None else _finite(v["value_high"], f"{where}.value_high")
    for b in (x, x_hi):
        if not (lo <= b <= hi) or (b - lo) % step != 0:
            raise StructuralError(f"{where}: score off the pinned scale/step grid")
    if x > x_hi:
        raise StructuralError(f"{where}: value > value_high")
    return "known", _band(x, x_hi, unit)


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

_FACT_REQUIRED = ("fact_id", "fact_key", "state", "value", "missing_reason", "assertion", "subject_scope",
                  "effective_time", "recorded_time", "evidence", "provenance", "review_status", "generalization",
                  "alternatives", "scope")
_EVIDENCE = ("resource_type", "resource_id", "version_id", "locator", "source_kind", "verification_status")
_PROVENANCE = ("method", "method_version", "model_id", "confidence", "input_fact_refs")


def _evidence(e: Any, where: str) -> dict:
    _exact(e, _EVIDENCE, ("offset_unit", "normalization_version"), where)
    if e["source_kind"] not in ("structured", "lab", "prescription", "billing", "administration", "narrative",
                                "manual_review"):
        raise StructuralError(f"{where}: unknown source_kind")
    if e["verification_status"] not in ("source_assertion", "extracted_candidate", "reviewed"):
        raise StructuralError(f"{where}: unknown verification_status")
    out = dict(e)
    # A locator, never narrative: the matcher must not carry patient text.
    out["source_text"] = f"{e['resource_type']}/{e['resource_id']}@{e['locator']}"
    return out


def _fact(f: Any, i: int, fact_ids: set, report: _Report) -> dict:
    where = f"facts[{i}]"
    _exact(f, _FACT_REQUIRED, ("concept", "qualifiers"), where)
    where = f"fact {f['fact_id']}"
    prov = _exact(f["provenance"], _PROVENANCE, (), f"{where}.provenance")
    out = {
        "fact_id": _str(f["fact_id"], where), "fact_key": _str(f["fact_key"], where),
        "state": f["state"], "value": None, "missing_reason": f["missing_reason"], "assertion": f["assertion"],
        "subject_scope": f["subject_scope"],
        "effective_time": _time(f["effective_time"], f"{where}.effective_time"),
        "recorded_time": _timepoint(f["recorded_time"], f"{where}.recorded_time"),
        "evidence": [_evidence(e, f"{where}.evidence[{j}]") for j, e in enumerate(f["evidence"] or [])],
        "provenance": {"derivation_method": _str(prov["method"], where),
                       "extractor_version": _str(prov["method_version"], where),
                       "model_id": prov["model_id"], "confidence": prov["confidence"],
                       "input_fact_refs": list(prov["input_fact_refs"] or [])},
        "review_status": f["review_status"],
        "generalization": _exact(f["generalization"], ("applied", "constraints"), (), f"{where}.generalization"),
        "alternatives": list(f["alternatives"]),
        "scope": None,
    }
    if f.get("concept") is not None:
        out["concept"] = _coded(f["concept"], f"{where}.concept")
    if f.get("qualifiers") is not None:
        q = f["qualifiers"]
        if not isinstance(q, dict):
            raise StructuralError(f"{where}.qualifiers: expected object")
        for k in sorted(set(q) - set(_QUALIFIERS)):
            report.loss(f"{where}.qualifiers.{k}", "unrecognized_qualifier_ignored")
        out["qualifiers"] = {k: q[k] for k in _QUALIFIERS if k in q}
    if f["scope"] is not None:
        out["scope"] = dict(_scope(f["scope"], f"{where}.scope", fact_ids), scope_type="scoped_absence")
    if f["state"] == "known":
        disposition, value = _value(f["value"], f, f"{where}.value", report)
        if disposition == "biomarker":
            disposition, value, marker, quals = value
            # Identity is (system, code); display is a label, not part of the concept.
            if "concept" in out and ((out["concept"].get("system"), out["concept"].get("code"))
                                     != (marker.get("system"), marker.get("code"))):
                raise StructuralError(f"{where}: Fact.concept disagrees with biomarker marker")
            out["concept"] = marker
            out["qualifiers"] = {**quals, **out.get("qualifiers", {})}
        if disposition == "indeterminate":
            out.update(state="indeterminate", value=None, assertion=None, missing_reason=value)
        else:
            out["value"] = value
    elif f["value"] is not None:
        raise StructuralError(f"{where}: value must be null unless state=known")
    return out


# ---------------------------------------------------------------------------
# Completeness + authorization
# ---------------------------------------------------------------------------

def _authorized(auth: Any, policy: Optional[dict], where: str) -> bool:
    if not isinstance(auth, dict):
        raise StructuralError(f"{where}: authorization must be an object")
    kind = auth.get("kind")
    if kind == "human":
        _exact(auth, ("kind", "reviewer_id", "reviewed_at"), (), where)
        stamp = auth["reviewed_at"]
    elif kind == "approved_process":
        _exact(auth, ("kind", "process_id", "process_version", "approval_ref", "completed_at"), (), where)
        stamp = auth["completed_at"]
    else:
        raise StructuralError(f"{where}: authorization kind must be human or approved_process")
    if not (isinstance(stamp, str) and _PRECISION_RE["second"].match(stamp)):
        raise StructuralError(f"{where}: authorization timestamp must be RFC 3339 with offset")
    if not policy:
        return False
    if kind == "human":
        return auth["reviewer_id"] in (policy.get("human_reviewers") or [])
    key = (auth["process_id"], auth["process_version"], auth["approval_ref"])
    return any((p.get("process_id"), p.get("process_version"), p.get("approval_ref")) == key
               for p in policy.get("approved_processes") or [] if isinstance(p, dict))


def check_authorization_policy(policy: Any) -> Optional[dict]:
    if policy is None:
        return None
    _exact(policy, ("policy_version",), ("human_reviewers", "approved_processes"), "authorization_policy")
    _str(policy["policy_version"], "authorization_policy.policy_version")
    return policy


def _completeness(c: Any, i: int, snapshot_id: str, assessed: set, fact_ids: set,
                  policy: Optional[dict], report: _Report) -> Optional[dict]:
    where = f"coverage.completeness[{i}]"
    _exact(c, ("assertion_id", "fact_key", "scope", "method", "authorization", "evidence", "reconciled_sources",
               "source_snapshot_ref", "reconciliation_policy_version"), (), where)
    where = f"completeness {c['assertion_id']}"
    if c["method"] != "reviewed_reconciliation":
        raise StructuralError(f"{where}: method must be reviewed_reconciliation")
    if not c["evidence"] or not c["reconciled_sources"]:
        raise StructuralError(f"{where}: evidence and reconciled_sources must be non-empty")
    for j, e in enumerate(c["evidence"]):
        _evidence(e, f"{where}.evidence[{j}]")
    if c["source_snapshot_ref"] != snapshot_id:
        raise StructuralError(f"{where}: source_snapshot_ref does not match the packet snapshot")
    if c["fact_key"] not in assessed:
        raise StructuralError(f"{where}: fact_key must be assessed")
    _str(c["reconciliation_policy_version"], where)
    scope = _scope(c["scope"], f"{where}.scope", fact_ids)
    if not _authorized(c["authorization"], policy, f"{where}.authorization"):
        report.loss(where, "completeness_not_authorized_by_local_policy")
        return None
    return {"assertion_id": c["assertion_id"], "fact_key": c["fact_key"], "scope": scope,
            "authorized_under": policy["policy_version"]}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def adapt(packet: Any, authorization_policy: Optional[dict] = None) -> Tuple[dict, dict]:
    """Canonical packet → (internal packet, adaptation report). Raises StructuralError on
    any contract violation; never fills a gap with a guess."""
    _exact(packet, ("schema_version", "packet_id", "patient_ref", "generated_at", "environment", "source_snapshot",
                    "evaluation_context", "facts", "coverage", "warnings"), (), "packet")
    if packet["schema_version"] != CANONICAL_VERSION:
        raise StructuralError(f"adapter supports exactly {CANONICAL_VERSION}")
    policy = check_authorization_policy(authorization_policy)
    report = _Report()
    snap = _exact(packet["source_snapshot"], ("snapshot_id", "ingestion_state", "extractor_version",
                                               "terminology_version"), (), "source_snapshot")
    ec = _exact(packet["evaluation_context"], ("mode", "anchor", "absolute_screening_recency_allowed",
                                                "policy_version"), (), "evaluation_context")
    if ec["mode"] == "shifted_demo" and ec["absolute_screening_recency_allowed"] is not False:
        raise StructuralError("shifted_demo MUST set absolute_screening_recency_allowed = false")
    cov = _exact(packet["coverage"], ("assessed_fact_keys", "unassessed_fact_keys", "completeness"), (), "coverage")
    assessed, unassessed = set(cov["assessed_fact_keys"]), set(cov["unassessed_fact_keys"])
    if assessed & unassessed:
        raise StructuralError("coverage: a key is both assessed and unassessed")
    raw_facts = packet["facts"]
    if not isinstance(raw_facts, list):
        raise StructuralError("facts must be an array")
    fact_ids = {f.get("fact_id") for f in raw_facts if isinstance(f, dict)}
    facts = [_fact(f, i, fact_ids, report) for i, f in enumerate(raw_facts)]
    adapted = [_completeness(c, i, snap["snapshot_id"], assessed, fact_ids, policy, report)
               for i, c in enumerate(cov["completeness"])]
    completeness = [c for c in adapted if c is not None]
    warnings = list(packet["warnings"])
    if snap["ingestion_state"] != "complete" and "partial_ingestion" not in warnings:
        warnings.append("partial_ingestion")

    internal = {
        "schema_version": INTERNAL_VERSION,
        "packet_id": packet["packet_id"], "patient_ref": packet["patient_ref"],
        "generated_at": packet["generated_at"], "environment": packet["environment"],
        "source_snapshot": dict(snap),
        "evaluation_context": {
            "mode": ec["mode"], "anchor": _timepoint(ec["anchor"], "evaluation_context.anchor"),
            "absolute_screening_recency_allowed": ec["absolute_screening_recency_allowed"],
            "policy_version": ec["policy_version"],
        },
        "facts": facts,
        "coverage": {"assessed_fact_keys": list(cov["assessed_fact_keys"]),
                     "unassessed_fact_keys": list(cov["unassessed_fact_keys"]),
                     "completeness": completeness},
        "warnings": warnings,
    }
    return internal, {"adapter_version": ADAPTER_VERSION, "source_schema": CANONICAL_VERSION,
                      "target_schema": INTERNAL_VERSION, "losses": report.losses}
