"""Types and enums for avicenna.matcher/0.1"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, List, Union


class TriState(Enum):
    """K3 (Kleene) three-valued logic: {TRUE, FALSE, UNKNOWN}"""
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"

    def __bool__(self) -> bool:
        """For convenience in boolean contexts"""
        if self == TriState.TRUE:
            return True
        elif self == TriState.FALSE:
            return False
        else:
            raise ValueError("Cannot convert UNKNOWN to bool")


class FactState(Enum):
    """State of a clinical fact in the patient packet"""
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_TESTED = "not_tested"
    INDETERMINATE = "indeterminate"
    CONFLICT = "conflict"


class FactAssertion(Enum):
    """Assertion type for a fact (§PATIENT_MATCHING_FORMAT_STANDARD)"""
    POSITIVE = "positive"
    EXPLICIT_NEGATIVE = "explicit_negative"
    SUSPECTED = "suspected"
    HISTORICAL = "historical"
    NOT_APPLICABLE = "not_applicable"


class SubjectScope(Enum):
    """Subject scope of a fact"""
    PATIENT = "patient"
    FAMILY = "family"
    OTHER = "other"
    UNCERTAIN = "uncertain"


class ReviewStatus(Enum):
    """Review status of a fact"""
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class VerificationStatus(Enum):
    """Verification/authority status for §4.6 authority tiebreaking.
    
    Used in evidence resolution: how certain/authoritative is this fact?
    - reviewed: verified by domain expert or validated system process
    - source_assertion: asserted directly by structured source
    - extracted_candidate: extracted by algorithm, not yet verified
    """
    REVIEWED = "reviewed"
    SOURCE_ASSERTION = "source_assertion"
    EXTRACTED_CANDIDATE = "extracted_candidate"


class EvaluationState(Enum):
    """Result state for a criterion evaluation (§8.1)
    
    - evaluable: resolved to true/false
    - missing: required evidence absent
    - stale: evidence time-incompatible with anchor/window
    - conflict: contradictory evidence
    - unsupported: unit/scale/concept not validated
    - not_applicable: out of scope for this patient × arm
    - opaque: arrived as opaque_text
    - manual_review: needs human interpretation
    """
    EVALUABLE = "evaluable"
    MISSING = "missing"
    STALE = "stale"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"
    OPAQUE = "opaque"
    MANUAL_REVIEW = "manual_review"


class EligibilityState(Enum):
    """Trial-level eligibility state per arm (§8.1)
    
    Possible values: ineligible | eligible_pending_review | needs_chart_review | manual_review
    
    There is NO bare "eligible" — that is a post-human-review product state, never emitted by the matcher.
    """
    INELIGIBLE = "ineligible"
    ELIGIBLE_PENDING_REVIEW = "eligible_pending_review"
    NEEDS_CHART_REVIEW = "needs_chart_review"
    MANUAL_REVIEW = "manual_review"


class Hardness(Enum):
    """Hardness of a criterion (§6, dropped `soft`)
    
    - hard: must satisfy for eligibility
    - procedural_pre_screen: pre-screening workflow step, non-blocking
    """
    HARD = "hard"
    PROCEDURAL_PRE_SCREEN = "procedural_pre_screen"


class Outcome(Enum):
    """Outcome of a criterion evaluation (§8.2, after polarity applied)
    
    - satisfied: inclusion criterion TRUE
    - resolved_disqualifier: hard inclusion FALSE or hard exclusion TRUE (blocks)
    - clear: exclusion criterion FALSE (patient not excluded)
    - unresolved: hard criterion result is UNKNOWN
    - non_blocking: procedural_pre_screen not positively resolved (never blocks)
    - not_applicable: criterion not applicable to this patient × arm
    """
    SATISFIED = "satisfied"
    RESOLVED_DISQUALIFIER = "resolved_disqualifier"
    CLEAR = "clear"
    UNRESOLVED = "unresolved"
    NON_BLOCKING = "non_blocking"
    NOT_APPLICABLE = "not_applicable"


class NormalizationStatus(Enum):
    """Normalization status for a quantity value (§A5)
    
    - validated: unit was validated and normalized to standard
    - unmapped: unit not in the system's mapping
    - unsupported: unit/scale not supported for comparison
    """
    VALIDATED = "validated"
    UNMAPPED = "unmapped"
    UNSUPPORTED = "unsupported"


@dataclass
class TriStateValue:
    """Wraps TriState with a reason_code for UNKNOWN results"""
    value: TriState
    reason_code: Optional[str] = None

    def is_hard_outcome(self) -> bool:
        """Returns True if this is a hard pass or fail (not UNKNOWN)"""
        return self.value in (TriState.TRUE, TriState.FALSE)


@dataclass
class TimePoint:
    """A point in time (ISO 8601)"""
    timestamp: str  # RFC 3339


@dataclass
class TimeInterval:
    """A time interval"""
    start: Optional[TimePoint]
    end: Optional[TimePoint]


@dataclass
class Quantity:
    """A measured quantity with unit and normalization status"""
    value: float
    unit: str
    normalization_status: Union[NormalizationStatus, str]  # NormalizationStatus enum or string for flexibility


@dataclass
class CodedValue:
    """A coded/concept value"""
    system: str  # e.g., "SNOMED", "ICD-10", "ATC"
    code: str
    display: Optional[str] = None


@dataclass
class BandValue:
    """An age or similar band (unordered set)"""
    lower_inclusive: Optional[int] = None
    upper_inclusive: Optional[int] = None


# Marker for fact values
AnyFactValue = Any  # Could be Quantity, CodedValue, BandValue, bool, str, etc.
