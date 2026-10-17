"""Age is a snapshot that grows with time; existential relations do not apply to it.

Design sources:
- reports/STRONG_CANDIDATE_ENGINE_FINDINGS.md: "age <18" and not("age >=18") disagreed under any_history.
- PATIENT_MATCHING_FORMAT_STANDARD.md, synthetic example: for an age band of 60–64, "≥18" is true, "≤62" is
  unknown and "≤50" is false.
- MATCHER_DESIGN.md §4.3: anchor-relative evaluation.

All inputs are synthetic. The standard example anchor is 2026-04-01 (shifted_patient_local).
"""

import pytest

from test_p6_pipeline_cli import cmp_atom, cr_of, crit, pack, run
from test_review2_regressions import _tp, cfact, cpacket


def age_fact(lo, hi=None, t=None):
    hi = lo if hi is None else hi
    v = {"kind": "interval", "lower": lo, "upper": hi, "lower_inclusive": True, "upper_inclusive": True, "unit": "a"}
    return cfact("ag", "demographics.age", v, t=t)


def age_packet(lo, hi=None, t=None, **kw):
    return cpacket([age_fact(lo, hi, t)], assessed=("demographics.age",), **kw)


def age_crit(ctype, comparator, years, *, relation=None, logic=None):
    kw = {"relation": relation} if relation else {}
    return crit("c", ctype, [cmp_atom("a", "demographics.age", comparator, {"value": years, "unit": "a"}, **kw)],
                logic=logic)


def out(r):
    c = cr_of(r, "c")
    return c["outcome"], c["reason_code"]


class TestEncodingIndependence:
    """An adult with a documented age; exclusion: "age <18"."""

    @pytest.mark.parametrize("relation", ["any_history", "ever", "within_days_before_anchor"])
    def test_existential_relations_refused_on_age(self, relation):
        direct = run(pack([age_crit("exclusion", "lt", 18, relation=relation)]), age_packet(40))
        compl = run(pack([age_crit("exclusion", "ge", 18, relation=relation, logic="not")]), age_packet(40))
        assert out(direct) == out(compl) == ("unresolved", "relation_unsupported_for_key")

    @pytest.mark.parametrize("relation", [None, "current", "at_screening"])
    def test_point_encodings_agree(self, relation):
        direct = run(pack([age_crit("exclusion", "lt", 18, relation=relation)]), age_packet(40))
        compl = run(pack([age_crit("exclusion", "ge", 18, relation=relation, logic="not")]), age_packet(40))
        assert out(direct) == out(compl) == ("clear", None)

    def test_gender_existential_refused(self):
        c = crit("c", "inclusion", [cmp_atom("g", "demographics.administrative_gender", "eq",
                                             {"system": "syn", "code": "female"}, relation="ever")])
        p = cpacket([cfact("g", "demographics.administrative_gender",
                           {"kind": "coded", "system": "syn", "code": "female"})],
                    assessed=("demographics.administrative_gender",))
        assert out(run(pack([c]), p)) == ("unresolved", "relation_unsupported_for_key")


class TestStandardExample:
    """Untimed band of 60–64: elapsed time unknown, so only the monotone lower bound survives."""

    @pytest.mark.parametrize("ctype, comparator, years, expected", [
        ("inclusion", "ge", 18, "satisfied"),
        ("inclusion", "le", 62, "unresolved"),
        ("inclusion", "le", 50, "resolved_disqualifier"),
        ("inclusion", "le", 64, "unresolved"),        # the band was 60–64 at some time before screening
    ])
    def test_untimed_band(self, ctype, comparator, years, expected):
        assert out(run(pack([age_crit(ctype, comparator, years)]), age_packet(60, 64)))[0] == expected


class TestProjectionToAnchor:
    def test_stale_age_cannot_pass_an_upper_limit(self):
        # Aged 74 in 2020; by the 2026-04-01 anchor the patient is at least 79.
        r = run(pack([age_crit("inclusion", "le", 75)]), age_packet(74, t=_tp("2020-01-15")))
        assert out(r)[0] == "resolved_disqualifier"

    def test_recent_age_upper_limit_passes(self):
        r = run(pack([age_crit("inclusion", "le", 75)]), age_packet(70, t=_tp("2026-03-30")))
        assert out(r) == ("satisfied", None)

    def test_birthday_may_fall_in_between(self):
        # 74 one year before: now 75 or 76 → "≤ 75" is undecidable.
        r = run(pack([age_crit("inclusion", "le", 75)]), age_packet(74, t=_tp("2025-04-01")))
        assert out(r) == ("unresolved", "value_straddles_threshold")

    def test_minor_becomes_adult(self):
        r = run(pack([age_crit("inclusion", "ge", 18)]), age_packet(15, t=_tp("2019-01-01")))
        assert out(r) == ("satisfied", None)

    def test_year_precision_widens(self):
        r = run(pack([age_crit("inclusion", "le", 70)]), age_packet(69, t=_tp("2025", "year")))
        assert out(r) == ("unresolved", "value_straddles_threshold")

    def test_statement_after_anchor_is_not_evidence(self):
        p = age_packet(20, t=_tp("2030-06-01"), mode="historical_review")
        assert out(run(pack([age_crit("inclusion", "ge", 18)]), p))[0] == "unresolved"

    def test_incompatible_time_basis(self):
        r = run(pack([age_crit("inclusion", "ge", 18)]),
                age_packet(40, t=_tp("2026-01-01", basis="unshifted_verified")))
        assert out(r) == ("unresolved", "time_basis_incompatible")

    def test_historical_review_needs_timed_age(self):
        p = age_packet(40, mode="historical_review")
        assert out(run(pack([age_crit("inclusion", "ge", 18)]), p)) == ("unresolved", "time_precision_insufficient")

    def test_no_anchor_keeps_only_lower_bound(self):
        p = age_packet(40, t=_tp("2020-01-01"))
        p["evaluation_context"]["anchor"] = None
        assert out(run(pack([age_crit("inclusion", "ge", 18)]), p)) == ("satisfied", None)
        assert out(run(pack([age_crit("inclusion", "le", 75)]), p))[0] == "unresolved"
