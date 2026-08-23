"""Protocol 22 DimensionKey and build-context validation."""

from __future__ import annotations

import re

from .connection import McRemoteError


_NAMESPACE = re.compile(r"^[a-z0-9_.-]+$")
_PATH = re.compile(r"^[a-z0-9/._-]+$")


def is_dimension_key(value) -> bool:
    """Return whether *value* is a fully-qualified canonical DimensionKey."""

    if not isinstance(value, str) or value.count(":") != 1:
        return False
    namespace, path = value.split(":", 1)
    return (
        _NAMESPACE.fullmatch(namespace) is not None
        and _PATH.fullmatch(path) is not None
    )


def is_dimension_ref(value) -> bool:
    """Return whether *value* is a protocol 22 DimensionRef.

    Unqualified refs are Minecraft paths. Qualified refs use the same strict
    grammar as canonical server output. The client does not trim, case-fold,
    alias, or otherwise normalize either form.
    """

    if not isinstance(value, str):
        return False
    if ":" in value:
        return is_dimension_key(value)
    return _PATH.fullmatch(value) is not None


def require_dimension_key(value, where="dimension") -> str:
    if not is_dimension_key(value):
        raise McRemoteError(f"{where} must be a fully-qualified DimensionKey")
    return value


def require_dimension_ref(value, where="dimension") -> str:
    if not is_dimension_ref(value):
        raise ValueError(f"{where} must be a DimensionRef")
    return value


def _origin(value, where) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise McRemoteError(f"{where} must be a three-integer array")
    parsed = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise McRemoteError(f"{where}[{index}] must be an integer")
        parsed.append(item)
    return tuple(parsed)


def decode_build_context(
    value, where="build context"
) -> tuple[str, tuple[int, int, int]]:
    """Decode exact ``{dimension, origin}`` server output."""

    if not isinstance(value, dict):
        raise McRemoteError(f"{where} must be an object")
    if set(value) != {"dimension", "origin"}:
        raise McRemoteError(f"{where} has an invalid field set")
    dimension = require_dimension_key(value["dimension"], f"{where}.dimension")
    origin = _origin(value["origin"], f"{where}.origin")
    return dimension, origin


__all__ = [
    "decode_build_context",
    "is_dimension_key",
    "is_dimension_ref",
    "require_dimension_key",
    "require_dimension_ref",
]
