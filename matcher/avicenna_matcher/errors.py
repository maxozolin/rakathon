"""Error types for avicenna.matcher/0.1

CRITICAL DISTINCTION:
- StructuralError: A1 — pre-validated structure is broken (assert-and-abort).
- Evaluation returns TriState.UNKNOWN (never raises) for missing/ambiguous/out-of-scope evidence.
These must NEVER be conflated.
"""


class StructuralError(Exception):
    """
    Raised when the input (CriteriaPack, patient packet, or context) violates
    a structural constraint (A1 — pre-validated structure assumption).
    
    This is an assert-and-abort condition, not an eligibility outcome.
    """
    pass


class ValidationError(StructuralError):
    """Raised when schema validation fails"""
    pass


class ReferencingError(StructuralError):
    """Raised when a reference is dangling or cyclic (A3 violation)"""
    pass


class ConceptError(StructuralError):
    """Raised when a concept is unmapped/unsupported at load-time (A4 violation)"""
    pass
