"""Screening recency bound and per-assay biomarker selection.

Design sources:
- MATCHER_DESIGN.md §4.6: recency governs point-in-time state. A screening-state value with no recency bound is not
  "now".
- PATIENT_MATCHING_FORMAT_STANDARD.md: different specimens/assays are not interchangeable and are not a same-event
  conflict.
- reports/MANUAL_BATCH_ENGINE_FINDINGS.md: edge case 4 and "document-local performance score is not
  screening-current".

All inputs are synthetic. The standard example anchor is 2026-04-01 (shifted).
"""

import pytest

from avicenna_matcher.errors import StructuralError
from test_instrument_biomarker import ALT, LOINC, M, R, ecog_value, lab_fact
from test_p6_pipeline_cli import atom, cmp_atom, cr_of, crit, pack, run
from test_review2_regressions import _tp, age, cfact, cpacket


def ecog_crit(**kw):
    return crit("inc:ecog", "inclusion",
                [cmp_atom("e", "performance.status", "le", {"value": 1, "unit": "{ECOG}"}, **kw)])


def ps_packet(score, t):
    return cpacket([cfact("ps", "performance.status", ecog_value(score), t=_tp(t))], assessed=("performance.status",))


def outcome(r, cid):
    c = cr_of(r, cid)
    return c["outcome"], c["reason_code"]


class TestScreeningRecencyBound:
    @pytest.mark.parametrize("relation", [None, "current", "at_screening"])
    def test_unwindowed_screening_state_is_unresolved(self, relation):
        kw = {"relation": relation} if relation else {}
        r = run(pack([ecog_crit(**kw)]), ps_packet(0, "2026-03-30"))
        assert outcome(r, "inc:ecog") == ("unresolved", "recency_unbounded")

    def test_years_old_score_never_stands_for_now(self):
        # The old behaviour took the latest fact ever: a 2019 ECOG 0 satisfied the criterion.
        r = run(pack([ecog_crit()]), ps_packet(0, "2019-01-01"), {"screening_recency_days": {"performance.status": 28}})
        assert outcome(r, "inc:ecog") == ("unresolved", "fact_missing")

    def test_site_policy_window_resolves(self):
        ctx = {"screening_recency_days": {"performance.status": 28}}
        assert outcome(run(pack([ecog_crit()]), ps_packet(0, "2026-03-20"), ctx), "inc:ecog") == ("satisfied", None)
        assert outcome(run(pack([ecog_crit()]), ps_packet(3, "2026-03-20"), ctx), "inc:ecog")[0] == "resolved_disqualifier"

    def test_policy_window_boundary(self):
        ctx = {"screening_recency_days": {"performance.status": 10}}
        assert outcome(run(pack([ecog_crit()]), ps_packet(0, "2026-03-22"), ctx), "inc:ecog") == ("satisfied", None)
        assert outcome(run(pack([ecog_crit()]), ps_packet(0, "2026-03-21"), ctx), "inc:ecog")[1] == "fact_missing"

    def test_atom_window_beats_site_policy(self):
        ctx = {"screening_recency_days": {"performance.status": 365}}
        r = run(pack([ecog_crit(relation="at_screening", window_days=7)]), ps_packet(0, "2026-03-01"), ctx)
        assert outcome(r, "inc:ecog")[1] == "fact_missing"

    def test_policy_window_needs_an_anchor(self):
        p = ps_packet(0, "2026-03-30")
        p["evaluation_context"]["anchor"] = None
        r = run(pack([ecog_crit()]), p, {"screening_recency_days": {"performance.status": 28}})
        assert outcome(r, "inc:ecog") == ("unresolved", "anchor_missing")

    def test_policy_is_reported_in_notes(self):
        r = run(pack([ecog_crit()]), ps_packet(0, "2026-03-30"), {"screening_recency_days": {"performance.status": 28}})
        assert any("performance.status=28d" in n for n in r["notes"])

    def test_history_relation_is_not_bounded(self):
        r = run(pack([ecog_crit(relation="ever")]), ps_packet(0, "2019-01-01"))
        assert outcome(r, "inc:ecog") == ("satisfied", None)

    def test_non_screening_key_unaffected(self):
        p = cpacket([cfact("a", "demographics.age", {"kind": "interval", "lower": 60, "upper": 64,
                                                      "lower_inclusive": True, "upper_inclusive": True, "unit": "a"})],
                    assessed=("demographics.age",))
        assert outcome(run(pack([age("ge", 18)]), p), "inc:age") == ("satisfied", None)

    def test_relative_reference_is_bounded_too(self):
        c = crit("inc:alt", "inclusion", [atom("r", "relative_to_reference", "ALT ≤ 2.5 × ULN", fact_key="lab.result",
                                               concept={"system": LOINC, "code": ALT}, comparator="le", threshold=2.5,
                                               reference_qualifier="reference_high")])
        p = cpacket([lab_fact("alt", ALT, 50, high=40)])
        assert outcome(run(pack([c]), p), "inc:alt") == ("unresolved", "recency_unbounded")
        assert outcome(run(pack([c]), p, {"screening_recency_days": {"lab.result": 14}}), "inc:alt") == ("satisfied", None)

    def test_gate_on_screening_key_is_unresolved_without_bound(self):
        c = crit("inc:contra", "inclusion", [
            atom("g", "applicability_gate", "if pregnant", gate_fact_key="safety.pregnant", gate_value=True),
            cmp_atom("a", "demographics.age", "ge", {"value": 18, "unit": "a"})])
        p = cpacket([cfact("preg", "safety.pregnant", {"kind": "boolean", "value": True}, t=_tp("2020-01-01")),
                     cfact("a", "demographics.age", {"kind": "integer", "value": 30, "unit": "a"})],
                    assessed=("demographics.age",))
        assert cr_of(run(pack([c]), p), "inc:contra")["outcome"] == "unresolved"
        # with a 30-day policy the 2020 fact is out of window → still not "pregnant now"
        r = run(pack([c]), p, {"screening_recency_days": {"safety.pregnant": 30}})
        assert cr_of(r, "inc:contra")["outcome"] == "unresolved"

    @pytest.mark.parametrize("policy", [
        [28], {"demographics.age": 28}, {"performance.status": 0}, {"performance.status": "28"},
        {"performance.status": True},
    ])
    def test_invalid_policy_rejected(self, policy):
        with pytest.raises(StructuralError):
            run(pack([ecog_crit()]), ps_packet(0, "2026-03-30"), {"screening_recency_days": policy})


def bm(fid, result, *, assay=None, specimen=None, t="2026-03-01"):
    return cfact(fid, "biomarker.result", {"kind": "biomarker", "marker": {"system": M, "code": "PDL1"},
                                           "result": {"system": R, "code": result}, "assay": assay,
                                           "specimen_ref": specimen, "disease_fact_ref": None}, t=_tp(t))


def pdl1_crit(**kw):
    return crit("inc:m", "inclusion", [cmp_atom("m", "biomarker.result", "eq", {"system": R, "code": "positive"},
                                                concept={"system": M, "code": "PDL1"}, **kw)])


class TestAssayAwareSelection:
    def test_newer_result_on_other_assay_does_not_supersede(self):
        p = cpacket([bm("a", "positive", assay="22C3", t="2025-06-01"),
                     bm("b", "negative", assay="SP263", t="2026-03-01")])
        assert outcome(run(pack([pdl1_crit()]), p), "inc:m") == ("unresolved", "assay_discordant")

    def test_other_specimen_disagreeing_is_discordant(self):
        p = cpacket([bm("a", "positive", assay="NGS", specimen="tissue-1", t="2025-06-01"),
                     bm("b", "negative", assay="NGS", specimen="plasma-2", t="2026-03-01")])
        assert outcome(run(pack([pdl1_crit()]), p), "inc:m")[1] == "assay_discordant"

    def test_agreeing_assays_answer(self):
        p = cpacket([bm("a", "positive", assay="22C3", t="2025-06-01"),
                     bm("b", "positive", assay="SP263", t="2026-03-01")])
        assert outcome(run(pack([pdl1_crit()]), p), "inc:m") == ("satisfied", None)

    def test_same_assay_repeat_newer_wins(self):
        p = cpacket([bm("a", "positive", assay="22C3", specimen="s1", t="2025-06-01"),
                     bm("b", "negative", assay="22C3", specimen="s1", t="2026-03-01")])
        assert outcome(run(pack([pdl1_crit()]), p), "inc:m")[0] == "resolved_disqualifier"

    def test_atom_assay_constraint_selects_the_named_assay(self):
        p = cpacket([bm("a", "positive", assay="22C3", t="2025-06-01"),
                     bm("b", "negative", assay="SP263", t="2026-03-01")])
        assert outcome(run(pack([pdl1_crit(assay=["22C3"])]), p), "inc:m") == ("satisfied", None)
        assert outcome(run(pack([pdl1_crit(assay=["SP263"])]), p), "inc:m")[0] == "resolved_disqualifier"

    def test_assay_constraint_excludes_unstated_assay(self):
        p = cpacket([bm("a", "positive", t="2026-03-01")])
        assert outcome(run(pack([pdl1_crit(assay=["22C3"])]), p), "inc:m") == ("unresolved", "fact_missing")

    def test_existential_any_assay_is_enough(self):
        p = cpacket([bm("a", "positive", assay="22C3", t="2025-06-01"),
                     bm("b", "negative", assay="SP263", t="2026-03-01")])
        assert outcome(run(pack([pdl1_crit(relation="ever")]), p), "inc:m") == ("satisfied", None)


class TestBiomarkerConceptIdentity:
    def _fact(self, concept):
        f = bm("a", "positive")
        f["value"]["marker"]["display"] = "PD-L1"
        f["concept"] = concept
        return f

    def test_concept_equal_on_system_and_code_is_accepted(self):
        from avicenna_matcher import adapter
        internal, _ = adapter.adapt(cpacket([self._fact({"system": M, "code": "PDL1"})]))
        assert internal["facts"][0]["concept"]["code"] == "PDL1"

    @pytest.mark.parametrize("concept", [{"system": M, "code": "KRAS"}, {"system": "other", "code": "PDL1"}])
    def test_concept_disagreeing_with_marker_is_rejected(self, concept):
        from avicenna_matcher import adapter
        with pytest.raises(StructuralError):
            adapter.adapt(cpacket([self._fact(concept)]))
