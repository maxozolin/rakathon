"""P6 — pipeline + CLI + explanations, end to end.

All fixtures are synthetic and schema-valid (every run validates pack and packet in and
trial_result out). Expected values are taken from MATCHER_DESIGN.md (§3–§9, §11 trace)
and TRIAL_DATA_STANDARD.md §6.4, not from the implementation.
"""

import copy
import io
import json
import re
import socket
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from avicenna_matcher import cli, explain, pipeline
from avicenna_matcher.errors import ReferencingError, StructuralError
from avicenna_matcher.pipeline import CycleError, dependency_order
from avicenna_matcher.validator import validate

ANCHOR = "2026-03-01T00:00:00Z"
T = "2026-02-20T00:00:00Z"
GEN = "2026-03-01T12:00:00Z"


# ---------------------------------------------------------------------------
# Synthetic fixture builders
# ---------------------------------------------------------------------------

def qty(v, unit, status="validated"):
    return {"kind": "quantity", "value": v, "unit": unit, "normalization_status": status}


def band(lo, hi):
    return {"kind": "band", "lower_inclusive": lo, "upper_inclusive": hi}


def coded(code, system="local"):
    return {"kind": "coded", "system": system, "code": code}


def fact(fid, key, value=None, *, assertion="positive", t=T, state="known",
         review="unreviewed", scope=None, subject="patient", qualifiers=None):
    if state != "known":
        assertion = None
    extra = {"qualifiers": qualifiers} if qualifiers is not None else {}
    return {**extra,
        "fact_id": fid, "fact_key": key, "state": state, "value": value,
        "missing_reason": None if state == "known" else "not_documented",
        "assertion": assertion, "subject_scope": subject,
        "effective_time": {"timestamp": t} if t else None,
        "recorded_time": None,
        "evidence": [{"source_text": "synthetic"}] if state == "known" else [],
        "provenance": {"derivation_method": "direct_extract", "extractor_version": "test/0"},
        "review_status": review,
        "generalization": {"applied": False, "constraints": []},
        "alternatives": [], "scope": scope,
    }


def packet(facts, anchor=ANCHOR, policy="eval-policy-v1"):
    return {
        "schema_version": "avicenna.matcher-packet/1.0.0",
        "packet_id": "pkt-synthetic", "patient_ref": "pt-synthetic",
        "generated_at": "2026-03-01T00:00:00Z", "environment": "synthetic_demo",
        "source_snapshot": {"snapshot_id": "s1", "ingestion_state": "complete",
                            "extractor_version": "test/0", "terminology_version": "t/0"},
        "evaluation_context": {"mode": "prescreen_real_time",
                               "anchor": {"timestamp": anchor} if anchor else None,
                               "absolute_screening_recency_allowed": False,
                               "policy_version": policy},
        "facts": facts,
        "coverage": {"assessed_fact_keys": [], "unassessed_fact_keys": [], "completeness": []},
        "warnings": [],
    }


def atom(aid, ptype, src=None, **kw):
    a = {"atom_id": aid, "predicate_type": ptype, "arm_scope": None, "source_text": src or aid}
    a.update(kw)
    return a


def cmp_atom(aid, key, comparator, threshold, **kw):
    return atom(aid, "simple_comparison", fact_key=key, comparator=comparator, threshold=threshold, **kw)


def crit(cid, ctype, atoms, *, logic=None, hardness="hard", note="complete", arm_scope=None, src=None):
    c = {"criterion_id": cid, "criterion_type": ctype, "hardness": hardness, "arm_scope": arm_scope,
         "source_text": src or f"verbatim text of {cid}", "atoms": atoms, "completeness_note": note}
    if logic:
        c["logic"] = {"op": logic}
    return c


def pack(criteria, arms=None, completeness="complete"):
    return {
        "schema_version": "avicenna.criteria-pack/0.1", "pack_id": "pack-synthetic",
        "trial_id": "SYNTH-0001", "criteria_completeness": completeness,
        "generated_at": "2026-01-01T00:00:00Z",
        "arms": arms or [{"arm_id": "main", "arm_name": "Main", "study_type": "interventional"}],
        "criteria": copy.deepcopy(criteria),
    }


AGE_INCL = crit("inc:age", "inclusion", [cmp_atom("a1", "demographics.age", "ge", {"value": 18, "unit": "a"})],
                src="Age ≥ 18 years")


def run(pk, pt, context=None):
    """Evaluate and assert design invariants that must hold for every output."""
    r = pipeline.evaluate(pk, pt, context, result_id="res-test", generated_at=GEN)
    validate(r, "trial_result")
    by_id = {c["criterion_id"]: c for c in pk["criteria"]}
    for cr in r["criterion_results"]:
        assert cr["criterion_source_text"] == by_id[cr["criterion_id"]]["source_text"]
        assert cr["reason_code"] is None or cr["reason_code"] in explain.REASON_CODES
        for ar in cr["atom_results"]:
            assert ar["reason_code"] is None or ar["reason_code"] in explain.REASON_CODES
        # fail-closed: an unresolved criterion never carries a resolved reason-less state
        if cr["outcome"] == "unresolved":
            assert cr["reason_code"] is not None and cr["evaluation_state"] != "evaluable"
    for arm in r["per_arm_results"]:
        aid = arm["arm_id"]
        mine = [cr for cr in r["criterion_results"]
                if by_id[cr["criterion_id"]]["arm_scope"] in (None, aid)
                and (not cr["notes"] or aid in cr["notes"][0].removeprefix("arms: ").split(", "))]
        hard = [cr for cr in mine if cr["hardness"] == "hard" and cr["applicable"]]
        disq = [cr["criterion_id"] for cr in hard if cr["outcome"] == "resolved_disqualifier"]
        unres = [cr["criterion_id"] for cr in hard if cr["outcome"] == "unresolved"]
        # §8: blocking = resolved hard disqualifiers + unresolved hard requirements
        assert sorted(arm["blocking_criteria"]) == sorted(disq + unres)
        # §8: ineligible iff >= 1 resolved hard disqualifier (never from UNKNOWN)
        assert (arm["arm_eligibility_state"] == "ineligible") == bool(disq)
        # §8.2: nothing hard unresolved before eligible_pending_review
        if unres:
            assert arm["arm_eligibility_state"] != "eligible_pending_review"
    return r


def cr_of(result, cid):
    matches = [c for c in result["criterion_results"] if c["criterion_id"] == cid]
    assert len(matches) == 1, matches
    return matches[0]


# ---------------------------------------------------------------------------
# Core verdicts (the user's repro + §8.2)
# ---------------------------------------------------------------------------

class TestCoreVerdicts:
    def test_age_70_satisfies_age_18(self):
        r = run(pack([AGE_INCL]), packet([fact("f-age", "demographics.age", qty(70, "a"))]))
        c = cr_of(r, "inc:age")
        assert (c["outcome"], c["evaluation_state"], c["reason_code"]) == ("satisfied", "evaluable", None)
        assert c["fact_references"] == [{"fact_id": "f-age", "fact_key": "demographics.age", "role": "feeding"}]
        assert c["criterion_source_text"] == "Age ≥ 18 years"
        assert r["trial_eligibility_state"] == "eligible_pending_review"

    def test_age_16_is_resolved_disqualifier(self):
        r = run(pack([AGE_INCL]), packet([fact("f-age", "demographics.age", qty(16, "a"))]))
        assert cr_of(r, "inc:age")["outcome"] == "resolved_disqualifier"
        assert r["per_arm_results"][0]["blocking_criteria"] == ["inc:age"]
        assert r["trial_eligibility_state"] == "ineligible"

    def test_missing_fact_is_needs_chart_review_not_ineligible(self):
        r = run(pack([AGE_INCL]), packet([]))
        c = cr_of(r, "inc:age")
        assert (c["outcome"], c["evaluation_state"], c["reason_code"]) == ("unresolved", "missing", "fact_missing")
        assert r["trial_eligibility_state"] == "needs_chart_review"
        assert r["per_arm_results"][0]["blocking_criteria"] == ["inc:age"]
        assert r["per_arm_results"][0]["evidence_coverage"]["unassessed_criteria"] == ["inc:age"]

    def test_exclusion_false_is_clear_and_true_blocks(self):
        excl = crit("exc:mets", "exclusion", [cmp_atom("b1", "dx.brain_mets", "eq", True)])
        r = run(pack([AGE_INCL, excl]), packet([
            fact("f-age", "demographics.age", qty(40, "a")),
            fact("f-bm", "dx.brain_mets", None, assertion="explicit_negative")]))
        assert cr_of(r, "exc:mets")["outcome"] == "clear"
        assert r["trial_eligibility_state"] == "eligible_pending_review"
        r = run(pack([AGE_INCL, excl]), packet([
            fact("f-age", "demographics.age", qty(40, "a")), fact("f-bm", "dx.brain_mets", True)]))
        assert cr_of(r, "exc:mets")["outcome"] == "resolved_disqualifier"
        assert r["trial_eligibility_state"] == "ineligible"

    def test_policy_and_patient_ref_come_from_packet(self):
        r = run(pack([AGE_INCL]), packet([], policy="eval-policy-v7"))
        assert r["policy_version"] == "eval-policy-v7" and r["patient_ref"] == "pt-synthetic"
        assert r["result_id"] == "res-test" and r["generated_at"] == GEN


# ---------------------------------------------------------------------------
# §11 renal trace (golden oracle table)
# ---------------------------------------------------------------------------

RENAL = crit("inc:14c", "inclusion", [
    atom("alpha", "relative_to_reference", "Serum creatinine ≤ 1.5 × ULN", fact_key="lab.creatinine",
         reference_key="lab.creatinine.uln", comparator="le", threshold=1.5),
    atom("beta", "derived_value", "CrCl ≥ 50 mL/min (Cockcroft-Gault)", fact_key="derived.crcl_cg",
         comparator="ge", threshold={"value": 50, "unit": "mL/min"}, derived_expression="cockcroft_gault"),
], logic="any", src="Renal: Serum creatinine ≤ 1.5 × ULN or estimated creatinine clearance ≥ 50 mL/min "
                    "as calculated by Cockcroft-Gault equation.")


def _creat(v, uln=None, t=T):
    fs = [fact("f-cr", "lab.creatinine", qty(v, "mg/dL"), t=t, qualifiers={"specimen_ref": "spec-1"})]
    if uln is not None:
        fs.append(fact("f-uln", "lab.creatinine.uln", qty(uln, "mg/dL"), t=t, qualifiers={"specimen_ref": "spec-1"}))
    return fs


@pytest.mark.parametrize("facts, alpha, beta, outcome, trial", [
    (_creat(1.0, uln=1.2), "evaluable", "missing", "satisfied", "eligible_pending_review"),
    (_creat(1.0), "missing", "missing", "unresolved", "needs_chart_review"),
    (_creat(2.5, uln=1.2) + [fact("f-crcl", "derived.crcl_cg", qty(60, "mL/min"))],
     "evaluable", "evaluable", "satisfied", "eligible_pending_review"),
    (_creat(2.5, uln=1.2), "evaluable", "missing", "unresolved", "needs_chart_review"),
], ids=["alpha-true-beta-discharged", "no-reference", "alpha-false-beta-true", "alpha-false-beta-unknown"])
def test_section_11_renal_trace(facts, alpha, beta, outcome, trial):
    r = run(pack([RENAL]), packet(facts))
    c = cr_of(r, "inc:14c")
    atoms = {a["atom_id"]: a for a in c["atom_results"]}
    assert atoms["alpha"]["evaluation_state"] == alpha
    assert atoms["beta"]["evaluation_state"] == beta
    assert c["outcome"] == outcome
    assert r["trial_eligibility_state"] == trial


def test_renal_reference_must_be_same_measurement():
    facts = [fact("f-cr", "lab.creatinine", qty(1.0, "mg/dL"), t=T),
             fact("f-uln", "lab.creatinine.uln", qty(1.2, "mg/dL"), t="2025-06-01T00:00:00Z")]
    a = cr_of(run(pack([RENAL]), packet(facts)), "inc:14c")["atom_results"][0]
    assert a["reason_code"] == "reference_missing"


def test_renal_reference_ref_role_reported():
    c = cr_of(run(pack([RENAL]), packet(_creat(1.0, uln=1.2))), "inc:14c")
    roles = {(r["fact_id"], r["role"]) for r in c["fact_references"]}
    assert roles == {("f-cr", "feeding"), ("f-uln", "reference")}


# ---------------------------------------------------------------------------
# Units, precision, straddle (§3.2, §4.4)
# ---------------------------------------------------------------------------

class TestValues:
    CREAT = crit("inc:cr", "inclusion", [cmp_atom("c1", "lab.creatinine", "le", {"value": 1.5, "unit": "mg/dL"})])

    def test_unit_mismatch_is_unknown_never_converted(self):
        c = cr_of(run(pack([self.CREAT]), packet([fact("f", "lab.creatinine", qty(90, "umol/L"))])), "inc:cr")
        assert (c["outcome"], c["evaluation_state"], c["reason_code"]) == ("unresolved", "unsupported", "unit_mismatch")

    def test_unvalidated_normalization_is_unknown(self):
        c = cr_of(run(pack([self.CREAT]), packet([fact("f", "lab.creatinine", qty(1.0, "mg/dL", "unmapped"))])), "inc:cr")
        assert c["reason_code"] == "unit_unsupported" and c["outcome"] == "unresolved"

    def test_unitless_threshold_against_quantity_is_unknown(self):
        k = crit("inc:x", "inclusion", [cmp_atom("x", "lab.creatinine", "le", 1.5)])
        assert cr_of(run(pack([k]), packet([fact("f", "lab.creatinine", qty(1.0, "mg/dL"))])), "inc:x")["reason_code"] == "unit_mismatch"

    @pytest.mark.parametrize("lo, hi, thr, outcome", [
        (60, 64, 18, "satisfied"), (60, 64, 62, "unresolved"), (10, 14, 18, "resolved_disqualifier"),
    ])
    def test_age_band_straddle(self, lo, hi, thr, outcome):
        k = crit("inc:age", "inclusion", [cmp_atom("a", "demographics.age_band", "ge", thr)])
        c = cr_of(run(pack([k]), packet([fact("f", "demographics.age_band", band(lo, hi))])), "inc:age")
        assert c["outcome"] == outcome
        if outcome == "unresolved":
            assert c["reason_code"] == "value_straddles_threshold"

    def test_coded_in_set_and_system_mismatch(self):
        k = crit("inc:ecog", "inclusion", [cmp_atom("e", "perf.ecog", "in_set",
                                                    [{"system": "ecog", "code": "0"}, {"system": "ecog", "code": "1"}])])
        assert cr_of(run(pack([k]), packet([fact("f", "perf.ecog", coded("1", "ecog"))])), "inc:ecog")["outcome"] == "satisfied"
        assert cr_of(run(pack([k]), packet([fact("f", "perf.ecog", coded("3", "ecog"))])), "inc:ecog")["outcome"] == "resolved_disqualifier"
        c = cr_of(run(pack([k]), packet([fact("f", "perf.ecog", coded("1", "karnofsky"))])), "inc:ecog")
        assert c["reason_code"] == "concept_system_mismatch"

    def test_suspected_assertion_is_unknown(self):
        k = crit("exc:bm", "exclusion", [cmp_atom("b", "dx.brain_mets", "eq", True)])
        c = cr_of(run(pack([k]), packet([fact("f", "dx.brain_mets", True, assertion="suspected")])), "exc:bm")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "assertion_uncertain")

    def test_conflict_state_fact(self):
        c = cr_of(run(pack([AGE_INCL]), packet([fact("f", "demographics.age", None, state="conflict")])), "inc:age")
        assert (c["evaluation_state"], c["reason_code"]) == ("conflict", "fact_conflict")


# ---------------------------------------------------------------------------
# §4 resolution inside the pipeline
# ---------------------------------------------------------------------------

class TestResolution:
    ECOG = crit("inc:ecog", "inclusion", [cmp_atom("e", "perf.ecog", "le", 1)])

    def _ecog(self, v, t, review="unreviewed", fid=None):
        return fact(fid or f"f-{v}-{t[:10]}", "perf.ecog", v, t=t, review=review)

    def test_recency_dominates_authority(self):
        # reviewed ECOG 0 months ago never overrides a recent ECOG 3 (§4.6)
        old = fact("f-old", "perf.ecog", band(0, 0), t="2025-09-01T00:00:00Z", review="reviewed")
        new = fact("f-new", "perf.ecog", band(3, 3), t="2026-02-25T00:00:00Z")
        c = cr_of(run(pack([self.ECOG]), packet([old, new])), "inc:ecog")
        assert c["outcome"] == "resolved_disqualifier"
        assert c["fact_references"][0]["fact_id"] == "f-new"

    def test_contemporaneous_equal_authority_disagreement_is_conflict(self):
        a = fact("f-a", "perf.ecog", band(0, 0), t=T)
        b = fact("f-b", "perf.ecog", band(3, 3), t=T)
        c = cr_of(run(pack([self.ECOG]), packet([a, b])), "inc:ecog")
        assert (c["outcome"], c["evaluation_state"], c["reason_code"]) == ("unresolved", "conflict", "fact_conflict")

    def test_authority_breaks_contemporaneous_tie(self):
        a = fact("f-a", "perf.ecog", band(0, 0), t=T, review="reviewed")
        b = fact("f-b", "perf.ecog", band(3, 3), t=T)
        assert cr_of(run(pack([self.ECOG]), packet([a, b])), "inc:ecog")["outcome"] == "satisfied"

    def test_rejected_and_family_facts_never_feed(self):
        fs = [fact("f-rej", "demographics.age", qty(70, "a"), review="rejected"),
              fact("f-fam", "demographics.age", qty(70, "a"), subject="family")]
        assert cr_of(run(pack([AGE_INCL]), packet(fs)), "inc:age")["reason_code"] == "fact_missing"

    def test_fact_after_anchor_is_ignored(self):
        fs = [fact("f", "demographics.age", qty(70, "a"), t="2026-05-01T00:00:00Z")]
        assert cr_of(run(pack([AGE_INCL]), packet(fs)), "inc:age")["reason_code"] == "fact_missing"

    def test_null_anchor_makes_at_screening_stale(self):
        k = crit("inc:anc", "inclusion", [cmp_atom("n", "lab.anc", "ge", {"value": 1.5, "unit": "10*9/L"},
                                                   relation="at_screening")])
        r = run(pack([k]), packet([fact("f", "lab.anc", qty(3.0, "10*9/L"))], anchor=None))
        c = cr_of(r, "inc:anc")
        assert (c["evaluation_state"], c["reason_code"]) == ("stale", "anchor_missing")
        assert any("anchor is null" in n for n in r["notes"])

    def test_window_excludes_old_fact(self):
        k = crit("inc:anc", "inclusion", [cmp_atom("n", "lab.anc", "ge", {"value": 1.5, "unit": "10*9/L"},
                                                   relation="at_screening", window_days=14)])
        old = fact("f", "lab.anc", qty(3.0, "10*9/L"), t="2026-01-01T00:00:00Z")
        assert cr_of(run(pack([k]), packet([old])), "inc:anc")["reason_code"] == "fact_missing"
        fresh = fact("f", "lab.anc", qty(3.0, "10*9/L"), t="2026-02-25T00:00:00Z")
        assert cr_of(run(pack([k]), packet([fresh])), "inc:anc")["outcome"] == "satisfied"

    def test_existential_history_found_true_but_absence_not_provable(self):
        k = crit("exc:mi", "exclusion", [cmp_atom("m", "hx.mi", "eq", True, relation="any_history")])
        assert cr_of(run(pack([k]), packet([fact("f", "hx.mi", True, t="2010-01-01T00:00:00Z")])), "exc:mi")["outcome"] == "resolved_disqualifier"
        # a positive-assertion "false" value is not a scoped absence signal
        c = cr_of(run(pack([k]), packet([fact("f", "hx.mi", False)])), "exc:mi")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "absence_not_established")
        assert cr_of(run(pack([k]), packet([fact("f", "hx.mi", None, assertion="explicit_negative")])), "exc:mi")["outcome"] == "clear"


# ---------------------------------------------------------------------------
# §5.3 guarded supervaluation and §7.3 jurisdiction guards
# ---------------------------------------------------------------------------

def _ast_atom(mult, aid):
    return atom(aid, "relative_to_reference", fact_key="lab.ast", reference_key="lab.ast.uln",
                comparator="le", threshold=mult)


AST = crit("inc:ast", "inclusion", [atom("g", "guarded_case", "AST ≤ 1.5 × ULN (≤ 3 × ULN with liver mets)",
                                         guard_fact_key="dx.liver_mets",
                                         cases=[{"value": True, "predicate": _ast_atom(3.0, "g-mets")}],
                                         **{"else": _ast_atom(1.5, "g-else")})])


def _ast(x_uln, mets=None):
    link = {"specimen_ref": "spec-ast"}
    fs = [fact("f-ast", "lab.ast", qty(40 * x_uln, "U/L"), qualifiers=link),
          fact("f-ast-uln", "lab.ast.uln", qty(40, "U/L"), qualifiers=link)]
    if mets is not None:
        fs.append(fact("f-mets", "dx.liver_mets", mets, assertion="positive" if mets else "explicit_negative"))
    return fs


@pytest.mark.parametrize("x, mets, outcome", [
    (1.0, None, "satisfied"),               # strict branch passes → no guard needed
    (4.0, None, "resolved_disqualifier"),   # loose branch fails → no guard needed
    (2.0, None, "unresolved"),              # ambiguous band → guard genuinely needed
    (2.0, True, "satisfied"),
    (2.0, False, "resolved_disqualifier"),
])
def test_guard_supervaluation(x, mets, outcome):
    c = cr_of(run(pack([AST]), packet(_ast(x, mets))), "inc:ast")
    assert c["outcome"] == outcome
    if outcome == "unresolved":
        assert c["reason_code"] == "guard_unresolved"
    if mets is not None:
        assert {"fact_id": "f-mets", "fact_key": "dx.liver_mets", "role": "gate"} in c["fact_references"]


CZ_AGE = crit("inc:age-cz", "inclusion", [atom(
    "g", "guarded_case", "age ≥ 50, or ≥ 55 for Czech Republic", guard_fact_key="country", guard_scope="site_context",
    cases=[{"value": "CZ", "predicate": cmp_atom("cz", "demographics.age", "ge", {"value": 55, "unit": "a"})}],
    **{"else": cmp_atom("other", "demographics.age", "ge", {"value": 50, "unit": "a"})})])


@pytest.mark.parametrize("age, site, outcome", [
    (52, "CZ", "resolved_disqualifier"),
    (52, "DE", "satisfied"),
    (52, None, "unresolved"),   # §7.3: missing site context → UNKNOWN, never dropped
    (60, None, "satisfied"),    # both branches agree
    (45, None, "resolved_disqualifier"),
])
def test_jurisdiction_guard(age, site, outcome):
    ctx = {"site_context": {"country": site}} if site else None
    r = run(pack([CZ_AGE]), packet([fact("f", "demographics.age", qty(age, "a"))]), ctx)
    c = cr_of(r, "inc:age-cz")
    assert c["applicable"] is True and c["outcome"] == outcome


def test_guard_without_else_needs_exhaustive_cases():
    k = crit("inc:g", "inclusion", [atom("g", "guarded_case", guard_fact_key="country", guard_scope="site_context",
                                         cases=[{"value": "CZ", "predicate": cmp_atom("x", "demographics.age", "ge", {"value": 1, "unit": "a"})}])])
    c = cr_of(run(pack([k]), packet([fact("f", "demographics.age", qty(70, "a"))])), "inc:g")
    assert c["outcome"] == "unresolved"  # unknown guard may match no case at all


# ---------------------------------------------------------------------------
# §5.4 not_exists
# ---------------------------------------------------------------------------

SERD = crit("inc:9", "inclusion", [atom(
    "n", "not_exists", "No prior elacestrant or other SERDs for advanced disease", fact_key="tx.serd",
    scope={"time_extent": "lifetime", "setting": "advanced", "concepts": ["elacestrant"]})])


def _neg(review="reviewed", **scope):
    sc = {"scope_type": "explicit_concept_set", "completeness": "complete", "time_basis": "lifetime",
          "agents": ["elacestrant"], "settings": ["advanced"]}
    sc.update(scope)
    return fact("f-neg", "tx.serd", None, assertion="explicit_negative", review=review, scope=sc)


@pytest.mark.parametrize("facts, outcome, reason", [
    ([], "unresolved", "absence_not_established"),                         # no fact ≠ absent
    ([fact("f-pos", "tx.serd", coded("elacestrant"), scope={"scope_type": "setting", "setting": "advanced"})],
     "resolved_disqualifier", None),                                       # confirmed exposure → FALSE
    ([fact("f-pos", "tx.serd", coded("elacestrant"))], "unresolved", "exposure_scope_ambiguous"),
    ([fact("f-pos", "tx.serd", coded("elacestrant"), scope={"scope_type": "setting", "setting": "adjuvant"})],
     "unresolved", "absence_not_established"),                             # other setting: neither proves nor clears
    ([fact("f-neg", "tx.serd", None, assertion="explicit_negative")], "unresolved", "absence_not_established"),
    ([_neg()], "satisfied", None),                                         # reviewed, subsuming scope
    ([_neg(review="unreviewed")], "unresolved", "absence_not_established"),  # extraction can't self-certify
    ([_neg(time_basis="bounded", time_start="2024-03-01T00:00:00Z", time_end=ANCHOR)],
     "unresolved", "absence_not_established"),                             # bounded never clears lifetime
    ([_neg(agents=["fulvestrant"])], "unresolved", "absence_not_established"),
], ids=["no-facts", "exposure", "exposure-setting-unknown", "exposure-other-setting", "bare-negative",
        "reviewed-coverage", "unreviewed-coverage", "bounded-vs-lifetime", "concept-not-subsumed"])
def test_not_exists(facts, outcome, reason):
    c = cr_of(run(pack([SERD]), packet(facts)), "inc:9")
    assert c["outcome"] == outcome
    assert c["reason_code"] == reason


def test_not_exists_class_membership_requires_pin():
    k = crit("inc:9", "inclusion", [atom("n", "not_exists", fact_key="tx.serd",
                                         scope={"time_extent": "lifetime", "concepts": ["elacestrant"]})])
    neg = _neg(agents=[], classes=["SERD"], settings=[])
    assert cr_of(run(pack([k]), packet([neg])), "inc:9")["outcome"] == "unresolved"


# ---------------------------------------------------------------------------
# Folding, gates, opaque, procedural, partial (§6, §8.2)
# ---------------------------------------------------------------------------

PREG = crit("exc:preg", "exclusion", [
    atom("gate", "applicability_gate", "women of childbearing potential", gate_fact_key="demographics.sex",
         gate_value="female"),
    cmp_atom("p", "status.pregnant", "eq", True)])


class TestFoldingAndAggregation:
    def test_gate_false_is_not_applicable(self):
        r = run(pack([AGE_INCL, PREG]), packet([fact("f-age", "demographics.age", qty(40, "a")),
                                                fact("f-sex", "demographics.sex", "male")]))
        c = cr_of(r, "exc:preg")
        assert (c["applicable"], c["outcome"], c["evaluation_state"], c["reason_code"]) == \
            (False, "not_applicable", "not_applicable", "gate_not_met")
        assert r["trial_eligibility_state"] == "eligible_pending_review"

    def test_gate_unknown_is_unresolved_not_dropped(self):
        r = run(pack([AGE_INCL, PREG]), packet([fact("f-age", "demographics.age", qty(40, "a"))]))
        c = cr_of(r, "exc:preg")
        assert (c["applicable"], c["outcome"], c["reason_code"]) == (True, "unresolved", "gate_unresolved")
        assert r["trial_eligibility_state"] == "needs_chart_review"

    def test_multi_atom_without_logic_is_not_assumed(self):
        k = crit("inc:x", "inclusion", [cmp_atom("a", "demographics.age", "ge", {"value": 18, "unit": "a"}),
                                        cmp_atom("b", "demographics.age", "le", {"value": 99, "unit": "a"})])
        c = cr_of(run(pack([k]), packet([fact("f", "demographics.age", qty(40, "a"))])), "inc:x")
        assert (c["outcome"], c["evaluation_state"], c["reason_code"]) == ("unresolved", "manual_review", "logic_unspecified")

    def test_logic_all_and_not(self):
        both = [cmp_atom("a", "demographics.age", "ge", {"value": 18, "unit": "a"}),
                cmp_atom("b", "demographics.age", "le", {"value": 30, "unit": "a"})]
        f = [fact("f", "demographics.age", qty(40, "a"))]
        assert cr_of(run(pack([crit("i", "inclusion", both, logic="all")]), packet(f)), "i")["outcome"] == "resolved_disqualifier"
        assert cr_of(run(pack([crit("i", "inclusion", both, logic="any")]), packet(f)), "i")["outcome"] == "satisfied"
        neg = crit("i", "inclusion", [both[1]], logic="not")
        assert cr_of(run(pack([neg]), packet(f)), "i")["outcome"] == "satisfied"

    def test_resolved_disqualifier_beats_opaque_exclusion(self):
        opaque = crit("exc:op", "exclusion", [], note="opaque_text")
        r = run(pack([AGE_INCL, opaque]), packet([fact("f", "demographics.age", qty(10, "a"))]))
        arm = r["per_arm_results"][0]
        assert arm["arm_eligibility_state"] == "ineligible"
        assert arm["manual_review_criteria"] == ["exc:op"]

    def test_opaque_hard_exclusion_forces_manual_review(self):
        opaque = crit("exc:op", "exclusion", [], note="opaque_text")
        r = run(pack([AGE_INCL, opaque]), packet([fact("f", "demographics.age", qty(40, "a"))]))
        assert cr_of(r, "exc:op")["evaluation_state"] == "opaque"
        assert r["per_arm_results"][0]["arm_eligibility_state"] == "manual_review"

    def test_procedural_is_non_blocking_and_does_not_cap(self):
        consent = crit("inc:consent", "inclusion", [atom("c", "procedural", "Signed informed consent")],
                       hardness="procedural_pre_screen")
        r = run(pack([AGE_INCL, consent]), packet([fact("f", "demographics.age", qty(40, "a"))]))
        assert cr_of(r, "inc:consent")["outcome"] == "non_blocking"
        assert r["trial_eligibility_state"] == "eligible_pending_review"

    def test_partial_criterion_never_disqualifies_and_caps(self):
        k = crit("inc:p", "inclusion", [cmp_atom("a", "demographics.age", "ge", {"value": 18, "unit": "a"})], note="partial")
        c = cr_of(run(pack([k]), packet([fact("f", "demographics.age", qty(10, "a"))])), "inc:p")
        assert (c["outcome"], c["reason_code"], c["coverage"]) == ("unresolved", "partial_atomization", "partial")
        r = run(pack([k]), packet([fact("f", "demographics.age", qty(40, "a"))]))
        assert cr_of(r, "inc:p")["outcome"] == "satisfied"
        assert r["trial_eligibility_state"] == "needs_chart_review"

    def test_pack_partial_completeness_caps(self):
        r = run(pack([AGE_INCL], completeness="partial"), packet([fact("f", "demographics.age", qty(40, "a"))]))
        assert r["trial_eligibility_state"] == "needs_chart_review"


# ---------------------------------------------------------------------------
# §7.1 per-arm
# ---------------------------------------------------------------------------

ARMS = [{"arm_id": "A", "arm_name": "HER2+", "study_type": "interventional"},
        {"arm_id": "B", "arm_name": "All-comers", "study_type": "interventional"}]


class TestPerArm:
    def test_ineligible_for_one_arm_eligible_for_other(self):
        her2 = crit("inc:her2", "inclusion", [cmp_atom("h", "bio.her2", "eq", "positive")], arm_scope="A")
        r = run(pack([AGE_INCL, her2], arms=ARMS),
                packet([fact("f-age", "demographics.age", qty(40, "a")), fact("f-h", "bio.her2", "negative")]))
        arms = {a["arm_id"]: a for a in r["per_arm_results"]}
        assert arms["A"]["arm_eligibility_state"] == "ineligible"
        assert arms["B"]["arm_eligibility_state"] == "eligible_pending_review"
        assert r["trial_eligibility_state"] == "eligible_pending_review"
        for a in r["per_arm_results"]:
            assert set(a) == {"arm_id", "arm_eligibility_state", "blocking_criteria",
                              "manual_review_criteria", "evidence_coverage"}

    def test_arm_scoped_atom_produces_per_arm_variants(self):
        k = crit("inc:anc", "inclusion", [
            cmp_atom("a", "lab.anc", "ge", {"value": 1.5, "unit": "10*9/L"}, arm_scope="A"),
            cmp_atom("b", "lab.anc", "ge", {"value": 1.0, "unit": "10*9/L"}, arm_scope="B")])
        r = run(pack([k], arms=ARMS), packet([fact("f", "lab.anc", qty(1.2, "10*9/L"))]))
        variants = [c for c in r["criterion_results"] if c["criterion_id"] == "inc:anc"]
        assert sorted((v["notes"][0], v["outcome"]) for v in variants) == [
            ("arms: A", "resolved_disqualifier"), ("arms: B", "satisfied")]
        assert r["trial_eligibility_state"] == "eligible_pending_review"

    def test_observational_arm_noted(self):
        r = run(pack([AGE_INCL], arms=[{"arm_id": "o", "arm_name": "Registry", "study_type": "observational"}]),
                packet([fact("f", "demographics.age", qty(40, "a"))]))
        assert any("not treatment candidacy" in n for n in r["notes"])


# ---------------------------------------------------------------------------
# §6.4.5 DAG
# ---------------------------------------------------------------------------

INR_LINK = {"specimen_ref": "spec-inr"}


def _inr_pack(excl16_atoms=None):
    inr = crit("inc:14d", "inclusion", [
        atom("inr", "relative_to_reference", fact_key="lab.inr", reference_key="lab.inr.uln",
             comparator="le", threshold=1.5),
        atom("unless", "criterion_ref", ref={"criterion_id": "exc:16", "as": "triggered"})],
        logic="any", src="INR ≤ 1.5 × ULN, unless the patient meets exclusion criterion 16")
    e16 = crit("exc:16", "exclusion", excl16_atoms or [cmp_atom("ac", "tx.anticoagulant", "eq", True)])
    return pack([inr, e16])  # referrer listed first: evaluation must follow the DAG


class TestDag:
    def test_dependency_order_follows_refs(self):
        assert dependency_order(_inr_pack()["criteria"]) == ["exc:16", "inc:14d"]

    def test_ref_discharges_clause(self):
        fs = [fact("f-inr", "lab.inr", qty(3.0, "1"), qualifiers=INR_LINK),
              fact("f-uln", "lab.inr.uln", qty(1.1, "1"), qualifiers=INR_LINK),
              fact("f-ac", "tx.anticoagulant", True)]
        r = run(_inr_pack(), packet(fs))
        assert cr_of(r, "inc:14d")["outcome"] == "satisfied"
        assert cr_of(r, "exc:16")["outcome"] == "resolved_disqualifier"

    def test_unresolved_ref_propagates_unknown(self):
        fs = [fact("f-inr", "lab.inr", qty(3.0, "1"), qualifiers=INR_LINK),
              fact("f-uln", "lab.inr.uln", qty(1.1, "1"), qualifiers=INR_LINK)]
        c = cr_of(run(_inr_pack(), packet(fs)), "inc:14d")
        assert c["outcome"] == "unresolved" and c["reason_code"] == "ref_unresolved"

    def test_cycle_refused(self):
        pk = _inr_pack([atom("back", "criterion_ref", ref={"criterion_id": "inc:14d", "as": "satisfied"})])
        with pytest.raises(CycleError):
            run(pk, packet([]))

    def test_ref_inside_guard_branch_is_an_edge(self):
        pk = _inr_pack([atom("g", "guarded_case", guard_fact_key="country", guard_scope="site_context",
                             cases=[{"value": "CZ", "predicate": atom("r", "criterion_ref",
                                                                      ref={"criterion_id": "inc:14d", "as": "satisfied"})}])])
        with pytest.raises(CycleError):
            dependency_order(pk["criteria"])

    def test_dangling_ref_refused(self):
        pk = _inr_pack()
        pk["criteria"][0]["atoms"][1]["ref"]["criterion_id"] = "exc:99"
        with pytest.raises(ReferencingError):
            run(pk, packet([]))


# ---------------------------------------------------------------------------
# Structural errors are never eligibility outcomes
# ---------------------------------------------------------------------------

class TestStructural:
    def test_legacy_field_names_rejected(self):
        pk = pack([AGE_INCL])
        c = pk["criteria"][0]
        c["kind"] = c.pop("criterion_type")
        with pytest.raises(StructuralError):
            run(pk, packet([]))

    def test_duplicate_criterion_id(self):
        with pytest.raises(StructuralError):
            run(pack([AGE_INCL, AGE_INCL]), packet([]))

    def test_unknown_arm_scope(self):
        with pytest.raises(StructuralError):
            run(pack([crit("x", "inclusion", [], arm_scope="Z")]), packet([]))

    def test_invalid_packet(self):
        pt = packet([])
        del pt["evaluation_context"]
        with pytest.raises(StructuralError):
            run(pack([AGE_INCL]), pt)

    @pytest.mark.parametrize("ctx", [
        {"policy_version": "other"}, {"mode": "shifted_demo"}, {"anchor": "2020-01-01T00:00:00Z"},
        {"bogus": 1}, {"site_context": "CZ"},
    ])
    def test_context_must_agree_with_packet(self, ctx):
        with pytest.raises(StructuralError):
            run(pack([AGE_INCL]), packet([]), ctx)

    def test_agreeing_context_accepted(self):
        run(pack([AGE_INCL]), packet([]), {"policy_version": "eval-policy-v1", "anchor": {"timestamp": ANCHOR},
                                           "mode": "prescreen_real_time", "site_context": {"country": "CZ"}})

    @pytest.mark.parametrize("kw", [{"result_id": "", "generated_at": GEN}, {"result_id": "r", "generated_at": ""}])
    def test_ids_must_be_injected(self, kw):
        with pytest.raises(StructuralError):
            pipeline.evaluate(pack([AGE_INCL]), packet([]), **kw)


# ---------------------------------------------------------------------------
# Determinism / offline gate (build plan §3) and CLI
# ---------------------------------------------------------------------------

PKG = Path(pipeline.__file__).parent


class TestDeterminismAndOffline:
    def test_no_clock_rng_or_network_in_package(self):
        forbidden = re.compile(r"datetime\.now|datetime\.utcnow|date\.today|time\.time\(|\buuid\b|"
                               r"\brandom\b|\bsocket\b|urllib|requests|http\.client|subprocess")
        hits = []
        for p in sorted(PKG.glob("*.py")):
            for i, line in enumerate(p.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if forbidden.search(code) and not code.strip().startswith(('"', "'")):
                    hits.append(f"{p.name}:{i}: {line.strip()}")
        assert not hits, hits

    def test_no_network_at_runtime(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("network access attempted")
        monkeypatch.setattr(socket, "socket", boom)
        monkeypatch.setattr(socket, "create_connection", boom)
        run(pack([RENAL, SERD, AST]), packet(_creat(1.0, uln=1.2) + _ast(2.0)))

    def test_byte_identical_output(self):
        pk = pack([AGE_INCL, RENAL, SERD, AST, PREG, CZ_AGE])
        pt = packet(_creat(2.5, uln=1.2) + _ast(2.0) + [fact("f-age", "demographics.age", qty(52, "a"))])
        ctx = {"site_context": {"country": "CZ"}}
        a = cli.run_matcher(pk, pt, ctx, generated_at=GEN)
        b = cli.run_matcher(json.loads(json.dumps(pk)), json.loads(json.dumps(pt)), dict(ctx), generated_at=GEN)
        assert a == b
        assert json.loads(a)["result_id"] == cli.derive_result_id(pk, pt, ctx, GEN)

    def test_result_id_changes_with_inputs(self):
        pt1 = packet([fact("f", "demographics.age", qty(40, "a"))])
        pt2 = packet([fact("f", "demographics.age", qty(41, "a"))])
        assert cli.derive_result_id(pack([AGE_INCL]), pt1, None, GEN) != cli.derive_result_id(pack([AGE_INCL]), pt2, None, GEN)

    def _write(self, tmp_path, name, obj):
        p = tmp_path / name
        p.write_text(json.dumps(obj))
        return str(p)

    def test_cli_main_end_to_end(self, tmp_path):
        pk = self._write(tmp_path, "pack.json", pack([AGE_INCL]))
        pt = self._write(tmp_path, "packet.json", packet([fact("f", "demographics.age", qty(70, "a"))]))
        outs = []
        for _ in range(2):
            buf = io.StringIO()
            with redirect_stdout(buf):
                assert cli.main([pk, pt, "--generated-at", GEN]) == 0
            outs.append(buf.getvalue())
        assert outs[0] == outs[1]
        result = json.loads(outs[0])
        validate(result, "trial_result")
        assert result["trial_eligibility_state"] == "eligible_pending_review"

    def test_cli_requires_generated_at(self, tmp_path):
        pk = self._write(tmp_path, "pack.json", pack([AGE_INCL]))
        pt = self._write(tmp_path, "packet.json", packet([]))
        with redirect_stderr(io.StringIO()), pytest.raises(SystemExit):
            cli.main([pk, pt])

    def test_cli_structural_error_exit_2(self, tmp_path):
        pk = self._write(tmp_path, "pack.json", {"not": "a pack"})
        pt = self._write(tmp_path, "packet.json", packet([]))
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            assert cli.main([pk, pt, "--generated-at", GEN]) == 2
        assert out.getvalue() == ""
        assert json.loads(err.getvalue())["error"] == "structural_error"


def test_reason_code_registry_validates():
    validate(explain.registry_document(), "reason_codes")
    assert {c for c in explain.REASON_CODES} == set(explain.registry_document()["codes"])
