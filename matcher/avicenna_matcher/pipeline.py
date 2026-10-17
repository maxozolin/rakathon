"""§9 pipeline: CriteriaPack × patient packet (× context) → trial_result.

Order (MATCHER_DESIGN §9):
  validate inputs → build criterion DAG from atom-level refs (§6.4.5), refuse cycles →
  per arm, in dependency order: per atom resolve facts (§4) and evaluate (§3, §5) →
  fold atoms via logic.op (K3) → polarity + hardness (§6) → per-arm aggregation (§8) →
  trial roll-up → validate output.

Determinism: the evaluator reads no clock, no randomness, no network. `result_id` and
`generated_at` are injected by the caller and copied verbatim into the result.

Fail-closed: every path that cannot positively establish TRUE/FALSE yields UNKNOWN with
a registered reason code (explain.REASON_CODES). Structural defects in the inputs raise
StructuralError and never surface as an eligibility outcome.
"""

from __future__ import annotations

import heapq
import math
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import explain
from .aggregate import TrialAggregator, TrialResultBuilder
from .behaviors import PerArmMatcher
from .concepts import SEED_REGISTRY_V1, ConceptRegistry
from .errors import ReferencingError, StructuralError
from .outcome import OutcomeEvaluator
from .predicates import NotExistsEvaluator
from .resolution import (
    _verification,
    fact_authority_score,
    parse_time,
    resolve_facts_for_criterion,
)
from .sets import compare_band_to_threshold, compare_quantity_to_threshold
from .adapter import CANONICAL_VERSION, adapt, check_authorization_policy
from .timing import Span, _span_of_point, comparable, position, span_of, strictly_later
from .tristate import k3_all, k3_any, k3_not
from .types import TriState, VerificationStatus
from .validator import validate, validate_packet_facts


class CycleError(ReferencingError):
    """Cross-criterion references form a cycle (§9: the matcher MUST refuse cycles)."""


_NUMERIC_COMPARATORS = ("lt", "le", "gt", "ge", "eq", "ne")
_POINT_RELATIONS = ("current", "at_screening")
_EXISTENTIAL_RELATIONS = ("any_history", "ever", "within_days_before_anchor")
# When several atoms are UNKNOWN, report the most severe evaluation_state.
_STATE_PRIORITY = ["conflict", "manual_review", "unsupported", "stale", "missing"]
_CONTEXT_KEYS = {"site_context", "anchor", "mode", "policy_version", "authorization_policy",
                 "screening_recency_days"}
_CONFIRMED_EXPOSURE = ("administration", "review")   # prescription/billing/narrative ≠ administered
_PER_ARM_KEYS = ("arm_id", "arm_eligibility_state", "blocking_criteria",
                 "manual_review_criteria", "evidence_coverage")


# ---------------------------------------------------------------------------
# Atom evaluation result
# ---------------------------------------------------------------------------

@dataclass
class AtomEval:
    state: TriState
    eval_state: str = "evaluable"
    reason: Optional[str] = None
    refs: List[Dict[str, str]] = field(default_factory=list)


def _known(state: TriState, refs=None) -> AtomEval:
    return AtomEval(state, "evaluable", None, list(refs or []))


def _unknown(eval_state: str, reason: str, refs=None) -> AtomEval:
    assert reason in explain.REASON_CODES, reason
    return AtomEval(TriState.UNKNOWN, eval_state, reason, list(refs or []))


def _source_kind(fact: dict) -> str:
    """Most authoritative evidence source kind (canonical packets carry it per Evidence)."""
    kinds = [e.get("source_kind") for e in fact.get("evidence") or [] if isinstance(e, dict)]
    kinds = [k for k in kinds if isinstance(k, str)] or [fact.get("source_kind") or "narrative"]
    return max(kinds, key=lambda k: fact_authority_score(VerificationStatus.EXTRACTED_CANDIDATE, k))


def _ref(fact: dict, role: str) -> Dict[str, str]:
    return {"fact_id": fact["fact_id"], "fact_key": fact["fact_key"], "role": role}


# ---------------------------------------------------------------------------
# Value comparison (§3.2 set-based, units never converted)
# ---------------------------------------------------------------------------

def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _split_threshold(threshold) -> Tuple[Any, Optional[str]]:
    """Return (scalar, unit) for a numeric threshold; (None, None) if not numeric."""
    if _is_number(threshold):
        return threshold, None
    if isinstance(threshold, dict) and _is_number(threshold.get("value")):
        return threshold["value"], threshold.get("unit")
    return None, None


def _code_matches(value: dict, target) -> Optional[bool]:
    """CodedValue vs target code. None → systems differ (cannot decide)."""
    if isinstance(target, dict):
        system = target.get("system")
        if system is not None and system != value.get("system"):
            return None
        return target.get("code") == value.get("code")
    if isinstance(target, str):
        return target == value.get("code")
    return None


def _compare_value(value, comparator, threshold) -> AtomEval:
    if comparator is None:
        return _unknown("unsupported", "predicate_unsupported")

    if isinstance(value, dict) and value.get("kind") == "quantity":
        if value.get("normalization_status") != "validated":
            return _unknown("unsupported", "unit_unsupported")
        if comparator not in _NUMERIC_COMPARATORS:
            return _unknown("unsupported", "value_type_unsupported")
        t, unit = _split_threshold(threshold)
        if t is None:
            return _unknown("unsupported", "value_type_unsupported")
        if unit is None or unit != value.get("unit"):
            return _unknown("unsupported", "unit_mismatch")
        return _from_numeric(compare_quantity_to_threshold(value["value"], comparator, t))

    if isinstance(value, dict) and value.get("kind") == "band":
        if comparator not in _NUMERIC_COMPARATORS:
            return _unknown("unsupported", "value_type_unsupported")
        t, unit = _split_threshold(threshold)
        if t is None:
            return _unknown("unsupported", "value_type_unsupported")
        if unit != value.get("unit"):
            # A unitless band is never commensurable with a unit-bearing threshold, and vice versa.
            return _unknown("unsupported", "unit_mismatch")
        band = (value.get("lower_inclusive"), value.get("upper_inclusive"))
        return _from_numeric(compare_band_to_threshold(band, comparator, t))

    if isinstance(value, dict) and value.get("kind") == "coded":
        if comparator in ("eq", "ne"):
            m = _code_matches(value, threshold)
            if m is None:
                return _unknown("unsupported", "concept_system_mismatch")
            return _known(TriState.TRUE if (m if comparator == "eq" else not m) else TriState.FALSE)
        if comparator == "in_set" and isinstance(threshold, list):
            matches = [_code_matches(value, t) for t in threshold]
            if any(m is True for m in matches):
                return _known(TriState.TRUE)
            if any(m is None for m in matches):
                return _unknown("unsupported", "concept_system_mismatch")
            return _known(TriState.FALSE)
        return _unknown("unsupported", "value_type_unsupported")

    if isinstance(value, bool):
        if comparator in ("eq", "ne") and isinstance(threshold, bool):
            eq = value == threshold
            return _known(TriState.TRUE if (eq if comparator == "eq" else not eq) else TriState.FALSE)
        return _unknown("unsupported", "value_type_unsupported")

    if isinstance(value, str):
        if comparator in ("eq", "ne") and isinstance(threshold, str):
            eq = value == threshold
            return _known(TriState.TRUE if (eq if comparator == "eq" else not eq) else TriState.FALSE)
        if comparator == "in_set" and isinstance(threshold, list):
            return _known(TriState.TRUE if value in threshold else TriState.FALSE)
        return _unknown("unsupported", "value_type_unsupported")

    return _unknown("unsupported", "value_type_unsupported")


def _from_numeric(state: TriState) -> AtomEval:
    if state == TriState.UNKNOWN:
        return _unknown("unsupported", "value_straddles_threshold")
    return _known(state)


def _fact_compare(fact: dict, comparator, threshold) -> AtomEval:
    """Compare one resolved Fact against the atom's threshold, honoring state/assertion."""
    refs = [_ref(fact, "feeding")]
    state = fact.get("state")
    if state == "conflict":
        return _unknown("conflict", "fact_conflict", refs)
    if state != "known":
        return _unknown("missing", "fact_not_known", refs)

    assertion = fact.get("assertion")
    value = fact.get("value")
    if assertion == "suspected":
        return _unknown("missing", "assertion_uncertain", refs)
    if assertion == "not_applicable":
        return _unknown("missing", "fact_not_known", refs)
    if assertion == "explicit_negative":
        if value is None or isinstance(value, bool):
            value = False
        elif isinstance(value, dict) and value.get("kind") == "coded" and comparator in ("eq", "ne"):
            m = _code_matches(value, threshold)
            if m is True:
                # The patient explicitly does NOT have this code.
                r = TriState.FALSE if comparator == "eq" else TriState.TRUE
                return _known(r, refs)
            return _unknown("missing", "fact_not_known", refs)
        else:
            return _unknown("unsupported", "value_type_unsupported", refs)

    if value is None:
        return _unknown("missing", "fact_not_known", refs)
    res = _compare_value(value, comparator, threshold)
    res.refs = refs
    return res


# ---------------------------------------------------------------------------
# Evaluation context
# ---------------------------------------------------------------------------

# Point-in-time state that must be recent to stand for "at screening" (§4.6 recency bound).
_SCREENING_STATE_KEYS = frozenset({
    "performance.status", "lab.result", "cardiac.qtc", "cardiac.lvef",
    "safety.pregnant", "safety.pregnancy_test",
})


# Single-valued snapshot keys: "was ever X" has no eligibility meaning (everyone was once
# under 18), and an existential fold over them makes equivalent encodings disagree.
_SNAPSHOT_KEYS = frozenset({"demographics.age", "demographics.administrative_gender"})


def _extent(effective_time) -> Optional[Tuple[datetime, datetime, Optional[str]]]:
    """Whole extent of an effective time (an interval spans start..end, unlike span_of)."""
    if isinstance(effective_time, dict) and ("start" in effective_time or "end" in effective_time) \
            and "timestamp" not in effective_time:
        a, b = _span_of_point(effective_time.get("start")), _span_of_point(effective_time.get("end"))
        if a is None or b is None:
            return None               # open-ended: cannot bound the elapsed time
        return a.start, b.end, a.basis if a.basis == b.basis else "unknown"
    sp = _span_of_point(effective_time)
    return (sp.start, sp.end, sp.basis) if sp else None


def _age_at_anchor(fact: dict, ctx: "_Ctx") -> Tuple[Optional[dict], Optional[AtomEval]]:
    """Project an age statement to the evaluation anchor (age grows with time).

    The age (completed years) holds at the fact's effective time. At the anchor, with
    elapsed time Δ ∈ [Δmin, Δmax] years, completed age ∈ [lo + ⌊Δmin⌋, hi + ⌈Δmax⌉]
    (years bounded with 365/366 days, whichever is more conservative). If the elapsed
    time is unknown, only the monotone direction survives: age at screening ≥ the
    stated lower bound (screening is not before the record). In historical_review the
    anchor may precede the record, so nothing survives.
    """
    v = fact.get("value")
    if fact.get("state") != "known" or fact.get("assertion") != "positive" or not isinstance(v, dict):
        return fact, None
    if v.get("kind") == "quantity" and v.get("normalization_status") == "validated":
        lo = hi = v.get("value")
    elif v.get("kind") == "band":
        lo, hi = v.get("lower_inclusive"), v.get("upper_inclusive")
    else:
        return fact, None             # unsupported shapes fail later in _fact_compare
    refs = [_ref(fact, "feeding")]
    ext = _extent(fact.get("effective_time"))
    if ext is None or ctx.anchor_span is None:
        if ctx.mode == "historical_review":
            return None, _unknown("stale", "anchor_missing" if ctx.anchor_span is None
                                  else "time_precision_insufficient", refs)
        new_lo, new_hi = lo, None
    else:
        e_start, e_end, basis = ext
        if basis != ctx.anchor_span.basis or basis == "unknown":
            return None, _unknown("stale", "time_basis_incompatible", refs)
        d_min = (ctx.anchor_span.start - e_end).total_seconds() / 86400
        d_max = (ctx.anchor_span.end - e_start).total_seconds() / 86400
        y_min = d_min / (366 if d_min >= 0 else 365)
        y_max = d_max / (365 if d_max >= 0 else 366)
        new_lo = None if lo is None else lo + math.floor(y_min)
        new_hi = None if hi is None else hi + math.ceil(y_max)
    projected = dict(fact)
    projected["value"] = {"kind": "band", "lower_inclusive": new_lo, "upper_inclusive": new_hi,
                          "unit": v.get("unit")}
    return projected, None


def _assertion_of(f: dict):
    return (f.get("value"), f.get("assertion"), f.get("state"))


class _Ctx:
    def __init__(self, facts, anchor: Optional[Span], site_context, completeness=(), recency_days=None,
                 mode: Optional[str] = None):
        self.facts = facts
        self.mode = mode
        self.recency_days: Dict[str, int] = dict(recency_days or {})
        self.completeness = list(completeness)
        self.anchor_span: Optional[Span] = anchor
        self.anchor: Optional[datetime] = anchor.start if anchor else None
        self.site = site_context or {}
        self.done: Dict[str, Dict[str, Any]] = {}

    def completeness_for(self, fact_key: str) -> List[dict]:
        return [c for c in self.completeness if c["fact_key"] == fact_key]

    # §4 steps 1–2 (applicability, subject, rejected) — time handled by the callers below.
    def point_window(self, fact_key: str, relation: str, window_days) -> Tuple[Any, Optional[AtomEval]]:
        """Recency bound for a point-in-time read.

        Screening-state keys describe the patient *now*; "the latest fact ever" is not
        that. They need a bound: the atom's window_days (protocol), else the site's
        screening_recency_days policy for the key, else UNKNOWN.
        """
        if relation not in _POINT_RELATIONS or window_days is not None or fact_key not in _SCREENING_STATE_KEYS:
            return window_days, None
        days = self.recency_days.get(fact_key)
        if days is None:
            return None, _unknown("stale", "recency_unbounded")
        return days, None

    def _candidates(self, fact_key: str, concept=None, assay=None) -> List[dict]:
        facts = resolve_facts_for_criterion(self.facts, fact_key, "any_history")
        if assay is not None:
            # The atom names acceptable assays; a fact of unstated/other assay is not evidence.
            facts = [f for f in facts if (f.get("qualifiers") or {}).get("assay") in assay]
        if concept is None:
            return facts
        targets = concept if isinstance(concept, list) else [concept]

        def identity(f):
            if isinstance(f.get("concept"), dict):
                return f["concept"]
            v = f.get("value")
            if fact_key in _CONDITION_KEYS and isinstance(v, dict) and v.get("kind") == "coded":
                return v                  # on a condition key the coded value IS the concept
            return None

        # A fact of unstated or different concept is not evidence about this one.
        return [f for f in facts if (i := identity(f)) is not None
                and any(_code_matches(i, t) is True for t in targets)]

    def _place(self, fact: dict, window_days) -> str:
        """in / out / uncertain / incompatible, relative to the anchor (and window)."""
        sp = span_of(fact.get("effective_time"))
        if sp is None:
            return "uncertain"
        if self.anchor_span is None:
            return "in"
        if not comparable(sp, self.anchor_span):
            return "incompatible"
        return position(sp, self.anchor_span, window_days)

    def select_point(self, fact_key: str, relation: str, window_days,
                     concept=None, assay=None) -> Tuple[Optional[dict], Optional[AtomEval]]:
        """Point selection; biomarker results are selected per assay/specimen group.

        A newer result from a different assay or specimen does not supersede an older
        one (different tests, not change over time). Groups that agree answer; groups
        that disagree are UNKNOWN (assay_discordant).
        """
        cands = self._candidates(fact_key, concept, assay)
        if fact_key != "biomarker.result":
            return self._select_from(cands, relation, window_days)
        groups: Dict[Tuple, List[dict]] = {}
        for f in cands:
            q = f.get("qualifiers") or {}
            groups.setdefault((q.get("assay"), q.get("specimen_ref")), []).append(f)
        if len(groups) <= 1:
            return self._select_from(cands, relation, window_days)
        picks: List[dict] = []
        for members in groups.values():
            fact, err = self._select_from(members, relation, window_days)
            if err is not None:
                if err.reason == "fact_missing":
                    continue
                return None, err
            picks.append(fact)
        if not picks:
            return None, _unknown("missing", "fact_missing")
        if len({repr(_assertion_of(f)) for f in picks}) > 1:
            return None, _unknown("conflict", "assay_discordant", [_ref(f, "alternative") for f in picks])
        return picks[0], None

    def _select_from(self, cands: List[dict], relation: str,
                     window_days) -> Tuple[Optional[dict], Optional[AtomEval]]:
        """§4.3/§4.5/§4.6/§4.7 for current/at_screening.

        Recency dominates at the facts' real precision; authority breaks ties only among
        facts that are genuinely contemporaneous (neither is definitely later). A fact
        whose timing cannot be placed (reduced precision across the anchor/window edge,
        incompatible time basis) that might be the latest makes the selection UNKNOWN.
        """
        needs_anchor = relation == "at_screening" or window_days is not None
        if needs_anchor and self.anchor_span is None:
            return None, _unknown("stale", "anchor_missing")
        certain: List[Tuple[dict, Span]] = []
        doubtful: List[Tuple[dict, Optional[Span], str]] = []
        untimed: List[dict] = []
        for f in cands:
            sp = span_of(f.get("effective_time"))
            if sp is None:
                if needs_anchor:
                    doubtful.append((f, None, "time_precision_insufficient"))
                else:
                    untimed.append(f)         # cannot be ordered against anything
                continue
            place = self._place(f, window_days)
            if place == "out":
                continue
            if place == "in":
                certain.append((f, sp))
            else:
                doubtful.append((f, sp, "time_basis_incompatible" if place == "incompatible"
                                 else "time_precision_insufficient"))
        if not certain and not doubtful and not untimed:
            return None, _unknown("missing", "fact_missing")

        def dominated(sp: Optional[Span]) -> bool:
            return sp is not None and any(strictly_later(g, sp) is True for _, g in certain)

        live = [(f, sp) for f, sp in certain if not dominated(sp)]
        open_doubts = [(f, r) for f, sp, r in doubtful if not dominated(sp)]
        if open_doubts:
            return None, _unknown("stale", open_doubts[0][1], [_ref(f, "alternative") for f, _ in open_doubts])
        for i, (_, a) in enumerate(live):
            for _, b in live[i + 1:]:
                if not comparable(a, b):
                    return None, _unknown("stale", "time_basis_incompatible", [_ref(f, "alternative") for f, _ in live])

        def authority(f):
            return fact_authority_score(_verification(f), _source_kind(f))

        assertion_of = _assertion_of

        if untimed:
            # An untimed fact may be the latest. It is usable only when it cannot change
            # the answer: it is the sole evidence, or it agrees with every live candidate.
            pool = [f for f, _ in live] + untimed
            if live and len({repr(assertion_of(f)) for f in pool}) > 1:
                return None, _unknown("stale", "time_precision_insufficient", [_ref(f, "alternative") for f in pool])
            if not live:
                untimed.sort(key=authority, reverse=True)
                top = [f for f in untimed if authority(f) == authority(untimed[0])]
                if len({repr(assertion_of(f)) for f in top}) > 1:
                    return None, _unknown("conflict", "fact_conflict", [_ref(f, "alternative") for f in top])
                return untimed[0], None

        live.sort(key=lambda fs: (authority(fs[0]), fs[1].start), reverse=True)
        chosen = live[0][0]
        for other, _ in live[1:]:
            if authority(other) != authority(chosen):
                continue
            if assertion_of(other) != assertion_of(chosen):
                return None, _unknown("conflict", "fact_conflict",
                                      [_ref(chosen, "feeding"), _ref(other, "alternative")])
        return chosen, None

    def select_window(self, fact_key: str, window_days,
                      concept=None, assay=None) -> Tuple[List[dict], List[dict], Optional[AtomEval]]:
        """Facts certainly inside [anchor - window, anchor], and facts that may be."""
        if self.anchor_span is None:
            return [], [], _unknown("stale", "anchor_missing")
        if window_days is None:
            return [], [], _unknown("unsupported", "predicate_unsupported")
        inside, maybe = [], []
        for f in self._candidates(fact_key, concept, assay):
            place = self._place(f, window_days)
            if place == "in":
                inside.append(f)
            elif place != "out":
                maybe.append(f)
        return inside, maybe, None


# ---------------------------------------------------------------------------
# Atom evaluators
# ---------------------------------------------------------------------------

_CONCEPT_KEYED = frozenset({"biomarker.result", "lab.result"})
_CONDITION_KEYS = frozenset({"disease.condition", "safety.condition"})


def _eval_comparison(atom: dict, ctx: _Ctx, fact_key: Optional[str] = None) -> AtomEval:
    fact_key = fact_key or atom.get("fact_key")
    if not fact_key:
        raise StructuralError(f"atom {atom.get('atom_id')}: {atom['predicate_type']} without fact_key")
    relation = atom.get("relation", "current")
    comparator, threshold = atom.get("comparator"), atom.get("threshold")
    window = atom.get("window_days")
    concept = atom.get("concept")
    assay = atom.get("assay")
    if fact_key in _CONDITION_KEYS:
        # One fact per condition: only facts about the queried condition(s) are evidence.
        # Absence of a code is never a negative; `ne` would need exactly that, so it is refused.
        if comparator == "eq" and isinstance(threshold, dict):
            concept = threshold
        elif comparator == "in_set" and isinstance(threshold, list) and threshold:
            concept = threshold
        else:
            return _unknown("unsupported", "value_type_unsupported")
    elif concept is None and fact_key in _CONCEPT_KEYED:
        # A generic key mixes analytes/markers; without a concept any fact could answer.
        return _unknown("unsupported", "concept_unspecified")
    if fact_key in _SNAPSHOT_KEYS and relation not in _POINT_RELATIONS:
        return _unknown("unsupported", "relation_unsupported_for_key")

    if relation in _POINT_RELATIONS:
        window, err = ctx.point_window(fact_key, relation, window)
        if err:
            return err
        # Age is projected to the anchor by _age_at_anchor, which owns its time logic.
        point_relation = "current" if fact_key == "demographics.age" else relation
        fact, err = ctx.select_point(fact_key, point_relation, window, concept, assay)
        if err:
            return err
        if fact_key == "demographics.age":
            fact, err = _age_at_anchor(fact, ctx)
            if err:
                return err
        return _fact_compare(fact, comparator, threshold)

    maybe: List[dict] = []
    if relation == "within_days_before_anchor":
        # §4.5: a window alone does not say exists / latest / all — the atom must.
        quantifier = atom.get("quantifier")
        if quantifier == "latest":
            fact, err = ctx.select_point(fact_key, "current", window, concept, assay)
            if err:
                return err
            return _fact_compare(fact, comparator, threshold)
        if quantifier != "exists":
            return _unknown("unsupported", "window_quantifier_unspecified")
        facts, maybe, err = ctx.select_window(fact_key, window, concept, assay)
        if err:
            return err
    else:
        facts = ctx._candidates(fact_key, concept, assay)
    if not facts and not maybe:
        return _unknown("missing", "fact_missing")
    # §4.5 existential fold: one TRUE suffices. FALSE needs a positive absence signal
    # (every contributing fact is an explicit negative); otherwise non-existence is
    # not provable from the facts we happen to have. A TRUE from a fact that may lie
    # outside the window proves nothing.
    evals = [_fact_compare(f, comparator, threshold) for f in facts]
    maybe_evals = [_fact_compare(f, comparator, threshold) for f in maybe]
    refs = [r for e in evals + maybe_evals for r in e.refs]
    if any(e.state == TriState.TRUE for e in evals):
        return _known(TriState.TRUE, [r for e in evals if e.state == TriState.TRUE for r in e.refs])
    if any(e.state == TriState.TRUE for e in maybe_evals):
        return _unknown("stale", "time_precision_insufficient", refs)
    unknowns = [e for e in evals + maybe_evals if e.state == TriState.UNKNOWN]
    if unknowns:
        worst = _worst(unknowns)
        return _unknown(worst.eval_state, worst.reason, refs)
    if all(f.get("assertion") == "explicit_negative" for f in facts + maybe):
        return _known(TriState.FALSE, refs)
    return _unknown("missing", "absence_not_established", refs)


def _eval_relative(atom: dict, ctx: _Ctx) -> AtomEval:
    """§5.1: bound relative to the patient's own reference (paired reference fact)."""
    ref_key = atom.get("reference_key")
    ref_qual = atom.get("reference_qualifier")
    if not atom.get("fact_key") or bool(ref_key) == bool(ref_qual):
        raise StructuralError(f"atom {atom.get('atom_id')}: relative_to_reference needs fact_key and exactly one "
                              "of reference_key / reference_qualifier")
    relation = atom.get("relation", "current")
    if relation not in _POINT_RELATIONS:
        return _unknown("unsupported", "predicate_unsupported")
    window = atom.get("window_days")
    concept = atom.get("concept")
    if atom["fact_key"] in _CONDITION_KEYS:
        return _unknown("unsupported", "value_type_unsupported")
    if concept is None and atom["fact_key"] in _CONCEPT_KEYED:
        return _unknown("unsupported", "concept_unspecified")

    window, err = ctx.point_window(atom["fact_key"], relation, window)
    if err:
        return err
    fact, err = ctx.select_point(atom["fact_key"], relation, window, concept)
    if err:
        return err
    refs = [_ref(fact, "feeding")]
    if fact.get("state") == "conflict":
        return _unknown("conflict", "fact_conflict", refs)
    if fact.get("state") != "known":
        return _unknown("missing", "fact_not_known", refs)
    if fact.get("assertion") == "suspected":
        return _unknown("missing", "assertion_uncertain", refs)
    if fact.get("assertion") not in (None, "positive", "historical"):
        return _unknown("missing", "fact_not_known", refs)
    value = fact.get("value")
    if not (isinstance(value, dict) and value.get("kind") == "quantity"):
        return _unknown("unsupported", "value_type_unsupported", refs)
    if value.get("normalization_status") != "validated":
        return _unknown("unsupported", "unit_unsupported", refs)

    if ref_qual:
        # Reference range carried on the measurement itself — linkage by construction.
        q = fact.get("qualifiers") or {}
        limit_base, ref_unit = q.get(ref_qual), q.get("reference_ucum_code")
        if not _is_number(limit_base) or not ref_unit:
            return _unknown("missing", "reference_missing", refs)
        if ref_unit != value.get("unit"):
            return _unknown("unsupported", "unit_mismatch", refs)
    else:
        ref_fact, ref_err = _linked_reference(ctx, fact, ref_key)
        if ref_err:
            ref_err.refs = refs + ref_err.refs
            return ref_err
        refs.append(_ref(ref_fact, "reference"))
        rv = ref_fact["value"]
        if rv.get("unit") != value.get("unit"):
            return _unknown("unsupported", "unit_mismatch", refs)
        limit_base = rv["value"]

    mult, mult_unit = _split_threshold(atom.get("threshold"))
    if mult is None or mult_unit is not None:
        raise StructuralError(f"atom {atom.get('atom_id')}: relative threshold must be a unitless multiplier")
    offset = atom.get("reference_offset") or 0
    if not _is_number(offset):
        raise StructuralError(f"atom {atom.get('atom_id')}: reference_offset must be numeric")
    comparator = atom.get("comparator")
    if comparator not in _NUMERIC_COMPARATORS:
        raise StructuralError(f"atom {atom.get('atom_id')}: relative comparator must be numeric")
    limit = mult * limit_base + offset
    res = _from_numeric(compare_quantity_to_threshold(value["value"], comparator, limit))
    res.refs = refs
    return res


def _linked_reference(ctx: _Ctx, fact: dict, ref_key: str) -> Tuple[Optional[dict], Optional[AtomEval]]:
    """A separate reference fact counts only with explicit linkage to the measurement:
    the same non-null qualifiers.specimen_ref, and no disagreement on concept / assay.
    Equal timestamps alone do not prove the same specimen."""
    fq = fact.get("qualifiers") or {}
    specimen = fq.get("specimen_ref")
    if not specimen:
        return None, _unknown("missing", "reference_missing")
    linked = []
    for r in ctx._candidates(ref_key):
        rq = r.get("qualifiers") or {}
        if rq.get("specimen_ref") != specimen:
            continue
        if fact.get("concept") and r.get("concept") and fact["concept"] != r["concept"]:
            continue
        if fq.get("assay") and rq.get("assay") and fq["assay"] != rq["assay"]:
            continue
        rv = r.get("value")
        if (r.get("state") != "known" or r.get("assertion") not in (None, "positive", "historical")
                or not (isinstance(rv, dict) and rv.get("kind") == "quantity")
                or rv.get("normalization_status") != "validated"):
            continue
        linked.append(r)
    if not linked:
        return None, _unknown("missing", "reference_missing")
    values = {(r["value"]["value"], r["value"]["unit"]) for r in linked}
    if len(values) > 1:
        return None, _unknown("conflict", "fact_conflict", [_ref(r, "alternative") for r in linked])
    return linked[0], None


def _read_guard(ctx: _Ctx, key: str, scope: str) -> Tuple[Any, List[Dict[str, str]]]:
    """Return (guard_value or None if unknown, fact refs)."""
    if scope == "site_context":
        return ctx.site.get(key), []
    if key in _CONCEPT_KEYED or key in _CONDITION_KEYS:
        return None, []       # multi-concept key: "the latest fact" is an arbitrary concept
    fact = None
    window, err = ctx.point_window(key, "current", None)
    if err is None:
        fact, err = ctx.select_point(key, "current", window)
    if err or fact is None:
        return None, (err.refs if err else [])
    refs = [_ref(fact, "gate")]
    if fact.get("state") != "known":
        return None, refs
    assertion, value = fact.get("assertion"), fact.get("value")
    if assertion == "explicit_negative" and (value is None or isinstance(value, bool)):
        return False, refs
    if assertion in ("suspected", "not_applicable"):
        return None, refs
    if isinstance(value, dict) and value.get("kind") == "coded":
        return value, refs
    if isinstance(value, (bool, str)):
        return value, refs
    return None, refs


def _guard_eq(guard_value, case_value) -> bool:
    if isinstance(guard_value, dict) and guard_value.get("kind") == "coded":
        return _code_matches(guard_value, case_value) is True
    if isinstance(guard_value, bool) or isinstance(case_value, bool):
        return isinstance(guard_value, bool) and isinstance(case_value, bool) and guard_value == case_value
    return guard_value == case_value


def _eval_guarded(atom: dict, ctx: _Ctx) -> AtomEval:
    """§5.3: known guard → selected branch; unknown guard → supervaluation."""
    key = atom.get("guard_fact_key")
    cases = atom.get("cases") or []
    else_branch = atom.get("else")
    if not key or not (cases or else_branch):
        raise StructuralError(f"atom {atom.get('atom_id')}: guarded_case needs guard_fact_key and cases/else")
    guard, guard_refs = _read_guard(ctx, key, atom.get("guard_scope", "patient_fact"))

    if guard is not None:
        branch = next((c["predicate"] for c in cases if _guard_eq(guard, c["value"])), else_branch)
        if branch is None:
            return _unknown("missing", "guard_unresolved", guard_refs)
        res = _eval_atom(branch, ctx)
        res.refs = guard_refs + res.refs
        return res

    branches = [c["predicate"] for c in cases] + ([else_branch] if else_branch else [])
    exhaustive = else_branch is not None or {
        c["value"] for c in cases if isinstance(c["value"], bool)
    } == {True, False}
    evals = [_eval_atom(b, ctx) for b in branches]
    refs = guard_refs + [r for e in evals for r in e.refs]
    states = {e.state for e in evals}
    if exhaustive and states == {TriState.TRUE}:
        return _known(TriState.TRUE, refs)
    if exhaustive and states == {TriState.FALSE}:
        return _known(TriState.FALSE, refs)
    return _unknown("missing", "guard_unresolved", refs)


def _eval_gate(atom: dict, ctx: _Ctx) -> AtomEval:
    key = atom.get("gate_fact_key")
    if not key or "gate_value" not in atom:
        raise StructuralError(f"atom {atom.get('atom_id')}: applicability_gate needs gate_fact_key and gate_value")
    value, refs = _read_guard(ctx, key, atom.get("guard_scope", "patient_fact"))
    if value is None:
        return _unknown("missing", "gate_unresolved", refs)
    return _known(TriState.TRUE if _guard_eq(value, atom["gate_value"]) else TriState.FALSE, refs)


def _coverage_from_scope(fact: dict) -> Optional[dict]:
    """Map a reviewed Fact.scope onto the coverage shape NotExistsEvaluator checks.
    Extraction cannot self-certify completeness (§5.4): unreviewed scope is ignored."""
    scope = fact.get("scope")
    if not isinstance(scope, dict) or fact.get("review_status") != "reviewed":
        return None
    cov = {k: scope[k] for k in ("completeness", "time_basis", "agents", "classes", "settings",
                                 "chronology", "through", "disease_scope", "registry_version") if k in scope}
    for k in ("time_start", "time_end"):
        if k in scope:
            t = parse_time(scope[k])
            if t is None:
                return None
            cov[k] = t
    return cov or None


def _usable_coverage(cov: dict, ctx: "_Ctx", registry: ConceptRegistry) -> dict:
    """Standard Scope semantics the subsumption check cannot see on its own (§5.4).

    Coverage is withdrawn (completeness → "unusable", so it can never clear) when its
    chronology cannot be compared with the anchor, a lifetime cutoff does not reach the
    anchor, or it is scoped to a referenced disease (criteria carry no disease scope, so
    only an all-diseases scope covers them). Classes asserted under another registry
    version are dropped: their membership is unvalidated here.
    """
    cov = dict(cov)
    basis = cov.get("chronology")
    unusable = False
    if basis is not None:
        anchor = ctx.anchor_span
        if anchor is None or anchor.basis != basis or basis == "unknown":
            unusable = True
        elif cov.get("time_basis") == "lifetime":
            through = parse_time(cov.get("through"))
            # `through` is the first instant of the cutoff unit; the anchor's own day
            # counts as reached, any possibly-later day does not.
            if through is None or anchor.last_day > through.date():
                unusable = True
    if cov.get("disease_scope") not in (None, "all_diseases"):
        unusable = True
    if cov.get("registry_version") not in (None, registry.version):
        cov["classes"] = []
    if unusable:
        cov["completeness"] = "unusable"
    return cov


def _registry_for(scope: dict) -> ConceptRegistry:
    pin = scope.get("ontology_version_pin")
    if pin is not None and pin == SEED_REGISTRY_V1.version:
        return SEED_REGISTRY_V1
    # Null or unknown pin → every class-membership check is UNKNOWN.
    return ConceptRegistry(version=f"unpinned:{pin}", memberships={})


def _exposure_codes(fact: dict) -> Tuple[List[str], List[str]]:
    """(agent codes, asserted class codes) carried by a positive exposure fact."""
    v = fact.get("value")
    if isinstance(v, dict) and v.get("kind") == "coded" and isinstance(v.get("code"), str):
        return [v["code"]], []
    if isinstance(v, dict) and v.get("kind") == "therapy_event":
        agents = [a["code"] for a in v.get("agents") or [] if isinstance(a, dict) and isinstance(a.get("code"), str)]
        return agents, [c for c in v.get("classes") or [] if isinstance(c, str) and c != "unknown"]
    return [], []


def _exposure_membership(fact: dict, concepts: set, registry: ConceptRegistry) -> TriState:
    """Is this exposure an instance of the queried concepts (§5.4)?

    TRUE: identical identifier, or registered membership under the pinned registry.
    FALSE: only when every carried agent is a proven non-member of every queried
    registered class. Anything else (bare boolean, class-only evidence, unregistered
    concept, unpinned registry) is UNKNOWN — never assumed (non-)member.
    """
    if not concepts:
        return TriState.TRUE          # the atom queries any exposure under this fact_key
    agents, classes = _exposure_codes(fact)
    if not agents and not classes:
        return TriState.UNKNOWN
    if any(c in concepts for c in agents + classes):
        return TriState.TRUE
    if classes:
        return TriState.UNKNOWN       # no class-subsumption hierarchy is registered
    verdict = TriState.FALSE
    for q in concepts:
        for a in agents:
            m = registry.is_member(a, q)
            if m == TriState.TRUE:
                return TriState.TRUE
            if m == TriState.UNKNOWN:
                verdict = TriState.UNKNOWN
    return verdict


def _exposure_setting(fact: dict) -> Optional[str]:
    setting = (fact.get("scope") or {}).get("setting")
    if setting is not None:
        return setting
    v = fact.get("value")
    if isinstance(v, dict) and v.get("kind") == "therapy_event" and v.get("intent") not in (None, "unknown", "other"):
        return v["intent"]
    return None


def _eval_not_exists(atom: dict, ctx: _Ctx) -> AtomEval:
    """§5.4: TRUE only with a criterion-scoped absence signal; confirmed exposure → FALSE."""
    key = atom.get("fact_key")
    if not key:
        raise StructuralError(f"atom {atom.get('atom_id')}: not_exists without fact_key")
    scope = atom.get("scope") or {}
    time_extent = scope.get("time_extent", "lifetime")
    window = None
    if time_extent == "bounded":
        days = scope.get("bounded_days")
        if not isinstance(days, int):
            raise StructuralError(f"atom {atom.get('atom_id')}: bounded not_exists needs bounded_days")
        if ctx.anchor_span is None:
            return _unknown("stale", "anchor_missing")
        # widest possible queried window: coverage must span all of it
        window = (ctx.anchor_span.start - timedelta(days=days), ctx.anchor_span.end)
    elif time_extent != "lifetime":
        raise StructuralError(f"atom {atom.get('atom_id')}: unknown time_extent {time_extent!r}")
    setting = scope.get("setting")
    concepts = set(scope.get("concepts") or [])

    registry = _registry_for(scope)
    candidates = ctx._candidates(key)
    ambiguous_refs: List[Dict[str, str]] = []
    membership_refs: List[Dict[str, str]] = []
    for f in candidates:
        if f.get("assertion") not in ("positive", "historical", "suspected"):
            continue
        if f.get("state") != "known" or f.get("value") is False:
            continue
        if window is not None:
            place = ctx._place(f, scope["bounded_days"])
            if place == "out":
                continue
            if place != "in":             # may or may not fall inside the bounded window
                ambiguous_refs.append(_ref(f, "feeding"))
                continue
        member = _exposure_membership(f, concepts, registry)
        if member == TriState.FALSE:
            continue                      # proven unrelated exposure: neither proves nor clears
        if member == TriState.UNKNOWN:
            membership_refs.append(_ref(f, "feeding"))
            continue
        fact_setting = _exposure_setting(f)
        v = f.get("value")
        unconfirmed = isinstance(v, dict) and v.get("kind") == "therapy_event" \
            and v.get("evidence_kind") not in _CONFIRMED_EXPOSURE
        if f.get("assertion") == "suspected" or unconfirmed or (setting is not None and fact_setting is None):
            ambiguous_refs.append(_ref(f, "feeding"))
            continue
        if setting is not None and fact_setting != setting:
            continue
        return _known(TriState.FALSE, [_ref(f, "feeding")])
    if membership_refs:
        return _unknown("missing", "exposure_membership_unknown", membership_refs + ambiguous_refs)
    if ambiguous_refs:
        return _unknown("missing", "exposure_scope_ambiguous", ambiguous_refs)

    adapted = []
    neg_refs = []
    for f in candidates:
        if f.get("assertion") != "explicit_negative":
            continue
        g = dict(f)
        g.pop("coverage", None)
        cov = _coverage_from_scope(f)
        if cov is not None:
            g["coverage"] = _usable_coverage(cov, ctx, registry)
        adapted.append(g)
        neg_refs.append(_ref(f, "feeding"))
    for entry in ctx.completeness_for(key):
        cov = _coverage_from_scope({"scope": entry["scope"], "review_status": "reviewed"})
        if cov is None:
            continue
        adapted.append({
            "fact_id": entry["assertion_id"], "fact_key": key, "state": "known", "value": None,
            "assertion": "explicit_negative", "subject_scope": "patient", "review_status": "reviewed",
            "effective_time": None, "coverage": _usable_coverage(cov, ctx, registry),
        })
        neg_refs.append({"fact_id": entry["assertion_id"], "fact_key": key, "role": "completeness"})
    state = NotExistsEvaluator.evaluate(
        adapted, key, concepts, setting, time_extent, window, registry
    )
    if state == TriState.TRUE:
        return _known(TriState.TRUE, neg_refs)
    return _unknown("missing", "absence_not_established", neg_refs)


def _eval_criterion_ref(atom: dict, ctx: _Ctx) -> AtomEval:
    ref = atom.get("ref") or {}
    target = ctx.done.get(ref.get("criterion_id"))
    if target is None:
        raise ReferencingError(f"atom {atom.get('atom_id')}: reference to unevaluated criterion {ref.get('criterion_id')!r}")
    if ref["as"] in ("triggered", "predicate_true"):
        if not target["applicable"]:
            return _known(TriState.FALSE)
        if target["predicate"] == TriState.UNKNOWN:
            return _unknown("missing", "ref_unresolved")
        return _known(target["predicate"])
    outcome = target["outcome"]
    if outcome in ("satisfied", "clear"):
        return _known(TriState.TRUE)
    if outcome == "resolved_disqualifier":
        return _known(TriState.FALSE)
    return _unknown("missing", "ref_unresolved")


def _eval_atom(atom: dict, ctx: _Ctx) -> AtomEval:
    ptype = atom["predicate_type"]
    if ptype in ("simple_comparison", "derived_value"):
        # §5.2: a derived value is its own Fact; the matcher never computes it.
        return _eval_comparison(atom, ctx)
    if ptype == "relative_to_reference":
        return _eval_relative(atom, ctx)
    if ptype == "guarded_case":
        return _eval_guarded(atom, ctx)
    if ptype == "not_exists":
        return _eval_not_exists(atom, ctx)
    if ptype == "applicability_gate":
        return _eval_gate(atom, ctx)
    if ptype == "criterion_ref":
        return _eval_criterion_ref(atom, ctx)
    if ptype == "procedural":
        return _unknown("unsupported", "procedural_not_evaluable")
    raise StructuralError(f"atom {atom.get('atom_id')}: unknown predicate_type {ptype!r}")


def _worst(evals: List[AtomEval]) -> AtomEval:
    return min(evals, key=lambda e: _STATE_PRIORITY.index(e.eval_state)
               if e.eval_state in _STATE_PRIORITY else len(_STATE_PRIORITY))


# ---------------------------------------------------------------------------
# Criterion evaluation
# ---------------------------------------------------------------------------

def _atom_outcome(atom: dict, ev: AtomEval, criterion: dict) -> str:
    if atom["predicate_type"] == "applicability_gate":
        return {TriState.TRUE: "non_blocking", TriState.FALSE: "not_applicable"}.get(ev.state, "unresolved")
    return OutcomeEvaluator.evaluate(ev.state, criterion["criterion_type"], criterion["hardness"]).value


def _is_disqualifying(pred: TriState, criterion_type: str) -> bool:
    return (criterion_type == "inclusion" and pred == TriState.FALSE) or (
        criterion_type == "exclusion" and pred == TriState.TRUE)


def _evaluate_criterion(criterion: dict, arm_id: str, ctx: _Ctx) -> Dict[str, Any]:
    cid = criterion["criterion_id"]
    atoms = [a for a in criterion["atoms"] if a.get("arm_scope") in (None, arm_id)]
    evals = [(a, _eval_atom(a, ctx)) for a in atoms]
    gates = [e for a, e in evals if a["predicate_type"] == "applicability_gate"]
    body = [e for a, e in evals if a["predicate_type"] != "applicability_gate"]
    note = criterion["completeness_note"]
    logic = (criterion.get("logic") or {}).get("op")

    applicable = True
    coverage = "full"
    if any(g.state == TriState.FALSE for g in gates):
        applicable, pred, eval_state, reason = False, TriState.UNKNOWN, "not_applicable", "gate_not_met"
    elif note == "opaque_text" or not body:
        pred, eval_state, reason = TriState.UNKNOWN, "opaque", "opaque_text"
    elif logic == "custom":
        pred, eval_state, reason = TriState.UNKNOWN, "manual_review", "logic_custom"
    elif logic is None and len(body) > 1:
        pred, eval_state, reason = TriState.UNKNOWN, "manual_review", "logic_unspecified"
    elif logic == "not" and len(body) != 1:
        pred, eval_state, reason = TriState.UNKNOWN, "manual_review", "logic_not_arity"
    else:
        states = [e.state for e in body]
        if logic == "any":
            pred = k3_any(states)
        elif logic == "not":
            pred = k3_not(states[0])
        else:  # "all", or a single atom with no logic
            pred = k3_all(states)
        eval_state, reason = "evaluable", None
        unknown_gate = [g for g in gates if g.state == TriState.UNKNOWN]
        if unknown_gate:
            pred = TriState.UNKNOWN
            eval_state, reason = unknown_gate[0].eval_state, "gate_unresolved"
        elif pred == TriState.UNKNOWN:
            worst = _worst([e for e in body if e.state == TriState.UNKNOWN] or body)
            eval_state, reason = worst.eval_state, worst.reason
        if note == "partial" and _is_disqualifying(pred, criterion["criterion_type"]):
            pred, eval_state, reason = TriState.UNKNOWN, "unsupported", "partial_atomization"

    if not applicable:
        outcome = "not_applicable"
    else:
        outcome = OutcomeEvaluator.evaluate(pred, criterion["criterion_type"], criterion["hardness"]).value
        if pred == TriState.UNKNOWN or outcome == "non_blocking":
            coverage = "unknown"
        if note == "partial":
            coverage = "partial"
    if reason is not None:
        assert reason in explain.REASON_CODES, reason

    ctx.done[cid] = {"predicate": pred, "outcome": outcome, "applicable": applicable}

    atom_results = []
    for a, e in evals:
        atom_results.append({
            "atom_id": a["atom_id"],
            "predicate_type": a["predicate_type"],
            "evaluation_state": "not_applicable" if (
                a["predicate_type"] == "applicability_gate" and e.state == TriState.FALSE) else e.eval_state,
            "outcome": _atom_outcome(a, e, criterion),
            "reason_code": e.reason,
            "source_text": a["source_text"],
            "fact_references": [{"fact_id": r["fact_id"], "role": r["role"]}
                                for r in explain.merge_fact_refs(e.refs)],
        })

    return {
        "criterion_id": cid,
        "criterion_type": criterion["criterion_type"],
        "criterion_source_text": criterion["source_text"],
        "evaluation_state": eval_state,
        "outcome": outcome,
        "applicable": applicable,
        "hardness": criterion["hardness"],
        "coverage": coverage,
        "reason_code": reason if (pred == TriState.UNKNOWN or not applicable) else None,
        "fact_references": explain.merge_fact_refs([r for _, e in evals for r in e.refs]),
        "atom_results": atom_results,
        "notes": [],
    }


# ---------------------------------------------------------------------------
# DAG (§6.4.5)
# ---------------------------------------------------------------------------

def _atom_refs(atom: dict) -> List[str]:
    out = []
    if atom.get("predicate_type") == "criterion_ref":
        ref = atom.get("ref")
        if not ref:
            raise StructuralError(f"atom {atom.get('atom_id')}: criterion_ref without ref")
        out.append(ref["criterion_id"])
    for case in atom.get("cases") or []:
        out.extend(_atom_refs(case["predicate"]))
    if atom.get("else"):
        out.extend(_atom_refs(atom["else"]))
    return out


def dependency_order(criteria: List[dict]) -> List[str]:
    """Kahn's algorithm over atom-level refs; ties broken by pack order (deterministic)."""
    index = {}
    for i, c in enumerate(criteria):
        if c["criterion_id"] in index:
            raise StructuralError(f"duplicate criterion_id {c['criterion_id']!r}")
        index[c["criterion_id"]] = i
    deps = {cid: set() for cid in index}
    users = {cid: set() for cid in index}
    for c in criteria:
        for a in c["atoms"]:
            for target in _atom_refs(a):
                if target not in index:
                    raise ReferencingError(f"{c['criterion_id']}: dangling reference to {target!r}")
                deps[c["criterion_id"]].add(target)
                users[target].add(c["criterion_id"])
    heap = [index[cid] for cid, d in deps.items() if not d]
    heapq.heapify(heap)
    order = []
    ids = [c["criterion_id"] for c in criteria]
    while heap:
        cid = ids[heapq.heappop(heap)]
        order.append(cid)
        for u in users[cid]:
            deps[u].discard(cid)
            if not deps[u]:
                heapq.heappush(heap, index[u])
    if len(order) != len(criteria):
        cyclic = sorted(cid for cid, d in deps.items() if d)
        raise CycleError(f"cross-criterion reference cycle among {cyclic}")
    return order


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _check_context(context: Optional[dict], eval_ctx: dict) -> dict:
    """§4.3: separately supplied context must agree with the packet; never overrides it."""
    context = context or {}
    unknown = set(context) - _CONTEXT_KEYS
    if unknown:
        raise StructuralError(f"unknown context keys: {sorted(unknown)}")
    if "policy_version" in context and context["policy_version"] != eval_ctx.get("policy_version"):
        raise StructuralError("context policy_version disagrees with packet evaluation_context")
    if "mode" in context and context["mode"] != eval_ctx.get("mode"):
        raise StructuralError("context mode disagrees with packet evaluation_context")
    if "anchor" in context and parse_time(context["anchor"]) != parse_time(eval_ctx.get("anchor")):
        raise StructuralError("context anchor disagrees with packet evaluation_context")
    site = context.get("site_context")
    if site is not None and not isinstance(site, dict):
        raise StructuralError("site_context must be an object")
    return site or {}


def _check_recency_policy(policy) -> Dict[str, int]:
    """Site screening-recency policy: {fact_key: days}. Only screening-state keys; positive ints."""
    if policy is None:
        return {}
    if not isinstance(policy, dict):
        raise StructuralError("screening_recency_days must be an object {fact_key: days}")
    for key, days in policy.items():
        if key not in _SCREENING_STATE_KEYS:
            raise StructuralError(f"screening_recency_days: {key!r} is not a screening-state key")
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
            raise StructuralError(f"screening_recency_days[{key!r}] must be a positive integer")
    return dict(policy)


def evaluate(
    pack: dict,
    packet: dict,
    context: Optional[dict] = None,
    *,
    result_id: str,
    generated_at: str,
) -> Dict[str, Any]:
    """Evaluate one CriteriaPack against one patient packet → trial_result (schema-valid)."""
    if not (isinstance(result_id, str) and result_id):
        raise StructuralError("result_id must be injected by the caller")
    if not (isinstance(generated_at, str) and generated_at):
        raise StructuralError("generated_at must be injected by the caller")

    validate(pack, "criteria_pack")
    adaptation_notes: List[str] = []
    auth_policy = check_authorization_policy((context or {}).get("authorization_policy"))
    if isinstance(packet, dict) and packet.get("schema_version") == CANONICAL_VERSION:
        packet, report = adapt(packet, auth_policy)
        adaptation_notes.append(f"packet adapted {report['source_schema']} -> {report['target_schema']} "
                                f"by {report['adapter_version']}; {len(report['losses'])} loss(es)")
        adaptation_notes += [f"adapter loss: {l['where']}: {l['code']}" for l in report["losses"]]
    validate(packet, "patient_packet")
    validate_packet_facts(packet)
    eval_ctx = packet["evaluation_context"]
    site = _check_context(context, eval_ctx)
    recency_days = _check_recency_policy((context or {}).get("screening_recency_days"))
    if eval_ctx["mode"] == "shifted_demo" and eval_ctx["absolute_screening_recency_allowed"]:
        raise StructuralError("shifted_demo cannot allow absolute screening recency (shifted time is not real time)")
    anchor = span_of(eval_ctx.get("anchor"))
    # Completeness counts only when the caller pins the same local authorization policy
    # that accepted it; otherwise not_exists stays unresolved.
    completeness = [c for c in packet["coverage"]["completeness"]
                    if auth_policy is not None and c["authorized_under"] == auth_policy["policy_version"]]

    criteria = pack["criteria"]
    arms = pack["arms"]
    if not arms:
        raise StructuralError("pack has no arms")
    arm_ids = [a["arm_id"] for a in arms]
    if len(set(arm_ids)) != len(arm_ids):
        raise StructuralError("duplicate arm_id")
    for c in criteria:
        if c["arm_scope"] is not None and c["arm_scope"] not in arm_ids:
            raise ReferencingError(f"{c['criterion_id']}: arm_scope {c['arm_scope']!r} is not an arm of this pack")
    order = dependency_order(criteria)
    by_id = {c["criterion_id"]: c for c in criteria}

    per_arm_results = []
    per_arm_criteria: Dict[str, Dict[str, dict]] = {}
    notes = list(adaptation_notes)
    if eval_ctx["mode"] != "prescreen_real_time":
        notes.append(f"mode={eval_ctx['mode']}: relative timing on the packet's own time basis only; "
                     "not current enrollment clearance")
    for arm in arms:
        ctx = _Ctx(packet["facts"], anchor, site, completeness, recency_days, eval_ctx["mode"])
        results = {cid: _evaluate_criterion(by_id[cid], arm["arm_id"], ctx) for cid in order}
        arm_list = [results[c["criterion_id"]] for c in criteria]
        arm_res = PerArmMatcher.evaluate_arm(
            arm["arm_id"], arm["study_type"], criteria, arm_list,
            criteria_completeness=pack["criteria_completeness"],
        )
        per_arm_results.append({k: arm_res[k] for k in _PER_ARM_KEYS})
        per_arm_criteria[arm["arm_id"]] = {
            c["criterion_id"]: results[c["criterion_id"]]
            for c in criteria if c["arm_scope"] in (None, arm["arm_id"])
        }
        if arm["study_type"] != "interventional":
            notes.append(f"arm {arm['arm_id']}: study_type={arm['study_type']}; "
                         "not treatment candidacy (§7.2)")

    trial_state, _ = TrialAggregator.aggregate(per_arm_results)
    criterion_results = _merge_criterion_results(criteria, arm_ids, per_arm_criteria)

    if anchor is None:
        notes.append("evaluation anchor is null: anchor-relative predicates are UNKNOWN (§4.3)")
    if pack["criteria_completeness"] == "partial":
        notes.append("criteria_completeness=partial: arms capped at needs_chart_review (§8.2)")
    if recency_days:
        notes.append("site screening_recency_days applied where the atom gives no window: "
                     + ", ".join(f"{k}={v}d" for k, v in sorted(recency_days.items())))

    result = TrialResultBuilder.build(
        trial_id=pack["trial_id"],
        patient_ref=packet["patient_ref"],
        policy_version=eval_ctx["policy_version"],
        trial_eligibility_state=trial_state,
        per_arm_results=per_arm_results,
        criterion_results=criterion_results,
        notes=notes,
        result_id=result_id,
        generated_at=generated_at,
    )
    validate(result, "trial_result")
    for cr in criterion_results:
        validate(cr, "criterion_result")
    return result


def _merge_criterion_results(criteria, arm_ids, per_arm_criteria) -> List[dict]:
    """One result per criterion; if arm-scoped atoms make arms disagree, one per variant,
    each annotated with the arms it belongs to."""
    out = []
    for c in criteria:
        cid = c["criterion_id"]
        variants: Dict[str, Tuple[dict, List[str]]] = {}
        for arm_id in arm_ids:
            r = per_arm_criteria[arm_id].get(cid)
            if r is None:
                continue
            key = json.dumps(r, sort_keys=True)
            variants.setdefault(key, (r, []))[1].append(arm_id)
        if len(variants) == 1:
            out.append(next(iter(variants.values()))[0])
        else:
            for r, arms in variants.values():
                r = dict(r)
                r["notes"] = [f"arms: {', '.join(arms)}"]
                out.append(r)
    return out
