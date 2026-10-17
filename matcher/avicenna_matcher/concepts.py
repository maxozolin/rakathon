"""Concept registry for avicenna.matcher

§5.4 Coverage-aware `not_exists`: requires validated, versioned concept membership
to determine if a queried agent/class is subsumed by an asserted coverage class.

Membership is **pinned to an ontology version** to ensure reproducibility.
Unknown or unvalidated mappings return UNKNOWN (never assumed member or non-member).
"""

from typing import Optional, Set
from dataclasses import dataclass
from .types import TriState


@dataclass(frozen=True)
class ConceptRegistry:
    """Pinned concept registry with version stamp.
    
    Maps agent/class names to membership sets under a specific ontology version.
    All membership checks respect the pinned version; querying outside the registry
    returns UNKNOWN (conservative: unknown mappings cannot affirm or deny membership).
    """
    version: str  # e.g., "SNOMED-CT/2023-01-15"
    
    # Class membership: { 'class_name': {'member1', 'member2', ...} }
    # For SNOMED concepts, keys are display names or codes
    memberships: dict[str, Set[str]]
    
    def is_member(self, agent: str, concept_class: str) -> TriState:
        """
        Check if agent is a member of concept_class.
        
        Returns:
        - TRUE if agent is in the registered members of concept_class
        - FALSE if agent is explicitly not in it (class exists but agent not listed)
        - UNKNOWN if the class is not registered (unvalidated mapping)
        
        Args:
            agent: The agent/code to check (e.g., "elacestrant", "SNOMED:12345")
            concept_class: The class/category (e.g., "SERD", "toxicity_grade_3_plus")
        
        Returns: TriState
        """
        if concept_class not in self.memberships:
            # Unvalidated mapping: unknown membership
            return TriState.UNKNOWN
        
        members = self.memberships[concept_class]
        if agent in members:
            return TriState.TRUE
        else:
            return TriState.FALSE
    
    def get_coverage_members(self, concept_class: str) -> Optional[Set[str]]:
        """Get the registered members of a concept class, or None if unvalidated."""
        return self.memberships.get(concept_class)


# Pinned seed registry for pilot specialties (oncology, cardio/resp, renal)
# Version: hypothetical snapshot for testing; actual registry would be SNOMED CT or similar
SEED_REGISTRY_V1 = ConceptRegistry(
    version="avicenna-seed/1.0.0",
    memberships={
        # SERDs (Selective Estrogen Receptor Degraders)
        "SERD": {
            "elacestrant",
            "SNOMED:12345",  # hypothetical SNOMED code for elacestrant
            "AZD9496",
            "SNOMED:12346",
        },
        # Hormone receptor positive breast cancer settings
        "hr_positive_bc_setting": {
            "advanced",
            "metastatic",
            "recurrent",
        },
        # Toxicity grades (CTCAE)
        "grade_3_plus_toxicity": {
            "grade_3",
            "grade_4",
            "grade_5",
        },
        # Cardiac events
        "cardiac_event": {
            "myocardial_infarction",
            "MI",
            "SNOMED:54329005",
            "heart_failure",
            "HF",
        },
        # Kidney disease stages
        "ckd_stage_4_plus": {
            "stage_4",
            "stage_5",
            "ESRD",
            "end_stage_renal_disease",
        },
    },
)


def validate_concept_membership(
    agent: str,
    concept_class: str,
    registry: Optional[ConceptRegistry] = None,
) -> TriState:
    """
    Validate if an agent belongs to a concept class using a pinned registry.
    
    Args:
        agent: The agent to check
        concept_class: The class to check membership in
        registry: The ConceptRegistry to use (defaults to SEED_REGISTRY_V1)
    
    Returns: TriState (TRUE, FALSE, or UNKNOWN for unvalidated mappings)
    """
    if registry is None:
        registry = SEED_REGISTRY_V1
    
    return registry.is_member(agent, concept_class)
