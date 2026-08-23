"""Protocol 22 structured block values.

``BlockSpec`` is represented on the public Python input surface by the
``block_id`` and ``state`` arguments accepted by ``Minecraft.setBlock`` and
``Minecraft.setBlocks``.  ``BlockValue`` is the immutable output returned by
``Minecraft.getBlock`` and contained in the tuple from ``Minecraft.getBlocks``.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Generic, TypeAlias, TypeVar

from .connection import McRemoteError


StateScalar: TypeAlias = str | int | float | bool
_StateT = TypeVar("_StateT")
_SHORT_BLOCK_ID = re.compile(r"^[a-z0-9/._-]+$")
_QUALIFIED_BLOCK_ID = re.compile(r"^[a-z0-9_.-]+:[a-z0-9/._-]+$")


class BlockId(Generic[_StateT]):
    """Static-only link between a generated block ID and its state shape.

    Generated ``mc_constants.pyi`` files annotate normal string constants as
    ``BlockId[SomeState]``. At runtime those constants remain ordinary strings;
    this deliberately opaque static marker prevents an invalid state from
    falling through to the API's dynamic-string overload.
    """


def _is_block_id(value, *, require_namespace):
    if not isinstance(value, str) or not value:
        return False
    if require_namespace:
        return _QUALIFIED_BLOCK_ID.fullmatch(value) is not None
    return (
        _QUALIFIED_BLOCK_ID.fullmatch(value) is not None
        or _SHORT_BLOCK_ID.fullmatch(value) is not None
    )


def _is_state_scalar(value):
    if type(value) is bool:
        return True
    if type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    return type(value) is str


def _normalize_state(state, *, where):
    if state is None:
        return {}
    if not isinstance(state, Mapping):
        raise TypeError(f"{where} must be a mapping or None")

    property_names = list(state)
    if any(not isinstance(name, str) or not name for name in property_names):
        raise TypeError(f"{where} property names must be non-empty strings")

    normalized = {}
    for property_name in sorted(property_names):
        value = state[property_name]
        if not _is_state_scalar(value):
            raise TypeError(
                f"{where}[{property_name!r}] must be a finite JSON scalar "
                "(boolean, number, or string)"
            )
        normalized[property_name] = value
    return normalized


class FrozenState(Mapping[str, StateScalar]):
    """Small immutable mapping used by :class:`BlockValue`.

    Its representation intentionally looks like a normal ``dict`` so the
    first learner-facing ``print(value.state)`` remains unsurprising.
    """

    __slots__ = ("_values",)

    def __init__(self, values):
        self._values = MappingProxyType(dict(values))

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return repr(dict(self._values))

    def __eq__(self, other):
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return NotImplemented


@dataclass(frozen=True)
class BlockValue:
    """Immutable canonical block snapshot returned by block getters.

    ``block_id`` is fully qualified and ``state`` contains the full server
    state.  Blocks with no state properties use an empty ``FrozenState``.
    """

    block_id: str
    state: Mapping[str, StateScalar]

    def __post_init__(self):
        if not _is_block_id(self.block_id, require_namespace=True):
            raise ValueError(
                "BlockValue.block_id must be a fully-qualified namespace:path"
            )
        normalized = _normalize_state(self.state, where="BlockValue.state")
        object.__setattr__(self, "state", FrozenState(normalized))


def block_spec(block_id, state=None):
    """Build the exact protocol 22 ``BlockSpec`` wire object."""
    if not _is_block_id(block_id, require_namespace=False):
        raise ValueError(
            "block_id must be a vanilla short ID or fully-qualified namespace:path"
        )
    return {
        "block_id": block_id,
        "state": _normalize_state(state, where="state"),
    }


def decode_block_value(value) -> BlockValue:
    """Decode and strictly validate one protocol 22 ``BlockValue`` result."""
    if not isinstance(value, dict):
        raise McRemoteError("world.getBlock result must be a BlockValue object")
    if set(value) != {"block_id", "state"}:
        raise McRemoteError(
            "world.getBlock result must contain exactly block_id and state"
        )
    if not isinstance(value["state"], dict):
        raise McRemoteError("world.getBlock result.state must be an object")
    try:
        return BlockValue(value["block_id"], value["state"])
    except (TypeError, ValueError) as exc:
        raise McRemoteError(f"invalid world.getBlock BlockValue: {exc}") from exc


__all__ = ["BlockId", "BlockValue", "FrozenState", "StateScalar"]
