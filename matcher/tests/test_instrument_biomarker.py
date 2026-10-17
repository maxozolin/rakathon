"""Scored instruments, biomarker concepts and multi-denial not_exists.

Expected values come from PATIENT_MATCHING_FORMAT_STANDARD.md (scored_instrument shape,
biomarker.result, scoped_absence) and MATCHER_DESIGN.md §5.4. All inputs synthetic.
"""

import copy

import pytest

from avicenna_matcher import adapter
from avicenna_matcher.errors import StructuralError
from test_p6_pipeline_cli import atom, cmp_atom, cr_of, crit, pack, run
from test_review2_regressions import _tp, cfact, cpacket

LOINC = "http://loinc.org"


def ecog_value(score, *, code="89247-1", registry="avicenna-instruments/1.0.0", scale=(0, 4, 1), high=None):
    return {"kind": "scored_instrument", "instrument": {"system": LOINC, "code": code},
            "registry_version": registry, "representation": "numeric", "no_interconversion": True,
            "value": score, "value_high": high, "scale_min": scale[0], "scale_max": scale[1], "step": scale[2]}


KPS = dict(code="89243-0", scale=(0, 100, 10))
ECOG_LE1 = crit("inc:ecog", "inclusion", [cmp_atom("e", "performance.status", "le", {"value": 1, "unit": "{ECOG}"},
                                                         relation="at_screening", window_days=28)])
KPS_GE70 = crit("inc:kps", "inclusion", [cmp_atom("k", "performance.status", "ge", {"value": 70, "unit": "{Karnofsky}"},
                                                       relation="at_screening", window_days=28)])


def ps_packet(value):
    return cpacket([cfact("ps", "performance.status", value, t=_tp("2026-03-30"))], assessed=("performance.status",))


class TestScoredInstrument:
    @pytest.mark.parametrize("score, outcome", [(0, "satisfied"), (1, "satisfied"), (2, "resolved_disqualifier")])
    def test_ecog_threshold(self, score, outcome):
        assert cr_of(run(pack([ECOG_LE1]), ps_packet(ecog_value(score))), "inc:ecog")["outcome"] == outcome

    def test_ecog_interval_straddling_threshold_is_unresolved(self):
        c = cr_of(run(pack([ECOG_LE1]), ps_packet(ecog_value(1, high=2))), "inc:ecog")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "value_straddles_threshold")

    def test_karnofsky_never_answers_ecog_and_vice_versa(self):
        c = cr_of(run(pack([ECOG_LE1]), ps_packet(ecog_value(90, **KPS))), "inc:ecog")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "unit_mismatch")
        c = cr_of(run(pack([KPS_GE70]), ps_packet(ecog_value(0))), "inc:kps")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "unit_mismatch")

    def test_karnofsky_against_karnofsky_threshold(self):
        assert cr_of(run(pack([KPS_GE70]), ps_packet(ecog_value(80, **KPS))), "inc:kps")["outcome"] == "satisfied"

    @pytest.mark.parametrize("over", [{"registry": "other-registry/9"}, {"code": "99999-9"}])
    def test_unpinned_instrument_is_indeterminate_with_loss(self, over):
        internal, report = adapter.adapt(ps_packet(ecog_value(1, **over)))
        assert internal["facts"][0]["state"] == "indeterminate"
        assert any(l["code"] == "instrument_not_in_pinned_registry" for l in report["losses"])

    @pytest.mark.parametrize("value", [
        ecog_value(5),                         # off scale
        ecog_value(1.5),                       # off step grid
        ecog_value(1, scale=(0, 5, 1)),        # scale chosen by the extractor
        ecog_value(2, high=1),                 # inverted interval
        ecog_value(75, **KPS),                 # Karnofsky off its 10-step grid
    ])
    def test_structurally_invalid_scores_rejected(self, value):
        with pytest.raises(StructuralError):
            adapter.adapt(ps_packet(value))

    def test_ordinal_representation_not_guessed(self):
        v = {"kind": "scored_instrument", "instrument": {"system": LOINC, "code": "89247-1"},
             "registry_version": "avicenna-instruments/1.0.0", "representation": "ordinal",
             "no_interconversion": True, "ordinal_code": "LA9623-5", "ordinal_code_high": None}
        assert adapter.adapt(ps_packet(v))[0]["facts"][0]["state"] == "indeterminate"


M, R = "syn-marker", "syn-result"


def marker_fact(fid, code, result):
    return cfact(fid, "biomarker.result", {"kind": "biomarker", "marker": {"system": M, "code": code},
                                           "result": {"system": R, "code": result}, "assay": None,
                                           "specimen_ref": None, "disease_fact_ref": None}, t=_tp("2026-03-30"))


def marker_crit(code, result="detected", concept=True):
    kw = {"concept": {"system": M, "code": code}} if concept else {}
    return crit("inc:m", "inclusion", [cmp_atom("m", "biomarker.result", "eq", {"system": R, "code": result}, **kw)])


class TestBiomarkerConcept:
    def test_marker_becomes_fact_concept(self):
        f = adapter.adapt(cpacket([marker_fact("k", "KRAS", "detected")]))[0]["facts"][0]
        assert (f["concept"]["code"], f["value"]["code"]) == ("KRAS", "detected")

    def test_other_marker_never_answers(self):
        p = cpacket([marker_fact("k", "KRAS", "detected")])
        c = cr_of(run(pack([marker_crit("FGFR3")]), p), "inc:m")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "fact_missing")

    def test_matching_marker_answers_despite_newer_other_marker(self):
        newer = marker_fact("k", "KRAS", "not_detected")
        newer["effective_time"] = _tp("2026-03-31")
        p = cpacket([marker_fact("f", "FGFR3", "detected"), newer])
        assert cr_of(run(pack([marker_crit("FGFR3")]), p), "inc:m")["outcome"] == "satisfied"
        p = cpacket([marker_fact("f", "FGFR3", "not_detected"), marker_fact("k", "KRAS", "detected")])
        assert cr_of(run(pack([marker_crit("FGFR3")]), p), "inc:m")["outcome"] == "resolved_disqualifier"

    @pytest.mark.parametrize("key", ["biomarker.result", "lab.result"])
    def test_generic_key_without_concept_is_unresolved(self, key):
        c = crit("inc:m", "inclusion", [cmp_atom("m", key, "eq", {"system": R, "code": "detected"})])
        cr = cr_of(run(pack([c]), cpacket([marker_fact("k", "KRAS", "detected")])), "inc:m")
        assert (cr["outcome"], cr["reason_code"]) == ("unresolved", "concept_unspecified")


def absence(fid, setting, agents=(), classes=()):
    scope = {"concepts": {"system": "local", "registry_version": "avicenna-seed/1.0.0",
                          "classes": list(classes), "agents": list(agents)},
             "disease_setting": setting, "disease_fact_ref": None, "disease_scope": "all_diseases",
             "time": {"extent": "lifetime", "time_basis": "shifted_patient_local", "through": _tp("2026-04-01")}}
    return cfact(fid, "therapy.event", {"kind": "scoped_absence", "absent": True}, assertion="explicit_negative",
                 review="reviewed", scope=scope)


def no_prior(concepts, setting=None):
    scope = {"time_extent": "lifetime", "concepts": concepts, "ontology_version_pin": "avicenna-seed/1.0.0"}
    if setting:
        scope["setting"] = setting
    return crit("inc:n", "inclusion", [atom("n", "not_exists", "no prior", fact_key="therapy.event", scope=scope)])


class TestMultipleDenials:
    def test_a_non_subsuming_denial_does_not_veto_a_subsuming_one(self):
        q = no_prior(["sotorasib", "adagrasib"])
        unrelated = absence("a", "advanced", classes=["chemotherapy"])
        right = absence("b", "all_settings", agents=["sotorasib", "adagrasib"])
        for facts in ([unrelated, right], [right, unrelated]):
            assert cr_of(run(pack([q]), cpacket(facts)), "inc:n")["outcome"] == "satisfied"

    def test_only_non_subsuming_denials_stay_unresolved(self):
        q = no_prior(["sotorasib", "adagrasib"])
        c = cr_of(run(pack([q]), cpacket([absence("a", "advanced", classes=["chemotherapy"])])), "inc:n")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "absence_not_established")

    def test_partial_agent_denial_does_not_clear(self):
        q = no_prior(["sotorasib", "adagrasib"])
        c = cr_of(run(pack([q]), cpacket([absence("a", "all_settings", agents=["sotorasib"])])), "inc:n")
        assert c["outcome"] == "unresolved"

    def test_class_denial_clears_identical_class_query(self):
        q = no_prior(["chemotherapy", "adc"], "advanced")
        p = cpacket([absence("a", "advanced", classes=["chemotherapy", "adc"])])
        assert cr_of(run(pack([q]), p), "inc:n")["outcome"] == "satisfied"

    def test_denial_never_beats_a_qualifying_exposure(self):
        q = no_prior(["sotorasib"])
        ev = cfact("x", "therapy.event", {
            "kind": "therapy_event", "agents": [{"system": "local", "code": "sotorasib"}], "classes": [],
            "evidence_kind": "administration", "line": None, "line_context": None, "intent": "advanced",
            "start": None, "end": None, "progression_time": None, "best_response": None,
            "disease_fact_ref": None}, t=_tp("2025-06-01"))
        p = cpacket([absence("a", "all_settings", agents=["sotorasib"]), ev])
        assert cr_of(run(pack([q]), p), "inc:n")["outcome"] == "resolved_disqualifier"


C = "syn-condition"


def cond_fact(fid, code, negated=False, t="2026-03-25"):
    return cfact(fid, "disease.condition", {"kind": "coded", "system": C, "code": code},
                 assertion="explicit_negative" if negated else "positive", t=_tp(t))


def cond_excl(*codes, relation="ever", comparator="eq"):
    if comparator == "in_set":
        atoms = [cmp_atom("c", "disease.condition", "in_set", [{"system": C, "code": c} for c in codes],
                          relation=relation)]
    else:
        atoms = [cmp_atom(f"c{i}", "disease.condition", comparator, {"system": C, "code": c}, relation=relation)
                 for i, c in enumerate(codes)]
    return crit("exc:c", "exclusion", atoms, logic="any" if len(atoms) > 1 else None)


class TestConditionKeys:
    """disease.condition / safety.condition: one fact per condition; the code is the identity."""

    @pytest.mark.parametrize("relation", ["ever", "current"])
    def test_negation_of_another_condition_is_not_evidence(self, relation):
        p = cpacket([cond_fact("a", "pneumonitis", negated=True)])
        c = cr_of(run(pack([cond_excl("lepto", relation=relation)]), p), "exc:c")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "fact_missing")

    def test_negations_of_different_conditions_are_not_a_conflict(self):
        p = cpacket([cond_fact("a", "pneumonitis", negated=True), cond_fact("b", "lepto", negated=True),
                     cond_fact("c", "fibrosis", negated=True)])
        assert cr_of(run(pack([cond_excl("lepto", relation="current")]), p), "exc:c")["outcome"] == "clear"
        assert cr_of(run(pack([cond_excl("pneumonitis", "fibrosis")]), p), "exc:c")["outcome"] == "clear"

    def test_latest_fact_about_another_condition_does_not_shadow(self):
        p = cpacket([cond_fact("a", "lepto", t="2026-01-01"), cond_fact("b", "pneumonitis", negated=True)])
        c = cr_of(run(pack([cond_excl("lepto", relation="current")]), p), "exc:c")
        assert c["outcome"] == "resolved_disqualifier"

    def test_positive_in_set_member_triggers(self):
        p = cpacket([cond_fact("a", "fibrosis")])
        c = cr_of(run(pack([cond_excl("pneumonitis", "fibrosis", comparator="in_set")]), p), "exc:c")
        assert c["outcome"] == "resolved_disqualifier"

    def test_one_negated_member_does_not_clear_a_set(self):
        p = cpacket([cond_fact("a", "fibrosis", negated=True)])
        c = cr_of(run(pack([cond_excl("pneumonitis", "fibrosis", comparator="in_set")]), p), "exc:c")
        assert c["outcome"] == "unresolved"

    def test_ne_on_condition_key_is_refused(self):
        p = cpacket([cond_fact("a", "fibrosis")])
        c = cr_of(run(pack([cond_excl("lepto", comparator="ne")]), p), "exc:c")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "value_type_unsupported")

    def test_same_code_in_another_system_is_not_the_same_condition(self):
        f = cfact("a", "disease.condition", {"kind": "coded", "system": "other-system", "code": "lepto"},
                  assertion="positive", t=_tp("2026-03-25"))
        c = cr_of(run(pack([cond_excl("lepto", relation="current")]), cpacket([f])), "exc:c")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "fact_missing")


def lab_fact(fid, loinc, value, *, high=None, t="2026-03-30"):
    q = {"reference_high": high, "reference_ucum_code": "U/L"} if high is not None else None
    return cfact(fid, "lab.result", {"kind": "quantity", "value": value, "comparator": "eq", "unit_original": "U/L",
                                     "ucum_code": "U/L", "normalization_status": "validated"},
                 t=_tp(t), concept={"system": LOINC, "code": loinc}, qualifiers=q)


ALT, AST = "1742-6", "1920-8"


def alt_uln(concept=True):
    kw = {"concept": {"system": LOINC, "code": ALT}} if concept else {}
    return crit("inc:alt", "inclusion", [atom("r", "relative_to_reference", "ALT ≤ 2.5 × ULN", fact_key="lab.result",
                                              reference_qualifier="reference_high", comparator="le",
                                              threshold=2.5, relation="at_screening", window_days=28, **kw)])


class TestGenericKeysElsewhere:
    def test_relative_reference_reads_only_the_queried_analyte(self):
        p = cpacket([lab_fact("alt", ALT, 50, high=40, t="2026-03-29"), lab_fact("ast", AST, 500, high=40)])
        assert cr_of(run(pack([alt_uln()]), p), "inc:alt")["outcome"] == "satisfied"
        p = cpacket([lab_fact("alt", ALT, 500, high=40, t="2026-03-29"), lab_fact("ast", AST, 50, high=40)])
        assert cr_of(run(pack([alt_uln()]), p), "inc:alt")["outcome"] == "resolved_disqualifier"

    def test_relative_reference_without_concept_is_unresolved(self):
        p = cpacket([lab_fact("alt", ALT, 50, high=40)])
        c = cr_of(run(pack([alt_uln(concept=False)]), p), "inc:alt")
        assert (c["outcome"], c["reason_code"]) == ("unresolved", "concept_unspecified")

    @pytest.mark.parametrize("key, value", [
        ("disease.condition", {"kind": "coded", "system": C, "code": "liver_mets"}),
        ("biomarker.result", None),
    ])
    def test_gate_on_multi_concept_key_never_resolves(self, key, value):
        facts = [cond_fact("lm", "liver_mets")] if key == "disease.condition" else [marker_fact("k", "KRAS", "detected")]
        gate = atom("g", "applicability_gate", "gate", gate_fact_key=key,
                    gate_value=value or {"system": R, "code": "detected"})
        c = crit("exc:g", "exclusion", [gate, cmp_atom("a", "demographics.age", "ge", {"value": 18, "unit": "a"})])
        cr = cr_of(run(pack([c]), cpacket(facts + [cfact("ag", "demographics.age",
                                                         {"kind": "integer", "value": 70, "unit": "years"})])), "exc:g")
        assert cr["outcome"] == "unresolved"
