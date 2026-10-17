"""K3 (Kleene strong three-valued) logic for avicenna.matcher

§3.1: Implements TRUE, FALSE, UNKNOWN with Kleene semantics:
- AND (all): FALSE if any FALSE; else UNKNOWN if any UNKNOWN; else TRUE
- OR (any): TRUE if any TRUE; else UNKNOWN if any UNKNOWN; else FALSE
- NOT: swaps TRUE/FALSE; UNKNOWN is fixed

The flood-relief rule falls out for free: any() with one TRUE is TRUE
regardless of unknown siblings.
"""

from typing import Sequence
from .types import TriState


def k3_and(*values: TriState) -> TriState:
    """
    Kleene AND (all): FALSE if any FALSE; else UNKNOWN if any UNKNOWN; else TRUE.
    For sequence input, use k3_all() instead.
    """
    if not values:
        return TriState.TRUE

    for v in values:
        if v == TriState.FALSE:
            return TriState.FALSE

    for v in values:
        if v == TriState.UNKNOWN:
            return TriState.UNKNOWN

    return TriState.TRUE


def k3_or(*values: TriState) -> TriState:
    """
    Kleene OR (any): TRUE if any TRUE; else UNKNOWN if any UNKNOWN; else FALSE.
    Flood-relief rule: if any value is TRUE, the result is TRUE regardless of UNKNOWNs.
    For sequence input, use k3_any() instead.
    """
    if not values:
        return TriState.FALSE

    for v in values:
        if v == TriState.TRUE:
            return TriState.TRUE

    for v in values:
        if v == TriState.UNKNOWN:
            return TriState.UNKNOWN

    return TriState.FALSE


def k3_not(value: TriState) -> TriState:
    """Kleene NOT: swaps TRUE/FALSE; UNKNOWN is fixed."""
    if value == TriState.TRUE:
        return TriState.FALSE
    elif value == TriState.FALSE:
        return TriState.TRUE
    else:  # UNKNOWN
        return TriState.UNKNOWN


def k3_all(values: Sequence[TriState]) -> TriState:
    """AND over a sequence."""
    return k3_and(*values)


def k3_any(values: Sequence[TriState]) -> TriState:
    """OR over a sequence."""
    return k3_or(*values)
