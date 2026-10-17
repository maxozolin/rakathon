"""Design-derived ORACLE tests for study-type behavior (MATCHER_DESIGN.md §7.2).

These are written from the DESIGN, not from the implementation. They are the
gate for the healthy-volunteer (HV) inversion feature, which is currently a
stub in behaviors.py (`_apply_study_type_inversion` only annotates; it does not
invert disease polarity).

Mechanism: the HV-inversion oracles are marked `xfail(strict=True)`.
- Today the feature is unimplemented, so each oracle fails (or errors on a
  not-yet-existing parameter) → recorded as xfailed → suite stays green.
- When someone implements HV inversion correctly, the oracle will PASS, which
  under strict xfail is reported as XPASS → a FAILURE. That failure is the
  signal: "the feature now works — delete the xfail marker and promote it."

So HV inversion literally cannot be marked done until it actually inverts:
either the oracle is xfailing (not done) or it xpasses and forces the marker's
removal (done, and now a normal green test).

§7.2 (design): "Healthy-volunteer trials invert disease logic (inclusion =
absence of significant disease). Observational / analytical studies are not
treatment candidacy and MUST be labeled as such."
"""

import pytest
from avicenna_matcher import OutcomeEvaluator, PerArmMatcher, TriState, Outcome


# --- Control: interventional trials must NOT invert (passes today) -----------

class TestInterventionalNotInverted:
    """A normal interventional trial: disease-presence inclusion is satisfied
    when the disease is present. This documents the baseline and must stay green."""

    def test_interventional_disease_inclusion_true_is_satisfied(self):
        # "Patient must have disease X" (inclusion), disease present (predicate TRUE)
        out = OutcomeEvaluator.evaluate(TriState.TRUE, "inclusion", "hard")
        assert out == Outcome.SATISFIED

    def test_interventional_disease_inclusion_false_is_disqualifier(self):
        # disease absent (predicate FALSE) → hard inclusion fails
        out = OutcomeEvaluator.evaluate(TriState.FALSE, "inclusion", "hard")
        assert out == Outcome.RESOLVED_DISQUALIFIER


# --- Oracle: HV trials MUST invert disease logic (fails until implemented) ----

class TestHealthyVolunteerInversion:
    """§7.2: for a healthy-volunteer trial, a disease-presence inclusion inverts —
    disease PRESENT becomes disqualifying, disease ABSENT becomes satisfied.

    Expressed against the intended interface: OutcomeEvaluator.evaluate(...,
    healthy_volunteers=True). Until that parameter exists and inverts, these
    xfail (a TypeError on the unknown kwarg counts as an expected failure)."""

    @pytest.mark.xfail(strict=True, reason="§7.2 HV inversion not implemented (behaviors.py stub)")
    def test_hv_disease_presence_is_disqualifying(self):
        # Disease inclusion, patient HAS the disease (predicate TRUE).
        # Under HV inversion, presence of significant disease disqualifies.
        out = OutcomeEvaluator.evaluate(
            TriState.TRUE, "inclusion", "hard", healthy_volunteers=True
        )
        assert out == Outcome.RESOLVED_DISQUALIFIER

    @pytest.mark.xfail(strict=True, reason="§7.2 HV inversion not implemented (behaviors.py stub)")
    def test_hv_disease_absence_is_satisfied(self):
        # Disease inclusion, patient does NOT have the disease (predicate FALSE).
        # Under HV inversion, absence of significant disease satisfies.
        out = OutcomeEvaluator.evaluate(
            TriState.FALSE, "inclusion", "hard", healthy_volunteers=True
        )
        assert out == Outcome.SATISFIED

    @pytest.mark.xfail(strict=True, reason="§7.2 HV inversion not implemented (behaviors.py stub)")
    def test_hv_unknown_still_never_hard_outcome(self):
        # Invariant preserved under inversion: UNKNOWN never becomes a hard outcome.
        out = OutcomeEvaluator.evaluate(
            TriState.UNKNOWN, "inclusion", "hard", healthy_volunteers=True
        )
        assert out == Outcome.UNRESOLVED


# --- Oracle: observational studies must be labeled not-candidacy --------------

class TestObservationalNotCandidacy:
    """§7.2: observational/analytical studies are not treatment candidacy and
    MUST be labeled as such — not ranked beside interventional trials."""

    def test_observational_flagged(self):
        # The arm result must at minimum carry the observational label (implemented).
        result = PerArmMatcher.evaluate_arm(
            arm_id="A", study_type="observational", criteria=[], criterion_results=[],
        )
        assert result["is_observational"] is True

    @pytest.mark.xfail(
        strict=True,
        reason="§7.2 observational 'not treatment candidacy' label not yet a distinct output",
    )
    def test_observational_marked_not_candidacy(self):
        # Intended: a dedicated candidacy flag so a consumer cannot rank an
        # observational study as a treatment option.
        result = PerArmMatcher.evaluate_arm(
            arm_id="A", study_type="observational", criteria=[], criterion_results=[],
        )
        assert result["is_treatment_candidacy"] is False
