"""Python-native projection of protocol 23.1 ``DirectionValue`` arrays."""

from __future__ import annotations

import math
from typing import TypeAlias

from .connection import McRemoteError


DirectionValue: TypeAlias = tuple[int | float, int | float, int | float]
DIRECTION_NORM_TOLERANCE = 1.5e-6


def decode_direction_value(value, where="direction result") -> DirectionValue:
    """Validate a canonical server result without rounding or normalizing it."""

    if not isinstance(value, list) or len(value) != 3:
        raise McRemoteError(f"{where} must be a three-number array")
    parsed = []
    for index, item in enumerate(value):
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
        ):
            raise McRemoteError(f"{where}[{index}] must be a finite number")
        parsed.append(item)
    if abs(math.hypot(*parsed) - 1.0) > DIRECTION_NORM_TOLERANCE:
        raise McRemoteError(
            f"{where} must have a norm within {DIRECTION_NORM_TOLERANCE} of 1"
        )
    return parsed[0], parsed[1], parsed[2]


__all__ = [
    "DIRECTION_NORM_TOLERANCE",
    "DirectionValue",
    "decode_direction_value",
]
