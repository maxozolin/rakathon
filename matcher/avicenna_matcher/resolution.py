"""Evidence resolution policy for avicenna.matcher

§4 order: applicability → subject/assertion → time compat → precision → 
aggregation → authority/recency → conflict

This module implements the ordering rules for selecting the most-relevant Fact
from a patient packet to evaluate against a criterion.
"""

from typing import Optional, List
from datetime import datetime, timezone
from .types import TriState, FactAssertion, ReviewStatus, VerificationStatus


def parse_time(value) -> Optional[datetime]:
    """Normalise a schema time (RFC 3339 str, TimePoint, TimeInterval, datetime) to naive UTC.

    For a TimeInterval the end bound is used (latest point the assertion held);
    an open-ended interval falls back to its start.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        if "timestamp" in value:
            return parse_time(value["timestamp"])
        if "start" in value or "end" in value:
            return parse_time(value.get("end")) or parse_time(value.get("start"))
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    return None


_REVIEW_TO_VERIFICATION = {
    "reviewed": VerificationStatus.REVIEWED,
    "unreviewed": VerificationStatus.EXTRACTED_CANDIDATE,
    "source_assertion": VerificationStatus.SOURCE_ASSERTION,
    "extracted_candidate": VerificationStatus.EXTRACTED_CANDIDATE,
}


def _verification(fact: dict) -> VerificationStatus:
    return _REVIEW_TO_VERIFICATION.get(
        fact.get("review_status"), VerificationStatus.EXTRACTED_CANDIDATE
    )


def _assertion(fact: dict) -> Optional[FactAssertion]:
    raw = fact.get("assertion", "positive")
    if raw is None:
        return None
    try:
        return FactAssertion(raw)
    except ValueError:
        return None


def is_fact_applicable(
    fact_key: str,
    predicate_fact_key: str,
) -> bool:
    """
    Step 1: Applicability — the fact_key matches the predicate's required fact_key.
    
    Args:
        fact_key: The fact's key from the patient packet
        predicate_fact_key: The fact_key required by the predicate
    
    Returns: bool
    """
    # Simple equality for now; could support concept subsumption later
    return fact_key == predicate_fact_key


def is_assertion_compatible(
    assertion: FactAssertion,
    predicate_assertion_scope: Optional[set[FactAssertion]] = None,
) -> bool:
    """
    Step 2: Subject/Assertion — the fact's assertion aligns with the predicate.
    
    Args:
        assertion: The fact's assertion (positive, explicit_negative, suspected, historical)
        predicate_assertion_scope: Set of acceptable assertions for the predicate.
                                   If None, all are acceptable (default: all).
    
    Returns: bool
    
    Note: A predicate can be scoped to, e.g., only explicit_negative facts for not_exists;
    or to positive assertions for normal inclusion/exclusion criteria.
    """
    if predicate_assertion_scope is None:
        # Default: all assertions are compatible
        return True
    return assertion is not None and assertion in predicate_assertion_scope


def is_time_compatible(
    effective_time: Optional[datetime],
    predicate_relation: str,  # "current", "at_screening", "any_history", "within_days_before_anchor"
    anchor_time: Optional[datetime] = None,
    window_days: Optional[int] = None,
) -> bool:
    """
    Step 3: Time compatibility — the fact's effective_time fits the predicate's temporal scope.
    
    Args:
        effective_time: The fact's effective_time (when the fact was observed/reported)
        predicate_relation: The temporal relation of the predicate
                           ("current", "at_screening", "any_history", "within_days_before_anchor")
        anchor_time: Reference time for point-in-time or windowed predicates (e.g., screening date)
        window_days: For windowed predicates, the window width in days before anchor
    
    Returns: bool
    
    Note: For "any_history", always True (any time is compatible).
    For "current" or "at_screening", the fact must have an effective_time.
    For windowed relations, the fact must fall within the window.
    """
    if predicate_relation == "any_history":
        return True
    
    if effective_time is None:
        return predicate_relation == "any_history"
    
    if predicate_relation in ("current", "at_screening"):
        # Any fact with a time is compatible; we'll use recency to pick the latest
        return True
    
    if predicate_relation == "within_days_before_anchor":
        if anchor_time is None or window_days is None:
            # Missing anchor info; cannot determine window
            return False
        time_delta = (anchor_time - effective_time).days
        return 0 <= time_delta <= window_days
    
    # Unknown relation; conservative: not compatible
    return False


def fact_precision(
    effective_time: Optional[datetime],
    recorded_time: Optional[datetime],
) -> int:
    """
    Step 4: Precision tiebreaker — later effective times (more recent) are preferred.
    
    Returns an integer score for sorting; higher = more recent = higher priority.
    
    (Precision here means "how narrowly pinned is the time" — point-in-time > windowed.
    For simplicity, we use effective_time as the precision proxy.)
    """
    if effective_time is None:
        return 0
    # Full-resolution recency: truncating to days would let an older same-day fact
    # outrank a newer one on authority alone.
    delta = effective_time - datetime(1970, 1, 1)
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def fact_authority_score(
    verification_status: VerificationStatus,
    source_kind: str,  # "structured", "lab", "administration", "prescription", "narrative"
) -> int:
    """
    Step 6: Authority tiebreaker — used only among facts with equal recency.
    
    Scoring:
    - verification_status: reviewed (3) > source_assertion (2) > extracted_candidate (1)
    - source_kind: structured/lab (3) > admin/prescription (2) > narrative (1)
    
    Args:
        verification_status: The fact's review/verification status
        source_kind: How the fact was sourced
    
    Returns: int (higher = more authoritative)
    """
    verification_score = {
        VerificationStatus.REVIEWED: 3,
        VerificationStatus.SOURCE_ASSERTION: 2,
        VerificationStatus.EXTRACTED_CANDIDATE: 1,
    }.get(verification_status, 0)
    
    source_score = {
        "structured": 3,
        "lab": 3,
        "administration": 2,
        "prescription": 2,
        "narrative": 1,
    }.get(source_kind, 0)
    
    return verification_score + source_score


def select_fact_for_point_predicate(
    compatible_facts: List[dict],
    predicate_relation: str,  # "current" or "at_screening"
) -> Optional[dict]:
    """
    Select a single fact for a point-in-time predicate (current/at_screening).
    
    §4.6 Rule: **Recency dominates; authority only breaks ties among contemporaneous facts.**
    
    Args:
        compatible_facts: List of facts that passed applicability, assertion, and time checks
        predicate_relation: Must be "current" or "at_screening"
    
    Returns: The selected fact, or None if no compatible facts
    
    Algorithm:
    1. Sort by effective_time (descending = most recent first)
    2. Among facts with the same effective_time, sort by authority
    3. Return the first (most recent, highest authority)
    """
    if not compatible_facts:
        return None
    
    # Sort by effective_time (descending), then by authority (descending)
    def sort_key(fact):
        eff_time = parse_time(fact.get("effective_time"))
        eff_time_score = fact_precision(eff_time, parse_time(fact.get("recorded_time")))
        
        verification = _verification(fact)
        source_kind = fact.get("source_kind", "narrative")
        authority = fact_authority_score(verification, source_kind)
        
        # Sort descending: (-precision, -authority)
        return (-eff_time_score, -authority)
    
    sorted_facts = sorted(compatible_facts, key=sort_key)
    return sorted_facts[0]


def select_facts_for_existential_predicate(
    compatible_facts: List[dict],
    predicate_relation: str,  # "any_history" or windowed
) -> List[dict]:
    """
    Select all compatible facts for an existential predicate (any_history/windowed).
    
    §4.6 Rule: For existential relations, **recency is irrelevant**; all compatible facts
    are considered. Authority is used only when a single fact needs to assert existence
    (e.g., for not_exists, does any compatible fact explicitly assert absence).
    
    Args:
        compatible_facts: List of facts that passed applicability, assertion, and time checks
        predicate_relation: Must be "any_history" or a windowed relation
    
    Returns: List of all compatible facts (for folding/aggregation)
    """
    # For existential relations, return all compatible facts in authority order
    # (authority determines which single fact, if any, can assert the existence)
    def sort_key(fact):
        verification = _verification(fact)
        source_kind = fact.get("source_kind", "narrative")
        authority = fact_authority_score(verification, source_kind)
        return -authority  # Higher authority first
    
    return sorted(compatible_facts, key=sort_key)


def _compatible_facts(
    facts: List[dict],
    criterion_fact_key: str,
    predicate_relation: str,
    predicate_assertion_scope: Optional[set[FactAssertion]],
    anchor_time: Optional[datetime],
    window_days: Optional[int],
) -> List[dict]:
    """§4 steps 1–3: applicability, subject/assertion, time compatibility.

    Rejected facts and facts about someone other than the patient never feed a
    patient criterion.
    """
    anchor_time = parse_time(anchor_time)
    compatible = []
    for fact in facts:
        if not is_fact_applicable(fact.get("fact_key"), criterion_fact_key):
            continue
        if fact.get("review_status") == "rejected":
            continue
        if fact.get("subject_scope", "patient") != "patient":
            continue
        if not is_assertion_compatible(_assertion(fact), predicate_assertion_scope):
            continue
        eff_time = parse_time(fact.get("effective_time"))
        if not is_time_compatible(eff_time, predicate_relation, anchor_time, window_days):
            continue
        compatible.append(fact)
    return compatible


def resolve_fact_for_criterion(
    facts: List[dict],
    criterion_fact_key: str,
    predicate_relation: str,
    predicate_assertion_scope: Optional[set[FactAssertion]] = None,
    anchor_time: Optional[datetime] = None,
    window_days: Optional[int] = None,
) -> Optional[dict]:
    """
    Full §4 resolution pipeline: filter and select the best fact for a criterion.
    
    This is the high-level API that applies the entire ordering (steps 1–6):
    1. Applicability (fact_key match)
    2. Assertion compatibility
    3. Time compatibility
    4. Precision (part of tiebreaker)
    5. Aggregation (all compatible for existential; one best for point)
    6. Authority/recency selection
    
    Args:
        facts: List of facts from the patient packet
        criterion_fact_key: The fact_key required by the criterion
        predicate_relation: "current", "at_screening", "any_history", or windowed
        predicate_assertion_scope: Set of acceptable assertions (None = all)
        anchor_time: Reference time for time compatibility checks
        window_days: Window width for windowed relations
    
    Returns: The selected fact for a point predicate, or None if no compatible facts.
             For existential predicates, use resolve_facts_for_criterion() instead.
    """
    # Step 1–3: Filter for compatible facts
    compatible_facts = _compatible_facts(
        facts, criterion_fact_key, predicate_relation,
        predicate_assertion_scope, anchor_time, window_days,
    )
    
    # Steps 4–6: Select best fact
    if predicate_relation in ("current", "at_screening"):
        return select_fact_for_point_predicate(compatible_facts, predicate_relation)
    else:
        # For existential/windowed, return first (highest authority) compatible fact
        # (caller should use resolve_facts_for_criterion() for full list)
        return select_facts_for_existential_predicate(compatible_facts, predicate_relation)[0] if compatible_facts else None


def resolve_facts_for_criterion(
    facts: List[dict],
    criterion_fact_key: str,
    predicate_relation: str,
    predicate_assertion_scope: Optional[set[FactAssertion]] = None,
    anchor_time: Optional[datetime] = None,
    window_days: Optional[int] = None,
) -> List[dict]:
    """
    Full §4 resolution for existential predicates: return all compatible facts.
    
    Args:
        facts: List of facts from the patient packet
        criterion_fact_key: The fact_key required by the criterion
        predicate_relation: "any_history" or a windowed relation
        predicate_assertion_scope: Set of acceptable assertions (None = all)
        anchor_time: Reference time for time compatibility checks
        window_days: Window width for windowed relations
    
    Returns: List of all compatible facts, sorted by authority (descending)
    """
    # Step 1–3: Filter for compatible facts
    compatible_facts = _compatible_facts(
        facts, criterion_fact_key, predicate_relation,
        predicate_assertion_scope, anchor_time, window_days,
    )
    
    # Step 5–6: Return all, sorted by authority
    return select_facts_for_existential_predicate(compatible_facts, predicate_relation)
