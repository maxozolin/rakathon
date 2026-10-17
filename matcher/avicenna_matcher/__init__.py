"""Avicenna hospital-side matcher (avicenna.matcher/0.1)

A deterministic, offline Python library for evaluating patient packets against
trial criteria packs and emitting per-criterion eligibility results.
"""

__version__ = "0.1.0"

from .errors import StructuralError, ValidationError, ReferencingError, ConceptError
from .types import (
    TriState,
    TriStateValue,
    FactState,
    FactAssertion,
    SubjectScope,
    ReviewStatus,
    VerificationStatus,
    EvaluationState,
    EligibilityState,
    Hardness,
    Outcome,
    NormalizationStatus,
    TimePoint,
    TimeInterval,
    Quantity,
    CodedValue,
    BandValue,
)
from .validator import validate, validate_packet_facts, validate_state_assertion_consistency
from .concepts import ConceptRegistry, SEED_REGISTRY_V1, validate_concept_membership
from .resolution import (
    resolve_fact_for_criterion,
    resolve_facts_for_criterion,
)
from .predicates import (
    RelativeThresholdEvaluator,
    DerivedValueEvaluator,
    GuardedPredicateEvaluator,
    NotExistsEvaluator,
)
from .outcome import OutcomeEvaluator
from .aggregate import PerArmAggregator, TrialAggregator, CriterionResultBuilder, TrialResultBuilder
from .behaviors import PerArmMatcher
from .pipeline import evaluate, dependency_order, CycleError
from .explain import REASON_CODES, registry_document
from .cli import run_matcher

__all__ = [
    "TriState",
    "TriStateValue",
    "FactState",
    "FactAssertion",
    "SubjectScope",
    "ReviewStatus",
    "VerificationStatus",
    "EvaluationState",
    "EligibilityState",
    "Hardness",
    "Outcome",
    "NormalizationStatus",
    "TimePoint",
    "TimeInterval",
    "Quantity",
    "CodedValue",
    "BandValue",
    "StructuralError",
    "ValidationError",
    "ReferencingError",
    "ConceptError",
    "validate",
    "validate_packet_facts",
    "validate_state_assertion_consistency",
    "ConceptRegistry",
    "SEED_REGISTRY_V1",
    "validate_concept_membership",
    "resolve_fact_for_criterion",
    "resolve_facts_for_criterion",
    "RelativeThresholdEvaluator",
    "DerivedValueEvaluator",
    "GuardedPredicateEvaluator",
    "NotExistsEvaluator",
    "OutcomeEvaluator",
    "PerArmAggregator",
    "TrialAggregator",
    "CriterionResultBuilder",
    "TrialResultBuilder",
    "PerArmMatcher",
    "evaluate",
    "dependency_order",
    "CycleError",
    "REASON_CODES",
    "registry_document",
    "run_matcher",
]
