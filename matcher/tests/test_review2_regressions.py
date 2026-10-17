"""Review-2 regressions (8 findings). Expected values come from MATCHER_DESIGN.md and
PATIENT_MATCHING_FORMAT_STANDARD.md, not from the implementation. All inputs synthetic;
the canonical example is the fictional one printed in the standard itself.
"""

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from avicenna_matcher import adapter
from avicenna_matcher.aggregate import PerArmAggregator
from avicenna_matcher.errors import StructuralError
from avicenna_matcher.resolution import fact_precision
from avicenna_matcher.validator import validate
from test_p6_pipeline_cli import ANCHOR, atom, band, cmp_atom, coded, cr_of, crit, fact, pack, packet, qty, run

STANDARD = Path(__file__).resolve().parents[2] / "PATIENT_MATCHING_FORMAT_STANDARD.md"


def _standard_example() -> dict:
    md = STANDARD.read_text()
    block = md[md.index("## Synthetic example"):]
    block = block[block.index("```json") + len("```json"):]
    return json.loads(block[:block.index("```")])


def _tp(value, precision="day", basis="shifted_patient_local"):
    return {"kind": "point", "value": value, "precision": precision, "time_basis": basis}


EVIDENCE = [{"resource_type": "Observation", "resource_id": "syn-1", "version_id": "1", "locator": "value",
             "source_kind": "structured", "verification_status": "source_assertion"}]
PROV = {"method": "source_projection", "method_version": "syn/1", "model_id": None, "confidence": None,
        "input_fact_refs": []}


def cfact(fid, key, value, *, assertion="positive", t=None, review="unreviewed", scope=None, **extra):
    f = {"fact_id": fid, "fact_key": key, "state": "known", "value": value, "missing_reason": None,
         "assertion": assertion, "subject_scope": "patient", "effective_time": t, "recorded_time": None,
         "evidence": copy.deepcopy(EVIDENCE), "provenance": copy.deepcopy(PROV), "review_status": review,
         "generalization": {"applied": False, "constraints": []}, "alternatives": [], "scope": scope}
    f.update(extra)
    return f


def cpacket(facts, completeness=(), anchor=None, assessed=("therapy.event",), mode="shifted_demo"):
    p = _standard_example()
    p["facts"] = facts
    p["evaluation_context"]["mode"] = mode
    if anchor is not None:
        p["evaluation_context"]["anchor"] = anchor
    p["coverage"] = {"assessed_fact_keys": list(assessed), "unassessed_fact_keys": [],
                     "completeness": list(completeness)}
    return p


def age(comparator, years):
    return crit("inc:age", "inclusion", [cmp_atom("a", "demographics.age", comparator, {"value": years, "unit": "a"})])


# ---------------------------------------------------------------------------
# #1 Canonical packet contract — accepted through a loss-aware adapter
# ---------------------------------------------------------------------------

class TestCanonicalContract:
    @pytest.mark.parametrize("comparator, years, outcome", [
        ("ge", 18, "satisfied"),            # standard: "at least 18" is true
        ("le", 62, "unresolved"),           # standard: "at most 62" is unknown
        ("le", 50, "resolved_disqualifier"),  # standard: "at most 50" is false
    ])
    def test_standard_synthetic_example_age_band(self, comparator, years, outcome):
        r = run(pack([age(comparator, years)]), _standard_example())
        assert cr_of(r, "inc:age")["outcome"] == outcome

    def test_standard_example_unknown_performance_cannot_establish_ecog(self):
        ecog = crit("inc:ecog", "inclusion", [cmp_atom("e", "performance.status", "le", 1)])
        assert cr_of(run(pack([ecog]), _standard_example()), "inc:ecog")["outcome"] == "unresolved"

    def test_internal_schema_does_not_accept_canonical_shape(self):
        with pytest.raises(Exception):
            validate(_standard_example(), "patient_packet")

    def test_adapted_result_says_it_was_adapted_and_demo_mode(self):
        notes = run(pack([age("ge", 18)]), _standard_example())["notes"]
        assert any("adapted avicenna.patient-packet/1.1.0" in n for n in notes)
        assert any("mode=shifted_demo" in n for n in notes)

    def test_unexpected_field_rejected_not_interpreted(self):
        p = _standard_example()
        p["facts"][0]["eligible"] = True
        with pytest.raises(StructuralError):
            adapter.adapt(p)

    def test_shifted_demo_cannot_allow_absolute_recency(self):
        p = _standard_example()
        p["evaluation_context"]["absolute_screening_recency_allowed"] = True
        with pytest.raises(StructuralError):
            adapter.adapt(p)

    def test_reduced_precision_and_basis_preserved(self):
        p = cpacket([cfact("dx", "disease.metastatic", {"kind": "boolean", "value": True},
                           t=_tp("2026-02", "month"))])
        internal, _ = adapter.adapt(p)
        assert internal["facts"][0]["effective_time"] == {
            "timestamp": "2026-02-01T00:00:00Z", "precision": "month", "time_basis": "shifted_patient_local"}
        assert internal["evaluation_context"]["anchor"]["precision"] == "day"

    def test_unsupported_kind_becomes_indeterminate_with_recorded_loss(self):
        stage = {"kind": "stage", "system": "AJCC", "edition": "8", "stage_group": "IV", "t": None, "n": None,
                 "m": "M1", "disease_fact_ref": "dx"}
        internal, report = adapter.adapt(cpacket([cfact("st", "disease.stage", stage)]))
        f = internal["facts"][0]
        assert (f["state"], f["value"], f["assertion"]) == ("indeterminate", None, None)
        assert {"where": "fact st.value", "code": "stage_not_supported_by_matcher"} in report["losses"]

    def test_exclusive_interval_widened_never_narrowed(self):
        v = {"kind": "interval", "lower": 60, "upper": 64.5, "lower_inclusive": False, "upper_inclusive": True,
             "unit": "years"}
        internal, report = adapter.adapt(cpacket([cfact("ag", "demographics.age", v)]))
        assert internal["facts"][0]["value"] == {"kind": "band", "lower_inclusive": 60, "upper_inclusive": 65,
                                                 "unit": "a"}
        assert report["losses"][0]["code"] == "interval_widened_to_integer_band"

    def test_inequality_lab_is_a_one_sided_band(self):
        v = {"kind": "quantity", "value": 60, "comparator": "gt", "unit_original": "mL/min/1.73m2",
             "ucum_code": "mL/min/{1.73_m2}", "normalization_status": "validated"}
        egfr = lambda c, t: crit("inc:g", "inclusion", [cmp_atom("g", "lab.egfr", c, {"value": t, "unit": "mL/min/{1.73_m2}"})])
        p = cpacket([cfact("g", "lab.egfr", v, t=_tp("2026-03-30"))])
        assert cr_of(run(pack([egfr("ge", 50)]), p), "inc:g")["outcome"] == "satisfied"
        assert cr_of(run(pack([egfr("ge", 90)]), p), "inc:g")["outcome"] == "unresolved"

    def test_unitless_band_never_meets_unit_threshold(self):
        v = {"kind": "integer", "value": 70}
        p = cpacket([cfact("ag", "demographics.age", v)])
        assert cr_of(run(pack([age("ge", 18)]), p), "inc:age")["reason_code"] == "unit_mismatch"


# ---------------------------------------------------------------------------
# #2 not_exists checks concept membership before treating evidence as exposure
# ---------------------------------------------------------------------------

SERD_Q = crit("exc:serd", "exclusion", [atom(
    "n", "not_exists", "Prior SERD for advanced disease", fact_key="tx.serd",
    scope={"time_extent": "lifetime", "setting": "advanced", "concepts": ["SERD"],
           "ontology_version_pin": "avicenna-seed/1.0.0"})])
ADV = {"scope_type": "setting", "setting": "advanced"}


def _incl(e):  # exclusion of "prior SERD" expressed as inclusion "no prior SERD"
    return crit("inc:noserd", "inclusion", e["atoms"])


class TestExposureMembership:
    def test_unrelated_therapy_in_same_setting_is_not_a_disqualifier(self):
        r = run(pack([_incl(SERD_Q)]), packet([fact("p", "tx.serd", coded("paclitaxel"), scope=ADV)]))
        assert cr_of(r, "inc:noserd")["outcome"] != "resolved_disqualifier"

    def test_registered_member_is_a_disqualifier(self):
        r = run(pack([_incl(SERD_Q)]), packet([fact("p", "tx.serd", coded("elacestrant"), scope=ADV)]))
        assert cr_of(r, "inc:noserd")["outcome"] == "resolved_disqualifier"

    def test_unpinned_registry_leaves_membership_unknown(self):
        q = copy.deepcopy(SERD_Q)
        q["atoms"][0]["scope"]["ontology_version_pin"] = None
        c = cr_of(run(pack([_incl(q)]), packet([fact("p", "tx.serd", coded("elacestrant"), scope=ADV)])), "inc:noserd")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "exposure_membership_unknown")

    def test_prescription_alone_is_not_an_administered_exposure(self):
        ev = lambda kind: {"kind": "therapy_event", "agents": [{"system": "local", "code": "elacestrant"}],
                           "classes": [], "intent": "advanced", "evidence_kind": kind}
        r = run(pack([_incl(SERD_Q)]), packet([fact("p", "tx.serd", ev("prescription"))]))
        assert cr_of(r, "inc:noserd")["outcome"] == "unresolved"
        r = run(pack([_incl(SERD_Q)]), packet([fact("p", "tx.serd", ev("administration"))]))
        assert cr_of(r, "inc:noserd")["outcome"] == "resolved_disqualifier"


# ---------------------------------------------------------------------------
# #3 Same-day recency keeps effective-time precision
# ---------------------------------------------------------------------------

ECOG = crit("inc:ecog", "inclusion", [cmp_atom("e", "performance.ecog", "le", 1, relation="current")])


class TestSameDayRecency:
    def test_fact_precision_orders_within_a_day(self):
        assert fact_precision(datetime(2026, 2, 20, 15), None) > fact_precision(datetime(2026, 2, 20, 8), None)

    def test_newer_same_day_fact_beats_older_reviewed_fact(self):
        facts = [fact("old", "performance.ecog", band(3, 3), t="2026-02-20T08:00:00Z", review="reviewed"),
                 fact("new", "performance.ecog", band(1, 1), t="2026-02-20T15:00:00Z")]
        c = cr_of(run(pack([ECOG]), packet(facts)), "inc:ecog")
        assert c["outcome"] == "satisfied"
        assert {r["fact_id"] for r in c["fact_references"]} == {"new"}

    def test_day_precision_same_day_is_contemporaneous_authority_decides(self):
        facts = [fact("rev", "performance.ecog", band(1, 1), review="reviewed"),
                 fact("unrev", "performance.ecog", band(3, 3), t="2026-02-20T15:00:00Z")]
        facts[0]["effective_time"] = {"timestamp": "2026-02-20T00:00:00Z", "precision": "day"}
        assert cr_of(run(pack([ECOG]), packet(facts)), "inc:ecog")["outcome"] == "satisfied"

    def test_contemporaneous_equal_authority_disagreement_is_conflict(self):
        facts = [fact("a", "performance.ecog", band(1, 1)), fact("b", "performance.ecog", band(3, 3), t="2026-02-20T15:00:00Z")]
        facts[0]["effective_time"] = {"timestamp": "2026-02-20T00:00:00Z", "precision": "day"}
        c = cr_of(run(pack([ECOG]), packet(facts)), "inc:ecog")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "fact_conflict")


# ---------------------------------------------------------------------------
# #4 Zero applicable hard criteria never yields a positive label
# ---------------------------------------------------------------------------

class TestEmptyGate:
    def test_aggregator_empty_arm_is_manual_review(self):
        state, _, _, _ = PerArmAggregator.aggregate([], "A", "complete")
        assert getattr(state, "value", state) == "manual_review"

    def test_arm_with_no_applicable_hard_criteria_end_to_end(self):
        arms = [{"arm_id": "A", "arm_name": "A", "study_type": "interventional"},
                {"arm_id": "B", "arm_name": "B", "study_type": "interventional"}]
        only_a = crit("inc:a", "inclusion", [cmp_atom("x", "dx.her2", "eq", True)], arm_scope="A")
        r = run(pack([only_a], arms=arms), packet([fact("h", "dx.her2", False, assertion="explicit_negative")]))
        arm_b = next(a for a in r["per_arm_results"] if a["arm_id"] == "B")
        assert arm_b["arm_eligibility_state"] == "manual_review"
        assert arm_b["evidence_coverage"]["applicable_count"] == 0
        assert r["trial_eligibility_state"] != "eligible_pending_review"


# ---------------------------------------------------------------------------
# #5 Time precision and time basis are enforced
# ---------------------------------------------------------------------------

MI = lambda q="exists": crit("exc:mi", "exclusion", [cmp_atom(
    "m", "dx.mi", "eq", True, relation="within_days_before_anchor", window_days=183, quantifier=q)])


class TestTimeBasisAndPrecision:
    def _at(self, ts, precision=None, basis=None):
        t = {"timestamp": ts}
        if precision:
            t["precision"] = precision
        if basis:
            t["time_basis"] = basis
        return t

    def test_shifted_fact_vs_unshifted_anchor_is_unknown(self):
        f = fact("x", "performance.ecog", band(1, 1))
        f["effective_time"] = self._at("2026-02-20T00:00:00Z", "day", "shifted_patient_local")
        p = packet([f])
        p["evaluation_context"]["anchor"] = self._at(ANCHOR, "day", "unshifted_verified")
        k = crit("inc:e", "inclusion", [cmp_atom("e", "performance.ecog", "le", 1, relation="at_screening")])
        c = cr_of(run(pack([k]), p), "inc:e")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "time_basis_incompatible")

    def test_unknown_basis_never_compares(self):
        f = fact("x", "performance.ecog", band(1, 1))
        f["effective_time"] = self._at("2026-02-20T00:00:00Z", "day", "unknown")
        p = packet([f])
        p["evaluation_context"]["anchor"] = self._at(ANCHOR, "day", "unknown")
        k = crit("inc:e", "inclusion", [cmp_atom("e", "performance.ecog", "le", 1, relation="at_screening")])
        assert cr_of(run(pack([k]), p), "inc:e")["outcome"] == "unresolved"

    def test_month_precision_straddling_window_edge_is_unknown(self):
        f = fact("mi", "dx.mi", True)
        f["effective_time"] = self._at("2025-08-01T00:00:00Z", "month")   # Aug 2025 vs window from ~Aug 30
        c = cr_of(run(pack([MI()]), packet([f])), "exc:mi")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "time_precision_insufficient")

    def test_month_precision_wholly_inside_window_triggers(self):
        f = fact("mi", "dx.mi", True)
        f["effective_time"] = self._at("2025-12-01T00:00:00Z", "month")
        assert cr_of(run(pack([MI()]), packet([f])), "exc:mi")["outcome"] == "resolved_disqualifier"

    def test_month_precision_in_anchor_month_may_postdate_anchor(self):
        f = fact("x", "performance.ecog", band(1, 1))
        f["effective_time"] = self._at("2026-03-01T00:00:00Z", "month")
        p = packet([f], anchor="2026-03-10T00:00:00Z")
        k = crit("inc:e", "inclusion", [cmp_atom("e", "performance.ecog", "le", 1, relation="at_screening")])
        assert cr_of(run(pack([k]), p), "inc:e")["reason_code"] == "time_precision_insufficient"

    def test_canonical_month_precision_is_not_flattened(self):
        p = cpacket([cfact("mi", "dx.mi", {"kind": "boolean", "value": True}, t=_tp("2025-08", "month"))],
                    anchor=_tp("2026-03-01"), assessed=())
        assert cr_of(run(pack([MI()]), p), "exc:mi")["reason_code"] == "time_precision_insufficient"


# ---------------------------------------------------------------------------
# #6 Packet-level completeness: consumed only when scoped, compatible and authorized
# ---------------------------------------------------------------------------

POLICY = {"policy_version": "auth-policy-syn-1", "human_reviewers": ["syn-reviewer"]}
NO_ELA = crit("inc:noela", "inclusion", [atom(
    "n", "not_exists", "No prior elacestrant", fact_key="therapy.event",
    scope={"time_extent": "lifetime", "concepts": ["elacestrant"]})])


def completeness(**over):
    c = {
        "assertion_id": "syn-recon-1", "fact_key": "therapy.event",
        "scope": {"concepts": {"system": "urn:synthetic:therapy", "registry_version": "1", "classes": [],
                               "agents": ["elacestrant"]},
                  "disease_setting": "all_settings", "disease_scope": "all_diseases", "disease_fact_ref": None,
                  "time": {"extent": "lifetime", "time_basis": "shifted_patient_local",
                           "through": _tp("2026-04-01")}},
        "method": "reviewed_reconciliation",
        "authorization": {"kind": "human", "reviewer_id": "syn-reviewer", "reviewed_at": "2026-10-17T09:00:00Z"},
        "evidence": copy.deepcopy(EVIDENCE), "reconciled_sources": ["syn-treatment-record"],
        "source_snapshot_ref": "synthetic-fixtures-v1", "reconciliation_policy_version": "syn-recon-v1",
    }
    for k, v in over.items():
        if k in c["scope"]:
            c["scope"][k] = v
        else:
            c[k] = v
    return c


def _noela(comp, policy=POLICY, anchor=None):
    ctx = {"authorization_policy": policy} if policy else None
    return cr_of(run(pack([NO_ELA]), cpacket([], [comp], anchor=anchor), ctx), "inc:noela")


class TestCompleteness:
    def test_authorized_subsuming_completeness_clears(self):
        c = _noela(completeness())
        assert c["outcome"] == "satisfied"
        assert {"fact_id": "syn-recon-1", "fact_key": "therapy.event", "role": "completeness"} in c["fact_references"]

    def test_completeness_defaults_to_unresolved_without_local_policy(self):
        assert _noela(completeness(), policy=None)["outcome"] == "unresolved"

    def test_populated_reviewer_string_alone_proves_nothing(self):
        c = completeness(authorization={"kind": "human", "reviewer_id": "self-approved",
                                        "reviewed_at": "2026-10-17T09:00:00Z"})
        assert _noela(c)["outcome"] == "unresolved"

    def test_snapshot_mismatch_is_a_validation_error(self):
        with pytest.raises(StructuralError):
            adapter.adapt(cpacket([], [completeness(source_snapshot_ref="other")]), POLICY)

    def test_unassessed_fact_key_is_a_validation_error(self):
        with pytest.raises(StructuralError):
            adapter.adapt(cpacket([], [completeness()], assessed=()), POLICY)

    def test_lifetime_cutoff_before_anchor_does_not_clear(self):
        c = completeness(time={"extent": "lifetime", "time_basis": "shifted_patient_local",
                               "through": _tp("2026-01-01")})
        assert _noela(c)["outcome"] == "unresolved"

    def test_cutoff_on_other_time_basis_does_not_clear(self):
        c = completeness(time={"extent": "lifetime", "time_basis": "unshifted_verified",
                               "through": _tp("2026-04-01", basis="unshifted_verified")})
        assert _noela(c)["outcome"] == "unresolved"

    def test_bounded_completeness_never_clears_lifetime(self):
        c = completeness(time={"extent": "bounded", "interval": {"kind": "interval", "start": _tp("2000-01-01"),
                                                                  "end": _tp("2026-04-01")}})
        assert _noela(c)["outcome"] == "unresolved"

    def test_referenced_disease_scope_does_not_cover_unscoped_criterion(self):
        p = cpacket([cfact("dx1", "disease.primary", {"kind": "coded", "system": "local", "code": "C50"})],
                    [completeness(disease_scope="referenced_disease", disease_fact_ref="dx1")])
        c = cr_of(run(pack([NO_ELA]), p, {"authorization_policy": POLICY}), "inc:noela")
        assert c["outcome"] == "unresolved"

    def test_single_setting_does_not_cover_setting_agnostic_query(self):
        assert _noela(completeness(disease_setting="advanced"))["outcome"] == "unresolved"

    def test_known_exposure_beats_completeness(self):
        ev = {"kind": "therapy_event", "agents": [{"system": "local", "code": "elacestrant"}], "classes": [],
              "evidence_kind": "administration", "line": None, "line_context": None, "intent": "advanced",
              "start": None, "end": None, "progression_time": None, "best_response": None,
              "disease_fact_ref": None}
        p = cpacket([cfact("tx", "therapy.event", ev)], [completeness()])
        c = cr_of(run(pack([NO_ELA]), p, {"authorization_policy": POLICY}), "inc:noela")
        assert c["outcome"] == "resolved_disqualifier"


# ---------------------------------------------------------------------------
# #7 Reference ranges need explicit linkage, not equal timestamps
# ---------------------------------------------------------------------------

ALT_KEY = crit("inc:alt", "inclusion", [atom("r", "relative_to_reference", fact_key="lab.alt",
                                             reference_key="lab.alt.uln", comparator="le", threshold=2.5)])
ALT_Q = crit("inc:alt", "inclusion", [atom("r", "relative_to_reference", fact_key="lab.alt",
                                           reference_qualifier="reference_high", comparator="le", threshold=2.5)])


class TestReferenceLinkage:
    def test_equal_timestamps_without_linkage_is_reference_missing(self):
        facts = [fact("a", "lab.alt", qty(40, "U/L")), fact("u", "lab.alt.uln", qty(40, "U/L"))]
        assert cr_of(run(pack([ALT_KEY]), packet(facts)), "inc:alt")["reason_code"] == "reference_missing"

    def test_other_specimen_is_reference_missing(self):
        facts = [fact("a", "lab.alt", qty(40, "U/L"), qualifiers={"specimen_ref": "s1"}),
                 fact("u", "lab.alt.uln", qty(40, "U/L"), qualifiers={"specimen_ref": "s2"})]
        assert cr_of(run(pack([ALT_KEY]), packet(facts)), "inc:alt")["reason_code"] == "reference_missing"

    def test_same_specimen_evaluates(self):
        facts = [fact("a", "lab.alt", qty(40, "U/L"), qualifiers={"specimen_ref": "s1"}),
                 fact("u", "lab.alt.uln", qty(40, "U/L"), qualifiers={"specimen_ref": "s1"},
                      t="2026-01-01T00:00:00Z")]
        assert cr_of(run(pack([ALT_KEY]), packet(facts)), "inc:alt")["outcome"] == "satisfied"

    def test_assay_disagreement_breaks_linkage(self):
        facts = [fact("a", "lab.alt", qty(40, "U/L"), qualifiers={"specimen_ref": "s1", "assay": "m1"}),
                 fact("u", "lab.alt.uln", qty(40, "U/L"), qualifiers={"specimen_ref": "s1", "assay": "m2"})]
        assert cr_of(run(pack([ALT_KEY]), packet(facts)), "inc:alt")["reason_code"] == "reference_missing"

    def test_same_fact_reference_qualifier(self):
        q = {"reference_high": 40, "reference_ucum_code": "U/L"}
        assert cr_of(run(pack([ALT_Q]), packet([fact("a", "lab.alt", qty(90, "U/L"), qualifiers=q)])),
                     "inc:alt")["outcome"] == "satisfied"
        assert cr_of(run(pack([ALT_Q]), packet([fact("a", "lab.alt", qty(120, "U/L"), qualifiers=q)])),
                     "inc:alt")["outcome"] == "resolved_disqualifier"

    def test_reference_qualifier_unit_must_match(self):
        q = {"reference_high": 0.67, "reference_ucum_code": "ukat/L"}
        c = cr_of(run(pack([ALT_Q]), packet([fact("a", "lab.alt", qty(90, "U/L"), qualifiers=q)])), "inc:alt")
        assert c["reason_code"] == "unit_mismatch"

    def test_reference_qualifier_without_unit_is_missing(self):
        c = cr_of(run(pack([ALT_Q]), packet([fact("a", "lab.alt", qty(90, "U/L"),
                                                  qualifiers={"reference_high": 40})])), "inc:alt")
        assert c["reason_code"] == "reference_missing"


# ---------------------------------------------------------------------------
# #8 Windowed predicates require an explicit quantifier
# ---------------------------------------------------------------------------

class TestWindowQuantifier:
    def _facts(self):
        return [fact("old", "dx.mi", True, t="2025-12-01T00:00:00Z"),
                fact("new", "dx.mi", False, assertion="explicit_negative", t="2026-02-20T00:00:00Z")]

    def test_missing_quantifier_is_unknown(self):
        k = crit("exc:mi", "exclusion", [cmp_atom("m", "dx.mi", "eq", True, relation="within_days_before_anchor",
                                                  window_days=183)])
        c = cr_of(run(pack([k]), packet(self._facts())), "exc:mi")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "window_quantifier_unspecified")

    def test_exists_any_qualifying_fact_in_window(self):
        assert cr_of(run(pack([MI("exists")]), packet(self._facts())), "exc:mi")["outcome"] == "resolved_disqualifier"

    def test_latest_uses_most_recent_fact_in_window(self):
        assert cr_of(run(pack([MI("latest")]), packet(self._facts())), "exc:mi")["outcome"] == "clear"


class TestMutationGaps:
    """Tests added after mutation testing showed these behaviours were unpinned."""

    def _internal_with_completeness(self, authorized_under):
        p = packet([])
        p["coverage"]["completeness"] = [{
            "assertion_id": "c1", "fact_key": "therapy.event", "authorized_under": authorized_under,
            "scope": {"scope_type": "reviewed_reconciliation", "completeness": "complete", "time_basis": "lifetime",
                      "agents": ["elacestrant"], "classes": [], "settings": ["all_settings"],
                      "disease_scope": "all_diseases"}}]
        return p

    @pytest.mark.parametrize("ctx, outcome", [
        (None, "unresolved"),                                                  # no pinned policy supplied
        ({"authorization_policy": {"policy_version": "other"}}, "unresolved"),  # different policy
        ({"authorization_policy": {"policy_version": "auth-1"}}, "satisfied"),
    ])
    def test_internal_completeness_requires_the_same_pinned_policy(self, ctx, outcome):
        r = run(pack([NO_ELA]), self._internal_with_completeness("auth-1"), ctx)
        assert cr_of(r, "inc:noela")["outcome"] == outcome

    def test_fractional_interval_bound_widens_outward(self):
        v = {"kind": "interval", "lower": 59.5, "upper": 64, "lower_inclusive": True, "upper_inclusive": True,
             "unit": "years"}
        p = cpacket([cfact("ag", "demographics.age", v)], assessed=())
        assert cr_of(run(pack([age("ge", 60)]), p), "inc:age")["outcome"] == "unresolved"
        assert cr_of(run(pack([age("ge", 59)]), p), "inc:age")["outcome"] == "satisfied"

    def test_untimed_fact_disagreeing_with_timed_fact_is_unknown(self):
        untimed = fact("u", "performance.ecog", band(3, 3), t=None)
        timed = fact("t", "performance.ecog", band(1, 1))
        c = cr_of(run(pack([ECOG]), packet([untimed, timed])), "inc:ecog")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "time_precision_insufficient")

    def test_untimed_fact_agreeing_or_alone_is_usable(self):
        untimed = fact("u", "performance.ecog", band(1, 1), t=None)
        assert cr_of(run(pack([ECOG]), packet([untimed])), "inc:ecog")["outcome"] == "satisfied"
        timed = fact("t", "performance.ecog", band(1, 1))
        assert cr_of(run(pack([ECOG]), packet([untimed, timed])), "inc:ecog")["outcome"] == "satisfied"
