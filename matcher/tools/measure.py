#!/usr/bin/env python3
"""P7 — corpus measurement harness (MATCHER_BUILD_PLAN P7; answers MATCHER_DESIGN §10.2, §13.7).

Inputs are TRIAL data only — the CTIS / CT.gov SQLite catalogs and CriteriaPacks — plus
synthetic patient packets generated here. Patient data is never read.

Two measurements, deliberately kept apart:

  A. Corpus census (``--ctis`` / ``--ctgov``): no atomizer exists yet, so real criteria are
     classified *lexically*. Every number from this part is a PROXY (construct demand and a
     best-case ceiling), not matcher output.

  B. Pack measurement (``--packs DIR``): exact. Each pack is run through the real pipeline
     against a synthetic best-case "witness" packet (facts constructed to satisfy every
     inclusion and clear every exclusion), once per completeness scenario:

       S0 none      — chart holds only positive findings; no negatives, no completeness
       S1 negatives — documented (unreviewed, unscoped) explicit negatives exist
       S2 reviewed  — reviewed-reconciliation completeness covering each absence query

     The spread S0→S2 is the eligible_pending_review yield sensitivity to completeness.

Output is a deterministic Markdown report (no timestamps).
"""

from __future__ import annotations

import argparse
import copy
import json
import functools
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from avicenna_matcher import pipeline  # noqa: E402
from avicenna_matcher.errors import StructuralError  # noqa: E402
from avicenna_matcher.validator import validate  # noqa: E402

SCENARIOS = ("S0", "S1", "S2")
SCENARIO_LABEL = {
    "S0": "no negatives / no completeness (launch default)",
    "S1": "documented explicit negatives, no reviewed completeness",
    "S2": "reviewed-reconciliation completeness",
}

# ===========================================================================
# A. Corpus census (lexical proxy)
# ===========================================================================


@dataclass
class Trial:
    trial_id: str
    source: str
    priority: bool                      # Motol / Homolka site
    criteria: List[Tuple[str, str]] = field(default_factory=list)   # (inclusion|exclusion, text)


FORBIDDEN_PATH_PARTS = ("rakathon-dataset",)


def _guard(path: str) -> str:
    """Refuse anything under the patient-data tree, whatever the caller passes."""
    resolved = str(Path(path).resolve())
    if any(part in resolved for part in FORBIDDEN_PATH_PARTS):
        raise SystemExit(f"refusing to read {path}: patient data is out of scope for P7")
    return path


def _ro(path: str) -> sqlite3.Connection:
    _guard(path)
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def load_ctis(path: str) -> List[Trial]:
    out = []
    with _ro(path) as c:
        rows = c.execute("SELECT ct_number, inclusions_json, exclusions_json, sites_json "
                         "FROM trials_retrieve ORDER BY ct_number").fetchall()
    for ct, inc, exc, sites in rows:
        s = (sites or "").lower()
        t = Trial(ct, "ctis", "motol" in s or "homolka" in s)
        for kind, blob in (("inclusion", inc), ("exclusion", exc)):
            for text in json.loads(blob or "[]") or []:
                if isinstance(text, str) and text.strip():
                    t.criteria.append((kind, " ".join(text.split())))
        out.append(t)
    return out


_BULLET = re.compile(r"^(\d+[.)]|\*|-|•|[a-z][.)])\s+")
_HEADER = re.compile(r"^\s*(inclusion|exclusion)\s+criteria\b", re.I)


def split_ctgov(text: str) -> List[Tuple[str, str]]:
    """Split CT.gov eligibility text into top-level criteria; indented sub-items and
    continuation lines are folded into their parent item."""
    kind, items = None, []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        h = _HEADER.match(raw)
        if h:
            kind = h.group(1).lower()
            continue
        if kind is None:
            continue
        indented = raw[:1].isspace()
        line = raw.strip().replace("\\", "")
        if not indented and _BULLET.match(line):
            items.append([kind, _BULLET.sub("", line, count=1)])
        elif items and items[-1][0] == kind and (indented or not line.endswith(":")):
            items[-1][1] += " " + _BULLET.sub("", line, count=1)
    return [(k, " ".join(t.split())) for k, t in items if t.strip()]


def load_ctgov(path: str) -> List[Trial]:
    out = []
    with _ro(path) as c:
        rows = c.execute("SELECT nct_id, eligibility_text, motol_related, homolka_related "
                         "FROM ctgov_studies ORDER BY nct_id").fetchall()
    for nct, text, motol, homolka in rows:
        out.append(Trial(nct, "ctgov", bool(motol or homolka), split_ctgov(text)))
    return out


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


LEX = {
    "procedural": _rx(r"\b(informed consent|consent form|willing|willingness|able to comply|comply with|"
                      r"agree(s)? to|ability to understand|capable (of|to) understand)\b"),
    "investigator_judgment": _rx(r"\b(investigator'?s?|physician'?s?|in the opinion of|judg(e)?ment|discretion|"
                                 r"considered (by|clinically)|clinically (significant|relevant))\b"),
    "relative_to_reference": _rx(r"\b(ULN|LLN|upper limit of (the )?normal|lower limit of (the )?normal|"
                                 r"(institutional|laboratory) (upper|lower) limit)\b"),
    "derived_value": _rx(r"\b(creatinine clearance|CrCl|e?GFR|Cockcroft|CKD-EPI|MDRD|body mass index|BMI|"
                         r"QTc[FB]?|body surface area|IPI)\b"),
    "guarded": _rx(r"\((?=[^)]*[≤≥<>])[^)]*\b(in|for) (patients|subjects|participants)\b|"
                   r"\b(in|for) (patients|subjects|participants|those) (with|who|aged|older|younger)\b|"
                   r"\bunless\b|\bexcept\b|\bwith the exception\b|\bif\b"),
    "jurisdiction": _rx(r"\b(for|in) (participants|patients|subjects|sites?|women|men)\s+(in|from|enrolled in)\s+"
                        r"[A-Z][a-z]+|\b(country|countries|local (regulations?|requirements?|law|label)|"
                        r"where (required|applicable)|per local|locally approved|national (law|regulation))\b"),
    "cross_ref": _rx(r"\b(inclusion|exclusion) criteri(on|a)\s*(#|no\.?|number)?\s*\d|\bcriterion\s*#?\s*\d"),
    "measurement": _rx(r"[≤≥<>]|\b(at least|greater than|less than|more than|or more|or less|minimum|maximum|"
                       r"between)\b[^.;]{0,30}\d|\d\s*(years?|mg|g/dl|mmol|[µu]mol|ml/min|%|x\s*10|×\s*10|/mm3|"
                       r"/[µu]l|kg|msec|ms)\b|\b(ECOG|Karnofsky|WHO performance|Lansky)\b"),
    "therapy_absence": _rx(r"\b(no|without|not)\s+(prior|previous|previously)\b|\bnaive\b|\b(prior|previous)\s+"
                           r"(treatment|therapy|therapies|chemotherapy|systemic|line|regimen|exposure|use)\b|"
                           r"\b(treated|treatment) with\b|\breceived\b|\bwashout\b"),
    "condition_absence": _rx(r"\b(history of|known|active|concurrent|current|ongoing|presence of|uncontrolled|"
                             r"diagnos(is|ed)|infection|disease|malignan|metasta|pregnan|breast-?feeding|lactat|"
                             r"allerg|hypersensitiv|disorder|syndrome|within \d+\s*(days|weeks|months|years))"),
    "inclusion_negation": _rx(r"^\s*(no|absence of|without|never)\b|\bno (history|known|evidence|active|current)\b"),
}


def classify(kind: str, text: str) -> Dict[str, bool]:
    return dict(_classify(kind, text))


@functools.lru_cache(maxsize=None)
def _classify(kind: str, text: str) -> Tuple[Tuple[str, bool], ...]:
    f = {k: bool(rx.search(text)) for k, rx in LEX.items()}
    words = len(text.split())
    sentences = len(re.findall(r"[.;:](\s|$)", text))
    f["complex"] = words > 60 or sentences >= 3 or len(re.findall(r"\band/or\b", text, re.I)) >= 2 \
        or bool(re.search(r"\b(as defined by|as per local|e\.g\.|such as|including but not limited)\b", text, re.I))
    if kind == "inclusion":
        # an inclusion needs absence proof only when it is a negation ("no prior X")
        neg = f["inclusion_negation"] or bool(re.search(r"\b(no|without|not)\s+(prior|previous)", text, re.I))
        f["absence_therapy"] = neg and f["therapy_absence"]
        f["absence_condition"] = neg and not f["absence_therapy"]
    else:
        # an exclusion is cleared by FALSE: unless it is a pure measurement, that means
        # proving a condition/exposure is absent
        pure_measure = f["measurement"] and not (f["condition_absence"] or f["therapy_absence"])
        # any other exclusion is cleared only by proving the excluded state absent (§5.4),
        # whether or not a keyword like "history of" is present
        f["absence_therapy"] = (not pure_measure) and f["therapy_absence"]
        f["absence_condition"] = (not pure_measure) and not f["absence_therapy"] and not f["procedural"]
    f["procedural_only"] = f["procedural"] and not (f["measurement"] or f["absence_therapy"] or f["absence_condition"])
    f["opaque_proxy"] = (f["complex"] or f["investigator_judgment"]) and not f["procedural_only"]
    f["guarded"] = f["guarded"] or f["jurisdiction"]
    f["four_constructs"] = f["relative_to_reference"] or f["derived_value"] or f["guarded"] \
        or f["absence_therapy"] or f["absence_condition"]
    return tuple(sorted(f.items()))


ATOMIZERS = {
    "conservative": "compound and judgment criteria become opaque_text",
    "optimistic": "compound criteria atomized faithfully; judgment criteria stay opaque_text",
    "judgment_atomized": "everything atomized; 'clinically significant X' read as presence of X",
}


def best_case_state(trial: Trial, scenario: str, atomizer: str, why: Optional[Counter] = None) -> str:
    """Lexical ceiling for a best-case patient (every measurable fact present and favourable).
    Mirrors §8: opaque hard exclusion → manual_review; un-evaluable ratio > 1/3 → manual_review;
    any unresolved hard → needs_chart_review."""
    if not trial.criteria:
        return "no_criteria"
    hard = unres = unevaluable = 0
    severity = False
    for kind, text in trial.criteria:
        f = classify(kind, text)
        if f["procedural_only"]:
            continue
        hard += 1
        opaque = {"conservative": f["investigator_judgment"] or f["complex"],
                  "optimistic": f["investigator_judgment"],
                  "judgment_atomized": False}[atomizer]
        if opaque:
            unres += 1
            unevaluable += 1
            severity = severity or kind == "exclusion"
            continue
        cleared = {
            "S0": not (f["absence_therapy"] or f["absence_condition"]),
            "S1": not f["absence_therapy"],
            "S2": True,
        }[scenario]
        if not cleared:
            unres += 1
    if hard and (severity or unevaluable / hard > 1 / 3):
        if why is not None:
            why["severity" if severity else "ratio"] += 1
        return "manual_review"
    return "needs_chart_review" if unres else "eligible_pending_review"


def corpus_stats(trials: List[Trial]) -> Dict[str, Any]:
    labels = ["four_constructs", "relative_to_reference", "derived_value", "guarded", "jurisdiction", "absence_therapy",
              "absence_condition", "cross_ref", "measurement", "procedural_only", "investigator_judgment",
              "complex", "opaque_proxy"]
    per_kind = {k: Counter() for k in ("inclusion", "exclusion")}
    total = Counter()
    for t in trials:
        for kind, text in t.criteria:
            f = classify(kind, text)
            per_kind[kind]["n"] += 1
            total["n"] += 1
            for lab in labels:
                if f[lab]:
                    per_kind[kind][lab] += 1
                    total[lab] += 1
    yields = {}
    for subset, ts in (("all", [t for t in trials if t.criteria]),
                       ("priority", [t for t in trials if t.criteria and t.priority])):
        for atz in ATOMIZERS:
            for sc in SCENARIOS:
                why: Counter = Counter()
                c = Counter(best_case_state(t, sc, atz, why) for t in ts)
                yields[(subset, atz, sc)] = (c, len(ts), why)
    return {
        "trials": len(trials),
        "trials_with_criteria": sum(1 for t in trials if t.criteria),
        "priority": sum(1 for t in trials if t.priority and t.criteria),
        "labels": labels, "per_kind": per_kind, "total": total, "yields": yields,
    }


# ===========================================================================
# B. Pack measurement (exact, real pipeline) with synthetic witness packets
# ===========================================================================

ANCHOR = "2026-01-15T00:00:00Z"
FACT_TIME = "2026-01-14T00:00:00Z"
_INVERT = {"lt": "ge", "le": "gt", "gt": "le", "ge": "lt", "eq": "ne", "ne": "eq"}


class WitnessFail(Exception):
    pass


class Witness:
    """Accumulates constraints for a best-case synthetic patient; realised into packet facts."""

    def __init__(self):
        self.num: Dict[str, Dict[str, Any]] = {}      # key -> {unit, lo, lo_inc, hi, hi_inc, ne:set}
        self.cat: Dict[str, Any] = {}
        self.site: Dict[str, Any] = {}
        self.absence: Dict[str, Optional[dict]] = {}   # key -> not_exists scope (None = existential)
        self.positive_scope: Dict[str, Optional[str]] = {}
        self.refs: Dict[str, str] = {}                 # reference key -> unit
        self.ref_quals: Dict[str, set] = {}            # fact key -> {reference_high|reference_low}

    def copy(self) -> "Witness":
        return copy.deepcopy(self)

    # --- constraint primitives -------------------------------------------------
    def _num(self, key, unit, comparator, t):
        if key in self.cat or key in self.absence:
            raise WitnessFail(key)
        c = self.num.setdefault(key, {"unit": unit, "lo": None, "lo_inc": True, "hi": None, "hi_inc": True, "ne": set()})
        if c["unit"] != unit:
            raise WitnessFail(key)
        if comparator in ("gt", "ge", "eq"):
            inc = comparator != "gt"
            if c["lo"] is None or t > c["lo"] or (t == c["lo"] and not inc):
                c["lo"], c["lo_inc"] = t, inc
        if comparator in ("lt", "le", "eq"):
            inc = comparator != "lt"
            if c["hi"] is None or t < c["hi"] or (t == c["hi"] and not inc):
                c["hi"], c["hi_inc"] = t, inc
        if comparator == "ne":
            c["ne"].add(t)
        if c["lo"] is not None and c["hi"] is not None and (
                c["lo"] > c["hi"] or (c["lo"] == c["hi"] and not (c["lo_inc"] and c["hi_inc"]))):
            raise WitnessFail(key)

    def _cat(self, key, value, site=False):
        store = self.site if site else self.cat
        if not site and (key in self.num or key in self.absence):
            raise WitnessFail(key)
        if key in store and store[key] != value:
            raise WitnessFail(key)
        store[key] = value

    def _absent(self, key, scope):
        if key in self.cat or key in self.num or key in self.positive_scope:
            raise WitnessFail(key)
        if key in self.absence and self.absence[key] != scope:
            # merge: keep the stricter (scoped) query
            scope = scope or self.absence[key]
        self.absence[key] = scope

    # --- atom → constraint ----------------------------------------------------
    def want_atom(self, atom: dict, v: bool, packs_ctx: dict):
        p = atom["predicate_type"]
        if p in ("simple_comparison", "derived_value"):
            return self._want_cmp(atom, v)
        if p == "relative_to_reference":
            comp = atom["comparator"] if v else _INVERT[atom["comparator"]]
            mult = atom["threshold"]["value"] if isinstance(atom["threshold"], dict) else atom["threshold"]
            limit = mult * 100 + (atom.get("reference_offset") or 0)
            if atom.get("reference_qualifier"):
                self.ref_quals.setdefault(atom["fact_key"], set()).add(atom["reference_qualifier"])
            else:
                self.refs[atom["reference_key"]] = "U"
            return self._num(atom["fact_key"], "U", comp, limit)
        if p == "guarded_case":
            cases = atom.get("cases") or []
            site = atom.get("guard_scope") == "site_context"
            if cases:
                self._cat(atom["guard_fact_key"], cases[0]["value"], site)
                return self.want_atom(cases[0]["predicate"], v, packs_ctx)
            return self.want_atom(atom["else"], v, packs_ctx)
        if p == "applicability_gate":
            return self._cat(atom["gate_fact_key"], atom["gate_value"], atom.get("guard_scope") == "site_context")
        if p == "not_exists":
            scope = atom.get("scope") or {}
            if v:
                return self._absent(atom["fact_key"], scope)
            if atom["fact_key"] in self.absence:
                raise WitnessFail(atom["fact_key"])
            self.positive_scope[atom["fact_key"]] = scope.get("setting")
            return None
        raise WitnessFail(p)   # procedural, criterion_ref: no constructible witness

    def _want_cmp(self, atom, v):
        key, comp, t = atom["fact_key"], atom.get("comparator"), atom.get("threshold")
        relation = atom.get("relation")
        if relation == "within_days_before_anchor" and atom.get("quantifier") not in ("exists", "latest"):
            raise WitnessFail("window_quantifier")   # matcher returns UNKNOWN regardless of facts
        existential = relation in ("any_history", "ever") or (
            relation == "within_days_before_anchor" and atom.get("quantifier") == "exists")
        if existential and not v:
            return self._absent(key, None)
        if comp is None:
            raise WitnessFail(key)
        if isinstance(t, dict) and "value" in t and isinstance(t["value"], (int, float)):
            return self._num(key, t.get("unit"), comp if v else _INVERT[comp], t["value"])
        if isinstance(t, (int, float)) and not isinstance(t, bool):
            return self._num(key, None, comp if v else _INVERT[comp], t)
        if comp == "in_set" and isinstance(t, list) and t:
            return self._cat(key, t[0] if v else _other(t[0]))
        if comp in ("eq", "ne"):
            want_equal = v if comp == "eq" else not v
            if isinstance(t, bool):
                return self._cat(key, t if want_equal else (not t))
            return self._cat(key, t if want_equal else _other(t))
        raise WitnessFail(key)

    def want_criterion(self, crit: dict, packs_ctx: dict) -> "Witness":
        """Return a witness extended so that the criterion is satisfied/clear."""
        if crit["completeness_note"] == "opaque_text":
            raise WitnessFail("opaque")
        atoms = crit["atoms"]
        gates = [a for a in atoms if a["predicate_type"] == "applicability_gate"]
        body = [a for a in atoms if a["predicate_type"] != "applicability_gate"]
        if not body:
            raise WitnessFail("no atoms")
        target = crit["criterion_type"] == "inclusion"
        op = (crit.get("logic") or {}).get("op") or ("all" if len(body) == 1 else None)
        if op in (None, "custom"):
            raise WitnessFail("logic")
        w = self.copy()
        for g in gates:
            w.want_atom(g, True, packs_ctx)
        if op == "not":
            op, target = "all", not target
        need_all = (op == "all") == target       # all→TRUE / any→FALSE: every atom must hit target
        if need_all:
            for a in body:
                w.want_atom(a, target, packs_ctx)
            return w
        for a in body:                            # any→TRUE / all→FALSE: one atom suffices
            trial = w.copy()
            try:
                trial.want_atom(a, target, packs_ctx)
                return trial
            except WitnessFail:
                continue
        raise WitnessFail("no branch")

    # --- realisation ------------------------------------------------------------
    def facts(self, scenario: str) -> List[dict]:
        facts = []

        def add(key, value, assertion="positive", review="unreviewed", scope=None, qualifiers=None):
            facts.append({**({"qualifiers": qualifiers} if qualifiers else {}),
                "fact_id": f"w{len(facts)}", "fact_key": key, "state": "known", "value": value,
                "missing_reason": None, "assertion": assertion, "subject_scope": "patient",
                "effective_time": {"timestamp": FACT_TIME}, "recorded_time": None,
                "evidence": [{"source_text": "synthetic witness"}],
                "provenance": {"derivation_method": "synthetic", "extractor_version": "measure/0"},
                "review_status": review, "generalization": {"applied": False, "constraints": []},
                "alternatives": [], "scope": scope,
            })

        for key, c in sorted(self.num.items()):
            x = _pick(c)
            if c["unit"] is None:
                add(key, {"kind": "band", "lower_inclusive": x, "upper_inclusive": x})
            else:
                # one shared synthetic specimen links every measurement to its reference (§7 linkage)
                q = {"specimen_ref": WITNESS_SPECIMEN}
                for rq in sorted(self.ref_quals.get(key, ())):
                    q[rq], q["reference_ucum_code"] = 100, c["unit"]
                add(key, {"kind": "quantity", "value": x, "unit": c["unit"], "normalization_status": "validated"},
                    qualifiers=q)
        for key, unit in sorted(self.refs.items()):
            add(key, {"kind": "quantity", "value": 100, "unit": unit, "normalization_status": "validated"},
                qualifiers={"specimen_ref": WITNESS_SPECIMEN})
        for key, v in sorted(self.cat.items(), key=lambda kv: kv[0]):
            if isinstance(v, dict):
                add(key, {"kind": "coded", "system": v.get("system", "local"), "code": v.get("code")})
            else:
                # current-state values (incl. a measured `false`, e.g. negative pregnancy test)
                # are positive findings, present in every scenario
                add(key, v)
        for key, setting in sorted(self.positive_scope.items()):
            add(key, True, scope={"scope_type": "setting", "setting": setting} if setting else None)
        for key, scope in sorted(self.absence.items(), key=lambda kv: kv[0]):
            if scenario == "S0":
                continue
            if scenario == "S1":
                add(key, None, assertion="explicit_negative")
                continue
            scope = scope or {}
            cov = {"scope_type": "reviewed_reconciliation", "completeness": "complete", "time_basis": "lifetime",
                   "time_start": "1900-01-01T00:00:00Z", "time_end": ANCHOR,
                   "agents": list(scope.get("concepts") or []),
                   "settings": [scope["setting"]] if scope.get("setting") else ["all_settings"]}
            add(key, None, assertion="explicit_negative", review="reviewed", scope=cov)
        return facts


WITNESS_SPECIMEN = "witness-specimen"


def _other(t):
    """A value of the same type as t that is not equal to it."""
    if isinstance(t, dict):
        return {"system": t.get("system", "local"), "code": "__other__"}
    return "__other__"


def _pick(c) -> float:
    lo, hi = c["lo"], c["hi"]
    if lo is not None and hi is not None:
        x = lo if lo == hi else (lo + hi) / 2
    elif lo is not None:
        x = lo if c["lo_inc"] else lo + 1
    elif hi is not None:
        x = hi if c["hi_inc"] else hi - 1
    else:
        x = 1
    while x in c["ne"]:
        x += 0.5
    return x


def _packet(facts: List[dict]) -> dict:
    return {
        "schema_version": "avicenna.matcher-packet/1.0.0", "packet_id": "pkt-witness",
        "patient_ref": "synthetic-witness", "generated_at": ANCHOR, "environment": "synthetic_demo",
        "source_snapshot": {"snapshot_id": "witness", "ingestion_state": "complete",
                            "extractor_version": "measure/0", "terminology_version": "none"},
        "evaluation_context": {"mode": "prescreen_real_time", "anchor": {"timestamp": ANCHOR},
                               "absolute_screening_recency_allowed": False, "policy_version": "measure-p7"},
        "facts": facts,
        "coverage": {"assessed_fact_keys": [], "unassessed_fact_keys": [], "completeness": []},
        "warnings": [],
    }


def build_witness(pack: dict, arm_id: Optional[str] = None) -> Tuple[Witness, List[str]]:
    """Best-case patient for one arm (a patient only needs to fit one arm, §8.3)."""
    w, failed = Witness(), []
    for crit in pack["criteria"]:
        if crit["hardness"] != "hard" or crit["arm_scope"] not in (None, arm_id):
            continue
        try:
            w = w.want_criterion(crit, {})
        except WitnessFail:
            failed.append(crit["criterion_id"])
    return w, failed


_BEST = ["eligible_pending_review", "needs_chart_review", "manual_review", "ineligible"]


def measure_pack(pack: dict) -> Dict[str, Any]:
    """Run the real pipeline once per (arm witness × scenario); keep the best trial verdict."""
    witnesses = [build_witness(pack, arm["arm_id"]) for arm in pack["arms"]]
    failed = sorted(set.intersection(*(set(f) for _, f in witnesses)))
    out = {"trial_id": pack["trial_id"], "pack_id": pack["pack_id"],
           "criteria_completeness": pack["criteria_completeness"], "no_witness": failed,
           "states": {}, "eval_states": {}, "arm_states": {}, "forced_complete": {}}
    variants = [("as_is", pack)]
    if pack["criteria_completeness"] == "partial":
        forced = copy.deepcopy(pack)
        forced["criteria_completeness"] = "complete"
        variants.append(("forced", forced))
    for sc in SCENARIOS:
        best: Dict[str, Tuple[int, dict]] = {}
        for i, (w, _) in enumerate(witnesses):
            pt = _packet(w.facts(sc))
            ctx = {"site_context": dict(w.site)} if w.site else None
            for name, pk in variants:
                r = pipeline.evaluate(pk, pt, ctx, result_id=f"measure-{sc}-{i}", generated_at=ANCHOR)
                rank = _BEST.index(r["trial_eligibility_state"])
                if name not in best or rank < best[name][0]:
                    best[name] = (rank, r)
        r = best["as_is"][1]
        out["states"][sc] = r["trial_eligibility_state"]
        out["eval_states"][sc] = Counter(c["evaluation_state"] for c in r["criterion_results"])
        out["arm_states"][sc] = Counter(a["arm_eligibility_state"] for a in r["per_arm_results"])
        if "forced" in best:
            out["forced_complete"][sc] = best["forced"][1]["trial_eligibility_state"]
    return out


def pack_stats(packs: List[dict]) -> Dict[str, Any]:
    notes, ptypes, logic = Counter(), Counter(), Counter()
    n_crit = 0
    for p in packs:
        for c in p["criteria"]:
            n_crit += 1
            notes[c["completeness_note"]] += 1
            logic[(c.get("logic") or {}).get("op") or ("single" if len(c["atoms"]) <= 1 else "unspecified")] += 1
            for a in c["atoms"]:
                ptypes[a["predicate_type"]] += 1
    results = [measure_pack(p) for p in packs]
    return {"packs": len(packs), "criteria": n_crit, "notes": notes, "ptypes": ptypes, "logic": logic,
            "results": results}


def load_packs(directory: str) -> List[dict]:
    packs = []
    for path in sorted(Path(_guard(directory)).glob("*.json")):
        pk = json.loads(path.read_text(encoding="utf-8"))
        try:
            validate(pk, "criteria_pack")
        except StructuralError as e:
            raise SystemExit(f"{path}: invalid pack: {e}")
        packs.append(pk)
    return packs


# ===========================================================================
# Report
# ===========================================================================

def _pct(n, d) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "n/a"


def render(corpus: Optional[Dict[str, Any]], packs: Optional[Dict[str, Any]]) -> str:
    L = ["# P7 — Matcher measurement report", ""]
    L += ["Trial data only (CTIS / CT.gov catalogs, CriteriaPacks) + synthetic packets. No patient data.", ""]
    if corpus:
        t, pk = corpus["total"], corpus["per_kind"]
        L += ["## A. Corpus census — lexical PROXY (no atomizer yet)", "",
              f"{corpus['trials']} trials, {corpus['trials_with_criteria']} with criteria text "
              f"({corpus['priority']} Motol/Homolka); {t['n']} criteria "
              f"({pk['inclusion']['n']} inclusion / {pk['exclusion']['n']} exclusion).", "",
              "### §10.2 — how many real criteria need the four constructs", "",
              "| signal | all | inclusion | exclusion |", "|---|---|---|---|"]
        names = {"four_constructs": "**any of the four §5 constructs**",
                 "relative_to_reference": "§5.1 relative-to-reference (ULN/LLN)",
                 "derived_value": "§5.2 derived value (CrCl, eGFR, BMI, QTc…)",
                 "guarded": "§5.3 guarded / exception (`in patients with`, `unless`, jurisdiction)",
                 "jurisdiction": "§7.3 jurisdiction-specific (`participants in France`, `local regulations`)",
                 "absence_therapy": "§5.4 absence — therapy-scoped (`no prior X`)",
                 "absence_condition": "§5.4 absence — condition / state (any non-measurement exclusion)",
                 "cross_ref": "§6.4.5 cross-criterion reference",
                 "measurement": "plain measurement / threshold",
                 "procedural_only": "procedural only (consent, willingness)",
                 "investigator_judgment": "investigator judgment / clinical significance",
                 "complex": "compound (> 60 words, ≥ 3 clauses, `e.g.`/`as defined by`)",
                 "opaque_proxy": "**likely `opaque_text`** (compound or judgment)"}
        for lab in corpus["labels"]:
            L.append(f"| {names[lab]} | {_pct(t[lab], t['n'])} | {_pct(pk['inclusion'][lab], pk['inclusion']['n'])} "
                     f"| {_pct(pk['exclusion'][lab], pk['exclusion']['n'])} |")
        L += ["", "### §13.7 — best-case `eligible_pending_review` ceiling by completeness scenario", "",
              "Best-case patient: every measurable fact present and favourable. "
              "Atomizer levels: " + "; ".join(f"**{k}** — {v}" for k, v in ATOMIZERS.items()) + ".", "",
              "| subset | atomizer | scenario | eligible_pending_review | needs_chart_review | manual_review "
              "(severity / ratio) |", "|---|---|---|---|---|---|"]
        for subset in ("all", "priority"):
            for atz in ATOMIZERS:
                for sc in SCENARIOS:
                    c, n, why = corpus["yields"][(subset, atz, sc)]
                    L.append(f"| {subset} (n={n}) | {atz} | {sc} "
                             f"| {_pct(c['eligible_pending_review'], n)} | {_pct(c['needs_chart_review'], n)} "
                             f"| {_pct(c['manual_review'], n)} ({why['severity']} / {why['ratio']}) |")
        L += ["", "Scenarios: " + "; ".join(f"**{k}** {v}" for k, v in SCENARIO_LABEL.items()) + ".", ""]
    if packs:
        L += ["## B. CriteriaPacks — exact (real pipeline, synthetic witness packets)", "",
              f"{packs['packs']} packs, {packs['criteria']} criteria.", "",
              "- completeness_note: " + ", ".join(f"{k} {_pct(v, packs['criteria'])}" for k, v in sorted(packs['notes'].items())),
              "- logic: " + ", ".join(f"{k} {v}" for k, v in sorted(packs['logic'].items())),
              "- atom predicate types: " + ", ".join(f"{k} {v}" for k, v in sorted(packs['ptypes'].items())), ""]
        res = packs["results"]
        L += ["| trial | completeness | no-witness hard criteria | " + " | ".join(SCENARIOS) + " | forced complete (S2) |",
              "|---|---|---|" + "---|" * len(SCENARIOS) + "---|"]
        for r in res:
            L.append(f"| {r['trial_id']} | {r['criteria_completeness']} | {len(r['no_witness'])} | "
                     + " | ".join(r["states"][sc] for sc in SCENARIOS)
                     + f" | {r['forced_complete'].get('S2', '—')} |")
        n = len(res)
        L += ["", "| scenario | eligible_pending_review yield | opaque criteria | manual_review arms |", "|---|---|---|---|"]
        for sc in SCENARIOS:
            epr = sum(1 for r in res if r["states"][sc] == "eligible_pending_review")
            op = sum(r["eval_states"][sc]["opaque"] for r in res)
            mr = sum(r["arm_states"][sc]["manual_review"] for r in res)
            arms = sum(sum(r["arm_states"][sc].values()) for r in res)
            L.append(f"| {sc} | {_pct(epr, n)} ({epr}/{n}) | {_pct(op, packs['criteria'])} | {_pct(mr, arms)} |")
        L.append("")
    L += ["## Caveats", "",
          "- Part A is lexical: it estimates construct *demand* and a best-case *ceiling*; it is not matcher output. "
          "Real rates require atomized packs (Part B) once the atomizer exists.",
          "- Best-case ceilings assume a perfectly documented chart; real yields are lower.",
          "- CT.gov criteria are split on top-level bullets; nested sub-items are folded into their parent.", ""]
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ctis", help="CTIS SQLite (trials_retrieve)")
    ap.add_argument("--ctgov", help="CT.gov SQLite (ctgov_studies)")
    ap.add_argument("--packs", help="directory of CriteriaPack JSON files")
    ap.add_argument("-o", "--out", help="write Markdown report here (default stdout)")
    a = ap.parse_args(argv)
    if not (a.ctis or a.ctgov or a.packs):
        ap.error("give at least one of --ctis, --ctgov, --packs")
    trials = (load_ctis(a.ctis) if a.ctis else []) + (load_ctgov(a.ctgov) if a.ctgov else [])
    report = render(corpus_stats(trials) if trials else None,
                    pack_stats(load_packs(a.packs)) if a.packs else None)
    if a.out:
        Path(a.out).write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
